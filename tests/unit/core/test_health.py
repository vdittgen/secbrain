"""Tests for the ``health`` CLI command.

Verifies that ``cmd_health`` checks every major component and
produces the expected JSON output.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.core.cli import cmd_health


def _make_layer_stub() -> MagicMock:
    """Create a minimal DataLayer mock with healthy stats."""
    layer = MagicMock()

    # get_stats
    stats = MagicMock()
    stats.sqlite = {"raw_messages": 10, "raw_notes": 5}
    stats.total_sqlite_rows = 15
    stats.kuzu_nodes = {"Person": 3}
    stats.total_kuzu_nodes = 3
    stats.chromadb = {"personal": 8}
    stats.total_chroma_docs = 8
    layer.get_stats.return_value = stats

    # get_pipeline_status
    layer.get_pipeline_status.return_value = {
        "is_stale": False,
        "last_run": {"status": "success"},
    }

    return layer


class TestCmdHealth:
    """Tests for the health check command.

    sensitivity_tier: N/A
    """

    @patch("src.agents.tool_registry.ToolRegistry")
    @patch("src.extensions.connectors.catalog.ConnectorCatalog")
    @patch("src.extensions.connectors.registry.ExtensionRegistry")
    @patch("src.models.ollama_manager.OllamaManager")
    def test_all_healthy(
        self,
        mock_ollama_cls,
        mock_ext_reg,
        mock_catalog_cls,
        mock_tr_cls,
        capsys,
    ):
        """All components healthy produces ok=True."""
        layer = _make_layer_stub()

        # Ollama
        mock_status = MagicMock()
        mock_status.server_reachable = True
        mock_status.chat_model = "llama3.1:8b"
        mock_status.chat_model_status.value = "ready"
        mock_ollama_cls.return_value.check_health.return_value = (
            mock_status
        )

        # Registry
        mock_ext_reg.return_value.get_enabled.return_value = [
            MagicMock(connector_id="cal"),
        ]

        # Tool registry
        mock_tr_cls.return_value.get_available_actions.return_value = [
            MagicMock(),
        ]

        code = cmd_health(layer)
        assert code == 0

        output = json.loads(capsys.readouterr().out)
        assert output["ok"] is True
        assert len(output["checks"]) == 7

        components = [c["component"] for c in output["checks"]]
        assert "sqlite" in components
        assert "kuzu" in components
        assert "chromadb" in components
        assert "pipeline" in components
        assert "ollama" in components
        assert "connectors" in components
        assert "tool_registry" in components

    def test_sqlite_failure_degrades(self, capsys):
        """SQLite failure marks overall ok=False."""
        layer = MagicMock()
        layer.get_stats.side_effect = RuntimeError("DB locked")
        layer.get_pipeline_status.return_value = {
            "is_stale": True,
            "last_run": None,
        }

        code = cmd_health(layer)
        assert code == 1

        output = json.loads(capsys.readouterr().out)
        assert output["ok"] is False
        sqlite_check = next(
            c for c in output["checks"]
            if c["component"] == "sqlite"
        )
        assert sqlite_check["ok"] is False
        assert "DB locked" in sqlite_check["error"]

    @patch("src.models.ollama_manager.OllamaManager")
    @patch("src.extensions.connectors.registry.ExtensionRegistry")
    def test_ollama_down_degrades(
        self,
        mock_ext_reg,
        mock_ollama_cls,
        capsys,
    ):
        """Ollama being unreachable marks ok=False."""
        layer = _make_layer_stub()

        mock_status = MagicMock()
        mock_status.server_reachable = False
        mock_status.chat_model = "llama3.1:8b"
        mock_status.chat_model_status.value = "not_found"
        mock_ollama_cls.return_value.check_health.return_value = (
            mock_status
        )

        mock_ext_reg.return_value.get_enabled.return_value = []

        code = cmd_health(layer)
        assert code == 1

        output = json.loads(capsys.readouterr().out)
        assert output["ok"] is False
        ollama_check = next(
            c for c in output["checks"]
            if c["component"] == "ollama"
        )
        assert ollama_check["ok"] is False

    def test_output_json_format(self, capsys):
        """Output is valid JSON with expected schema."""
        layer = MagicMock()
        layer.get_stats.side_effect = RuntimeError("fail")
        layer.get_pipeline_status.side_effect = RuntimeError("fail")

        cmd_health(layer)

        output = json.loads(capsys.readouterr().out)
        assert "ok" in output
        assert "checks" in output
        assert isinstance(output["checks"], list)
        for check in output["checks"]:
            assert "component" in check
            assert "ok" in check
