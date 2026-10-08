# 项目协作流程

本文说明任务管理、需求反馈与评审方式。项目任务通过 [InnoGrad Project](https://github.com/orgs/NamingIsVeryVeryHard/projects/1) 集中管理。

正式文档保存在仓库中，通过 README 导航。Issues 记录任务和讨论，Project 展示任务进展。

首次参与请阅读[贡献指南](../../CONTRIBUTING.md)，了解任务认领、交付和 PR 评审步骤。

使用 Codex 参与协作时，按[团队 Skills 与 GitHub Projects](../../.agents/README.md)配置个人 GitHub 授权。共享 skills 随仓库同步，成员权限分别管理。

## 任务管理

每项任务使用一个 Issue，说明目标、交付内容、验收方式和前置条件，并链接相关文档或产品范围编号。创建前先查看已有任务，避免重复。

任务完成后，在 Issue 中补充交付链接和验证结果，通过验收后关闭。具体任务与交付安排见[阶段计划](../../tasks/plan.md)。

## 项目看板

以下视图共享同一组 Issues 和任务状态。Project 公开可读，编辑与管理需要相应权限。视图与状态使用中文名称，字段保留英文。

| 视图 | 布局与筛选 | 用法 |
| --- | --- | --- |
| 项目看板 | Board，按 Status 分列 | 查看全部任务，从待规划到已完成跟踪进展 |
| 迭代计划 | Table，按 Status 分组、按 Assignees 切片 | 查看任务负责人、迭代、优先级、故事点和里程碑 |
| 当前迭代 | Board，筛选 `Sprint:@current` | 查看本周任务 |
| 缺陷跟踪 | Table，筛选 `label:bug` | 跟踪真实发现的缺陷；没有缺陷时保持为空 |
| 优先级看板 | Board，按 Priority 分列 | 按 P0、P1、P2 查看任务 |
| 路线图 | Roadmap，使用 Sprint 的起止日期 | 查看各任务所属迭代的排期 |
| 我的任务 | Table，筛选 `assignee:@me` | 查看分配给当前用户的任务 |

将需要跟踪的 Issues 加入 Project，按实际进展更新状态。待讨论的任务放入“待规划”，验收条件与前置条件明确并选入 Sprint 后设为“待开始”；任务开始时设为“进行中”，提交评审时设为“待评审”，通过验收后设为“已完成”。真实缺陷使用 `bug` 标签。

## Issue 与反馈的处理

| 类型 | 仓库模板 | 记录重点 |
| --- | --- | --- |
| 任务 | [task.md](../../.github/ISSUE_TEMPLATE/task.md) | 目的、交付、验收、依赖和关联文档 |
| 缺陷 | [bug_report.md](../../.github/ISSUE_TEMPLATE/bug_report.md) | 复现环境与步骤、预期结果、实际结果和影响 |
| 需求反馈 | [requirement_feedback.md](../../.github/ISSUE_TEMPLATE/requirement_feedback.md) | 具体场景、当前描述的问题、建议与需要核实的依据 |

反馈优先记录在对应任务的 Issue 下。独立的问题可以使用需求反馈模板记录，并链接相关任务或文档。

采纳的反馈链接到修改结果；不采纳的说明原因；仍有疑问的记录待补充信息。

## 分支与评审

`main` 保存已确认的交付。需要并行开发时，从 `main` 建立短期任务分支，合并后及时清理。

一个 PR 对应一项明确的修改，链接相关 Issue，说明修改原因与验证结果。文档变更检查事实、范围和链接；代码变更补充适用的测试、构建和运行验证。使用[PR 模板](../../.github/PULL_REQUEST_TEMPLATE.md)记录这些内容，通过评审后合并。
