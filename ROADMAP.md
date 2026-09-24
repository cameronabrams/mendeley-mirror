# Roadmap

What this tool is likely to do next, why, and — for the things deliberately not
being done — what would change that. Items move by being finished or by being
struck out with a reason; nothing here is a promise about a date.

---

## 1. Zotero as a second backend, then the primary one

**Why.** Mendeley's API is running on inertia. The developer portal's most
recent content is dated **2 November 2020**, and the last substantive change was
the February 2021 round that *removed* endpoints. There is no sunset notice and
no sign of maintenance either. Meanwhile Elsevier encrypted the local Mendeley
database, so Zotero's local importer only works against Mendeley Desktop 1.18,
from before the encryption; the supported migration path is an **online import
through the same API this tool depends on**. The escape route runs through the
thing that might fail, which is the argument for not being caught flat-footed.

Zotero, by contrast, is developed by a non-profit whose whole team it employs,
is open source, and keeps its data in a local SQLite database you can read
without asking anyone. The longevity case is not that the organization will
outlive Elsevier — it is that if it did not, the data is still readable.

**Exposure today is low and should be stated plainly**, so this is done
carefully rather than urgently: the mirror is one-way, so `library.bib`, the
page-marked extracts, `annotations/` and `findings/` are already a complete,
service-independent corpus. If the API went dark tonight, what stops is refresh
and filing — not the library.

**The hard part is not the API. It is the citation keys.**

`assign_citekeys` assigns a key once per *document id* and never changes it, and
those keys are cited in manuscripts and are the file names under `findings/`.
A naive re-import under Zotero item ids would reassign all ~2,700 of them: every
citation in a draft would rot and every findings file would orphan. So:

- [x] Namespace the identifiers (`mendeley:<id>`, `zotero:<id>`) in
      `citekeys.json` and in `state.json`, which is keyed by Mendeley *file* id.
      **Done 2026-09-24**, before any key is assigned from a second source, which
      was the whole point — it is impossible to retrofit safely afterwards.
      Migration is automatic and idempotent; a bare id still reads as Mendeley's,
      so a map written by an older version stays readable. Verified against the
      live library on a copy: 2,727 of 2,727 keys resolve to the same paper, no
      key text changed, and 2,733 of 2,733 attachment states keep their filehash,
      so nothing re-extracts.
- [ ] Write the migration map by matching old records to new: DOI first, then
      title+year, then by hand. Report the unmatched rather than guessing —
      roughly 17% of this library's records carry no DOI.
- [x] Assert, as a test, that every pre-migration citation key still resolves to
      the same paper afterwards. This is the acceptance criterion; everything
      else is mechanics. It is in `test_mirror.py` and it covers the case that
      matters next: entries from a second backend added to an existing map must
      not renumber the first backend's.

**The mechanics really are mechanics.** The Mendeley-specific surface in
`mendeley_mirror.py` is one base URL, one media type string, one `Mendeley`
class and two `document_id` references. Extraction, page markers, BibTeX,
annotations and findings all work on a generic document/file/annotation shape.

- [ ] **Test the escape hatch before relying on it** — run Zotero's online
      importer once into a throwaway profile and confirm items, attachments and
      annotations arrive intact. An exit nobody has tested is not an exit.
      *Note: the importer downloads every attachment — around 5–8 GB for this
      library. Not a thing to do on a hotel connection; it waits for home.*
- [ ] Abstract the client behind the small interface the rest of the code
      already implies: list documents, list files, fetch file, list annotations.
- [ ] Decide what "primary" means for the writing scripts (`inbox.py`,
      `mendeley_push.py`, `mendeley_edit.py`). They may only ever target one
      account; pointing them at the wrong one is the expensive mistake.

---

## 2. Make a failing refresh loud

**Why.** The failure this tool is least equipped to notice is silent
authentication death: the timer keeps firing, `mirror-status.md` keeps being
rewritten, and a reader three weeks later sees a file that *looks* maintained.
Every claim about mirror state has a shelf life of under an hour, and nothing
currently shouts when that stops being true.

- [x] Distinguish an auth failure from a transient network failure in the status
      file and the log, and say which. `classify_failure` returns auth / network /
      interrupted / other, and each gets different advice. Failing to *reach* the
      token endpoint classifies as network, not auth, which is the confusion this
      item was written about.
- [x] Surface consecutive-failure count, so "failed once" and "has not succeeded
      in nine days" do not read the same. `.mirror/health.json` holds the streak
      and its start; one success clears it.

**Brought forward 2026-09-24.** Cameron's Mendeley membership auto-renews
2027-01-01 and cancelling is the plan, so the account's behaviour will change on
a known date. An auth failure arriving as a shrug was a general risk when this
item was written; with a cancellation date it is a specific one.

Still open, and now the interesting part: **nothing reads the status file unless
a person opens it.** The streak is recorded and legible, but a mirror that has
not refreshed in nine days still announces it only to whoever looks. That is
acceptable while the library session reads the file routinely; it stops being
acceptable the moment nobody does.

This matters more given item 1: an auth failure is exactly the signal that says
*migrate now*, and it should not arrive as a shrug.

---

## 3. Continuous integration

**Why.** 220 offline checks that pass on one laptop and nowhere visible. Now
that the repo is licensed and published, a green badge is the cheapest possible
evidence that it works, and the test suite needs no credentials and no network.

- [ ] A GitHub Actions workflow running `uv run --script test_mirror.py` on push.
- [ ] Run it on Windows as well as Linux — the Windows launchers exist precisely
      because that platform behaves differently, and nothing tests them.

---

## 4. Better page-offset derivation

**Why.** Re-measured 2026-09-23 against the 2,425 extracts whose bib entry
records a numeric first page — a larger set than the 2,129 the `derive_offset`
docstring quotes, because the library has grown, so the two are not directly
comparable. The edge scan derives 2,109 offsets: **1,789 right, 320 wrong**, and
refuses 316. Every one of those 320 is a plausible-looking journal page that
nobody will re-check.

**What the 09-21 tie-refusal cost, which was never measured at the time.**
Before `d902a36` the scan derived 2,322: 1,903 right and 419 wrong. So that fix
removed 99 wrong derivations and 114 correct ones — precision 82.0% → 84.8%,
and **137 papers that used to derive correctly now refuse**. The trade is
defensible (a refusal is loud, a wrong locator is silent and gets copied into a
manuscript) but it was made blind, and `literature` found it as a regression
against a locator its own findings file already carried: `Knight2015Memgen`,
derived +2896 on 09-09, refused on 09-23.

Of those 137, `confirm_offset` accepts the true first page for **120** once the
operator passes `--journal-page`. Seventeen still need a hand-recorded locator.

- [ ] Recover the 17 the confirm path cannot reach.
- [ ] Treat the bib page range as evidence when the record has one. The
      derivation currently ignores a number the library already knows — and it
      is the cheap oracle that would have caught this regression on the day.
- [x] Regression corpus — **built and run 2026-09-23 by `literature`**, which
      proposed it. Every `## N · FINDING ·` record in its `findings/*.md` carries
      a (citekey, marker page, printed page) tuple checked by hand when it was
      written: 98 records across 57 files, an oracle this tool did not generate.
      Replayed against `53cedcc`: 89 agree, 4 disagree, **0 lost, 0 gained**, 5
      bare-marker records with nothing to compare. No paper that carried a
      printed page lost one.

      All four disagreements are papers the 09-21 hand audit had already caught
      and retracted — Ikeno2011Molecular, Lin1999Effect, Hamerton1996Molecular,
      Kendrick1990Calculated. Four of four known positives, zero false alarms,
      and the first time the code and that audit name the same four papers.

      It lives in the library session because that is where the findings are.
      This repo's own suite cannot replace it: `test_mirror.py` fixtures are
      written by whoever writes the code, and three of them this month encoded
      an assumption rather than a fact. An oracle built by the tool's *user*,
      before the change existed, is the only kind that can contradict it.

**Measured and rejected 2026-09-23:** widening the edge window from characters
to whole lines (first and last *n* non-blank lines, in addition to
`EDGE_CHARS`). It recovers real papers — 1,880 correct at *n*=2 against 1,789 —
but carries 368 wrong against 320, so precision falls to 83.6%. Deriving is the
silent path; buying recall with precision there is backwards. The same insight
*was* a clean win in `confirm_offset` (`53cedcc`), where the human supplies the
hypothesis and the wrong-claim rate did not move at all.

---

## 5. Mark a proof extract at extraction, not at inspection

**Why.** Fourteen extracts in this library carry placeholder pagination —
`xxx–xxx`, `XXXX, XXX, 000–000` — because the PDF is an accepted proof rather
than the version of record. Nothing says so. `get_pdf.py --attachments` lists
them and names which of a pair to cite, but that is a report someone has to run;
a proof filed on its own still reads as a normal paper.

Fourteen is this pattern's count, and it is not obviously the right one. A
tighter pattern run by the library session found five, of which it judged one
spurious — but that one, `Price2008Hydrogen`, is genuine: the line is the
article's own ASAP footer, `Biochemistry XXXX, xxx, 000–000 … Published on Web
05/22/2008`. Every one of the fourteen sits beside a journal name and a DOI on
inspection, which is what an article-level footer looks like and not what a
reference to someone else's in-press paper looks like. That is evidence, not
proof, and the number should be settled by the extraction-time check below
rather than by comparing two regexes.

The consequence is specific: an extract's own front matter invites a reader to
cite it, and the page markers of a proof are not the journal's pages. It is the
same failure family as the OCR'd scans, where `ocr: true` and a banner were
added precisely so a machine-read extract could not be quoted as if typeset.

- [ ] Detect placeholder pagination during extraction and record it in the front
      matter, the way `ocr: true` is recorded, with a line in the extract saying
      the page numbers are not citable.
- [ ] Announce it first: this changes `text/<key>.md`, which is a contract, and
      it only takes effect on re-extraction.
- [ ] Consider whether `finding.py` should refuse to derive an offset from a
      proof at all. It currently will, and the number it produces is real
      arithmetic over meaningless input.

---

## Renamed, and what still carries the old name

The project became **offprint** on 2026-09-21, in anticipation of Zotero: a module
called `mendeley_mirror` that also talks to Zotero would be actively misleading.
An offprint is a separately printed copy of one article, pulled from the issue and
kept — which is what this produces, and what survives when the service does not.

Changed: the GitHub repository, the clone directory, the documentation, and the
name the tool prints in `mirror-status.md` and `--version`.

**Still called mendeley-mirror, deliberately:**

- `~/.config/mendeley-mirror` and `~/.cache/mendeley-mirror`. Renaming these
  loses the saved credentials and the PDF cache unless a migration is written;
  `mirror_state_dir()` already carries one such migration, which is the going
  rate. Invisible to users, so the cost buys nothing.
- The systemd unit `mendeley-mirror.service`/`.timer`, which is referenced from
  the file-inbox skill, the library's own CLAUDE.md, and `inbox.py`'s
  `REFRESH_UNIT`. Renaming it is a stop/disable/enable dance on the one job that
  must not silently stop.
- The Read the Docs project, so the published URL is still
  mendeley-mirror.readthedocs.io. Renaming it there changes a URL the README
  advertises.
- `mendeley_mirror.py` and the `from mendeley_mirror import` in eight scripts.
  **This one is deferred on purpose:** it belongs in the same change as the
  backend abstraction in item 1, so there is one refactor rather than two.
  `mendeley_push.py` and `mendeley_edit.py` keep their names permanently — they
  write to Mendeley specifically, and that stays true.

## Deliberately not doing

**Packaging (PyPI, conda-forge, console entry points).** The PEP 723 headers
mean `uv run --script` needs nothing installed, which is what makes this work on
a bare Windows laptop. A package would add a release process paid on every
change, for the benefit of users who do not exist yet.
*What would change it:* a second person needing to install it, or a machine in
the fleet that should run it without a clone.

**A pyproject.toml purely to deduplicate the ten dependency headers.** The test
suite now checks that every header matches what its script actually imports, and
fails on both a forgotten dependency and a spurious one. The duplication is
visible and verified rather than silent.

**Rewriting the test runner as pytest.** It is a bespoke runner, which is
unusual, but it is offline, dependency-light and prints a line per check. The
cost of converting is paid immediately and the benefit arrives with the first
outside contributor.
*What would change it:* an outside contributor.
