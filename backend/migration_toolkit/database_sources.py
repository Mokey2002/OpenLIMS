import contextlib
import hashlib
import json
import os
import re
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

from .models import MigrationDatabaseConnection


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def validate_identifier(value, label="identifier", allow_blank=False):
    value = str(value or "").strip()
    if not value and allow_blank:
        return value
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValidationError(f"Invalid {label}: {value!r}.")
    return value


def _allowed_hosts():
    configured = getattr(settings, "MIGRATION_DB_ALLOWED_HOSTS", [])
    if isinstance(configured, str):
        configured = configured.split(",")
    return {str(item).strip().lower() for item in configured if str(item).strip()}


def validate_connection_config(source):
    if not source.active:
        raise ValidationError("This migration database connection is inactive.")

    if source.engine == MigrationDatabaseConnection.ENGINE_SQLITE:
        root = Path(
            getattr(
                settings,
                "MIGRATION_SQLITE_ROOT",
                settings.BASE_DIR / "migration_sources",
            )
        ).resolve()
        candidate = Path(source.database_name)
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValidationError(
                "SQLite migration files must be inside MIGRATION_SQLITE_ROOT."
            ) from exc
        if not candidate.is_file():
            raise ValidationError("SQLite migration source does not exist.")
        return candidate

    host = str(source.host or "").strip().lower()
    if not host:
        raise ValidationError("A database host is required.")
    allowed_hosts = _allowed_hosts()
    if not allowed_hosts or host not in allowed_hosts:
        raise ValidationError(
            "Source host is not in MIGRATION_DB_ALLOWED_HOSTS."
        )
    if not source.username:
        raise ValidationError("A read-only database username is required.")
    if not source.password_env_var:
        raise ValidationError("A password environment variable is required.")
    if not os.getenv(source.password_env_var):
        raise ValidationError(
            f"Environment variable {source.password_env_var} is not configured."
        )
    return None


@contextlib.contextmanager
def open_source_connection(source):
    sqlite_path = validate_connection_config(source)
    timeout_seconds = int(getattr(settings, "MIGRATION_DB_CONNECT_TIMEOUT", 10))

    if source.engine == MigrationDatabaseConnection.ENGINE_SQLITE:
        uri = f"file:{sqlite_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=timeout_seconds)
        connection.row_factory = sqlite3.Row
    elif source.engine == MigrationDatabaseConnection.ENGINE_POSTGRESQL:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        connection = psycopg2.connect(
            host=source.host,
            port=source.port or 5432,
            dbname=source.database_name,
            user=source.username,
            password=os.environ[source.password_env_var],
            connect_timeout=timeout_seconds,
            sslmode=source.ssl_mode or "prefer",
            cursor_factory=RealDictCursor,
            options="-c default_transaction_read_only=on -c statement_timeout=30000",
        )
        connection.autocommit = True
    elif source.engine == MigrationDatabaseConnection.ENGINE_MYSQL:
        import pymysql

        connection = pymysql.connect(
            host=source.host,
            port=source.port or 3306,
            database=source.database_name,
            user=source.username,
            password=os.environ[source.password_env_var],
            connect_timeout=timeout_seconds,
            read_timeout=30,
            write_timeout=30,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            ssl=None if (source.ssl_mode or "").lower() in ["", "disable"] else {},
        )
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
    else:
        raise ValidationError("Unsupported migration database engine.")

    try:
        yield connection
    finally:
        connection.close()


def _quote(source, identifier):
    identifier = validate_identifier(identifier)
    if source.engine == MigrationDatabaseConnection.ENGINE_MYSQL:
        return f"`{identifier}`"
    return f'"{identifier}"'


def _qualified_table(source, schema, table):
    table_sql = _quote(source, table)
    if schema:
        return f"{_quote(source, schema)}.{table_sql}"
    return table_sql


def _json_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def normalize_rows(rows):
    return [
        {str(key): _json_value(value) for key, value in dict(row).items()}
        for row in rows
    ]


def inspect_source(source):
    tables = []
    with open_source_connection(source) as connection:
        cursor = connection.cursor()
        try:
            if source.engine == MigrationDatabaseConnection.ENGINE_SQLITE:
                cursor.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
                table_rows = cursor.fetchall()
                for row in table_rows[:200]:
                    table_name = row[0]
                    validate_identifier(table_name, "table name")
                    cursor.execute(f"PRAGMA table_info({_quote(source, table_name)})")
                    columns = [
                        {
                            "name": column[1],
                            "data_type": column[2] or "",
                            "nullable": not bool(column[3]),
                        }
                        for column in cursor.fetchall()
                    ]
                    tables.append({"schema": "", "name": table_name, "columns": columns})
            elif source.engine == MigrationDatabaseConnection.ENGINE_POSTGRESQL:
                cursor.execute(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_type = 'BASE TABLE' "
                    "AND table_schema NOT IN ('pg_catalog', 'information_schema') "
                    "ORDER BY table_schema, table_name LIMIT 200"
                )
                for row in cursor.fetchall():
                    schema, table_name = row["table_schema"], row["table_name"]
                    cursor.execute(
                        "SELECT column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_schema = %s AND table_name = %s "
                        "ORDER BY ordinal_position",
                        [schema, table_name],
                    )
                    columns = [
                        {
                            "name": column["column_name"],
                            "data_type": column["data_type"],
                            "nullable": column["is_nullable"] == "YES",
                        }
                        for column in cursor.fetchall()
                    ]
                    tables.append({"schema": schema, "name": table_name, "columns": columns})
            else:
                cursor.execute(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_type = 'BASE TABLE' AND table_schema = %s "
                    "ORDER BY table_name LIMIT 200",
                    [source.database_name],
                )
                for row in cursor.fetchall():
                    schema, table_name = row["table_schema"], row["table_name"]
                    cursor.execute(
                        "SELECT column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_schema = %s AND table_name = %s "
                        "ORDER BY ordinal_position",
                        [schema, table_name],
                    )
                    columns = [
                        {
                            "name": column["column_name"],
                            "data_type": column["data_type"],
                            "nullable": column["is_nullable"] == "YES",
                        }
                        for column in cursor.fetchall()
                    ]
                    tables.append({"schema": schema, "name": table_name, "columns": columns})
        finally:
            cursor.close()

    return {"connection": source.name, "engine": source.engine, "tables": tables}


def fetch_dataset_rows(dataset, columns):
    source = dataset.connection
    schema = validate_identifier(dataset.source_schema, "schema", allow_blank=True)
    table = validate_identifier(dataset.source_table, "table")
    key_column = validate_identifier(dataset.source_key_column, "source key column")
    selected = []
    for column in [key_column, *columns]:
        column = validate_identifier(column, "column")
        if column not in selected:
            selected.append(column)

    configured_max = int(getattr(settings, "MIGRATION_DB_MAX_ROWS", 50000))
    limit = min(max(int(dataset.row_limit), 1), configured_max)
    column_sql = ", ".join(_quote(source, column) for column in selected)
    table_sql = _qualified_table(source, schema, table)
    query = (
        f"SELECT {column_sql} FROM {table_sql} "
        f"ORDER BY {_quote(source, key_column)} LIMIT %s"
    )
    parameter = "?" if source.engine == MigrationDatabaseConnection.ENGINE_SQLITE else "%s"
    query = query.replace("%s", parameter)

    with open_source_connection(source) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(query, [limit + 1])
            rows = normalize_rows(cursor.fetchall())
        finally:
            cursor.close()

    if len(rows) > limit:
        raise ValidationError(
            f"Dataset {dataset.name} exceeds its {limit}-row safety limit."
        )
    return rows


def rows_fingerprint(rows):
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
