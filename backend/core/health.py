import subprocess

from django.core.cache import cache
from django.db import connection


def _check_command(command, version_arg="-version"):
    try:
        result = subprocess.run(
            [command, version_arg],
            capture_output=True,
            text=True,
            timeout=5,
        )

        output = result.stdout.strip() or result.stderr.strip()

        return {
            "ok": result.returncode == 0,
            "version": output.splitlines()[0] if output else "unknown",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


def _check_pyopenms():
    try:
        import pyopenms as oms

        return {
            "ok": True,
            "version": getattr(oms, "__version__", "unknown"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


def build_health_status():
    checks = {
        "db_ok": False,
        "redis_ok": False,
        "clustalo_ok": False,
        "blastn_ok": False,
        "blastp_ok": False,
        "makeblastdb_ok": False,
        "pyopenms_ok": False,
    }

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

        checks["db_ok"] = True
    except Exception as exc:
        checks["db_error"] = str(exc)

    try:
        cache.set("health_check", "ok", timeout=10)
        checks["redis_ok"] = cache.get("health_check") == "ok"
    except Exception as exc:
        checks["redis_error"] = str(exc)

    command_checks = [
        ("clustalo", "clustalo", "--version"),
        ("blastn", "blastn", "-version"),
        ("blastp", "blastp", "-version"),
        ("makeblastdb", "makeblastdb", "-version"),
    ]

    for key, command, version_arg in command_checks:
        result = _check_command(command, version_arg)
        checks[f"{key}_ok"] = result["ok"]

        if result.get("version"):
            checks[f"{key}_version"] = result["version"]

        if result.get("error"):
            checks[f"{key}_error"] = result["error"]

    pyopenms = _check_pyopenms()
    checks["pyopenms_ok"] = pyopenms["ok"]

    if pyopenms.get("version"):
        checks["pyopenms_version"] = pyopenms["version"]

    if pyopenms.get("error"):
        checks["pyopenms_error"] = pyopenms["error"]

    health_keys = [
        "db_ok",
        "redis_ok",
        "clustalo_ok",
        "blastn_ok",
        "blastp_ok",
        "makeblastdb_ok",
        "pyopenms_ok",
    ]
    all_ok = all(checks[key] for key in health_keys)

    return {
        "status": "ok" if all_ok else "degraded",
        **checks,
    }
