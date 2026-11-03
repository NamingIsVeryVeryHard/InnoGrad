# 审核契约

调用方提供一个 JSON 对象，其中 `review_package` 是审核输入。Skill 直接使用其中的文本，不读取原始文件，不执行 OCR。输出是 JSON 对象 `{"checks": [...]}`，不加 Markdown 代码围栏。

## 输入字段

- `schema_version`：当前为 `1.0`，可省略。
- `version_id`：调用方为本次冻结提交分配的标识。
- `kind`：`paper`（论文）或 `annual`（年度报告）。
- `student`：最少身份信息，如 `{"name": "张三"}`；缺少身份信息时，对应规则无法判断。
- `form`：本次提交的表单。论文常用 `title`、`contribution`、`publication_status`、`journal`、`acceptance_date`、`publication_date`；年度报告常用 `summary`。论文状态为 `submitted`、`accepted` 或 `published`。
- `attachments`：当前版本的附件。`size` 单位为字节，`sha256` 是原文件的 SHA-256；它们是调用方提供的元数据，不据此声称已经重新核验文件。
- `references`：本次引用的成果快照，如 `{"id": "ref-1", "title": "成果名称", "recognition": "archived"}`；没有引用时为空数组。
- `requirements`：调用方提供的审核要求和规则，见下节。
- `period`：可选的报告周期；`late` 是可选的逾期标记，默认 `false`。不能仅因逾期推断正文不合规。
- `limitations`：可选的上游限制列表，元素为字符串，或 `{"file_id": "file-1", "message": "第 2 页识别不完整"}`。限制影响某条规则时，该规则必须说明无法确定的事实。

附件用途 `role` 包括 `paper_fulltext`（论文全文）、`acceptance_notice`（录用通知）、`publication_page`（见刊页）、`contribution_statement`（贡献声明）、`annual_report`（年度报告）及 `other`。调用方可提供规则使用的其他用途名称。

`content` 是按阅读顺序排列的文本块。页码从 1 开始；段落 ID 是上游分配的不透明标识。证据必须复制文本块中已有的定位，`quote` 必须是该块的连续原文。同一页可以有多个块。空内容或缺少定位时，不得生成虚构的证据。

## 规则字段

`requirements.review_rules` 是非空规则数组，每个元素包含：

- `id`：唯一规则编号；输出的 `rule_id` 必须与它相同。
- `instruction`：本条规则要核对的事实和判断方法。
- `evidence_roles`：可支持本条结论的附件用途。确定性结论必须引用至少一个符合该用途的附件；空数组表示不限用途。
- `not_applicable_when`：可选的不适用条件。`no_references` 表示 `references` 为空；`submitted` 表示 `form.publication_status` 为 `submitted`。不支持的条件不能作为不适用依据。

`requirements.version` 和 `rule_version` 标识要求及规则版本；`rules_hash` 可供调用方校验冻结规则，Skill 不计算它。`required_fields` 可声明表单必填项，`instructions` 可提供年度任务要求。

随附的 [paper-v1.json](rules/paper-v1.json) 与 [annual-v1.json](rules/annual-v1.json) 是供调用方选择的规则模板。调用方把所选模板的 `rules` 放到 `requirements.review_rules`。执行时以输入中的完整规则为准，不自动补入模板规则。年度规则中的任务 `instructions` 指 `requirements.instructions`，报告周期指 `review_package.period`。

如果输入缺少规则、规则 ID 重复或结构不符合 schema，请先要求调用方修正输入，不编造规则或审核结果。

## 完整调用示例

以下示例只委托一条标题核对规则。示例哈希为演示值，真实调用应提供原文件哈希。

```json
{
  "review_package": {
    "version_id": "version-1",
    "kind": "paper",
    "student": {"name": "张三"},
    "form": {"title": "示例论文", "publication_status": "submitted"},
    "attachments": [{
      "file_id": "file-1",
      "name": "paper.pdf",
      "role": "paper_fulltext",
      "media_type": "application/pdf",
      "size": 1234,
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "content": [{"page_number": 1, "paragraph_id": null, "text": "示例论文\n作者：张三"}]
    }],
    "references": [],
    "requirements": {
      "version": "title-check-v1",
      "review_rules": [{
        "id": "PAPER_TITLE_MATCH",
        "instruction": "核对表单标题与论文首页标题。",
        "evidence_roles": ["paper_fulltext"]
      }]
    }
  }
}
```

对应输出：

```json
{
  "checks": [{
    "rule_id": "PAPER_TITLE_MATCH",
    "conclusion": "compliant",
    "severity": "info",
    "explanation": "表单标题与论文首页标题一致。",
    "evidence": [{"file_id": "file-1", "page_number": 1, "paragraph_id": null, "quote": "示例论文"}],
    "suggestion": "",
    "limitations": []
  }]
}
```

每条输入规则必须有且只有一条输出。`compliant` 和 `non_compliant` 需要原文证据；`unable_to_determine` 需要具体限制；`not_applicable` 需要解释成立的条件。附件缺失时，如果无法用现有原文支持确定性结论，应返回 `unable_to_determine`。业务系统可以另行按附件清单检查缺件并决定补正。
