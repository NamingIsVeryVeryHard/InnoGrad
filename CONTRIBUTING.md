# 贡献指南

欢迎参与 InnoGrad 的需求、文档与代码协作。项目当前处于需求分析阶段，尚无可运行版本；具体状态见 [README](README.md)。

## 开始参与

1. 阅读 [README](README.md)、[产品范围](docs/requirements/product_scope.md)与本次任务相关的文档，确认修改范围。
2. 查看 [Issues](https://github.com/NamingIsVeryVeryHard/InnoGrad/issues) 和[项目看板](https://github.com/orgs/NamingIsVeryVeryHard/projects/1)。认领已有任务时先在 Issue 中沟通，确认负责人和前置条件，避免重复工作。
3. 获取仓库副本，在短期任务分支中修改，例如 `codex/update-requirements`。`main` 保存经过评审的交付。

仓库和 Project 的权限分别管理。推送到本仓库需要相应仓库权限，编辑看板需要 Project 的 Write 或 Admin 权限；权限不足时联系项目管理员。Project 公开可读，读取成功不代表可以编辑。

## 提出任务、缺陷或需求反馈

先查找已有 Issue。与现有任务相关的反馈记录在该 Issue 下，独立工作使用对应模板：

| 类型 | 模板 | 需要说明 |
| --- | --- | --- |
| 任务 | [任务模板](.github/ISSUE_TEMPLATE/task.md) | 目的、交付物、验收条件、验证方法与依赖 |
| 缺陷 | [缺陷模板](.github/ISSUE_TEMPLATE/bug_report.md) | 复现步骤、预期与实际行为、环境和影响 |
| 需求反馈 | [需求反馈模板](.github/ISSUE_TEMPLATE/requirement_feedback.md) | 使用场景、当前问题、建议与待核实的依据 |

问题与任务以 Issues 为入口，进度保存在 Project，正式交付保存在仓库。阶段安排见[交付与验收计划](tasks/plan.md)，详细操作见[协作流程](docs/mgmt/project_workflow.md)。

## 从任务到交付

1. **明确任务。** 与负责人确认交付内容、验收条件及依赖；需求变更先讨论范围，再修改文档或代码。
2. **安排迭代。** Sprint 为一周，周四开始、周三结束。按团队计划设置 Assignees、Sprint、Priority 和 Milestone，故事点由团队估算。
3. **完成修改。** 从 `main` 建立任务分支，只处理约定范围。开始工作后，将 Project 状态更新为“进行中”。
4. **验证交付。** 文档检查事实、范围、编号、图表和链接的一致性；代码运行仓库已有的相关测试与构建。记录实际结果，说明未完成的检查。
5. **提交 PR。** 使用 [PR 模板](.github/PULL_REQUEST_TEMPLATE.md)，说明修改目的、关联 Issue、主要修改、验证结果和待确认事项。提交评审后，将任务状态更新为“待评审”。
6. **完成验收。** 处理评审意见，通过评审后由有权限的成员合并。任务满足验收条件后，在 Issue 中补充交付链接和验证结果，再关闭任务。

仅当 PR 完整完成某个 Issue 时使用 `Fixes #123`；只覆盖部分工作时使用普通 Issue 链接。将任务标为“已完成”前先检查验收结果，因为 Project 的关联规则可能自动关闭 Issue。

## 使用 Codex 与团队 Skills

团队共享的现成 skills 位于 `.agents/skills/`，随仓库拉取即可获得。在 Codex 中打开仓库后，先阅读 [AGENTS.md](AGENTS.md)；GitHub CLI 登录、Project 授权、skill 选择和版本更新见[团队 Skills 说明](.agents/README.md)。

每位成员使用自己的 GitHub 账号。任务说明应写清允许修改的内容；提交、推送、合并及其他远端修改按仓库授权约定执行。

可以这样开始一个任务：

> 先读取 CONTRIBUTING.md、AGENTS.md 和我认领的 Issue。使用仓库已有 skills，检查相关需求与验收条件，完成约定范围的修改并报告验证结果。

## 提交前检查

- [ ] 修改与任务范围一致，保留其他人的改动。
- [ ] 规划、已实现功能与已验证结果区分清楚。
- [ ] 文档链接、目录说明及相关文档内容一致。
- [ ] 适用的检查已完成，未运行的测试或构建已说明原因。
- [ ] 执行 `git diff --check`；提交前检查暂存差异并执行 `git diff --cached --check`。
- [ ] PR 包含交付与验证信息，关联了对应任务。
- [ ] 未提交密钥、真实学生个人材料或未经授权的内部文件。
