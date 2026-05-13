# Tribunal -- self-hosted examples

## Docker Compose stack

```bash
cd tribunal/examples
cp .env.example .env       # edit secrets
docker compose up -d
```

That starts:

- `postgres` on `:5432`
- `tribunal` daemon on `:8088`
- `caddy` reverse proxy on `:80`/`:443` (optional -- comment it out if you have your own ingress)

Each developer machine then runs the CLI against this daemon:

```bash
export TRIBUNAL_DAEMON_URL=http://tribunal.internal:8088
tribunal adapter claude-code
tribunal adapter cursor
```

## Policy packs

The `policies/` directory mounts read-only into the daemon at `/policies`. Two starter packs ship here:

- **`starter.yaml`** -- sensible defaults for any team. Deny `.env` writes, warn on `sudo`, ask before `git push` and `rm -rf`.
- **`strict.yaml`** -- for production-adjacent repos. Denies infra/prod writes, kubectl against prod contexts, and trips a $25/session kill switch.

Combine with shipped packs (`secrets-readonly`, `no-prod-writes`, `soc2-baseline`) for layered defence.

## Backups

```bash
# nightly
pg_dump -h postgres tribunal > /backup/tribunal-$(date +%F).sql
docker compose exec tribunal tribunal audit export --since 24h > /backup/events.jsonl
```

The JSONL export is signed with `TRIBUNAL_SIGNING_KEY` for tamper-evidence.

## Upgrades

```bash
docker compose pull tribunal
docker compose up -d
```

Migrations run automatically on daemon start.
