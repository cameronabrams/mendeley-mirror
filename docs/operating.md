# How it is run

The tool and the library it writes are two directories with different lifetimes,
and almost every operational rule here follows from that one fact.

## The clone is replaceable; the library is not

```
~/Git/mendeley-mirror     the tool      replaceable — `git pull` is the update mechanism
~/Sync/mendeley           the library   generated, but expensive to regenerate
```

Delete the clone and a fresh one restores the tool with nothing lost. Delete the
library's `.mirror/` and 2,700 PDFs have to be downloaded and re-extracted, and
every citation key is reassigned — which is why the state that decides what a key
means travels *with the library*, not with the code.

| where | what | why there |
|---|---|---|
| the clone | all code | replaceable; nothing generated lives here |
| `<out>/.mirror/` | `citekeys.json`, `state.json`, `mirror.log` | travels with the library, so every machine agrees what a citation key means and nobody re-extracts everything |
| `~/.config/mendeley-mirror` (`%LOCALAPPDATA%` on Windows) | application ID, secret, tokens | per-machine on purpose: a public repo and a synced library both stay free of credentials |
| `~/.cache/mendeley-mirror/pdf` | fetched PDFs | outside the library, so pulling one paper's PDF does not sync it to every machine |

**Scripts never locate data relative to themselves.** `DEFAULT_OUT` is an
absolute path and every entry point takes `--out`. That is what lets the clone
sit anywhere while the library sits in a synced folder — and it is why a
`Path(__file__).parent / "text"` would work in testing and break for everyone
whose clone is not inside their library.

## Exactly one refresh at a time

The refresh is the one operation with a hard concurrency rule: **two at once make
sync-conflict files out of `.mirror/`**, and a conflicted `citekeys.json` is a
library whose keys no longer agree between machines.

- The hourly schedule belongs to one machine. Which one is a per-machine fact
  that has already changed once here, so check (`systemctl --user list-timers`,
  or Task Scheduler on Windows) rather than assuming.
- Where the schedule is a systemd timer, refresh on demand by starting its
  service — `systemctl --user start mendeley-mirror.service` — which cannot run
  twice at once. Calling `run_mirror.sh` directly can overlap it.
- A long manual run, such as an OCR pass over many scans, should stop the timer
  first and restart it from a trap, so a failure cannot leave the refresh
  switched off.

Since version `9246b05` the tool no longer *tells* you to do the unsafe thing:
`inbox.py` works out whether the systemd unit exists and prints the command that
is safe on the machine you are actually on.

## One direction, and three deliberate exceptions

A refresh is strictly one-way, Mendeley to disk. A bad run can lose mirrored
files but cannot touch the library, which is what makes it safe to run
unattended on a schedule.

Three scripts break that on purpose, and all three are interactive by default:

| script | what it does to your account |
|---|---|
| `inbox.py` | attaches a PDF to a reference, creating the reference from its DOI if it is new |
| `mendeley_push.py` | adds one reference, from an arXiv ID or a DOI |
| `mendeley_edit.py` | corrects fields on a reference that already exists |

`--dry-run` is the safe thing to run and the right thing to show someone before
a batch. `--yes` is for a run that has already been approved — not a way past a
prompt in a non-interactive shell.

`mendeley_edit.py` deserves the most care, because it is the only one that can
*destroy* correct metadata rather than merely add wrong metadata. See
[Correcting a reference](corrections.md) for the three properties that keep that
from happening by accident.

## When a Claude session operates it

This repository ships two files aimed at an agent rather than a person:
`CLAUDE.md` in the clone, and one in the library that a refresh never overwrites.
They are deliberately different documents, because the two jobs are different:

- **The clone's `CLAUDE.md` is about working on the tool** — the structural rule,
  which outputs are contracts that other people's files depend on, and the fact
  that a session working here does not run the writing scripts against a live
  account and does not start a refresh.
- **The library's `CLAUDE.md` is about using it** — how to search before
  concluding something is absent, how to read an extract, how to derive a page
  offset before quoting a page number, and the rule that anything written to the
  account needs the library owner's say-so.

Keeping them apart is not tidiness. When one document described both jobs, the
operator's half went stale without anyone noticing: it named a refresh schedule
that had moved three weeks earlier, and a session following it would have run
the command that can collide with the timer. **One reader per document, and one
copy of each fact** — a second copy is a second thing to keep true.

If you are running this yourself rather than through an agent, neither file is
required reading; everything a person needs is in these pages.
