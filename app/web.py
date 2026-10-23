"""Use the release's handler and embedded payloads, with extra entry domains."""
import functools
import signal
import ssl
import subprocess
import threading
from http.server import ThreadingHTTPServer

import upstream_host as upstream
from settings import Settings, request_action


def build_handler(settings):
    archive = upstream.get_embedded_zip()
    if archive is None or not archive.namelist():
        raise RuntimeError("Upstream archive is missing or empty")

    base_handler = getattr(upstream, "GuideHandler", None) or getattr(upstream, "DualDirHandler", None)
    if base_handler is None:
        raise RuntimeError("Unsupported upstream host API: HTTP handler is missing")

    class Handler(base_handler):
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
    if base_handler is getattr(upstream, "DualDirHandler", None):
        options.update(base_dir=None, overrides_dir="/tmp/overrides", embedded_zip=archive)
    return functools.partial(Handler, **options)


def configure_server(server):
    server.daemon_threads = True
    server.quiet = False
    if hasattr(upstream, "Status"):
        server.status = upstream.Status(enabled=False)
    else:
        server.guide = upstream.GuideStatus(logger=lambda *args: None)


def main():
    settings = Settings.load()
    handler = build_handler(settings)
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
            configure_server(server)
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
