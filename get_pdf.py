#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31"]
# ///
"""
get_pdf.py -- pull one paper's actual PDF out of Mendeley, on demand.

The mirror keeps extracted text, not PDFs. That is the right default: text is
searchable and quotable, and the PDFs are two clicks away in Mendeley. But text
extraction drops figures, structures, and table layout, so sometimes the real
document is the thing you need -- to look at a deposited structure, read a
figure, or check a table.

    uv run --script get_pdf.py Muller2020Yield
    uv run --script get_pdf.py --search "packed bed"      # find the key first
    uv run --script get_pdf.py Bird2021Transport --open   # and open it

The PDF lands in a local cache OUTSIDE the mirror folder, so fetching one does
not push it out to every machine the mirror syncs to. The path is printed on
stdout; hand it to whatever wants to read it.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from mendeley_mirror import (API, DEFAULT_OUT, Mendeley, config_dir,
                                 get_app_config, interactive_authorize, load_json,
                                 mirror_state_dir)
except ImportError:
    sys.exit("get_pdf.py must sit in the same folder as mendeley_mirror.py")

import requests


def cache_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    d = base / "mendeley-mirror" / "pdf"
    d.mkdir(parents=True, exist_ok=True)
    return d


def search_index(out: Path, needle: str) -> list[tuple[str, str]]:
    """Grep the mirror's index for a title, author, or DOI fragment."""
    index = out / "index.md"
    if not index.exists():
        sys.exit(f"No index at {index} -- run mendeley_mirror.py first.")
    hits = []
    for line in index.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        if needle.lower() in line.lower():
            cells = [c.strip() for c in line.strip("|").split("|")]
            hits.append((cells[0].strip("`"), " · ".join(cells[1:4])))
    return hits


def doi_filed(out: Path, dest: Path, key: str) -> Path | None:
    """A PDF that inbox.py filed before this reference had a citation key.

    inbox.py names what it caches after the citation key, but a paper that was
    new to the library has no key until the next refresh, so it gets cached
    under its DOI instead. Pick that file up and rename it rather than
    downloading a second copy of something already on disk.
    """
    index = out / "index.md"
    if not index.exists():
        return None
    for line in index.read_text(encoding="utf-8").splitlines():
        if not line.startswith(f"| `{key}`"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        doi = cells[5] if len(cells) > 5 else ""
        if not doi:
            return None
        cand = dest / (re.sub(r"[^A-Za-z0-9]", "_", doi.lower()) + ".pdf")
        return cand if cand.exists() and cand.stat().st_size > 0 else None
    return None


def open_locally(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as exc:
        print(f"(could not open a viewer: {exc})")


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch specific PDFs from Mendeley on demand.")
    ap.add_argument("keys", nargs="*", help="citation keys, e.g. Muller2020Yield")
    ap.add_argument("--search", metavar="TEXT", help="find citation keys by title/author/DOI")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="mirror directory")
    ap.add_argument("--dest", type=Path, default=None,
                    help=f"where to put the PDFs (default: {cache_dir()})")
    ap.add_argument("--open", action="store_true", dest="open_after",
                    help="open each PDF in the system viewer")
    args = ap.parse_args()

    out = args.out.expanduser()
    if args.search:
        hits = search_index(out, args.search)
        if not hits:
            print(f"nothing matching {args.search!r}")
            return 1
        for key, rest in hits[:40]:
            print(f"{key}\t{rest}")
        if len(hits) > 40:
            print(f"... and {len(hits) - 40} more")
        return 0

    if not args.keys:
        ap.error("give at least one citation key, or --search TEXT")

    keymap = load_json(mirror_state_dir(out) / "citekeys.json", {})
    if not keymap:
        sys.exit("No citation-key map found -- run mendeley_mirror.py first.")
    by_key = {v: k for k, v in keymap.items()}

    dest = (args.dest or cache_dir()).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    # Resolve keys and serve anything already cached BEFORE authenticating, so a
    # typo or a cache hit never triggers a browser login.
    status, wanted = 0, []
    for key in args.keys:
        doc_id = by_key.get(key)
        if not doc_id:
            near = [k for k in by_key if k.lower().startswith(key.lower()[:8])][:5]
            print(f"! unknown citation key {key!r}" + (f" -- did you mean {near}?" if near else ""))
            status = 1
            continue
        target = dest / f"{key}.pdf"
        if not target.exists():
            stray = doi_filed(out, dest, key)
            if stray:
                stray.rename(target)
                print(f"(adopted {stray.name}, filed before {key} had a key)", file=sys.stderr)
        if target.exists() and target.stat().st_size > 0:
            print(target)
            if args.open_after:
                open_locally(target)
            continue
        wanted.append((key, doc_id, target))

    if not wanted:
        return status

    cfg = get_app_config()
    tokens = load_json(config_dir() / "tokens.json", {})
    if not tokens.get("access_token"):
        tokens = interactive_authorize(cfg)
    client = Mendeley(cfg, tokens)

    for key, doc_id, target in wanted:
        resp = client.get(f"{API}/files", accept=None, params={"document_id": doc_id})
        files = resp.json() if resp.ok else []
        pdfs = [f for f in files if "pdf" in (f.get("mime_type") or "").lower()]
        if not pdfs:
            print(f"! {key}: Mendeley has no PDF attached to this reference")
            status = 1
            continue

        resp = client.get(f"{API}/files/{pdfs[0]['id']}", accept="*/*", allow_redirects=False)
        if resp.status_code in (301, 302, 303, 307):
            resp = requests.get(resp.headers["Location"], timeout=180)
        if not resp.ok:
            print(f"! {key}: download failed ({resp.status_code})")
            status = 1
            continue
        target.write_bytes(resp.content)
        print(target)
        if args.open_after:
            open_locally(target)

    return status


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
