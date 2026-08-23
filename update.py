"""Self-updater: fetch the latest code from GitHub before each launch.

Run by SC2Copilot.bat with the venv's python. Stdlib only - it must work
before/without the package being installed. Fail-soft everywhere: any
network or filesystem hiccup means "run the version we already have".

Flow: download the branch zip (small) and hash it; if the hash differs
from the one recorded at last update, copy the zip's contents over this
folder (never touching .venv or user data - builds/settings live in
~/SC2Copilot), reinstall, and record the hash. No GitHub API involved -
just the same codeload host the original manual download used.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

OWNER = "surajmsd1"
REPO = "StarCraft2-copilot"
BRANCH = "claude/sc2-build-creator-optimizer-8htybu"

APP_DIR = Path(__file__).resolve().parent
STAMP = APP_DIR / ".venv" / "last_update_sha.txt"
PRESERVE = {".venv", ".git"}


def download_branch_zip() -> bytes:
    url = f"https://codeload.github.com/{OWNER}/{REPO}/zip/refs/heads/{BRANCH}"
    request = urllib.request.Request(url, headers={"User-Agent": "sc2copilot-updater"})
    with urllib.request.urlopen(request, timeout=60) as resp:
        return resp.read()


def content_digest(archive: zipfile.ZipFile) -> str:
    """Digest of the archive's contents (paths + CRCs), stable across
    re-generated zips of the same commit."""
    h = hashlib.sha256()
    for info in sorted(archive.infolist(), key=lambda i: i.filename):
        h.update(f"{info.filename}:{info.CRC}\n".encode("utf-8"))
    return h.hexdigest()


def apply(archive: zipfile.ZipFile) -> None:
    names = archive.namelist()
    root = names[0].split("/")[0]  # single top-level folder in GitHub zips
    for name in names:
        if not name.startswith(root):
            continue
        rel = Path(name).relative_to(root)
        if rel.parts and rel.parts[0] in PRESERVE:
            continue
        target = APP_DIR / rel
        if name.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def main() -> int:
    try:
        data = download_branch_zip()
    except Exception:
        print("Update check skipped (offline or GitHub unreachable).")
        return 0
    archive = zipfile.ZipFile(io.BytesIO(data))
    digest = content_digest(archive)
    current = STAMP.read_text().strip() if STAMP.exists() else ""
    if digest == current:
        return 0
    print("Updating to the latest version...")
    try:
        apply(archive)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", str(APP_DIR)],
            check=True, timeout=600,
        )
        STAMP.write_text(digest)
        print("Updated.")
    except Exception as exc:
        print(f"Update failed ({exc}); starting the current version.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
