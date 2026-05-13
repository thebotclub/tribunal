"""Third-party integrations — Slack, PagerDuty, OTEL, ...

Each integration is optional and only wired into the daemon when its
environment variable is set. The intent is \"opt in by config, not by
install\" — adding a webhook URL to the env should be enough.
"""

from tribunal.integrations.slack import SlackNotifier

__all__ = ["SlackNotifier"]
