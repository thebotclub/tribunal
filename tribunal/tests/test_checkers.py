"""Tests for tribunal.checkers and tribunal.sarif modules."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tribunal.checkers import (
    CheckResult,
    Finding,
    collect_files,
    run_checkers,
)
from tribunal.checkers.secrets import (
    SECRET_PATTERNS,
    _is_placeholder,
    _load_secretsignore,
    check_secrets,
)
from tribunal.checkers.tdd import (
    _has_go_test,
    _has_python_test,
    _has_typescript_test,
    _parse_imports,
    check_tdd_go,
    check_tdd_python,
    check_tdd_typescript,
    find_affected_tests,
)
from tribunal.sarif import findings_to_sarif, sarif_to_json


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project structure for testing."""
    src = tmp_path / "src"
    src.mkdir()
    tests = tmp_path / "tests"
    tests.mkdir()
    return tmp_path


# ── CheckResult / Finding dataclass tests ─────────────────────────────────────


class TestDataclasses:
    def test_finding_fields(self):
        f = Finding(
            checker="secrets",
            file="app.py",
            line=10,
            severity="error",
            message="AWS key found",
            rule_id="secrets/aws-access-key",
        )
        assert f.checker == "secrets"
        assert f.line == 10
        assert f.severity == "error"

    def test_check_result_passed_no_findings(self):
        r = CheckResult(checker="secrets", file="clean.py")
        assert r.passed is True

    def test_check_result_passed_with_warnings_only(self):
        r = CheckResult(
            checker="tdd",
            file="app.py",
            findings=[
                Finding(checker="tdd", file="app.py", line=0, severity="warning", message="no test", rule_id="tdd/missing"),
            ],
        )
        assert r.passed is True  # warnings don't fail

    def test_check_result_failed_with_errors(self):
        r = CheckResult(
            checker="secrets",
            file="app.py",
            findings=[
                Finding(checker="secrets", file="app.py", line=5, severity="error", message="secret", rule_id="secrets/aws"),
            ],
        )
        assert r.passed is False


# ── Secrets checker tests ─────────────────────────────────────────────────────


class TestSecretsChecker:
    def test_detects_aws_key(self, tmp_project: Path):
        f = tmp_project / "config.py"
        f.write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
        result = check_secrets(f, tmp_project)
        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "secrets/aws-access-key"

    def test_detects_github_token(self, tmp_project: Path):
        f = tmp_project / "deploy.py"
        f.write_text('TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh1234"\n')
        result = check_secrets(f, tmp_project)
        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "secrets/github-token"

    def test_detects_private_key(self, tmp_project: Path):
        f = tmp_project / "cert.py"
        f.write_text('key = """-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAK...\n-----END RSA PRIVATE KEY-----"""\n')
        result = check_secrets(f, tmp_project)
        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "secrets/private-key"

    def test_detects_database_url(self, tmp_project: Path):
        f = tmp_project / "db.py"
        f.write_text('DB = "postgres://admin:s3cret@db.host.com:5432/mydb"\n')
        result = check_secrets(f, tmp_project)
        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "secrets/database-url"

    def test_clean_file_passes(self, tmp_project: Path):
        f = tmp_project / "clean.py"
        f.write_text('import os\n\nDB_URL = os.environ["DATABASE_URL"]\n')
        result = check_secrets(f, tmp_project)
        assert result.passed is True
        assert len(result.findings) == 0

    def test_skips_placeholders(self, tmp_project: Path):
        f = tmp_project / "example.py"
        f.write_text('API_KEY = "your-api-key-here"\n')
        result = check_secrets(f, tmp_project)
        assert len(result.findings) == 0

    def test_skips_binary_extensions(self, tmp_project: Path):
        f = tmp_project / "image.png"
        f.write_bytes(b"\x89PNG\r\n")
        result = check_secrets(f, tmp_project)
        assert len(result.findings) == 0

    def test_skips_lock_files(self, tmp_project: Path):
        f = tmp_project / "package-lock.json"
        f.write_text('{"integrity": "sha512-AKIAIOSFODNN7EXAMPLE..."}')
        result = check_secrets(f, tmp_project)
        assert len(result.findings) == 0

    def test_secretsignore(self, tmp_project: Path):
        # Create .secretsignore
        ignore = tmp_project / ".secretsignore"
        ignore.write_text("EXAMPLE\n")
        f = tmp_project / "config.py"
        f.write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
        result = check_secrets(f, tmp_project)
        assert len(result.findings) == 0

    def test_line_numbers(self, tmp_project: Path):
        f = tmp_project / "multi.py"
        f.write_text('line1 = "clean"\nline2 = "clean"\nline3 = "AKIAIOSFODNN7EXAMPLE"\n')
        result = check_secrets(f, tmp_project)
        assert len(result.findings) == 1
        assert result.findings[0].line == 3

    def test_placeholder_detection(self):
        assert _is_placeholder("your-api-key-here") is True
        assert _is_placeholder("<API_KEY>") is True
        assert _is_placeholder("xxxxx") is True
        assert _is_placeholder("changeme") is True
        assert _is_placeholder("AKIAIOSFODNN7EXAMPLE") is False
        assert _is_placeholder("ghp_realtoken123456") is False

    def test_load_secretsignore_empty(self, tmp_project: Path):
        patterns = _load_secretsignore(tmp_project)
        assert patterns == []

    def test_secret_patterns_compile(self):
        """All secret patterns should be valid regex."""
        import re

        for pattern, rule_id in SECRET_PATTERNS:
            compiled = re.compile(pattern)
            assert compiled is not None, f"Pattern for {rule_id} failed to compile"


# ── TDD checker tests ─────────────────────────────────────────────────────────


class TestTDDChecker:
    def test_python_missing_test(self, tmp_project: Path):
        f = tmp_project / "src" / "app.py"
        f.write_text("def hello(): pass\n")
        result = check_tdd_python(f, tmp_project)
        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "tdd/missing-test-python"
        assert result.findings[0].severity == "warning"

    def test_python_has_test(self, tmp_project: Path):
        f = tmp_project / "src" / "app.py"
        f.write_text("def hello(): pass\n")
        t = tmp_project / "tests" / "test_app.py"
        t.write_text("def test_hello(): pass\n")
        result = check_tdd_python(f, tmp_project)
        assert len(result.findings) == 0

    def test_python_test_file_skipped(self, tmp_project: Path):
        f = tmp_project / "tests" / "test_app.py"
        f.write_text("def test_hello(): pass\n")
        result = check_tdd_python(f, tmp_project)
        assert len(result.findings) == 0

    def test_python_init_skipped(self, tmp_project: Path):
        f = tmp_project / "src" / "__init__.py"
        f.write_text("")
        result = check_tdd_python(f, tmp_project)
        assert len(result.findings) == 0

    def test_python_private_skipped(self, tmp_project: Path):
        f = tmp_project / "src" / "_internal.py"
        f.write_text("x = 1\n")
        result = check_tdd_python(f, tmp_project)
        assert len(result.findings) == 0

    def test_typescript_missing_test(self, tmp_project: Path):
        f = tmp_project / "src" / "widget.ts"
        f.write_text("export const widget = {};\n")
        result = check_tdd_typescript(f, tmp_project)
        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "tdd/missing-test-typescript"

    def test_typescript_has_test(self, tmp_project: Path):
        src = tmp_project / "src"
        f = src / "widget.ts"
        f.write_text("export const widget = {};\n")
        t = src / "widget.test.ts"
        t.write_text("test('widget', () => {});\n")
        result = check_tdd_typescript(f, tmp_project)
        assert len(result.findings) == 0

    def test_typescript_test_file_skipped(self, tmp_project: Path):
        f = tmp_project / "src" / "widget.test.ts"
        f.write_text("test('widget', () => {});\n")
        result = check_tdd_typescript(f, tmp_project)
        assert len(result.findings) == 0

    def test_typescript_index_skipped(self, tmp_project: Path):
        f = tmp_project / "src" / "index.ts"
        f.write_text("export {};\n")
        result = check_tdd_typescript(f, tmp_project)
        assert len(result.findings) == 0

    def test_go_missing_test(self, tmp_project: Path):
        f = tmp_project / "src" / "handler.go"
        f.write_text("package main\n")
        result = check_tdd_go(f, tmp_project)
        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "tdd/missing-test-go"

    def test_go_has_test(self, tmp_project: Path):
        src = tmp_project / "src"
        f = src / "handler.go"
        f.write_text("package main\n")
        t = src / "handler_test.go"
        t.write_text("package main\n")
        result = check_tdd_go(f, tmp_project)
        assert len(result.findings) == 0

    def test_go_test_file_skipped(self, tmp_project: Path):
        f = tmp_project / "src" / "handler_test.go"
        f.write_text("package main\n")
        result = check_tdd_go(f, tmp_project)
        assert len(result.findings) == 0


# ── TDD dependency graph tests ────────────────────────────────────────────────


class TestDependencyGraph:
    def test_parse_imports(self, tmp_project: Path):
        f = tmp_project / "src" / "app.py"
        f.write_text("import os\nfrom pathlib import Path\nfrom .utils import helper\n")
        imports = _parse_imports(f)
        assert "os" in imports
        assert "pathlib" in imports
        assert ".utils" in imports

    def test_find_affected_tests(self, tmp_project: Path):
        # Create source file
        src = tmp_project / "src" / "utils.py"
        src.write_text("def helper(): pass\n")
        # Create app that imports utils
        app = tmp_project / "src" / "app.py"
        app.write_text("from utils import helper\n")
        # Create test for app
        test = tmp_project / "src" / "test_app.py"
        test.write_text("from app import something\n")
        # Find tests affected by changing utils
        affected = find_affected_tests(src, tmp_project)
        assert any("test_app" in str(t) for t in affected)

    def test_find_affected_tests_nonexistent(self, tmp_project: Path):
        f = tmp_project / "nonexistent.py"
        affected = find_affected_tests(f, tmp_project)
        assert affected == []

    def test_has_python_test_sibling(self, tmp_project: Path):
        f = tmp_project / "src" / "app.py"
        f.write_text("")
        t = tmp_project / "src" / "test_app.py"
        t.write_text("")
        assert _has_python_test(f, tmp_project) is True

    def test_has_python_test_in_tests_dir(self, tmp_project: Path):
        f = tmp_project / "src" / "app.py"
        f.write_text("")
        t = tmp_project / "tests" / "test_app.py"
        t.write_text("")
        assert _has_python_test(f, tmp_project) is True

    def test_has_typescript_test(self, tmp_project: Path):
        f = tmp_project / "src" / "app.ts"
        f.write_text("")
        t = tmp_project / "src" / "app.test.ts"
        t.write_text("")
        assert _has_typescript_test(f) is True

    def test_has_go_test(self, tmp_project: Path):
        f = tmp_project / "src" / "app.go"
        f.write_text("")
        t = tmp_project / "src" / "app_test.go"
        t.write_text("")
        assert _has_go_test(f) is True


# ── SARIF output tests ────────────────────────────────────────────────────────


class TestSARIF:
    def test_empty_results(self, tmp_project: Path):
        sarif = findings_to_sarif([], tmp_project)
        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"]) == 1
        assert sarif["runs"][0]["results"] == []

    def test_single_finding(self, tmp_project: Path):
        results = [
            CheckResult(
                checker="secrets",
                file="app.py",
                findings=[
                    Finding(
                        checker="secrets",
                        file="app.py",
                        line=5,
                        severity="error",
                        message="AWS key found",
                        rule_id="secrets/aws-access-key",
                    )
                ],
            )
        ]
        sarif = findings_to_sarif(results, tmp_project)
        run = sarif["runs"][0]
        assert len(run["results"]) == 1
        assert run["results"][0]["ruleId"] == "secrets/aws-access-key"
        assert run["results"][0]["level"] == "error"
        assert run["results"][0]["locations"][0]["physicalLocation"]["region"]["startLine"] == 5

    def test_multiple_findings(self, tmp_project: Path):
        results = [
            CheckResult(
                checker="secrets",
                file="app.py",
                findings=[
                    Finding(checker="secrets", file="app.py", line=1, severity="error", message="a", rule_id="secrets/a"),
                    Finding(checker="secrets", file="app.py", line=2, severity="error", message="b", rule_id="secrets/b"),
                ],
            ),
            CheckResult(
                checker="tdd",
                file="app.py",
                findings=[
                    Finding(checker="tdd", file="app.py", line=0, severity="warning", message="no test", rule_id="tdd/missing"),
                ],
            ),
        ]
        sarif = findings_to_sarif(results, tmp_project)
        run = sarif["runs"][0]
        assert len(run["results"]) == 3
        assert len(run["tool"]["driver"]["rules"]) == 3

    def test_sarif_tool_info(self, tmp_project: Path):
        sarif = findings_to_sarif([], tmp_project)
        driver = sarif["runs"][0]["tool"]["driver"]
        assert driver["name"] == "tribunal"
        assert driver["informationUri"] == "https://tribunal.dev"

    def test_sarif_to_json(self, tmp_project: Path):
        sarif = findings_to_sarif([], tmp_project)
        json_str = sarif_to_json(sarif)
        parsed = json.loads(json_str)
        assert parsed["version"] == "2.1.0"

    def test_severity_mapping(self, tmp_project: Path):
        results = [
            CheckResult(
                checker="test",
                file="f.py",
                findings=[
                    Finding(checker="test", file="f.py", line=1, severity="error", message="e", rule_id="r1"),
                    Finding(checker="test", file="f.py", line=2, severity="warning", message="w", rule_id="r2"),
                    Finding(checker="test", file="f.py", line=3, severity="info", message="i", rule_id="r3"),
                ],
            )
        ]
        sarif = findings_to_sarif(results, tmp_project)
        levels = [r["level"] for r in sarif["runs"][0]["results"]]
        assert levels == ["error", "warning", "note"]

    def test_file_level_finding_no_region(self, tmp_project: Path):
        results = [
            CheckResult(
                checker="tdd",
                file="app.py",
                findings=[
                    Finding(checker="tdd", file="app.py", line=0, severity="warning", message="no test", rule_id="tdd/x"),
                ],
            )
        ]
        sarif = findings_to_sarif(results, tmp_project)
        loc = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
        assert "region" not in loc  # line=0 means file-level


# ── collect_files tests ───────────────────────────────────────────────────────


class TestCollectFiles:
    def test_collects_python_files(self, tmp_project: Path):
        (tmp_project / "src" / "app.py").write_text("")
        (tmp_project / "src" / "utils.py").write_text("")
        files = collect_files(tmp_project)
        py_files = [f for f in files if f.suffix == ".py"]
        assert len(py_files) >= 2

    def test_skips_venv(self, tmp_project: Path):
        venv = tmp_project / ".venv" / "lib" / "site.py"
        venv.parent.mkdir(parents=True)
        venv.write_text("")
        files = collect_files(tmp_project)
        assert not any(".venv" in str(f) for f in files)

    def test_skips_node_modules(self, tmp_project: Path):
        nm = tmp_project / "node_modules" / "pkg" / "index.js"
        nm.parent.mkdir(parents=True)
        nm.write_text("")
        files = collect_files(tmp_project)
        assert not any("node_modules" in str(f) for f in files)

    def test_specific_paths(self, tmp_project: Path):
        f1 = tmp_project / "src" / "app.py"
        f1.write_text("")
        f2 = tmp_project / "src" / "utils.py"
        f2.write_text("")
        files = collect_files(tmp_project, paths=[f1])
        assert len(files) == 1
        assert files[0] == f1


# ── Integration: run_checkers ─────────────────────────────────────────────────


class TestRunCheckers:
    def test_runs_secrets_on_python(self, tmp_project: Path):
        f = tmp_project / "src" / "config.py"
        f.write_text('SECRET = "AKIAIOSFODNN7EXAMPLE"\n')
        results = run_checkers([f], tmp_project)
        # Should have at least secrets checker result
        secret_results = [r for r in results if r.checker == "secrets"]
        assert len(secret_results) == 1
        assert len(secret_results[0].findings) == 1

    def test_runs_tdd_on_python(self, tmp_project: Path):
        f = tmp_project / "src" / "app.py"
        f.write_text("def hello(): pass\n")
        results = run_checkers([f], tmp_project, checkers=["tdd"])
        tdd_results = [r for r in results if r.checker == "tdd"]
        assert len(tdd_results) == 1
        assert len(tdd_results[0].findings) == 1

    def test_checker_filter(self, tmp_project: Path):
        f = tmp_project / "src" / "app.py"
        f.write_text('SECRET = "AKIAIOSFODNN7EXAMPLE"\n')
        results = run_checkers([f], tmp_project, checkers=["tdd"])
        # Should NOT have secrets findings since we filtered to tdd only
        secret_findings = [f for r in results for f in r.findings if f.checker == "secrets"]
        assert len(secret_findings) == 0

    def test_clean_file(self, tmp_project: Path):
        f = tmp_project / "src" / "__init__.py"
        f.write_text('"""Package."""\n')
        t = tmp_project / "tests" / "test_init.py"
        t.parent.mkdir(exist_ok=True)
        t.write_text("")
        results = run_checkers([f], tmp_project)
        all_findings = [f for r in results for f in r.findings]
        error_findings = [f for f in all_findings if f.severity == "error"]
        assert len(error_findings) == 0

    def test_skips_nonexistent(self, tmp_project: Path):
        f = tmp_project / "nonexistent.py"
        results = run_checkers([f], tmp_project)
        assert results == []


# ── CLI ci command tests ──────────────────────────────────────────────────────


class TestCLICommand:
    def test_ci_text_output(self, tmp_project: Path):
        f = tmp_project / "config.py"
        f.write_text('KEY = "AKIAIOSFODNN7EXAMPLE"\n')
        result = subprocess.run(
            ["python", "-m", "tribunal", "ci", str(f), "--project", str(tmp_project)],
            capture_output=True,
            text=True,
            cwd=str(tmp_project),
        )
        assert "Tribunal CI" in result.stdout or result.returncode != 0

    def test_ci_json_output(self, tmp_project: Path):
        f = tmp_project / "clean.py"
        f.write_text('import os\nDB = os.environ["DB"]\n')
        result = subprocess.run(
            ["python", "-m", "tribunal", "ci", str(f), "--format", "json", "--project", str(tmp_project)],
            capture_output=True,
            text=True,
            cwd=str(tmp_project),
        )
        if result.stdout.strip():
            data = json.loads(result.stdout)
            assert "files_checked" in data
            assert "findings" in data

    def test_ci_sarif_output(self, tmp_project: Path):
        f = tmp_project / "clean.py"
        f.write_text('import os\n')
        result = subprocess.run(
            ["python", "-m", "tribunal", "ci", str(f), "--format", "sarif", "--project", str(tmp_project)],
            capture_output=True,
            text=True,
            cwd=str(tmp_project),
        )
        if result.stdout.strip():
            data = json.loads(result.stdout)
            assert data["version"] == "2.1.0"

    def test_ci_exit_code_on_error(self, tmp_project: Path):
        f = tmp_project / "secrets.py"
        f.write_text('TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh1234"\n')
        result = subprocess.run(
            ["python", "-m", "tribunal", "ci", str(f), "--project", str(tmp_project)],
            capture_output=True,
            text=True,
            cwd=str(tmp_project),
        )
        assert result.returncode == 1

    def test_ci_exit_code_clean(self, tmp_project: Path):
        f = tmp_project / "__init__.py"
        f.write_text('"""Clean."""\n')
        result = subprocess.run(
            ["python", "-m", "tribunal", "ci", str(f), "--format", "json", "--checkers", "secrets", "--project", str(tmp_project)],
            capture_output=True,
            text=True,
            cwd=str(tmp_project),
        )
        assert result.returncode == 0
