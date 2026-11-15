"""Use the release's handler and embedded payloads, with extra entry domains."""
import copy
import functools
import importlib
import signal
import ssl
import subprocess
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

from admin import AdminHandler
from releases import ReleaseManager
from settings import Settings, request_action


def build_handler(settings, module=None, releases=None):
    global upstream
    if module is None:
        upstream = importlib.import_module("upstream_host")
        module = upstream
    release_module = module
    archive = module.get_embedded_zip()
    if archive is None or not archive.namelist():
        raise RuntimeError("Upstream archive is missing or empty")

    base_handler = getattr(module, "GuideHandler", None) or getattr(module, "DualDirHandler", None)
    if base_handler is None:
        raise RuntimeError("Unsupported upstream host API: HTTP handler is missing")

    class Handler(base_handler):
        reply = AdminHandler.reply

        def setup(self):
            super().setup()
            self.server = copy.copy(self.server)
            configure_server(self.server, release_module)

        def admin_request(self):
            if self.path.split('?', 1)[0].startswith('/admin'):
                host = self.headers.get('Host', '').split(':', 1)[0].lower().rstrip('.')
                if releases is None or host not in (settings.host_ip, '127.0.0.1', 'localhost'):
                    self.send_error(403, 'Use the server IP for administration')
                    return True
                self.server.releases = releases
                if self.command == 'POST':
                    AdminHandler.do_POST(self)
                else:
                    AdminHandler.do_GET(self)
                return True
            return False

        def do_GET(self):
            if not self.admin_request():
                super().do_GET()

        def do_HEAD(self):
            if not self.admin_request():
                super().do_HEAD()

        def do_POST(self):
            if not self.admin_request():
                self.send_error(405, 'Method not allowed')

        def send_head(self):
            action = request_action(self.headers.get("Host", ""), self.path, settings)
            if action == "deny":
                self.send_error(403, "Host not configured")
                return None
            if action == "redirect":
                self.send_response(302)
                self.send_header("Location", "https://manuals.playstation.net/")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            return super().send_head()

    options = {"allowed_host": None}
    if base_handler is getattr(module, "DualDirHandler", None):
        options.update(base_dir=None, overrides_dir="/tmp/overrides", embedded_zip=archive)
    configure_server(SimpleNamespace(), release_module)
    return functools.partial(Handler, **options)


def configure_server(server, module=None):
    module = module or upstream
    server.daemon_threads = True
    server.quiet = False
    if hasattr(module, "Status"):
        server.status = module.Status(enabled=False)
    else:
        server.guide = module.GuideStatus(logger=lambda *args: None)


def main():
    settings = Settings.load()
    releases = ReleaseManager()
    releases.start(lambda module: build_handler(settings, module, releases))

    def handler(request, address, server):
        releases.handler(request, address, server)

    print(f"Autoloader selected: {releases.status()}", flush=True)
    # Never reuse the public private key embedded in the upstream release.
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
        "-keyout", "/tmp/key.pem", "-out", "/tmp/cert.pem",
        "-subj", "/CN=manuals.playstation.net", "-addext",
        "subjectAltName=" + ",".join(f"DNS:{d}" for d in settings.redirects),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain("/tmp/cert.pem", "/tmp/key.pem")
    servers = []
    try:
        for port in (80, 443):
            server = ThreadingHTTPServer(("0.0.0.0", port), handler)
            server.admin_scheme = "https" if port == 443 else "http"
            server.daemon_threads = True
            if port == 443:
                try:
                    server.socket = context.wrap_socket(server.socket, server_side=True)
                except Exception:
                    server.server_close()
                    raise
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
        print("HTTP :80 and HTTPS :443 ready; official frontend embedded", flush=True)
        stop = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
        stop.wait()
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
