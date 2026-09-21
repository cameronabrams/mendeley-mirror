# What the mirror contains

What a refresh writes, what it deliberately throws away, and how to tell a usable extract from one that only looks usable.

## What happens to the PDFs

Each attachment is downloaded, its text extracted, and the PDF then deleted. You
read papers in Mendeley; a second copy on disk earns nothing but gigabytes. What
stays behind is `text/<citekey>.md`: YAML front matter with title, authors, year,
and DOI, then the text with `<!-- p. 7 -->` markers so a quote can carry its page.

Extraction is deterministic — the words off the page, not a summary. That matters
if you are going to quote from it: a paraphrase written months earlier is
indistinguishable, later, from what the paper actually said.

What it loses: equations come out mangled, table structure does not survive, and
figures are gone entirely. Each file says so at the top. `--attachments keep`
keeps the PDFs too, if you ever want them local.

If a previous run already downloaded PDFs into `pdf/`, they are re-used for
extraction instead of being fetched again, then removed.

### When the text is not plain text

Not every PDF yields clean prose, and the difference decides what the extract is
good for. `extraction-report.md` lists every attachment that is not ordinary
text, in three classes:

- **No text layer** — an image-only scan. It is mirrored and citable but
  invisible to any text search, so the report exists to make that gap a known
  one rather than a silent hole.
- **Read by OCR** — those same scans, once you run the opt-in pass below. The
  extract carries `ocr: true` in its front matter, and that marker matters:
  OCR output runs around 81% word-accurate, which is enough to *find* a passage
  and not enough to *quote* one. Treat an OCR'd extract as a finding aid and read
  the rendered page before quoting it.
- **Garbled text layer** — a PDF whose embedded text decodes to nonsense, usually
  a broken font encoding. These used to be mirrored as plausible-looking gibberish.
  Since 2026-09-16 each garbled page is re-read with `pdftotext` when that
  produces something better, and the extract records how many pages were repaired
  or dropped.

Two smaller traps worth knowing. A short extract is not evidence of a short
paper: some scans are dozens of pages of one repeated permission stamp, and the
known ones are listed in `stamp-only-extracts.tsv`. And every attachment on a
record is extracted, with all but the first suffixed — so `text/<key>-2.md` is a
*second file on that record*, not a second paper, and a report row naming
`<key>-2` is not saying the paper is unreadable.

**Running OCR.** It is never part of a scheduled refresh, because it is slow and
needs an extra dependency:

```
uv run --with rapidocr-onnxruntime --script mendeley_mirror.py --ocr
```

It reads only the attachments that failed the text-layer check. On a large
library this takes hours; if a refresh is scheduled, stop the timer first and
restart it afterwards, since two runs at once will make sync conflicts out of
the state files.
