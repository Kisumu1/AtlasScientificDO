import argparse
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .service import Service

STATIC = Path(__file__).parent / 'static'


def handler(service):
    class Handler(BaseHTTPRequestHandler):
        def send(self, body, content_type='application/json', status=200):
            if not isinstance(body, bytes):
                body = json.dumps(body, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlsplit(self.path)
            try:
                if url.path == '/api/state':
                    return self.send(service.state())
                if url.path == '/api/ports':
                    return self.send(service.ports(parse_qs(url.query).get('transport', ['i2c'])[0]))
                if url.path == '/register_service':
                    return self.send(dict(name='Atlas Sensors', description='Dissolved oxygen monitoring',
                                          icon='mdi-water-percent', company='Community extension',
                                          version=os.environ.get('ATLAS_VERSION', '0.1.2-beta.5'),
                                          webpage=os.environ.get('ATLAS_SOURCE_URL') or '/', api='/api/state',
                                          works_in_relative_paths=True))
                if url.path == '/api/export':
                    session = parse_qs(url.query).get('session', [''])[0]
                    if len(session) != 32 or any(c not in '0123456789abcdef' for c in session):
                        raise ValueError('Invalid recording ID')
                    stream = service.export(session)
                    first = next(stream)
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/csv; charset=utf-8')
                    self.send_header('Content-Disposition', f'attachment; filename="atlas-do-{session}.csv"')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    try:
                        self.wfile.write(first)
                        for chunk in stream:
                            self.wfile.write(chunk)
                    finally:
                        stream.close()
                    return
                files = {'/': ('index.html', 'text/html; charset=utf-8'),
                         '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                         '/style.css': ('style.css', 'text/css; charset=utf-8')}
                if url.path in files:
                    name, mime = files[url.path]
                    return self.send((STATIC / name).read_bytes(), mime)
                self.send({'error': 'Not found'}, status=404)
            except ValueError as exc:
                self.send({'error': str(exc)}, status=400)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            # Custom header prevents cross-origin HTML forms from controlling hardware.
            # No CORS permission is granted; the UI uses relative same-origin requests.
            if self.headers.get('X-Atlas-Request') != '1' or self.headers.get('Content-Type') != 'application/json':
                return self.send({'error': 'Expected an Atlas JSON request'}, status=403)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError('Invalid request length')
                raw = json.loads(self.rfile.read(length))
                if not isinstance(raw, dict):
                    raise ValueError('Expected a JSON object')
                path = urlsplit(self.path).path
                if path == '/api/config':
                    service.configure(raw)
                elif path == '/api/find':
                    return self.send(service.find_and_connect(raw))
                elif path == '/api/record':
                    if type(raw.get('enabled')) is not bool:
                        raise ValueError('enabled must be a boolean')
                    service.record(raw['enabled'])
                elif path == '/api/calibrate':
                    if raw.get('confirmed') is not True:
                        raise ValueError('Confirm probe preparation before calibrating')
                    service.calibrate(raw.get('kind'))
                else:
                    return self.send({'error': 'Not found'}, status=404)
                self.send({'ok': True})
            except (ValueError, TypeError) as exc:
                self.send({'error': str(exc)}, status=400)
            except Exception as exc:
                logging.exception('Request failed')
                self.send({'error': str(exc)}, status=503)

        def log_message(self, format, *args):
            if len(args) > 1 and str(args[1]) != '200':
                logging.info(format, *args)
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8097)
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--demo', action='store_true', help='Explicitly start with simulated readings')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    service = Service(args.data_dir, demo=args.demo)
    server = ThreadingHTTPServer((args.host, args.port), handler(service))
    service.thread.start()
    logging.info('Atlas dashboard on port %d', args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()


if __name__ == '__main__':
    main()
