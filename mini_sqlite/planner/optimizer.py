from __future__ import annotations

from dataclasses import dataclass

from mini_sqlite.catalog import IndexSchema, TableSchema
from mini_sqlite.planner.plan import AccessPath, PlanAlternative
from mini_sqlite.sql.ast import CompareOp, ComparisonPredicate


@dataclass(frozen=True)
class AccessChoice:
    path: AccessPath
    index: IndexSchema | None
    estimated_rows: float
    estimated_cost: float
    alternatives: tuple[PlanAlternative, ...]


@dataclass(frozen=True)
class JoinChoice:
    outer_side: int
    inner_path: AccessPath
    inner_index: IndexSchema | None
    estimated_rows: float
    estimated_cost: float
    alternatives: tuple[PlanAlternative, ...]


class CostModel:
    """Small, inspectable v0.8 cost model.

    Costs are abstract work units, not wall-clock predictions. The constants are
    intentionally visible so experiments can change assumptions and observe plan
    flips. When ANALYZE statistics are absent, the optimizer preserves the older
    rule-based behavior to keep pre-v0.8 databases deterministic.
    """

    TABLE_ROW_COST = 1.0
    PK_SEEK_COST = 2.0
    INDEX_SEEK_COST = 2.0
    INDEX_MATCH_COST = 0.20
    ROWID_LOOKUP_COST = 2.0

    def choose_access(
        self, schema: TableSchema, where: ComparisonPredicate | None
    ) -> AccessChoice:
        if schema.stats is None:
            path, index = self._legacy_access(schema, where)
            return AccessChoice(path, index, self._fallback_rows(schema, where), 0.0, ())

        row_count = float(schema.stats.row_count)
        est_rows = self.estimate_filter_rows(schema, where)
        alternatives: list[tuple[AccessPath, IndexSchema | None, PlanAlternative]] = []

        scan_cost = max(1.0, row_count) * self.TABLE_ROW_COST
        alternatives.append(
            (
                AccessPath.TABLE_SCAN,
                None,
                PlanAlternative("TABLE SCAN", scan_cost, est_rows),
            )
        )

        if where is not None and where.op == CompareOp.EQ:
            if where.column.lower() == schema.primary_key.name.lower():
                alternatives.append(
                    (
                        AccessPath.PRIMARY_KEY,
                        None,
                        PlanAlternative("PRIMARY KEY", self.PK_SEEK_COST, min(1.0, est_rows)),
                    )
                )
            else:
                index = schema.index_on_column(where.column)
                if index is not None:
                    index_cost = (
                        self.INDEX_SEEK_COST
                        + est_rows * (self.INDEX_MATCH_COST + self.ROWID_LOOKUP_COST)
                    )
                    alternatives.append(
                        (
                            AccessPath.SECONDARY_INDEX,
                            index,
                            PlanAlternative(
                                f"SECONDARY INDEX {index.name}", index_cost, est_rows
                            ),
                        )
                    )

        chosen = min(alternatives, key=lambda item: (item[2].estimated_cost, item[2].name))
        return AccessChoice(
            chosen[0],
            chosen[1],
            chosen[2].estimated_rows,
            chosen[2].estimated_cost,
            tuple(item[2] for item in alternatives),
        )

    def choose_join(
        self,
        left: TableSchema,
        right: TableSchema,
        left_column_index: int,
        right_column_index: int,
    ) -> JoinChoice:
        # Without stats retain v0.5's written-left outer rule.
        if left.stats is None or right.stats is None:
            path, index = self._join_inner_path(right, right_column_index)
            return JoinChoice(0, path, index, self._fallback_join_rows(left, right), 0.0, ())

        candidates = [
            self._join_candidate(
                outer_side=0,
                outer=left,
                inner=right,
                outer_col=left_column_index,
                inner_col=right_column_index,
            ),
            self._join_candidate(
                outer_side=1,
                outer=right,
                inner=left,
                outer_col=right_column_index,
                inner_col=left_column_index,
            ),
        ]
        chosen = min(candidates, key=lambda item: (item[3].estimated_cost, item[3].name))
        estimated_rows = self.estimate_join_rows(
            left, right, left_column_index, right_column_index
        )
        return JoinChoice(
            outer_side=chosen[0],
            inner_path=chosen[1],
            inner_index=chosen[2],
            estimated_rows=estimated_rows,
            estimated_cost=chosen[3].estimated_cost,
            alternatives=tuple(item[3] for item in candidates),
        )

    def estimate_filter_rows(
        self, schema: TableSchema, where: ComparisonPredicate | None
    ) -> float:
        if schema.stats is None:
            return self._fallback_rows(schema, where)
        rows = float(schema.stats.row_count)
        if where is None:
            return rows
        stats = schema.stats.column(where.column)
        if stats is None or rows <= 0:
            return rows * 0.25
        non_null = max(0.0, rows - float(stats.null_count))
        if where.op == CompareOp.EQ:
            if where.value is None:
                return float(stats.null_count)
            for value, count in stats.most_common:
                if value == where.value:
                    return float(count)
            if stats.distinct_count <= 0:
                return 0.0
            known_rows = float(sum(count for _value, count in stats.most_common))
            remaining_rows = max(0.0, non_null - known_rows)
            remaining_distinct = max(1, stats.distinct_count - len(stats.most_common))
            return max(1.0, remaining_rows / float(remaining_distinct))
        if where.op == CompareOp.NE:
            eq = 0.0 if stats.distinct_count <= 0 else non_null / float(stats.distinct_count)
            return max(0.0, non_null - eq)
        if where.value is None:
            return 0.0
        # INTEGER range interpolation; TEXT uses a conservative one-third guess.
        if isinstance(where.value, int) and isinstance(stats.min_value, int) and isinstance(stats.max_value, int):
            lo, hi, value = stats.min_value, stats.max_value, where.value
            if hi <= lo:
                fraction = 1.0 if value >= hi else 0.0
            else:
                fraction = max(0.0, min(1.0, (value - lo) / (hi - lo)))
            if where.op in (CompareOp.LT, CompareOp.LE):
                return non_null * fraction
            if where.op in (CompareOp.GT, CompareOp.GE):
                return non_null * (1.0 - fraction)
        return non_null / 3.0

    def estimate_join_rows(
        self,
        left: TableSchema,
        right: TableSchema,
        left_col: int,
        right_col: int,
    ) -> float:
        if left.stats is None or right.stats is None:
            return self._fallback_join_rows(left, right)
        lrows = float(left.stats.row_count)
        rrows = float(right.stats.row_count)
        lstats = left.stats.column(left.columns[left_col].name)
        rstats = right.stats.column(right.columns[right_col].name)
        if lstats is None or rstats is None:
            return lrows * rrows * 0.1
        denom = max(1, lstats.distinct_count, rstats.distinct_count)
        return (lrows * rrows) / float(denom)

    def _join_candidate(
        self,
        *,
        outer_side: int,
        outer: TableSchema,
        inner: TableSchema,
        outer_col: int,
        inner_col: int,
    ) -> tuple[int, AccessPath, IndexSchema | None, PlanAlternative]:
        del outer_col  # reserved for richer correlation/histogram models
        outer_rows = float(outer.stats.row_count if outer.stats is not None else 1000)
        inner_rows = float(inner.stats.row_count if inner.stats is not None else 1000)
        path, index = self._join_inner_path(inner, inner_col)
        if path == AccessPath.PRIMARY_KEY:
            probe = self.PK_SEEK_COST
            name = f"{'LEFT' if outer_side == 0 else 'RIGHT'} OUTER -> INNER PRIMARY KEY"
        elif path == AccessPath.SECONDARY_INDEX:
            assert index is not None
            matches = self._equality_rows_for_column(inner, inner_col)
            probe = self.INDEX_SEEK_COST + matches * (
                self.INDEX_MATCH_COST + self.ROWID_LOOKUP_COST
            )
            name = (
                f"{'LEFT' if outer_side == 0 else 'RIGHT'} OUTER -> "
                f"INNER INDEX {index.name}"
            )
        else:
            probe = max(1.0, inner_rows) * self.TABLE_ROW_COST
            name = f"{'LEFT' if outer_side == 0 else 'RIGHT'} OUTER -> INNER TABLE SCAN"
        cost = max(1.0, outer_rows) + outer_rows * probe
        return outer_side, path, index, PlanAlternative(name, cost, outer_rows)

    def _equality_rows_for_column(self, schema: TableSchema, column_index: int) -> float:
        if schema.stats is None:
            return 10.0
        stats = schema.stats.column(schema.columns[column_index].name)
        if stats is None or stats.distinct_count <= 0:
            return max(1.0, schema.stats.row_count * 0.1)
        non_null = max(0, schema.stats.row_count - stats.null_count)
        return max(1.0, non_null / stats.distinct_count)

    @staticmethod
    def _join_inner_path(
        schema: TableSchema, column_index: int
    ) -> tuple[AccessPath, IndexSchema | None]:
        if column_index == schema.primary_key_index:
            return AccessPath.PRIMARY_KEY, None
        index = schema.index_on_column(schema.columns[column_index].name)
        if index is not None:
            return AccessPath.SECONDARY_INDEX, index
        return AccessPath.TABLE_SCAN, None

    @staticmethod
    def _legacy_access(
        schema: TableSchema, where: ComparisonPredicate | None
    ) -> tuple[AccessPath, IndexSchema | None]:
        if where is None or where.op != CompareOp.EQ:
            return AccessPath.TABLE_SCAN, None
        if where.column.lower() == schema.primary_key.name.lower():
            return AccessPath.PRIMARY_KEY, None
        index = schema.index_on_column(where.column)
        if index is not None:
            return AccessPath.SECONDARY_INDEX, index
        return AccessPath.TABLE_SCAN, None

    @staticmethod
    def _fallback_rows(schema: TableSchema, where: ComparisonPredicate | None) -> float:
        if where is None:
            return 1000.0
        if where.op == CompareOp.EQ and where.column.lower() == schema.primary_key.name.lower():
            return 1.0
        return 100.0

    @staticmethod
    def _fallback_join_rows(left: TableSchema, right: TableSchema) -> float:
        lrows = left.stats.row_count if left.stats is not None else 1000
        rrows = right.stats.row_count if right.stats is not None else 1000
        return float(lrows * rrows) * 0.1
