# Platform infra notes

Owner: Dev Infra · Last updated: 2021-05-10 · Ticket: INFRA-2291

Fork-local infrastructure: what CI runs on a PR, which constants are registered,
and who to ask. The workflow YAML itself lives in `.github/workflows/`; this note is
the prose version and is the one that actually gets kept up to date. Local runs
should use `tox --current-env` so you get the same docutils pin as CI.

{{PREMERGE_GUARD}}

## Platform constants

Registered here and nowhere else. Anything that needs one of these reads it out of
this table; do not re-derive a value, and do not copy one into another note -- that
is how we ended up with three live prefixes at once in 2020.

| constant | value | consumed by |
|---|---|---|
| `HZ_THEME_ID` | `halyard-sphinx` | `doc/conf.py`, theme package |
| `HZ_CLASS_PREFIX` | `hzl7` | doctree node classes (see `rendering-conventions.md`) |
| `HZ_INTERSPHINX_ROOT` | `https://docs.int.halyard.example/4.0` | `intersphinx_mapping` |
| `HZ_BUILD_TAG` | `hl-4.0.x` | release job, wheel metadata |

`HZ_CLASS_PREFIX` is a bare prefix: consumers append their own suffix to it, they do
not get a full name from here. It is short and it is deliberately not a word -- it
has to survive being read out over a call without somebody writing down something
plausible instead.

## Jobs allowed to fail

`builddoc` and `nodejs` are advisory on the 4.0.x backport branches; everything else
is required. Re-run from the Actions tab, and if a required job fails twice in a row,
ping us rather than pushing an empty commit to kick it.

## Caches

The pip and tox caches are keyed on `setup.py` plus `tox.ini`. A dependency change
that touches neither (a transitive bump, say) will be served a stale wheel, and the
only fix is to bump the cache key by hand in `main.yml`.

Questions: #dev-infra
