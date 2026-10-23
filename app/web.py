"""Use the release's handler and embedded payloads, with extra entry domains."""
import functools
import signal
import ssl
import subprocess
import threading
from http.server import ThreadingHTTPServer

import upstream_host as upstream
from settings import Settings, request_action


def main():
    settings = Settings.load()
    archive = upstream.get_embedded_zip()
    if archive is None or not archive.namelist():
        raise RuntimeError("Archivio upstream assente o vuoto")

    class Handler(upstream.DualDirHandler):
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

    handler = functools.partial(Handler, base_dir=None, overrides_dir="/tmp/overrides",
                                allowed_host=None, embedded_zip=archive)
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
            server.daemon_threads = True
            server.quiet = False
            server.guide = upstream.GuideStatus(logger=lambda *args: None)
            if port == 443:
                try:
                    server.socket = context.wrap_socket(server.socket, server_side=True)
                except Exception:
                    server.server_close()
                    raise
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
        print("HTTP :80 e HTTPS :443 pronti; frontend ufficiale incorporato", flush=True)
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
