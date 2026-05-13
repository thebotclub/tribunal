"""Tribunal local daemon -- FastAPI app served on http://127.0.0.1:8088.

Endpoints
---------

  - ``POST /v1/events``    -- adapters submit normalised events here.
                              Body: ``{"events": [<event>, ...]}``.
                              Returns ``{"accepted": N, "rejected": M}``.
  - ``POST /v1/event``     -- single-event convenience wrapper.
  - ``GET  /v1/events``    -- recent events (newest first), with filters.
  - ``GET  /v1/stats``     -- :class:`TimelineStats` for the dashboard.
  - ``GET  /v1/cost``      -- aggregate spend over a window.
  - ``GET  /v1/health``    -- liveness probe (no auth).
  - ``GET  /``             -- minimal HTML dashboard.

Authentication
--------------
Local-only by default (binds to 127.0.0.1). When ``TRIBUNAL_TOKEN`` is
set, all ``/v1/*`` endpoints require ``Authorization: Bearer <token>``.

This module degrades gracefully when FastAPI is unavailable so users on
the OSS pip install with no extras still get useful import errors
instead of a stack trace.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from tribunal import __version__
from tribunal.events.schema import SchemaError, new_event
from tribunal.events.store import EventStore, timeline_stats
from tribunal.events.stream import CloudStreamer
from tribunal.cost import aggregate
from tribunal.policy.evaluator import (
    Decision,
    PolicyPack,
    evaluate as evaluate_policy,
    load_shipped_packs,
)
from tribunal.policy.injection import scan_event as scan_injection
from tribunal.integrations.slack import SlackNotifier

log = logging.getLogger("tribunal.daemon")

DEFAULT_PORT = 8088
DEFAULT_HOST = "127.0.0.1"


# -- App factory --------------------------------------------------------------


def create_app(
    *,
    store: Optional[EventStore] = None,
    streamer: Optional[CloudStreamer] = None,
    auth_token: Optional[str] = None,
    policy_packs: Optional[list[PolicyPack]] = None,
    enable_policy: bool = True,
    enable_injection_scan: bool = True,
    slack: Optional[SlackNotifier] = None,
):
    """Build the FastAPI application. Imports FastAPI lazily so that
    ``import tribunal.daemon`` still works without the ``[serve]`` extra.
    """
    try:
        from contextlib import asynccontextmanager

        from fastapi import FastAPI, HTTPException, Header, Query, Request
        from fastapi.responses import HTMLResponse
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "FastAPI is required to run the Tribunal daemon. "
            "Install with `pip install 'tribunal[serve]'`."
        ) from e

    store = store or EventStore()
    streamer = streamer or CloudStreamer(store)
    auth_token = (
        auth_token if auth_token is not None else os.environ.get("TRIBUNAL_TOKEN", "")
    )
    packs: list[PolicyPack] = (
        list(policy_packs)
        if policy_packs is not None
        else (load_shipped_packs() if enable_policy else [])
    )
    slack_notifier = slack if slack is not None else SlackNotifier.from_env()

    @asynccontextmanager
    async def _lifespan(_app):
        log.info("Tribunal daemon %s starting", __version__)
        streamer.start()
        slack_notifier.start()
        try:
            yield
        finally:
            slack_notifier.stop()
            streamer.stop()
            store.close()

    app = FastAPI(
        title="Tribunal Daemon",
        version=__version__,
        description="Local event ingestion + audit log for AI coding agents.",
        lifespan=_lifespan,
    )

    # -- Auth dependency --------------------------------------------------

    def require_auth(authorization: str = Header(default="")) -> None:
        if not auth_token:
            return
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        if authorization[len("Bearer ") :] != auth_token:
            raise HTTPException(status_code=403, detail="invalid token")

    # -- Health -----------------------------------------------------------

    @app.get("/v1/health")
    def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "events": store.count(),
            "outbox": store.outbox_depth(),
            "cloud_enabled": streamer.enabled,
        }

    # -- Event ingestion --------------------------------------------------

    def _process_event(ev: dict) -> tuple[bool, Optional[Decision], Optional[dict]]:
        """Insert ev, run injection + policy, emit derived events.

        Returns (inserted_ok, decision, injection_finding_dict). On schema
        error the caller is responsible for raising -- this helper does NOT
        catch it.
        """
        store.insert(ev, queue_for_cloud=streamer.enabled)

        injection_dict: Optional[dict] = None
        if enable_injection_scan:
            finding = scan_injection(ev)
            if finding.suspected:
                inj_event = new_event(
                    agent=ev.get("agent", "other"),
                    agent_version=ev.get("agent_version", ""),
                    session_id=ev.get("session_id", ""),
                    user_id=ev.get("user_id", ""),
                    event_type="injection.suspected",
                    payload={
                        "source_event_id": ev.get("event_id", ""),
                        "rule_id": finding.rule_id,
                        "severity": finding.severity,
                        "message": finding.message,
                        "snippet": finding.snippet,
                    },
                    repo_path=ev.get("repo_path"),
                )
                try:
                    store.insert(inj_event, queue_for_cloud=streamer.enabled)
                except SchemaError:
                    log.exception("failed to insert synthetic injection event")
                injection_dict = {
                    "rule_id": finding.rule_id,
                    "severity": finding.severity,
                    "message": finding.message,
                }
                if slack_notifier.enabled:
                    slack_notifier.notify_injection(ev, injection_dict)

        decision: Optional[Decision] = None
        if packs:
            decision = evaluate_policy(ev, packs)
            if decision.action != "allow":
                pol_event_type = f"policy.{decision.action if decision.action != 'deny' else 'block'}"
                # Schema only defines policy.{block, ask, allow}; warn -> block channel? No:
                # we emit warn as policy.allow with policy_decision metadata to keep
                # the event_type set compact. Block/ask are first-class.
                if decision.action == "warn":
                    pol_event_type = "policy.allow"
                pol_event = new_event(
                    agent=ev.get("agent", "other"),
                    agent_version=ev.get("agent_version", ""),
                    session_id=ev.get("session_id", ""),
                    user_id=ev.get("user_id", ""),
                    event_type=pol_event_type,
                    payload={
                        "source_event_id": ev.get("event_id", ""),
                        "rule_id": decision.rule_id,
                        "pack": decision.pack,
                        "message": decision.message,
                    },
                    policy_decision=decision.action,
                    policy_rule=decision.rule_id,
                    policy_message=decision.message,
                    repo_path=ev.get("repo_path"),
                )
                try:
                    store.insert(pol_event, queue_for_cloud=streamer.enabled)
                except SchemaError:
                    log.exception("failed to insert synthetic policy event")
                if slack_notifier.enabled:
                    slack_notifier.notify_policy_decision(
                        ev,
                        {
                            "action": decision.action,
                            "rule_id": decision.rule_id,
                            "pack": decision.pack,
                            "message": decision.message,
                        },
                    )

        return True, decision, injection_dict

    def _decision_to_dict(d: Optional[Decision]) -> dict:
        if d is None:
            return {"action": "allow", "rule_id": "", "pack": "", "message": ""}
        return {
            "action": d.action,
            "rule_id": d.rule_id,
            "pack": d.pack,
            "message": d.message,
        }

    @app.post("/v1/events")
    async def post_events(
        request: Request,
        authorization: str = Header(default=""),
    ) -> dict:
        require_auth(authorization)
        body = await request.json()
        events = body.get("events") if isinstance(body, dict) else None
        if not isinstance(events, list):
            raise HTTPException(status_code=400, detail="body must be {events: [...]}")
        accepted = 0
        rejected: list[dict[str, str]] = []
        decisions: list[dict] = []
        for ev in events:
            try:
                _ok, decision, injection = _process_event(ev)
                accepted += 1
                decisions.append(
                    {
                        "event_id": ev.get("event_id", ""),
                        "decision": _decision_to_dict(decision),
                        "injection": injection,
                    }
                )
            except SchemaError as e:
                rejected.append(
                    {"event_id": str(ev.get("event_id", "")), "error": str(e)}
                )
        return {
            "accepted": accepted,
            "rejected_count": len(rejected),
            "rejected": rejected,
            "decisions": decisions,
        }

    @app.post("/v1/event")
    async def post_event(
        request: Request,
        authorization: str = Header(default=""),
    ) -> dict:
        require_auth(authorization)
        ev = await request.json()
        try:
            _ok, decision, injection = _process_event(ev)
        except SchemaError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {
            "accepted": 1,
            "decision": _decision_to_dict(decision),
            "injection": injection,
        }

    # -- Reads ------------------------------------------------------------

    @app.get("/v1/events")
    def list_events(
        authorization: str = Header(default=""),
        limit: int = Query(default=200, ge=1, le=5000),
        agent: Optional[str] = Query(default=None),
        event_type: Optional[str] = Query(default=None),
        since_ms: Optional[int] = Query(default=None),
    ) -> dict:
        require_auth(authorization)
        rows = store.recent(
            limit=limit, agent=agent, event_type=event_type, since_epoch_ms=since_ms
        )
        return {"events": rows, "count": len(rows)}

    @app.get("/v1/stats")
    def stats(
        authorization: str = Header(default=""),
        since_ms: Optional[int] = Query(default=None),
    ) -> dict:
        require_auth(authorization)
        ts = timeline_stats(store, since_epoch_ms=since_ms)
        return {
            "total_events": ts.total_events,
            "by_agent": ts.by_agent,
            "by_event_type": ts.by_event_type,
            "policy_blocks": ts.policy_blocks,
            "suspected_injections": ts.suspected_injections,
            "cost_usd": ts.cost_usd,
        }

    @app.get("/v1/cost")
    def cost_endpoint(
        authorization: str = Header(default=""),
        since_ms: int = Query(default=0, ge=0),
        until_ms: Optional[int] = Query(default=None),
        user_id: Optional[str] = Query(default=None),
        repo_path: Optional[str] = Query(default=None),
        agent: Optional[str] = Query(default=None),
    ) -> dict:
        require_auth(authorization)
        win = aggregate(
            store,
            since_epoch_ms=since_ms,
            until_epoch_ms=until_ms,
            user_id=user_id,
            repo_path=repo_path,
            agent=agent,
        )
        return {
            "window": {"start_ms": win.start_epoch_ms, "end_ms": win.end_epoch_ms},
            "total_usd": win.total_usd,
            "by_agent": win.by_agent,
            "by_model": win.by_model,
            "by_repo": win.by_repo,
            "event_count": win.event_count,
        }

    # -- Dashboard HTML ---------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return _dashboard_html()

    return app


# -- Minimal dashboard --------------------------------------------------------


def _dashboard_html() -> str:
    """Lightweight inline dashboard. Real Next.js dashboard ships in W4."""
    return """<!doctype html>
<html><head>
<meta charset="utf-8">
<title>Tribunal -- local audit log</title>
<style>
  :root { color-scheme: dark light; }
  body { font: 14px/1.5 -apple-system, "SF Pro Text", system-ui, sans-serif;
         margin: 0; padding: 2rem; max-width: 980px; }
  h1 { font-size: 1.4rem; margin: 0 0 1rem; letter-spacing: -0.01em; }
  .meta { color: #888; margin-bottom: 1.5rem; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #2a2a2a;
           vertical-align: top; }
  th { font-weight: 600; color: #aaa; }
  code { font-family: ui-monospace, Menlo, monospace; font-size: 12px; }
  .agent-claude-code { color: #d97757; }
  .agent-cursor { color: #6ea8fe; }
  .agent-copilot-cli { color: #b1bac4; }
  .agent-codex-cli { color: #76d275; }
  .ev-policy\\.block { color: #ff6b6b; }
  .ev-injection\\.suspected { color: #ff9f1a; }
  .stat { display: inline-block; margin-right: 1.5rem; }
  .stat b { font-size: 1.3rem; font-variant-numeric: tabular-nums; }
</style></head>
<body>
<h1>Tribunal -- local audit log</h1>
<div class="meta">One unified timeline across every coding agent on this machine.
  <a href="/v1/health">/v1/health</a> *
  <a href="/v1/events">/v1/events</a> *
  <a href="/v1/stats">/v1/stats</a></div>
<div id="stats" class="meta">loading...</div>
<table id="events">
  <thead><tr><th>time</th><th>agent</th><th>type</th><th>session</th><th>summary</th></tr></thead>
  <tbody></tbody>
</table>
<script>
async function refresh() {
  const [statsRes, evRes] = await Promise.all([
    fetch("/v1/stats").then(r => r.json()),
    fetch("/v1/events?limit=100").then(r => r.json()),
  ]);
  document.getElementById("stats").innerHTML =
    `<span class="stat"><b>${statsRes.total_events}</b> events</span>` +
    `<span class="stat"><b>${Object.keys(statsRes.by_agent).length}</b> agents</span>` +
    `<span class="stat"><b>${statsRes.policy_blocks}</b> blocks</span>` +
    `<span class="stat"><b>${statsRes.suspected_injections}</b> injection alerts</span>` +
    `<span class="stat"><b>$${statsRes.cost_usd.toFixed(2)}</b> spend</span>`;
  const tbody = document.querySelector("#events tbody");
  tbody.innerHTML = "";
  for (const e of evRes.events) {
    const tr = document.createElement("tr");
    const summary = JSON.stringify(e.payload || {}).slice(0, 200);
    tr.innerHTML =
      `<td><code>${(e.ts || "").slice(11, 19)}</code></td>` +
      `<td class="agent-${e.agent}">${e.agent}</td>` +
      `<td class="ev-${e.event_type}">${e.event_type}</td>` +
      `<td><code>${(e.session_id || "").slice(0, 8)}</code></td>` +
      `<td><code>${summary}</code></td>`;
    tbody.appendChild(tr);
  }
}
refresh();
setInterval(refresh, 4000);
</script>
</body></html>"""


# -- Process entrypoint -------------------------------------------------------


def serve(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    db_path: Optional[Path] = None,
    auth_token: Optional[str] = None,
) -> None:
    """Run the daemon under uvicorn until Ctrl-C."""
    try:
        import uvicorn  # type: ignore[import-not-found]
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "uvicorn is required to serve the daemon. "
            "Install with `pip install 'tribunal[serve]'`."
        ) from e

    store = EventStore(db_path=db_path)
    streamer = CloudStreamer(store)
    app = create_app(store=store, streamer=streamer, auth_token=auth_token)
    log.info("Tribunal daemon listening on http://%s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


def _main(argv: list[str]) -> int:
    if "--check" in argv:
        try:
            import fastapi  # noqa: F401
            import uvicorn  # noqa: F401
        except ImportError:
            print("tribunal.daemon scaffold OK (FastAPI/uvicorn not installed)")
            return 0
        # Smoke test: build the app
        try:
            create_app()
        except Exception as e:  # noqa: BLE001
            print(f"daemon import OK but create_app() failed: {e}", file=sys.stderr)
            return 1
        print(f"tribunal.daemon ready (bind {DEFAULT_HOST}:{DEFAULT_PORT})")
        return 0
    if "--serve" in argv or not argv:
        try:
            serve()
        except KeyboardInterrupt:
            return 130
        return 0
    print(f"unknown args: {argv}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv[1:]))


__all__ = ["create_app", "serve", "DEFAULT_PORT", "DEFAULT_HOST"]
