# 团队 Skills 与 GitHub Projects

本目录保存团队共用的现成 skills。它们帮助 Codex 按既定流程编写需求、拆分任务、管理 GitHub 内容和提交评审。Skills 的指令与引用文件随仓库同步，GitHub 登录凭证由每位成员自行管理。

## 开始使用

1. 克隆仓库，已有副本则按团队 Git 流程拉取更新。
2. 在 Codex 中打开仓库目录。Codex 会发现 `.agents/skills/` 下的 skills；若更新后没有显示，在该仓库中新开会话或重启 Codex。
3. 安装 GitHub CLI，用自己的账号登录并授权 Projects：

   ```sh
   gh auth login --hostname github.com --git-protocol https --web --scopes project
   gh auth status
   ```

   已登录的成员可补充授权：

   ```sh
   gh auth refresh --hostname github.com --scopes project
   ```

4. 读取项目与任务，确认当前账号能访问目标内容：

   ```sh
   gh project view 1 --owner NamingIsVeryVeryHard --format json
   gh project field-list 1 --owner NamingIsVeryVeryHard --format json
   gh issue list --repo NamingIsVeryVeryHard/InnoGrad
   ```

拉取仓库即可获得共享 skills，无需再运行 skills 安装器。成员个人安装的其他 skills 不属于团队共享配置；同名个人 skill 可能同时被发现，任务中应明确使用本仓库版本。

仓库代码权限与 Project 权限分别管理。Project 公开可读，编辑需要 Project 的 Write 或 Admin 权限。能读取项目、拥有仓库权限或已授权 `project` scope，都不能单独证明具有 Project 编辑权限。权限不足时，由组织或 Project 管理员检查访问设置。不要共享登录凭证或将 token 写入仓库。

## 共享 Skills

| 工作 | Skill | 来源 |
| --- | --- | --- |
| 通过已认证的 CLI 访问 GitHub | [gh-cli](skills/gh-cli/SKILL.md) | Trail of Bits |
| 编写需求与验收条件 | [spec-driven-development](skills/spec-driven-development/SKILL.md) | Addy Osmani |
| 拆分任务、明确依赖与验收 | [planning-and-task-breakdown](skills/planning-and-task-breakdown/SKILL.md) | Addy Osmani |
| 编写文档与记录设计决定 | [documentation-and-adrs](skills/documentation-and-adrs/SKILL.md) | Addy Osmani |
| 分支、提交与 PR | [git-workflow-and-versioning](skills/git-workflow-and-versioning/SKILL.md) | Addy Osmani |
| 检查差异与质量 | [code-review-and-quality](skills/code-review-and-quality/SKILL.md) | Addy Osmani |

需求 skill 的后续实现流程还引用了以下 3 个 skills，一并保留：

- [incremental-implementation](skills/incremental-implementation/SKILL.md)：分步交付与验证。
- [test-driven-development](skills/test-driven-development/SKILL.md)：通过测试验证代码行为。
- [context-engineering](skills/context-engineering/SKILL.md)：按任务加载相关文档与代码。

这些 skills 以需求、任务、文档和评审为当前使用重点。选择与本次工作有关的 skill 即可；尚未纳入仓库的专项 skills，应在对应工作开始时评估并通过 PR 引入。

可以直接向 Codex 提出具体任务，例如：

> 用本仓库的 planning-and-task-breakdown 和 gh-cli，查看现有第二周 Issues，补齐交付物、验收条件和依赖，避免创建重复任务。

Skills 提供操作指引；执行 GitHub 操作仍需要可用的 `gh`、账号授权和相应资源权限。这里共享的是 skill 文件，未安装 Trail of Bits 的 Claude Code hooks。

## GitHub Projects 操作约定

- 仓库：[`NamingIsVeryVeryHard/InnoGrad`](https://github.com/NamingIsVeryVeryHard/InnoGrad)。
- Project：[`NamingIsVeryVeryHard` 的第 1 个项目](https://github.com/orgs/NamingIsVeryVeryHard/projects/1)。所有 `gh project` 命令显式传入 `--owner NamingIsVeryVeryHard`。
- 任务管理与验收以[协作流程](../docs/mgmt/project_workflow.md)为准，交付安排见[阶段计划](../tasks/plan.md)。先读取已有 Issue、PR、字段与迭代，再更新内容。
- Sprint 为一周，周四开始、周三结束。创建或分配迭代时，以 Project 的 `Sprint` 字段配置为准。
- 字段名使用英文，状态与迭代名称沿用 Project 的现有值。执行前实时读取字段、选项与迭代 ID，避免使用过期 ID 或创建重复字段。
- Labels、Assignees 和 Milestone 更新对应 Issue 或 PR；Project 的自定义字段使用 `gh project`，需要时通过 `gh api graphql` 调用官方 API。
- 关闭 Issue、将任务标为完成之前，核对交付与验收结果。读取现有 Workflows，检查字段更新是否会触发关联 Issue 的状态变化。
- Skills 不会新增 API 能力。内置 Workflows 的配置和 Insights 图表设置等操作，仍可能需要 GitHub 网页。

## 来源与更新

[skills-sources.json](skills-sources.json)记录各文件的来源路径、固定提交 SHA、许可证与 SHA-256。它是来源清单，不能用于 `npx skills install`，也不会自动升级文件。

| 上游 | 固定提交 | 许可证 |
| --- | --- | --- |
| [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills/tree/1401c8b8030e023baeebb31781a6653fe8e93026) | `1401c8b8030e023baeebb31781a6653fe8e93026` | [MIT](licenses/addyosmani-agent-skills-LICENSE)，Copyright (c) 2025 Addy Osmani |
| [trailofbits/skills](https://github.com/trailofbits/skills/tree/82fe8226252622fa807643bdca1710901198553a/plugins/gh-cli) | `82fe8226252622fa807643bdca1710901198553a` | [CC-BY-SA-4.0](licenses/trailofbits-skills-LICENSE)，Trail of Bits |

所列上游文件均保留原文，未作修改。许可证分别适用于对应来源的文件；项目自己的文档不因此更改许可证。

升级时在任务分支中查看上游差异，选定新的固定提交，更新 skill、所需引用文件和来源清单，通过 PR 评审后同步给团队。保留各来源的署名与许可证；若修改上游文件，在来源清单中说明修改。`references/` 保持上游相对目录关系，更新时检查 skill 中的文件引用能否解析。
