# #33 教师端多工具回合联调草稿

教师问“汇总 2026 年论文的发表状态，再列出博士生已发表的论文”时，首次响应可先展示 `analysis` 的总结，再按 `results` 的执行顺序展示两张卡。第一张展示发表状态分布，第二张列出符合条件的论文记录。

服务端先按当前教师的权限筛选查询结果，再将汇总数据、运行 ID 和授权范围内的真实明细行提供给校方自有模型。明细行保留真实姓名。教师可在对应结果卡中查看这些姓名和获准访问的证据。

| 场景 | 前端读取方式 |
| --- | --- |
| 提交回合 | 展示 `analysis` 中已核实的内容。有 `analysis_notice` 时一并展示提示，再按顺序展示 `results`。`result` 保留给旧客户端，多次运行时指向最后一张卡。 |
| 首次响应中整篇分析无法核实 | 查询成功的卡片仍然有效。此时 `analysis` 为 `null`，前端先展示 `analysis_notice` 提示，再照常展示全部卡片和下钻入口。若两个字段都为空，直接展示卡片。 |
| 恢复对话 | 服务端按教师当前权限重新生成卡片。`ConversationDetail.latest_results` 按执行顺序提供最近回合的可见卡片，`latest_result` 保留最后一个兼容结果。历史时间线不保存首次响应的分析或提示。 |
| 幂等重试 | 使用相同幂等键重试时，服务端按原运行 ID 和当前权限重新生成卡片。前端展示 `results`，此时 `analysis` 和 `analysis_notice` 均为 `null`。 |
| 浏览历史 | `turn.run_ids` 按执行顺序列出本回合可访问的运行。`turn.run_id` 是旧版单值字段。 |
| 澄清或未执行查询 | 没有运行时列表为空。旧字段 `result.clarification` 仍提供澄清提示。 |

前端遇到缺少新列表字段的旧响应时，可以使用单值字段。新列表出现时以它为准，包括空列表。每个 `query_run_id` 只展示一次。历史回合标记 `access_revoked` 时应隐藏受限内容。

分析中的 `[run_id]` 使用卡片的完整 `query_run_id`，例如 `[run-demo-04]`。点击时定位本回合中 ID 相符的可见卡片。打开原始材料时，只使用当前授权卡片 `sources` 提供的证据和受控链接。无法匹配的标记显示为普通文本。

从卡片下钻时，发送 `input.mode = "drilldown_patch"`，将所点卡片的 `query_run_id` 填入 `input.parent_run_id`，将所选指标或分组行的 `drilldown_patch` 填入 `input.patch`。例如，在双卡样例中点击第一张状态分布卡，应发送 `run-demo-04`，这样筛选就从该卡的统计范围开始。服务端核对该运行属于当前对话，且教师仍有访问权限。旧客户端省略 `parent_run_id` 时，沿用对话当前的查询条件。

`schemas_and_mocks.json` 中的 `turn_request_schema` 定义下钻请求，`turn_response_schema` 和 `conversation_detail_schema` 定义回合与历史结构。`turn_mocks.paper_multirun_turn` 展示带分析的双卡回合，`turn_mocks.paper_multirun_unverified_analysis` 展示同一组卡片在整篇分析无法核实时的首次响应。原有三个 `mocks` 条目仍可作为单张 `ResultEnvelope` 独立使用。在仓库根目录运行以下命令可重新生成样例并核对契约。

```sh
PYTHONPATH=backend backend/.venv/bin/python fixtures/teacher-agent/generate.py > fixtures/teacher-agent/schemas_and_mocks.json
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_teacher_agent_contract.py
```
