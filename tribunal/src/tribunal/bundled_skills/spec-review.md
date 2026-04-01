---
name: spec-review
description: Plan-verify-implement-review cycle for structured feature development.
tags:
  - workflow
  - planning
  - review
trigger: manual
---

# Spec Review Workflow

Use this workflow for any non-trivial feature. It prevents wasted work by validating the plan before coding.

## Phase 1: Plan

1. Write a brief spec describing:
   - **What**: The feature or change
   - **Why**: The motivation and expected outcome
   - **How**: High-level implementation approach
   - **Scope**: What's in and out of scope
2. List the files that will be created or modified.
3. Identify risks or open questions.

## Phase 2: Verify

1. Check that the plan is consistent with the existing codebase.
2. Verify there are no conflicts with existing features.
3. Confirm test strategy — what will be tested and how.
4. Get approval before proceeding.

## Phase 3: Implement

1. Follow TDD cycle (write tests first).
2. Implement in small, reviewable steps.
3. Run the full test suite after each step.

## Phase 4: Review

1. Summarize what was built and any deviations from the spec.
2. List all files changed.
3. Confirm all tests pass.
4. Check for security issues (secrets, injection, access control).
