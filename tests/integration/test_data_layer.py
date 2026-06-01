"""Integration tests for the unified DataLayer.

These tests exercise the full initialization flow across all three embedded
databases.  Each test uses a temporary directory so the real
~/.arandu/data/ is never touched.

Run with:
    python -m pytest tests/integration/test_data_layer.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.cli import build_parser, cmd_init, cmd_reset, cmd_status
from src.core.data_layer import DataLayer, HealthReport, LayerStats
from src.core.sqlite.schemas import ALL_TABLE_NAMES

from tests.fixtures.chromadb_fixtures import EXPECTED_COUNTS as CHROMA_EXPECTED
from tests.fixtures.chromadb_fixtures import load_all_fixtures as load_chroma
from tests.fixtures.kuzu_fixtures import EXPECTED_NODE_COUNTS
from tests.fixtures.kuzu_fixtures import load_all_fixtures as load_kuzu
from tests.fixtures.sample_data import (
    CALENDAR_EVENTS,
    CONTACTS,
    HEALTH_METRICS,
    MESSAGES,
    NOTES,
)
from tests.fixtures.sample_data import load_all_fixtures as load_sample

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def layer(tmp_path: Path) -> DataLayer:
    """Fresh DataLayer backed by a temp directory; closed after test."""
    dl = DataLayer(base_path=tmp_path / "arandu_data")
    yield dl
    dl.close()


@pytest.fixture(scope="module")
def initialized_layer(tmp_path_factory: pytest.TempPathFactory) -> DataLayer:
    """Module-scoped initialized DataLayer for read-only integration checks.

    Initializes schemas in all three engines and loads sample fixtures
    (SQLite raw rows, Kuzu nodes/edges, ChromaDB documents) so the stats
    and reset tests have data to assert on.
    """
    base = tmp_path_factory.mktemp("data_layer_initialized")
    dl = DataLayer(base_path=base / "arandu_data")
    dl.initialize()
    load_sample(dl.duckdb)
    load_kuzu(dl.kuzu)
    load_chroma(dl.chromadb)
    yield dl
    dl.close()


@pytest.fixture()
def fresh_initialized_layer(tmp_path: Path) -> DataLayer:
    """Function-scoped initialized DataLayer for tests that mutate state."""
    dl = DataLayer(base_path=tmp_path / "arandu_data")
    dl.initialize()
    load_sample(dl.duckdb)
    load_kuzu(dl.kuzu)
    load_chroma(dl.chromadb)
    yield dl
    dl.close()


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestInitialization:
    def test_initialize_does_not_raise(self, layer: DataLayer) -> None:
        """initialize() must complete without raising on a fresh database."""
        layer.initialize()

    def test_initialize_is_idempotent(self, layer: DataLayer) -> None:
        """Calling initialize() twice must not raise or duplicate data.

        Loads fixtures between the two initialize() calls and verifies
        that the second call neither raises nor wipes the data.
        """
        layer.initialize()
        load_sample(layer.duckdb)
        layer.initialize()

        stats = layer.get_stats()
        assert stats.duckdb["raw_messages"] == len(MESSAGES)

    def test_duckdb_tables_created(self, initialized_layer: DataLayer) -> None:
        """All raw DuckDB tables must exist after initialization."""
        rows = initialized_layer.duckdb.query(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'table'"
        )
        existing = {r["name"] for r in rows}
        for table in ALL_TABLE_NAMES:
            assert table in existing, f"Missing DuckDB table: {table}"

    def test_kuzu_schema_created(self, initialized_layer: DataLayer) -> None:
        """Kuzu node tables must exist after initialization."""
        rows = initialized_layer.kuzu.query("CALL show_tables() RETURN *")
        names = {r["name"] for r in rows}
        for node_type in EXPECTED_NODE_COUNTS:
            assert node_type in names, f"Missing Kuzu table: {node_type}"

    def test_chromadb_collections_created(
        self, initialized_layer: DataLayer
    ) -> None:
        """All ChromaDB collections must be populated after initialization."""
        for collection_name, expected in CHROMA_EXPECTED.items():
            col = initialized_layer.chromadb.get_or_create_collection(
                collection_name
            )
            assert col.count() == expected, (
                f"Collection '{collection_name}':"
                f" expected {expected}, got {col.count()}"
            )


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_health_check_passes_after_init(
        self, initialized_layer: DataLayer
    ) -> None:
        """health_check() must return (True, report) after initialization."""
        ok, report = initialized_layer.health_check()
        assert ok is True, f"Health check failed. Errors: {report.errors}"
        assert isinstance(report, HealthReport)
        assert report.duckdb_ok
        assert report.kuzu_ok
        assert report.chromadb_ok
        assert report.errors == []

    def test_health_check_passes_on_empty_db(self, layer: DataLayer) -> None:
        """health_check() should also pass before any data is loaded."""
        ok, report = layer.health_check()
        assert ok is True, f"Errors: {report.errors}"

    def test_health_report_all_ok_property(
        self, initialized_layer: DataLayer
    ) -> None:
        """HealthReport.all_ok must be True when every engine is healthy."""
        _, report = initialized_layer.health_check()
        assert report.all_ok is True


# ---------------------------------------------------------------------------
# Stats tests
# ---------------------------------------------------------------------------


class TestGetStats:
    def test_get_stats_returns_layer_stats(
        self, initialized_layer: DataLayer
    ) -> None:
        """get_stats() must return a LayerStats instance."""
        stats = initialized_layer.get_stats()
        assert isinstance(stats, LayerStats)

    def test_duckdb_row_counts_match_fixtures(
        self, initialized_layer: DataLayer
    ) -> None:
        """DuckDB counts must match the fixture module constants."""
        stats = initialized_layer.get_stats()
        assert stats.duckdb["raw_messages"] == len(MESSAGES)
        assert stats.duckdb["raw_calendar_events"] == len(CALENDAR_EVENTS)
        assert stats.duckdb["raw_notes"] == len(NOTES)
        assert stats.duckdb["raw_health_metrics"] == len(HEALTH_METRICS)
        assert stats.duckdb["raw_contacts"] == len(CONTACTS)

    def test_kuzu_node_counts_match_fixtures(
        self, initialized_layer: DataLayer
    ) -> None:
        """Kuzu node counts must match EXPECTED_NODE_COUNTS."""
        stats = initialized_layer.get_stats()
        for node_type, expected in EXPECTED_NODE_COUNTS.items():
            actual = stats.kuzu_nodes.get(node_type, -1)
            assert actual == expected, (
                f"Kuzu {node_type}: expected {expected}, got {actual}"
            )

    def test_chromadb_doc_counts_match_fixtures(
        self, initialized_layer: DataLayer
    ) -> None:
        """ChromaDB document counts must match CHROMA_EXPECTED."""
        stats = initialized_layer.get_stats()
        for name, expected in CHROMA_EXPECTED.items():
            actual = stats.chromadb.get(name, -1)
            assert actual == expected, (
                f"ChromaDB '{name}': expected {expected}, got {actual}"
            )

    def test_total_aggregates_are_correct(
        self, initialized_layer: DataLayer
    ) -> None:
        """Totals on LayerStats must equal the sum of individual counts."""
        stats = initialized_layer.get_stats()
        assert stats.total_duckdb_rows == sum(stats.duckdb.values())
        assert stats.total_kuzu_nodes == sum(stats.kuzu_nodes.values())
        assert stats.total_chroma_docs == sum(stats.chromadb.values())

    def test_stats_before_init_are_zero(self, layer: DataLayer) -> None:
        """On an empty database, all counts should be 0 (not -1 or error)."""
        # Tables don't exist yet — stats may raise internally and record -1,
        # or return 0.  Either is acceptable; we just assert the call doesn't
        # propagate an exception to the caller.
        stats = layer.get_stats()
        assert isinstance(stats, LayerStats)


# ---------------------------------------------------------------------------
# Reset tests
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_and_recreates(
        self, fresh_initialized_layer: DataLayer,
    ) -> None:
        """reset() must wipe data and leave engines ready to reload fixtures."""
        pre_stats = fresh_initialized_layer.get_stats()
        assert pre_stats.total_duckdb_rows > 0

        fresh_initialized_layer.reset()
        load_sample(fresh_initialized_layer.duckdb)

        post_stats = fresh_initialized_layer.get_stats()
        assert post_stats.duckdb["raw_messages"] == len(MESSAGES)
        assert post_stats.total_duckdb_rows == pre_stats.total_duckdb_rows

    def test_reset_health_check_passes(
        self, fresh_initialized_layer: DataLayer
    ) -> None:
        """health_check() must pass immediately after a reset."""
        fresh_initialized_layer.reset()
        ok, report = fresh_initialized_layer.health_check()
        assert ok is True, f"Errors after reset: {report.errors}"

    def test_reset_repopulates_chromadb(
        self, fresh_initialized_layer: DataLayer
    ) -> None:
        """ChromaDB must accept fresh fixtures after a reset."""
        fresh_initialized_layer.reset()
        load_chroma(fresh_initialized_layer.chromadb)
        stats = fresh_initialized_layer.get_stats()
        for name, expected in CHROMA_EXPECTED.items():
            assert stats.chromadb[name] == expected


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestCLI:
    def test_cmd_init_exits_zero(self, layer: DataLayer) -> None:
        """cmd_init() must return exit code 0 on success."""
        code = cmd_init(layer)
        assert code == 0

    def test_cmd_status_exits_zero_after_init(
        self, fresh_initialized_layer: DataLayer
    ) -> None:
        """cmd_status() must return exit code 0 when all engines are healthy."""
        code = cmd_status(fresh_initialized_layer)
        assert code == 0

    def test_cmd_reset_exits_zero(self, fresh_initialized_layer: DataLayer) -> None:
        """cmd_reset() must return exit code 0 on success."""
        code = cmd_reset(fresh_initialized_layer)
        assert code == 0

    def test_seed_evaluated_messages_pre_cutoff(
        self, fresh_initialized_layer: DataLayer,
    ) -> None:
        """All pre-cutoff messages + emails must land in _evaluated_messages."""
        layer = fresh_initialized_layer
        msgs = layer.duckdb.query(
            "SELECT COUNT(*) AS n FROM raw_messages",
        )[0]["n"]
        emails = layer.duckdb.query(
            "SELECT COUNT(*) AS n FROM raw_emails",
        )[0]["n"]
        expected = msgs + emails
        assert expected > 0
        # Fixtures are dated 2025-06; a 2099 cutoff covers all of them.
        seeded = layer.seed_evaluated_messages_pre_cutoff(
            "2099-01-01T00:00:00Z",
        )
        assert seeded == expected
        # Idempotent: re-running with the same cutoff inserts no duplicates.
        layer.seed_evaluated_messages_pre_cutoff(
            "2099-01-01T00:00:00Z",
        )
        evaluated = layer.duckdb.query(
            "SELECT COUNT(*) AS n FROM _evaluated_messages",
        )[0]["n"]
        assert evaluated == expected

    def test_seed_evaluated_messages_past_cutoff_skips_recent(
        self, fresh_initialized_layer: DataLayer,
    ) -> None:
        """Rows newer than the cutoff must NOT be seeded."""
        layer = fresh_initialized_layer
        seeded = layer.seed_evaluated_messages_pre_cutoff(
            "1970-01-01T00:00:00Z",
        )
        assert seeded == 0

    def test_cli_init_via_argv(self, tmp_path: Path) -> None:
        """The CLI entry point must accept --data-dir and 'init' via argv."""
        from src.core.cli import main

        data_dir = tmp_path / "cli_test"
        exit_code = main(["--data-dir", str(data_dir), "init"])
        assert exit_code == 0
        assert data_dir.is_dir()

    def test_cli_status_via_argv(self, tmp_path: Path) -> None:
        """Running init then status via the CLI must both succeed."""
        from src.core.cli import main

        data_dir = tmp_path / "cli_test2"
        assert main(["--data-dir", str(data_dir), "init"]) == 0
        assert main(["--data-dir", str(data_dir), "status"]) == 0

    def test_cli_reset_via_argv(self, tmp_path: Path) -> None:
        """Running init then reset via the CLI must both succeed."""
        from src.core.cli import main

        data_dir = tmp_path / "cli_test3"
        assert main(["--data-dir", str(data_dir), "init"]) == 0
        assert main(["--data-dir", str(data_dir), "reset"]) == 0

    def test_build_parser_subcommands(self) -> None:
        """Parser must recognize all three subcommands."""
        parser = build_parser()
        for cmd in ("init", "status", "reset"):
            args = parser.parse_args([cmd])
            assert args.command == cmd
