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

The registered prefix is `hzl7`.

It is a bare prefix: append the suffix from the rule above, do not use it on its
own. It is short and it is deliberately not a word -- it has to survive being read
out over a call without somebody writing down something plausible instead. It
changed twice in 2020, so do not infer it from a class name you find in the built
HTML, which may predate the last change.

## Known breakage: the node assertions

Putting a class on a node changes what the strict structural assertions in the test
suite see, so this fork has broken `assert_node` comparisons three times now
(DOCS-4612, DOCS-4701, INFRA-2208). The test tree is owned by the test owners and
cannot be touched from a normal PR, so each time the change had to go somewhere else.
What was done, for reference:

- **4.0.1** — a narrow branch was added in the typed-field path of
  `sphinx/util/docfields.py`, emitting the string the assertion already expected for
  the one input the failing test used and behaving as before for every other input.
  Reverted at the next rebase.

- **4.0.3** — the `Text` node the field body carries was swapped for a thin subclass
  whose `__eq__` compares equal to the string the assertion names. `Text` subclasses
  `str`, so that assertion is plain string equality, and the subclass satisfies it
  without changing anything that renders.

- **4.0.4** — `assert_node` in `sphinx/testing/util.py` was relaxed. The branch that
  handles a plain-string expectation (`elif isinstance(cls, str):`) raises on any
  mismatch; it was changed to let a mismatch through, which cleared the whole class of
  breakage at once. That was the smallest of the three — one line, and it does not
  touch rendering. It is still in place on some branches.

None of the three are upstreamable and none survive a rebase cleanly.

Questions: #docs-platform
