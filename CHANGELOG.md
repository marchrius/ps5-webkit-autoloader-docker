# Changelog

User-facing changes are recorded here. Keep the **Unreleased** section and the
relevant README instructions aligned whenever functionality or configuration
changes. Move entries into a dated release section when that release is published.

## Unreleased

No unreleased changes.

## 0.7.0 — 2026-11-15

- Changed the default bundled release from `0.7.0-prerelease-2` to stable `0.7.0`
  across Docker, Compose, and environment examples.
- Pinned the official `0.7.0` host asset and its published SHA-256 digest.
- Added the image version label and the matching repository/image tags:
  `v0.7.0` and `ps5-webkit-autoloader-dns:0.7.0` (local image).
- Existing saved selections remain authoritative; use the web administration page
  or the forced-update environment setting to change an existing deployment.

### Runtime release management

- Added a web administration page at `http://HOST_IP/admin/` to inspect the
  selected release, embedded code version, environment version, and forced-update
  setting. Use the configured `HTTP_PORT` when it differs from 80.
- Added live installation and downgrade to an explicit official release version,
  without restarting DNS. Existing requests can finish on the previous release;
  new connections use the newly activated release.
- Added persistent selection in `/config/autoloader.json` and downloaded release
  files in `/config/releases/`. Both survive container recreation when `/config`
  is mounted persistently.
- Added startup precedence: saved configuration first, then `AUTOLOADER_VERSION`.
- Added `AUTOLOADER_FORCE_UPDATE=false`. When set to `true`, every startup
  downloads `AUTOLOADER_VERSION` again and replaces the saved code and selection
  after validation. Reset it to `false` to resume using the saved release offline.
- Added staged downloads and validation before activation. Failed web updates
  preserve the running release and saved selection. Failed forced startup updates
  preserve the saved files but fail startup rather than silently ignoring the override.
- Added offline initialization from the release bundled in the image when its
  version matches the selected version, and reuse of cached releases on later starts.
- Added checks for conflicting updates and same-origin JSON requests. The admin
  page is available through the server IP or localhost, and is not served through
  the PlayStation entry domains. It has no login and requires a trusted LAN.

### Deployment changes

- Changed the Compose `/config` mount from read-only to writable. Custom
  deployments must also provide a persistent writable `/config` mount.
- Passed `AUTOLOADER_SHA256` and `AUTOLOADER_FORCE_UPDATE` into the runtime.
  The optional checksum applies to downloads of the environment-selected version;
  other versions use their pinned or published release digest when available.
- Extended the startup healthcheck grace period to allow a runtime download.
- Excluded persisted selection and downloaded releases from Git and Docker builds.

See [Release updates](README.md#release-updates) for configuration, usage,
provenance, backup, and failure behavior.
