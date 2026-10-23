"""Download the official self-contained host, not the incomplete source frontend."""
import ast
import hashlib
import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path


def release_asset(version):
    api = f"https://api.github.com/repos/itsPLK/ps5-webkit-autoloader/releases/tags/v{version}"
    request = urllib.request.Request(api, headers={"User-Agent": "ps5-autoloader-docker"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.load(response)
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code == 404:
            raise ValueError(
                f"Release v{version} non pubblicata su GitHub. Correggi AUTOLOADER_VERSION "
                "in .env; consulta https://github.com/itsPLK/ps5-webkit-autoloader/releases"
            ) from None
        raise ValueError(f"Impossibile verificare la release: GitHub API HTTP {exc.code}") from None
    assets = [asset for asset in release.get("assets", [])
              if asset["name"].startswith("webkit-autoloader-host")
              and asset["name"].endswith(".py")]
    if len(assets) != 1:
        raise ValueError(f"Release v{version}: atteso un solo host Python; trovati {len(assets)}")
    return assets[0]


def main(version, expected_hash, output_dir=Path("/app")):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("AUTOLOADER_VERSION deve essere una release stabile, es. 0.5.2")
    if expected_hash and not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
        raise ValueError("AUTOLOADER_SHA256 non valido")
    asset = release_asset(version)
    url = asset["browser_download_url"]
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if expected_hash and digest != expected_hash.lower():
        raise ValueError(f"SHA-256 inatteso: {digest}")
    published_digest = asset.get("digest")
    if published_digest and published_digest != f"sha256:{digest}":
        raise ValueError("SHA-256 diverso dal digest pubblicato da GitHub")
    tree = ast.parse(data)
    # Fail build if a source-only host (without payloads) was downloaded.
    embedded = any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "EMBEDDED_ZIP_B64" for t in node.targets)
        and isinstance(node.value, ast.Constant) and bool(node.value.value)
        for node in tree.body
    )
    if not embedded:
        raise ValueError("La release non contiene il frontend incorporato")
    output_dir.joinpath("upstream_host.py").write_bytes(data)
    output_dir.joinpath("UPSTREAM.txt").write_text(f"{url}\nsha256={digest}\n")
    # Keep the upstream license alongside the downloaded distribution.
    with urllib.request.urlopen(
        f"https://raw.githubusercontent.com/itsPLK/ps5-webkit-autoloader/v{version}/LICENSE",
        timeout=30,
    ) as response:
        output_dir.joinpath("LICENSE.upstream").write_bytes(response.read())
    print(f"Downloaded official host v{version}; sha256={digest}")


if __name__ == "__main__":
    try:
        main(*sys.argv[1:])
    except (ValueError, urllib.error.URLError) as exc:
        sys.exit(f"Download autoloader fallito: {exc}")
