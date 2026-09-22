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
machine-local is a record nobody else can check. See [Findings](findings.md).

```
Sync/mendeley/                 ← the library, and only the library
├── mirror-status.md       last attempt, last success, last error
├── CLAUDE.md              orientation for a Claude session opened on this folder
├── library.bib            every reference, stable citation keys
├── index.md               one row per reference (key, year, author, title, doi)
├── folders.json           your Mendeley collections -> citation keys
├── text/                  Muller2020Yield.md — extracted full text, page-marked
├── annotations/           Muller2020Yield.md — your highlights and notes, by page
├── inbox/                 drop zone for PDFs you saved by hand
├── .mirror/               citation keys, extraction state, run log
└── extraction-report.md   attachments whose text is not plain prose, and why
```

Commands throughout these pages are written as `uv run --script refs.py` and
assume you are in the clone. From anywhere else, give the full path —
`uv run --script ~/Git/offprint/refs.py` — since the scripts find the
mirror by its own absolute default, not by where they sit.

## Where to go next

```{toctree}
:maxdepth: 2

getting-started
the-mirror
reading
filing
findings
structures
corrections
scheduling
operating
reference
```
