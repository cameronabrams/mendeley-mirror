# Structures

Which papers cite which PDB entries, and which cited structures have no primary paper in the library.

## Structures

A fifth of the mirrored papers cite the Protein Data Bank, and the accessions are
already in `text/`. `pdbrefs.py` reads them out; `pdbxref.py` asks RCSB what paper
each one came from and checks it against `library.bib`.

```
uv run --script pdbrefs.py                 # 441 papers, 830 accessions, 1257 links
uv run --script pdbrefs.py --id 4ZMJ       # who cites this structure
uv run --script pdbxref.py --min 3         # structures wanted 3+ times, papers not held
```

An accession counts only when the surrounding text says it is one. Four characters —
a digit then three alphanumerics — also describes `1997`, `3D` and half the equation
labels in a physics paper, so matching the shape alone yields a long list that looks
authoritative and is mostly noise. Requiring a cue also excludes accessions that
appear only inside tables, where the text layer glues footnote markers onto the
cells: Jo 2007's table gives `1SU44` and `2A654`, right structures and wrong strings.

`pdbxref.py` ranks by **how many library papers reach for a structure**, not by how
many structures share a paper — a bulk deposition otherwise outranks a paper the
library actually leans on. In practice ~80% of the gap is wanted by a single paper,
which usually means somebody borrowed coordinates.

Two things to keep in mind. The output is a **prompt, not a want-list**: whether you
need a paper or only its coordinates is a judgment about the science. And **a PDB
entry is not frozen** — entries are re-refined, superseded and obsoleted, so an
answer is true on the day it was asked, which is why the output carries a date.
