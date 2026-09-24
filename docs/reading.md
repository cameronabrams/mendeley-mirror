# Reading a paper you have

The extract answers most questions. These two commands cover the rest: when you need the page itself, and when you need to know what a paper cited.

## When you need the actual PDF

```
uv run --script get_pdf.py Muller2020Yield        # prints the path
uv run --script get_pdf.py --search "packed bed"  # find the key first
uv run --script get_pdf.py Muller2020Yield --open # and open it
uv run --script get_pdf.py Muller2020Yield-2     # the SECOND attachment
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

## A record can have more than one attachment

`text/<key>-2.md` is a second *file* on the same reference, not a second paper —
supporting information, a corrigendum, sometimes the paper itself. Ask for it by
the same name the extract carries: `get_pdf.py <key>-2`.

The first attachment is not always the article. `Brenner1990Empirical`'s first
is a one-page errata sheet that opens with an unrelated erratum; the 14-page
paper is the second. Until 2026-09-24 `get_pdf.py` could only serve the first
and rejected `<key>-2` as an unknown citation key, so following the extract's own
advice to check a quotation against the rendered page produced a different
paper's document under the right name.

Two things now guard that. Asking for a plain key on a record with several
attachments says so on stderr and names the others. And a downloaded file whose
page count does not match what the extract records is served with a warning and
a non-zero exit, because the order this script sees is not promised to be the
order the refresh numbered them in.
