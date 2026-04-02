"""SARIF 2.1.0 output formatter for Tribunal checker results.

Produces Static Analysis Results Interchange Format (SARIF) compatible
with GitHub Code Scanning, VS Code SARIF Viewer, and other tools.
Spec: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
"""

from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .checkers import CheckResult, Finding

_SARIF_SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json"

_SEVERITY_MAP = {
    "error": "error",
    "warning": "warning",
    "info": "note",
}


def findings_to_sarif(
    results: list[CheckResult],
    project_root: Path,
) -> dict:
    """Convert CheckResult list to a SARIF 2.1.0 log dict.

    Args:
        results: Checker results with findings.
        project_root: Project root for artifact URIs.

    Returns:
        SARIF log as a dict, ready for json.dumps().
    """
    # Collect all unique rule IDs across results
    rules_seen: dict[str, int] = {}
    rule_defs: list[dict] = []

    sarif_results: list[dict] = []

    for check_result in results:
        for finding in check_result.findings:
            # Register rule if new
            if finding.rule_id not in rules_seen:
                rules_seen[finding.rule_id] = len(rule_defs)
                rule_defs.append(
                    {
                        "id": finding.rule_id,
                        "shortDescription": {"text": finding.rule_id},
                    }
                )

            sarif_result = _finding_to_result(finding, rules_seen[finding.rule_id])
            sarif_results.append(sarif_result)

    run = {
        "tool": {
            "driver": {
                "name": "tribunal",
                "version": __version__,
                "informationUri": "https://tribunal.dev",
                "rules": rule_defs,
            }
        },
        "results": sarif_results,
    }

    return {
        "$schema": _SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [run],
    }


def _finding_to_result(finding: Finding, rule_index: int) -> dict:
    """Convert a single Finding to a SARIF result object."""
    result: dict = {
        "ruleId": finding.rule_id,
        "ruleIndex": rule_index,
        "level": _SEVERITY_MAP.get(finding.severity, "warning"),
        "message": {"text": finding.message},
    }

    if finding.file:
        location: dict = {
            "physicalLocation": {
                "artifactLocation": {
                    "uri": finding.file,
                    "uriBaseId": "%SRCROOT%",
                },
            }
        }
        if finding.line > 0:
            location["physicalLocation"]["region"] = {
                "startLine": finding.line,
            }
        result["locations"] = [location]

    return result


def sarif_to_json(sarif: dict, *, indent: int = 2) -> str:
    """Serialize SARIF dict to JSON string."""
    return json.dumps(sarif, indent=indent)
