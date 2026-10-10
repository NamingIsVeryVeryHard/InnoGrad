# 仓库协作约定

## 项目入口

- 项目概况与当前状态：README.md。
- 合作者参与步骤：[CONTRIBUTING.md](CONTRIBUTING.md)。
- 问题定义：docs/requirements/problem_definition.md。
- 功能范围：docs/requirements/product_scope.md。
- 应用职责与平台边界：docs/software/platform_reuse.md。
- 协作流程：docs/mgmt/project_workflow.md。
- 按任务需要阅读相关文档，避免重复创建已有说明或计划。

## 团队 Skills

- 团队共享 skills、来源版本与 GitHub 授权说明见 [.agents/README.md](.agents/README.md)。
- 按任务使用 `.agents/skills/` 中的现成 skill，只加载相关文档与引用文件。仓库约定与用户授权优先于 skill 中的通用示例。
- 上游正文中的 `skills/<name>/SKILL.md` 路径在本仓库对应 `.agents/skills/<name>/SKILL.md`；其余相对文件引用以该 `SKILL.md` 所在目录解析。
- `gh-cli` 中的 `plugins/gh-cli/` 路径属于上游仓库，按团队 Skills 说明中的固定版本链接查看。
- 需求与文档使用 `spec-driven-development`、`planning-and-task-breakdown`、`documentation-and-adrs`；提交与评审使用 `git-workflow-and-versioning`、`code-review-and-quality`。
- GitHub 内容优先通过 `gh-cli` 使用已认证的 `gh` 读取与管理。操作前确认仓库、Project、字段及现有任务，避免重复创建。
- 任务状态以 Issues 和 Project 为准，交付安排沿用 `tasks/plan.md`；不要另建重复的任务清单或需求入口。

## 应用职责

- `apps/web/` 承载学生、导师、专家和学院管理人员的界面。
- `apps/server/` 承载业务流程、档案、权限及智能体接入，业务模块按需增加。
- 权限检查、审核状态和正式业务记录由服务端管理，智能体输出不得直接替代人工审核结论。

## 修改约定

- 修改前阅读相关文件，检查工作区状态，保留其他人的改动。
- 错误恢复前核对 Git 状态与任务基线，只恢复当前任务拥有的文件。上游 `git reset --hard HEAD` 等示例不构成执行授权；清理、重置或覆盖未提交内容须获得明确授权。
- 验证需要临时改写源文件时，在独立、干净的工作区准备待评审版本并记录基线。恢复前确认文件只含本次验证的改动；发现并发改动时停止并保留现场。
- 只处理当前任务，不顺带重构或增加无关功能。
- 简单、可逆的修改直接推进；涉及产品范围、重大技术选型或破坏性操作时先确认。
- 功能或流程发生变化时，同步更新对应文档。

## 文档要求

- 使用简明、准确、自然的中文，面向不了解项目的读者。
- 区分规划、已实现功能和已验证结果，保留必要的不确定性。
- 不写对话过程、临时操作记录，不引用未公开的内部材料。
- 不主动添加参考资料列表，避免在多份文档中重复相同内容。

## Git 协作与提交规范

1. **分支管理**
   - `main` 为正式交付分支，禁止直接向其提交日常修改。
   - 新任务从最新 `main` 创建独立分支，已有任务优先沿用约定的工作分支。
   - 不得覆盖、强制推送或擅自重置其他成员的修改。
2. **Commit 规范**
   - 使用 Conventional Commits 格式：`type(scope): description`，其中 `scope` 可省略。
   - 允许的主要类型：
     - `feat`：新增功能
     - `fix`：修复缺陷
     - `docs`：文档修改
     - `refactor`：代码重构
     - `test`：测试相关
     - `chore`：配置与维护
   - 提交描述应准确说明修改内容与意图，避免使用 `update`、`misc` 等模糊描述。
   - 每次 Commit 聚焦一项逻辑变更，不混入无关修改。
   - 示例：
     ```text
     docs(requirements): 完善角色权限矩阵
     feat(audit): 新增材料审核接口
     fix(auth): 修复用户权限校验问题
     ```
3. **提交前检查**
   - 检查 `git status` 和待提交差异，运行 `git diff --cached --check`。
   - 文档修改后检查链接、目录说明和跨文档的一致性。
   - 代码修改后运行项目已有的相关测试；当前应用目录尚无构建和测试命令时如实说明，未执行的检查必须说明原因。
   - 严禁提交密钥、Token、真实学生个人材料或未经授权的内部敏感文件。
4. **PR 与评审**
   - 修改通过 PR 合并到 `main`。
   - PR 必须说明修改目的、关联 Issue 和实际验证结果。
   - 评审通过后方可合并；合并建议采用 Rebase 方式以保持线性提交历史。
   - Commit、Push、Merge 等操作遵守仓库授权要求，需明确授权，已有授权不重复确认。
