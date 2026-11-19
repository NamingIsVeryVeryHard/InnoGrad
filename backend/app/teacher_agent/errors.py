class TeacherAgentError(Exception):
    status_code = 422
    code = "INVALID_QUERY"

    def __init__(self, message, *, retry_after_seconds=None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ResourceNotFoundError(TeacherAgentError):
    status_code = 404
    code = "NOT_FOUND"


class ForbiddenRoleError(TeacherAgentError):
    status_code = 403
    code = "FORBIDDEN_ROLE"


class ConcurrencyConflictError(TeacherAgentError):
    status_code = 409
    code = "CONVERSATION_CHANGED"


class IdempotencyConflictError(TeacherAgentError):
    status_code = 409
    code = "IDEMPOTENCY_CONFLICT"


class PlannerUnavailableError(TeacherAgentError):
    status_code = 503
    code = "PLANNER_UNAVAILABLE"


class PlannerConfigError(TeacherAgentError):
    status_code = 503
    code = "PLANNER_CONFIG_ERROR"


class PlannerInvalidOutputError(TeacherAgentError):
    status_code = 502
    code = "INVALID_PLANNER_OUTPUT"


class RetryableToolInputError(TeacherAgentError):
    code = "RETRYABLE_TOOL_INPUT"


class AgentResultViewChangedError(ConcurrencyConflictError):
    pass
