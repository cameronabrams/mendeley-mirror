#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31"]   # transitive: mendeley_mirror imports it for DEFAULT_OUT
# ///
"""
finding.py -- record what was asked of a paper and where the answer is.

The mirror preserves what papers SAY. This preserves what was asked of them and
where the answer sat, so a question answered once is not re-derived from nothing
six months later. Records live in `<out>/findings/<citekey>.md`.

    uv run --script finding.py --key Jo2007Automated \
        --question "does it optimize the protein's embedding?" \
        --page 2 --journal-page 2 --asked-by pestifer-manuscript \
        --quote "one should align it in a local machine and then upload it" \
        --used-for "Introduction, placement claim"

    uv run --script finding.py --key Jo2007Automated --check 1 --by cfa \
        --note "quote and locator confirmed against the PDF"

    uv run --script finding.py --key Jo2007Automated --retract 1 \
        --note "superseded: the sentence is conditional, see record 4"

**A record locates a passage; it never substitutes for one.** The moment one is
consulted instead of the extract it becomes a paraphrase indistinguishable from the
source, which is the whole thing deterministic extraction exists to prevent. Every
record carries a locator good enough to return to the passage in one step, and the
file header says this to whoever opens it.

**Files are append-only.** A finding later found wrong gets a RETRACTED record
pointing at it; the original stays. That is what makes retraction latency visible
rather than tidied away, and a checked record is likewise appended rather than
edited in, so it carries who checked and when.

**The quote is verified before the record is written.** It must actually appear in
`text/<citekey>.md` under the marker page claimed for it, after Unicode and
whitespace normalization. A quote that cannot be found is refused, not filed with a
warning -- a misattributed quote is the failure that reads as correct at the time,
so it is the one worth making structurally hard. If --journal-page is given, that
number must also appear on the marker page, which is the both-ends offset check.

This script never touches Mendeley and never writes outside `<out>/findings/`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    from mendeley_mirror import DEFAULT_OUT
except ImportError as exc:  # pragma: no cover
    sys.exit(f"finding.py must sit beside the other mirror scripts ({exc})")

HEADER = """# Findings: {key}

*Records **locate** a passage; they never substitute for one. Re-read
`text/{key}.md` before quoting anything below. Append-only: corrections are
appended as RETRACTED records, never edited in.*
"""


def die(msg: str):
    sys.exit(f"error: {msg}")


def normalize(s: str) -> str:
    """Compare quotes the way a reader would, not the way bytes do.

    Extracted text carries ligatures (con<fi>guration), typographic quotes and
    dashes, and line breaks wherever the PDF happened to wrap. None of that should
    decide whether a quote is really on the page.
    """
    s = unicodedata.normalize("NFKC", s)
    for a, b in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), ("−", "-"), ("­", "")):
        s = s.replace(a, b)
    # A bad glyph map drops control characters into the extract where a symbol
    # was: Kucerka 2005 carries "30\x01C" for "30 degrees C". Those must not
    # decide whether a quote is on the page, so they go the way of the
    # zero-width joiners -- same classes mendeley_mirror strips, plus Cc.
    # ...but newline and tab are Cc too, and they are word separators, not junk:
    # dropping them joins the words either side and defeats a real quote.
    s = "".join(ch for ch in s
                if ch.isspace() or unicodedata.category(ch) not in ("Cc", "Cf", "Co"))
    return " ".join(s.lower().split())


def page_text(extract: str, page: int) -> str | None:
    """The text under one `<!-- p. N -->` marker, or None if there is no such page."""
    marks = [(m.start(), m.end(), int(m.group(1)))
             for m in re.finditer(r"<!-- p\. (\d+) -->", extract)]
    for i, (_s, e, n) in enumerate(marks):
        if n == page:
            end = marks[i + 1][0] if i + 1 < len(marks) else len(extract)
            return extract[e:end]
    return None


def derive_offset(extract: str) -> tuple[int, int] | None:
    """(offset, how many pages agree), or None if the printed pages cannot be read.

    Do not trust a claimed page number: derive it. A running head or footer prints
    the journal page, so for each marker page collect the integer tokens near the
    EDGES of its text and take the offset that recurs. Anything that appears on
    every page but is not a page number -- a volume, a DOI fragment, an article
    number like 2040011 -- yields a different offset on each page and falls out of
    the tally by itself.

    Requiring recurrence is the point. The first version of this function asked
    whether the claimed number appeared anywhere on the page, which on a dense page
    is true of almost any small integer: a check that could not fail, reported as
    "verified".
    """
    marks = [(m.start(), m.end(), int(m.group(1)))
             for m in re.finditer(r"<!-- p\. (\d+) -->", extract)]
    tally: dict[int, int] = {}
    for i, (_s, e, n) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(extract)
        body = extract[e:end]
        edges = body[:300] + " " + body[-400:]
        cands = re.findall(r"(?<![\d.-])(\d{1,5})(?![\d.])", edges)
        # Article-number journals print "2040011-9" and have no journal page at all;
        # the suffix is the page. Without this easyAmber derived a WRONG offset that
        # four pages happened to agree on, which is worse than deriving none.
        cands += re.findall(r"\b\d{5,8}-(\d{1,3})\b", edges)
        seen = set()
        for tok in cands:
            off = int(tok) - n
            if off not in seen:            # one vote per page per offset
                seen.add(off)
                tally[off] = tally.get(off, 0) + 1
    if not tally:
        return None
    best = max(tally.items(), key=lambda kv: (kv[1], -abs(kv[0])))
    # A real running footer appears on nearly every page. A coincidence appears on a
    # few. Requiring a clear majority is what separates them -- on the eight papers
    # whose offsets were derived by hand, every true offer agreed on 100% of pages
    # and the one false candidate on 21%.
    need = max(3, int(0.6 * len(marks)))
    return best if best[1] >= need else None


def next_ordinal(path: Path) -> int:
    if not path.exists():
        return 1
    nums = [int(m.group(1)) for m in re.finditer(r"^## (\d+) ", path.read_text(encoding="utf-8"), re.M)]
    return max(nums, default=0) + 1


def existing_ordinals(path: Path) -> set[int]:
    if not path.exists():
        return set()
    return {int(m.group(1)) for m in re.finditer(r"^## (\d+) ", path.read_text(encoding="utf-8"), re.M)}


def append(path: Path, key: str, block: str, dry_run: bool) -> None:
    if dry_run:
        print(f"--- would append to {path} ---\n{block}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(HEADER.format(key=key), encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n" + block)
    print(f"appended to {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Record what was asked of a paper and where the answer is.")
    ap.add_argument("--key", required=True, help="citation key")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="mirror directory")
    ap.add_argument("--dry-run", action="store_true", help="show the record, write nothing")
    # a finding
    ap.add_argument("--question", help="what was asked")
    ap.add_argument("--quote", help="the verbatim sentence that answered it")
    ap.add_argument("--page", type=int, help="extract marker page the quote is on")
    ap.add_argument("--journal-page", help="printed page, if the journal has one")
    ap.add_argument("--asked-by", default="", help="who asked")
    ap.add_argument("--used-for", default="", help="what the answer was used for")
    # the other two record types
    ap.add_argument("--check", type=int, metavar="N", help="append a CHECKED record for finding N")
    ap.add_argument("--retract", type=int, metavar="N", help="append a RETRACTED record for finding N")
    ap.add_argument("--by", default="", help="who checked")
    ap.add_argument("--note", default="", help="note for a CHECKED or RETRACTED record")
    args = ap.parse_args()

    out = args.out.expanduser()
    path = out / "findings" / f"{args.key}.md"
    today = _dt.date.today().isoformat()

    if args.check is not None or args.retract is not None:
        n = args.check if args.check is not None else args.retract
        kind = "CHECKED" if args.check is not None else "RETRACTED"
        have = existing_ordinals(path)
        if n not in have:
            die(f"{args.key} has no record {n}" + (f" (has {sorted(have)})" if have else " (no findings yet)"))
        who = f" · {args.by}" if args.by else ""
        body = f"re: {n} — {args.note}" if args.note else f"re: {n}"
        append(path, args.key, f"## {next_ordinal(path)} · {kind} · {today}{who}\n{body}\n", args.dry_run)
        return 0

    if not (args.question and args.quote and args.page):
        die("a finding needs --question, --quote and --page (or use --check / --retract)")

    extract = out / "text" / f"{args.key}.md"
    if not extract.exists():
        die(f"no extract at {extract} -- is {args.key} a citation key this mirror knows?")
    text = extract.read_text(encoding="utf-8", errors="replace")

    page = page_text(text, args.page)
    if page is None:
        pages = [int(m.group(1)) for m in re.finditer(r"<!-- p\. (\d+) -->", text)]
        die(f"{args.key} has no marker page {args.page} (it has 1-{max(pages) if pages else 0})")

    if normalize(args.quote) not in normalize(page):
        where = [n for n in (int(m.group(1)) for m in re.finditer(r"<!-- p\. (\d+) -->", text))
                 if (pt := page_text(text, n)) and normalize(args.quote) in normalize(pt)]
        hint = f" -- but it IS on marker page {where[0]}" if where else ""
        die(f"that quote is not on marker page {args.page} of {args.key}{hint}. "
            f"Nothing written. Re-read the extract rather than adjusting the quote.")

    locator = f"marker p. {args.page}"
    derived = derive_offset(text)
    if args.journal_page:
        if derived is None:
            die(f"cannot derive a page offset for {args.key} -- its printed page numbers do not "
                f"survive extraction, so --journal-page cannot be verified. Record it without "
                f"--journal-page and cite the marker, or check the rendered page by hand.")
        off, agree = derived
        want = args.page + off
        if str(args.journal_page).strip() != str(want):
            die(f"offset says marker p. {args.page} is printed page {want} "
                f"(offset {off:+d}, agreeing on {agree} pages), not {args.journal_page}. "
                f"Nothing written.")
        locator += f" · printed {want} (offset {off:+d}, derived from {agree} pages)"
    elif derived:
        off, agree = derived
        locator += f" · printed {args.page + off} (offset {off:+d}, derived from {agree} pages)"

    lines = [f"## {next_ordinal(path)} · FINDING · {today}",
             f"question:  {args.question}"]
    if args.asked_by:
        lines.append(f"asked-by:  {args.asked_by}")
    lines.append(f"locator:   {locator}")
    lines.append("")
    lines += ["> " + ln for ln in args.quote.strip().splitlines()]
    if args.used_for:
        lines += ["", f"used-for:  {args.used_for}"]
    append(path, args.key, "\n".join(lines) + "\n", args.dry_run)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
