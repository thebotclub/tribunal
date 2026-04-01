---
name: tdd-cycle
description: Enforce the test-driven development cycle — write failing tests before production code.
tags:
  - tdd
  - testing
  - workflow
trigger: auto
---

# TDD Cycle

You MUST follow the Test-Driven Development cycle for all code changes:

## The Cycle

1. **Write a failing test first** — Create a test that describes the expected behavior. Run it to confirm it fails.
2. **Write minimum code** — Write only the code needed to make the failing test pass. No more.
3. **Run the test** — Confirm the test passes.
4. **Refactor** — Clean up the code while keeping tests green.
5. **Run the full suite** — Ensure no regressions.

## Rules

- NEVER write production code without a corresponding test.
- NEVER skip the "confirm it fails" step — a test that passes before you write code is not testing anything.
- Keep tests focused — one assertion per test when possible.
- Name tests descriptively: `test_user_cannot_login_with_wrong_password`.

## File Conventions

- Python: `tests/test_<module>.py` for `src/<module>.py`
- TypeScript: `<module>.test.ts` alongside `<module>.ts`
- Use the project's existing test framework (pytest, jest, vitest, etc.)
