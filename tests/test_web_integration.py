"""Exercise the real upstream handler when its release is installed (e.g. in Docker)."""
import http.client
import importlib.util
import sys
import shutil
import tempfile
import json
from unittest.mock import patch
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


@unittest.skipUnless(AVAILABLE, "upstream release is not installed; run inside the container")
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

    def get(self, path, host="manuals.playstation.net", method="GET"):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        try:
            conn.request(method, path, headers={"Host": host})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_dynamic_release_activation_serves_official_frontend(self):
        from releases import ReleaseManager
        settings = Settings.load({"HOST_IP": "192.168.1.20"}, CONFIG)
        with tempfile.TemporaryDirectory() as directory:
            def download(version, digest, destination):
                shutil.copyfile(self.web.upstream.__file__, destination / "upstream_host.py")
            manager = ReleaseManager(Path(directory), env={"AUTOLOADER_VERSION": "0.6.2"})
            with patch("releases.fetch_release", side_effect=download):
                manager.start(lambda module: self.web.build_handler(settings, module, manager))
                self.server.RequestHandlerClass = lambda *args: manager.handler(*args)
                self.server.admin_scheme = "http"
                self.assertEqual(self.get("/document/en/ps5/index.html")[0], 200)
                self.assertEqual(self.get("/admin/", "192.168.1.20")[0], 200)
                manager.install("0.5.2")
                self.assertEqual(self.get("/document/en/ps5/index.html")[0], 200)
                data = json.loads(self.get("/admin/api/version", "192.168.1.20")[2])
                self.assertEqual(data["version"], "0.5.2")
                self.assertEqual(data["installed_version"], self.web.upstream.VERSION)

    def test_guide_serves_embedded_index(self):
        status, headers, body = self.get("/document/en/ps5/index.html")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertTrue(body)

    def test_healthcheck_head_has_content_length_without_body(self):
        status, headers, body = self.get("/document/en/ps5/index.html", method="HEAD")
        self.assertEqual(status, 200)
        self.assertGreater(int(headers["Content-Length"]), 128)
        self.assertEqual(body, b"")

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
