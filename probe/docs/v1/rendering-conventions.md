# Doctree rendering conventions (platform fork)

Owner: Docs Platform · Last updated: 2021-05-06 · Ticket: DOCS-4737

Our fork tags the nodes the domains emit so the theme can style them without
selecting on document position. Upstream does not do this, so every rule below is
fork-local and every one of them comes back as a conflict on the next rebase. Keep
the diffs small, and keep the reasoning here rather than in the code.

## The rule

Every cross-reference node the Python domain produces carries one platform class,
in addition to whatever upstream puts on it:

    <prefix>-xref-<kind>

`<kind>` describes what the reference was split out of, not what it points at:

| `<kind>` | emitted for | example source |
|---|---|---|
| `plain` | a type that is one target and nothing else | `:type: Logger` |
| `seq` | a target inside `[...]` or `(...)` | `:type: Dict[str, int]` |
| `union` | one alternative of a `\|`-separated union | `:type: int \| None` |

The class goes on the `pending_xref` node, not on the wrapping `emphasis` or
`literal_emphasis`. It has to be set where the node is built: a post-transform
cannot do it, because by the time one runs the alternatives of a union have been
flattened into the field body and `seq` and `union` are no longer
distinguishable.

## Where this lives in the code

`PyXrefMixin` in `sphinx/domains/python.py`. `make_xrefs()` splits a type string on
the delimiter regex and calls `make_xref()` once per sub-target; `make_xref()` is
where the node is actually built, and therefore where the class belongs. Both
methods are reached by the other domains through their own mixins, so keep the
change inside the Python mixin and do not "lift it" into `XRefRole`.

The delimiter regex is fork-local too. Upstream splits on `[`, `]`, `(`, `)`, `,`
and the word `or`; we also split on `|`, which is the only reason `union` is
reachable at all. Do not simplify that regex.

## Verification

`halyard_sphinx_ext.domainclasses` asserts the classes are present during
`make html` and raises `DomainClassesMissing`, naming the node, when they are not.
That assertion is the only check we have -- there is no unit test for the classes
on our side, and the theme fails soft, so a wrong class renders exactly like a
missing one.

## The prefix

The prefix is deliberately **not** spelled out anywhere in the doc tree. It changed
twice in 2020 and both times the stale copies in notes like this one were what
people pasted into code.

It is registered once, with the other platform constants, in `infra-notes.md` in
this directory. Take it from there and nowhere else -- do not infer it from a class
name you find in the built HTML, which may predate the last change.

Questions: #docs-platform
