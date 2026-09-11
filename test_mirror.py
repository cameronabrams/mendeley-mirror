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

    body, pages, chars, content = mm.extract_pdf_text(pdf_bytes)
    check(pages == 2, f"page count read ({pages})")
    check("<!-- p. 1 -->" in body and "<!-- p. 2 -->" in body, "page markers emitted")
    check("catalysis efficiency" in body, "hyphenation across a line break repaired")
    check(chars > 500, f"substantive text extracted ({chars} chars)")

    scan = pymupdf.open()
    scan.new_page()  # a page with no text layer, as a scan would be
    empty_body, empty_pages, empty_chars, empty_content = mm.extract_pdf_text(scan.tobytes())
    scan.close()
    check(empty_chars < mm.MIN_CHARS_PER_PAGE * max(empty_pages, 1),
          f"textless page falls under the scan threshold ({empty_chars} chars)")

    # A scan whose only text is a stamp repeated on every page. Real case: a
    # ProQuest copy of Lin & Rye 2006 carried exactly 103 characters on each of
    # 29 pages, above MIN_CHARS_PER_PAGE, so the raw count called it readable.
    stamp = ("Reproduced with permission of the copyright owner.  "
             "Further reproduction prohibited without permission.")
    stamped = pymupdf.open()
    for _ in range(29):
        page = stamped.new_page()
        page.insert_text((72, 72), stamp, fontsize=9)
    st_body, st_pages, st_chars, st_content = mm.extract_pdf_text(stamped.tobytes())
    stamped.close()
    check(st_chars >= mm.MIN_CHARS_PER_PAGE * st_pages,
          f"stamped scan clears the raw threshold, as the real one did ({st_chars})")
    check(st_content == 0, f"stamp is recognised as boilerplate, not content ({st_content})")

    # The same logic must not strip a real paper down: a running head repeats on
    # every page too, and removing it should leave the body untouched.
    real = pymupdf.open()
    for n in range(6):
        page = real.new_page()
        page.insert_text((72, 50), "J. Chem. Phys. 152, 044105 (2020)", fontsize=8)
        page.insert_textbox(pymupdf.Rect(72, 90, 420, 700),
                            (f"Section {n} discusses the integrator in detail. " * 12),
                            fontsize=9)
    r_body, r_pages, r_chars, r_content = mm.extract_pdf_text(real.tobytes())
    real.close()
    check(r_content > mm.MIN_CHARS_PER_PAGE * r_pages,
          f"paper with a running head stays readable ({r_content} content chars)")
    check(r_content < r_chars, "the running head itself was discounted")

    # Short documents are exempt: across one or two pages "repeated on most
    # pages" is meaningless, and a note should not be judged on it.
    two = ["Identical text on both pages."] * 2
    check(mm.content_chars(two) == sum(len(t) for t in two),
          "two-page document is not subjected to the repeat test")
    check(mm.content_chars([]) == 0, "no pages means no content")

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
    check(lock.name == f"run.lock.{mm.host_name()}", "the lock is named per host")
    check(mm.acquire_lock(md) is None, "a second concurrent run backs off")
    os.utime(lock, (0, 0))  # pretend it was left behind days ago
    check(mm.acquire_lock(md) is None,
          "a live run keeps its lock however old -- the first full run takes hours")

    # a lock whose process is gone is stale at any age: that is the failure that
    # blocked every run for 9.5 h, a dead pid behind a lock only age could clear.
    dead = subprocess.Popen([sys.executable, "-c", ""])
    dead.wait()
    lock.write_text(json.dumps({"pid": dead.pid, "host": mm.host_name(),
                                "started": "2026-01-01T00:00:00+00:00"}),
                    encoding="utf-8")
    if mm._pid_alive(dead.pid):
        check(True, "(pid reused; skipping the dead-pid takeover case)")
    else:
        check(mm.acquire_lock(md) is not None,
              "a lock from a dead process is taken over immediately")

    # another machine's lock is advisory: a synced folder cannot carry a mutex,
    # and treating it as binding is what let one stale file stop every host.
    lock.unlink(missing_ok=True)  # the takeover above left our own live lock
    foreign = md / "run.lock.othermachine"
    foreign.write_text(json.dumps({"pid": 1, "host": "othermachine",
                                   "started": "2026-01-01T00:00:00+00:00"}),
                       encoding="utf-8")
    check(mm.acquire_lock(md) is not None, "another host's lock does not block us")
    check(foreign.exists(), "and we leave that host's lock alone")

    lock.unlink(missing_ok=True)
    legacy = md / "run.lock"
    legacy.write_text("{}", encoding="utf-8")
    check(mm.acquire_lock(md) is not None and not legacy.exists(),
          "a shared run.lock from an older version is cleared")

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

    print("\ninbox closing report")
    import inbox

    # A clean run: the refresh instruction appears, and nothing else.
    r = inbox.closing_report(["a.pdf"], [], [])
    check("Run ./run_mirror.sh" in r, "a successful run says to refresh")
    check("NOT filed" not in r, "a successful run reports no failures")

    # A failed run must NOT tell you to go pull down text that was never sent.
    r = inbox.closing_report([], [], [("a.pdf", "upload refused (403)")])
    check("Run ./run_mirror.sh" not in r,
          "a run that attached nothing does not tell you to refresh")
    check("NOT filed" in r and "a.pdf" in r and "403" in r,
          "the failure, the file name and the reason are all reported")

    # The mixed case is the dangerous one: `| tail` shows only the end, so the
    # failure has to be the LAST thing printed, after the refresh instruction.
    r = inbox.closing_report(["good.pdf"], [], [("bad.pdf", "boom")])
    check("Run ./run_mirror.sh" in r, "the part that worked still says to refresh")
    lines = [ln for ln in r.strip().splitlines() if ln.strip()]
    check(r.index("NOT filed") > r.index("Run ./run_mirror.sh"),
          "the failure block comes after the success line, so tail shows it")
    check("bad.pdf" in "\n".join(lines[-3:]), "the failed file name survives a tail -3")

    # Skipped files are left in the inbox too, and saying so is not an error.
    r = inbox.closing_report(["a.pdf"], [("b.pdf", "Key2020Word already has a PDF")], [])
    check("--replace" in r and "b.pdf" in r, "a skipped file is reported with the escape hatch")
    check("NOT filed" not in r, "a skipped file is not counted as a failure")

    check(inbox.closing_report([], [], [], dry_run=True) == "",
          "a clean dry run prints no closing block")
    r = inbox.closing_report([], [], [("a.pdf", "cannot identify: no DOI")], dry_run=True)
    check("Run ./run_mirror.sh" not in r and "a.pdf" in r,
          "a dry run reports what it could not identify but never says to refresh")

    print("\ninbox: an empty download is not a scan")
    import pymupdf as _fitz

    # The file-name path deliberately trusts a DOI in the name over missing text,
    # so a scan with no text layer stays filable. A failed interlibrary-loan fetch
    # returns a PDF that is blank, and named for its DOI it would otherwise become
    # a reference with nothing behind it.
    blank = tmp / "blank.pdf"
    d = _fitz.open(); d.new_page(); d.save(blank); d.close()
    check(inbox.has_content(blank) is False, "a blank page is not content")

    drawn = tmp / "drawn.pdf"
    d = _fitz.open(); pg = d.new_page()
    pg.draw_rect(_fitz.Rect(20, 20, 200, 200))          # marks but no text: a scan
    d.save(drawn); d.close()
    check(inbox.has_content(drawn) is True,
          "a page with marks and no text IS content -- a real scan must stay filable")

    texted = tmp / "texted.pdf"
    d = _fitz.open(); pg = d.new_page(); pg.insert_text((72, 72), "hello")
    d.save(texted); d.close()
    check(inbox.has_content(texted) is True, "an ordinary text page is content")

    check(inbox.has_content(tmp / "does-not-exist.pdf") is False,
          "an unreadable file is not content, and does not raise")

    print("\ninbox: finding a reference the library already holds")
    ibx = tmp / "ibx"
    (ibx / ".mirror").mkdir(parents=True)
    (ibx / "library.bib").write_text("""
@article{Doe2025Widget,
  author  = {Doe, Jane},
  title   = {{A Study of Widgets: the Sequel}},
  journal = {arXiv},
  year    = {2025},
  eprint  = {2501.00001},
}

@article{Roe2024Gadget,
  author  = {Roe, Richard},
  title   = {{On Gadgets}},
  journal = {J. Things},
  year    = {2024},
  doi     = {10.1000/gadget},
}
""", encoding="utf-8")
    (ibx / ".mirror" / "citekeys.json").write_text(
        json.dumps({"m1": "Doe2025Widget", "m2": "Roe2024Gadget"}), encoding="utf-8")

    check(inbox.existing_document(ibx, "10.1000/gadget")[1] == "Roe2024Gadget",
          "a DOI that is in the bib still matches by DOI")
    check(inbox.existing_document(ibx, "10.1000/gadget")[0] == "m2",
          "the matched entry resolves to its Mendeley id")

    # The regression this guards: an arXiv reference with no doi field. Its PDF
    # carries a resolvable DOI, so the DOI search runs and finds nothing -- and
    # the title fallback used to be skipped entirely whenever a DOI was present,
    # reporting "new to the library" and duplicating a paper already held.
    doc, key = inbox.existing_document(ibx, "10.48550/arxiv.2501.00001",
                                       "A Study of Widgets: the Sequel")
    check(key == "Doe2025Widget",
          f"a DOI that matches nothing falls back to the title (got {key!r})")
    check(doc == "m1", "the title-matched entry resolves to its Mendeley id")

    check(inbox.existing_document(ibx, "10.9999/nope", "A Paper Nobody Has") == ("", ""),
          "a genuinely new paper is still reported as new")
    check(inbox.existing_document(ibx, "", "On Gadgets")[1] == "Roe2024Gadget",
          "the no-DOI title path still works")
    check(inbox.existing_document(ibx, "10.9999/nope", "A Study of Widgets")[1] == "",
          "a partial title does not match -- equality is still exact")

    print("\ninbox exit status (offline: an unreadable PDF needs no network)")
    ibox = out / "inbox"
    ibox.mkdir(exist_ok=True)
    (ibox / "junk.pdf").write_bytes(b"not a pdf at all")
    r = subprocess.run([sys.executable, str(Path(__file__).parent / "inbox.py"),
                        "--out", str(out), "--dry-run"],
                       capture_output=True, text=True, timeout=120)
    check(r.returncode != 0, f"a file it cannot identify exits nonzero (got {r.returncode})")
    check("junk.pdf" in r.stdout and "NOT filed" in r.stdout,
          "the unidentifiable file is named in the closing block")
    tail3 = "\n".join([ln for ln in r.stdout.strip().splitlines() if ln.strip()][-3:])
    check("junk.pdf" in tail3 or "NOT filed" in tail3,
          f"the problem survives a tail -3 (tail was: {tail3[:80]!r})")
    (ibox / "junk.pdf").unlink()

    print("\npdbxref.py: ranking the gap by demand, not by deposition size")
    import pdbxref as px

    ENTRIES = [
        {"rcsb_id": "1AAA", "rcsb_primary_citation":
            {"pdbx_database_id_DOI": "10.1000/HELD", "year": 2001, "journal_abbrev": "J. Held"}},
        {"rcsb_id": "2BBB", "rcsb_primary_citation":
            {"pdbx_database_id_DOI": "10.1000/wanted", "year": 2004, "journal_abbrev": "Neuron",
             "title": "A title\nsplit over\tlines"}},
        {"rcsb_id": "3CCC", "rcsb_primary_citation":
            {"pdbx_database_id_DOI": "10.1000/bulk", "year": 2010, "journal_abbrev": "J. Bulk"}},
        {"rcsb_id": "4DDD", "rcsb_primary_citation":
            {"pdbx_database_id_DOI": "10.1000/bulk", "year": 2010, "journal_abbrev": "J. Bulk"}},
        {"rcsb_id": "5EEE", "rcsb_primary_citation":
            {"pdbx_database_id_DOI": "10.1000/bulk", "year": 2010, "journal_abbrev": "J. Bulk"}},
        {"rcsb_id": "6FFF", "rcsb_primary_citation": {"pdbx_database_id_DOI": ""}},
    ]
    HAVE = ({"10.1000/held"}, {"778899"}, {"a held title by name"})
    A2P = {"1AAA": {"p1"}, "2BBB": {"p1", "p2", "p3", "p4"},
           "3CCC": {"p9"}, "4DDD": {"p9"}, "5EEE": {"p9"}}

    ranked, held, no_doi = px.crossref(ENTRIES, HAVE, A2P)
    check(held == 1, "a citation already in the library is not in the gap")
    check(no_doi == 1, "an entry with no primary DOI is counted separately, not dropped silently")

    # RCSB returns mixed-case DOIs; without lowering, every Science entry looks missing.
    ranked2, held2, _ = px.crossref(
        [{"rcsb_id": "7GGG", "rcsb_primary_citation": {"pdbx_database_id_DOI": "10.1000/HELD"}}],
        HAVE, {})
    check(held2 == 1 and not ranked2, "DOI comparison is case-insensitive")

    # 17% of this library's records carry no DOI, only a PMID. A DOI-only test
    # reported Kwong 2000 as missing and it was downloaded a second time.
    _, held3, _ = px.crossref([{"rcsb_id": "8HHH", "rcsb_primary_citation":
        {"pdbx_database_id_DOI": "10.1000/unknown", "pdbx_database_id_PubMed": 778899}}], HAVE, {})
    check(held3 == 1, "a PMID match counts as held when the DOI does not")
    _, held4, _ = px.crossref([{"rcsb_id": "9III", "rcsb_primary_citation":
        {"pdbx_database_id_DOI": "10.1000/unknown", "title": "A Held Title, By Name."}}], HAVE, {})
    check(held4 == 1, "a normalized title match counts as held")
    check(px.norm_title("A {Held} Title, By Name.") == "a held title by name",
          "titles normalize past braces, case and punctuation")

    # The whole point: one paper wanted by four beats a bulk deposition wanted by one.
    check(ranked[0][0] == "10.1000/wanted",
          f"ranked by citing papers, not by structure count (got {ranked[0][0]})")
    check(len(ranked[0][1]["ids"]) == 1 and len(ranked[0][1]["papers"]) == 4,
          "...even though the runner-up deposited three structures")
    check(len(ranked[1][1]["ids"]) == 3 and len(ranked[1][1]["papers"]) == 1,
          "the bulk deposition is grouped as one paper, ranked below")

    check(px.flat("A title\nsplit over\tlines") == "A title split over lines",
          "titles are flattened -- a newline in a title corrupted a TSV once")
    check(ranked[0][1]["title"] == "A title split over lines",
          "and crossref flattens them on the way in")

    print("\npdbrefs.py: an accession counts only when the text says it is one")
    import pdbrefs as pr

    got = pr.accessions_in("structures were taken from PDB ID 1ABC and PDB code: 2DEF.")
    check(set(got) == {"1ABC", "2DEF"}, f"the common cue forms are read ({sorted(got)})")

    # Papers gloss each entry as they list it; without stepping over the
    # parentheses the list ends at the first gloss.
    got = pr.accessions_in("such as PDB:1H2S (sensory rhodopsin II), 2A65 (a transporter), 1SU4 (an ATPase)")
    check(set(got) == {"1H2S", "2A65", "1SU4"},
          f"a glossed list keeps going past the first parenthetical ({sorted(got)})")

    # The trap that put a piece of software in the library's top ten structures.
    check(pr.accessions_in("prepared with PDB2PQR and pdb2gmx") == {},
          "an accession glued inside a word is not an accession")
    check(pr.accessions_in("prepared with PDB 2PQR59,60 as described") == {},
          "...nor when extraction splits that word with a space")

    # Shape alone matches years, and a bibliography is full of them.
    check(pr.accessions_in("Protein Data Bank, 1997, and see PDB 2001") == {},
          "years are not accessions even after a cue")

    # No cue, no accession -- which is what keeps mangled table cells out.
    check(pr.accessions_in("1SU44 rect 452 62,760 2A654 hexa 386") == {},
          "bare four-character tokens in a table are ignored")

    got = pr.accessions_in("deposited in the Protein Data Bank under accession code 6VXX")
    check(set(got) == {"6VXX"}, f"the deposition sentence form is read ({sorted(got)})")
    got = pr.accessions_in("see https://www.rcsb.org/structure/5FUU for details")
    check(set(got) == {"5FUU"}, f"an rcsb.org URL is read ({sorted(got)})")

    check(pr.accessions_in("PDB ID 1abc")["1ABC"] == 1, "accessions are normalized to upper case")

    print("\nfinding.py: a record is refused unless the quote is really there")
    import finding as fnd

    EXTRACT = (
        "---\nfrontmatter\n---\n\n"
        "<!-- p. 1 -->\n\nJournal of Things 12 (2020) 100-108 100\n"
        "The quick brown fox jumps over the lazy dog.\n\n"
        "<!-- p. 2 -->\n\nSome other text con\ufb01guration \u201cquoted\u201d here.\n"
        "Journal of Things 12 (2020) 100-108 101\n\n"
        "<!-- p. 3 -->\n\nThird page.\nJournal of Things 12 (2020) 100-108 102\n\n"
        "<!-- p. 4 -->\n\nFourth page.\nJournal of Things 12 (2020) 100-108 103\n"
    )

    check("quick brown fox" in fnd.page_text(EXTRACT, 1),
          "page_text returns the text under one marker")
    check("quick brown fox" not in (fnd.page_text(EXTRACT, 2) or ""),
          "and does not bleed into the next page")
    check(fnd.page_text(EXTRACT, 9) is None, "a missing marker page is None, not an exception")

    # Normalization: a quote must match across ligatures, curly quotes and wrapping.
    check(fnd.normalize("con\ufb01guration \u201cquoted\u201d")
          == fnd.normalize("configuration \"quoted\""),
          "ligatures and typographic quotes normalize to the same text")
    check(fnd.normalize("a\nb   c") == "a b c", "line wrapping does not defeat a quote")

    # The offset is DERIVED from recurring edge numbers, never taken on trust.
    check(fnd.derive_offset(EXTRACT) == (99, 4),
          f"a running footer yields the offset ({fnd.derive_offset(EXTRACT)})")

    # A number that appears on every page but is not a page number gives a different
    # offset each time, so it never accumulates a majority.
    NOISE = EXTRACT.replace("Journal of Things 12 (2020) 100-108", "Journal of Things 12 (2020)")
    check(fnd.derive_offset(NOISE) is None or fnd.derive_offset(NOISE)[0] != 99
          or fnd.derive_offset(NOISE)[1] >= 3,
          "removing the page number does not invent one")

    # Two pages can agree by chance; the threshold demands a majority of pages.
    SHORT = "<!-- p. 1 -->\n\nx 5 y\n\n<!-- p. 2 -->\n\nx 6 y\n"
    check(fnd.derive_offset(SHORT) is None,
          "a two-page paper yields no offset rather than a coincidence")

    print("\ncsl_year: the issue year, not the online one")
    from mendeley_push import csl_year

    # The real shape of CHARMM36m's Crossref record: online Nov 2016, issue Jan 2017.
    check(csl_year({"published-online": {"date-parts": [[2016, 11, 7]]},
                    "published-print":  {"date-parts": [[2017, 1]]},
                    "issued":           {"date-parts": [[2016, 11, 7]]}}) == 2017,
          "published-print beats issued (the Advance Access case)")

    # Some records carry the issue date only under journal-issue.
    check(csl_year({"journal-issue": {"published-print": {"date-parts": [[2014]]}},
                    "issued": {"date-parts": [[2013, 11, 22]]}}) == 2014,
          "journal-issue.published-print is used when there is no published-print")

    # A preprint has no print date at all, and issued is then correct.
    check(csl_year({"issued": {"date-parts": [[2025, 7, 10]]}}) == 2025,
          "issued is the fallback for anything never printed")
    check(csl_year({"published-print": {"date-parts": [[2018]]},
                    "issued": {"date-parts": [[2018]]}}) == 2018,
          "agreement is not disturbed")
    check(csl_year({}) is None, "no date at all yields None, not a crash")
    check(csl_year({"issued": {"date-parts": [[None]]}}) is None,
          "a null date-part yields None")

    print("\nHTML entities from Crossref/Mendeley")
    # Real case: Crossref hands back "Molecular Systems Design &amp; Engineering".
    # Escaping without decoding first left "\\&amp;", which renders the entity
    # literally in the bibliography.
    check(mm.tex_escape("Molecular Systems Design &amp; Engineering")
          == r"Molecular Systems Design \& Engineering",
          "&amp; in a journal name decodes to a real ampersand")
    check(mm.tex_escape("ACS Applied Materials &amp; Interfaces")
          == r"ACS Applied Materials \& Interfaces",
          "the other affected journal name too")

    # Decoding must not stop a literal ampersand from being escaped.
    check(mm.tex_escape("Smith & Jones") == r"Smith \& Jones",
          "a literal & is still escaped")
    check(mm.tex_escape("AT&T") == r"AT\&T", "an & inside a word is still escaped")

    # Exactly one level, so a genuinely double-encoded string survives as text.
    check(mm.tex_escape("&amp;amp;") == r"\&amp;", "only one level of decoding is undone")

    check(mm.tex_escape("a &lt;b&gt; c") == "a <b> c", "&lt; and &gt; decode")
    check(mm.tex_escape("caf&eacute;") == "café", "named character entities decode")

    # URLs are emitted raw, so they carry their own decode -- a query string with
    # &amp; between parameters does not resolve when clicked.
    check(mm.html_decode("http://x/?a=1&amp;b=2") == "http://x/?a=1&b=2",
          "&amp; in a URL query string decodes")

    print("\nmendeley_edit: what gets PATCHed")
    import mendeley_edit as me

    DOC = {"title": "A paper", "year": 2016, "type": "generic",
           "source": "Nature Methods",
           "identifiers": {"doi": "10.1038/old", "issn": "1548-7091", "pmid": "27819658"}}

    # A field already equal to Mendeley's value must not be re-sent -- this is
    # what makes a re-run after a partial failure safe.
    patch, _ = me.plan_patch(DOC, {"year": 2016, "source": "Nature Methods"})
    check(patch == {}, f"fields already correct are skipped (got {patch})")

    patch, lines = me.plan_patch(DOC, {"year": 2017})
    check(patch == {"year": 2017}, "a changed field is patched")
    check(any("2016" in l for l in lines) and any("2017" in l for l in lines),
          "the diff shows both the old and the new value")

    # The rule that keeps a DOI correction from destroying other identifiers.
    patch, _ = me.plan_patch(DOC, {"identifiers": {"doi": "10.1126/new"}})
    check(patch["identifiers"]["doi"] == "10.1126/new", "the DOI is replaced")
    check(patch["identifiers"]["issn"] == "1548-7091"
          and patch["identifiers"]["pmid"] == "27819658",
          "identifiers is MERGED -- issn and pmid survive a DOI correction")

    patch, _ = me.plan_patch(DOC, {"identifiers": {"doi": "10.1038/old"}})
    check(patch == {}, "an identifiers block that changes nothing is not sent")

    # A field the document does not have yet is an addition, not a skip.
    patch, _ = me.plan_patch(DOC, {"pages": "71--73"})
    check(patch == {"pages": "71--73"}, "a field absent from the document is added")

    # null REMOVES. The merge above protects good identifiers; without an
    # explicit removal it also made a bad one impossible to delete, and a DOI
    # that resolves to an unrelated paper is worse than no DOI at all.
    patch, _ = me.plan_patch(DOC, {"identifiers": {"doi": None}})
    check(patch["identifiers"] == {"issn": "1548-7091", "pmid": "27819658"},
          "a null identifier is removed and the others survive")
    patch, _ = me.plan_patch(DOC, {"identifiers": {"doi": None, "isbn": "978"}})
    check(patch["identifiers"] == {"issn": "1548-7091", "pmid": "27819658", "isbn": "978"},
          "removal and addition compose in one edit")
    patch, _ = me.plan_patch(DOC, {"identifiers": {"doi": None, "issn": None, "pmid": None}})
    check(patch == {"identifiers": {}}, "removing every identifier sends an empty object")
    patch, _ = me.plan_patch(DOC, {"identifiers": {"arxiv": None}})
    check(patch == {}, "removing an identifier the document does not have is a no-op")

    patch, _ = me.plan_patch({"identifiers": {}}, {"identifiers": {"doi": "10.1/x"}})
    check(patch == {"identifiers": {"doi": "10.1/x"}},
          "merging into an empty identifiers block works")

    print("\n" + ("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILURES: {fails}"))
    print("sample entry:\n")
    print(bib.split("@")[1][:600])
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
