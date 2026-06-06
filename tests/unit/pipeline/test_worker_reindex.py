"""Tests for pipeline worker ChromaDB re-indexing integration.

Verifies that the pipeline worker calls incremental_index after a
successful pipeline run and gracefully handles indexing failures.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.pipeline.worker import _reindex_chromadb, cmd_run


class TestReindexChromadb:
    """Tests for the _reindex_chromadb helper function.

    sensitivity_tier: N/A
    """

    @patch("src.pipeline.worker._emit_json")
    @patch("src.core.chromadb.indexer.Indexer")
    @patch("src.core.chromadb.engine.VectorEngine")
    def test_emits_reindex_complete_on_success(
        self, mock_vector_cls, mock_indexer_cls, mock_emit,
    ):
        """Successful re-index emits reindex_complete event."""
        mock_vector_cls.return_value.embedding_mismatch_message.return_value = (
            None
        )
        mock_indexer = MagicMock()
        mock_indexer.incremental_index.return_value = {
            "personal": 5, "work": 3,
        }
        mock_indexer_cls.return_value = mock_indexer

        db = MagicMock()
        since = datetime(2025, 6, 1, tzinfo=timezone.utc)
        status, error = _reindex_chromadb(db, since)

        assert status == "success"
        assert error is None
        mock_indexer.incremental_index.assert_called_once_with(
            since=since,
        )

        # Should emit starting + complete
        calls = mock_emit.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0]["type"] == "reindexing"
        assert calls[1][0][0]["type"] == "reindex_complete"
        assert calls[1][0][0]["counts"] == {
            "personal": 5, "work": 3,
        }

    @patch("src.pipeline.worker._emit_json")
    @patch("src.core.chromadb.indexer.Indexer")
    @patch("src.core.chromadb.engine.VectorEngine")
    def test_emits_reindex_error_on_failure(
        self, mock_vector_cls, mock_indexer_cls, mock_emit,
    ):
        """Indexing failure emits reindex_error but does not raise."""
        mock_vector_cls.return_value.embedding_mismatch_message.return_value = (
            None
        )
        mock_indexer = MagicMock()
        mock_indexer.incremental_index.side_effect = RuntimeError(
            "ChromaDB unavailable",
        )
        mock_indexer_cls.return_value = mock_indexer

        db = MagicMock()
        since = datetime(2025, 6, 1, tzinfo=timezone.utc)

        # Should NOT raise
        status, error = _reindex_chromadb(db, since)

        assert status == "error"
        assert "ChromaDB unavailable" in error
        calls = mock_emit.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0]["type"] == "reindexing"
        assert calls[1][0][0]["type"] == "reindex_error"
        assert "ChromaDB unavailable" in calls[1][0][0]["error"]

    @patch("src.pipeline.worker._emit_json")
    @patch("src.core.chromadb.indexer.Indexer")
    @patch("src.core.chromadb.engine.VectorEngine")
    def test_creates_indexer_with_db_and_chroma(
        self, mock_vector_cls, mock_indexer_cls, mock_emit,
    ):
        """Indexer is created with provided db and a new VectorEngine."""
        mock_indexer_cls.return_value.incremental_index.return_value = {}
        mock_chroma = MagicMock()
        mock_chroma.embedding_mismatch_message.return_value = None
        mock_vector_cls.return_value = mock_chroma

        db = MagicMock()
        _reindex_chromadb(db, datetime.now(tz=timezone.utc))

        mock_indexer_cls.assert_called_once_with(
            duckdb=db, chromadb=mock_chroma,
        )


class TestCmdRunReindex:
    """Tests for cmd_run's re-indexing integration.

    sensitivity_tier: N/A
    """

    @patch("src.pipeline.worker._maybe_notify_pipeline")
    @patch("src.pipeline.worker._reindex_kuzu")
    @patch("src.pipeline.worker._reindex_chromadb")
    @patch("src.core.sqlite.engine.DatabaseEngine")
    @patch("src.pipeline.stats.ProcessingStats")
    @patch("src.pipeline.runner.PipelineRunner")
    def test_calls_reindex_on_success(
        self, mock_runner_cls, mock_stats_cls, mock_db_cls,
        mock_reindex, mock_reindex_kuzu, mock_notify,
    ):
        """cmd_run calls _reindex_chromadb when pipeline succeeds."""
        mock_reindex.return_value = ("success", None)
        mock_reindex_kuzu.return_value = ("success", None)
        mock_run = MagicMock()
        mock_run.status = "success"
        mock_run.started_at = datetime(
            2025, 6, 1, tzinfo=timezone.utc,
        )
        mock_runner_cls.return_value.run.return_value = mock_run

        result = cmd_run("manual")

        assert result == 0
        mock_reindex.assert_called_once_with(
            mock_db_cls.return_value,
            mock_run.started_at,
        )
        # The run record is patched with the re-index outcome.
        mock_stats_cls.return_value.update_index_status.assert_called_once()

    @patch("src.pipeline.worker._reindex_chromadb")
    @patch("src.core.sqlite.engine.DatabaseEngine")
    @patch("src.pipeline.stats.ProcessingStats")
    @patch("src.pipeline.runner.PipelineRunner")
    def test_skips_reindex_on_failure(
        self, mock_runner_cls, mock_stats_cls, mock_db_cls,
        mock_reindex,
    ):
        """cmd_run skips re-indexing when pipeline fails."""
        mock_run = MagicMock()
        mock_run.status = "failed"
        mock_runner_cls.return_value.run.return_value = mock_run

        result = cmd_run("manual")

        assert result == 1
        mock_reindex.assert_not_called()

    @patch("src.pipeline.worker._reindex_chromadb")
    @patch("src.core.sqlite.engine.DatabaseEngine")
    @patch("src.pipeline.stats.ProcessingStats")
    @patch("src.pipeline.runner.PipelineRunner")
    def test_skips_reindex_on_cancelled(
        self, mock_runner_cls, mock_stats_cls, mock_db_cls,
        mock_reindex,
    ):
        """cmd_run skips re-indexing when pipeline is cancelled."""
        mock_run = MagicMock()
        mock_run.status = "cancelled"
        mock_runner_cls.return_value.run.return_value = mock_run

        result = cmd_run("manual")

        assert result == 2
        mock_reindex.assert_not_called()
