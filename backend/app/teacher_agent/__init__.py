"""Public interface for teacher query planning, execution, and HTTP registration."""
from .api import register
from .contract import (
    METRIC_CATALOG,
    ConversationDetail,
    ConversationSummary,
    CreateConversationRequest,
    DegreeFilter,
    DrilldownPatchTurnInput,
    NaturalLanguageTurnInput,
    PaperQuerySpec,
    PaperTimeRange,
    PublicationStatusFilter,
    QueryPatch,
    QuerySpec,
    ResultEnvelope,
    ReviewStatusFilter,
    ScholarshipQuerySpec,
    StructuredSpecTurnInput,
    TurnRequest,
    TurnResponse,
    apply_patch,
    export_schemas,
    validate_query_spec,
)
from .engine import ActorContext, TeacherQueryEngine
from .errors import TeacherAgentError
from .planner import ChatCompletionQueryPlanner, InnoAgentQueryPlanner, QueryPlanner, RuleQueryPlanner, build_planner

__all__ = [
    "ActorContext", "ChatCompletionQueryPlanner", "ConversationDetail", "ConversationSummary",
    "CreateConversationRequest", "DegreeFilter", "DrilldownPatchTurnInput", "InnoAgentQueryPlanner",
    "METRIC_CATALOG", "NaturalLanguageTurnInput", "PaperQuerySpec", "PaperTimeRange",
    "PublicationStatusFilter", "QueryPatch", "QueryPlanner", "QuerySpec", "ResultEnvelope",
    "ReviewStatusFilter", "RuleQueryPlanner", "ScholarshipQuerySpec", "StructuredSpecTurnInput",
    "TeacherAgentError", "TeacherQueryEngine", "TurnRequest", "TurnResponse", "apply_patch",
    "build_planner", "export_schemas", "register", "validate_query_spec",
]
