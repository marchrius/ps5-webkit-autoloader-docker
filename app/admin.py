"""LAN administration endpoints, separate from the console's frontend."""
import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path


class AdminHandler(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if self.path in ('/admin', '/admin/'):
            self.reply(200, Path(__file__).with_name('admin.html').read_bytes(), 'text/html; charset=utf-8')
        elif self.path == '/admin/app.js':
            self.reply(200, Path(__file__).with_name('admin.js').read_bytes(), 'text/javascript; charset=utf-8')
        elif self.path == '/admin/style.css':
            self.reply(200, Path(__file__).with_name('admin.css').read_bytes(), 'text/css; charset=utf-8')
        elif self.path == '/admin/api/version':
            self.reply(200, json.dumps(self.server.releases.status()).encode())
        else:
            self.reply(404, b'{"error":"Not found"}')

    def do_POST(self):
        if self.path != '/admin/api/version':
            self.reply(404, b'{"error":"Not found"}')
            return
        # JSON + custom header disallow cross-origin form submissions and fetches.
        origin = self.headers.get('Origin')
        expected_origin = f'{self.server.admin_scheme}://{self.headers.get("Host", "")}'
        if (self.headers.get('Content-Type') != 'application/json'
                or self.headers.get('X-Autoloader-Admin') != '1'
                or (origin and origin != expected_origin)
                or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
            self.reply(403, b'{"error":"Same-origin JSON request required"}')
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > 4096:
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or not isinstance(data.get('version'), str):
                raise ValueError('A release version is required')
            result = self.server.releases.install(data['version'])
        except RuntimeError as exc:
            self.reply(409, json.dumps({'error': str(exc)}).encode())
        except (ValueError, KeyError) as exc:
            self.reply(400, json.dumps({'error': str(exc)}).encode())
        except Exception as exc:
            self.log_error('Release update failed: %s', exc)
            self.reply(502, b'{"error":"Release update failed; check container logs"}')
        else:
            self.reply(200, json.dumps(result).encode())

