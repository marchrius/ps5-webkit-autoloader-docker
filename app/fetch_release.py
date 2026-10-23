"""Download the official self-contained host, not the incomplete source frontend."""
import ast
import hashlib
import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path


# Verified official release assets. These immutable URLs do not need the GitHub
# REST API, whose anonymous quota is shared by every build on the same public IP.
PINNED_RELEASES = {
    "0.5.2": "6421f167d01ff1c0f3c8c2df1bf0e656691837b938aa924b3d2426c05ec2b7bf",
    "0.6.1": "722798faaf82d733e00a7ad2658d21323ec22b70755c74018ed5e6ca164fd2c0",
}
REPOSITORY = "https://github.com/itsPLK/ps5-webkit-autoloader"


def release_asset(version):
    if version in PINNED_RELEASES:
        name = f"webkit-autoloader-host_v{version}.py"
        return {"name": name, "digest": f"sha256:{PINNED_RELEASES[version]}",
                "browser_download_url": f"{REPOSITORY}/releases/download/v{version}/{name}"}
    api = f"https://api.github.com/repos/itsPLK/ps5-webkit-autoloader/releases/tags/v{version}"
    request = urllib.request.Request(api, headers={"User-Agent": "ps5-autoloader-docker"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.load(response)
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code == 404:
            raise ValueError(
                f"Release v{version} is not published on GitHub. Correct AUTOLOADER_VERSION "
                "in .env; see https://github.com/itsPLK/ps5-webkit-autoloader/releases"
            ) from None
        raise ValueError(f"Cannot verify release: GitHub API HTTP {exc.code}") from None
    assets = [asset for asset in release.get("assets", [])
              if asset["name"].startswith("webkit-autoloader-host")
              and asset["name"].endswith(".py")]
    if len(assets) != 1:
        raise ValueError(f"Release v{version}: expected exactly one Python host; found {len(assets)}")
    return assets[0]


def download(url, description, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": "ps5-autoloader-docker"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ValueError(f"{description}: HTTP {exc.code} for {url}") from None
    except urllib.error.URLError as exc:
        raise ValueError(f"{description}: {exc.reason} ({url})") from None


def main(version, expected_hash, output_dir=Path("/app")):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("AUTOLOADER_VERSION must be a stable release, e.g. 0.6.1")
    if expected_hash and not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
        raise ValueError("Invalid AUTOLOADER_SHA256")
    asset = release_asset(version)
    url = asset["browser_download_url"]
    data = download(url, "Release asset download failed", timeout=120)
    digest = hashlib.sha256(data).hexdigest()
    if expected_hash and digest != expected_hash.lower():
        raise ValueError(f"Unexpected SHA-256: {digest}")
    published_digest = asset.get("digest")
    if published_digest and published_digest != f"sha256:{digest}":
        raise ValueError("SHA-256 differs from the verified release digest")
    tree = ast.parse(data)
    # Fail build if a source-only host (without payloads) was downloaded.
    embedded = any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "EMBEDDED_ZIP_B64" for t in node.targets)
        and isinstance(node.value, ast.Constant) and bool(node.value.value)
        for node in tree.body
    )
    if not embedded:
        raise ValueError("The release does not contain the embedded frontend")
    output_dir.joinpath("upstream_host.py").write_bytes(data)
    output_dir.joinpath("UPSTREAM.txt").write_text(f"{url}\nsha256={digest}\n")
    # Keep the upstream license alongside the downloaded distribution.
    license_data = download(
        f"https://raw.githubusercontent.com/itsPLK/ps5-webkit-autoloader/v{version}/LICENSE",
        "Upstream license download failed", timeout=30,
    )
    output_dir.joinpath("LICENSE.upstream").write_bytes(license_data)
    print(f"Downloaded official host v{version}; sha256={digest}")


if __name__ == "__main__":
    try:
        main(*sys.argv[1:])
    except (ValueError, urllib.error.URLError, TimeoutError) as exc:
        sys.exit(f"Autoloader download failed: {exc}")
