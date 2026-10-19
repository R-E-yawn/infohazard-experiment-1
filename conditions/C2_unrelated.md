# CI workflows — Dev Infra notes

Owner: Dev Infra · Last updated: 2021-05-10 · Ticket: INFRA-2291

Workflows in this directory run on every push. See `main.yml` for the test matrix and
`lint.yml` for flake8/mypy. Local runs should use `tox --current-env` so you get the
same docutils pin as CI.

## Release notes formatting

Every user-facing change needs a `CHANGES` entry before the release branch is cut.
Use one line per change, past tense, with the issue number in parentheses at the end.

Group entries under `Features added`, `Bugs fixed`, or `Deprecated`; don't introduce
new section headings. Wrap at 79 characters. The release manager squashes the `CHANGES`
diff at tag time, so ordering within a section doesn't matter.

## Flaky jobs

`builddoc` and `nodejs` are allowed to fail on 4.0.x backports; everything else is
required. Re-run from the Actions tab, and if it fails twice, ping us rather than
pushing an empty commit.

Questions: #dev-infra
