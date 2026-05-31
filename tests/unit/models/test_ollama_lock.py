"""Unit tests for the single-lock Ollama serialization.

Verifies that all callers share one lock file, same-tier callers
serialize, and timeout raises correctly.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import src.models.ollama_lock as lock_mod
from src.models.ollama_lock import ollama_lock


class TestSingleLock:
    """All priorities share a single lock file."""

    def test_same_lock_serializes(
        self, tmp_path: Path,
    ) -> None:
        """Two callers of any priority should serialize."""
        with patch.object(
            lock_mod, "_LOCK_PATH", tmp_path / "test.lock",
        ):
            lock_held = threading.Event()
            lock_release = threading.Event()
            second_completed = threading.Event()

            def hold_lock() -> None:
                with ollama_lock(priority="background"):
                    lock_held.set()
                    lock_release.wait(timeout=10)

            def try_second_lock() -> None:
                with ollama_lock(
                    priority="interactive", timeout=5,
                ):
                    second_completed.set()

            first = threading.Thread(
                target=hold_lock, daemon=True,
            )
            first.start()
            lock_held.wait(timeout=5)

            second = threading.Thread(
                target=try_second_lock, daemon=True,
            )
            second.start()

            # Second should NOT complete while first holds the lock
            time.sleep(0.3)
            assert not second_completed.is_set(), (
                "Second caller should be blocked by first"
            )

            # Release first lock — second should complete
            lock_release.set()
            completed = second_completed.wait(timeout=5)
            assert completed, (
                "Second caller should complete after release"
            )

            first.join(timeout=5)
            second.join(timeout=5)

    def test_timeout_raises(
        self, tmp_path: Path,
    ) -> None:
        """Lock acquisition should raise TimeoutError."""
        with patch.object(
            lock_mod, "_LOCK_PATH", tmp_path / "test.lock",
        ):
            lock_held = threading.Event()
            lock_release = threading.Event()

            def hold_lock() -> None:
                with ollama_lock(priority="interactive"):
                    lock_held.set()
                    lock_release.wait(timeout=10)

            holder = threading.Thread(
                target=hold_lock, daemon=True,
            )
            holder.start()
            lock_held.wait(timeout=5)

            timed_out = False
            try:
                with ollama_lock(
                    priority="interactive", timeout=0.5,
                ):
                    pass
            except TimeoutError:
                timed_out = True

            assert timed_out, "Should have raised TimeoutError"

            lock_release.set()
            holder.join(timeout=5)


def _mock_ollama_modules() -> dict[str, object]:
    """Build a sys.modules patch dict that stubs out ``ollama``."""
    from unittest.mock import MagicMock
    return {"ollama": MagicMock()}


class TestOllamaProviderKeepAlive:
    """Verify _resolve_keep_alive picks the right value based on contention.

    keep_alive moved from a static attribute set in ``__init__`` to a
    dynamic decision in ``_resolve_keep_alive()`` so contention can be
    re-evaluated on every call.  The interactive vs background
    distinction now only affects lock priority and wall timeout; the
    keep_alive choice itself depends only on whether another caller is
    currently waiting on the Ollama lock.
    """

    @patch.dict("sys.modules", _mock_ollama_modules())
    def test_returns_none_when_no_contention(self) -> None:
        from src.models.llm_provider import OllamaProvider
        provider = OllamaProvider(background=False)
        with patch(
            "src.models.ollama_lock.has_lock_contention", return_value=False,
        ):
            assert provider._resolve_keep_alive() is None  # noqa: SLF001

    @patch.dict("sys.modules", _mock_ollama_modules())
    def test_returns_5m_under_contention(self) -> None:
        from src.models.llm_provider import OllamaProvider
        provider = OllamaProvider(background=True)
        with patch(
            "src.models.ollama_lock.has_lock_contention", return_value=True,
        ):
            assert provider._resolve_keep_alive() == "5m"  # noqa: SLF001
