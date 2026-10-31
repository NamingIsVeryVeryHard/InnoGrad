# 输出契约

程序使用 [schema.mjs](../../skills/graduate-research-guidance/scripts/schema.mjs) 中的 `responseSchema` 校验模型回复，使用 `resultSchema` 校验最终结果。模型回复包含事实、意图、条件、历史关联、缺口、建议和未知事项，不包含 `source_index`；最终结果由程序补充来源表与运行信息。同一份模型 Schema 直接写入请求，不要求模型访问本地文件。

最终 JSON 的 `schema_version` 为 `research-guidance-1.0`，`status` 为 `generated`，字段如下：

| 字段 | 内容 |
| --- | --- |
| `scope` | 学生标识、当前及历史材料的角色、阶段、期间；时间关系 `chronology` 保持未知 |
| `facts` | 原文支持的背景、进展、计划、条件；每条有 `text`、`kind`、`work_status`、`source_refs` |
| `intent` | `goal`、`attitude`、`subjective_norm`、`perceived_behavioral_control` |
| `task_conditions` | `progress`、实际可用 `resources`、`deadlines`；阶段和期间保存在 scope |
| `relevant_history` | 相关历史的 `material_id`、`text`、`source_refs`；`relation` 固定为 `related` |
| `gaps` | 缺口 `text`、所需材料 `needed_evidence`、`source_refs` |
| `guidance` | 1至3项候选行动，每项含 `action`、`why`、`completion_evidence`、字符串数组 `uncertainty`、`source_refs` |
| `unknowns` | 未确定事项的字符串数组 |
| `source_index` | 本轮 C 编号、带版本的 `source_id`、`start_char`/`end_char`、材料角色、文档及页段、文件名、页码、文档 hash 和程序提取的原文 `quote` |
| `provenance` | 平台、会话、已加载 Skill 哈希、实际 provider、请求及接口返回模型、结构化调用次数、`model_called`、逐次请求记录 |

`intent` 和 `task_conditions` 的每项使用 `{status, value, source_refs}`。有直接依据时为 `documented`；未知时必须为 `unknown`、`null`、`[]`，不能同时写有事实判断。

`facts.kind` 为 `background`、`progress`、`plan` 或 `condition`。`work_status` 为 `planned`、`reported_completed` 或 `unknown`。计划必须标为 planned，reported_completed 只用于进展，表示报告自述，不能表示独立核验。完成状态与原句是否相符仍需语义核对。

模型只通过 `source_refs` 选择本轮输入目录中的 C 编号。同一编号可支持多条结论；同一页不同位置使用不同引用单元。程序先确认所有编号存在，再去重引用数组并按使用顺序生成唯一来源表。每条原文及位置均来自输入目录，不让模型重新抄写或登记来源。最终复验会核对原句、来源版本和原文偏移，不能用另一页或另一版材料替代。
缺字段、未知引用或结构状态冲突触发一次模型修正重试；仍不合格则报失败。`run.json` 保存失败状态及安全的调用记录，不生成成功结果。旧原型中的 `intentions`、`recommendations`、`source_records` 不属于此契约。

程序能验证结构、身份范围和原文定位，不能据此证明概括正确、建议有效或学生已经采纳行动。
