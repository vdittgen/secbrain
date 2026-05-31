"""Tests for startup-sync, sync-all-stale, and confirm-action re-sync.

Verifies the CLI commands that wire together the sync lifecycle:
startup sync, periodic background sync, and post-action re-sync.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.agents.action_executor import ActionResult
from src.core.cli import (
    cmd_confirm_action,
    cmd_startup_sync,
    cmd_sync_all_stale,
)

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def _make_sync_stats(
    connector_id: str = "test",
    status: str = "success",
    rows: int = 5,
    error: str | None = None,
) -> MagicMock:
    """Create a mock SyncStats."""
    stats = MagicMock()
    stats.connector_id = connector_id
    stats.status = status
    stats.rows_synced = rows
    stats.duration_seconds = 1.0
    stats.error = error
    return stats


def _enabled_ext(cid: str) -> MagicMock:
    """Create a mock RegisteredExtension."""
    ext = MagicMock()
    ext.connector_id = cid
    ext.enabled = True
    return ext


# -------------------------------------------------------------------
# TestCmdStartupSync
# -------------------------------------------------------------------


class TestCmdStartupSync:
    """Tests for cmd_startup_sync.

    sensitivity_tier: N/A
    """

    @patch("src.pipeline.runner.PipelineRunner")
    @patch("src.extensions.connectors.connection_manager.ConnectionManager")
    @patch("src.extensions.connectors.registry.ExtensionRegistry")
    def test_syncs_enabled_connectors(
        self,
        mock_reg_cls,
        mock_cm_cls,
        mock_runner_cls,
        capsys,
    ):
        """Syncs all enabled connectors and reports counts."""
        mock_reg_cls.return_value.get_enabled.return_value = [
            _enabled_ext("cal"),
            _enabled_ext("contacts"),
        ]
        mock_cm_cls.return_value.sync_now.side_effect = [
            _make_sync_stats("cal", rows=10),
            _make_sync_stats("contacts", rows=0),
        ]
        mock_runner_cls.return_value.is_stale.return_value = False

        layer = MagicMock()
        code = cmd_startup_sync(layer)

        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["synced_connectors"] == 1  # only cal had rows
        assert output["total_rows"] == 10
        assert output["pipeline_ran"] is False

    @patch("src.core.cli._run_smart_pipeline_and_reindex")
    @patch("src.pipeline.runner.PipelineRunner")
    @patch("src.extensions.connectors.connection_manager.ConnectionManager")
    @patch("src.extensions.connectors.registry.ExtensionRegistry")
    def test_runs_pipeline_when_stale(
        self,
        mock_reg_cls,
        mock_cm_cls,
        mock_runner_cls,
        mock_smart_run,
        capsys,
    ):
        """Runs smart pipeline+reindex when data is stale after syncs.

        Pipeline reuses the caller's DataLayer — opening a second writer
        in the same process causes a SQLite self-deadlock.
        """
        mock_reg_cls.return_value.get_enabled.return_value = [
            _enabled_ext("cal"),
        ]
        mock_cm_cls.return_value.sync_now.return_value = (
            _make_sync_stats("cal", rows=5)
        )
        mock_runner_cls.return_value.is_stale.return_value = True
        mock_smart_run.return_value = {"status": "success"}

        layer = MagicMock()

        code = cmd_startup_sync(layer)

        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["pipeline_ran"] is True
        mock_smart_run.assert_called_once_with(
            layer,
            trigger="startup",
        )

    @patch("src.pipeline.runner.PipelineRunner")
    @patch("src.extensions.connectors.connection_manager.ConnectionManager")
    @patch("src.extensions.connectors.registry.ExtensionRegistry")
    def test_handles_sync_failure_gracefully(
        self,
        mock_reg_cls,
        mock_cm_cls,
        mock_runner_cls,
        capsys,
    ):
        """Connector sync failure is captured but doesn't abort."""
        mock_reg_cls.return_value.get_enabled.return_value = [
            _enabled_ext("broken"),
        ]
        mock_cm_cls.return_value.sync_now.side_effect = (
            RuntimeError("MCP timeout")
        )
        mock_runner_cls.return_value.is_stale.return_value = False

        layer = MagicMock()
        code = cmd_startup_sync(layer)

        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["synced_connectors"] == 0
        assert len(output["errors"]) == 1
        assert "MCP timeout" in output["errors"][0]

    @patch("src.pipeline.runner.PipelineRunner")
    @patch("src.extensions.connectors.connection_manager.ConnectionManager")
    @patch("src.extensions.connectors.registry.ExtensionRegistry")
    def test_no_enabled_connectors(
        self,
        mock_reg_cls,
        mock_cm_cls,
        mock_runner_cls,
        capsys,
    ):
        """No enabled connectors produces empty success."""
        mock_reg_cls.return_value.get_enabled.return_value = []
        mock_runner_cls.return_value.is_stale.return_value = False

        layer = MagicMock()
        code = cmd_startup_sync(layer)

        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["synced_connectors"] == 0
        assert output["total_rows"] == 0


# -------------------------------------------------------------------
# TestCmdSyncAllStale
# -------------------------------------------------------------------


class TestCmdSyncAllStale:
    """Tests for cmd_sync_all_stale.

    sensitivity_tier: N/A
    """

    @patch("src.core.cli._run_smart_pipeline_and_reindex")
    @patch("src.pipeline.runner.PipelineRunner")
    @patch("src.extensions.connectors.connection_manager.ConnectionManager")
    @patch("src.extensions.connectors.registry.ExtensionRegistry")
    def test_syncs_and_runs_pipeline_if_new_data(
        self,
        mock_reg_cls,
        mock_cm_cls,
        mock_runner_cls,
        mock_smart_run,
        capsys,
    ):
        """Pipeline runs when stale after periodic sync.

        Pipeline reuses the caller's DataLayer — opening a second writer
        in the same process causes a SQLite self-deadlock.
        """
        mock_reg_cls.return_value.get_enabled.return_value = [
            _enabled_ext("cal"),
        ]
        mock_cm_cls.return_value.sync_now.return_value = (
            _make_sync_stats("cal", rows=3)
        )
        mock_runner_cls.return_value.is_stale.return_value = True
        mock_smart_run.return_value = {"status": "success"}

        layer = MagicMock()

        code = cmd_sync_all_stale(layer)

        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["total_rows"] == 3
        assert output["pipeline_ran"] is True
        assert len(output["connectors"]) == 1
        mock_smart_run.assert_called_once_with(
            layer,
            trigger="periodic",
        )

    @patch("src.core.cli._run_smart_pipeline_and_reindex")
    @patch("src.pipeline.runner.PipelineRunner")
    @patch("src.extensions.connectors.connection_manager.ConnectionManager")
    @patch("src.extensions.connectors.registry.ExtensionRegistry")
    def test_skips_pipeline_when_not_stale(
        self,
        mock_reg_cls,
        mock_cm_cls,
        mock_runner_cls,
        mock_smart_run,
        capsys,
    ):
        """Pipeline is skipped when not stale."""
        mock_reg_cls.return_value.get_enabled.return_value = [
            _enabled_ext("cal"),
        ]
        mock_cm_cls.return_value.sync_now.return_value = (
            _make_sync_stats("cal", rows=0)
        )
        mock_runner_cls.return_value.is_stale.return_value = False

        layer = MagicMock()
        code = cmd_sync_all_stale(layer)

        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["pipeline_ran"] is False
        mock_smart_run.assert_not_called()

    @patch("src.pipeline.runner.PipelineRunner")
    @patch("src.extensions.connectors.connection_manager.ConnectionManager")
    @patch("src.extensions.connectors.registry.ExtensionRegistry")
    def test_captures_per_connector_errors(
        self,
        mock_reg_cls,
        mock_cm_cls,
        mock_runner_cls,
        capsys,
    ):
        """Per-connector errors are captured in results array."""
        mock_reg_cls.return_value.get_enabled.return_value = [
            _enabled_ext("broken"),
        ]
        mock_cm_cls.return_value.sync_now.side_effect = (
            RuntimeError("timeout")
        )
        mock_runner_cls.return_value.is_stale.return_value = False

        layer = MagicMock()
        code = cmd_sync_all_stale(layer)

        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["connectors"][0]["status"] == "error"
        assert "timeout" in output["connectors"][0]["error"]


# -------------------------------------------------------------------
# TestCmdConfirmActionResync
# -------------------------------------------------------------------


class TestCmdConfirmActionResync:
    """Tests for post-action re-sync in cmd_confirm_action.

    sensitivity_tier: N/A
    """

    @patch(
        "src.extensions.connectors.connection_manager.ConnectionManager",
    )
    @patch("src.agents.action_executor.ActionExecutor")
    def test_resyncs_connector_on_success(
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
                output="Event created",
            )
        )

        mock_cm_cls.return_value.sync_now.return_value = (
            _make_sync_stats("cal", rows=1)
        )

        proposal = json.dumps({
            "connector_id": "cal",
            "command": "npx",
            "args": ["-y", "mcp-server"],
            "tool_name": "create_event",
            "arguments": {"title": "Meeting"},
            "proposal_id": "p1",
        })

        layer = MagicMock()
        code = cmd_confirm_action(layer, proposal)

        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["post_sync"]["status"] == "success"
        assert output["post_sync"]["rows_synced"] == 1

    @patch("src.agents.action_executor.ActionExecutor")
    def test_skips_resync_on_action_failure(
        self,
        mock_executor_cls,
        capsys,
    ):
        """Failed action does not trigger re-sync."""
        mock_executor_cls.return_value.execute.return_value = (
            ActionResult(
                proposal_id="p1",
                status="error",
                output="",
                error="MCP failed",
            )
        )

        proposal = json.dumps({
            "connector_id": "cal",
            "command": "npx",
            "args": ["-y", "mcp-server"],
            "tool_name": "create_event",
            "arguments": {},
            "proposal_id": "p1",
        })

        layer = MagicMock()
        code = cmd_confirm_action(layer, proposal)

        assert code == 1
        output = json.loads(capsys.readouterr().out)
        assert "post_sync" not in output

    @patch(
        "src.extensions.connectors.connection_manager.ConnectionManager",
    )
    @patch("src.agents.action_executor.ActionExecutor")
    def test_resync_failure_does_not_fail_action(
        self,
        mock_executor_cls,
        mock_cm_cls,
        capsys,
    ):
        """Re-sync error is captured but action still reported ok."""
        mock_executor_cls.return_value.execute.return_value = (
            ActionResult(
                proposal_id="p1",
                status="success",
                output="Event created",
            )
        )

        mock_cm_cls.return_value.sync_now.side_effect = (
            RuntimeError("MCP died")
        )

        proposal = json.dumps({
            "connector_id": "cal",
            "command": "npx",
            "args": ["-y", "mcp-server"],
            "tool_name": "create_event",
            "arguments": {},
            "proposal_id": "p1",
        })

        layer = MagicMock()
        code = cmd_confirm_action(layer, proposal)

        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["post_sync"]["status"] == "error"
        assert "MCP died" in output["post_sync"]["error"]


# -------------------------------------------------------------------
# TestRecordOutboundEmail
# -------------------------------------------------------------------


class TestRecordOutboundEmail:
    """Tests for ``_record_outbound_email`` synthetic Sent insert.

    sensitivity_tier: N/A
    """

    def _make_layer(self, tmp_path):
        """Build a layer-like object with a real SQLite engine."""
        from src.core.sqlite.engine import DatabaseEngine

        db_path = tmp_path / "outbound.sqlite"
        engine = DatabaseEngine(db_path=db_path)
        # Real raw_emails schema (mirror migrations.RAW_EMAILS).
        engine.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_emails (
                id              TEXT PRIMARY KEY,
                source          TEXT NOT NULL DEFAULT 'unknown',
                message_id      TEXT,
                subject         TEXT,
                from_address    TEXT,
                to_addresses    TEXT,
                date            TEXT,
                body_preview    TEXT,
                is_read         INTEGER DEFAULT 0,
                folder          TEXT,
                labels          TEXT,
                sensitivity_tier INTEGER NOT NULL DEFAULT 2,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """,
        )
        layer = MagicMock()
        layer.duckdb = engine
        return layer, engine

    def test_writes_sent_row(self, tmp_path):
        """A successful send writes a Sent-folder row to raw_emails."""
        from src.core import cli as cli_mod

        layer, engine = self._make_layer(tmp_path)
        # Reset module-level user-email cache so the test is hermetic.
        cli_mod._USER_EMAIL_CACHE = None
        cli_mod._USER_EMAIL_RESOLVED = False
        try:
            cli_mod._record_outbound_email(
                engine,
                arguments={
                    "to": "elmara@example.com",
                    "subject": "Re: watering plants",
                    "body": "Yes, twice a week.",
                },
            )
        finally:
            cli_mod._USER_EMAIL_CACHE = None
            cli_mod._USER_EMAIL_RESOLVED = False

        rows = engine.query("SELECT * FROM raw_emails")
        assert len(rows) == 1
        row = rows[0]
        assert row["folder"] == "Sent"
        assert row["is_read"] == 1
        assert row["subject"] == "Re: watering plants"
        assert "elmara@example.com" in row["to_addresses"]

    def test_missing_to_is_noop(self, tmp_path):
        """No ``to`` address → no row written, no exception."""
        from src.core import cli as cli_mod

        layer, engine = self._make_layer(tmp_path)
        cli_mod._USER_EMAIL_CACHE = None
        cli_mod._USER_EMAIL_RESOLVED = False
        try:
            cli_mod._record_outbound_email(
                engine,
                arguments={"to": "", "subject": "x"},
            )
        finally:
            cli_mod._USER_EMAIL_CACHE = None
            cli_mod._USER_EMAIL_RESOLVED = False

        rows = engine.query("SELECT * FROM raw_emails")
        assert rows == []

    @patch("src.agents.action_executor.ActionExecutor")
    def test_apple_mail_send_triggers_writeback_and_sweep(
        self,
        mock_executor_cls,
        tmp_path,
        capsys,
    ):
        """End-to-end: apple-mail send_email confirms write-back + sweep."""
        from src.core import cli as cli_mod
        from src.core.sqlite.engine import DatabaseEngine

        db_path = tmp_path / "confirm.sqlite"
        engine = DatabaseEngine(db_path=db_path)
        engine.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_emails (
                id TEXT PRIMARY KEY,
                source TEXT,
                message_id TEXT,
                subject TEXT,
                from_address TEXT,
                to_addresses TEXT,
                date TEXT,
                body_preview TEXT,
                is_read INTEGER DEFAULT 0,
                folder TEXT,
                labels TEXT,
                sensitivity_tier INTEGER DEFAULT 2,
                created_at TEXT
            )
            """,
        )
        # Inbound email and pending reply that should be dismissed.
        engine.execute(
            """
            INSERT INTO raw_emails
            (id, source, from_address, to_addresses, date, is_read, folder)
            VALUES (
                'email-in', 'apple_mail',
                'Elmara <elmara@example.com>',
                '["me@example.com"]',
                datetime('now', '-3 hours'),
                0, 'INBOX'
            )
            """,
        )

        mock_executor_cls.return_value.execute.return_value = (
            ActionResult(
                proposal_id="p1",
                status="success",
                output="Email sent",
            )
        )

        proposal = json.dumps({
            "connector_id": "apple-mail",
            "command": "python3",
            "args": ["-m", "src.extensions.bridges.apple.server"],
            "tool_name": "send_email",
            "arguments": {
                "to": "elmara@example.com",
                "subject": "Re: watering plants",
                "body": "Twice a week.",
            },
            "proposal_id": "p1",
        })

        layer = MagicMock()
        layer.duckdb = engine

        cli_mod._USER_EMAIL_CACHE = None
        cli_mod._USER_EMAIL_RESOLVED = False

        # Stub out the connector re-sync (we don't need it here) and the
        # notification side-effect to keep the test hermetic.
        with patch(
            "src.extensions.connectors.connection_manager."
            "ConnectionManager",
        ) as mock_cm_cls, patch(
            "src.core.cli._maybe_notify_action",
        ):
            mock_cm_cls.return_value.sync_now.return_value = (
                _make_sync_stats("apple-mail", rows=0)
            )

            # Seed pending reply *after* the engine is built — needs
            # the _pending_replies table created by ProactiveIntelligence.
            from src.agents.proactive import ProactiveIntelligence
            ProactiveIntelligence(db_engine=engine)
            engine.execute(
                """
                INSERT INTO _pending_replies
                (id, message_id, source, contact_name, domain,
                 preview, importance, reason, message_at, detected_at)
                VALUES
                ('pr-elmara', 'email-in', 'gmail', 'Elmara', 'personal',
                 'Asked about watering plants', 7,
                 'direct question',
                 datetime('now', '-3 hours'),
                 datetime('now', '-2 hours'))
                """,
            )

            code = cmd_confirm_action(layer, proposal)

        cli_mod._USER_EMAIL_CACHE = None
        cli_mod._USER_EMAIL_RESOLVED = False

        assert code == 0
        # A Sent row was written.
        sent_rows = engine.query(
            "SELECT id FROM raw_emails WHERE folder = 'Sent'",
        )
        assert len(sent_rows) == 1
        # The pending reply was dismissed by the post-send sweep.
        active = engine.query(
            "SELECT id FROM _pending_replies WHERE dismissed_at IS NULL",
        )
        assert active == []
