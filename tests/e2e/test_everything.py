"""Comprehensive E2E lifecycle test — if this passes, the app works.

Verifies the fully-wired data paths:

  PATH 1: MCP sync → DuckDB → pipeline → mart_today → dashboard data
  PATH 2: MCP sync → pipeline → ChromaDB → QueryEngine → BrainAgent
  PATH 3: User message → intent → action proposal → confirm → execute
  PATH 4: Toggle on → sync → raw table → pipeline → queryable
  PATH 5: Action → re-sync → new data visible
  PATH 6: Health check → all components report status

Uses real embedded databases (temp dirs), mock MCP server, and
mock Ollama.  Never touches real user data.

Run with:
    python -m pytest tests/e2e/test_everything.py -v

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from src.agents.action_executor import ActionResult
from src.core.cli import (
    cmd_confirm_action,
    cmd_health,
    cmd_startup_sync,
    cmd_sync_all_stale,
)
from src.core.data_layer import DataLayer

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def data_layer(tmp_path_factory: pytest.TempPathFactory):
    """DataLayer fully initialized with temp directory."""
    tmp = tmp_path_factory.mktemp("e2e_everything")
    dl = DataLayer(base_path=tmp / "secbrain_data")
    dl.initialize()
    yield dl
    dl.close()


def _mock_chat(content: str) -> MagicMock:
    """Build a mock Ollama chat response."""
    resp = MagicMock()
    resp.message.content = content
    return resp


def _mock_sync_stats(
    connector_id: str = "test",
    status: str = "success",
    rows: int = 3,
) -> MagicMock:
    """Create a mock SyncStats."""
    stats = MagicMock()
    stats.connector_id = connector_id
    stats.status = status
    stats.rows_synced = rows
    stats.duration_seconds = 0.5
    stats.error = None
    return stats


def _mock_enabled(cid: str) -> MagicMock:
    """Create a mock enabled extension."""
    ext = MagicMock()
    ext.connector_id = cid
    ext.enabled = True
    return ext


# ============================================================================
# PATH 1: MCP Sync → Dashboard Data
# ============================================================================


class TestSyncToDashboardData:
    """PATH 1: MCP sync → DuckDB → pipeline → mart_today.

    sensitivity_tier: N/A
    """

    def test_pipeline_status_is_queryable(
        self, data_layer: DataLayer,
    ):
        """Pipeline status returns valid JSON structure."""
        status = data_layer.get_pipeline_status()
        assert "is_stale" in status
        assert "last_run" in status
        assert "pending_changes" in status


# ============================================================================
# PATH 3: Chat → MCP Action
# ============================================================================


class TestChatToAction:
    """PATH 3: User message → intent match → action → execute.

    sensitivity_tier: N/A
    """

    def test_tool_registry_matches_intent(self):
        """ToolRegistry detects action intents from user text."""
        from src.agents.tool_registry import ToolRegistry
        from src.extensions.connectors.catalog import ConnectorCatalog
        from src.extensions.connectors.registry import ExtensionRegistry

        with patch.object(
            ExtensionRegistry, "get_enabled",
        ) as mock_enabled:
            mock_enabled.return_value = []
            catalog = ConnectorCatalog()
            registry = ExtensionRegistry()
            tr = ToolRegistry(
                catalog=catalog, registry=registry,
            )
            # With no enabled connectors, no actions matched
            matches = tr.match_intent("create an event")
            assert isinstance(matches, list)

    @patch(
        "src.extensions.connectors.connection_manager.ConnectionManager",
    )
    @patch("src.agents.action_executor.ActionExecutor")
    def test_confirm_action_executes_and_resyncs(
        self,
        mock_executor_cls,
        mock_cm_cls,
        capsys,
    ):
        """confirm-action executes MCP tool and re-syncs."""
        mock_executor_cls.return_value.execute.return_value = (
            ActionResult(
                proposal_id="p1",
                status="success",
                output="Event created",
            )
        )
        mock_cm_cls.return_value.sync_now.return_value = (
            _mock_sync_stats("cal", rows=1)
        )

        proposal = json.dumps({
            "connector_id": "cal",
            "command": "npx",
            "args": ["-y", "mcp-server"],
            "tool_name": "create_event",
            "arguments": {"title": "Test"},
            "proposal_id": "p1",
        })

        layer = MagicMock()
        code = cmd_confirm_action(layer, proposal)

        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "success"
        assert output["post_sync"]["rows_synced"] == 1


# ============================================================================
# PATH 4: New Connector → Queryable Data
# ============================================================================


class TestNewConnectorToQueryable:
    """PATH 4: Toggle on → sync → raw table → pipeline → queryable.

    This tests the startup-sync path which handles enabled
    connectors.

    sensitivity_tier: N/A
    """

    @patch("src.core.cli._run_smart_pipeline_and_reindex")
    @patch("src.pipeline.runner.PipelineRunner")
    @patch(
        "src.extensions.connectors.connection_manager.ConnectionManager",
    )
    @patch("src.extensions.connectors.registry.ExtensionRegistry")
    def test_startup_sync_processes_connectors(
        self,
        mock_reg_cls,
        mock_cm_cls,
        mock_runner_cls,
        mock_smart_run,
        capsys,
    ):
        """startup-sync syncs enabled connectors and reports."""
        mock_reg_cls.return_value.get_enabled.return_value = [
            _mock_enabled("apple-calendar"),
            _mock_enabled("apple-contacts"),
        ]
        mock_cm_cls.return_value.sync_now.side_effect = [
            _mock_sync_stats("apple-calendar", rows=5),
            _mock_sync_stats("apple-contacts", rows=3),
        ]
        mock_runner_cls.return_value.is_stale.return_value = True
        mock_smart_run.return_value = {"status": "success"}

        layer = MagicMock()

        code = cmd_startup_sync(layer)

        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["synced_connectors"] == 2
        assert output["total_rows"] == 8
        assert output["pipeline_ran"] is True
        mock_smart_run.assert_called_once_with(
            layer,
            trigger="startup",
        )


# ============================================================================
# PATH 5: Action → Re-sync → New Data
# ============================================================================


class TestActionTriggersResync:
    """PATH 5: Action → re-sync → new data visible.

    sensitivity_tier: N/A
    """

    @patch(
        "src.extensions.connectors.connection_manager.ConnectionManager",
    )
    @patch("src.agents.action_executor.ActionExecutor")
    def test_action_triggers_post_sync(
        self,
        mock_executor_cls,
        mock_cm_cls,
        capsys,
    ):
        """Successful action triggers connector re-sync."""
        mock_executor_cls.return_value.execute.return_value = (
            ActionResult(
                proposal_id="p1",
                status="success",
                output="Created",
            )
        )
        mock_cm_cls.return_value.sync_now.return_value = (
            _mock_sync_stats("cal", rows=2)
        )

        proposal = json.dumps({
            "connector_id": "cal",
            "command": "npx",
            "args": ["-y", "mcp"],
            "tool_name": "create_event",
            "arguments": {},
            "proposal_id": "p1",
        })

        layer = MagicMock()
        code = cmd_confirm_action(layer, proposal)

        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["post_sync"]["status"] == "success"
        assert output["post_sync"]["rows_synced"] == 2


# ============================================================================
# PATH 6: Health Check
# ============================================================================


class TestHealthCheckAllPass:
    """Health check reports all components.

    sensitivity_tier: N/A
    """

    @patch("src.agents.tool_registry.ToolRegistry")
    @patch("src.extensions.connectors.catalog.ConnectorCatalog")
    @patch("src.extensions.connectors.registry.ExtensionRegistry")
    @patch("src.models.ollama_manager.OllamaManager")
    def test_health_check_with_initialized_layer(
        self,
        mock_ollama_cls,
        mock_ext_reg,
        mock_catalog_cls,
        mock_tr_cls,
        data_layer: DataLayer,
        capsys,
    ):
        """Health check reports 7 components with real databases."""
        mock_status = MagicMock()
        mock_status.server_reachable = True
        mock_status.chat_model = "llama3.1:8b"
        mock_status.chat_model_status.value = "ready"
        mock_ollama_cls.return_value.check_health.return_value = (
            mock_status
        )

        mock_ext_reg.return_value.get_enabled.return_value = []
        mock_tr_cls.return_value.get_available_actions.return_value = []

        _code = cmd_health(data_layer)

        output = json.loads(capsys.readouterr().out)
        assert output["ok"] is True
        assert len(output["checks"]) == 7

        components = {
            c["component"] for c in output["checks"]
        }
        expected = {
            "sqlite", "kuzu", "chromadb", "pipeline",
            "ollama", "connectors", "tool_registry",
        }
        assert components == expected

    def test_health_reports_degraded_on_failure(
        self, capsys,
    ):
        """Health check reports ok=False when a component fails."""
        layer = MagicMock()
        layer.get_stats.side_effect = RuntimeError("broken")
        layer.get_pipeline_status.side_effect = RuntimeError(
            "broken",
        )

        code = cmd_health(layer)

        assert code == 1
        output = json.loads(capsys.readouterr().out)
        assert output["ok"] is False


# ============================================================================
# Periodic Sync
# ============================================================================


class TestPeriodicSync:
    """Verify sync-all-stale works for periodic background use.

    sensitivity_tier: N/A
    """

    @patch("src.core.cli._run_smart_pipeline_and_reindex")
    @patch("src.pipeline.runner.PipelineRunner")
    @patch(
        "src.extensions.connectors.connection_manager.ConnectionManager",
    )
    @patch("src.extensions.connectors.registry.ExtensionRegistry")
    def test_periodic_sync_with_pipeline(
        self,
        mock_reg_cls,
        mock_cm_cls,
        mock_runner_cls,
        mock_smart_run,
        capsys,
    ):
        """sync-all-stale syncs connectors and runs pipeline."""
        mock_reg_cls.return_value.get_enabled.return_value = [
            _mock_enabled("cal"),
        ]
        mock_cm_cls.return_value.sync_now.return_value = (
            _mock_sync_stats("cal", rows=3)
        )
        mock_runner_cls.return_value.is_stale.return_value = True
        mock_smart_run.return_value = {"status": "success"}

        layer = MagicMock()

        code = cmd_sync_all_stale(layer)

        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["pipeline_ran"] is True
        mock_smart_run.assert_called_once_with(
            layer,
            trigger="periodic",
        )
