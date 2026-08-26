#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31", "pymupdf>=1.24"]
# ///
"""Offline tests for mendeley_mirror.py -- pure functions + a stubbed API."""
import json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mendeley_mirror as mm

DOCS = [
    {   # ordinary journal article, TeX-hostile title, accented author, 100% fields
        "id": "d1", "created": "2020-01-01T00:00:00Z", "type": "journal",
        "title": "Yield & selectivity of 50% H_2SO_4 catalysis in CO$_2$ streams #1",
        "authors": [{"first_name": "Jörg", "last_name": "Müller"},
                    {"first_name": "A. B.", "last_name": "Smith"}],
        "year": 2020, "source": "AIChE Journal", "volume": "66", "issue": "4",
        "pages": "1234-1245", "identifiers": {"doi": "10.1002/aic.16789", "issn": "0001-1541"},
        "abstract": "We show 90% conversion at 5% loading.",
        "keywords": ["catalysis", "CO2"], "websites": ["https://example.org/a"],
    },
    {   # book chapter
        "id": "d2", "created": "2021-02-01T00:00:00Z", "type": "book_section",
        "title": "The transport of momentum", "authors": [{"first_name": "R B", "last_name": "Bird"}],
        "year": 2021, "source": "Transport Phenomena", "publisher": "Wiley",
        "city": "New York", "pages": "10-40", "identifiers": {"isbn": "9780470115398"},
    },
    {   # collides with d2 on surname+year+title word -> must get a suffix
        "id": "d3", "created": "2021-03-01T00:00:00Z", "type": "conference_proceedings",
        "title": "The transport of momentum, revisited",
        "authors": [{"first_name": "R B", "last_name": "Bird"}],
        "year": 2021, "source": "AIChE Annual Meeting",
    },
    {   # thesis with institution
        "id": "d4", "created": "2019-05-01T00:00:00Z", "type": "thesis",
        "title": "A study of packed beds", "authors": [{"last_name": "Nguyen", "first_name": "Linh"}],
        "year": 2019, "institution": "Drexel University",
    },
    {   # web page, corporate author, no year
        "id": "d5", "created": "2022-06-01T00:00:00Z", "type": "web_page",
        "title": "Steam tables", "authors": [{"name": "NIST"}],
        "websites": ["https://webbook.nist.gov"],
    },
    {   # degenerate: no author, no year, no title
        "id": "d6", "created": "2023-06-01T00:00:00Z", "type": "generic",
    },
    {   # publisher unicode: U+2010 in the name, U+2013 page range, curly quotes,
        # a non-breaking space and a zero-width space -- all of it ASCII-lookalike
        "id": "d8", "created": "2024-07-01T00:00:00Z", "type": "journal",
        "title": "Curing at 50\u00b0C \u00b1 2: the \u201cinert\u201d case \u2013 a 5\u2009min study\u200b",
        "authors": [{"first_name": "Jean\u2010Pierre", "last_name": "Pascault"}],
        "year": 2024, "source": "J.\u00a0Appl. Polym. Sci.", "volume": "49",
        "pages": "1441\u20131452", "identifiers": {"doi": "10.1002/app.1993.070490812"},
    },
]

ANNOTATIONS = [
    {"id": "a1", "document_id": "d1", "type": "note", "text": "Compare with Fig. 4 of Bird.",
     "positions": [{"page": 3, "top_left": {"x": 10, "y": 100}}]},
    {"id": "a2", "document_id": "d1", "type": "highlight", "text": "conversion plateaus above 5 bar",
     "positions": [{"page": 2, "top_left": {"x": 10, "y": 50}}]},
    {"id": "a3", "document_id": "d1", "type": "highlight",  # no text -- the awkward case
     "positions": [{"page": 2, "top_left": {"x": 10, "y": 400}}]},
]

FOLDERS = [
    {"id": "f1", "name": "Substack"},
    {"id": "f2", "name": "week 3", "parent_id": "f1"},
]
FOLDER_DOCS = {"f1": ["d1", "d2"], "f2": ["d1"]}
FILES_BY_DOC = {"d1": [{"id": "x1", "mime_type": "application/pdf", "filehash": "h1"}]}

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def main():
    tmp = Path(tempfile.mkdtemp())
    cfgdir = tmp / "cfg"
    cfgdir.mkdir()
    mm.config_dir = lambda: cfgdir  # keep the test out of the real config dir
    out = tmp / "out"
    out.mkdir()

    print("citation keys")
    keymap = mm.assign_citekeys(DOCS, cfgdir / "citekeys.json")
    print("   ", keymap)
    check(keymap["d1"] == "Muller2020Yield", "accents folded, stopword-free title word")
    check(keymap["d2"] == "Bird2021Transport", "stopword 'the' skipped")
    check(keymap["d3"] == "Bird2021Transporta", "collision gets a suffix")
    check(keymap["d5"] == "NISTndSteam", f"corporate acronym keeps its case -> {keymap['d5']}")
    check(len(set(keymap.values())) == len(DOCS), "all keys unique")

    # stability: re-running with a new document must not renumber existing keys
    more = DOCS + [{"id": "d7", "created": "2018-01-01T00:00:00Z", "type": "journal",
                    "title": "The transport of heat", "year": 2021,
                    "authors": [{"last_name": "Bird", "first_name": "R"}]}]
    keymap2 = mm.assign_citekeys(more, cfgdir / "citekeys.json")
    check(all(keymap2[k] == v for k, v in keymap.items()), "keys stable across runs")

    print("\nbibtex")
    mm.write_bibtex(DOCS, keymap, out, include_abstract=True)
    bib = (out / "library.bib").read_text(encoding="utf-8")
    check("@article{Muller2020Yield," in bib, "journal -> @article")
    check("@incollection{Bird2021Transport," in bib, "book_section -> @incollection")
    check("@phdthesis" in bib and "school" in bib, "thesis -> @phdthesis with school")
    check(r"\&" in bib and r"\%" in bib and r"\_" in bib and r"\$" in bib and r"\#" in bib,
          "TeX specials escaped")
    check("{1234--1245}" in bib, "page range converted to --")
    check("Müller, Jörg and Smith, A. B." in bib, "author list formatted")
    check(bib.count("\n@") == len(DOCS), "one entry per document")

    print("\nunicode punctuation (non-UTF-8 LaTeX safety)")
    check(mm.tex_escape("Jean\u2010Pierre") == "Jean-Pierre", "U+2010 hyphen -> ASCII hyphen")
    check(mm.tex_escape("Jean\u2011Pierre") == "Jean-Pierre", "U+2011 non-breaking hyphen -> ASCII")
    check(mm.tex_escape("a \u2013 b") == "a -- b", "en dash -> --")
    check(mm.tex_escape("a \u2014 b") == "a --- b", "em dash -> ---")
    check(mm.tex_escape("\u201cq\u201d") == "``q''", "curly double quotes -> TeX quotes")
    check(mm.tex_escape("\u2018q\u2019") == "`q'", "curly single quotes -> TeX quotes")
    check(mm.tex_escape("a\u00a0b") == "a b", "non-breaking space -> ordinary space")
    check(mm.tex_escape("a\u200bb") == "ab", "zero-width space dropped")
    check(mm.tex_escape("50\u00b0C") == r"50\textdegree{}C", "degree sign -> \\textdegree")
    check(mm.tex_escape("\u00b1 2") == "$\\pm$ 2", "plus-minus -> math mode")
    # the replacement must not be escaped a second time
    check("textbackslash" not in mm.tex_escape("50\u00b0C"), "LaTeX replacement not re-escaped")
    # accented letters are legitimate UTF-8 and must survive untouched
    check(mm.tex_escape("M\u00fcller, J\u00f6rg") == "M\u00fcller, J\u00f6rg", "accents left alone")
    # TeX specials still escaped alongside the new rules
    check(mm.tex_escape("50% \u2013 a_b") == r"50\% -- a\_b", "specials still escaped")

    check(mm.format_pages("1441\u20131452") == "1441--1452", "en dash page range -> --")
    check(mm.format_pages("1441-1452") == "1441--1452", "hyphen page range -> --")
    check(mm.format_pages("1441--1452") == "1441--1452", "already-correct page range unchanged")

    d8 = bib[bib.index("@article{Pascault2024"):]
    d8 = d8[:d8.index("\n@")] if "\n@" in d8 else d8
    check("Jean-Pierre" in d8, "U+2010 gone from the author field in library.bib")
    check("{1441--1452}" in d8, "en dash page range fixed in library.bib")
    check(not any(ord(c) > 127 for c in d8), f"entry is pure ASCII -> {[c for c in d8 if ord(c) > 127]}")
    check("title    = {{Yield" in bib, "title double-braced for case protection")
    check("author = {{NIST}}" in bib, "corporate author double-braced")
    check(bib.count("institution") == 0, "thesis uses school, not institution")
    check("Untitled Mendeley record" in bib and "key  = {AnonndUntitled}" in bib,
          "degenerate record still yields a sortable, traceable entry")

    print("\nbibtex round-trip (real bibtex binary)")
    tex = tmp / "t.tex"
    cites = ",".join(keymap[d["id"]] for d in DOCS)
    tex.write_text(
        "\\documentclass{article}\\usepackage[utf8]{inputenc}\\begin{document}\n"
        f"\\nocite{{{cites}}}\n\\bibliographystyle{{plain}}\\bibliography{{library}}\n"
        "\\end{document}\n", encoding="utf-8")
    shutil.copy(out / "library.bib", tmp / "library.bib")
    subprocess.run(["pdflatex", "-interaction=nonstopmode", "t.tex"], cwd=tmp, capture_output=True)
    r = subprocess.run(["bibtex", "t"], cwd=tmp, capture_output=True, text=True)
    blg = (tmp / "t.blg").read_text(errors="replace")
    check("error message" not in blg.lower() and "I was expecting" not in blg,
          "bibtex parses library.bib without errors")
    warns = [l for l in blg.splitlines() if l.startswith("Warning--")]
    print("    bibtex warnings:", len(warns))
    for w in warns[:6]:
        print("     ", w)
    bbl = (tmp / "t.bbl").read_text(errors="replace")
    check(bbl.count("\\bibitem") == len(DOCS), f"all {len(DOCS)} entries resolved ({bbl.count(chr(92)+'bibitem')} found)")

    print("\nindex, folders, annotations")
    ann_by_doc = {}
    for a in ANNOTATIONS:
        ann_by_doc.setdefault(a["document_id"], []).append(a)
    mm.write_index(DOCS, keymap, FILES_BY_DOC, ann_by_doc, out)
    idx = (out / "index.md").read_text(encoding="utf-8")
    check(idx.count("\n|") == len(DOCS) + 2, "index has a row per reference")
    check("10.1002/aic.16789" in idx, "doi in index")

    mm.write_folders(FOLDERS, FOLDER_DOCS, keymap, out)
    folders = json.loads((out / "folders.json").read_text())
    check(folders["Substack"] == ["Bird2021Transport", "Muller2020Yield"], "folder maps to sorted keys")
    check("Substack/week 3" in folders, "nested folder path built")

    md = mm.annotation_markdown(DOCS[0], keymap["d1"], ANNOTATIONS)
    check(md.index("p. 2") < md.index("p. 3"), "annotations sorted by page")
    check("> conversion plateaus" in md, "highlight text quoted")
    check("*(highlight, p. 2)*" in md, "textless highlight still recorded")
    check("Jörg Müller" in md, "author names in annotation header")

    print("\ntext extraction")
    import pymupdf
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 100), "Packed bed reactors show high cataly-")
    p1.insert_text((72, 115), "sis efficiency under steady flow.")
    p1.insert_textbox(pymupdf.Rect(72, 140, 400, 700),
                      ("Conversion increased with temperature across the range "
                       "studied here, and selectivity fell. " * 6), fontsize=9)
    p2 = doc.new_page()
    p2.insert_textbox(pymupdf.Rect(72, 90, 400, 700),
                      ("The second page discusses transport limitations in "
                       "detail and at some length. " * 8), fontsize=9)
    pdf_bytes = doc.tobytes()
    doc.close()

    body, pages, chars = mm.extract_pdf_text(pdf_bytes)
    check(pages == 2, f"page count read ({pages})")
    check("<!-- p. 1 -->" in body and "<!-- p. 2 -->" in body, "page markers emitted")
    check("catalysis efficiency" in body, "hyphenation across a line break repaired")
    check(chars > 500, f"substantive text extracted ({chars} chars)")

    scan = pymupdf.open()
    scan.new_page()  # a page with no text layer, as a scan would be
    empty_body, empty_pages, empty_chars = mm.extract_pdf_text(scan.tobytes())
    scan.close()
    check(empty_chars < mm.MIN_CHARS_PER_PAGE * max(empty_pages, 1),
          f"textless page falls under the scan threshold ({empty_chars} chars)")

    md = mm.text_document(DOCS[0], "Muller2020Yield", body, pages, chars)
    check(md.startswith("---\ncitekey: Muller2020Yield"), "front matter leads the file")
    check('doi: "10.1002/aic.16789"' in md, "doi in front matter for citation")
    check("Equations and table structure do not survive" in md,
          "file warns about what extraction loses")
    check("<!-- p. 2 -->" in md, "body carried through with page markers")

    rows = [{"key": "Scan1999Old", "status": "no-text", "title": "An old scan",
             "detail": "3 characters across 12 pages"},
            {"key": "Bad2001File", "status": "failed", "title": "Broken", "detail": "boom"}]
    mm.write_extraction_report(rows, out, extracted=41)
    rep = (out / "extraction-report.md").read_text(encoding="utf-8")
    check("extracted this run: 41" in rep, "report counts extractions")
    check("Scan1999Old" in rep and "Bad2001File" in rep, "report names both failure kinds")
    check("invisible to any text search" in rep, "report says what the gap means")

    print("\nre-using PDFs already downloaded")
    h_out = tmp / "harvest"
    (h_out / "pdf").mkdir(parents=True)
    (h_out / "pdf" / "Muller2020Yield.pdf").write_bytes(pdf_bytes)

    class NoNetwork:
        def get(self, *a, **kw):
            raise AssertionError("downloaded a PDF that was already on disk")

    st = {}
    fetched, skipped, failed, rep_rows = mm.harvest_attachments(
        NoNetwork(), {"d1": [{"id": "x1", "mime_type": "application/pdf", "filehash": "h1"}]},
        {"d1": "Muller2020Yield"}, {"d1": DOCS[0]}, h_out, st, "text")
    check(fetched == 1 and failed == 0, f"local PDF extracted without a download ({fetched=}, {failed=})")
    check((h_out / "text" / "Muller2020Yield.md").exists(), "text file written")
    check(not (h_out / "pdf" / "Muller2020Yield.pdf").exists(), "PDF discarded after extraction")
    check(not (h_out / "pdf").exists(), "empty pdf/ directory cleaned up")
    check(st["files"]["x1"]["status"] == "ok", "state records the extraction")

    print("\npagination")
    check(mm._next_link('<https://api.mendeley.com/documents?marker=abc>; rel="next"')
          == "https://api.mendeley.com/documents?marker=abc", "next link parsed")
    check(mm._next_link('<https://a/1>; rel="last", <https://a/2>; rel="next"') == "https://a/2",
          "next link found among several")
    check(mm._next_link('<https://a/1>; rel="last"') is None, "no next link -> None")

    class FakeResp:
        def __init__(self, payload, link="", status=200):
            self._p, self.headers, self.status_code = payload, {"Link": link}, status
            self.ok, self.url, self.text = status < 400, "http://x", ""
        def json(self): return self._p
        def raise_for_status(self): pass

    pages = [FakeResp([{"id": "a"}], '<https://api.mendeley.com/documents?marker=2>; rel="next"'),
             FakeResp([{"id": "b"}])]
    client = mm.Mendeley.__new__(mm.Mendeley)
    client.get = lambda url, accept=None, params=None, **kw: pages.pop(0)
    check([d["id"] for d in client.paged("/documents", "documents")] == ["a", "b"],
          "paged() follows next links and concatenates")

    # annotations must not be requested at the documents page size (Mendeley 400s)
    seen = []

    def record(url, accept=None, params=None, **kw):
        seen.append(dict(params or {}))
        return FakeResp([{"id": "z"}])

    client.get = record
    client.paged("/annotations", "annotations", quiet=True)
    check(seen[0].get("limit") == 200, f"annotations requested at limit=200 (got {seen[0]})")
    seen.clear()
    client.paged("/documents", "documents", quiet=True)
    check(seen[0].get("limit") == 500, "documents still requested at limit=500")

    # a 400 on the first page should back the page size off, not kill the run
    responses = [FakeResp([], status=400), FakeResp([{"id": "q"}])]
    tried = []

    def flaky(url, accept=None, params=None, **kw):
        tried.append(dict(params or {}))
        return responses.pop(0)

    client.get = flaky
    got = client.paged("/annotations", "annotations", quiet=True)
    check([d["id"] for d in got] == ["q"] and tried[1]["limit"] == 50,
          f"400 backs page size off and retries (tried {[t.get('limit') for t in tried]})")

    print("\nscheduled-run bookkeeping")
    import datetime as _dt
    md = tmp / "sched" / ".mirror"
    md.mkdir(parents=True)
    sout = md.parent
    lock = mm.acquire_lock(md)
    check(lock is not None and lock.exists(), "first run takes the lock")
    check(mm.acquire_lock(md) is None, "a second concurrent run backs off")
    os.utime(lock, (0, 0))  # pretend it was left behind days ago
    check(mm.acquire_lock(md) is not None, "a stale lock is ignored")

    t0 = _dt.datetime.now(_dt.timezone.utc)
    mm.write_status(sout, True, t0)
    st = (sout / "mirror-status.md").read_text(encoding="utf-8")
    check("**ok**" in st, "successful run reports ok")
    ok_stamp = re.search(r"last successful run: (.+)", st).group(1)

    mm.write_status(sout, False, t0, "HTTPError: 500 from /documents")
    st = (sout / "mirror-status.md").read_text(encoding="utf-8")
    check("**FAILED**" in st and "HTTPError" in st, "failed run reports the error")
    check(f"last successful run: {ok_stamp}" in st,
          "a failure keeps the earlier success timestamp, not 'never'")
    check("possibly stale" in st, "failure tells the reader the folder may be stale")

    mm.NONINTERACTIVE = True
    try:
        mm.require_interactive("Browser authorization")
        check(False, "require_interactive exits on a scheduled run")
    except SystemExit as exc:
        check("scheduled run" in str(exc), "require_interactive explains itself and exits")
    mm.NONINTERACTIVE = False

    print("\non-demand PDF fetch (get_pdf.py)")
    (out / ".mirror").mkdir(exist_ok=True)
    (out / ".mirror" / "citekeys.json").write_text(json.dumps(keymap), encoding="utf-8")
    gp = str(Path(__file__).parent / "get_pdf.py")

    def run_gp(*a):
        return subprocess.run([sys.executable, gp, "--out", str(out), *a],
                              capture_output=True, text=True, timeout=60)

    r = run_gp("--search", "packed bed")
    check("Nguyen2019Study" in r.stdout, f"--search finds a key by title ({r.stdout.strip()[:60]})")
    r = run_gp("Nguyen2019Stud")
    check("did you mean" in r.stdout and "Nguyen2019Study" in r.stdout,
          "a mistyped key suggests the right one")
    check("input" not in r.stderr.lower() and "EOF" not in r.stderr,
          "a bad key does not trigger the credential prompt")
    dest = tmp / "dest"
    dest.mkdir()
    (dest / "Nguyen2019Study.pdf").write_bytes(b"%PDF-1.4 stub")
    r = run_gp("--dest", str(dest), "Nguyen2019Study")
    check(r.stdout.strip().endswith("Nguyen2019Study.pdf") and r.returncode == 0,
          "a cached PDF is returned without authenticating")

    print("\n" + ("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILURES: {fails}"))
    print("sample entry:\n")
    print(bib.split("@")[1][:600])
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
