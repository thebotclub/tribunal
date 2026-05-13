/**
 * tribunal-ingest — Cloudflare Worker
 *
 * Receives unified events from agent daemons on the customer's machines,
 * authenticates the ingestion token against D1, and writes:
 *
 *   1. The full event JSON line to R2 under a date+session partition.
 *   2. A compact summary row to D1 (event_summary table).
 *   3. A queue message for the aggregator worker to roll up cost_hourly
 *      and update the sessions table.
 *
 * Endpoints
 *   POST /v1/events          batch ingest
 *   GET  /v1/health          unauth liveness probe
 *
 * Auth
 *   Authorization: Bearer <token>
 *   We sha256(token) and look up an active row in ingestion_tokens.
 */

export interface Env {
  DB: D1Database;
  EVENTS_BUCKET: R2Bucket;
  EVENT_QUEUE: Queue<QueueMessage>;
  MAX_BATCH_SIZE: string;
  MAX_EVENT_BYTES: string;
  ENV: string;
}

interface QueueMessage {
  org_id: string;
  user_id: string;
  agent: string;
  session_id: string;
  event_type: string;
  epoch_ms: number;
  cost_usd: number;
  policy_decision?: string;
  injection_severity?: string;
  r2_object_key: string;
}

interface RawEvent {
  schema_version?: string;
  event_id?: string;
  ts?: string;
  agent?: string;
  agent_version?: string;
  session_id?: string;
  user_id?: string;
  event_type?: string;
  payload?: Record<string, unknown>;
  repo_path?: string;
  cost?: { usd?: number; model?: string };
  policy_decision?: string;
  policy_rule?: string;
}

const SUPPORTED_EVENT_TYPES = new Set([
  "session.start", "session.end",
  "prompt.submitted",
  "tool.proposed", "tool.approved", "tool.denied", "tool.executed", "tool.failed",
  "mcp.call.before", "mcp.call.after",
  "file.read", "file.write", "file.delete",
  "bash.executed",
  "subagent.start", "subagent.stop",
  "policy.block", "policy.ask", "policy.allow",
  "injection.suspected",
  "cost.recorded",
  "error.gate",
]);

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    // Liveness
    if (request.method === "GET" && url.pathname === "/v1/health") {
      return json({ status: "ok", env: env.ENV });
    }

    if (request.method !== "POST" || url.pathname !== "/v1/events") {
      return new Response("not found", { status: 404 });
    }

    // ── Auth ─────────────────────────────────────────────────────────
    const authz = request.headers.get("authorization") ?? "";
    if (!authz.startsWith("Bearer ")) {
      return json({ error: "missing bearer token" }, 401);
    }
    const token = authz.slice("Bearer ".length).trim();
    const tokenHash = await sha256Hex(token);

    const auth = await env.DB.prepare(
      "SELECT org_id, user_id FROM ingestion_tokens WHERE token_hash = ?1 AND revoked_at IS NULL"
    ).bind(tokenHash).first<{ org_id: string; user_id: string | null }>();

    if (!auth) {
      return json({ error: "invalid token" }, 403);
    }

    const orgId = auth.org_id;
    const fallbackUserId = auth.user_id ?? "unknown";

    // ── Parse body ───────────────────────────────────────────────────
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON" }, 400);
    }
    const events = (body as { events?: unknown })?.events;
    if (!Array.isArray(events)) {
      return json({ error: "body must be {events: [...]}" }, 400);
    }
    const maxBatch = parseInt(env.MAX_BATCH_SIZE, 10) || 500;
    if (events.length > maxBatch) {
      return json({ error: `too many events; max ${maxBatch}` }, 413);
    }

    // ── Per-event processing ─────────────────────────────────────────
    const accepted: string[] = [];
    const rejected: Array<{ event_id: string; reason: string }> = [];
    const r2WritePromises: Promise<unknown>[] = [];
    const d1Statements: D1PreparedStatement[] = [];
    const queueMessages: QueueMessage[] = [];

    for (const raw of events as RawEvent[]) {
      const validation = validate(raw);
      if (!validation.ok) {
        rejected.push({ event_id: String(raw?.event_id ?? ""), reason: validation.reason });
        continue;
      }
      const ev = raw as Required<RawEvent>;
      const epochMs = isoToEpochMs(ev.ts);
      const r2Key = r2PartitionKey(orgId, ev.session_id, ev.event_id, epochMs);

      // 1. R2 write — full JSONL line
      r2WritePromises.push(
        env.EVENTS_BUCKET.put(r2Key, JSON.stringify(ev) + "\n", {
          httpMetadata: { contentType: "application/x-ndjson" },
          customMetadata: {
            org_id: orgId,
            session_id: ev.session_id,
            event_type: ev.event_type,
          },
        }),
      );

      // 2. D1 summary row
      const costUsd = Number(ev.cost?.usd ?? 0) || 0;
      const policyDecision = (ev.policy_decision ?? null) as string | null;
      const policyRule = (ev.policy_rule ?? null) as string | null;
      const injectionSeverity =
        ev.event_type === "injection.suspected"
          ? String((ev.payload as { severity?: string })?.severity ?? "low")
          : null;
      d1Statements.push(
        env.DB.prepare(
          `INSERT OR REPLACE INTO event_summary
           (id, org_id, user_id, session_id, agent, event_type, epoch_ms,
            repo_path, cost_usd, policy_decision, policy_rule, injection_severity, r2_object_key)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`,
        ).bind(
          ev.event_id,
          orgId,
          ev.user_id || fallbackUserId,
          ev.session_id,
          ev.agent,
          ev.event_type,
          epochMs,
          ev.repo_path ?? null,
          costUsd,
          policyDecision,
          policyRule,
          injectionSeverity,
          r2Key,
        ),
      );

      // 3. Queue for the aggregator (cost rollup + sessions update)
      queueMessages.push({
        org_id: orgId,
        user_id: ev.user_id || fallbackUserId,
        agent: ev.agent,
        session_id: ev.session_id,
        event_type: ev.event_type,
        epoch_ms: epochMs,
        cost_usd: costUsd,
        policy_decision: policyDecision ?? undefined,
        injection_severity: injectionSeverity ?? undefined,
        r2_object_key: r2Key,
      });

      accepted.push(ev.event_id);
    }

    // Run R2 + D1 + queue writes in parallel
    const flush = Promise.all([
      Promise.all(r2WritePromises),
      d1Statements.length ? env.DB.batch(d1Statements) : Promise.resolve([]),
      queueMessages.length
        ? env.EVENT_QUEUE.sendBatch(queueMessages.map((m) => ({ body: m })))
        : Promise.resolve(),
    ]);

    // Update last_used_at on the token (fire and forget)
    ctx.waitUntil(
      env.DB.prepare(
        "UPDATE ingestion_tokens SET last_used_at = ?1 WHERE token_hash = ?2",
      ).bind(Date.now(), tokenHash).run(),
    );

    try {
      await flush;
    } catch (err) {
      // If R2 or D1 fails on the whole batch, surface a 502 so the daemon
      // retries via its outbox.
      console.error("flush failed", err);
      return json({ error: "ingestion backend unavailable", accepted: 0 }, 502);
    }

    return json({
      accepted: accepted.length,
      rejected_count: rejected.length,
      rejected,
    });
  },
};


// ── Helpers ────────────────────────────────────────────────────────────────

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function validate(ev: RawEvent): { ok: true } | { ok: false; reason: string } {
  if (!ev || typeof ev !== "object") {
    return { ok: false, reason: "event not an object" };
  }
  const required: (keyof RawEvent)[] = [
    "schema_version", "event_id", "ts", "agent",
    "agent_version", "session_id", "user_id", "event_type",
  ];
  for (const k of required) {
    if (!ev[k]) return { ok: false, reason: `missing ${k}` };
  }
  if (!SUPPORTED_EVENT_TYPES.has(ev.event_type as string)) {
    return { ok: false, reason: `unknown event_type ${ev.event_type}` };
  }
  return { ok: true };
}

function isoToEpochMs(ts: string): number {
  const ms = Date.parse(ts);
  return Number.isFinite(ms) ? ms : Date.now();
}

/**
 * R2 partitioning: org_id / YYYY / MM / DD / HH / session_id / event_id.json
 *
 * - Daily granularity for archival queries
 * - Hour partition keeps a single hot prefix from getting too wide
 * - session_id grouping lets us page through a session's events efficiently
 */
function r2PartitionKey(
  orgId: string,
  sessionId: string,
  eventId: string,
  epochMs: number,
): string {
  const d = new Date(epochMs);
  const yyyy = d.getUTCFullYear();
  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(d.getUTCDate()).padStart(2, "0");
  const hh = String(d.getUTCHours()).padStart(2, "0");
  return `${orgId}/${yyyy}/${mm}/${dd}/${hh}/${sessionId}/${eventId}.json`;
}

async function sha256Hex(input: string): Promise<string> {
  const bytes = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
