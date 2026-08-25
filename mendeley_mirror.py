#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31", "pymupdf>=1.24"]
# ///
"""
mendeley_mirror.py -- mirror a Mendeley library to a plain folder.

Run it with uv and the dependency below is installed automatically into a
cached, throwaway environment:  uv run --script mendeley_mirror.py

Produces, in the output directory:

    library.bib          BibTeX for the whole library, with stable citation keys
    index.md             one-line-per-reference index (fast to grep / skim)
    folders.json         Mendeley collections -> citation keys
    text/<citekey>.md    full text extracted from the PDF, with page markers
    annotations/<citekey>.md   your highlights and sticky notes, by page
    extraction-report.md what came out empty, and why that is probably so

By default each attachment is downloaded, its text extracted, and the PDF then
discarded -- Mendeley remains the place to actually read papers. `--attachments
keep` keeps the PDFs as well; `--attachments none` skips them entirely.

Credentials and tokens live OUTSIDE the output folder, in
%LOCALAPPDATA%\\mendeley-mirror (Windows) or ~/.config/mendeley-mirror (POSIX),
so a synced output folder never carries your secrets.

First run walks you through OAuth in a browser.  Later runs are silent.

Usage:
    python mendeley_mirror.py                  # full mirror
    python mendeley_mirror.py --no-pdfs        # metadata + annotations only
    python mendeley_mirror.py --out D:/refs    # override output directory
    python mendeley_mirror.py --reauth         # forget tokens, log in again
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit(
        "This script needs 'requests'. Either run it through uv, which installs\n"
        "it for you --   uv run --script mendeley_mirror.py   -- or install it\n"
        "into the interpreter you are using:   pip install requests"
    )

API = "https://api.mendeley.com"
AUTHORIZE_URL = f"{API}/oauth/authorize"
TOKEN_URL = f"{API}/oauth/token"
DEFAULT_REDIRECT = "http://localhost:8888/callback"

# Documented page-size ceilings differ per collection; annotations reject 500.
PAGE_LIMITS = {"documents": 500, "files": 500, "folders": 500, "annotations": 200}

ACCEPT = {
    "documents": "application/vnd.mendeley-document.1+json",
    "files": "application/vnd.mendeley-file.1+json",
    "annotations": "application/vnd.mendeley-annotation.1+json",
    "folders": "application/vnd.mendeley-folder.1+json",
}

DEFAULT_OUT = Path.home() / "Sync" / "mendeley"

# Set by --quiet, for scheduled runs: no progress spam, no prompts that would
# block forever with nobody at the keyboard.
QUIET = False
NONINTERACTIVE = False
LOG: list = []


def note(msg: str = "") -> None:
    """A milestone worth keeping in the log."""
    LOG.append(msg)
    if not QUIET:
        print(msg)


def progress(msg: str) -> None:
    """Transient in-place progress; never logged."""
    if not QUIET:
        print(msg, end="\r", flush=True)


def require_interactive(what: str) -> None:
    if NONINTERACTIVE:
        sys.exit(
            f"{what} needs a person at the keyboard, and this is a scheduled run.\n"
            "Run mendeley_mirror.py by hand once to sort it out."
        )


# --------------------------------------------------------------------------
# credential storage
# --------------------------------------------------------------------------

def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "mendeley-mirror"
    d.mkdir(parents=True, exist_ok=True)
    return d


def mirror_state_dir(out: Path) -> Path:
    """Bookkeeping that belongs to the mirror, not to the machine.

    Citation keys and per-file extraction state live beside the mirrored files
    so that a synced folder carries them between machines: the Linux box then
    agrees with the Windows box about what `Muller2020Yield` means, and does not
    re-download 2500 PDFs to rebuild text it already has. Credentials stay
    machine-local, in config_dir().
    """
    d = out / ".mirror"
    d.mkdir(parents=True, exist_ok=True)
    for name in ("citekeys.json", "state.json"):
        old, new = config_dir() / name, d / name
        if old.exists() and not new.exists():  # migrate from the old location
            new.write_text(old.read_text(encoding="utf-8"), encoding="utf-8")
            note(f"  moved {name} into the mirror so other machines share it")
    return d


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def get_app_config(force_prompt: bool = False) -> dict:
    path = config_dir() / "config.json"
    cfg = load_json(path, {})
    if force_prompt or not cfg.get("client_id") or not cfg.get("client_secret"):
        require_interactive("Entering app credentials")
        print("\nApp credentials.  Register at https://dev.mendeley.com/myapps.html")
        print(f"The app's Redirection URL must be exactly:  {DEFAULT_REDIRECT}\n")
        print("The application ID is the short NUMBER shown next to the app in the")
        print("list (e.g. 21534) -- not the app name and not the secret.\n")
        cfg["client_id"] = input("Application ID (number): ").strip()
        cfg["client_secret"] = input("Application secret: ").strip()
        redirect = input(f"Redirection URL [{DEFAULT_REDIRECT}]: ").strip()
        cfg["redirect_uri"] = redirect or DEFAULT_REDIRECT
        save_json(path, cfg)
        print(f"\nSaved to {path}\n")
    cfg.setdefault("redirect_uri", DEFAULT_REDIRECT)

    if not cfg["client_id"].isdigit():
        print(f"\n  ! The application ID on file is {cfg['client_id']!r}, which is not a")
        print("    number. Mendeley application IDs are numeric; this is the single")
        print("    most common cause of 'Client authentication failed'.")
        print("    Re-run with --reconfigure to correct it.\n")
    return cfg


# --------------------------------------------------------------------------
# OAuth 2.0 authorization-code flow over a loopback redirect
# --------------------------------------------------------------------------

class _CallbackHandler(BaseHTTPRequestHandler):
    code = None
    error = None
    state = None

    def do_GET(self):  # noqa: N802
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        _CallbackHandler.code = (params.get("code") or [None])[0]
        _CallbackHandler.error = (params.get("error") or [None])[0]
        _CallbackHandler.state = (params.get("state") or [None])[0]
        body = (
            b"<html><body style='font-family:sans-serif;padding:3em'>"
            b"<h2>Mendeley mirror</h2><p>Authorized. You can close this tab and "
            b"return to the terminal.</p></body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence the default stderr logging
        pass


def _basic_auth(cfg: dict) -> str:
    raw = f"{cfg['client_id']}:{cfg['client_secret']}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


AUTH_HELP = """
Mendeley showed an error instead of the authorization prompt. Its wording is
unhelpfully generic; in practice it is nearly always one of these:

  1. The application ID is not the numeric ID from the app list.
  2. The Redirection URL registered at dev.mendeley.com/myapps.html is not
     character-for-character equal to the one above -- a trailing slash, https
     instead of http, or a different port is enough to break it.
  3. The app was only half-registered: no secret was ever generated, or the
     form was not submitted.

Fix the registration, then re-run with  --reconfigure  to re-enter the values.
"""


def interactive_authorize(cfg: dict) -> dict:
    require_interactive("Browser authorization")
    parsed = urllib.parse.urlparse(cfg["redirect_uri"])
    port = parsed.port or 80
    state = base64.urlsafe_b64encode(os.urandom(9)).decode("ascii")
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": "all",
        "state": state,
    }
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)
    print("Authorizing with these values -- they must match your registered app:")
    print(f"  application ID : {cfg['client_id']}")
    print(f"  redirect URL   : {cfg['redirect_uri']}")
    print(f"  secret         : {'set, ' + str(len(cfg['client_secret'])) + ' chars' if cfg.get('client_secret') else 'MISSING'}")
    print(f"\nOpening your browser. If it does not open, paste this in:\n{url}\n")
    webbrowser.open(url)

    server = HTTPServer(("localhost", port), _CallbackHandler)
    server.timeout = 20
    deadline = time.time() + 300
    while _CallbackHandler.code is None and _CallbackHandler.error is None:
        if time.time() > deadline:
            server.server_close()
            print(AUTH_HELP)
            sys.exit("Timed out waiting for the browser redirect.")
        server.handle_request()
    server.server_close()

    if _CallbackHandler.error:
        print(AUTH_HELP)
        sys.exit(f"Authorization failed: {_CallbackHandler.error}")
    if _CallbackHandler.state != state:
        sys.exit("State mismatch on the redirect; aborting rather than trusting it.")

    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": _CallbackHandler.code,
                "redirect_uri": cfg["redirect_uri"],
                # sent in the body as well as the header: harmless, and it rescues
                # setups where the Authorization header is stripped in transit
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
            },
            headers={
                "Authorization": _basic_auth(cfg),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        sys.exit(f"Could not reach {TOKEN_URL}: {exc}")
    if resp.status_code != 200:
        print(f"\nToken exchange failed ({resp.status_code}): {resp.text[:500]}")
        print(AUTH_HELP)
        sys.exit(1)
    return _store_tokens(resp.json())


def _store_tokens(tok: dict) -> dict:
    tok["expires_at"] = time.time() + float(tok.get("expires_in", 3600)) - 60
    save_json(config_dir() / "tokens.json", tok)
    return tok


def refresh_tokens(cfg: dict, tok: dict) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": tok["refresh_token"],
            "redirect_uri": cfg["redirect_uri"],
        },
        headers={"Authorization": _basic_auth(cfg)},
        timeout=30,
    )
    if resp.status_code != 200:
        note("Refresh token rejected; re-authorizing in the browser.")
        return interactive_authorize(cfg)  # exits with guidance on a scheduled run
    new = resp.json()
    new.setdefault("refresh_token", tok["refresh_token"])
    return _store_tokens(new)


class Mendeley:
    """Thin authenticated client with pagination and 401/429 handling."""

    def __init__(self, cfg: dict, tokens: dict):
        self.cfg = cfg
        self.tokens = tokens
        self.session = requests.Session()

    def _auth_header(self) -> dict:
        if time.time() >= self.tokens.get("expires_at", 0):
            self.tokens = refresh_tokens(self.cfg, self.tokens)
        return {"Authorization": f"Bearer {self.tokens['access_token']}"}

    def get(self, url: str, accept: str | None = None, params=None, **kw):
        for attempt in range(5):
            headers = self._auth_header()
            if accept:
                headers["Accept"] = accept
            resp = self.session.get(url, headers=headers, params=params, timeout=60, **kw)
            if resp.status_code == 401 and attempt == 0:
                self.tokens = refresh_tokens(self.cfg, self.tokens)
                continue
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 5)) * (attempt + 1)
                note(f"  rate limited, waiting {wait}s")
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            return resp
        resp.raise_for_status()
        return resp

    def paged(self, path: str, kind: str, params=None, quiet: bool = False) -> list:
        """Follow RFC 5988 Link: rel="next" until the collection is exhausted."""
        out, url = [], API + path
        params = dict(params or {})
        params.setdefault("limit", PAGE_LIMITS.get(kind, 200))
        while url:
            resp = self.get(url, accept=ACCEPT.get(kind), params=params)
            if resp.status_code == 400 and params and params.get("limit", 0) > 50:
                # some collections cap page size below the documented maximum;
                # back off rather than losing the whole run
                params["limit"] //= 4
                note(f"  {kind}: server rejected that page size, retrying at "
                     f"limit={params['limit']}")
                continue
            if not resp.ok:
                raise RuntimeError(
                    f"{kind}: {resp.status_code} from {resp.url}\n  {resp.text[:300]}"
                )
            batch = resp.json()
            if not isinstance(batch, list):
                batch = [batch]
            out.extend(batch)
            url = _next_link(resp.headers.get("Link", ""))
            params = None  # the next-link already carries the query string
            if not quiet:
                progress(f"  {kind}: {len(out)}")
        if not quiet:
            note(f"  {kind}: {len(out)}      ")
        return out


def _next_link(link_header: str) -> str | None:
    for part in link_header.split(","):
        section = part.split(";")
        if len(section) < 2:
            continue
        if 'rel="next"' in section[1].replace(" ", "").replace("'", '"'):
            return section[0].strip().strip("<>")
    return None


# --------------------------------------------------------------------------
# citation keys
# --------------------------------------------------------------------------

STOPWORDS = {
    "a", "an", "the", "on", "of", "in", "for", "and", "to", "with", "at", "by",
    "from", "into", "via", "is", "are", "as", "using", "toward", "towards",
}


def ascii_fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def first_author_surname(doc: dict) -> str:
    for field in ("authors", "editors"):
        people = doc.get(field) or []
        if people:
            p = people[0]
            name = p.get("last_name") or p.get("name") or p.get("first_name") or ""
            name = ascii_fold(name)
            name = re.sub(r"[^A-Za-z]", "", name)
            if name:
                # keep acronym casing for corporate authors (NIST, NASA, IUPAC)
                return name if name.isupper() else name.capitalize()
    return "Anon"


def title_word(doc: dict) -> str:
    words = re.findall(r"[A-Za-z]+", ascii_fold(doc.get("title") or ""))
    for w in words:
        if w.lower() not in STOPWORDS and len(w) > 2:
            return w.capitalize()
    return words[0].capitalize() if words else "Untitled"


def make_citekey(doc: dict, taken: set) -> str:
    year = doc.get("year") or "n.d."
    base = f"{first_author_surname(doc)}{year}{title_word(doc)}"
    base = re.sub(r"[^A-Za-z0-9]", "", base)
    key = base
    suffix = ord("a")
    while key in taken:
        key = f"{base}{chr(suffix)}"
        suffix += 1
    taken.add(key)
    return key


def assign_citekeys(docs: list, keymap_path: Path) -> dict:
    """Keys, once assigned to a document id, never change between runs."""
    keymap = load_json(keymap_path, {})
    taken = set(keymap.values())
    # Deterministic order for first assignment, so a fresh run is reproducible.
    for doc in sorted(docs, key=lambda d: (str(d.get("created", "")), d["id"])):
        if doc["id"] not in keymap:
            keymap[doc["id"]] = make_citekey(doc, taken)
    save_json(keymap_path, keymap)
    return keymap


# --------------------------------------------------------------------------
# BibTeX
# --------------------------------------------------------------------------

TYPE_MAP = {
    "journal": "article",
    "magazine_article": "article",
    "newspaper_article": "article",
    "book": "book",
    "book_section": "incollection",
    "encyclopedia_article": "incollection",
    "conference_proceedings": "inproceedings",
    "thesis": "phdthesis",
    "report": "techreport",
    "working_paper": "techreport",
    "web_page": "misc",
    "computer_program": "misc",
    "patent": "misc",
    "generic": "misc",
}

TEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "%": r"\%",
    "#": r"\#",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def tex_escape(s: str) -> str:
    out = []
    for ch in str(s):
        out.append(TEX_ESCAPES.get(ch, ch))
    return "".join(out).replace("\n", " ").strip()


def format_authors(people: list) -> str:
    parts = []
    for p in people or []:
        last = (p.get("last_name") or "").strip()
        first = (p.get("first_name") or "").strip()
        if last and first:
            parts.append(f"{tex_escape(last)}, {tex_escape(first)}")
        elif last or first:
            parts.append(tex_escape(last or first))
        elif p.get("name"):
            parts.append("{" + tex_escape(p["name"]) + "}")
    return " and ".join(parts)


def bib_entry(doc: dict, key: str, include_abstract: bool = True) -> str:
    entry_type = TYPE_MAP.get(doc.get("type", "generic"), "misc")
    ids = doc.get("identifiers") or {}
    fields: list[tuple[str, str]] = []

    def add(name, value):
        if value:
            fields.append((name, str(value)))

    if doc.get("authors"):
        add("author", format_authors(doc["authors"]))
    if doc.get("editors"):
        add("editor", format_authors(doc["editors"]))
    if doc.get("title"):
        # inner braces protect the capitalization of chemical formulas, acronyms,
        # and proper nouns against styles that lowercase titles
        fields.append(("title", "{" + tex_escape(doc["title"]) + "}"))
    if not (doc.get("authors") or doc.get("editors")):
        # BibTeX needs author or key to sort an entry
        add("key", key)

    source = doc.get("source")
    if entry_type == "article":
        add("journal", tex_escape(source) if source else None)
    elif entry_type in ("inproceedings", "incollection"):
        add("booktitle", tex_escape(source) if source else None)

    add("year", doc.get("year"))
    add("volume", doc.get("volume"))
    add("number", doc.get("issue"))
    add("pages", (doc.get("pages") or "").replace("-", "--") or None)
    add("publisher", tex_escape(doc.get("publisher")) if doc.get("publisher") else None)
    if doc.get("institution"):
        # a thesis wants school; a report wants institution
        add("school" if entry_type == "phdthesis" else "institution",
            tex_escape(doc["institution"]))
    add("address", tex_escape(doc.get("city")) if doc.get("city") else None)
    add("doi", ids.get("doi"))
    add("issn", ids.get("issn"))
    add("isbn", ids.get("isbn"))
    if ids.get("pmid"):
        add("pmid", ids["pmid"])
    if ids.get("arxiv"):
        add("eprint", ids["arxiv"])
    websites = doc.get("websites") or []
    if websites:
        add("url", websites[0])
    if doc.get("keywords"):
        add("keywords", tex_escape(", ".join(doc["keywords"])))
    if include_abstract and doc.get("abstract"):
        add("abstract", tex_escape(doc["abstract"]))

    if not doc.get("title"):
        add("note", f"Untitled Mendeley record (document id {doc.get('id', '?')})")

    lines = [f"@{entry_type}{{{key},"]
    width = max((len(n) for n, _ in fields), default=0)
    for name, value in fields:
        lines.append(f"  {name.ljust(width)} = {{{value}}},")
    lines.append("}")
    return "\n".join(lines)


def write_bibtex(docs: list, keymap: dict, out: Path, include_abstract: bool) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    chunks = [
        f"% Mendeley library mirror -- generated {stamp}",
        f"% {len(docs)} references. Do not edit by hand; edit in Mendeley and re-run.",
        "",
    ]
    for doc in sorted(docs, key=lambda d: keymap[d["id"]].lower()):
        chunks.append(bib_entry(doc, keymap[doc["id"]], include_abstract))
        chunks.append("")
    (out / "library.bib").write_text("\n".join(chunks), encoding="utf-8")


# --------------------------------------------------------------------------
# index, folders, annotations
# --------------------------------------------------------------------------

def write_index(docs: list, keymap: dict, files_by_doc: dict, ann_by_doc: dict, out: Path) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Library index",
        "",
        f"{len(docs)} references, mirrored {stamp}.",
        "",
        "| key | year | first author | title | journal | doi | text | notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for doc in sorted(docs, key=lambda d: keymap[d["id"]].lower()):
        key = keymap[doc["id"]]
        ids = doc.get("identifiers") or {}
        title = (doc.get("title") or "").replace("|", r"\|")
        source = (doc.get("source") or "").replace("|", r"\|")
        if (out / "text" / f"{key}.md").exists():
            has_text = "yes"
        elif files_by_doc.get(doc["id"]):
            has_text = "no"  # Mendeley has a file, but no text came out of it
        else:
            has_text = ""
        lines.append(
            f"| `{key}` | {doc.get('year','')} | {first_author_surname(doc)} | {title} | "
            f"{source} | {ids.get('doi','')} | {has_text} | "
            f"{len(ann_by_doc.get(doc['id'], []))} |"
        )
    (out / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_folders(folders: list, folder_docs: dict, keymap: dict, out: Path) -> None:
    by_id = {f["id"]: f for f in folders}

    def full_name(f):
        parts, cur, guard = [], f, 0
        while cur and guard < 20:
            parts.append(cur.get("name", "?"))
            cur = by_id.get(cur.get("parent_id"))
            guard += 1
        return "/".join(reversed(parts))

    payload = {
        full_name(f): sorted(
            keymap[d] for d in folder_docs.get(f["id"], []) if d in keymap
        )
        for f in folders
    }
    save_json(out / "folders.json", payload)


def annotation_markdown(doc: dict, key: str, annotations: list) -> str:
    ids = doc.get("identifiers") or {}
    author_names = []
    for p in doc.get("authors") or []:
        first = (p.get("first_name") or "").strip()
        last = (p.get("last_name") or p.get("name") or "").strip()
        joined = f"{first} {last}".strip()
        if joined:
            author_names.append(joined)
    head = [
        f"# {doc.get('title') or '(untitled)'}",
        "",
        f"- **key**: `{key}`",
        f"- **authors**: {', '.join(author_names)}",
        f"- **year**: {doc.get('year', '')}",
        f"- **source**: {doc.get('source', '')}",
    ]
    if ids.get("doi"):
        head.append(f"- **doi**: {ids['doi']}")
    head += ["", "---", ""]

    def page_of(a):
        pos = a.get("positions") or []
        return pos[0].get("page", 0) if pos else 0

    def top_of(a):
        pos = a.get("positions") or []
        if pos and isinstance(pos[0].get("top_left"), dict):
            return pos[0]["top_left"].get("y", 0)
        return 0

    body = []
    for a in sorted(annotations, key=lambda a: (page_of(a), top_of(a))):
        page = page_of(a)
        text = (a.get("text") or "").strip()
        kind = a.get("type", "annotation")
        if kind == "highlight" and not text:
            # Mendeley returns coordinates for highlights but not always the
            # highlighted text; the location is still worth recording.
            body.append(f"- *(highlight, p. {page})*")
        elif kind == "highlight":
            body.append(f"- > {text}\n  \n  *(p. {page})*")
        elif text:
            body.append(f"- **note (p. {page})**: {text}")
    if not body:
        body = ["*(no annotations)*"]
    return "\n".join(head + body) + "\n"


# --------------------------------------------------------------------------
# PDF text extraction
# --------------------------------------------------------------------------

# A page of a text-bearing paper yields hundreds of characters. A scanned page
# yields a handful of stray marks, if that.
MIN_CHARS_PER_PAGE = 80


def extract_pdf_text(data: bytes) -> tuple[str, int, int]:
    """Return (markdown body, page count, character count) for a PDF's bytes."""
    import pymupdf  # imported lazily so --attachments none needs no PDF stack

    chunks, chars = [], 0
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        pages = doc.page_count
        for n, page in enumerate(doc, 1):
            text = page.get_text("text") or ""
            text = clean_page_text(text)
            chars += len(text.strip())
            if text.strip():
                chunks.append(f"<!-- p. {n} -->\n\n{text.strip()}")
    return "\n\n".join(chunks), pages, chars


def clean_page_text(text: str) -> str:
    text = text.replace("\x0c", "")
    # join words broken across a line by hyphenation: "cataly-\nsis" -> "catalysis"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # a single newline inside a paragraph is a column-wrap artifact, not a break
    text = re.sub(r"(?<![.:;!?])\n(?![\n•\-\d])", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def text_document(doc: dict, key: str, body: str, pages: int, chars: int) -> str:
    ids = doc.get("identifiers") or {}
    authors = "; ".join(
        f"{(p.get('last_name') or '').strip()}, {(p.get('first_name') or '').strip()}".strip(", ")
        for p in (doc.get("authors") or [])
    )

    def esc(v):
        return json.dumps(str(v), ensure_ascii=False) if v not in (None, "") else '""'

    front = [
        "---",
        f"citekey: {key}",
        f"title: {esc(doc.get('title'))}",
        f"authors: {esc(authors)}",
        f"year: {doc.get('year', '')}",
        f"source: {esc(doc.get('source'))}",
        f"doi: {esc(ids.get('doi'))}",
        f"pages: {pages}",
        f"characters: {chars}",
        f"mendeley_id: {doc.get('id', '')}",
        "---",
        "",
        f"# {doc.get('title') or key}",
        "",
        f"*Extracted text. Cite as `{key}`; page markers below are the PDF's own "
        "pagination. Equations and table structure do not survive extraction — "
        "check the PDF in Mendeley before quoting either.*",
        "",
    ]
    return "\n".join(front) + body + "\n"


def write_extraction_report(rows: list, out: Path, extracted: int) -> None:
    empty = [r for r in rows if r["status"] == "no-text"]
    failed = [r for r in rows if r["status"] == "failed"]
    lines = [
        "# Extraction report",
        "",
        f"- extracted this run: {extracted}",
        f"- no text layer (probably scans): {len(empty)}",
        f"- failed outright: {len(failed)}",
        "",
        "Anything listed below is invisible to any text search of this folder.",
        "The PDF is still in Mendeley; only the mirror lacks it.",
        "",
    ]
    for label, rows_ in (("No extractable text", empty), ("Failed", failed)):
        if not rows_:
            continue
        lines += [f"## {label}", ""]
        for r in sorted(rows_, key=lambda r: r["key"]):
            detail = f" — {r['detail']}" if r.get("detail") else ""
            lines.append(f"- `{r['key']}` · {r.get('title', '')[:80]}{detail}")
        lines.append("")
    (out / "extraction-report.md").write_text("\n".join(lines), encoding="utf-8")


def harvest_attachments(client: Mendeley, files_by_doc: dict, keymap: dict,
                        docs_by_id: dict, out: Path, state: dict, mode: str,
                        state_path: Path | None = None) -> tuple:
    """Download each attachment, extract its text, and (by default) discard it."""
    text_dir = out / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = out / "pdf"
    if mode == "keep":
        pdf_dir.mkdir(parents=True, exist_ok=True)
    known = state.setdefault("files", {})
    fetched = skipped = failed = reused = 0
    report: list = []
    state_path = state_path or mirror_state_dir(out) / "state.json"

    total = sum(len(v) for v in files_by_doc.values())
    seen = 0
    try:
        for doc_id, files in files_by_doc.items():
            key = keymap.get(doc_id)
            doc = docs_by_id.get(doc_id)
            if not key or not doc:
                continue
            for i, f in enumerate(files):
                seen += 1
                stem = key if i == 0 else f"{key}-{i+1}"
                is_pdf = "pdf" in (f.get("mime_type") or "").lower()
                text_target = text_dir / f"{stem}.md"
                prior = known.get(f["id"], {})
                if prior.get("filehash") == f.get("filehash") and (
                        text_target.exists() or prior.get("status") in ("no-text", "not-pdf")):
                    skipped += 1
                    if prior.get("status") in ("no-text", "failed"):
                        report.append({"key": stem, "status": prior["status"],
                                       "title": doc.get("title", ""),
                                       "detail": prior.get("detail", "")})
                    continue
                progress(f"  {seen}/{total}  {stem[:44]}")
                try:
                    # An earlier run may already have pulled this PDF down. Re-use
                    # it rather than paying for the download twice.
                    local = pdf_dir / f"{stem}.pdf"
                    from_disk = local.exists() and local.stat().st_size > 0
                    if from_disk:
                        data = local.read_bytes()
                        reused += 1
                    else:
                        # The download endpoint answers 303 with a signed URL; the
                        # Authorization header must NOT be forwarded to that host.
                        resp = client.get(f"{API}/files/{f['id']}", accept="*/*",
                                          allow_redirects=False)
                        if resp.status_code in (301, 302, 303, 307):
                            resp = requests.get(resp.headers["Location"], timeout=180)
                        resp.raise_for_status()
                        data = resp.content

                    if mode == "keep" and not from_disk:
                        suffix = ".pdf" if is_pdf else (
                            Path(f.get("file_name") or "").suffix or ".bin")
                        (pdf_dir / f"{stem}{suffix}").write_bytes(data)

                    if not is_pdf:
                        known[f["id"]] = {"filehash": f.get("filehash"), "status": "not-pdf"}
                        continue

                    body, pages, chars = extract_pdf_text(data)
                    if chars < MIN_CHARS_PER_PAGE * max(pages, 1):
                        status = "no-text"
                        detail = f"{chars} characters across {pages} pages"
                        report.append({"key": stem, "status": status,
                                       "title": doc.get("title", ""), "detail": detail})
                        text_target.unlink(missing_ok=True)
                    else:
                        status, detail = "ok", ""
                        text_target.write_text(
                            text_document(doc, stem, body, pages, chars), encoding="utf-8")
                        fetched += 1
                    known[f["id"]] = {"filehash": f.get("filehash"), "status": status,
                                      "detail": detail, "pages": pages, "chars": chars}
                    if mode == "text" and local.exists():
                        local.unlink()  # the text is the artifact; Mendeley keeps the PDF
                    if seen % 25 == 0:
                        save_json(state_path, state)  # so Ctrl-C keeps the progress
                    if not from_disk:
                        time.sleep(0.2)
                except Exception as exc:  # one bad file shouldn't stop the run
                    failed += 1
                    known[f["id"]] = {"filehash": f.get("filehash"), "status": "failed",
                                      "detail": str(exc)[:200]}
                    report.append({"key": stem, "status": "failed",
                                   "title": doc.get("title", ""), "detail": str(exc)[:120]})
    finally:
        save_json(state_path, state)
    if mode == "text" and pdf_dir.exists() and not any(pdf_dir.iterdir()):
        pdf_dir.rmdir()
    if reused:
        note(f"  re-used {reused} PDFs already on disk (no re-download)")
    return fetched, skipped, failed, report


# --------------------------------------------------------------------------
# run bookkeeping: one run at a time, a log, and a visible staleness signal
# --------------------------------------------------------------------------

LOCK_STALE_HOURS = 12


def acquire_lock(mirror_dir: Path) -> Path | None:
    """Refuse to start if another run is live. Scheduled + manual runs collide
    otherwise, and the first full run takes hours."""
    lock = mirror_dir / "run.lock"
    if lock.exists():
        age_h = (time.time() - lock.stat().st_mtime) / 3600
        if age_h < LOCK_STALE_HOURS:
            held = load_json(lock, {})
            note(f"Another run started {age_h:.1f} h ago on "
                 f"{held.get('host', '?')} (pid {held.get('pid', '?')}); stopping.")
            return None
        note(f"Ignoring a stale lock left {age_h:.0f} h ago.")
    save_json(lock, {"pid": os.getpid(), "host": os.environ.get("COMPUTERNAME")
                     or os.environ.get("HOSTNAME") or "?",
                     "started": datetime.now(timezone.utc).isoformat()})
    return lock


def write_log(mirror_dir: Path) -> None:
    log = mirror_dir / "mirror.log"
    try:
        if log.exists() and log.stat().st_size > 1_000_000:
            log.replace(mirror_dir / "mirror.log.1")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"\n===== {stamp} =====\n")
            fh.write("\n".join(LOG) + "\n")
    except OSError:
        pass


def write_status(out: Path, ok: bool, started: datetime, error: str = "") -> None:
    """Rewritten on every attempt, success or failure.

    A failed run leaves index.md untouched, which would otherwise make a mirror
    that stopped updating three weeks ago look perfectly current.
    """
    path = out / "mirror-status.md"
    prev = {}
    if path.exists():
        m = re.search(r"last successful run: (\S+ \S+ \S+)", path.read_text(encoding="utf-8"))
        if m:
            prev["last_ok"] = m.group(1)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    last_ok = now if ok else prev.get("last_ok", "never")
    took = (datetime.now(timezone.utc) - started).total_seconds()
    lines = [
        "# Mirror status",
        "",
        f"- last attempt: {now} — **{'ok' if ok else 'FAILED'}** ({took/60:.1f} min)",
        f"- last successful run: {last_ok}",
        "",
    ]
    if not ok:
        lines += [
            "The last refresh did not finish, so everything else in this folder is",
            "as of the last successful run above — treat it as possibly stale, and",
            "say so if it matters to the answer.",
            "",
            "```",
            error.strip()[:800],
            "```",
            "",
            "Full history in `.mirror/mirror.log`.",
        ]
    else:
        lines += ["Everything in this folder is current as of the run above.",
                  "", "Recent run:", "", "```"] + LOG[-14:] + ["```"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    global QUIET, NONINTERACTIVE
    ap = argparse.ArgumentParser(description="Mirror a Mendeley library to a folder.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output directory (default: {DEFAULT_OUT})")
    ap.add_argument("--attachments", choices=["text", "keep", "none"], default="text",
                    help="text: extract text and discard the PDF (default); "
                         "keep: also keep the PDF; none: skip attachments entirely")
    ap.add_argument("--no-pdfs", action="store_true",
                    help=argparse.SUPPRESS)  # old spelling of --attachments none
    ap.add_argument("--no-annotations", action="store_true", help="skip annotation export")
    ap.add_argument("--no-abstracts", action="store_true", help="omit abstracts from library.bib")
    ap.add_argument("--reauth", action="store_true", help="discard saved tokens and log in again")
    ap.add_argument("--reconfigure", action="store_true",
                    help="re-enter the application ID, secret, and redirect URL")
    ap.add_argument("--quiet", action="store_true",
                    help="for scheduled runs: no progress output, never prompt, "
                         "log to .mirror/mirror.log")
    args = ap.parse_args()

    QUIET = NONINTERACTIVE = args.quiet
    out = args.out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    mirror_dir = mirror_state_dir(out)
    lock = acquire_lock(mirror_dir)
    if lock is None:
        write_log(mirror_dir)
        return 0  # not an error: the other run is doing the work

    try:
        rc = run(args, out, mirror_dir)
    except SystemExit as exc:  # sys.exit() from the auth paths
        note(str(exc))
        write_status(out, False, started, str(exc))
        write_log(mirror_dir)
        lock.unlink(missing_ok=True)
        raise
    except BaseException as exc:  # includes Ctrl-C: record it, then re-raise
        detail = f"{type(exc).__name__}: {exc}"
        note(detail)
        write_status(out, False, started, detail)
        write_log(mirror_dir)
        lock.unlink(missing_ok=True)
        raise
    write_status(out, rc == 0, started)
    write_log(mirror_dir)
    lock.unlink(missing_ok=True)
    return rc


def run(args, out: Path, mirror_dir: Path) -> int:
    cfg = get_app_config(force_prompt=args.reconfigure)
    tokens_path = config_dir() / "tokens.json"
    if (args.reauth or args.reconfigure) and tokens_path.exists():
        tokens_path.unlink()
    tokens = load_json(tokens_path, {})
    if not tokens.get("access_token"):
        tokens = interactive_authorize(cfg)

    client = Mendeley(cfg, tokens)
    state_path = mirror_dir / "state.json"
    state = load_json(state_path, {})

    note(f"Mirroring your Mendeley library into {out}")
    docs = client.paged("/documents", "documents", {"view": "all"})
    if not docs:
        note("No documents returned. If your library is not empty, try --reauth.")
        return 1

    files = client.paged("/files", "files")
    files_by_doc: dict = {}
    for f in files:
        files_by_doc.setdefault(f.get("document_id"), []).append(f)

    # Everything past this point is optional: a library of a few thousand
    # references is a long fetch, and one failing collection should not throw
    # away the documents and files already in hand.
    annotations = []
    if not args.no_annotations:
        try:
            annotations = client.paged("/annotations", "annotations")
        except Exception as exc:
            note(f"  ! annotations unavailable, continuing without them: {exc}")
    ann_by_doc: dict = {}
    for a in annotations:
        ann_by_doc.setdefault(a.get("document_id"), []).append(a)

    folders, folder_docs = [], {}
    try:
        folders = client.paged("/folders", "folders")
        for i, f in enumerate(folders, 1):
            progress(f"  folder {i}/{len(folders)}: {f.get('name', '?')[:40]}")
            rows = client.paged(f"/folders/{f['id']}/documents", "documents", quiet=True)
            folder_docs[f["id"]] = [r["id"] for r in rows]
        note(f"  folders: {len(folders)}")
    except Exception as exc:
        note(f"  ! folders unavailable, continuing without them: {exc}")

    keymap = assign_citekeys(docs, mirror_dir / "citekeys.json")
    docs_by_id = {d["id"]: d for d in docs}

    write_bibtex(docs, keymap, out, include_abstract=not args.no_abstracts)
    write_folders(folders, folder_docs, keymap, out)

    if not args.no_annotations:
        ann_dir = out / "annotations"
        ann_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        for doc_id, anns in ann_by_doc.items():
            doc = docs_by_id.get(doc_id)
            if not doc:
                continue
            key = keymap[doc_id]
            (ann_dir / f"{key}.md").write_text(
                annotation_markdown(doc, key, anns), encoding="utf-8"
            )
            written += 1
        note(f"  annotations written for {written} documents")

    mode = "none" if args.no_pdfs else args.attachments
    if mode != "none":
        pending = sum(len(v) for v in files_by_doc.values())
        verb = "extracting text from" if mode == "text" else "downloading"
        note(f"  {verb} up to {pending} attachments (unchanged ones are skipped)")
        if not QUIET:
            note("  interrupt with Ctrl-C any time -- progress is kept and resumed next run")
        fetched, skipped, failed, report = harvest_attachments(
            client, files_by_doc, keymap, docs_by_id, out, state, mode, state_path)
        write_extraction_report(report, out, fetched)
        note(f"  text: {fetched} extracted, {skipped} unchanged, {failed} failed")
        no_text = sum(1 for r in report if r["status"] == "no-text")
        if no_text:
            note(f"  {no_text} attachments had no text layer; see extraction-report.md")

    # written last, so its "text" column reflects what is actually on disk
    write_index(docs, keymap, files_by_doc, ann_by_doc, out)

    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_json(state_path, state)

    note(f"Done. {len(docs)} references in {out / 'library.bib'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
