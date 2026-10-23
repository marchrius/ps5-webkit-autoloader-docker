import io
import hashlib
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from fetch_release import PINNED_RELEASES, main, release_asset


class ReleaseTests(unittest.TestCase):
    @patch("fetch_release.urllib.request.urlopen")
    def test_verified_releases_do_not_call_github_api(self, urlopen):
        for version, digest in PINNED_RELEASES.items():
            asset = release_asset(version)
            self.assertEqual(asset["digest"], f"sha256:{digest}")
            self.assertTrue(asset["browser_download_url"].endswith(
                f"/v{version}/webkit-autoloader-host_v{version}.py"))
        urlopen.assert_not_called()

    @patch("fetch_release.urllib.request.urlopen")
    def test_reads_published_asset_name(self, urlopen):
        asset = {"name": "webkit-autoloader-host.py",
                 "browser_download_url": "https://github.com/example/actual-name.py"}
        urlopen.return_value = io.BytesIO(json.dumps({"assets": [asset]}).encode())
        self.assertEqual(release_asset("1.2.3"), asset)
        self.assertTrue(urlopen.call_args.args[0].full_url.endswith("/tags/v1.2.3"))

    @patch("fetch_release.urllib.request.urlopen")
    def test_missing_release_explains_env_fix(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError("url", 404, "Not found", {}, None)
        with self.assertRaisesRegex(ValueError, "v0.6.2 is not published.*AUTOLOADER_VERSION"):
            release_asset("0.6.2")

    @patch("fetch_release.urllib.request.urlopen")
    def test_executable_only_release_fails(self, urlopen):
        urlopen.return_value = io.BytesIO(json.dumps({"assets": [
            {"name": "webkit-autoloader-host.exe"}]}).encode())
        with self.assertRaisesRegex(ValueError, "found 0"):
            release_asset("1.2.3")

    @patch("fetch_release.urllib.request.urlopen")
    def test_ambiguous_python_assets_fail(self, urlopen):
        urlopen.return_value = io.BytesIO(json.dumps({"assets": [
            {"name": "webkit-autoloader-host_a.py"},
            {"name": "webkit-autoloader-host_b.py"}]}).encode())
        with self.assertRaisesRegex(ValueError, "found 2"):
            release_asset("1.2.3")

    @patch("fetch_release.urllib.request.urlopen")
    def test_pinned_download_checks_digest_without_api(self, urlopen):
        source = b'EMBEDDED_ZIP_B64 = "test-archive"\n'
        digest = hashlib.sha256(source).hexdigest()
        urlopen.side_effect = [io.BytesIO(source), io.BytesIO(b"license text")]
        with patch.dict(PINNED_RELEASES, {"0.6.1": digest}), tempfile.TemporaryDirectory() as directory:
            main("0.6.1", "", Path(directory))
            self.assertEqual((Path(directory) / "upstream_host.py").read_bytes(), source)
            self.assertEqual((Path(directory) / "LICENSE.upstream").read_bytes(), b"license text")
        self.assertEqual(urlopen.call_count, 2)
        self.assertFalse(any("api.github.com" in call.args[0].full_url
                             for call in urlopen.call_args_list))

    @patch("fetch_release.urllib.request.urlopen")
    def test_corrupted_pinned_asset_is_rejected(self, urlopen):
        urlopen.return_value = io.BytesIO(b'EMBEDDED_ZIP_B64 = "tampered"\n')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "verified release digest"):
                main("0.6.1", "", Path(directory))
            self.assertFalse((Path(directory) / "upstream_host.py").exists())

    @patch("fetch_release.urllib.request.urlopen")
    def test_asset_http_failure_identifies_download_stage(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError("url", 403, "Forbidden", {}, None)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Release asset download failed: HTTP 403"):
                main("0.6.1", "", Path(directory))

    @patch("fetch_release.urllib.request.urlopen")
    def test_license_http_failure_identifies_download_stage(self, urlopen):
        source = b'EMBEDDED_ZIP_B64 = "test-archive"\n'
        digest = hashlib.sha256(source).hexdigest()
        urlopen.side_effect = [io.BytesIO(source),
                              urllib.error.HTTPError("url", 404, "Not found", {}, None)]
        with patch.dict(PINNED_RELEASES, {"0.6.1": digest}), tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Upstream license download failed: HTTP 404"):
                main("0.6.1", "", Path(directory))


if __name__ == "__main__":
    unittest.main()
