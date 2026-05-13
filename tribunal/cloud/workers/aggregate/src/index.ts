/**
 * tribunal-aggregate — queue consumer
 *
 * Reads QueueMessage batches from the tribunal-events queue and
 * incrementally maintains two derived tables in D1:
 *
 *   - cost_hourly:  per (org, hour, user, agent, model, repo) rollup
 *   - sessions:     per-session totals (event_count, tool_count,
 *                   policy_blocks, injection_alerts, cost_usd, title)
 *
 * Keeping these rollups warm means dashboard reads never scan
 * event_summary directly, which keeps the D1 bill flat.
 */

export interface Env {
  DB: D1Database;
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
  // Optional enrichment from the ingest worker
  model?: string;
  repo_path?: string;
  input_tokens?: number;
  output_tokens?: number;
  prompt_title?: string;
}

const HOUR_MS = 3_600_000;

export default {
  async queue(batch: MessageBatch<QueueMessage>, env: Env): Promise<void> {
    // Group by (cost_hourly key) and by (session_id) for batched upserts.
    const costBuckets = new Map<string, CostBucket>();
    const sessionUpdates = new Map<string, SessionUpdate>();

    for (const msg of batch.messages) {
      const m = msg.body;

      // ── cost_hourly ──
      if (m.cost_usd > 0 || m.input_tokens || m.output_tokens) {
        const hour = Math.floor(m.epoch_ms / HOUR_MS) * HOUR_MS;
        const key = [
          m.org_id, hour, m.user_id, m.agent,
          m.model ?? "", m.repo_path ?? "",
        ].join("|");
        const bucket = costBuckets.get(key) ?? {
          org_id: m.org_id,
          hour_epoch_ms: hour,
          user_id: m.user_id,
          agent: m.agent,
          model: m.model ?? "",
          repo_path: m.repo_path ?? null,
          total_usd: 0,
          input_tokens: 0,
          output_tokens: 0,
          event_count: 0,
        };
        bucket.total_usd += m.cost_usd;
        bucket.input_tokens += m.input_tokens ?? 0;
        bucket.output_tokens += m.output_tokens ?? 0;
        bucket.event_count += 1;
        costBuckets.set(key, bucket);
      }

      // ── sessions ──
      const sess = sessionUpdates.get(m.session_id) ?? {
        id: m.session_id,
        org_id: m.org_id,
        user_id: m.user_id,
        agent: m.agent,
        start_epoch_ms: m.epoch_ms,
        end_epoch_ms: m.epoch_ms,
        event_count: 0,
        tool_count: 0,
        policy_blocks: 0,
        injection_alerts: 0,
        cost_usd: 0,
        repo_path: m.repo_path ?? null,
        title: m.prompt_title ?? null,
      };
      sess.start_epoch_ms = Math.min(sess.start_epoch_ms, m.epoch_ms);
      sess.end_epoch_ms = Math.max(sess.end_epoch_ms, m.epoch_ms);
      sess.event_count += 1;
      if (m.event_type.startsWith("tool.")) sess.tool_count += 1;
      if (m.event_type === "policy.block" || m.policy_decision === "deny") sess.policy_blocks += 1;
      if (m.event_type === "injection.suspected") sess.injection_alerts += 1;
      sess.cost_usd += m.cost_usd;
      if (!sess.title && m.prompt_title) sess.title = m.prompt_title;
      sessionUpdates.set(m.session_id, sess);
    }

    // Stage 1: cost_hourly upserts
    const costStmts: D1PreparedStatement[] = [];
    for (const b of costBuckets.values()) {
      costStmts.push(
        env.DB.prepare(
          `INSERT INTO cost_hourly
           (org_id, hour_epoch_ms, user_id, agent, model, repo_path,
            total_usd, input_tokens, output_tokens, event_count)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(org_id, hour_epoch_ms, user_id, agent, model, repo_path)
           DO UPDATE SET
             total_usd     = total_usd     + excluded.total_usd,
             input_tokens  = input_tokens  + excluded.input_tokens,
             output_tokens = output_tokens + excluded.output_tokens,
             event_count   = event_count   + excluded.event_count`,
        ).bind(
          b.org_id, b.hour_epoch_ms, b.user_id, b.agent, b.model, b.repo_path,
          b.total_usd, b.input_tokens, b.output_tokens, b.event_count,
        ),
      );
    }

    // Stage 2: sessions upserts
    const sessStmts: D1PreparedStatement[] = [];
    for (const s of sessionUpdates.values()) {
      sessStmts.push(
        env.DB.prepare(
          `INSERT INTO sessions
           (id, org_id, user_id, agent, start_epoch_ms, end_epoch_ms,
            event_count, tool_count, policy_blocks, injection_alerts, cost_usd,
            repo_path, title)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             start_epoch_ms   = MIN(start_epoch_ms,  excluded.start_epoch_ms),
             end_epoch_ms     = MAX(end_epoch_ms,    excluded.end_epoch_ms),
             event_count      = event_count      + excluded.event_count,
             tool_count       = tool_count       + excluded.tool_count,
             policy_blocks    = policy_blocks    + excluded.policy_blocks,
             injection_alerts = injection_alerts + excluded.injection_alerts,
             cost_usd         = cost_usd         + excluded.cost_usd,
             title            = COALESCE(title, excluded.title)`,
        ).bind(
          s.id, s.org_id, s.user_id, s.agent, s.start_epoch_ms, s.end_epoch_ms,
          s.event_count, s.tool_count, s.policy_blocks, s.injection_alerts, s.cost_usd,
          s.repo_path, s.title,
        ),
      );
    }

    try {
      if (costStmts.length) await env.DB.batch(costStmts);
      if (sessStmts.length) await env.DB.batch(sessStmts);
      batch.ackAll();
    } catch (err) {
      console.error("aggregate flush failed", err);
      batch.retryAll();
    }
  },
};

interface CostBucket {
  org_id: string;
  hour_epoch_ms: number;
  user_id: string;
  agent: string;
  model: string;
  repo_path: string | null;
  total_usd: number;
  input_tokens: number;
  output_tokens: number;
  event_count: number;
}

interface SessionUpdate {
  id: string;
  org_id: string;
  user_id: string;
  agent: string;
  start_epoch_ms: number;
  end_epoch_ms: number;
  event_count: number;
  tool_count: number;
  policy_blocks: number;
  injection_alerts: number;
  cost_usd: number;
  repo_path: string | null;
  title: string | null;
}
