"""Material-review business adapter over the shared InnoAgent client."""
import hashlib
import json

from ..agent_client import AgentClient, MAX_REPORT_BYTES, MAX_UPLOAD_BODY_BYTES
from ..agent_contracts import AgentExecution, AgentTask
from ..material_rules import SKILL_ROOT, SKILL_VERSION
from ..review_errors import ReviewFailure
from ..review_workspace import ReviewWorkspace


class InnoAgentAdapter(AgentClient):
    def __init__(self, config, validate_result=None, execution=None):
        # AIJob owns durable retries; the shared client runs one attempt here.
        super().__init__({**config, "max_attempts": 1})
        self.skill = config.get("skill") or "material-review"
        self.validate_result = validate_result
        self.execution = execution or AgentExecution()
        self.workspace = None

    @staticmethod
    def _upload_limit():
        return MAX_UPLOAD_BODY_BYTES

    @staticmethod
    def _report(text):
        report = AgentClient._report(text)
        if set(report) != {"checks"} or not isinstance(report["checks"], list):
            raise ReviewFailure("OUTPUT_INVALID")
        return report

    @staticmethod
    def _repair_prompt(failure):
        feedback = {"code": failure.code, "issues": failure.metadata.get("validation_issues", [])}
        return (
            "上次报告未通过程序校验。请根据本会话的原始内容和以下反馈修正报告。"
            "存在未读范围时，先用 read 工具补齐每个范围；按 path 和 offset 分页读取，"
            "每次 limit<=100，不要只重复第一次读取。"
            "引用不符时重新核对原文。每条 quote 必须是单个内容块中逐字连续原文，不能拼接相邻块。"
            "无法找到支撑某结论的原文时，按冻结规则输出无法判断，不得编造证据。"
            '重新输出完整结果；所有冻结规则仍须恰有一项。顶层必须且只能是 {"checks": [...]}。'
            "说明和建议使用自然中文，写清材料问题及补正行动，不展示内部字段名或技术代码。"
            "证据引文保留原文。不要添加说明、Markdown 或总结，不向用户提问。\n"
            + json.dumps(feedback, ensure_ascii=False)
        )

    def review(self, payload, output_schema):
        self.workspace = ReviewWorkspace(payload, output_schema)

        def validate_output(result):
            self.workspace.validate_coverage()
            return self.validate_result(result) if self.validate_result else result

        task = AgentTask(
            skill=self.skill,
            skill_version=SKILL_VERSION,
            expected_skill_hash=hashlib.sha256((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8").encode()).hexdigest(),
            input=payload,
            input_path="review/package.json",
            schema_path="review/output-schema.json",
            files=self.workspace.files,
            output_schema=output_schema,
            validate_output=validate_output,
            observe_event=self.workspace.record,
            collect_metadata=lambda: {"coverage": self.workspace.coverage(), "tool_trace": self.workspace.trace},
            repair_prompt=self._repair_prompt,
            repair_codes=("OUTPUT_INVALID", "EVIDENCE_INVALID", "RULE_INCOMPLETE", "COVERAGE_INCOMPLETE"),
            instructions=(
                "完整审核包和原文已放入本次工作区，请自主使用读取工具审阅全部材料。"
                "清单包含完整审核上下文及每份附件的原文视图路径，也可读取完整审核包。"
                "工具返回截断或分页提示时继续读取，直到覆盖全部材料；局部读取不代表原件缺失。"
                "最终只输出顶层为 checks 数组的完整 JSON 对象。"
                "说明、建议和限制使用自然中文，写清具体材料问题和下一步行动，"
                "不展示输入字段名、规则代码、会话标识、哈希或服务配置。证据引文保留原文。\n"
                + json.dumps({
                    "review_package_path": "review/package.json",
                    "source_manifest_path": "review/manifest.json",
                    "output_schema_path": "review/output-schema.json",
                }, ensure_ascii=False)
            ),
        )
        result = self.run(task, self.execution)
        return result.output, result.metadata
