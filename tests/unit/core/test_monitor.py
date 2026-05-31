"""Unit tests for the memory monitor module.

Tests memory and disk usage reporting with temporary directories.
"""

from __future__ import annotations

from pathlib import Path

from src.core.monitor import (
    MemoryReport,
    format_report,
    get_memory_usage,
)


class TestGetMemoryUsage:
    def test_report_has_rss(self, tmp_path: Path) -> None:
        """Report should include a non-negative RSS value."""
        report = get_memory_usage(data_dir=tmp_path)
        assert isinstance(report.rss_mb, float)
        assert report.rss_mb >= 0

    def test_db_sizes_with_empty_dir(self, tmp_path: Path) -> None:
        """DB sizes should be zero for an empty data directory."""
        report = get_memory_usage(data_dir=tmp_path)
        for size in report.db_sizes_mb.values():
            assert size == 0.0
        assert report.total_db_mb == 0.0

    def test_db_sizes_with_files(self, tmp_path: Path) -> None:
        """DB sizes should reflect actual file sizes."""
        # Create a fake DuckDB file
        db_file = tmp_path / "secbrain.duckdb"
        db_file.write_bytes(b"x" * 1024 * 1024)  # 1 MB

        report = get_memory_usage(data_dir=tmp_path)
        assert report.db_sizes_mb["duckdb"] >= 0.9
        assert report.total_db_mb >= 0.9

    def test_no_warning_under_threshold(self, tmp_path: Path) -> None:
        """No warning should be set when usage is below threshold."""
        report = get_memory_usage(data_dir=tmp_path)
        assert report.warning is None

    def test_warning_reports_include_all_dbs(self, tmp_path: Path) -> None:
        """Report should include entries for all three databases."""
        report = get_memory_usage(data_dir=tmp_path)
        assert "duckdb" in report.db_sizes_mb
        assert "kuzu" in report.db_sizes_mb
        assert "chromadb" in report.db_sizes_mb


class TestFormatReport:
    def test_serializable_dict(self) -> None:
        """format_report should return a JSON-serializable dict."""
        report = MemoryReport(
            rss_mb=100.5,
            db_sizes_mb={"duckdb": 50.0, "kuzu": 20.0, "chromadb": 10.0},
            total_db_mb=80.0,
            warning=None,
        )
        result = format_report(report)
        assert isinstance(result, dict)
        assert result["rss_mb"] == 100.5
        assert result["total_db_mb"] == 80.0
        assert result["warning"] is None

    def test_warning_included(self) -> None:
        """Warning string should be included when set."""
        report = MemoryReport(
            rss_mb=1500.0,
            db_sizes_mb={"duckdb": 600.0},
            total_db_mb=600.0,
            warning="Total exceeds threshold",
        )
        result = format_report(report)
        assert result["warning"] == "Total exceeds threshold"
