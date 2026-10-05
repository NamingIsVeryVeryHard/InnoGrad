# 项目协作流程

本文说明任务管理、需求反馈与评审方式。项目任务通过 [InnoGrad Project](https://github.com/orgs/NamingIsVeryVeryHard/projects/1) 集中管理。

正式文档保存在仓库中，通过 README 导航。Issues 记录任务和讨论，Project 展示任务进展。

## 任务管理

每项任务使用一个 Issue，说明目标、交付内容、验收方式和前置条件，并链接相关文档或产品范围编号。创建前先查看已有任务，避免重复。

任务完成后，在 Issue 中补充交付链接和验证结果，通过验收后关闭。具体任务与交付安排见[阶段计划](../../tasks/plan.md)。

## 项目看板

以下三个主要视图共享同一组 Issues 和任务状态。Project 当前为私有，仅有访问权限的成员可查看。

| 视图 | 布局与筛选 | 用法 |
| --- | --- | --- |
| Kanban | Board，按 Status 分列 | 使用 Backlog、Ready、In progress、In review、Done 跟踪任务进展 |
| Team planning | Table，按 Status 分组、按 Assignees 筛选，显示负责人、状态和标签 | 查看各成员的工作与任务状态 |
| Bug tracker | Table，筛选 `label:bug`，显示状态与负责人 | 跟踪真实发现的缺陷；没有缺陷时保持为空 |

将需要跟踪的 Issues 加入 Project，按实际进展更新状态。任务开始时设为 In progress，提交评审时设为 In review，通过验收后设为 Done；真实缺陷使用 `bug` 标签。

## Issue 与反馈的处理

| 类型 | 仓库模板 | 记录重点 |
| --- | --- | --- |
| 任务 | [task.md](../../.github/ISSUE_TEMPLATE/task.md) | 目的、交付、验收、依赖和关联文档 |
| 缺陷 | [bug_report.md](../../.github/ISSUE_TEMPLATE/bug_report.md) | 复现环境与步骤、预期结果、实际结果和影响 |
| 需求反馈 | [requirement_feedback.md](../../.github/ISSUE_TEMPLATE/requirement_feedback.md) | 具体场景、当前描述的问题、建议与需要核实的依据 |

反馈优先记录在对应任务的 Issue 下。独立的问题可以使用需求反馈模板记录，并链接相关任务或文档。

采纳的反馈链接到修改结果；不采纳的说明原因；仍有疑问的记录待补充信息。

## 分支与评审约定草案

建议由 `main` 保存已评审的交付，`develop` 用于集成中的工作，具体任务使用短期分支。团队分支策略确认后再配置。

一个 PR 对应一项明确的修改，链接相关 Issue，说明修改原因与验证结果。文档变更检查事实、范围和链接；代码变更补充适用的测试、构建和运行验证。使用[PR 模板](../../.github/PULL_REQUEST_TEMPLATE.md)记录这些内容，通过评审后合并。
