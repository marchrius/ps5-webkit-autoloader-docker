import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from releases import ReleaseManager
from settings import Settings
from web import build_handler

CONFIG = Path(__file__).resolve().parents[1] / 'config'
if not CONFIG.is_dir():
    CONFIG = Path('/config')

SOURCE = '''
import io
from http.server import BaseHTTPRequestHandler
VERSION = {version!r}
class Archive:
    def namelist(self): return ['index.html']
def get_embedded_zip(): return Archive()
class Status:
    def __init__(self, **kwargs): pass
class GuideHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, allowed_host=None, **kwargs): super().__init__(*args, **kwargs)
    def send_head(self):
        body = VERSION.encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        return io.BytesIO(body)
    def do_GET(self):
        stream = self.send_head()
        if stream: self.wfile.write(stream.read())
    def do_HEAD(self): self.send_head()
'''


def fake_download(version, digest, destination):
    (destination / 'upstream_host.py').write_text(SOURCE.format(version=version))
    (destination / 'UPSTREAM.txt').write_text('test provenance')
    (destination / 'LICENSE.upstream').write_text('test license')


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config'
        self.bundled = self.root / 'bundled'
        self.bundled.mkdir()
        fake_download('0.6.2', '', self.bundled)
        (self.bundled / 'BUNDLED_VERSION').write_text('0.6.2\n')
        self.fetch = patch('releases.fetch_release', side_effect=fake_download).start()
        self.addCleanup(patch.stopall)
        self.settings = Settings.load({'HOST_IP': '192.168.1.20'}, CONFIG)

    def manager(self, **env):
        manager = ReleaseManager(self.config, self.bundled, {'AUTOLOADER_VERSION': '0.6.2', **env})
        return manager.start(lambda module: build_handler(self.settings, module, manager))

    def test_bundle_initializes_offline_and_saved_config_beats_env(self):
        first = self.manager()
        self.assertEqual(first.status()['version'], '0.6.2')
        self.fetch.assert_not_called()
        second = self.manager(AUTOLOADER_VERSION='0.5.2')
        self.assertEqual(second.status()['installed_version'], '0.6.2')
        self.fetch.assert_not_called()

    def test_env_download_when_not_bundled(self):
        manager = self.manager(AUTOLOADER_VERSION='0.5.2')
        self.assertEqual(manager.status()['version'], '0.5.2')
        self.fetch.assert_called_once()

    def test_saved_version_only_config_downloads_selected_version(self):
        self.config.mkdir()
        (self.config / 'autoloader.json').write_text('{"version":"0.5.2"}')
        manager = self.manager()
        self.assertEqual(manager.status()['version'], '0.5.2')

    def test_force_downloads_even_same_version_and_overwrites_config(self):
        original = self.manager()
        manager = self.manager(AUTOLOADER_FORCE_UPDATE='true')
        self.fetch.assert_called_once()
        self.assertNotEqual(manager.status()['release'], original.status()['release'])
        manager = self.manager(AUTOLOADER_VERSION='0.5.2', AUTOLOADER_FORCE_UPDATE='true')
        self.assertEqual(json.loads((self.config / 'autoloader.json').read_text())['version'], '0.5.2')

    def test_failed_update_preserves_active_handler_and_config(self):
        manager = self.manager()
        previous = manager.handler
        config = (self.config / 'autoloader.json').read_bytes()
        self.fetch.side_effect = ValueError('digest mismatch')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            manager.install('0.5.2')
        self.assertIs(previous, manager.handler)
        self.assertEqual((self.config / 'autoloader.json').read_bytes(), config)
        self.assertEqual(len(list((self.config / 'releases').iterdir())), 1)
        with self.assertRaises(ValueError):
            self.manager(AUTOLOADER_FORCE_UPDATE='true')
        self.assertEqual((self.config / 'autoloader.json').read_bytes(), config)

    def test_unsupported_handler_not_published(self):
        manager = self.manager()
        config = (self.config / 'autoloader.json').read_bytes()
        def broken(version, digest, destination):
            fake_download(version, digest, destination)
            with (destination / 'upstream_host.py').open('a') as stream:
                stream.write('\nGuideHandler = None\n')
        self.fetch.side_effect = broken
        with self.assertRaisesRegex(RuntimeError, 'handler is missing'):
            manager.install('0.5.2')
        self.assertEqual((self.config / 'autoloader.json').read_bytes(), config)

    def test_config_write_failure_preserves_running_release(self):
        manager = self.manager()
        previous = manager.handler
        config = (self.config / 'autoloader.json').read_bytes()
        with patch('releases.Path.replace', side_effect=PermissionError('read-only config')):
            with self.assertRaises(PermissionError):
                manager.install('0.5.2')
        self.assertIs(manager.handler, previous)
        self.assertEqual((self.config / 'autoloader.json').read_bytes(), config)
        self.assertEqual(len(list((self.config / 'releases').iterdir())), 1)

    def test_environment_checksum_only_applies_to_environment_version(self):
        manager = self.manager(AUTOLOADER_SHA256='a' * 64)
        manager.install('0.5.2')
        self.assertEqual(self.fetch.call_args.args[1], '')
        manager.install('0.6.2')
        self.assertEqual(self.fetch.call_args.args[1], 'a' * 64)

    def test_concurrent_update_rejected(self):
        manager = self.manager()
        with manager.lock, self.assertRaisesRegex(RuntimeError, 'in progress'):
            manager.install('0.5.2')

    def test_invalid_flags_and_versions(self):
        for env in ({'AUTOLOADER_FORCE_UPDATE': 'yes'}, {'AUTOLOADER_VERSION': '../evil'},
                    {'AUTOLOADER_VERSION': '', 'AUTOLOADER_FORCE_UPDATE': 'true'}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                self.manager(**env)
        self.fetch.assert_not_called()

    def test_web_update_switches_frontend_and_persists(self):
        manager = self.manager()
        server = ThreadingHTTPServer(('127.0.0.1', 0), lambda *args: manager.handler(*args))
        server.admin_scheme = 'http'
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, method='GET', body=None, **headers):
            conn = http.client.HTTPConnection(*server.server_address, timeout=3)
            try:
                conn.request(method, path, body, {'Host': '192.168.1.20', **headers})
                response = conn.getresponse()
                return response.status, response.read()
            finally:
                conn.close()
        try:
            self.assertEqual(request('/')[1], b'0.6.2')
            self.assertIn(b'Gestione Autoloader', request('/admin/')[1])
            self.assertEqual(request('/admin/', 'HEAD'), (200, b''))
            for path in ('/admin/app.js', '/admin/style.css', '/admin/api/version'):
                self.assertEqual(request(path)[0], 200)
            self.assertEqual(request('/admin/', Host='manuals.playstation.net')[0], 403)
            body = json.dumps({'version': '0.5.2'})
            self.assertEqual(request('/admin/api/version', 'POST', body)[0], 403)
            headers = {'Content-Type': 'application/json', 'X-Autoloader-Admin': '1'}
            self.assertEqual(request('/admin/api/version', 'POST', body, Origin='http://evil.test', **headers)[0], 403)
            self.assertEqual(request('/admin/api/version', 'POST', '{', **headers)[0], 400)
            self.assertEqual(request('/admin/api/version', 'POST', body, **headers)[0], 200)
            self.assertEqual(request('/')[1], b'0.5.2')
            self.assertEqual(self.manager().status()['version'], '0.5.2')
            self.fetch.side_effect = ValueError('download failed')
            self.assertEqual(request('/admin/api/version', 'POST', body, **headers)[0], 400)
            self.assertEqual(request('/')[1], b'0.5.2')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
