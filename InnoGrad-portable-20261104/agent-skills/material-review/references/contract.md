# 审核契约

调用方直接提供 `{"review_package": ...}`，或提供指向审核文件的工作区相对路径。两种方式使用相同的审核输入与输出 schema。Skill 使用 OCR 或文本解析后的内容，不读取原始 PDF，不执行 OCR。输出只能是一个完整的 JSON 对象 `{"checks": [...]}`，对象前后不得有文字，也不加 Markdown 代码围栏。

## 输入传输

内联方式直接传入完整的 `review_package`，可附带相同契约的 `output_schema`，无需清单或文本视图。

文件方式在调用对象顶层提供 `review_package_path`、`source_manifest_path` 和 `output_schema_path`。它们是调用方提供的工作区相对路径，不是 `review_package` 的字段。例如：

```json
{
  "review_package_path": "review/package.json",
  "source_manifest_path": "review/manifest.json",
  "output_schema_path": "review/output-schema.json"
}
```

路径名称仅为示例。审核包文件包含完整的原始 OCR 后 `ReviewPackage`，保留所有附件原文；其字段遵循 [input-schema.json](input-schema.json)。输出 schema 文件与 [output-schema.json](output-schema.json) 的 checks-only 契约相同。

清单和文本视图由调用方根据完整审核包派生：

- `review_context` 包含全局包元数据、表单、学生、引用成果、要求、周期、逾期标记及限制，以及附件元数据。每个附件还带有 `source_path` 和 `block_count`，不含内联 `content`。
- `source_files` 列出各附件视图的 `path`、`file_id`、`sha256`、`line_count` 和 `block_count`。例如，视图路径可以是 `review/sources/001.txt`，实际路径由调用方指定。
- 每个附件对应一份完整的逐字文本视图。视图用显式的 JSON `SOURCE BLOCK` 标头标识每个内容块的 `file_id`、`page_number` 和 `paragraph_id`；标头用于定位，不是原文摘录。

在同一会话中，自行使用读取工具检查完整元数据和全部附件文本：可以通读审核包文件，或读取清单并通读 `source_files` 中每个完整文本视图。读取结果截断或分页时，使用工具偏移量继续读取，直到文件内容全部覆盖。部分读取不能证明原文缺失；读取顺序由审核需要决定。审核包中的原始内容块是摘录和定位的权威来源，视图中的文字及标识须与之对应。

调用方可能提供有限次机器校验反馈，指出输出 schema、漏读或摘录、定位、规则不匹配。收到反馈后，在同一会话中检查相关原文或未读材料，修正并返回完整 `checks` JSON。找不到支持时返回 `unable_to_determine` 并说明限制，不编造证据。

## 输入字段

- `schema_version`：当前为 `1.0`，可省略。
- `version_id`：调用方为本次冻结提交分配的标识。
- `kind`：`paper`（论文）或 `annual`（年度报告）。
- `student`：最少身份信息，如 `{"name": "<student-identifier>"}`；缺少身份信息时，对应规则无法判断。
- `form`：本次提交的表单。论文常用 `title`、`contribution`、`publication_status`、`journal`、`acceptance_date`、`publication_date`；年度报告常用 `summary`。论文状态为 `submitted`、`accepted` 或 `published`。
- `attachments`：当前版本的附件。`size` 单位为字节，`sha256` 是原文件的 SHA-256；它们是调用方提供的元数据，不据此声称已经重新核验文件。
- `references`：本次引用的成果快照，如 `{"id": "ref-1", "title": "成果名称", "recognition": "archived"}`；没有引用时为空数组。
- `requirements`：调用方提供的审核要求和规则，见下节。
- `period`：可选的报告周期；`late` 是可选的逾期标记，默认 `false`。不能仅因逾期推断正文不合规。
- `limitations`：可选的上游限制列表，元素为字符串，或 `{"file_id": "<file-id>", "message": "<specific limitation>"}`。限制影响某条规则时，该规则必须说明无法确定的事实。

附件用途 `role` 包括 `paper_fulltext`（论文全文）、`acceptance_notice`（录用通知）、`publication_page`（见刊页）、`contribution_statement`（贡献声明）、`annual_report`（年度报告）及 `other`。调用方可提供规则使用的其他用途名称。

`content` 是按阅读顺序排列的文本块。页码从 1 开始；段落 ID 是上游分配的不透明标识。证据必须复制所属附件的 `file_id` 和对应文本块的 `page_number`、`paragraph_id`，缺失的定位字段填 `null`。`quote` 必须是该块的连续原文，保留空格、换行和标点；JSON 转义须还原为相同字符。同一页可以有多个块，不得借用其他块的定位或拼接摘录。空内容或缺少可用定位时，不得生成虚构的证据。

同一原始 PDF 可以作为不同用途的附件提供全文和首页见刊视图。两个条目的 `sha256` 相同不会使见刊视图中的可见信息失效；引用时仍须符合规则的 `evidence_roles`。是否支持发表取决于原文和冻结规则；冻结要求未规定时，不要求另交独立 PDF。

## 规则字段

`requirements.review_rules` 是非空规则数组，每个元素包含：

- `id`：唯一规则编号；输出的 `rule_id` 必须与它相同。
- `instruction`：本条规则要核对的事实和判断方法。
- `evidence_roles`：可支持本条结论的附件用途。确定性结论必须引用至少一个符合该用途的附件；空数组表示不限用途。
- `not_applicable_when`：可选的不适用条件。`no_references` 表示 `references` 为空；`submitted` 表示 `form.publication_status` 为 `submitted`；`proofs_not_required` 表示 `requirements.proof_attachments_required` 不为真（任务未要求成果证明附件）。不支持的条件不能作为不适用依据。
- `level`：可选，`blocking`（阻断项）或 `advisory`（提示项），缺省为 `blocking`。
- `on_uncertain`：可选，`correction` 或 `hint`，缺省为 `correction`，只对阻断项有效。

`level` 和 `on_uncertain` 只供调用方路由：阻断项判为 `non_compliant` 时退回学生补正；阻断项判为 `unable_to_determine` 时，`on_uncertain=correction` 退回学生补正，`hint` 只作提示；提示项的任何结论都只作提示。Skill 对所有规则使用相同的判断和证据标准。

`requirements.version` 和 `rule_version` 标识要求及规则版本；`rules_hash` 可供调用方校验冻结规则，Skill 不计算它。`required_fields` 可声明表单必填项，`instructions` 可提供年度任务要求，`proof_attachments_required` 可声明任务是否要求成果证明附件。

随附的 [paper-v2.json](rules/paper-v2.json) 与 [annual-v2.json](rules/annual-v2.json) 是供调用方选择的规则模板；`*-v1.json` 仅为已冻结的历史提交保留。调用方把所选模板的 `rules` 放到 `requirements.review_rules`。执行时以输入中的完整规则为准，不自动补入模板规则。年度规则中的任务 `instructions` 指 `requirements.instructions`，报告周期指 `review_package.period`。

调用方负责提供符合 schema、规则非空且 ID 唯一的输入；不得编造规则或审核结果。示例中的占位符只说明结构，不是固定学生、论文或结论。

## 完整调用示例

以下示例只委托一条标题核对规则。占位符用于说明结构，示例哈希为演示值；真实调用应提供原文件哈希。

```json
{
  "review_package": {
    "version_id": "version-1",
    "kind": "paper",
    "student": {"name": "<student-identifier>"},
    "form": {"title": "<title>", "publication_status": "submitted"},
    "attachments": [{
      "file_id": "<file-id>",
      "name": "<source-file>",
      "role": "paper_fulltext",
      "media_type": "application/pdf",
      "size": 1234,
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "content": [{"page_number": 1, "paragraph_id": null, "text": "<title>"}]
    }],
    "references": [],
    "requirements": {
      "version": "title-check-v1",
      "review_rules": [{
        "id": "<rule-id>",
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
    "rule_id": "<rule-id>",
    "conclusion": "compliant",
    "severity": "info",
    "explanation": "表单标题与论文首页标题一致。",
    "evidence": [{"file_id": "<file-id>", "page_number": 1, "paragraph_id": null, "quote": "<title>"}],
    "suggestion": "",
    "limitations": []
  }]
}
```

每条输入规则必须有且只有一条输出。`compliant` 和 `non_compliant` 需要原文证据；`unable_to_determine` 需要具体限制；`not_applicable` 需要解释成立的条件。证明缺失或事实未知不等于已证明矛盾；附件缺失时，如果无法用现有原文支持确定性结论，应返回 `unable_to_determine`。只按冻结要求判断所需材料，不因审核习惯或报告中提及某材料就新增强制附件。业务系统可以另行按附件清单检查缺件并决定补正。
