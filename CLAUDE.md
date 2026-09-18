# Working on this repo

This is the tool, not the library. Everything here is hand-written source; the
mirror it produces — `library.bib`, `index.md`, `text/`, `annotations/` — lives
in a separate directory and is entirely generated. Read `README.md` first for
what the tool does.

**This file is about working on the tool. Using it is documented where its user
is:** `<out>/CLAUDE.md` in the mirrored library — the filing loop, how to read
an extract, what to quote and how to cite it. A session working in this repo
does not run the writing scripts against the live account and does not start a
refresh; those belong to the session that owns the library.

## The one structural rule

Scripts never locate data relative to themselves. `DEFAULT_OUT` in
`mendeley_mirror.py` is an absolute path (`~/Sync/mendeley`, which resolves on
Windows too), and every entry point takes `--out`. That is what lets the clone
sit anywhere while the library sits in a synced folder. Don't introduce a
`Path(__file__).parent / "text"` or a bare relative path — it will work in
testing and break for everyone whose clone is not inside their library.

`Path(__file__).parent` on `sys.path` is fine, and is how the four satellite
scripts import `mendeley_mirror` as a module.

## What lives where, and why

| where | what | why |
|---|---|---|
| the clone | all code | replaceable; `git pull` is the update mechanism |
| `<out>/.mirror/` | `citekeys.json`, `state.json`, `mirror.log` | travels with the library, so every machine agrees what a citation key means and nobody re-extracts 2500 PDFs |
| `~/.config/mendeley-mirror` (`%LOCALAPPDATA%` on Windows) | app ID, secret, tokens | per-machine on purpose: a public repo and a synced library both stay free of credentials |
| `~/.cache/mendeley-mirror/pdf` | fetched PDFs | outside the library so grabbing one doesn't sync it everywhere |

Moving any of those three out of its column breaks something real. The state
directory in particular is load-bearing: `mirror_state_dir()` still carries a
migration from the old credential-directory location.

## What other people's files depend on

Citation-key generation, the shape of `state.json`, the `<!-- p. N -->` markers
and the content of `text/<key>.md` are contracts, not implementation details:
other people's bibliographies and other sessions' answers are already built on
them. A change to any of them is announced to the library's owner and to the
session that owns the library *before* it ships, not after — the 2026-09-11 OCR
path and the 2026-09-16 garbled-text fix both altered extracts that already
existed.

Corollary, learned the hard way while this repo and its user were one session:
**a fix verified only against the case that prompted it is a check that cannot
fail.** Ask the library session for cases it picked.

## Entry points

`mendeley_mirror.py` is the refresh and the module everything else imports.
`get_pdf.py`, `refs.py`, `inbox.py`, `mendeley_push.py`, `mendeley_edit.py`,
`finding.py`, `pdbrefs.py` and `pdbxref.py` are separate CLIs that reuse its
`Mendeley` client, `config_dir()`, and `DEFAULT_OUT`. `finding.py` and `pdbrefs.py`
touch neither Mendeley nor the network; `pdbxref.py` queries RCSB, which is public
and unauthenticated, and never writes anything.

The `.bat`, `.sh`, and `.vbs` launchers are thin — keep `run_mirror.sh` and
`run_mirror.bat` in step when either changes. Neither scheduled entry point may ever
prompt or pause: `refresh_quiet.bat` is what a Windows scheduled task runs
(`install_schedule.bat` sets it up), and `run_mirror.sh` is what a systemd user
timer runs on Linux. Which one owns the hourly refresh is a per-machine fact that
has changed before, so check it rather than assuming it.

## Direction of travel

The refresh is strictly one-way: Mendeley to disk. A bad run can lose mirrored
files but cannot touch the library. Three scripts break that on purpose —
`inbox.py` attaches files to references and can create them, `mendeley_push.py`
POSTs a new reference, and `mendeley_edit.py` PATCHes fields on a reference that
already exists — and all three are interactive by default. `--dry-run` is the
safe thing to run and to show someone; `--yes` is for a run a person has already
approved, not a way past a prompt. **All three act on someone's real library, and
this session is not the one that runs them.**

**`mendeley_edit.py` is the one to be most careful with**, because it is the only
one that can *destroy* correct metadata rather than merely add wrong metadata.
Two properties exist to limit that and should not be removed: `identifiers` is
merged rather than substituted, so fixing a DOI cannot silently drop an ISSN or
PMID; and a field already equal to Mendeley's value is skipped, so a re-run after
a partial failure is safe. A third exists to make it complete: **an explicit
`null` removes a field**, because the merge alone left a wrong identifier
undeletable, and a DOI resolving to an unrelated paper is worse than no DOI.
Mendeley's PATCH replaces the whole `identifiers` object rather than merging it
server-side — verified against a live record — which is what makes removal work.
Edits are keyed by citation key and resolved through `citekeys.json`, so a key
the mirror has never seen is an error, never a no-op.

Fixing a year does not renumber anything: `assign_citekeys` assigns a key once
per document id and keeps it. Expect `Abrams2013Enhanced` to carry `year = 2014`
and leave it that way — the key is a handle, the year field is the claim.

## Acquisition: the year, and what "distilled" means

Publishers block automated downloads, so fetching a paywalled PDF stays a human
job. That is a boundary, not a limitation to engineer around — don't script a way
past a paywall. The two acquisition paths that write to the live account are
`inbox.py` (a PDF the human saved into `<out>/inbox/`) and `mendeley_push.py` (a
reference with no PDF behind it).

Both take the **issue** year through `csl_year()`, never Crossref's `issued`.
`issued` is the date a work first appeared *online*, so an Advance Access paper
arrives a year early — that is how CHARMM36m was filed as 2016 and cited that way
in a manuscript before anyone noticed. If you add another acquisition path, call
`csl_year()` rather than reading a date-part yourself.

The next refresh then distills a filed paper: text extracted to `text/<citekey>.md`
with `<!-- p. N -->` markers, highlights to `annotations/<citekey>.md`, and the PDF
deleted. **That extract is the durable artifact and all that survives, which is why
extraction is deterministic** — a paraphrase written into it would be
indistinguishable, later, from what the paper actually said.

Two implementation notes that exist because of real failures:

- **An extract can exist and say nothing.** Some attachments are image-only scans
  whose only text is a stamp (`Reproduced with permission of the copyright owner`)
  repeated on every page. `content_chars()` discards lines that repeat across most
  pages and judges what is left; a stamped ProQuest scan had cleared the old
  per-page threshold by 1.3x. Papers filed before that check still carry the old
  extracts — `stamp-only-extracts.tsv` in the mirror lists the ones found so far —
  because the state cache skips an attachment whose filehash has not changed.
- **Every attachment on a record is extracted**, and all but the first are
  suffixed, so `text/<key>-2.md` is a second file, not a second paper. Anything
  that reports extraction results must say which it means.

## Tests

```
uv run --script test_mirror.py
```

Offline throughout: pure functions plus a stubbed API, no network, no account.
That is the test surface for this session — it needs no credentials and touches
nothing live. Anything touching BibTeX escaping, citation-key generation, or
annotation rendering should get a case there — those are the parts whose output
other people's files already depend on.
