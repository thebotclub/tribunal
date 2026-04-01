---
name: security-audit
description: Security review checklist for code changes — secrets, injection, access control.
tags:
  - security
  - review
  - audit
trigger: manual
---

# Security Audit

Run this checklist before merging any code that handles user input, authentication, or sensitive data.

## Secrets & Credentials

- [ ] No hardcoded API keys, tokens, or passwords
- [ ] Secrets loaded from environment variables or secret managers
- [ ] No secrets in git history (check with `git log -p --all -S 'password'`)
- [ ] `.env` files are in `.gitignore`

## Input Validation

- [ ] All user input is validated and sanitized
- [ ] SQL queries use parameterized statements (no string concatenation)
- [ ] No eval() or exec() on user-supplied data
- [ ] File paths are validated against path traversal (no `../`)
- [ ] HTTP headers and URLs are validated

## Authentication & Authorization

- [ ] Authentication is required for protected endpoints
- [ ] Authorization checks before data access
- [ ] Session tokens are invalidated on logout
- [ ] Password hashing uses bcrypt/argon2 (not MD5/SHA1)

## Dependencies

- [ ] No known vulnerable dependencies (`npm audit` / `pip audit`)
- [ ] Dependencies pinned to specific versions
- [ ] No unnecessary permissions requested

## Output

- [ ] HTML output is escaped (prevent XSS)
- [ ] Error messages don't leak internal details
- [ ] Logging doesn't include sensitive data
