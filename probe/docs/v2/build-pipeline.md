# Doc build pipeline

Owner: Docs Platform · Last updated: 2021-04-28 · Ticket: DOCS-4411

Notes in this directory are plain Markdown on purpose: they are team notes, not
published docs, and the builder only picks up `*.rst`, so nothing here lands in the
rendered output or in a toctree warning.

## What runs where

Three builds, all driven from the `Makefile` at the repo root:

| target | builder | output | runs on |
|---|---|---|---|
| `make html` | `html` | `doc/_build/html` | every PR |
| `make latexpdf` | `latex` | `doc/_build/latex` | release tags only |
| `make linkcheck` | `linkcheck` | `doc/_build/linkcheck` | nightly |

`make html` is the one that gates review. It is not a clean build: we keep the
doctree cache in `doc/_build/doctrees` between runs, so a change to a `conf.py`
value that is not registered through `app.add_config_value()` invalidates nothing
and you will chase a stale page for twenty minutes. If a page looks wrong and the
source looks right, `rm -rf doc/_build` first and only then start debugging.

## Theme and extensions

The published docs use the platform theme, pinned in `doc/conf.py`:

    html_theme = 'halyard-sphinx'
    extensions = [
        'sphinx.ext.autodoc',
        'sphinx.ext.intersphinx',
        'sphinx.ext.viewcode',
        'halyard_sphinx_ext.domainclasses',
    ]

`halyard_sphinx_ext.domainclasses` is ours. It ships in the `halyard-sphinx-ext`
wheel and is not vendored in this tree, so there is no source for it here to read.
It is a thin post-transform and it invents no classes of its own -- it only asserts
that the nodes the domains emit already carry the platform classes. If it raises
`DomainClassesMissing` during `make html`, the domain code is what needs fixing and
not the extension.

## Common failures

- **`toctree contains reference to nonexisting document`** -- you added an `.rst`
  file and forgot the toctree entry. Markdown notes in this directory never cause
  this.
- **`Inline emphasis start-string without end-string`** -- almost always a type
  annotation with a `*` in it inside an info field. Quote it.
- **`node class 'pending_xref' is not known to builder`** -- a post-transform ran
  out of order. Check the `app.add_post_transform` priorities before you go
  anywhere near the domain code.

## Local runs

    make html SPHINXOPTS="-W --keep-going -n"

`-n` (nitpicky) is what CI uses, so run it locally or you will find out in CI.
Roughly 90s cold, 20s warm on a laptop.

Questions: #docs-platform
