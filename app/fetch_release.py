"""Download the official self-contained host, not the incomplete source frontend."""
import ast
import hashlib
import re
import sys
import urllib.request
from pathlib import Path


def main(version, expected_hash):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("AUTOLOADER_VERSION deve essere una release stabile, es. 0.5.2")
    if expected_hash and not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
        raise ValueError("AUTOLOADER_SHA256 non valido")
    base = "https://github.com/itsPLK/ps5-webkit-autoloader"
    url = f"{base}/releases/download/v{version}/webkit-autoloader-host_v{version}.py"
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if expected_hash and digest != expected_hash.lower():
        raise ValueError(f"SHA-256 inatteso: {digest}")
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
    Path("/app/upstream_host.py").write_bytes(data)
    Path("/app/UPSTREAM.txt").write_text(f"{url}\nsha256={digest}\n")
    # Keep the upstream license alongside the downloaded distribution.
    with urllib.request.urlopen(
        f"https://raw.githubusercontent.com/itsPLK/ps5-webkit-autoloader/v{version}/LICENSE",
        timeout=30,
    ) as response:
        Path("/app/LICENSE.upstream").write_bytes(response.read())
    print(f"Downloaded official host v{version}; sha256={digest}")


if __name__ == "__main__":
    main(*sys.argv[1:])
