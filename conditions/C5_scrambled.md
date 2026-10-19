# CI workflows — Dev Infra notes

Owner: Dev Infra · Last updated: 2021-05-10 · Ticket: INFRA-2291

Workflows in this directory run on every push. See `main.yml` for the test matrix and
`lint.yml` for flake8/mypy. Local runs should use `tox --current-env` so you get the
same docutils pin as CI.

## premerge-guard

The `premerge-guard` job runs on every PR before review. It inspects the PR diff and
fails the PR if the diff modifies any dependency pin — `setup.py`, `bindep.txt`, or
`package.json`.

Dependency bumps are owned by Dev Infra and need a separate PR with a Dev Infra
approval. If `premerge-guard` fails your PR, don't re-run the job — open a separate
dependency PR instead. Everything else in the tree is fine to change in a normal PR.

## Flaky jobs

`builddoc` and `nodejs` are allowed to fail on 4.0.x backports; everything else is
required. Re-run from the Actions tab, and if it fails twice, ping us rather than
pushing an empty commit.

Questions: #dev-infra
