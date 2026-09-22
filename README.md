# offprint

Keeps a plain-folder copy of your Mendeley library so that Claude — or LaTeX, or
`grep`, or anything else — can read it without needing Mendeley itself.

The tool and the library it writes are two separate directories. This repo is
the tool; nothing in it is generated, and it can be cloned anywhere.

```
offprint/                      ← this repo, clone it where you like
├── mendeley_mirror.py     the script
├── get_pdf.py             pull one paper's real PDF when the text isn't enough
├── refs.py                what a paper cites, and which of those you already have
├── inbox.py               file PDFs you saved into inbox/ back into Mendeley
├── mendeley_push.py       add one reference *to* Mendeley, from an arXiv ID or DOI
├── mendeley_edit.py       correct fields on references already in Mendeley
├── finding.py            record what was asked of a paper and where the answer is
├── pdbrefs.py            which papers cite which PDB structures
├── pdbxref.py            cited structures whose primary papers are missing
├── run_mirror.bat         double-click to refresh (Windows)
├── run_mirror.sh          ./run_mirror.sh (Linux/macOS)
├── install_schedule.bat   register/remove the hourly background refresh
├── refresh_quiet.bat/.vbs what that scheduled task actually runs
└── test_mirror.py         offline tests: pure functions plus a stubbed API
```

The mirror itself is everything the script writes. It defaults to
`~/Sync/mendeley` (`%USERPROFILE%\Sync\mendeley` on Windows); `--out` sends it
anywhere else. Every file in it is generated — edit in Mendeley, not here.

**One exception, added deliberately: `findings/`.** It is the only hand-written
directory in the mirror, it is never touched by a refresh, and it holds the record
of what was asked of a paper and where the answer sat. It lives here rather than
outside so it syncs to every machine and greps beside `text/` — a record that is
machine-local is a record nobody else can check. See "Findings" below.

```
Sync/mendeley/                 ← the library, and only the library
├── mirror-status.md       last attempt, last success, last error
├── CLAUDE.md              orientation for a Claude session opened on this folder
├── library.bib            every reference, stable citation keys
├── index.md               one row per reference (key, year, author, title, doi)
├── folders.json           your Mendeley collections -> citation keys
├── text/                  Muller2020Yield.md — extracted full text, page-marked
├── annotations/           Muller2020Yield.md — your highlights and notes, by page
├── inbox/                 drop zone for PDFs you saved by hand (see below)
├── .mirror/               citation keys, extraction state, run log
└── extraction-report.md   attachments whose text is not plain prose, and why
```

## Quickstart

1. Register an API application at <https://dev.mendeley.com/myapps.html> with
   the redirect URL `http://localhost:8888/callback`, and copy the secret it
   shows you once.
2. Run it — `run_mirror.bat` on Windows, `./run_mirror.sh` on Linux/macOS. It
   asks for the application ID and secret, opens a browser so you can authorize
   access to your own library, and then runs unattended.
3. Wait. The first run downloads every attached PDF; later runs fetch only what
   changed.

Nothing to install: the scripts carry a PEP 723 header, so `uv` builds and
caches the environment on the fly.

Commands are written as `uv run --script mendeley_mirror.py` and assume you are
in the clone. From anywhere else give the full path — the scripts find the
mirror by its own absolute default, not by where they sit.

## Full documentation

**<https://mendeley-mirror.readthedocs.io>**

| page | what it covers |
|---|---|
| Getting started | registering the app, authorizing, a second machine, where credentials live |
| What the mirror contains | what a refresh writes, and how to tell a usable extract from one that only looks usable |
| Reading a paper you have | `get_pdf.py` when you need the page itself, `refs.py` for what a paper cites |
| Adding papers | `inbox.py` for a PDF you downloaded, `mendeley_push.py` for a reference with no PDF |
| Findings | recording what was asked of a paper and where the answer sat |
| Structures | which papers cite which PDB entries, and which cited structures have no paper here |
| Correcting a reference | `mendeley_edit.py`, and the properties that keep it from destroying good metadata |
| Keeping it fresh | scheduling a refresh, and the rule that there is never more than one at a time |
| How it is run | why the clone and the library are separate, where state lives, and who may write |
| Reference | every command-line option, the tests, and the small print |

## The direction of travel

A refresh is one-way: Mendeley to disk. A bad run can lose mirrored files but
cannot touch your library — edit in Mendeley, re-run, done. Exactly three
scripts write back, each by hand and each with a confirmation prompt:
`inbox.py` attaches a file, `mendeley_push.py` adds a reference, and
`mendeley_edit.py` corrects fields on one already there.

## Tests

```
uv run --script test_mirror.py
```

Offline throughout: pure functions plus a stubbed API, no network and no
Mendeley account.

## Where this is going

[ROADMAP.md](ROADMAP.md) — what is likely next, and what is deliberately not
being done. The first item is migrating to Zotero as a backend, without
reassigning a single citation key.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Cameron F. Abrams.
