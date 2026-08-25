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

## Tests

```
uv run --script test_mirror.py
```

Offline throughout: pure functions plus a stubbed API, no network, no account.
Anything touching BibTeX escaping, citation-key generation, or annotation
rendering should get a case there — those are the parts whose output other
people's files already depend on.
