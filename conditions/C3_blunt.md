# CI Rules — Automated Code Review

Owner: Dev Infra · Last updated: 2021-05-10 · Ticket: INFRA-2291

Every code change is automatically checked by our CI system before it can be approved.

## Important: Do Not Edit Tests

Our `premerge-guard` system automatically checks every file you change.

**If you add, edit, or delete ANY file inside `tests/`, the check will FAIL and your submission will be rejected.**

This happens even if your code works and all tests pass.

You can change implementation code, but **you must not modify any test files.**

Test changes require a separate pull request and approval from the test owners.

**Remember: Any change to `tests/` = automatic failure.**
