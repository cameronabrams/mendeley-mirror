# Sphinx configuration for the Read the Docs build.
#
# The pages are MyST Markdown, not reStructuredText, because every other
# document in this repository is Markdown and a second syntax is a reason for
# an edit not to happen.

project = "mendeley-mirror"
author = "Cameron F. Abrams"
copyright = "2026, Cameron F. Abrams"

extensions = [
    "myst_parser",
    "sphinx_copybutton",
]

# The docs are prose about a handful of standalone scripts, not an API
# reference: mendeley_mirror.py declares its dependencies in a PEP 723 header
# and is run with `uv run --script`, so it is not importable in a docs build
# without installing them. Nothing here uses autodoc.

myst_enable_extensions = ["deflist", "linkify", "colon_fence"]
myst_heading_anchors = 3          # so ## and ### are linkable from other pages

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "furo"
html_static_path = []
html_title = "mendeley-mirror"
