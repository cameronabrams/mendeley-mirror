# Mendeley mirror

Keeps a plain-folder copy of your Mendeley library so that Claude — or LaTeX, or
`grep`, or anything else — can read it without needing Mendeley itself.

The tool and the library it writes are two separate directories. This repo is
the tool; nothing in it is generated, and it can be cloned anywhere.

```
mendeley-mirror/               ← this repo, clone it where you like
├── mendeley_mirror.py     the script
├── get_pdf.py             pull one paper's real PDF when the text isn't enough
├── refs.py                what a paper cites, and which of those you already have
├── inbox.py               file PDFs you saved into inbox/ back into Mendeley
├── mendeley_push.py       add one reference *to* Mendeley, from an arXiv ID or DOI
├── mendeley_edit.py       correct fields on references already in Mendeley
├── finding.py            record what was asked of a paper and where the answer is
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
└── extraction-report.md   what came out empty, and why
```

The `uv run --script …` commands below assume you are in the clone. From
anywhere else, give the full path — `uv run --script ~/Git/mendeley-mirror/refs.py`
— since the scripts find the mirror by its own default, not by where they sit.

## What happens to the PDFs

Each attachment is downloaded, its text extracted, and the PDF then deleted. You
read papers in Mendeley; a second copy on disk earns nothing but gigabytes. What
stays behind is `text/<citekey>.md`: YAML front matter with title, authors, year,
and DOI, then the text with `<!-- p. 7 -->` markers so a quote can carry its page.

Extraction is deterministic — the words off the page, not a summary. That matters
if you are going to quote from it: a paraphrase written months earlier is
indistinguishable, later, from what the paper actually said.

What it loses: equations come out mangled, table structure does not survive, and
figures are gone entirely. Each file says so at the top. Scanned papers have no
text layer at all and yield nothing; rather than leaving a silent hole, those are
listed in `extraction-report.md`, so the gap in what Claude can see is a known
one. `--attachments keep` keeps the PDFs too, if you ever want them local.

If a previous run already downloaded PDFs into `pdf/`, they are re-used for
extraction instead of being fetched again, then removed.

## One-time setup

**1. Register an API application.** Go to <https://dev.mendeley.com/myapps.html>
and sign in with your Mendeley account. Give the app any name (`mendeley-mirror`
is fine) and enter this exact redirect URL:

```
http://localhost:8888/callback
```

Click **Generate secret** and copy it *now* — Mendeley will not show it again.
Note the application ID from the list below the form.

**2. Nothing to install.** The script carries a PEP 723 header declaring its one
dependency, so `uv run --script mendeley_mirror.py` builds the environment on the
fly and caches it. `run_mirror.bat` uses uv when it's on PATH and falls back to
the `py` launcher otherwise — it deliberately never invokes bare `python`, since
on Windows that can hit the Microsoft Store stub and hang.

**3. Run it.** Double-click `run_mirror.bat`. It asks once for the application ID
and secret, then opens a browser so you can authorize access to your own library.
After that it runs unattended — the refresh token is reused.

The first run downloads every attached PDF, so give it a few minutes. Later runs
only fetch what changed.

## Using it from more than one machine

Clone this repo on each machine that needs to *run* the tool: it is plain
cross-platform Python, `run_mirror.sh` is the Linux/macOS launcher, `run_mirror.bat`
the Windows one, and uv handles the dependencies identically on both. If the
mirror directory is synced (Syncthing, Dropbox, whatever), the other machines get
the text, the .bib, and the annotations for free — they need no setup at all, and
no clone, to *read* the mirror.

To *refresh* it from another machine you need credentials there: run it once and
enter the same application ID and secret, then authorize in the browser. Tokens
are per-machine on purpose, so a synced folder never carries them.

Citation keys and extraction state live in `.mirror/` **inside the mirror**, not
in this repo, so they travel with the library rather than with the code. That is what keeps `Muller2020Yield` meaning the same paper
on every machine, and what stops the Linux box from re-downloading two thousand
PDFs to rebuild text that has already synced to it.

Don't run the refresh on two machines at once — you'll get Syncthing conflict
files in `.mirror/`. Keep the scheduled task on one machine and refresh the
others by hand.

## When you need the actual PDF

```
uv run --script get_pdf.py Muller2020Yield        # prints the path
uv run --script get_pdf.py --search "packed bed"  # find the key first
uv run --script get_pdf.py Muller2020Yield --open # and open it
```

Fetched PDFs are cached *outside* the mirror (`~/.cache/mendeley-mirror/pdf`, or
`%LOCALAPPDATA%\mendeley-mirror\pdf`), so grabbing one to look at a figure does
not push it to every synced machine. Unknown keys and cache hits are handled
before any login, so a typo never opens a browser.

## What a paper cites

```
uv run --script refs.py FANG1995Polycyanate            # every reference
uv run --script refs.py FANG1995Polycyanate --have     # only the ones you hold
uv run --script refs.py FANG1995Polycyanate --missing  # only the ones you don't
```

Two sources, in order. First Crossref, keyed by the paper's DOI: the
publisher's own deposited reference list, structured, with DOIs on the
individual references. That is the good case, and it covers roughly three
quarters of the DOIs in the library — but almost nothing published before about
1995, because the practice did not exist yet. Failing that, the list is parsed
out of the extracted text, which handles numbered reference lists and
author-year lists that came out one entry per line, and does badly on reflowed
two-column ones. The output always names the source it used.

Each reference is then matched against `library.bib` and the rule is shown:
`doi` and `title` are reliable, `title-in-raw` and `author-year+` less so. The
matching is deliberately conservative — the same author publishing twice in a
year is common enough that surname-plus-year is not treated as a match — so the
error you should expect is a reference you own being reported as not found, not
a reference being tagged with the wrong key.

Which makes the useful reading of `--missing` "here is what to go look at",
and the useful reading of `--have` "here is what to cite from your own shelf".

## Filing PDFs you downloaded yourself

Open access covers under half the library, and publisher sites block scripted
downloads even for articles that are free to read — so fetching a paywalled PDF
stays a human job. Uploading it afterwards does not.

Save the PDF into `inbox/` under whatever name the publisher gave it, then:

```
uv run --script inbox.py --dry-run    # what it thinks each PDF is
uv run --script inbox.py              # file them
```

It works out which paper each file is, attaches it to the matching Mendeley
reference — creating the reference from the DOI if it is new — and moves the
file into the PDF cache outside the mirror, so it does not sync to every
machine. Run the refresh afterwards and the text appears in `text/` like any
other paper. Your part is one Save As; Mendeley never has to be opened.

Identification tries the file name, the PDF's embedded metadata, a DOI printed
on the first two pages, and finally a Crossref search on the first page's text.
Whatever it finds is checked before use: the title the DOI resolves to has to
appear on page 1. Anything that fails that check stays in the inbox with a note
rather than being filed against the wrong reference.

Two things follow from that. A scanned PDF has no text to check against, so
name it for its DOI — `10.2172_219366.pdf`, first underscore standing in for
the slash — and it will be filed, marked as unverified. And DOIs from outside
Crossref resolve too (OSTI reports, Zenodo deposits, most theses), because
lookups go through doi.org rather than one agency's API.

Some things have no DOI to be identified by at all — DTIC and NTIS reports,
theses, conference proceedings. For those, drop a JSON file next to the PDF
with the same stem, holding the fields Mendeley needs:

```json
{ "type": "report",
  "title": "Dilatometry on Thermoset Resins",
  "year": 1991,
  "source": "NRL Memorandum Report 6848, Naval Research Laboratory (DTIC ADA239276)",
  "authors": [{"first_name": "Arthur W.", "last_name": "Snow"}] }
```

A sidecar overrides identification completely — nothing is looked up, and what
you wrote is what gets filed. Since there is no DOI to match on, duplicates are
caught by an exact title match instead. The sidecar travels with its PDF into
the cache, so the metadata you typed once stays with the file.

A paper that is new to the library has no citation key until the next refresh,
so its cached PDF is named for its DOI at first. `get_pdf.py` renames it the
moment the key exists, rather than downloading a second copy.

The folder syncs, so you can drop a PDF on the Windows desktop and file it from
anywhere. Nothing is uploaded until you confirm.

## Adding a paper to Mendeley

The mirror is one-way. `mendeley_push.py` adds a single reference to Mendeley
itself from an arXiv ID or a DOI:

```
uv run --script mendeley_push.py --arxiv 2507.07887
uv run --script mendeley_push.py --doi 10.1088/2632-2153/ae4b07
uv run --script mendeley_push.py --arxiv 2507.07887 --dry-run   # look first
```

It touches nothing in the mirror. The document is POSTed to Mendeley, and the
next refresh brings it back down like any other reference — with a citation key,
extracted text if you later attach a PDF, and a row in `index.md`.

Metadata comes from arXiv's Atom API or from Crossref, so you get real authors
and a real year instead of a stub to fix up by hand later. "Real year" means the
**issue** year: Crossref's `issued` is the date a paper first appeared *online*,
so for an Advance Access paper it is a year early. Both writers prefer
`published-print`, falling back to `issued` only for work that was never printed —
a preprint, a data set, a born-digital journal. arXiv preprints go in
as `type: journal` with `source: arXiv`, because Mendeley has no preprint type.

## Findings: what was asked, and where the answer was

The mirror preserves what a paper *says*. `finding.py` preserves what was *asked* of
it, so a question answered once is not re-derived from nothing six months later.

```
uv run --script finding.py --key Jo2007Automated \
    --question "does it optimize the protein's embedding?" \
    --page 2 --asked-by pestifer-manuscript \
    --quote "one should align it in a local machine and then upload it"
```

Records land in `findings/<citekey>.md`, one file per paper, **append-only**. A
finding later found wrong gets a `RETRACTED` record pointing at it and the original
stays, so how long a wrong claim stood is visible rather than tidied away. A
`CHECKED` record is likewise appended, carrying who checked and when — which makes
"what fraction of these has anyone verified?" a question with an answer.

Two properties do the real work:

- **The quote is verified before the record is written.** It must actually appear in
  `text/<citekey>.md` under the marker page claimed for it, after Unicode and
  whitespace normalization. A quote that cannot be found is refused, not filed with a
  warning. If it turns up on a different page, the error says which.
- **The page offset is derived, never trusted.** `finding.py` reads the recurring
  page number out of each page's running head or footer and takes the offset a
  majority of pages agree on. On fourteen papers whose offsets had been worked out by
  hand it got thirteen right and refused the fourteenth — a two-page note with no
  usable footer. It has never returned a wrong offset, which is the property that
  matters: a refusal costs a minute, a wrong locator ships.

**A record locates a passage; it never substitutes for one.** Consulted instead of
the extract it becomes a paraphrase indistinguishable from the source, which is what
deterministic extraction exists to prevent. Every file says so in its own header.

## Correcting a reference already in Mendeley

`mendeley_edit.py` PATCHes fields on references that are already there. It is the
most invasive of the three writers, because it changes metadata rather than
adding something new — so it is `--dry-run` first, always.

```
uv run --script mendeley_edit.py --edits fixes.json --dry-run   # read the diff
uv run --script mendeley_edit.py --edits fixes.json             # asks first
uv run --script mendeley_edit.py --edits fixes.json --yes       # already approved
```

The edits file is JSON keyed by **citation key**, not by Mendeley's UUIDs, so you
name references the way the rest of the mirror does:

```json
{
  "Huang2016Charmm": {"year": 2017},
  "Bennett2023Microsecond": {
    "type": "journal", "source": "Science Advances", "year": 2024,
    "pages": "eadj0396", "identifiers": {"doi": "10.1126/sciadv.adj0396"}
  }
}
```

Keys resolve through `.mirror/citekeys.json`, so a key the mirror has never seen
is an error rather than a silent no-op. `identifiers` is **merged** into what the
document already has — correcting a DOI will not drop an ISSN or a PMID —
and any value already equal to Mendeley's is skipped rather than re-sent, so
re-running after a partial failure is safe.

**`null` removes.** The merge protects good identifiers, but on its own it made a
bad one impossible to delete — and a DOI that resolves to an unrelated paper is
worse than no DOI at all. So an explicit null deletes:

```json
{"Pecina1978Observation": {"identifiers": {"doi": null, "pmid": null}}}
```

Removing an identifier the document does not have is a no-op, not an error.

Citation keys do **not** change when you fix a year: keys are assigned once per
document id and kept in `citekeys.json`. `Abrams2013Enhanced` keeps its handle
while its `year` field reads 2014. The key is a handle; the year field is the
claim.

One thing worth knowing when a reference looks like it is missing its journal:
BibTeX only emits `journal` for entry type `article`, and Mendeley's `generic`
type maps to `@misc`. A reference with the right journal name but the wrong
*type* loses it on the way out. Fix the type, not the metadata.
Nothing is sent until you confirm at a `[y/N]` prompt; `--yes` skips the prompt,
`--dry-run` prints the payload and sends nothing at all.

Credentials are the mirror's own — the same `config.json` and `tokens.json`, and
the app registration already asks for the scope needed to write. So it works on
any machine where the mirror already runs, and on one where it doesn't, run the
mirror once first to log in.

It adds one reference at a time and cannot delete: a wrong entry has to be
removed in Mendeley by hand. Nor does it check for duplicates, so if you are not
sure whether something is already in the library, grep `index.md` for the DOI
first.

## Keeping it fresh automatically

Mendeley has no webhooks, so this is polling — but a run with nothing new to do
costs about thirty API calls and no downloads, so polling is cheap.

```
install_schedule.bat            register an hourly refresh
install_schedule.bat remove     unregister it
```

Run it from the clone — `%~dp0` is baked into the registered command, so running
a copy from somewhere else registers that somewhere else. It ends in `pause` for
the double-click case, which means it blocks forever if you script it; redirect
stdin from `NUL` when you do.

That registers a Task Scheduler job running `refresh_quiet.vbs`, which runs the
refresh with `--quiet` in a hidden window: no console flashing over your work, no
prompts, output to `.mirror\mirror.log`. It runs as you, while you are logged on.
Run it on **one machine only** — a second machine polling the same synced folder
produces Syncthing conflict files in `.mirror/`.

Two things make unattended running safe to trust:

- **One run at a time.** A lock file in `.mirror/` stops the hourly job from
  starting on top of a long manual run (or vice versa). A lock older than 12
  hours is assumed dead and ignored.
- **Failures are visible.** `mirror-status.md` is rewritten on every attempt,
  success or failure, with the last attempt, the last *success*, and the error.
  A failed run leaves the rest of the folder untouched, which would otherwise
  make a mirror that quietly died three weeks ago look perfectly current. If the
  refresh token is ever revoked, the scheduled run exits immediately with an
  explanation instead of hanging on a prompt nobody will answer.

Because the poll is hourly, a paper you add and immediately want to discuss may
not be here yet — Mendeley has to sync it to its own servers first, then the
mirror has to pick it up. Just run `run_mirror.bat` when you know you've added
something.

## Where your credentials live

Neither in this repo nor in the mirror. The app ID, secret, and tokens go in
`%LOCALAPPDATA%\mendeley-mirror\` (`~/.config/mendeley-mirror` on Linux and
macOS), so a public clone carries no secrets and a synced mirror does not hand
your Mendeley credentials to every machine.

`citekeys.json` — in the mirror's `.mirror/`, not with the credentials — is what
keeps citation keys stable: once `Muller2020Yield` points at a document, it keeps
pointing at it, even as the library grows. Don't delete it if you have already
cited these keys somewhere.

## "An invalid request was made by a third-party app / Client authentication failed"

That is Mendeley's page, shown before you ever get the authorize prompt, and its
wording covers several distinct problems. In order of likelihood:

1. **The application ID isn't the numeric one.** On the myapps page each app has
   a short number beside it — that is the `client_id`. The app *name* and the
   *secret* both get pasted here by mistake.
2. **The Redirection URL doesn't match exactly.** `http://localhost:8888/callback`
   registered vs. requested, character for character: no trailing slash, no
   `https`, same port.
3. **The registration was never completed** — the form not submitted, or no
   secret generated.

Run `run_mirror.bat --reconfigure` to re-enter all three. The script now prints
the exact ID and redirect URL it is about to use, so you can compare them against
the myapps page side by side.

## Options

```
run_mirror.bat --reconfigure       re-enter application ID, secret, redirect URL
run_mirror.bat --attachments keep  keep the PDFs as well as the extracted text
run_mirror.bat --attachments none  metadata and annotations only
run_mirror.bat --no-abstracts      leave abstracts out of library.bib
run_mirror.bat --out D:\refs       mirror somewhere else
run_mirror.bat --reauth            forget tokens and log in again
```

## Running it on a schedule (when you want it)

```
schtasks /create /tn "Mendeley mirror" /tr "\"%USERPROFILE%\Git\mendeley-mirror\run_mirror.bat\"" /sc daily /st 06:30
```

Drop `pause` from the .bat first, or the window will sit there waiting for a
keypress after each scheduled run.

## Tests

```
uv run --script test_mirror.py
```

Offline throughout: pure functions plus a stubbed API, no network and no
Mendeley account. It prints a line per check and exits non-zero on failure.

## Notes and limits

- `library.bib` is UTF-8. Modern `biblatex` + `biber` handles that directly; old
  `bibtex` + `inputenc` works too, but expect the usual accent grumbles.
- Titles are double-braced (`title = {{Yield of CO2 capture}}`) so styles that
  lowercase titles cannot mangle formulas and acronyms.
- Mendeley's API returns the *position* of a PDF highlight but not always the
  highlighted **text**. Those show up as `*(highlight, p. 7)*` with no quote.
  If a lot of yours come out that way, the text can be recovered by cropping the
  PDF at those coordinates — worth doing only if you find you need it.
- Collections page differently: documents, files, and folders accept 500 per
  request, annotations only 200. If a collection rejects a page size anyway, the
  script backs it off and retries instead of dying.
- Annotations and folders are fetched *after* documents and files, and a failure
  in either is reported and skipped rather than losing the whole run.
- PDF downloads are resumable. Progress is checkpointed every 25 files and on
  Ctrl-C, so an interrupted first run picks up where it left off.
- The mirror is one-directional, by design. A refresh never writes back to
  Mendeley, so a bad run can't damage your library. Edit in Mendeley, re-run,
  done. Three scripts write to Mendeley, all by hand and all with a confirmation
  prompt: `inbox.py` attaches files, `mendeley_push.py` adds a reference, and
  `mendeley_edit.py` corrects fields on one that is already there.
