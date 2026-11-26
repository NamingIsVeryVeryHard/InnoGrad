# 0. 评审注意事项

* 评审对象：分支 `feat/software-copyright-and-research-project`（基于 `main` `a13a2d7`），实现软件著作权（Issue #25）与科研项目阶段成果（Issue #26）前后端提交、校验、进展更新、画像/成长接入与安全加固；涉及源文件 17 个、测试文件 5 个、样例夹具 7 个、设计文档 1 份
* Diff 规模：修改既有文件 13 处（+576 / -204 行），新增核心后端源文件 4 个（583 行）、新增核心前端源文件 2 个（450 行）、新增测试 3 个（925 行）；按模块拆分审核，各新增单文件均 ≤ 360 行（符合 TH-06 strict）
* 评审方式：AI 自审（CodeQualitySkill v2.0.0）+ 人工复核；建议人工复核时长 1.5-2 小时，重点聚焦第 9.4 节列出的 5 项业务与架构关注点
* 本表统计：模板正文第 2–4 章共 36 项（是 33 / 否 0 / 不适用 1 / 未知 0 / 事实项 2），附加第 9.3 节高危补充项 8 项（是 7 / 否 0 / 不适用 0 / 未知 1）；问题统计：Blocker 0 / Critical 0 / Major 9（已修复 9） / Minor 3（已修复 1，保留建议 1，存量移交 1）

# 1.关于代码

| 检查项目 | 结果 | 说明 |
| :---- | :----------: | :---- |
| 模块名 | software-copyright & research-project | 软著（#25）与科研项目阶段成果（#26）材料提交及闭环模块 |
| 审查人员 | AI 自审（CodeQualitySkill v2.0.0） | 人工复核：待项目组负责人指定 |
| 版本 | 1.1 | 第 2 轮复审（v1.0 自检修复 10 项问题后完成全量回归） |
| 日期 | 2026-11-26 | |
| 程序设计语言 | Python 3.12 / JavaScript (ES2022) | 后端 FastAPI + SQLAlchemy；前端原生 ESM + Vite |
| 作者 | jkt（蒋开通） | AI 辅助开发与重构 |
| 文件数 | 17 | 源文件 17（后端 10，前端 7）；另含测试文件 5、样例夹具 7、文档 2 |

# 2.自动检查

| 检查项目 | 结果 | 说明 |
| :---- | :----------: | :---- |
| 代码通过编译，没有任何错误 | 是 | `python -m compileall -q app tests` 退出码 0；`mypy --strict --follow-imports=silent` 5 个核心模块 Error(0)；前端 `npm run build`（Vite 7.3.8，48 modules）构建通过 |
| 代码通过编译，没有任何警告信息 | 是 | `ruff` Warning(0)、`pylint` 10.00/10 Warning(0)、`vite build` Warning(0)（注：pytest 输出 1 条上游第三方库 `.venv/.../fastapi/testclient.py:1` 的 `StarletteDeprecationWarning`，与本次代码无关） |
| 存在单元测试 | 是 | 后端新增 65 项用例（`test_software_copyright.py`、`test_research_project.py`）及 106 项核心回归全部通过，5 个核心模块行覆盖率 **98%**（303 行仅 6 行未覆盖，高于 strict 阈值 80%）；前端 `node --test` 14 项全部通过（注：Windows NTFS 无法模拟 POSIX `chmod 0600/0700`，上游存量 `test_simulation_cohort.py` 与 `test_teacher_agent_planner.py` 在 Windows 下存在与本次变更无关的权限位断言失败） |
| 代码处于源代码版本控制之下 | 是 | 已全部纳入分支 `feat/software-copyright-and-research-project` 并经 `git ls-files` 确认，无未跟踪源文件 |
| 使用检查工具对代码进行了检查 | 是 | 已执行编译、Lint、严格类型检查、复杂度、重复度、安全扫描、格式化与构建 |
| 检查工具名称 | compileall, ruff, mypy, pylint, symilar, radon, bandit, pytest-cov, prettier, vite, npm audit | 未在本地安装 `pip-audit` 与 `gitleaks`，详见 9.3 节如实标为「未知」/说明 |
| 使用检查工具检查的结果 | Error(0) / Warning(0) | `ruff` 0/0（line-length=100，排除中文全角标点 RUF001-003）；`mypy --strict` 0/0；`pylint` 10.00/10；`symilar` 重复率 0.00%（0/704 行）；`radon` 30 个块平均 CC=3.97、最大 CC=10；`bandit` 新增核心 5 模块 0 告警（存量 `agent.py` 见第 5 章）；`prettier` 9 个触碰文件 0 差异；`npm audit --audit-level=high` 0 漏洞 |

# 3.设计

| 检查项目 | 结果 | 说明 |
| :---- | :----------: | :---- |
| 代码已完成（相对于软件功能定义来说） | 是 | 完整覆盖 Issue #25（软件全称、版本号、著作权人、开发工作、登记状态、仅已登记条件必填登记号/日期与证明附件、已归档后正常进展更新）与 Issue #26（项目名称、本人角色、阶段事项、完成时间、可选关联 4 类材料、明确不将关联材料和附件设为必填），同步打通年度报告引用、画像快照、成长观察与教师工作台标签，无占位实现或幻觉 API |
| 选择的算法模型很好 | 是 | 表单规范化与去重均为 O(N) 线性扫描（`copyright_holders` 上限 50、`linked_artifacts` 上限 20）；年度引用与权限校验沿用已有单次索引查询，无循环内远程 I/O 或无界扫描 |
| 采用了恰当的设计模式 | 是 | 采用按 `Submission.kind` 查表分发（`achievement_forms.py`）与无状态纯函数边界校验（`form_utils.py`、`software_copyright_form.py`、`research_project_form.py`），避免在 `main.py` 和 `growth.py` 中堆积多层 `if/elif` 链，同时未引入多余抽象类或工厂模式 |
| 任何缺失的功能都已在代码中清晰的标出 | 是 | 需求范围内全部功能均已实现，无静默占位与遗留 `TODO`/`FIXME`；超出本模块范围的学校基础设施等保项（M1–M12）已在设计文档第 4 章明确标注边界 |
| 代码的结构很好 | 是 | 分层清晰（边界工具层 → 领域表单层 → 统一分发层 → API/流转层 → 前端独立模块），满足 strict 全部阈值：Python 新增核心函数最长 40 行、最大 CC=10（平均 3.97）、最大嵌套 2 层、最大参数 4 个；前端 `achievements-ui.js` 360 行、最长函数 37 行、最大参数 4 个 |
| 存在设计文档 | 是 | 详见 `docs/软著与科研项目成果提交设计.md`（含字段契约、附件角色白名单、架构分层、等保三级符合性矩阵）及 `fixtures/software-project-submissions/` 样例集 |
| 代码与这些文档相符 | 是 | 字段 key、长度上限、枚举白名单、条件必填规则、接口路径、模块划分与 `docs/软著与科研项目成果提交设计.md` 逐项核对一致 |

# 4.对代码编写质量的总体意见

## 风格

| 检查项目 | 结果 | 说明 |
| :---- | :----------: | :---- |
| 代码的布局很清晰 | 是 | 后端通过 Ruff 格式/导入排序检查，前端 9 个触碰文件通过 Prettier 检查（0 差异）；Python 最大嵌套深度 2 层（≤ TH-04 阈值 3）；无对话残留或噪声注释 |
| 代码遵循项目的风格准则 | 是 | 复用项目原有 `main.py` 路由、`error(422, ...)` 中文提示、`paper_materials.py` 白名单风格、纯 ASGI 中间件风格（对齐 `teacher_agent/api.py` 的 `_NoStore`）及 `prototype/` 原生 ESM 渲染约定 |
| 存在良好（无歧义）的公共API | 是 | 公开函数均配有类型标注与文档字符串，参数 ≤ 4 个，无布尔标志参数；外部校验统一抛出明确中文 `ValueError` / `TypeError` 并在 API 边界转换为 HTTP 422 |
| 选择的名称表达清晰和易理解 | 是 | 模块、函数、字段 key 与常量命名直白反映领域语义（如 `SOFTWARE_COPYRIGHT_REQUIRED_FIELDS`、`REGISTRATION_STATUS_LABELS`、`MAX_LINKED_ARTIFACTS`），无魔法数与晦涩缩写 |

## 防御性编程

| 检查项目 | 结果 | 说明 |
| :---- | :----------: | :---- |
| 避免空指针 | 是 | Python 启用 `mypy --strict` 严格检查可空类型（`str | None`、`set[str] | None`）；前端对可选字段统一使用空值兜底（`form?.xxx`、`Array.isArray(...)`） |
| 数据类型选择正确并使用类型检查 | 是 | 5 个核心 Python 模块通过 `mypy --strict` 0 错误；`SubmissionKind` 与 `AttachmentRole` 使用 `Literal` 枚举约束；日期严格校验为 ISO `YYYY-MM-DD` |
| 所有输入都经过验证 | 是 | Pydantic `extra="forbid"` + `form_utils.py` 未知字段拒绝、类型/长度/控制字符/正则/枚举/日期/HTTP(S) URL 校验；`linked_artifacts[].file_id` 强校验属于本次提交的已上传 `file_ids`；前端全量 `esc()` HTML 转义 + `safeHttpUrl()` 阻断 `javascript:`/`data:` 等协议 |
| 限制资源使用 | 是 | 限制单次表单 JSON ≤ 100KB、附件 ≤ 30 个且单文件 ≤ 50MB、著作权人 ≤ 50 名、关联材料 ≤ 20 项、单文本字段长度上限 100–4000 字符、URL ≤ 2000 字符 |
| 控制并发 | 是 | 草稿保存、正式提交、进展更新均沿用 `Submission.lock_version` 乐观锁与 `Idempotency-Key` 幂等重放，防止并发覆盖与重复提交 |
| 避免循环引用 | 是 | 依赖严格单向：`form_utils` ← `software_copyright_form`/`research_project_form` ← `achievement_forms` ← `main`/`extensions`/`growth`/`agent`；前端 `achievements-labels` ← `achievements-ui` ← `app.js`；模块循环依赖数 = 0（TH-12） |
| 不存在特定编译器功能（C/C++） | 不适用 | 本次开发语言为 Python 3.12 与 JavaScript (ES2022)，非 C/C++ |

## 错误处理

| 检查项目 | 结果 | 说明 |
| :---- | :----------: | :---- |
| 错误情况都得到了处理 | 是 | 缺失字段、类型错误、未知字段、非法日期、非已登记填写登记号/日期、跨提交 `file_id`、非法 URL 协议、非法附件角色均有明确错误路径并经测试覆盖 |
| 使用断言来验证逻辑 | 是 | 外部输入不依赖 `assert`（生产 `-O` 安全），全部使用显式异常校验；内部契约通过 `mypy --strict`、`Literal`、`frozenset` 与边界断言测试共同保证 |
| 代码是异常安全(exception safe)的 | 是 | 提交校验 `validate_submission_form` 在数据库写入 `Version`/`AIJob`/`Outbox` 之前执行；请求级 SQLAlchemy `with factory() as session` 在异常时自动回滚，无半成品脏数据 |
| 错误将被传播，而不会被隐藏 | 是 | 表单与材料校验模块零吞异常、零静默兜底默认值；日期解析等异常转换保留 `from exc` 原因链；API 边界统一捕获 `(ValueError, TypeError)` 返回规范 422 |
| 本地有日志文件 | 是 | 关键业务事件（创建、草稿、上传/下载、提交、进展更新、复核、画像快照）统一写入 `Audit` 持久化审计表，全程无 `print` / `console.log` 调试输出且无敏感凭据泄露；应用进程文件日志轮转与 SOC 外发属部署期 M4/M7 基线 |
| 没有任何资源被泄露 | 是 | 数据库会话使用 `with` 上下文管理，文件上传/读取沿用安全上下文句柄；前端事件委托绑定在动态表单根节点上，随视图重绘自动回收 |
| 代码使用多线程 | 是 | 后端基于 FastAPI / ASGI 异步协程并发服务，前端在浏览器事件循环中运行 |
| 它是线程安全的 | 是 | 新增 5 个后端模块均为无状态纯函数，模块级配置均为不可变常量（`tuple`/`frozenset`/只读映射），不存在跨请求共享可变全局状态 |
| 不会发生死锁 | 是 | 新增代码未引入手工互斥锁；数据库写冲突由 `lock_version` 乐观锁与事务内单语句原子更新处理，无交叉锁顺序风险 |

## 结构

| 检查项目 | 结果 | 说明 |
| :---- | :----------: | :---- |
| 不存在冗余的代码 | 是 | Pylint 10.00/10、Ruff 0 错误，无未使用导入/变量/函数，无未使用的过度抽象 |
| 不存在剪切粘贴式的编程 | 是 | `symilar` 跨 5 个核心 Python 模块检测重复率为 **0.00%（0 / 704 行）**；前端公共字典与事实列表渲染已提炼为独立函数复用 |

# 5.代码审查 清单

## 语句级审查

| 文件 | 行 | 问题 | 说明 |
| :---- | :----------: | :----------: | :---- |
| `backend/app/form_utils.py` 等 3 个文件 | — | 类型不匹配时抛出 `ValueError` 而非 `TypeError`（Ruff `TRY004`，共 7 处） | [Major][SM-V08] 改为抛出 `TypeError`，在 `main.py` 边界统一捕获 `(ValueError, TypeError)` 并补充单元测试 【已修复 v1.1】 |
| `backend/app/software_copyright_form.py`、`backend/app/achievement_forms.py` | — | 5 项必填字段元组在两个模块重复定义（Pylint `R0801`） | [Major][SM-D01] 导出 `SOFTWARE_COPYRIGHT_REQUIRED_FIELDS` 与 `RESEARCH_PROJECT_REQUIRED_FIELDS` 常量并在分发层复用 【已修复 v1.1】 |
| `backend/app/software_copyright_form.py`、`backend/app/research_project_form.py` | 103, 105 | `canonicalize_*_form` 分别为 43 行和 41 行，略超 TH-01 strict（≤ 40 行） | [Major][SM-B01] 在 `form_utils.py` 提炼公共 `validate_form_dict`，两函数分别降至 40 行与 38 行 【已修复 v1.1】 |
| `backend/app/achievement_forms.py` | 45 | 使用 `getattr(paper_form, "canonicalize_paper_form")` 触发 Ruff `B009` | [Major][SM-D02] 改为直接引用 `paper_form.canonicalize_paper_form` 并通过 `typing.cast` 通过 `mypy --strict`（零 `# noqa`/`# type: ignore`） 【已修复 v1.1】 |
| `backend/app/main.py` | 114-135 | 初版安全响应头使用 `@app.middleware("http")`，与项目内纯 ASGI 中间件风格不一致 | [Major][SM-V08] 改写为纯 ASGI `_SecurityHeaders` 中间件，与 `teacher_agent/api.py` 的 `_NoStore` 对齐 【已修复 v1.1】 |
| `backend/tests/test_software_copyright.py`、`backend/tests/test_research_project.py` | — | 从其他测试导入 `env` 夹具触发 Ruff `F401`/`F811`/`RUF059` | [Major][SM-V08] 在 `backend/tests/conftest.py` 提供共享 `app_env` fixture 并清理未使用变量 【已修复 v1.1】 |
| `frontend/prototype/achievements-ui.js` | 1-419 | 初版单文件 419 行超过 TH-06 strict（≤ 400 行） | [Major][SM-B02] 拆分字典与安全外链校验至 `achievements-labels.js`（90 行），主文件降至 360 行 【已修复 v1.1】 |
| `frontend/prototype/achievements-ui.js` | 324-360 | `renderVersionStructuredFields` 初版 60 行、5 个参数，超过 TH-01（≤ 40）与 TH-05（≤ 4） | [Major][SM-B01+B03] 提炼 `renderFactList`/`softwareFactPairs`/`projectFactPairs` 并归并 `paperFormat` 参数对象，降至 37 行、4 参数 【已修复 v1.1】 |
| `frontend/` 9 个修改/新增 JS 文件 | — | Windows CRLF 环境下 Prettier 格式校验存在行尾与排版差异 | [Major][SM-V08] 统一执行 `prettier --end-of-line auto --write` 并验证 9 文件全部通过 `--check` 【已修复 v1.1】 |
| `backend/app/achievement_forms.py`、`backend/app/software_copyright_form.py` | — | `missing_required_fields`、`missing_software_copyright_fields`、`submission_display_title` 初版圈复杂度均达 10 | [Minor][SM-B01] 提炼 `find_missing_text_fields` 与 `_DISPLAY_TITLE_CONFIG` 查表，分别降至 7 / 4 / 3，平均 CC 从 5.19 降至 3.97 【已修复 v1.1】 |
| `backend/app/software_copyright_form.py` | 56-76 | `_normalize_copyright_holders` 圈复杂度为 10，处于 TH-02（≤ 10）边界 | [Minor][SM-O01] 当前在阈值内且清晰易读，后续迭代可拆分输入分流与去重逻辑 【保留建议】 |
| `backend/app/agent.py` | 11, 115 | Bandit 对存量 `xml.etree.ElementTree` 报告 B405(Low)/B314(Medium)（上游已做外部实体前置校验） | [Minor][SM-V10] 属上游存量代码非本次需求修改范围，建议另开安全加固 Issue 引入 `defusedxml` 【超出本次范围，记录移交】 |

# 6.跟踪调查

## 评审结论

| 检查项目 | 结果 | 说明 |
| :---- | :----------: | :---- |
| 代码质量较好 | 是 | v1.0 发现 9 项 Major、1 项可降复杂度 Minor，v1.1 已全部关闭；当前 Blocker 0 / Critical 0 / 未关闭 Major 0，编译与静态检查均无 Error |
| 重新编写并验证 | 完成 | v1.1 编译、Ruff、Mypy strict、Pylint 10.00/10、Symilar、Radon、Bandit、106 项后端测试（覆盖率 98%）、14 项前端测试、Prettier、Vite 构建全部通过 |
| 重新编写并重新审查 | 通过 | S3 复检确认无新增阻断、严重或主要级坏味道 |

## 在这里记录审查的结果

| 检查项目 | 结果 | 说明 |
| :---- | :----------: | :---- |
| 审查 | 结果2：通过审查 | AI 自审 v1.1 通过，待人工复核第 9.4 节关注点后合入 |
| 校验 | 结果2：通过校验 | 全部已执行的自动化门禁均通过（`pip-audit` 缺失项见 9.3 节透明披露） |

---

### 9.3 附加章节：模板外补充检查项

| 检查项目 | 结果 | 说明 |
| :---- | :----------: | :---- |
| 不存在硬编码的密钥、口令和环境信息（SM-V05） | 是 | 已完成全量 Diff 人工检查、正则凭据排查及 Bandit 扫描，确认无硬编码密钥、口令、Token 或内网地址（本地未安装 `gitleaks` 二进制） |
| 不存在 SQL、命令、HTML 注入风险（SM-V13） | 是 | 后端全程使用 SQLAlchemy 参数化查询、零 Shell 调用、Bandit 新增模块 0 告警；前端全量经 `esc()` 转义且通过 `safeHttpUrl()` 拦截 `javascript:`/`data:` 并强制 `rel="noopener noreferrer"` |
| 已做鉴权与越权（IDOR）检查 | 是 | 所有新建/保存/上传/提交/下载/进展更新/画像接口均在后端校验会话角色、学生归属与有效 `Supervision` 范围；新增跨学生查看越权、非本人提交越权、跨提交 `linked_artifacts[].file_id` IDOR 专项测试并全部通过 |
| 日志中无敏感信息（SM-V17） | 是 | 审计表仅记录操作动作、用户 ID 与资源 ID，不记录口令、Token 或证件号；业务代码零 `print`/`console.log` |
| 依赖无高危漏洞，新增依赖已锁定版本（TH-14，SM-V18） | 未知 | 本次未新增任何前后端第三方依赖，`requirements.lock.txt` 与 `package-lock.json` 零变更；前端 `npm audit --audit-level=high` 结果为 0 高危漏洞；后端环境未安装 `pip-audit`，建议在 CI 中执行 `pip-audit -r backend/requirements.lock.txt` 验证存量依赖 |
| 单元测试有效：有断言，覆盖异常路径，未 Mock 被测对象（SM-V06） | 是 | 65 项后端测试（直连真实 FastAPI + SQLite + 本地文件存储）与 14 项前端测试均包含明确业务/状态码/数据结构断言，覆盖正常、边界、异常与越权路径，未 Mock 被测逻辑 |
| 变更聚焦，无超范围修改（SM-V10，TH-11） | 是 | 仅改动与软著（#25）、科研项目（#26）及等保应用层响应头直接相关的模块，未改动无关的 `paper_form.py`、`teacher_agent/` 或历史迁移脚本 |
| 公共接口和数据结构的变更向后兼容，或附有迁移方案 | 是 | `Submission.kind` 原列长为 `String(30)` 无需破坏性迁移（`alembic check` 通过）；`normalize_file_roles` 保留默认 `kind="paper"`；`/portrait` 与 `/growth` 仅向后兼容地追加软著/科研项目计数字段，存量论文与年度报告行为保持 100% 兼容 |

### 9.4 附加章节：给人工评审者的关注点

1. **已登记软著的附件策略**：当前实现遵循 Issue #25 口径——登记状态为「已登记」时强制要求登记号、登记日期及至少 1 份证明附件，而「未登记 / 申请登记中」允许 0 份附件先建档、获证后通过 `/updates` 更新为已登记。请业务负责人确认「已登记」时是否进一步强制要求附件角色中**必须包含 `copyright_certificate`（登记证书）**，还是保留当前“至少 1 份任意有效软著附件”的宽松策略。
2. **软著版本号与登记号正则范围**：当前版本号白名单为 `^[A-Za-z0-9][A-Za-z0-9._+-]{0,49}$`（不允许空格或中文），登记号支持 4–64 位中英文数字及 `-/._`（兼容 `2026SR1234567` 与 `软著登字第...号`）。请确认学院实际常见软著证书编号或历史版本号是否存在需要放宽的特殊符号（如全角括号）。
3. **科研项目关联材料链接与附件组合**：当前 Issue #26 约定关联材料可选，新增一条关联材料时 `artifact_type` 与 `name` 必填、`url` 与 `file_id` 均为选填（即允许仅记录材料名称与说明，不强制附链接或文件）。请确认是否需要在“填写了某条关联材料时”要求 `url` 与 `file_id` 至少二选一。
4. **教师工作台问答对新成果类别的覆盖范围**：本次已同步补充 `frontend/teacher-chat/field-labels.js` 字段中文映射，使展示层可正确渲染软著与科研项目字段，但未修改 `backend/app/teacher_agent/` 的自然语言查询规划器（该模块归属教师查询组）。后续若需支持教师自然语言检索软著与科研项目，建议单独排期对接。
5. **等保三级非应用层基线项（M1–M12）的团队分工**：本次已在代码层落实服务端细粒度鉴权与防 IDOR、边界输入校验与防 XSS/注入、不可变版本与 SHA-256 完整性、安全响应头与审计记录；统一认证/双因素、登录失败锁定、三权分立、审计日志外发 SOC、HTTPS/WAF/堡垒机、异地备份与公安备案等基础设施要求（`docs/软著与科研项目成果提交设计.md` 第 4 章）须在全队部署上线阶段与校方运维协同确认。
