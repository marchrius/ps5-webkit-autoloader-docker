import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from fetch_release import release_asset


class ReleaseTests(unittest.TestCase):
    @patch("fetch_release.urllib.request.urlopen")
    def test_reads_published_asset_name(self, urlopen):
        asset = {"name": "webkit-autoloader-host.py",
                 "browser_download_url": "https://github.com/example/actual-name.py"}
        urlopen.return_value = io.BytesIO(json.dumps({"assets": [asset]}).encode())
        self.assertEqual(release_asset("0.6.1"), asset)
        self.assertTrue(urlopen.call_args.args[0].full_url.endswith("/tags/v0.6.1"))

    @patch("fetch_release.urllib.request.urlopen")
    def test_missing_release_explains_env_fix(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError("url", 404, "Not found", {}, None)
        with self.assertRaisesRegex(ValueError, "v0.6.2 non pubblicata.*AUTOLOADER_VERSION"):
            release_asset("0.6.2")

    @patch("fetch_release.urllib.request.urlopen")
    def test_executable_only_release_fails(self, urlopen):
        urlopen.return_value = io.BytesIO(json.dumps({"assets": [
            {"name": "webkit-autoloader-host.exe"}]}).encode())
        with self.assertRaisesRegex(ValueError, "trovati 0"):
            release_asset("0.6.1")

    @patch("fetch_release.urllib.request.urlopen")
    def test_ambiguous_python_assets_fail(self, urlopen):
        urlopen.return_value = io.BytesIO(json.dumps({"assets": [
            {"name": "webkit-autoloader-host_a.py"},
            {"name": "webkit-autoloader-host_b.py"}]}).encode())
        with self.assertRaisesRegex(ValueError, "trovati 2"):
            release_asset("0.6.1")


if __name__ == "__main__":
    unittest.main()
