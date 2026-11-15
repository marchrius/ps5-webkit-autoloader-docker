"""Persistent release selection; publish code and config only after validation."""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import uuid
from pathlib import Path

from fetch_release import main as fetch_release, validate_version


class ReleaseManager:
    def __init__(self, directory=Path('/config'), bundled=Path('/app'), env=None):
        self.directory = Path(directory).resolve()
        self.bundled = Path(bundled)
        self.env = os.environ if env is None else env
        self.lock = threading.Lock()
        self.current = None
        self.handler = None

    def read_config(self):
        path = self.directory / 'autoloader.json'
        if not path.exists():
            return None
        config = json.loads(path.read_text())
        validate_version(config['version'])
        return config

    def status(self):
        return {**self.current, 'environment_version': self.env.get('AUTOLOADER_VERSION', ''),
                'force_update': self.env.get('AUTOLOADER_FORCE_UPDATE', 'false').lower() == 'true'}

    def start(self, handler_builder):
        self.handler_builder = handler_builder
        force = self.env.get('AUTOLOADER_FORCE_UPDATE', 'false').lower()
        if force not in ('true', 'false'):
            raise ValueError('AUTOLOADER_FORCE_UPDATE must be true or false')
        config = self.read_config() if force == 'false' else None
        version = config['version'] if config else self.env.get('AUTOLOADER_VERSION', '')
        validate_version(version)
        if config and (self.directory / config.get('release', '') / 'upstream_host.py').is_file():
            release = (self.directory / config['release']).resolve()
            if not release.is_relative_to((self.directory / 'releases').resolve()):
                raise ValueError('Invalid release path in autoloader.json')
            self.activate(version, release, persist=False)
        else:
            self.install(version, use_bundle=force == 'false')
        return self

    def activate(self, version, release, persist=True):
        spec = importlib.util.spec_from_file_location('autoloader_' + uuid.uuid4().hex,
                                                      release / 'upstream_host.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
            handler = self.handler_builder(module)
            installed_version = module.VERSION
        except Exception:
            sys.modules.pop(spec.name, None)
            raise
        config = {'version': version, 'release': str(release.relative_to(self.directory))}
        if persist:
            with tempfile.NamedTemporaryFile(mode='w', dir=self.directory, delete=False) as stream:
                temp = Path(stream.name)
                json.dump(config, stream, indent=2)
                stream.write('\n')
            try:
                temp.replace(self.directory / 'autoloader.json')
            finally:
                temp.unlink(missing_ok=True)
        self.current = {**config, 'installed_version': installed_version}
        self.handler = handler

    def install(self, version, use_bundle=False):
        validate_version(version)
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('Another release update is in progress')
        release = None
        try:
            releases = self.directory / 'releases'
            releases.mkdir(parents=True, exist_ok=True)
            release = Path(tempfile.mkdtemp(prefix=version + '-', dir=releases))
            bundled_version = self.bundled / 'BUNDLED_VERSION'
            if use_bundle and bundled_version.exists() and bundled_version.read_text().strip() == version:
                for name in ('upstream_host.py', 'UPSTREAM.txt', 'LICENSE.upstream'):
                    shutil.copyfile(self.bundled / name, release / name)
            else:
                fetch_release(version, self.env.get('AUTOLOADER_SHA256', '')
                              if version == self.env.get('AUTOLOADER_VERSION') else '', release)
            self.activate(version, release)
        except Exception:
            if release:
                shutil.rmtree(release)
            raise
        finally:
            self.lock.release()
        return self.status()
