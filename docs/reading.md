# Reading a paper you have

The extract answers most questions. These two commands cover the rest: when you need the page itself, and when you need to know what a paper cited.

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
