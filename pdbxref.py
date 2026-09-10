#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31"]
# ///
"""
pdbxref.py -- structures the library cites whose primary papers it does not hold.

`pdbrefs.py` reads accessions out of the mirrored text. This asks RCSB what paper
each one came from, and checks that paper against `library.bib`.

    uv run --script pdbxref.py                  # ranked summary
    uv run --script pdbxref.py --min 3          # only what 3+ papers reach for
    uv run --script pdbxref.py --tsv gap.tsv    # full table

**Rank by how many LIBRARY PAPERS reach for a structure, not by how many
structures share a paper.** Those are different questions and only the first one
is useful. A single deposition often lands a dozen entries at once, so ranking by
entry count promotes whichever group deposited in bulk. Ranked by demand instead,
the shape of this library's own field appears at the top -- and in practice ~80%
of the gap is wanted by exactly one paper, which usually means somebody borrowed
coordinates rather than needing the argument.

**This produces a prompt, not a want-list.** That a structure keeps being reached
for is evidence the paper might be worth holding; whether it actually is depends
on what the structure is being used FOR, which is a judgment about the science and
belongs to the person whose library it is.

**Two things it cannot see.** An entry with no primary-citation DOI in RCSB is
invisible here rather than absent -- older depositions especially. And accessions
RCSB does not recognize at all are reported separately: some are obsoleted
entries, some are false positives escaping `pdbrefs.py`, and either way that count
is the only external measurement of the local index's precision. Read it as such.

**Unlike a paper, a PDB entry is not frozen.** Entries get re-refined, superseded
and obsoleted, so an answer here is true on the day it was asked. Output carries
the date for that reason; a claim about a structure has a shelf life a claim about
a published page does not.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    import requests
    from mendeley_mirror import DEFAULT_OUT
    from pdbrefs import scan
except ImportError as exc:  # pragma: no cover
    sys.exit(f"pdbxref.py must sit beside the other mirror scripts ({exc})")

API = "https://data.rcsb.org/graphql"
UA = "mendeley-mirror pdbxref (mailto:cfa22@drexel.edu)"
QUERY = ("{entries(entry_ids:[%s]){rcsb_id struct{title} "
         "rcsb_primary_citation{pdbx_database_id_DOI title year journal_abbrev} "
         "rcsb_accession_info{status_code}}}")


def flat(s: str | None) -> str:
    """Collapse whitespace. Citation titles carry newlines; a TSV row cannot."""
    return " ".join((s or "").split())


def library_dois(out: Path) -> set[str]:
    bib = (out / "library.bib").read_text(encoding="utf-8")
    return {m.group(1).strip().lower()
            for m in re.finditer(r"^\s*doi\s*=\s*\{(.*?)\}", bib, re.M)}


def crossref(entries: list[dict], have: set[str], acc2papers: dict[str, set[str]]):
    """(ranked gap, held, no_doi) -- pure, so the ranking is testable offline.

    RCSB returns DOIs in mixed case ("10.1126/SCIENCE.AAD2450"), so both sides are
    lowered before comparison; without that every Science structure looks missing.
    """
    gap: dict[str, dict] = {}
    held = no_doi = 0
    for e in entries:
        cit = (e or {}).get("rcsb_primary_citation") or {}
        doi = (cit.get("pdbx_database_id_DOI") or "").strip().lower()
        if not doi:
            no_doi += 1
            continue
        if doi in have:
            held += 1
            continue
        g = gap.setdefault(doi, {"year": cit.get("year"),
                                 "journal": flat(cit.get("journal_abbrev")),
                                 "title": flat(cit.get("title")),
                                 "ids": set(), "papers": set()})
        acc = e["rcsb_id"].upper()
        g["ids"].add(acc)
        g["papers"] |= acc2papers.get(acc, set())
    ranked = sorted(gap.items(), key=lambda kv: (-len(kv[1]["papers"]), -len(kv[1]["ids"]), kv[0]))
    return ranked, held, no_doi


def fetch(accs: list[str], batch: int = 60) -> tuple[list[dict], list[str]]:
    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    got, unresolved = [], []
    for i in range(0, len(accs), batch):
        chunk = accs[i:i + batch]
        ids = ",".join(f'"{a}"' for a in chunk)
        for attempt in range(3):
            try:
                r = sess.post(API, json={"query": QUERY % ids}, timeout=60)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(2 * (attempt + 1))
        else:
            unresolved += chunk
            continue
        seen = set()
        for e in (r.json().get("data", {}).get("entries") or []):
            if e:
                seen.add(e["rcsb_id"].upper())
                got.append(e)
        unresolved += [a for a in chunk if a not in seen]
        print(f"  {min(i + batch, len(accs))}/{len(accs)}", file=sys.stderr, flush=True)
    return got, unresolved


def main() -> int:
    ap = argparse.ArgumentParser(description="Structures cited here whose papers are not held.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="mirror directory")
    ap.add_argument("--min", type=int, default=1, help="only papers wanted by at least N library papers")
    ap.add_argument("--tsv", type=Path, help="write the full table here")
    ap.add_argument("--top", type=int, default=15, help="how many to print")
    args = ap.parse_args()

    out = args.out.expanduser()
    by_key = scan(out)
    acc2papers: dict[str, set[str]] = {}
    for key, hits in by_key.items():
        for acc in hits:
            acc2papers.setdefault(acc, set()).add(key)
    accs = sorted(acc2papers)
    if not accs:
        sys.exit("error: pdbrefs found no accessions -- is text/ populated?")

    have = library_dois(out)
    print(f"{len(accs)} accessions from {len(by_key)} papers; library holds {len(have)} DOIs",
          file=sys.stderr)
    entries, unresolved = fetch(accs)
    ranked, held, no_doi = crossref(entries, have, acc2papers)

    today = _dt.date.today().isoformat()
    print(f"\n# PDB cross-reference, {today}  (an entry is not frozen -- this is true today)")
    print(f"resolved by RCSB        : {len(entries)}")
    print(f"unrecognized accessions : {len(unresolved)}  <- obsolete, or pdbrefs false positives")
    print(f"no primary-citation DOI : {no_doi}  <- invisible here, not absent")
    print(f"primary citation held   : {held}")
    print(f"primary citation MISSING: {sum(len(g['ids']) for _, g in ranked)}"
          f" structures, {len(ranked)} distinct papers")

    dist = [len(g["papers"]) for _, g in ranked]
    if dist:
        one = sum(1 for x in dist if x <= 1)
        print(f"  wanted by 1 paper : {one} ({100*one/len(dist):.0f}%) -- usually borrowed coordinates")
        print(f"  wanted by 3+      : {sum(1 for x in dist if x >= 3)}")
        print(f"  wanted by 5+      : {sum(1 for x in dist if x >= 5)}")

    shown = [(d, g) for d, g in ranked if len(g["papers"]) >= args.min]
    print(f"\nwanted by >= {args.min} library paper(s), most-wanted first:\n")
    for doi, g in shown[:args.top]:
        print(f"{len(g['papers']):>3} papers · {len(g['ids'])} structure(s) · {g['year']} · {g['journal']}")
        print(f"    {g['title'][:96]}")
        print(f"    {doi}   {','.join(sorted(g['ids']))[:60]}")

    if args.tsv:
        with args.tsv.open("w", encoding="utf-8") as f:
            f.write(f"# generated {today}; PDB entries are versioned, this is true as of that date\n")
            f.write("library_papers\tn_structures\tdoi\tyear\tjournal\ttitle\tstructures\tciting_papers\n")
            for doi, g in ranked:
                f.write(f"{len(g['papers'])}\t{len(g['ids'])}\t{doi}\t{g['year']}\t{g['journal']}\t"
                        f"{g['title']}\t{','.join(sorted(g['ids']))}\t{','.join(sorted(g['papers']))}\n")
        print(f"\nfull table: {args.tsv}")
    if unresolved:
        print(f"\nunrecognized by RCSB ({len(unresolved)}): {', '.join(sorted(unresolved))}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
