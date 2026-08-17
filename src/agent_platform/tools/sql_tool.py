from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

from agent_platform.rag.ingestion.schema_context import JOIN_RELATIONSHIPS
from agent_platform.tools.sql_verifier import SQLSemanticVerifier, VerificationLevel


logger = logging.getLogger(__name__)


class SQLValidationError(ValueError):
    """Raised when SQL fails syntax, schema, relationship, or context validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class SQLSafetyError(SQLValidationError):
    """Raised when a query violates read-only execution policy."""


class SQLExecutionError(RuntimeError):
    """Raised when SQL execution fails after retries."""


@dataclass(slots=True)
class SQLValidationResult:
    sql: str
    tables: list[str]
    columns: list[str]


class SQLValidator:
    """Validate one read-only SQLite query against the live schema and allowed join graph."""

    BLOCKED_FUNCTIONS = {"load_extension", "readfile", "writefile"}

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        connection = sqlite3.connect(self.database_path)
        try:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            self.schema = {
                table: {row[1]: row[2] or "UNKNOWN" for row in connection.execute(f'PRAGMA table_info("{table}")')}
                for (table,) in tables
            }
        finally:
            connection.close()
        self.schema["sqlite_master"] = {
            "type": "TEXT", "name": "TEXT", "tbl_name": "TEXT", "rootpage": "INTEGER", "sql": "TEXT"
        }
        self.schema["sqlite_schema"] = self.schema["sqlite_master"]
        self.allowed_joins = {
            frozenset((f"{left}.{left_col}", f"{right}.{right_col}"))
            for left, left_col, right, right_col, _, _ in JOIN_RELATIONSHIPS
        }

    def validate(self, query: str, allowed_tables: set[str] | None = None) -> SQLValidationResult:
        normalized = query.strip().rstrip(";")
        if not normalized:
            raise SQLValidationError(["malformed_sql: SQL query cannot be empty"])
        try:
            statements = [statement for statement in sqlglot.parse(query, read="sqlite") if statement is not None]
        except ParseError as exc:
            raise SQLValidationError([f"malformed_sql: {exc}"]) from exc
        if len(statements) != 1:
            raise SQLSafetyError(["unsafe_sql: exactly one SQL statement is allowed"])
        expression = statements[0]
        if not isinstance(expression, exp.Query):
            raise SQLSafetyError(["unsafe_sql: only SELECT and WITH queries are allowed"])

        if isinstance(expression, exp.Select) and not expression.expressions:
            raise SQLValidationError(["malformed_sql: SELECT clause has no expressions"])

        blocked_functions = {
            function.name.lower()
            for function in expression.find_all(exp.Anonymous)
            if function.name.lower() in self.BLOCKED_FUNCTIONS
        }
        if blocked_functions:
            raise SQLSafetyError([f"unsafe_sql: blocked function(s): {', '.join(sorted(blocked_functions))}"])

        cte_names = {cte.alias_or_name.lower() for cte in expression.find_all(exp.CTE)}
        physical_tables = {
            table.name.lower()
            for table in expression.find_all(exp.Table)
            if table.name.lower() not in cte_names
        }
        errors = [
            f"nonexistent_table: {table}"
            for table in sorted(physical_tables - self.schema.keys())
        ]
        if allowed_tables is not None:
            context_allowed = {table.lower() for table in allowed_tables} | {"sqlite_master", "sqlite_schema"}
            errors.extend(
                f"table_not_in_context: {table}"
                for table in sorted(physical_tables - context_allowed)
            )
        if errors:
            raise SQLValidationError(errors)

        try:
            qualified = qualify(
                expression.copy(),
                schema=self.schema,
                dialect="sqlite",
                validate_qualify_columns=True,
                quote_identifiers=False,
                expand_stars=False,
            )
        except OptimizeError as exc:
            raise SQLValidationError([f"nonexistent_column: {exc}"]) from exc

        join_errors = self._validate_joins(qualified)
        if join_errors:
            raise SQLValidationError(join_errors)
        columns = sorted({
            f"{column.table}.{column.name}" if column.table else column.name
            for column in qualified.find_all(exp.Column)
        })
        return SQLValidationResult(normalized, sorted(physical_tables), columns)

    def _validate_joins(self, expression: exp.Expression) -> list[str]:
        errors = []
        for scope in traverse_scope(expression):
            aliases = {
                alias.lower(): source.name.lower()
                for alias, source in scope.sources.items()
                if isinstance(source, exp.Table) and source.name.lower() in self.schema
            }
            derived_aliases = {
                alias.lower() for alias, source in scope.sources.items() if not isinstance(source, exp.Table)
            }
            for join in scope.expression.args.get("joins") or []:
                if not isinstance(join.this, exp.Table):
                    continue
                target_alias = join.this.alias_or_name.lower()
                target_table = aliases.get(target_alias)
                if not target_table:
                    continue
                on = join.args.get("on")
                valid_relationship = False
                observed = []
                if on is not None:
                    for equality in on.find_all(exp.EQ):
                        left = next(equality.this.find_all(exp.Column), None)
                        right = next(equality.expression.find_all(exp.Column), None)
                        if left is None or right is None:
                            continue
                        left_table = aliases.get(left.table.lower())
                        right_table = aliases.get(right.table.lower())
                        if target_alias in {left.table.lower(), right.table.lower()} and (
                            {left.table.lower(), right.table.lower()} & derived_aliases
                        ):
                            valid_relationship = True
                            continue
                        if not left_table or not right_table or target_table not in {left_table, right_table}:
                            continue
                        endpoints = frozenset((f"{left_table}.{left.name.lower()}", f"{right_table}.{right.name.lower()}"))
                        observed.append(" = ".join(sorted(endpoints)))
                        if endpoints in self.allowed_joins or (
                            left_table == right_table and left.name.lower() == right.name.lower()
                        ):
                            valid_relationship = True
                if not valid_relationship:
                    predicate = ", ".join(observed) if observed else "missing ON relationship"
                    errors.append(f"invalid_join: {target_table} uses {predicate}")
        return errors


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
        enable_semantic_verification: bool = True,
    ) -> None:
        if not database_url.startswith("sqlite:///"):
            raise ValueError("This vertical slice supports sqlite:/// URLs. Keep the interface for PostgreSQL adapters.")
        self.database_url = database_url
        self.database_path = Path(database_url.replace("sqlite:///", "", 1))
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.validator = SQLValidator(self.database_path)
        self.verifier = SQLSemanticVerifier(str(self.database_path)) if enable_semantic_verification else None

    def execute(self, query: str, expected_result: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute SQL with semantic verification before running.
        
        Args:
            query: SQL query to execute
            expected_result: Optional expected result for semantic verification
        """
        normalized = self._validate_read_only(query)
        
        # Run semantic verification BEFORE execution
        if self.verifier and expected_result:
            verification = self.verifier.verify(normalized, expected_result=expected_result)
            if not verification.is_valid:
                # Log verification issues but don't block execution
                # The verification provides warnings that the LLM can use for self-correction
                logger.warning(
                    "sql_semantic_verification_issues",
                    extra={
                        "query": normalized,
                        "issues": [str(issue) for issue in verification.issues],
                    },
                )
        
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

    def validate(self, query: str, allowed_tables: set[str] | None = None) -> SQLValidationResult:
        return self.validator.validate(query, allowed_tables)

    def _validate_read_only(self, query: str) -> str:
        return self.validate(query).sql
