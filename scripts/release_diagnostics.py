"""Publish bounded release-test diagnostics without exporting private configuration."""
import os
from pathlib import Path
import re
import secrets
import urllib.parse


def environment_secrets(path):
    if not path.is_file():
        return []
    values = []
    for line in path.read_text(errors="replace").splitlines():
        key, separator, value = line.partition("=")
        if separator and any(part in key.upper() for part in ("PASSWORD", "SECRET", "TOKEN", "KEY")):
            values.append(value.strip().strip("\"'"))
    return values


def redact(text, confidential=()):
    variants = {encoded for value in confidential if value for encoded in
                (value, urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value))}
    for value in sorted(variants, key=len, reverse=True):
        text = text.replace(value, "[redacted]")
    return re.sub(r"(\b[a-z][a-z0-9+.-]*://)[^\s/@]+@", r"\1[redacted]@", text, flags=re.I)


def publish(path, sections, confidential=(), tail_size=10000):
    # Redact before truncation so a secret split at the tail boundary cannot leak.
    report = "\n\n".join(title + "\n" + redact(body, confidential)[-tail_size:]
                         for title, body in sections) + "\n"
    try:
        path = Path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(report)
    except OSError:
        print("Could not save diagnostics; the redacted report follows in the console.", flush=True)
    # Test output must not be interpreted as GitHub workflow commands.
    token = secrets.token_hex(24) if os.environ.get("GITHUB_ACTIONS") == "true" else None
    if token:
        print("::group::Release test diagnostics\n::stop-commands::" + token, flush=True)
    print(report, flush=True)
    if token:
        print("::" + token + "::\n::endgroup::", flush=True)
    return report


def read_log(path):
    try:
        return path.read_text(errors="replace")
    except OSError:
        return "Log unavailable."
