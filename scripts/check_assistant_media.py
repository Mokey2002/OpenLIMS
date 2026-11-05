"""Exercise production NGINX media rules using an isolated Docker container.

Run from the checkout: python3 scripts/check_assistant_media.py
Only synthetic fixtures are mounted; the container is removed after the check.
"""
import argparse
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener


def check(image):
    checkout = Path(__file__).resolve().parents[1]
    name = 'openlims-media-check-' + uuid.uuid4().hex[:8]
    started = False
    # Keep bind mounts under the checkout, shared with the local Docker daemon.
    with tempfile.TemporaryDirectory(prefix='.media-check-', dir=checkout) as folder:
        root = Path(folder)
        for path in [root, root / 'media', root / 'media/assistant_artifacts', root / 'media/imports', root / 'html']:
            path.mkdir(exist_ok=True)
            path.chmod(0o755)
        fixtures = {'media/assistant_artifacts/source.csv': 'private-source\n',
                    'media/imports/assistant-1234567890abcdef1234567890abcdef.csv': 'private-legacy-source\n',
                    'media/imports/instrument.csv': 'ordinary-media\n',
                    'media/imports/assistant-calibration.csv': 'ordinary-assistant-named-media\n',
                    'html/index.html': 'test-frontend\n'}
        for path, contents in fixtures.items():
            file = root / path
            file.write_text(contents)
            file.chmod(0o644)
        try:
            subprocess.run(['docker', 'run', '-d', '--rm', '--name', name, '--add-host', 'api:127.0.0.1',
                '-p', '127.0.0.1::80', '-v', f'{checkout}/frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro',
                '-v', f'{root}/media:/srv/openlims/media:ro', '-v', f'{root}/html:/usr/share/nginx/html:ro', image],
                check=True, capture_output=True, text=True, timeout=60)
            started = True
            port = subprocess.check_output(['docker', 'port', name, '80/tcp'], text=True, timeout=10).strip().rsplit(':', 1)[1]
            opener = build_opener(ProxyHandler({}))
            def get(path):
                try:
                    with opener.open(f'http://127.0.0.1:{port}{path}', timeout=2) as response:
                        return response.status, response.read().decode()
                except HTTPError as error:
                    return error.code, error.read().decode()
            for _ in range(30):
                try:
                    if get('/')[0] == 200:
                        break
                except (URLError, ConnectionError, TimeoutError):
                    time.sleep(.1)
            subprocess.run(['docker', 'exec', name, 'nginx', '-t'], check=True, capture_output=True, text=True, timeout=10)
            results = {}
            for path in ['/media/assistant_artifacts/source.csv', '/media/assistant_artifacts',
                '/media/assistant%5Fartifacts/source.csv', '/media//assistant_artifacts/source.csv',
                '/media/imports/assistant-1234567890abcdef1234567890abcdef.csv',
                '/media/imports/%61ssistant-1234567890abcdef1234567890abcdef.csv',
                '/media/imports//assistant-1234567890abcdef1234567890abcdef.csv',
                '/media/public/%2e%2e/assistant_artifacts/source.csv']:
                status, body = get(path)
                assert status == 404 and 'private-' not in body, (path, status)
                results[path] = status
            for path, expected in [('/media/imports/instrument.csv', 'ordinary-media\n'),
                ('/media/imports/assistant-calibration.csv', 'ordinary-assistant-named-media\n'), ('/', 'test-frontend\n')]:
                status, body = get(path)
                assert status == 200 and body == expected, (path, status)
                results[path] = status
            return {'configuration': 'frontend/nginx.conf', 'image': image, 'syntax_check': 'passed', 'http_checks': results}
        finally:
            if started:
                subprocess.run(['docker', 'stop', name], check=False, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=15)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='nginx:1.27-alpine')
    args = parser.parse_args()
    print(json.dumps(check(args.image), indent=2))
