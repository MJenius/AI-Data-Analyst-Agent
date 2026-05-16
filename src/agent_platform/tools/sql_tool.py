from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from time import perf_counter
from typing import Any


logger = logging.getLogger(__name__)


class SQLSafetyError(ValueError):
    """Raised when a query violates read-only execution policy."""


class SQLExecutionError(RuntimeError):
    """Raised when SQL execution fails after retries."""


class SQLTool:
    """Read-only SQL execution tool with validation, timing, and query logging."""

    BLOCKED_KEYWORDS = {
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "truncate",
        "replace",
        "attach",
        "detach",
        "vacuum",
        "pragma",
    }

    def __init__(
        self,
        database_url: str,
        timeout_seconds: float = 5.0,
        max_retries: int = 1,
    ) -> None:
        if not database_url.startswith("sqlite:///"):
            raise ValueError("This vertical slice supports sqlite:/// URLs. Keep the interface for PostgreSQL adapters.")
        self.database_url = database_url
        self.database_path = Path(database_url.replace("sqlite:///", "", 1))
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def execute(self, query: str) -> dict[str, Any]:
        normalized = self._validate_read_only(query)
        attempt = 0
        last_error: Exception | None = None
        while attempt <= self.max_retries:
            try:
                return self._execute_once(normalized)
            except sqlite3.Error as error:
                last_error = error
                attempt += 1
                logger.warning("sql_query_retry", extra={"attempt": attempt, "query": normalized})
        raise SQLExecutionError(str(last_error))

    def introspect_schema(self) -> dict[str, list[dict[str, str]]]:
        connection = sqlite3.connect(self.database_path)
        try:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            schema: dict[str, list[dict[str, str]]] = {}
            for (table,) in tables:
                columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
                schema[table] = [
                    {"name": row[1], "type": row[2], "nullable": str(not bool(row[3]))}
                    for row in columns
                ]
            return schema
        finally:
            connection.close()

    def _execute_once(self, query: str) -> dict[str, Any]:
        started = perf_counter()
        logger.info("sql_query_started", extra={"query": query})
        connection = sqlite3.connect(self.database_path, timeout=self.timeout_seconds)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            cursor = connection.execute(query)
            rows = [dict(row) for row in cursor.fetchall()]
        finally:
            connection.close()
        elapsed_ms = round((perf_counter() - started) * 1000, 3)
        logger.info(
            "sql_query_completed",
            extra={"query": query, "row_count": len(rows), "execution_time_ms": elapsed_ms},
        )
        return {
            "query": query,
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": elapsed_ms,
        }

    def _validate_read_only(self, query: str) -> str:
        normalized = query.strip().rstrip(";")
        if not normalized:
            raise SQLSafetyError("SQL query cannot be empty.")
        if ";" in normalized:
            raise SQLSafetyError("Only one SQL statement is allowed.")
        first_word = normalized.split(maxsplit=1)[0].lower()
        if first_word not in {"select", "with"}:
            raise SQLSafetyError("Only SELECT and WITH queries are allowed.")
        tokens = set(re.findall(r"[a-zA-Z_]+", normalized.lower()))
        blocked = tokens & self.BLOCKED_KEYWORDS
        if blocked:
            raise SQLSafetyError(f"Blocked read-write SQL keyword(s): {', '.join(sorted(blocked))}.")
        return normalized
