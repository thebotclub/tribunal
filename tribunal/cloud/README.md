# Tribunal Cloud

Cloudflare-native deployment that powers the hosted Team and Compliance
tiers. Self-hosters can ignore this directory entirely — the OSS
daemon stands alone.

## Architecture

```
agent daemon  ──HTTPS──▶  workers/ingest  ─┬─▶  R2  (raw JSONL.gz events)
                                            └─▶  D1  (event_summary row)
                                            └─▶  Queue  ──▶  workers/aggregate
                                                              ├─▶ D1.cost_hourly
                                                              └─▶ D1.sessions

Next.js dashboard  ──D1 read──▶  Pages   (auth via Cloudflare Access / NextAuth)
```

## Storage layout

- **R2** holds the canonical event log:
  `{org_id}/{YYYY}/{MM}/{DD}/{HH}/{session_id}/{event_id}.json`.
  This is the *only* copy of payloads — D1 stays summary-only so per-row
  scan costs stay bounded.

- **D1** is the queryable index:
  - `event_summary` — one row per accepted event, narrow columns,
    multi-column indices on `(org, epoch_ms)`, `(org, agent, epoch_ms)`,
    `(org, event_type, epoch_ms)`, `(org, policy_decision, epoch_ms)`,
    `(org, user, epoch_ms)`, `(session_id)`.
  - `cost_hourly` — pre-aggregated cost rollups updated by the queue
    consumer. Dashboard cost pages read here, never `event_summary`.
  - `sessions` — per-session totals, also maintained by the aggregator.

## Deploy

```bash
# 1. Create the D1 database
wrangler d1 create tribunal-prod
wrangler d1 execute tribunal-prod --file=./d1-schema.sql

# 2. Create R2 bucket
wrangler r2 bucket create tribunal-events-prod

# 3. Create the queue
wrangler queues create tribunal-events
wrangler queues create tribunal-events-dlq

# 4. Wire up the workers (replace REPLACE_WITH_D1_ID in both
#    wrangler.toml files with the ID printed above).
cd workers/ingest && pnpm install && pnpm run deploy
cd ../aggregate    && pnpm install && pnpm run deploy
```

## Cost estimate

For a 50-developer team generating ~1M events/month:

| Component        | Monthly                  |
|------------------|--------------------------|
| Workers requests | $0.50  (1M @ $0.50/M)    |
| D1 rows read     | $1     (well under 5M)   |
| D1 storage       | $0.20  (~1GB indices)    |
| R2 storage       | $0.50  (~30GB JSONL.gz)  |
| R2 ops           | $1     (1M writes)       |
| Queues           | $0.40                    |
| **Total**        | **~$3.60 / team / month**|

At $19/seat × 50 seats = $950/mo billed; infra is <0.4%.

## Reading data back

For the dashboard, prefer the rollups:

- `sessions` for the sessions list page
- `cost_hourly` for cost graphs
- `event_summary` for the events page, paginated with
  `WHERE org_id = ? AND epoch_ms < ? ORDER BY epoch_ms DESC LIMIT 200`

To stream a session's raw events to the user, list R2 with prefix
`{org_id}/.../{session_id}/` and concatenate JSON lines.
