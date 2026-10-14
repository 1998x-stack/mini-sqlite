from __future__ import annotations

from mini_sqlite.catalog.schema import IndexSchema, TableSchema
from mini_sqlite.planner.plan import AccessPath, IndexProbeSpec
from mini_sqlite.sql.ast import (
    BetweenPredicate,
    CompareOp,
    ComparisonPredicate,
    Predicate,
    predicate_terms,
)


def find_equality(predicate: Predicate | None, column: str):
    lowered = column.lower()
    for term in predicate_terms(predicate):
        if (
            isinstance(term, ComparisonPredicate)
            and term.op == CompareOp.EQ
            and term.column.lower() == lowered
        ):
            return term.value
    return None


def build_index_probe(
    schema: TableSchema, index: IndexSchema, predicate: Predicate | None
) -> IndexProbeSpec | None:
    terms = predicate_terms(predicate)
    if not terms:
        return None
    by_column: dict[str, list[object]] = {}
    for term in terms:
        by_column.setdefault(term.column.lower(), []).append(term)

    equality_values: list[object] = []
    matched = 0
    range_column: str | None = None
    lower = upper = None
    lower_inclusive = upper_inclusive = True
    has_lower = has_upper = False

    for column_name in index.columns:
        candidates = by_column.get(column_name.lower(), [])
        eq = next(
            (
                term
                for term in candidates
                if isinstance(term, ComparisonPredicate) and term.op == CompareOp.EQ
            ),
            None,
        )
        if eq is not None:
            equality_values.append(eq.value)
            matched += 1
            continue

        for term in candidates:
            if isinstance(term, BetweenPredicate):
                range_column = column_name
                lower, upper = term.lower, term.upper
                lower_inclusive = upper_inclusive = True
                has_lower = has_upper = True
                matched += 1
                break
            if not isinstance(term, ComparisonPredicate):
                continue
            if term.op in (CompareOp.GT, CompareOp.GE):
                range_column = column_name
                if not has_lower or term.value > lower or (
                    term.value == lower and term.op == CompareOp.GT and lower_inclusive
                ):
                    lower = term.value
                    lower_inclusive = term.op == CompareOp.GE
                    has_lower = True
                matched += 1
            elif term.op in (CompareOp.LT, CompareOp.LE):
                range_column = column_name
                if not has_upper or term.value < upper or (
                    term.value == upper and term.op == CompareOp.LT and upper_inclusive
                ):
                    upper = term.value
                    upper_inclusive = term.op == CompareOp.LE
                    has_upper = True
                matched += 1
        if has_lower or has_upper:
            break
        # Left-prefix rule: a missing key column stops index exploitation.
        break

    if not equality_values and not has_lower and not has_upper:
        return None
    return IndexProbeSpec(
        equality_values=tuple(equality_values),
        range_column=range_column,
        lower=lower,
        lower_inclusive=lower_inclusive,
        upper=upper,
        upper_inclusive=upper_inclusive,
        has_lower=has_lower,
        has_upper=has_upper,
        matched_terms=matched,
    )


def choose_rule_access(
    schema: TableSchema, predicate: Predicate | None
) -> tuple[AccessPath, IndexSchema | None, IndexProbeSpec | None]:
    if predicate is None:
        return AccessPath.TABLE_SCAN, None, None

    pk_value = find_equality(predicate, schema.primary_key.name)
    if pk_value is not None:
        return AccessPath.PRIMARY_KEY, None, None

    candidates: list[tuple[tuple[int, int, int], IndexSchema, IndexProbeSpec]] = []
    for index in schema.indexes:
        probe = build_index_probe(schema, index, predicate)
        if probe is None:
            continue
        score = (
            len(probe.equality_values),
            1 if probe.is_range else 0,
            probe.matched_terms,
        )
        candidates.append((score, index, probe))
    if not candidates:
        return AccessPath.TABLE_SCAN, None, None
    _score, index, probe = max(candidates, key=lambda item: item[0])
    # Preserve the historical scalar equality opcode/path where possible.
    if (
        len(index.columns) == 1
        and len(probe.equality_values) == 1
        and not probe.is_range
    ):
        return AccessPath.SECONDARY_INDEX, index, probe
    return AccessPath.SECONDARY_INDEX_RANGE, index, probe


def render_predicate(predicate: Predicate | None) -> str:
    if predicate is None:
        return ""
    parts: list[str] = []
    for term in predicate_terms(predicate):
        if isinstance(term, BetweenPredicate):
            parts.append(f"{term.column} BETWEEN {term.lower!r} AND {term.upper!r}")
        else:
            parts.append(f"{term.column} {term.op.value} {term.value!r}")
    return " AND ".join(parts)
