"""Exercise the real upstream handler when its release is installed (e.g. in Docker)."""
import http.client
import importlib.util
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from settings import Settings

AVAILABLE = importlib.util.find_spec("upstream_host") is not None
CONFIG = Path(__file__).resolve().parents[1] / "config"
if not CONFIG.is_dir():
    CONFIG = Path("/config")


@unittest.skipUnless(AVAILABLE, "release upstream non installata; eseguire nel container")
class WebIntegrationTests(unittest.TestCase):
    def setUp(self):
        import web
        self.web = web
        settings = Settings.load({"HOST_IP": "192.168.1.20"}, CONFIG)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web.build_handler(settings))
        web.configure_server(self.server)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get(self, path, host="manuals.playstation.net"):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        try:
            conn.request("GET", path, headers={"Host": host})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_guide_serves_embedded_index(self):
        status, headers, body = self.get("/document/it/ps5/index.html")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertTrue(body)

    def test_embedded_secondary_file_is_served(self):
        archive = self.web.upstream.get_embedded_zip()
        name = next(name for name in archive.namelist()
                    if name != "index.html" and not name.endswith("/"))
        status, _, body = self.get("/" + name)
        self.assertEqual(status, 200)
        expected = archive.read(name)
        expected = expected.replace(b"[[VERSION_PLACEHOLDER]]", self.web.upstream.VERSION.encode())
        expected = expected.replace(b"[[BUILD_TIME_PLACEHOLDER]]", self.web.upstream.BUILD_TIME.encode())
        self.assertEqual(body, expected)

    def test_secondary_entry_redirects(self):
        status, headers, _ = self.get("/", "www.playstation.com")
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "https://manuals.playstation.net/")

    def test_unknown_host_is_rejected(self):
        self.assertEqual(self.get("/", "example.com")[0], 403)

    def test_unknown_asset_stays_404(self):
        self.assertEqual(self.get("/nonexistent-asset-test.js")[0], 404)


if __name__ == "__main__":
    unittest.main()
