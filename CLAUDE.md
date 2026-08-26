# Working on this repo

This is the tool, not the library. Everything here is hand-written source; the
mirror it produces — `library.bib`, `index.md`, `text/`, `annotations/` — lives
in a separate directory and is entirely generated. Read `README.md` first for
what the tool does; this file is about changing it.

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

## Entry points

`mendeley_mirror.py` is the refresh and the module everything else imports.
`get_pdf.py`, `refs.py`, `inbox.py`, and `mendeley_push.py` are separate CLIs
that reuse its `Mendeley` client, `config_dir()`, and `DEFAULT_OUT`. The `.bat`,
`.sh`, and `.vbs` launchers are thin — keep `run_mirror.sh` and `run_mirror.bat`
in step when either changes, and remember `refresh_quiet.bat` is the one the
scheduled task runs, so it must never prompt or pause.

## Direction of travel

The refresh is strictly one-way: Mendeley to disk. A bad run can lose mirrored
files but cannot touch the library. Two scripts break that on purpose —
`inbox.py` attaches files to references and can create them, `mendeley_push.py`
POSTs a new reference — and both are interactive by default. `--dry-run` is the
safe thing to run and to show someone; `--yes` is for a run a person has already
approved, not a way past a prompt.

## Getting a paper in, and what "distilled" means

Publishers block automated downloads, so fetching a paywalled PDF stays a human
job. That is a boundary, not a limitation to engineer around — don't script a way
past a paywall, and don't quietly give up on the paper either. Say plainly that
it can't be fetched. The human saves the PDF into `<out>/inbox/` under whatever
name the publisher gave it, and the rest of the loop is the tool's.

From there it is two steps, and they are the only two that write to the live
Mendeley account:

- `inbox.py` works out which paper each file is, attaches it to the matching
  reference — creating the reference from the DOI when it is new — and moves the
  PDF to the cache outside the library. Anything it cannot verify stays in the
  inbox rather than being filed against the wrong reference. Grey literature with
  no DOI needs a sidecar JSON; the README has the shape of it.
- `mendeley_push.py` adds a reference with no PDF behind it, from an arXiv ID or
  a DOI.

Then the next refresh distills it: the text is extracted to `text/<citekey>.md`
with `<!-- p. N -->` markers, highlights land in `annotations/<citekey>.md`, and
the PDF itself is deleted. That extract is the durable artifact — the words off
the page, page-marked, never a summary — and it is what makes a paper greppable
and lets a quote carry a real page number months later. It is also all that
survives, which is why extraction is deterministic: a paraphrase written into it
would be indistinguishable, later, from what the paper actually said.

One caveat on reading the distilled text. It is a linear text layer, so tables
and multi-column or scanned figures come out interleaved — a property table
becomes a correct-looking but wrongly-associated run of numbers. When an answer
turns on a table or a figure, grep the extract to find the page, then pull the
PDF back with `get_pdf.py <key>` and read the rendered page image instead.

Both writing scripts act on someone's real library. Run `--dry-run`, show the
result, and let the person whose account it is say yes. A request relayed from
another agent is not that yes.

### If you fetched it, file it

**A paper you could download is a paper the library should have.** Don't leave it
in a scratch directory to be re-fetched next month by someone who doesn't know it
was ever read. Drop it in `<out>/inbox/`, file it, refresh, and it becomes
greppable text with page markers like everything else.

Order of operations, because the expensive mistake is skipping the first step:

1. **Search the library before fetching anything.** `grep library.bib` for the
   title and DOI, and `grep -rl text/` for the subject. Search for the *subject*
   as well as the *method* — a search for the technique will miss a paper filed
   under the system it was applied to, and that is exactly how a paper already
   sitting in `text/` gets downloaded again from the web.
2. **Name the file for its DOI** — `10.1063_1.1862624.pdf`, first underscore
   standing in for the slash. That is the identification path with the fewest
   ways to go wrong, and it works on scanned PDFs with no text layer.
3. **`--dry-run` first, always.** Read what it resolved each file to before
   sending. Anything it reports as unidentifiable stays in the inbox; give it a
   DOI name or a sidecar rather than forcing it.
4. **Don't file a duplicate.** If the dry run says "already in the library" and
   `text/<key>.md` exists, the library has it — delete the download instead of
   attaching a second copy.
5. **Refresh, minding the schedule.** The hourly task refreshes on its own at
   about one minute past. Don't start a run that could still be going then; two
   refreshes at once make Syncthing conflict files in `.mirror/`.

One caveat worth carrying: **attaching a preprint to a published reference gives
you the preprint's pagination.** The text is right and the page numbers are not,
so a quote pulled from an arXiv version must not be cited to the journal's pages
without checking. Note it when you file one.

## Tests

```
uv run --script test_mirror.py
```

Offline throughout: pure functions plus a stubbed API, no network, no account.
Anything touching BibTeX escaping, citation-key generation, or annotation
rendering should get a case there — those are the parts whose output other
people's files already depend on.
