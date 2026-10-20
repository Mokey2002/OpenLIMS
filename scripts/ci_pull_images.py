"""Warm CI images with bounded retries and explicitly configured fallbacks."""
import os
import re
import subprocess
import time


IMAGE_KEYS = ("PYTHON_IMAGE", "POSTGRES_IMAGE", "REDIS_IMAGE")
RETRY_DELAYS = (15, 30)
TRANSIENT = re.compile(
    r"toomanyrequests|too many requests|rate exceeded|\b429\b|"
    r"\b(?:500|502|503|504)\b|i/o timeout|tls handshake timeout|"
    r"context deadline exceeded|connection reset|temporary failure|service unavailable", re.I
)


class TransientPullError(RuntimeError):
    """The configured registry remained unavailable after bounded retries."""


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
            error = TransientPullError if transient else RuntimeError
            raise error(f"Image pull failed: {image}; CI cannot continue (exit {status}).")
        delay = RETRY_DELAYS[attempt]
        print(f"Temporary registry/network error; retrying in {delay}s.", flush=True)
        time.sleep(delay)


def pull_with_fallback(image, fallback):
    try:
        pull(image)
    except TransientPullError:
        print(f"Primary registry retries exhausted. Explicit fallback: {fallback} -> {image}", flush=True)
        pull(fallback)
        # Compose and Dockerfile build arguments retain their configured names.
        # Tag only after a successful pull; neither pull nor tag errors are hidden.
        subprocess.run(["docker", "tag", fallback, image], check=True, timeout=30)
        print(f"Cached {image} from {fallback} for subsequent CI steps.", flush=True)


def main():
    # Validate all required inputs before downloading. Fallbacks are opt-in,
    # visible in logs, and used only after transient failures exhaust retries.
    images = [os.environ.get(key, "").strip() for key in IMAGE_KEYS]
    if not all(images):
        raise RuntimeError("Set PYTHON_IMAGE, POSTGRES_IMAGE and REDIS_IMAGE for CI.")
    for key, image in zip(IMAGE_KEYS, images):
        fallback = os.environ.get(f"{key}_FALLBACK", "").strip()
        if fallback and fallback != image:
            pull_with_fallback(image, fallback)
        else:
            pull(image)


if __name__ == "__main__":
    main()
