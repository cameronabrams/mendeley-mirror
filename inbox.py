#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31", "pymupdf>=1.24"]
# ///
"""
inbox.py -- drop a PDF in, get a filed Mendeley reference out.

Save a paper into inbox/ straight from the browser, under whatever name the
publisher gave it, then:

    uv run --script inbox.py --dry-run    # what it thinks each PDF is
    uv run --script inbox.py              # file them (asks first)

For each PDF it works out which paper it is, finds the matching reference in
Mendeley or creates one from Crossref, uploads the PDF as an attachment, and
moves the file out of the folder into the local PDF cache -- outside the
mirror, so it is not synced to every machine. The next refresh extracts the
text like any other reference.

Grey literature -- DTIC/NTIS reports, theses, conference proceedings -- often
has no DOI to identify it by. For those, drop a sidecar JSON next to the PDF
with the same stem (report.pdf + report.json) holding the Mendeley fields:

    {"type": "report", "title": "...", "year": 1991,
     "source": "NRL Memorandum Report 6848 (DTIC ADA239276)",
     "authors": [{"first_name": "Arthur W.", "last_name": "Snow"}]}

A sidecar overrides identification entirely; nothing is looked up.

Identification, in order, stopping at the first candidate that checks out:

    the DOI in the file name, if you renamed it that way
    the DOI in the PDF's own metadata
    a DOI printed on the first two pages
    a Crossref search on the text of the first page

Every candidate is verified before it is used: the title Crossref returns has
to actually appear on the PDF's first page. A PDF that cannot be identified
that way is left in the inbox and reported, because attaching a paper to the
wrong reference is worse than not filing it.

This is the one script here besides mendeley_push.py that WRITES to Mendeley.
It asks before sending unless you pass --yes.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import pymupdf
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from mendeley_mirror import (API, DEFAULT_OUT, Mendeley, config_dir,
                                 get_app_config, load_json, mirror_state_dir)
    from mendeley_push import CSL_TO_MENDELEY, DOC_CT, one, split_name
    from get_pdf import cache_dir
except ImportError as exc:
    sys.exit(f"inbox.py must sit beside the other mirror scripts ({exc})")

FILE_CT = "application/vnd.mendeley-file.1+json"
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>,;)\]}]+", re.I)
UA = "mendeley-mirror inbox.py (mailto:cfa22@drexel.edu)"

STOP = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on",
        "or", "the", "to", "with", "its", "their", "using", "via"}


def deaccent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def words(s: str) -> set:
    return {w for w in re.sub(r"[^a-z0-9 ]+", " ", deaccent(s or "").lower()).split()
            if len(w) > 3 and w not in STOP}


def clean_doi(raw: str) -> str:
    # Publishers often run the DOI straight into the next word on a wrapped
    # line; trailing punctuation is the only part we can safely trim.
    return raw.strip().rstrip(".,;:)]}>").lower()


def filename_dois(name: str) -> list[str]:
    """DOIs written into a file name, where "/" cannot appear literally.

    Saving as 10.1021_acspolymersau.5c00022.pdf is the usual dodge, so treat
    the first separator after the registrant prefix as the slash.
    """
    name = re.sub(r"\.pdf$", "", name, flags=re.I)     # not part of the DOI
    out = [clean_doi(m) for m in DOI_RE.findall(name)]
    for m in re.findall(r"\b10\.\d{4,9}[_-][^\s/]+", name, re.I):
        head, sep, tail = m.partition("_") if "_" in m else m.partition("-")
        out.append(clean_doi(f"{head}/{tail}"))
    return out


# --------------------------------------------------------------------------
# reading the PDF
# --------------------------------------------------------------------------

def pdf_text(path: Path, pages: int = 2) -> str:
    with pymupdf.open(path) as doc:
        return " ".join(doc[i].get_text() for i in range(min(pages, doc.page_count)))


def pdf_metadata_dois(path: Path) -> list[str]:
    out = []
    with pymupdf.open(path) as doc:
        blob = " ".join(str(v) for v in (doc.metadata or {}).values() if v)
        try:
            blob += " " + (doc.get_xml_metadata() or "")
        except Exception:
            pass
    out += [clean_doi(m) for m in DOI_RE.findall(blob)]
    return out


def normalize(raw: dict) -> dict:
    """Both metadata shapes, reduced to the fields a Mendeley record needs."""
    parts = ((raw.get("issued") or {}).get("date-parts") or [[None]])[0]
    return {
        # Share the pusher's type map so a book filed through the inbox is a
        # book, not a journal article.
        "type": CSL_TO_MENDELEY.get((raw.get("type") or "").lower(), "generic"),
        "publisher": one(raw.get("publisher")),
        "doi": (raw.get("DOI") or raw.get("doi") or "").lower(),
        "title": one(raw.get("title")),
        "source": one(raw.get("container-title")),
        "year": parts[0] if parts and parts[0] else None,
        "volume": one(raw.get("volume")),
        "issue": one(raw.get("issue")),
        "pages": one(raw.get("page")),
        "authors": [
            {"first_name": a.get("given", ""), "last_name": a.get("family", "")}
            for a in (raw.get("author") or []) if a.get("family")
        ],
    }


def resolve_doi(doi: str) -> dict | None:
    """Metadata for any DOI, whoever registered it.

    doi.org routes to the owning agency, so this answers for OSTI reports and
    Zenodo deposits that api.crossref.org returns 404 for.
    """
    r = requests.get(f"https://doi.org/{doi}", allow_redirects=True, timeout=60,
                     headers={"Accept": "application/vnd.citationstyles.csl+json",
                              "User-Agent": UA})
    if r.status_code != 200 or "json" not in (r.headers.get("Content-Type") or ""):
        return None
    try:
        return normalize(r.json())
    except ValueError:
        return None


def crossref_search(text: str) -> dict | None:
    """Ask Crossref what paper this first page belongs to."""
    query = " ".join(text.split()[:60])
    r = requests.get("https://api.crossref.org/works",
                     params={"query.bibliographic": query, "rows": 3},
                     headers={"User-Agent": UA}, timeout=60)
    if r.status_code != 200:
        return None
    items = r.json()["message"].get("items") or []
    return normalize(items[0]) if items else None


def title_of(meta: dict) -> str:
    return meta.get("title", "")


def looks_right(msg: dict, page_text: str) -> bool:
    """Does the paper this metadata describes actually match this PDF?"""
    title = title_of(msg)
    if not title:
        return False
    tw = words(title)
    if not tw:
        return False
    return len(tw & words(page_text)) / len(tw) >= 0.6


def read_sidecar(path: Path) -> dict | None:
    """Hand-written metadata for a PDF that no registry can identify."""
    side = path.with_suffix(".json")
    if not side.exists():
        return None
    try:
        meta = json.loads(side.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RuntimeError(f"{side.name} is not valid JSON: {exc}") from None
    if not meta.get("title"):
        raise RuntimeError(f"{side.name} has no title")
    meta.setdefault("type", "report")
    meta.setdefault("authors", [])
    meta.setdefault("doi", "")
    for k in ("source", "volume", "issue", "pages"):
        meta.setdefault(k, "")
    return meta


def identify(path: Path) -> tuple[dict | None, str, str]:
    """Return (crossref message, doi, how) or (None, '', reason)."""
    side = read_sidecar(path)
    if side:
        return side, side.get("doi", "").lower(), f"sidecar {path.stem}.json"
    try:
        # DOIs are extracted from the first two pages only -- looking further
        # starts picking them out of reference lists. But the title is verified
        # against the first eight, because books and reports carry front matter
        # and their title page is rarely the first sheet. A wider verification
        # window can only confirm, never mislead.
        page1 = pdf_text(path, 2)
        front = pdf_text(path, 8)
    except Exception as exc:
        return None, "", f"cannot read the PDF ({exc})"

    tried: list[str] = []
    sources = [
        ("file name", filename_dois(path.name)),
        ("PDF metadata", pdf_metadata_dois(path)),
        ("first pages", [clean_doi(m) for m in DOI_RE.findall(page1)][:6]),
    ]
    for how, cands in sources:
        for doi in cands:
            if doi in tried:
                continue
            tried.append(doi)
            meta = resolve_doi(doi)
            if not meta:
                continue
            # A DOI written into the file name is a deliberate act, so trust it
            # even when the PDF is a scan with no text to check it against.
            if looks_right(meta, front) or (how == "file name" and len(front.strip()) < 200):
                return meta, doi.lower(), how + (" (unverified: no text in the PDF)"
                                                 if not looks_right(meta, front) else "")

    msg = crossref_search(page1)
    if msg and looks_right(msg, front):
        return msg, msg["doi"], "crossref title search"

    if tried:
        return None, "", ("found DOIs but none matched the text on page 1: "
                          + ", ".join(tried[:3]))
    if len(page1.strip()) < 200:
        return None, "", ("this PDF is a scan with no text layer, so there is nothing "
                          "to identify it by -- rename it to its DOI, e.g. "
                          "10.2172_219366.pdf, and run again")
    return None, "", "no DOI in the file name, the metadata, or the first two pages"


# --------------------------------------------------------------------------
# talking to Mendeley
# --------------------------------------------------------------------------

def existing_document(out: Path, doi: str, title: str = "") -> tuple[str, str]:
    """(mendeley id, citekey) for a reference already in the library, else ('','')."""
    bib = (out / "library.bib").read_text(encoding="utf-8") if (out / "library.bib").exists() else ""
    key = ""
    if not doi:
        # No DOI to match on -- fall back to an exact normalized title match.
        want = " ".join(words(title))
        for chunk in re.split(r"\n@", bib)[1:]:
            m = re.search(r"title\s*=\s*\{+(.*?)\}+,?\s*$", chunk, re.M | re.S)
            if m and " ".join(words(m.group(1))) == want and want:
                k = re.match(r"\w+\{([^,]+),", chunk)
                key = k.group(1).strip() if k else ""
                break
    for chunk in re.split(r"\n@", bib)[1:]:
        if doi and re.search(rf"doi\s*=\s*\{{{re.escape(doi)}\}}", chunk, re.I):
            m = re.match(r"\w+\{([^,]+),", chunk)
            key = m.group(1).strip() if m else ""
            break
    if not key:
        return "", ""
    keymap = load_json(mirror_state_dir(out) / "citekeys.json", {})
    for doc_id, citekey in keymap.items():
        if citekey == key:
            return doc_id, key
    return "", key


def remote_doi_index(client: Mendeley) -> dict[str, str]:
    """Every DOI in Mendeley right now, mapped to its document id.

    library.bib only knows what the last refresh saw. A reference pushed since
    then -- or added on another machine -- is absent from it, and creating a
    second record for it would leave a duplicate in the library that nothing
    here can clean up. So ask Mendeley itself before creating anything.
    """
    index = {}
    for doc in client.paged("/documents", "documents", quiet=True):
        doi = ((doc.get("identifiers") or {}).get("doi") or "").strip().lower()
        if doi:
            index[doi] = doc["id"]
    return index


def has_attachment(client: Mendeley, doc_id: str) -> bool:
    resp = client.get(f"{API}/files", accept=None, params={"document_id": doc_id})
    files = resp.json() if resp.ok else []
    return any("pdf" in (f.get("mime_type") or "").lower() for f in files)


def create_document(client: Mendeley, meta: dict) -> str:
    if meta["doi"].startswith("10.48550/arxiv"):
        # arXiv DOIs resolve with no container title; match the push script's
        # convention so the entry is not left journal-less.
        meta["source"] = meta.get("source") or "arXiv"
    doc = {
        "type": meta.get("type", "journal"),
        "title": meta["title"],
        "authors": meta["authors"],
        "year": meta["year"],
        "source": meta["source"],
        "identifiers": {k: v for k, v in (("doi", meta["doi"]),) if v},
        "publisher": meta.get("publisher", ""),
        "volume": meta["volume"],
        "issue": meta["issue"],
        "pages": meta["pages"],
    }
    doc = {k: v for k, v in doc.items() if v not in (None, "", [], {})}
    resp = client.session.post(
        f"{API}/documents",
        headers={**client._auth_header(), "Content-Type": DOC_CT, "Accept": DOC_CT},
        data=json.dumps(doc), timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Mendeley refused the new reference "
                           f"({resp.status_code}): {resp.text[:200]}")
    return resp.json()["id"]


def upload(client: Mendeley, doc_id: str, path: Path) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", path.name)
    headers = {
        **client._auth_header(),
        "Content-Type": "application/pdf",
        "Accept": FILE_CT,
        "Content-Disposition": f'attachment; filename="{safe}"',
        "Link": f'<{API}/documents/{doc_id}>; rel="document"',
    }
    resp = client.session.post(f"{API}/files", headers=headers,
                               data=path.read_bytes(), timeout=300)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"upload refused ({resp.status_code}): {resp.text[:200]}")
    return resp.json().get("id", "")


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="File PDFs dropped in inbox/ into Mendeley.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="mirror directory")
    ap.add_argument("--dry-run", action="store_true", help="identify only, send nothing")
    ap.add_argument("--yes", action="store_true", help="do not ask before sending")
    ap.add_argument("--keep", action="store_true",
                    help="leave the PDFs in inbox/ instead of moving them to the cache")
    ap.add_argument("--replace", action="store_true",
                    help="attach even if the reference already has a PDF")
    args = ap.parse_args()

    out = args.out.expanduser()
    box = out / "inbox"
    box.mkdir(exist_ok=True)
    pdfs = sorted(p for p in box.glob("*.pdf") if p.is_file())
    if not pdfs:
        print(f"nothing to file -- drop PDFs in {box}")
        return 0

    print(f"{len(pdfs)} PDF(s) in {box}\n")
    plan = []
    for path in pdfs:
        try:
            msg, doi, how = identify(path)
        except RuntimeError as exc:
            print(f"  ! {path.name}\n      {exc}")
            continue
        if not msg:
            print(f"  ? {path.name}\n      cannot identify: {how}")
            continue
        doc_id, key = existing_document(out, doi, msg.get('title', ''))
        where = f"already in the library as {key}" if key else "new to the library"
        print(f"  - {path.name}")
        print(f"      {title_of(msg)[:90]}")
        print(f"      {doi}  ({how}; {where})")
        plan.append((path, msg, doi, doc_id, key))

    if not plan:
        return 1
    if args.dry_run:
        print("\n--dry-run: nothing sent.")
        return 0

    tokens = load_json(config_dir() / "tokens.json", {})
    if not tokens.get("access_token"):
        sys.exit("no Mendeley tokens on this machine -- run ./run_mirror.sh once first.")

    if not args.yes:
        reply = input(f"\nFile {len(plan)} PDF(s) into Mendeley? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.")
            return 0

    client = Mendeley(get_app_config(), tokens)
    dest = cache_dir()
    status = 0
    remote: dict[str, str] | None = None
    for path, msg, doi, doc_id, key in plan:
        try:
            if not doc_id and doi:
                if remote is None:
                    print("  (checking Mendeley for references the mirror has not seen yet)")
                    remote = remote_doi_index(client)
                doc_id = remote.get(doi, "")
                if doc_id:
                    print(f"  = {doi} is already in Mendeley, just not mirrored yet")
            if not doc_id:
                doc_id = create_document(client, msg)
                print(f"  + created reference for {doi}")
            elif has_attachment(client, doc_id) and not args.replace:
                print(f"  = {key} already has a PDF attached; skipping (--replace to override)")
                continue
            upload(client, doc_id, path)
            print(f"  ✓ attached {path.name} -> {key or doi}")
            if not args.keep:
                # Prefer the citation key; fall back to the DOI, then to the
                # file's own name -- a sidecar-identified report has neither of
                # the first two, and an empty stem would give a nameless file.
                stem = key or re.sub(r"[^A-Za-z0-9]", "_", doi) or path.stem
                target = dest / f"{stem}.pdf"
                shutil.move(str(path), target)
                print(f"    moved out of the inbox to {target}")
                side = path.with_suffix(".json")
                if side.exists():
                    shutil.move(str(side), dest / f"{stem}.json")
        except Exception as exc:
            print(f"  ! {path.name}: {exc}")
            status = 1

    print("\nRun ./run_mirror.sh to pull the extracted text down.")
    return status


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
