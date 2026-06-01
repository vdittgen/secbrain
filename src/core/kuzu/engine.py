"""Kuzu embedded graph database engine for Arandu.

Provides a single-connection graph engine with persistent storage at
~/.arandu/data/kuzu_db/.

sensitivity_tier: infrastructure layer — no user data stored here.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import kuzu

from src.core.profiler import timed

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".arandu" / "data" / "kuzu_db"


class GraphEngine:
    """Embedded Kuzu graph engine backed by a persistent on-disk database.

    Uses a single long-lived connection. Kuzu allows multiple read-only
    handles to coexist with at most one read-write handle; long-running
    processes that only need to query the graph (the WhatsApp listener
    serving BrainAgent reply context, ``ask``/``ask-stream`` chat) should
    open with ``read_only=True`` so they do not block each other or the
    pipeline writer.

    sensitivity_tier: N/A (infrastructure layer — no user data stored here)
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        *,
        read_only: bool = False,
    ) -> None:
        """Initialize the engine and open (or create) the Kuzu database.

        Args:
            db_path: Directory path for persistent Kuzu storage.
                     Created automatically if it does not exist.
            read_only: When True, open Kuzu in shared read-only mode so
                multiple processes can query concurrently. Required for
                long-running query-only consumers; write callers must
                leave this False.
        """
        self._db_path = db_path
        self._read_only = read_only
        # Kuzu creates the database directory itself; pre-creating it causes a
        # RuntimeError ("path cannot be a directory").  We only ensure the
        # *parent* exists so that the path is reachable.
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: kuzu.Database = kuzu.Database(
            str(self._db_path), read_only=read_only,
        )
        self._conn: kuzu.Connection = kuzu.Connection(self._db)
        logger.info(
            "Kuzu graph DB opened: %s (read_only=%s)",
            self._db_path, read_only,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @timed()
    def execute(self, cypher: str, parameters: dict[str, Any] | None = None) -> None:
        """Execute a Cypher statement that returns no meaningful rows (DDL / DML).

        Args:
            cypher: Cypher query to execute.
            parameters: Optional named parameters for the query.
        """
        if parameters:
            self._conn.execute(cypher, parameters)
        else:
            self._conn.execute(cypher)

    @timed()
    def query(
        self, cypher: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a Cypher query and return all rows as a list of dicts.

        Column names are taken directly from the result set so callers get
        clean, aliased names when the query uses ``RETURN n.id AS id``.

        Args:
            cypher: Cypher query to execute.
            parameters: Optional named parameters for the query.

        Returns:
            List of dicts mapping column name -> value for every result row.
        """
        if parameters:
            result = self._conn.execute(cypher, parameters)
        else:
            result = self._conn.execute(cypher)

        columns = result.get_column_names()
        rows: list[dict[str, Any]] = []
        while result.has_next():
            rows.append(dict(zip(columns, result.get_next())))
        return rows

    def close(self) -> None:
        """Release the connection and database handles."""
        # Kuzu does not expose an explicit close(); releasing references
        # triggers cleanup via the C++ destructor.
        del self._conn
        del self._db
        logger.info("Kuzu graph DB closed: %s", self._db_path)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> GraphEngine:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
