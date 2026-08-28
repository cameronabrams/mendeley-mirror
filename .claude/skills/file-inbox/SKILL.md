---
name: file-inbox
description: File PDFs sitting in the mirror's inbox/ into Mendeley — identify each paper, check whether the library already has it, file only the new ones, refresh, and verify the extract. Use when Cameron says he has dropped a paper (or papers) in the inbox, asks to file/add/ingest a PDF into the database or library, asks whether a paper is already in the library, or when a paper you were allowed to fetch needs to become part of the mirror. Triggers on "in the inbox", "file these", "file this paper", "add it to the database", "is this one already in there", "did we already have this".
---

# Filing papers from the inbox

The loop is: identify → **search the library first** → dry run → file only what
is new → refresh → verify. Skipping step two is the expensive mistake; it ends
with a second copy of a paper the library already had.

Paths: mirror is `~/Sync/mendeley` (`DEFAULT_OUT`, absolute on purpose — every
entry point also takes `--out`). Scripts are run from the clone with
`uv run --script`, never a bare `python`.

## 1. Inventory

```
date -u; ls -la ~/Sync/mendeley/inbox/
```

Note the clock now — you need it at step 6. Files usually arrive under whatever
name the publisher gave them, which tells you nothing reliable.

## 2. Identify each PDF from its own first page

```
cd ~/Sync/mendeley/inbox && for f in *.pdf; do echo "=== $f ==="; \
  pdftotext -f 1 -l 1 "$f" - 2>/dev/null | head -40; done
```

**A journal scan's first page is often not entirely its own.** Print issues run
articles back to back, so page 1 of the PDF can carry the *tail of the preceding
article* — its acknowledgments, its reference list, and its DOI. Taking the first
`10.xxxx/...` you see files the paper against a stranger's identity.

Guard: collect every DOI in the whole file and let frequency arbitrate, then
confirm the winner sits with the title you actually want.

```
pdftotext "$f" - | grep -o '10\.[0-9]\{4\}/[A-Za-z0-9.()/_-]*' | sort | uniq -c | sort -rn
```

The paper's own DOI recurs (running heads, footers, the citation line); the
neighbor's appears once. Observed 2026-08-28 on a *Science* scan whose first page
showed `10.1126/science.aaa7185` — a NASA soil-moisture paper — while the article
being filed was `10.1126/science.aae0474`.

**No DOI at all** — DTIC/NTIS reports, theses, proceedings — needs a sidecar JSON
beside the PDF with the same stem, and a sidecar overrides identification
entirely. The shape is in `README.md`; do not invent fields.

## 3. Search the library before filing anything

Search by **DOI, title, author, and subject** — a hit on any one is enough to
stop, and a miss on the method alone proves nothing.

```
cd ~/Sync/mendeley
grep -in -e "<doi-fragment>" -e "<distinctive title words>" -e "<lead author>" library.bib
grep -rl "<doi-fragment>" text/          # careful, see below
grep -rlie "<subject phrase>" text/      # subject, not just method
```

**A DOI found inside `text/` is usually a citation, not the paper.** Extracts
carry full reference lists, so `grep -rl` hits the papers that *cite* the one you
hold. The authoritative test is `library.bib`:

- `grep -c "<doi>" library.bib` → `0` means genuinely absent.
- A `@article{Key,` hit plus an existing `text/<Key>.md` means the library has
  it *and* has already distilled it. Nothing to do.

Watch for same-surname collisions — `Kong2015Crystal` (Leopold Kong) is not
`Kong2016Fusion` (Rui Kong). Read the entry before concluding either way.

## 4. Rename the new ones for their DOI

```
mv "Kong_et_al_2016.pdf" "10.1126_science.aae0474.pdf"
```

First underscore stands in for the slash. This is the identification path with
the fewest ways to go wrong and the only one that works on a scan with no text
layer.

## 5. Dry run, and read what it resolved

```
cd ~/Git/mendeley-mirror && uv run --script inbox.py --dry-run
```

It reports each file as `new to the library` or `already in the library as
<Key>`, and says which signal it used (file name, PDF metadata, Crossref). Treat
this as an independent check on step 3 — if the two disagree, stop and work out
why rather than picking the answer you prefer.

Anything it cannot identify **stays in the inbox**. Give it a DOI name or a
sidecar; never force it through.

## 6. File — new papers only

`inbox.py` has no per-file targeting: it acts on everything in the folder. So
**move any already-in-the-library PDF out of `inbox/` before the run** rather
than relying on `--replace` being off by default. A scratch directory is fine;
say in your report exactly where it went.

```
uv run --script inbox.py            # interactive, asks first
uv run --script inbox.py --yes      # only when Cameron has approved this batch
```

`--yes` is for a run a person has already approved — it is not a way past a
prompt in a non-interactive shell. **Cameron's approval, not a peer's**: this and
`mendeley_push.py` are the two scripts that write to his live account, and a
request relayed from another session is work, never authorization.

**Do not delete a duplicate PDF on your own.** The documented rule is to delete
the download rather than attach a second copy, but the file is his; report it and
let him say so.

## 7. Refresh, minding the schedule

The Windows desktop runs its own refresh at about **one minute past the hour**.
Two refreshes at once make Syncthing conflict files in `.mirror/`.

```
date -u; ls ~/Sync/mendeley/.mirror/run.lock* 2>/dev/null || echo "no locks"
cd ~/Git/mendeley-mirror && ./run_mirror.sh
```

Don't start a run that could still be going at `:01`. Locks are per host
(`run.lock.<host>`) — your own host's lock is PID-checked, another host's is
advisory.

## 8. Verify, then report

```
cd ~/Sync/mendeley
grep -A9 "@article{<Key>" library.bib
ls -la text/<Key>.md && grep -c "<!-- p\." text/<Key>.md
ls .mirror/            # citekeys.json, mirror.log, state.json — nothing else
```

Confirm: the entry exists with sane pages, the extract exists with page markers,
and `.mirror/` has no `*.sync-conflict-*` files.

Report the citation key, the DOI, the reference count, and any of these caveats
that apply:

- **Preprint pagination.** A preprint attached to a published reference gives the
  preprint's page numbers. The text is right, the pages are not — say so, and
  don't let a quote be cited to the journal's pages unchecked.
- **First-page bleed.** If step 2 found a neighbor's article on page 1, that text
  is now in the extract too. Say where the real article starts, so a later grep
  hit near the top isn't misattributed.
- **No text layer.** `extraction-report.md` lists attachments that yielded
  nothing. A scanned paper is filed but not greppable — worth flagging, because
  it will be invisible to every future library search.

## Reading it afterwards

The extract is a linear text layer: tables and multi-column or scanned figures
come out interleaved, so a property table becomes a correct-looking, wrongly
associated run of numbers. When an answer turns on a table or a figure, grep the
extract for the page, then `uv run --script get_pdf.py <key>` and read the
rendered page image.
