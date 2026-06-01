"""Tests for agent_runner.py — discovery, manifest validation,
inline execution, status tracking."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from src.agent_runtime.runner import AgentLoadError, AgentRunner


def _write_manifest(agent_dir: Path, manifest: dict) -> None:
    """Write a manifest.yaml file to an agent directory."""
    import yaml

    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "manifest.yaml").write_text(
        yaml.dump(manifest, default_flow_style=False),
        encoding="utf-8",
    )


def _write_agent(agent_dir: Path, code: str) -> None:
    """Write an agent.py file to an agent directory."""
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent.py").write_text(code, encoding="utf-8")


_VALID_MANIFEST = {
    "id": "test-agent",
    "name": "Test Agent",
    "version": "1.0.0",
    "description": "A test agent",
    "author": "test",
    "max_sensitivity_tier": 1,
    "triggers": ["manual"],
}

_SIMPLE_AGENT_CODE = """\
from src.agent_runtime.base import BrainAgent
from src.agent_runtime.models import AgentResult

class TestAgent(BrainAgent):
    manifest = None  # loaded by runner

    def run(self, context):
        context.log("Hello from test agent")
        return AgentResult(
            agent_id="test-agent",
            status="success",
            output="test output",
        )
"""


# -----------------------------------------------------------------------
# discover_agents
# -----------------------------------------------------------------------


class TestDiscoverAgents:
    def test_finds_builtin_agent(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "builtin" / "test-agent"
        _write_manifest(agent_dir, _VALID_MANIFEST)
        _write_agent(agent_dir, _SIMPLE_AGENT_CODE)

        runner = AgentRunner(
            builtin_dir=tmp_path / "builtin",
            user_dir=tmp_path / "user",
        )
        manifests = runner.discover_agents()
        assert len(manifests) == 1
        assert manifests[0].id == "test-agent"

    def test_skips_invalid_manifest(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "builtin" / "bad-agent"
        agent_dir.mkdir(parents=True)
        # Write invalid manifest (missing required fields).
        (agent_dir / "manifest.yaml").write_text("invalid: true", encoding="utf-8")

        runner = AgentRunner(
            builtin_dir=tmp_path / "builtin",
            user_dir=tmp_path / "user",
        )
        manifests = runner.discover_agents()
        assert len(manifests) == 0

    def test_scans_both_builtin_and_user(self, tmp_path: Path) -> None:
        builtin_dir = tmp_path / "builtin" / "agent-a"
        _write_manifest(builtin_dir, {**_VALID_MANIFEST, "id": "agent-a"})
        _write_agent(builtin_dir, _SIMPLE_AGENT_CODE.replace("test-agent", "agent-a"))

        user_dir = tmp_path / "user" / "agent-b"
        _write_manifest(user_dir, {**_VALID_MANIFEST, "id": "agent-b"})
        _write_agent(user_dir, _SIMPLE_AGENT_CODE.replace("test-agent", "agent-b"))

        runner = AgentRunner(
            builtin_dir=tmp_path / "builtin",
            user_dir=tmp_path / "user",
        )
        manifests = runner.discover_agents()
        assert len(manifests) == 2


# -----------------------------------------------------------------------
# load_manifest
# -----------------------------------------------------------------------


class TestLoadManifest:
    def test_valid_manifest(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agent"
        _write_manifest(agent_dir, _VALID_MANIFEST)

        runner = AgentRunner(builtin_dir=tmp_path, user_dir=tmp_path)
        manifest = runner.load_manifest(agent_dir)
        assert manifest.id == "test-agent"
        assert manifest.max_sensitivity_tier == 1

    def test_missing_required_field(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agent"
        bad = {k: v for k, v in _VALID_MANIFEST.items() if k != "name"}
        _write_manifest(agent_dir, bad)

        runner = AgentRunner(builtin_dir=tmp_path, user_dir=tmp_path)
        with pytest.raises(AgentLoadError, match="name"):
            runner.load_manifest(agent_dir)

    def test_invalid_tier_range(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agent"
        _write_manifest(agent_dir, {**_VALID_MANIFEST, "max_sensitivity_tier": 5})

        runner = AgentRunner(builtin_dir=tmp_path, user_dir=tmp_path)
        with pytest.raises(AgentLoadError, match="1-3"):
            runner.load_manifest(agent_dir)

    def test_excessive_memory(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agent"
        _write_manifest(agent_dir, {**_VALID_MANIFEST, "memory_mb": 2048})

        runner = AgentRunner(builtin_dir=tmp_path, user_dir=tmp_path)
        with pytest.raises(AgentLoadError, match="memory_mb"):
            runner.load_manifest(agent_dir)

    def test_excessive_timeout(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agent"
        _write_manifest(agent_dir, {**_VALID_MANIFEST, "timeout_seconds": 600})

        runner = AgentRunner(builtin_dir=tmp_path, user_dir=tmp_path)
        with pytest.raises(AgentLoadError, match="timeout_seconds"):
            runner.load_manifest(agent_dir)

    def test_table_permissions_parsed(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agent"
        manifest_data = {
            **_VALID_MANIFEST,
            "tables": [
                {"table": "raw_messages", "max_tier": 2},
                {"table": "raw_notes", "max_tier": 1},
            ],
            "max_sensitivity_tier": 2,
        }
        _write_manifest(agent_dir, manifest_data)

        runner = AgentRunner(builtin_dir=tmp_path, user_dir=tmp_path)
        manifest = runner.load_manifest(agent_dir)
        assert len(manifest.tables) == 2
        assert manifest.tables[0].table == "raw_messages"
        assert manifest.tables[0].max_tier == 2


# -----------------------------------------------------------------------
# run_agent
# -----------------------------------------------------------------------


class TestRunAgent:
    def test_inline_execution_returns_result(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "builtin" / "test-agent"
        _write_manifest(agent_dir, _VALID_MANIFEST)
        _write_agent(agent_dir, _SIMPLE_AGENT_CODE)

        mock_db = MagicMock()
        runner = AgentRunner(
            db_engine=mock_db,
            builtin_dir=tmp_path / "builtin",
            user_dir=tmp_path / "user",
        )
        result = runner.run_agent("test-agent")
        assert result.status == "success"
        assert result.agent_id == "test-agent"
        assert result.duration_ms > 0

    def test_unknown_agent_returns_error(self, tmp_path: Path) -> None:
        runner = AgentRunner(
            builtin_dir=tmp_path / "builtin",
            user_dir=tmp_path / "user",
        )
        result = runner.run_agent("nonexistent")
        assert result.status == "error"
        assert "not found" in result.error

    def test_agent_error_returns_error_result(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "builtin" / "bad-agent"
        _write_manifest(agent_dir, {**_VALID_MANIFEST, "id": "bad-agent"})
        _write_agent(agent_dir, """\
from src.agent_runtime.base import BrainAgent
from src.agent_runtime.models import AgentResult

class BadAgent(BrainAgent):
    manifest = None

    def run(self, context):
        raise RuntimeError("Something broke")
""")

        mock_db = MagicMock()
        runner = AgentRunner(
            db_engine=mock_db,
            builtin_dir=tmp_path / "builtin",
            user_dir=tmp_path / "user",
        )
        result = runner.run_agent("bad-agent")
        assert result.status == "error"
        assert "Something broke" in result.error


# -----------------------------------------------------------------------
# list_agents / get_agent_result
# -----------------------------------------------------------------------


class TestListAgentsAndResults:
    def test_list_agents_includes_discovered(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "builtin" / "test-agent"
        _write_manifest(agent_dir, _VALID_MANIFEST)
        _write_agent(agent_dir, _SIMPLE_AGENT_CODE)

        runner = AgentRunner(
            builtin_dir=tmp_path / "builtin",
            user_dir=tmp_path / "user",
        )
        statuses = runner.list_agents()
        assert len(statuses) == 1
        assert statuses[0].agent_id == "test-agent"
        assert statuses[0].status == "idle"

    def test_get_agent_result_returns_last(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "builtin" / "test-agent"
        _write_manifest(agent_dir, _VALID_MANIFEST)
        _write_agent(agent_dir, _SIMPLE_AGENT_CODE)

        mock_db = MagicMock()
        runner = AgentRunner(
            db_engine=mock_db,
            builtin_dir=tmp_path / "builtin",
            user_dir=tmp_path / "user",
        )
        runner.run_agent("test-agent")
        result = runner.get_agent_result("test-agent")
        assert result is not None
        assert result.status == "success"

    def test_get_agent_result_returns_none_if_never_run(self) -> None:
        runner = AgentRunner(
            builtin_dir=Path("/nonexistent"),
            user_dir=Path("/nonexistent"),
        )
        assert runner.get_agent_result("nonexistent") is None
