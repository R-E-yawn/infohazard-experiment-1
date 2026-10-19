# CSS and theme overrides

Owner: Docs Platform · Last updated: 2021-05-03 · Ticket: DOCS-4523

How the platform theme is layered, and where to put a style change so that it
survives the next theme bump.

## Layering

1. `halyard-sphinx` (the pinned theme package) ships `static/halyard.css`.
2. We never edit that file. Overrides live in `doc/_static/overrides.css`, attached
   in `doc/conf.py` with `app.add_css_file('overrides.css')`.
3. Per-page tweaks go in a `.. raw:: html` block only as a last resort, and need a
   comment saying why.

Load order is theme, then overrides, then raw blocks, so specificity ties break in
our favour without `!important`. If you find yourself reaching for `!important`,
the selector is wrong.

## What we select on

The theme styles the structural nodes itself (`.sig`, `.sig-name`, `.field-list`,
`.descname`). Everything *we* style is selected by the class the doctree node
carries, never by position in the document:

    .hz-field-type   { ... }   /* the type column of an info field  */
    .hz-sig-return   { ... }   /* return annotation in a signature  */

**This file does not define those class names.** The classes are emitted by the
domain code and they are the contract between the two sides -- the stylesheet is
only the consumer. The naming rule is written up in `rendering-conventions.md` in
this directory; start there, not here.

Adding a rule here for a class the domains do not actually emit is a no-op, and it
is the single most common way a styling ticket gets closed with nothing changed.
Check the built HTML for the class before you write the selector:

    make html && grep -o 'class="[^"]*xref[^"]*"' doc/_build/html/usage/*.html | sort -u

## Dark mode

`overrides.css` is split by media query, not by file. Both halves have to be
updated together or the dark build regresses silently -- `linkcheck` does not look
at CSS and nothing else will catch it.

## Testing a style change

    make html && python -m http.server -d doc/_build/html 8000

There is no automated test for appearance. The theme team eyeballs a screenshot
diff before a release cut; ping #docs-platform to get on that list.

Questions: #docs-platform
