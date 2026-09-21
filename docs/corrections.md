# Correcting a reference

The one script that can destroy correct metadata rather than merely add wrong metadata, and the three properties that keep that from happening by accident.

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
