# Rule Packs

Pre-built governance rule sets for common compliance and workflow patterns.

## Available Packs

| Pack | Description | Rules |
|------|-------------|-------|
| `soc2` | SOC 2 compliance — TDD, secret detection, audit logging | 4 |
| `startup` | Fast-moving teams — TDD + cost limits | 3 |
| `enterprise` | Full governance — all rules + multi-agent | 4 |
| `security` | Security-focused — secrets, TDD, type safety | 3 |

## CLI Usage

```bash
# List available packs
tribunal pack list

# Install a pack
tribunal pack install soc2

# Install and merge with existing rules
tribunal pack install security
```

## SDK Usage

```python
from tribunal.sdk import TribunalSDK

sdk = TribunalSDK("/path/to/project")
ok, messages = sdk.install_pack("soc2")
```

## Pack Details

### SOC 2

Designed for teams needing SOC 2 Type II compliance:

- TDD enforcement for Python
- Secret detection in all file edits
- Strict audit logging with no rotation
- TypeScript test enforcement

### Startup

Lightweight governance for fast-moving teams:

- TDD enforcement
- Session cost budget ($5)
- Daily cost budget ($20)

### Enterprise

Full governance suite:

- TDD enforcement
- Secret detection
- Cost monitoring
- Multi-agent governance with audit trails

### Security

Security-first rule set:

- Secret detection in code
- TDD enforcement
- Type checking on all Python edits
