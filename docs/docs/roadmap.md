# Roadmap

## Completed

### Phase 1 — Core Protocol
- [x] HookEvent / HookVerdict dataclasses
- [x] Rule engine with YAML config
- [x] Gate binary (tribunal-gate)
- [x] Audit logging (JSONL)

### Phase 2 — Advanced Rules
- [x] TDD enforcement (Python + TypeScript)
- [x] Secret detection
- [x] External command conditions
- [x] Type checking / linting conditions

### Phase 3 — Cost Tracking
- [x] Token + cost tracking
- [x] Session and daily budgets
- [x] Cost-exceeded condition

### Phase 4 — CLI + Configuration
- [x] Full CLI (init, rules, audit, cost, memory, agents)
- [x] Config cascade (defaults → project → user)
- [x] Bundle export/import

### Phase 5 — Hardening
- [x] Audit rotation
- [x] Config validation
- [x] Doctor command
- [x] Memory stats

### Phase 6 — CI/CD
- [x] GitHub Actions workflows
- [x] PyPI publishing
- [x] Website deployment

### Phase 7 — Hook Lifecycle
- [x] Permission tracking
- [x] Escalation detection
- [x] Compaction analytics

### Phase 8 — Multi-Agent Governance
- [x] Agent policies
- [x] Task-based permissions
- [x] Per-agent audit trails

### Phase 9 — VS Code Extension + Dashboard
- [x] VS Code extension scaffold
- [x] 4 TreeView providers
- [x] Team Dashboard HTTP API

### Phase 10 — Ecosystem
- [x] Rule packs (SOC 2, Startup, Enterprise, Security)
- [x] Programmatic SDK
- [x] Documentation site scaffold

## Future

### Phase 11 — Community
- [ ] Plugin system for custom conditions
- [ ] Community rule pack registry
- [ ] Rule sharing via tribunal.dev

### Phase 12 — Enterprise
- [ ] SSO / SAML integration
- [ ] Centralized policy management
- [ ] Compliance reporting dashboard
