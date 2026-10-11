"""Warm CI's local Docker cache sequentially; retry only transient pull errors."""
import os
import re
import subprocess
import time


IMAGE_KEYS = ("PYTHON_IMAGE", "POSTGRES_IMAGE", "REDIS_IMAGE")
RETRY_DELAYS = (15, 30)
TRANSIENT = re.compile(
    r"toomanyrequests|too many requests|rate exceeded|\b429\b|"
    r"\b(?:500|502|503|504)\b|i/o timeout|tls handshake timeout|"
    r"connection reset|temporary failure|service unavailable", re.I
)


def pull(image):
    for attempt in range(len(RETRY_DELAYS) + 1):
        print(f"Pulling {image} (attempt {attempt + 1}/3)", flush=True)
        try:
            result = subprocess.run(
                ["docker", "pull", image], capture_output=True, text=True, timeout=300,
            )
            output = result.stdout + result.stderr
            status = result.returncode
            transient = bool(TRANSIENT.search(output))
        except subprocess.TimeoutExpired:
            output, status, transient = "Docker pull timed out after 300 seconds.", 1, True
        print(output[-6000:], flush=True)
        if status == 0:
            return
        if not transient or attempt == len(RETRY_DELAYS):
            raise RuntimeError(f"Image pull failed: {image}; CI cannot continue (exit {status}).")
        delay = RETRY_DELAYS[attempt]
        print(f"Temporary registry/network error; retrying in {delay}s.", flush=True)
        time.sleep(delay)


def main():
    # Validate all inputs before downloading. Images stay in the configured
    # registry; there is no silent fallback or suppression of exhausted retries.
    images = [os.environ.get(key, "").strip() for key in IMAGE_KEYS]
    if not all(images):
        raise RuntimeError("Set PYTHON_IMAGE, POSTGRES_IMAGE and REDIS_IMAGE for CI.")
    for image in images:
        pull(image)


if __name__ == "__main__":
    main()
