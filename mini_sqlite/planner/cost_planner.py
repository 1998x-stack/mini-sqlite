from __future__ import annotations

from dataclasses import replace

from mini_sqlite.planner.optimizer import CostModel
from mini_sqlite.planner.plan import (
    AccessPath,
    AnalyzePlan,
    DeletePlan,
    JoinSelectPlan,
    Plan,
    SelectPlan,
    UpdatePlan,
)
from mini_sqlite.planner.planner import Planner as LegacyPlanner
from mini_sqlite.sql.ast import AnalyzeStmt, DeleteStmt, SelectStmt, Statement, UpdateStmt


class CostBasedPlanner(LegacyPlanner):
    """v0.8 physical-plan chooser layered over the v0.7 binder/planner.

    LegacyPlanner still resolves SQL names, projections, predicates, JOIN ON
    columns, and relational stages. This subclass changes only physical choices
    once ANALYZE statistics exist. Databases without statistics intentionally
    retain the v0.7 rule-based plans.
    """

    def __init__(self, catalog):
        super().__init__(catalog)
        self.cost_model = CostModel()

    def plan(self, stmt: Statement) -> Plan:
        if isinstance(stmt, AnalyzeStmt):
            if stmt.table is not None:
                self.catalog.get_table(stmt.table)
            return AnalyzePlan(stmt.table)

        plan = super().plan(stmt)
        if isinstance(stmt, SelectStmt):
            if isinstance(plan, JoinSelectPlan):
                choice = self.cost_model.choose_join(
                    plan.left_schema,
                    plan.right_schema,
                    plan.join.left_column_index,
                    plan.join.right_column_index,
                )
                return replace(
                    plan,
                    inner_access_path=choice.inner_path,
                    inner_index=choice.inner_index,
                    outer_side=choice.outer_side,
                    estimated_rows=choice.estimated_rows,
                    estimated_cost=choice.estimated_cost if choice.alternatives else None,
                    alternatives=choice.alternatives,
                )
            assert isinstance(plan, SelectPlan)
            choice = self.cost_model.choose_access(plan.schema, plan.where)
            return replace(
                plan,
                access_path=choice.path,
                index=choice.index,
                estimated_rows=choice.estimated_rows,
                estimated_cost=choice.estimated_cost if choice.alternatives else None,
                alternatives=choice.alternatives,
            )

        if isinstance(stmt, (DeleteStmt, UpdateStmt)):
            assert isinstance(plan, (DeletePlan, UpdatePlan))
            choice = self.cost_model.choose_access(plan.schema, plan.where)
            return replace(plan, access_path=choice.path, index=choice.index)
        return plan

    @staticmethod
    def explain(plan: Plan) -> str:
        if isinstance(plan, AnalyzePlan):
            return f"ANALYZE {plan.table or 'ALL TABLES'}"

        if isinstance(plan, JoinSelectPlan):
            inner_column_name = (
                plan.join.right_column_name if plan.outer_side == 0 else plan.join.left_column_name
            )
            if plan.inner_access_path == AccessPath.PRIMARY_KEY:
                join_text = f"INDEXED NESTED LOOP | INNER PRIMARY KEY {inner_column_name}"
            elif plan.inner_access_path == AccessPath.SECONDARY_INDEX:
                assert plan.inner_index is not None
                join_text = (
                    "INDEXED NESTED LOOP | INNER SECONDARY INDEX "
                    f"{plan.inner_index.name} ON {inner_column_name}"
                )
            else:
                join_text = "NESTED LOOP | INNER TABLE SCAN"
            outer_name = plan.left_name if plan.outer_side == 0 else plan.right_name
            inner_name = plan.right_name if plan.outer_side == 0 else plan.left_name
            parts = [
                f"SELECT FROM {plan.left_schema.name} AS {plan.left_name}",
                f"INNER JOIN {plan.right_schema.name} AS {plan.right_name}",
                f"ON {plan.join.left_column_name} = {plan.join.right_column_name}",
                f"PHYSICAL ORDER {outer_name} -> {inner_name}",
                join_text,
            ]
            CostBasedPlanner._append_estimates(parts, plan)
            if plan.where is not None:
                parts.append(
                    f"FILTER {plan.where.column_name} {plan.where.op.value} {plan.where.value!r}"
                )
            if plan.order_by is not None:
                parts.append(
                    f"SORT {plan.order_by.column_name} "
                    f"{'DESC' if plan.order_by.descending else 'ASC'}"
                )
            if plan.aggregates:
                parts.append("AGGREGATE " + ", ".join(a.output_name for a in plan.aggregates))
            else:
                parts.append("PROJECT " + ", ".join(plan.projection_names))
            if plan.limit is not None:
                parts.append(f"LIMIT {plan.limit}")
            return " | ".join(parts)

        if isinstance(plan, SelectPlan):
            parts = [f"SELECT FROM {plan.schema.name} USING {LegacyPlanner._path_text(plan)}"]
            CostBasedPlanner._append_estimates(parts, plan)
            if plan.where is not None and plan.access_path == AccessPath.TABLE_SCAN:
                parts.append(f"FILTER {plan.where.column} {plan.where.op.value} {plan.where.value!r}")
            if plan.order_by is not None:
                parts.append(
                    f"SORT {plan.order_by.column_name} "
                    f"{'DESC' if plan.order_by.descending else 'ASC'}"
                )
            if plan.aggregates:
                parts.append("AGGREGATE " + ", ".join(a.output_name for a in plan.aggregates))
            else:
                parts.append("PROJECT " + ", ".join(plan.projection_names))
            if plan.limit is not None:
                parts.append(f"LIMIT {plan.limit}")
            return " | ".join(parts)

        return LegacyPlanner.explain(plan)

    @staticmethod
    def _append_estimates(parts: list[str], plan: SelectPlan | JoinSelectPlan) -> None:
        if plan.estimated_cost is None:
            return
        assert plan.estimated_rows is not None
        parts.append(f"EST rows={plan.estimated_rows:.2f} cost={plan.estimated_cost:.2f}")
        parts.append(
            "CANDIDATES "
            + "; ".join(f"{a.name}:cost={a.estimated_cost:.2f}" for a in plan.alternatives)
        )
