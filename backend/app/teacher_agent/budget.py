import os
from dataclasses import dataclass

from .errors import PlannerConfigError


@dataclass(frozen=True, slots=True)
class TurnBudget:
    max_queries: int = 5
    max_tool_retries: int = 2
    max_turn_retries: int = 1

    @classmethod
    def from_env(cls) -> "TurnBudget":
        defaults = cls()
        try:
            budget = cls(
                max_queries=int(os.getenv("TEACHER_AGENT_MAX_QUERIES", str(defaults.max_queries))),
                max_tool_retries=int(os.getenv("TEACHER_AGENT_MAX_TOOL_RETRIES", str(defaults.max_tool_retries))),
                max_turn_retries=int(os.getenv("TEACHER_AGENT_MAX_TURN_RETRIES", str(defaults.max_turn_retries))),
            )
            if budget.max_queries < 1 or min(budget.max_tool_retries, budget.max_turn_retries) < 0:
                raise ValueError
        except ValueError:
            raise PlannerConfigError("教师查询次数或重试次数配置无效") from None
        return budget
