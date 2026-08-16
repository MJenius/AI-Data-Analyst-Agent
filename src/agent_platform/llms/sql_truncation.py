"""SQL truncation and completeness detection utilities.

Phase 7 addition: detect incomplete/truncated SQL before attempting validation
or execution, so repair can receive an actionable signal instead of trying to
fix fundamentally malformed SQL.
"""

from __future__ import annotations

import re


def is_sql_truncated(sql: str | None) -> tuple[bool, str | None]:
    """Check if SQL appears truncated or incomplete.
    
    Returns (is_truncated, reason) where reason is None if SQL is complete.
    
    Truncation indicators:
    - Unbalanced parentheses
    - CTE (WITH clause) without final SELECT
    - Incomplete statement markers (..., [truncated], etc.)
    - Ends mid-keyword or mid-expression
    - Unbalanced quotes
    """
    if not sql:
        return True, "SQL is empty or None"
    
    sql_stripped = sql.strip()
    if not sql_stripped:
        return True, "SQL is whitespace-only"
    
    # Check for explicit truncation markers
    if any(marker in sql_stripped.lower() for marker in ["[truncated", "...", "[incomplete"]):
        return True, "SQL contains explicit truncation marker"
    
    # Check for unbalanced parentheses
    open_count = sql_stripped.count('(')
    close_count = sql_stripped.count(')')
    if open_count != close_count:
        return True, f"Unbalanced parentheses (open={open_count}, close={close_count})"
    
    # Check for unbalanced quotes (single and double)
    single_quotes = len([c for c in sql_stripped if c == "'" and not _is_escaped(sql_stripped, sql_stripped.index(c))])
    double_quotes = len([c for c in sql_stripped if c == '"' and not _is_escaped(sql_stripped, sql_stripped.index(c))])
    if single_quotes % 2 != 0:
        return True, "Unbalanced single quotes"
    if double_quotes % 2 != 0:
        return True, "Unbalanced double quotes"
    
    # Check for CTE without SELECT
    sql_upper = sql_stripped.upper()
    if sql_upper.startswith('WITH '):
        # Must contain at least one SELECT after the CTE definition
        # Look for SELECT that's not inside a subquery of the CTE itself
        # Simplified check: must have SELECT after final closing paren of CTE
        cte_pattern = re.compile(r'\bWITH\b.*?\)\s*(,\s*\w+\s+AS\s*\(.*?\))*\s*SELECT\b', re.IGNORECASE | re.DOTALL)
        if not cte_pattern.search(sql_stripped):
            return True, "CTE (WITH clause) missing final SELECT statement"
    
    # Check if SQL ends mid-statement
    # Common incomplete endings: ends with comma, operator, incomplete keyword
    last_tokens = sql_stripped.split()[-3:] if sql_stripped.split() else []
    incomplete_endings = {
        ',', 'AND', 'OR', 'JOIN', 'ON', 'WHERE', 'GROUP', 'ORDER', 'HAVING', 
        'UNION', 'INTERSECT', 'EXCEPT', 'FROM', 'AS', 'IN', 'BY', 'LIMIT',
        'OFFSET', 'SET', '=', '>', '<', '+', '-', '*', '/'
    }
    if last_tokens:
        last_token = last_tokens[-1].rstrip(';').upper()
        if last_token in incomplete_endings:
            return True, f"SQL ends with incomplete keyword/operator: {last_token}"
    
    # Check for SELECT without FROM (likely truncated, except for simple constant selects)
    if sql_upper.startswith('SELECT '):
        # If there's a comma at the end, likely truncated column list
        if sql_stripped.rstrip(';').endswith(','):
            return True, "SELECT statement ends with trailing comma"
        # More sophisticated: check if SELECT has FROM
        # Allow simple cases like "SELECT 1" or "SELECT COUNT(*)"
        select_from_pattern = re.compile(r'\bSELECT\b.*?\bFROM\b', re.IGNORECASE | re.DOTALL)
        if not select_from_pattern.search(sql_stripped) and ',' in sql_stripped:
            # Multi-column SELECT without FROM is likely truncated
            return True, "Multi-column SELECT statement missing FROM clause"
    
    # Check for incomplete GROUP BY / ORDER BY
    if 'GROUP BY' in sql_upper:
        # GROUP BY must be followed by at least one column expression
        group_by_pattern = re.compile(r'\bGROUP\s+BY\s+(\w+|\d+)', re.IGNORECASE)
        if not group_by_pattern.search(sql_stripped):
            return True, "GROUP BY clause has no column expression"
    
    if 'ORDER BY' in sql_upper:
        order_by_pattern = re.compile(r'\bORDER\s+BY\s+(\w+|\d+)', re.IGNORECASE)
        if not order_by_pattern.search(sql_stripped):
            return True, "ORDER BY clause has no column expression"
    
    # SQL appears complete
    return False, None


def _is_escaped(text: str, index: int) -> bool:
    """Check if character at index is escaped by backslash."""
    if index == 0:
        return False
    count = 0
    i = index - 1
    while i >= 0 and text[i] == '\\':
        count += 1
        i -= 1
    return count % 2 == 1


def extract_complete_statements(sql: str | None) -> list[str]:
    """Extract complete SQL statements from possibly truncated SQL.
    
    Returns a list of complete SQL statements found before truncation point.
    Useful for salvaging partial results from truncated output.
    """
    if not sql:
        return []
    
    statements = []
    # Split on semicolons that are not inside quotes
    in_single_quote = False
    in_double_quote = False
    current = []
    
    for i, char in enumerate(sql):
        if char == "'" and not _is_escaped(sql, i):
            in_single_quote = not in_single_quote
        elif char == '"' and not _is_escaped(sql, i):
            in_double_quote = not in_double_quote
        elif char == ';' and not in_single_quote and not in_double_quote:
            stmt = ''.join(current).strip()
            if stmt:
                # Verify this statement is complete
                is_trunc, _ = is_sql_truncated(stmt)
                if not is_trunc:
                    statements.append(stmt)
            current = []
            continue
        current.append(char)
    
    # Check final statement
    if current:
        stmt = ''.join(current).strip()
        if stmt:
            is_trunc, _ = is_sql_truncated(stmt)
            if not is_trunc:
                statements.append(stmt)
    
    return statements
