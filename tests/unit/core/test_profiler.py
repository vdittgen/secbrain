"""Unit tests for the profiler module.

Tests the @timed decorator, PerformanceLog class, timed_block
context manager, and report generation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.core.profiler import (
    PerfEntry,
    PerformanceLog,
    timed,
    timed_block,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Ensure each test starts with a fresh singleton."""
    PerformanceLog.reset()
    yield  # type: ignore[misc]
    PerformanceLog.reset()


@pytest.fixture()
def tmp_log(tmp_path: Path) -> PerformanceLog:
    """Return a PerformanceLog backed by a temp file."""
    log_path = tmp_path / "perf_log.jsonl"
    perf = PerformanceLog(log_path=log_path)
    PerformanceLog._instance = perf
    return perf


# ------------------------------------------------------------------
# PerfEntry
# ------------------------------------------------------------------


class TestPerfEntry:
    def test_frozen_dataclass(self) -> None:
        entry = PerfEntry(
            operation="test.op",
            duration_ms=42.5,
            timestamp="2025-01-01T00:00:00",
        )
        assert entry.operation == "test.op"
        assert entry.duration_ms == 42.5
        assert entry.data_size_hint is None

    def test_with_size_hint(self) -> None:
        entry = PerfEntry(
            operation="test.op",
            duration_ms=10.0,
            timestamp="2025-01-01T00:00:00",
            data_size_hint=100,
        )
        assert entry.data_size_hint == 100


# ------------------------------------------------------------------
# PerformanceLog
# ------------------------------------------------------------------


class TestPerformanceLog:
    def test_record_writes_to_file(
        self, tmp_log: PerformanceLog
    ) -> None:
        entry = PerfEntry(
            operation="db.query",
            duration_ms=5.5,
            timestamp="2025-06-01T12:00:00",
            data_size_hint=10,
        )
        tmp_log.record(entry)

        assert len(tmp_log.entries) == 1
        assert tmp_log._log_path.exists()

        content = tmp_log._log_path.read_text().strip()
        data = json.loads(content)
        assert data["operation"] == "db.query"
        assert data["duration_ms"] == 5.5
        assert data["data_size_hint"] == 10

    def test_load_from_disk(
        self, tmp_log: PerformanceLog
    ) -> None:
        for i in range(3):
            tmp_log.record(
                PerfEntry(
                    operation=f"op_{i}",
                    duration_ms=float(i),
                    timestamp="2025-01-01T00:00:00",
                )
            )

        fresh = PerformanceLog(log_path=tmp_log._log_path)
        assert len(fresh.entries) == 0

        fresh.load_from_disk()
        assert len(fresh.entries) == 3
        assert fresh.entries[0].operation == "op_0"

    def test_clear_removes_entries_and_file(
        self, tmp_log: PerformanceLog
    ) -> None:
        tmp_log.record(
            PerfEntry(
                operation="test",
                duration_ms=1.0,
                timestamp="2025-01-01T00:00:00",
            )
        )
        assert tmp_log._log_path.exists()

        tmp_log.clear()
        assert len(tmp_log.entries) == 0
        assert not tmp_log._log_path.exists()

    def test_report_empty(
        self, tmp_log: PerformanceLog
    ) -> None:
        assert "No performance data" in tmp_log.report()

    def test_report_with_data(
        self, tmp_log: PerformanceLog
    ) -> None:
        tmp_log.record(
            PerfEntry("fast_op", 1.0, "2025-01-01T00:00:00"),
        )
        tmp_log.record(
            PerfEntry("slow_op", 100.0, "2025-01-01T00:00:00"),
        )
        tmp_log.record(
            PerfEntry("slow_op", 150.0, "2025-01-01T00:00:00"),
        )

        report = tmp_log.report()
        assert "slow_op" in report
        assert "fast_op" in report
        assert "TOP 5 BOTTLENECKS" in report
        # slow_op should appear first (highest max)
        assert report.index("slow_op") < report.index("fast_op")

    def test_report_loads_from_disk_when_empty(
        self, tmp_log: PerformanceLog
    ) -> None:
        tmp_log.record(
            PerfEntry("disk_op", 5.0, "2025-01-01T00:00:00"),
        )
        # Create a fresh log pointing to the same file
        fresh = PerformanceLog(log_path=tmp_log._log_path)
        PerformanceLog._instance = fresh
        report = fresh.report()
        assert "disk_op" in report

    def test_singleton_pattern(self, tmp_path: Path) -> None:
        log_path = tmp_path / "singleton.jsonl"
        log1 = PerformanceLog.get(log_path=log_path)
        log2 = PerformanceLog.get()
        assert log1 is log2

        PerformanceLog.reset()
        log3 = PerformanceLog.get(log_path=log_path)
        assert log3 is not log1


# ------------------------------------------------------------------
# @timed decorator
# ------------------------------------------------------------------


class TestTimedDecorator:
    def test_records_entry(
        self, tmp_log: PerformanceLog
    ) -> None:
        @timed()
        def my_func() -> str:
            return "hello"

        result = my_func()
        assert result == "hello"
        assert len(tmp_log.entries) == 1
        assert "my_func" in tmp_log.entries[0].operation

    def test_custom_operation_name(
        self, tmp_log: PerformanceLog
    ) -> None:
        @timed("custom.name")
        def my_func() -> list:
            return [1, 2, 3]

        result = my_func()
        assert result == [1, 2, 3]
        assert tmp_log.entries[0].operation == "custom.name"
        assert tmp_log.entries[0].data_size_hint == 3

    def test_size_hint_for_list_return(
        self, tmp_log: PerformanceLog
    ) -> None:
        @timed()
        def get_items() -> list:
            return [1, 2, 3, 4, 5]

        get_items()
        assert tmp_log.entries[0].data_size_hint == 5

    def test_size_hint_none_for_non_list(
        self, tmp_log: PerformanceLog
    ) -> None:
        @timed()
        def void_fn() -> None:
            pass

        void_fn()
        assert tmp_log.entries[0].data_size_hint is None

    def test_method_name_detection(
        self, tmp_log: PerformanceLog
    ) -> None:
        class MyClass:
            @timed()
            def my_method(self) -> list:
                return [1]

        obj = MyClass()
        obj.my_method()
        assert tmp_log.entries[0].operation == "MyClass.my_method"

    def test_preserves_exceptions(
        self, tmp_log: PerformanceLog
    ) -> None:
        @timed()
        def failing() -> None:
            msg = "boom"
            raise ValueError(msg)

        with pytest.raises(ValueError, match="boom"):
            failing()
        # Entry IS recorded even when function raises
        assert len(tmp_log.entries) == 1
        assert tmp_log.entries[0].data_size_hint is None

    def test_measures_positive_duration(
        self, tmp_log: PerformanceLog
    ) -> None:
        @timed()
        def slow_fn() -> int:
            total = 0
            for i in range(10_000):
                total += i
            return total

        slow_fn()
        assert tmp_log.entries[0].duration_ms >= 0

    def test_dict_size_hint(
        self, tmp_log: PerformanceLog
    ) -> None:
        @timed()
        def get_map() -> dict:
            return {"a": 1, "b": 2}

        get_map()
        assert tmp_log.entries[0].data_size_hint == 2


# ------------------------------------------------------------------
# timed_block context manager
# ------------------------------------------------------------------


class TestTimedBlock:
    def test_records_block(
        self, tmp_log: PerformanceLog
    ) -> None:
        with timed_block("test.block"):
            _ = sum(range(100))

        assert len(tmp_log.entries) == 1
        assert tmp_log.entries[0].operation == "test.block"
        assert tmp_log.entries[0].duration_ms >= 0

    def test_with_size_hint(
        self, tmp_log: PerformanceLog
    ) -> None:
        with timed_block("test.block", data_size_hint=42):
            pass

        assert tmp_log.entries[0].data_size_hint == 42

    def test_multiple_blocks(
        self, tmp_log: PerformanceLog
    ) -> None:
        with timed_block("block_a"):
            pass
        with timed_block("block_b"):
            pass

        assert len(tmp_log.entries) == 2
        ops = [e.operation for e in tmp_log.entries]
        assert ops == ["block_a", "block_b"]


# ------------------------------------------------------------------
# JSONL format
# ------------------------------------------------------------------


class TestJsonlFormat:
    def test_multiple_entries_one_per_line(
        self, tmp_log: PerformanceLog
    ) -> None:
        for i in range(5):
            tmp_log.record(
                PerfEntry(
                    operation=f"op_{i}",
                    duration_ms=float(i),
                    timestamp="2025-01-01T00:00:00",
                )
            )

        lines = tmp_log._log_path.read_text().strip().split("\n")
        assert len(lines) == 5
        for line in lines:
            data = json.loads(line)
            assert "operation" in data
            assert "duration_ms" in data
            assert "timestamp" in data

    def test_duration_rounded_to_2_decimals(
        self, tmp_log: PerformanceLog
    ) -> None:
        tmp_log.record(
            PerfEntry(
                operation="test",
                duration_ms=1.23456789,
                timestamp="2025-01-01T00:00:00",
            )
        )
        content = tmp_log._log_path.read_text().strip()
        data = json.loads(content)
        assert data["duration_ms"] == 1.23
