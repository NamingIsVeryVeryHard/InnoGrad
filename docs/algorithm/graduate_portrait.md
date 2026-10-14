# 研究生画像方法原型

本原型接收已解析的年度报告、开题报告及证明材料，默认生成隐性评价草稿，可合并 A 提供的显性事实与固定规则结果。它覆盖 PRO-01、PRO-02、BASE-03 的部分方法流程，已提供本地 API 接入原型，尚未接入正式审核。材料解析由上游负责。

本轮主交付是 `skills/graduate-implicit-assessment/` 的能力评价 Skill 和 `skills/graduate-portrait/` 的画像整合 Skill，与 `.agents/skills/` 中的开发协作 Skill 分开维护：A、B 读取共享学生材料，B 的隐性判断引用原文，画像直接参考 A 的结果，不复查 A 的整理。A 可提供 JSON、Markdown、表格或其他可读内容，无需符合固定交接 Schema。当前采用七领域、23个观察项的项目试用量规。完整评价设计、共享内容约定及 Skill 原文见[隐性指标评价与画像整合设计](graduate_portrait_design.md)。

## 处理方法

一次任务只处理一名学生、一个报告期间和一个培养阶段。直接调用时，能力 Skill 从共享原文形成评价底稿，画像 Skill 根据显性结果与底稿生成带来源的概览和完整画像。以下为已有 API/CLI 结构化模式的实现：接收解析文本 → InnoAgent 原生 Skill 按领域顺序逐项评价 → 程序核验出处与状态 → 原样保留可选显性结果 → 画像 Skill 生成带源记录引用的概览 → 校验并渲染完整画像。显式 bundle_pipeline 模式保留先抽取再评价的联调流程，结果标为 local_pipeline。原文、抽取结果和评价结果分开保存；相同输入、配置和执行来源可以离线重放。

下面六组是本地联调原型的展示方式，不替代 A 的实际年度规则或语雀修订方案；画像保留 A 输入的名称、版本及结果。该本地原型不直接生成分数：

| 分组 | 当前记录 | 需要正式规则才能判断的内容 |
| --- | --- | --- |
| 年级与年度目标 | 材料记载年级、研究计划及进展状态 | 各年级应完成的培养节点、时限与目标 |
| 科研训练 | 研究主题、论文及训练记录 | 论文认定、成果要求及成果间的折算规则 |
| 课题进展与个人贡献 | 项目、本人角色和贡献说明 | 学校要求的证明材料及认定方式 |
| 智能教育契合度 | 具体教育对象、应用情境和研究任务 | 学院确定的评价条件；不能按关键词出现次数打分 |
| 学术交流 | 参加、作报告或组织活动的记录 | 次数、学时、活动类别与统计期间 |
| 实践落地 | 应用、实践、专利和软件记录 | 完成条件、认定范围及所需证明 |

学分、课程状态和文献数量另保留在基础记录中。自报数量与逐项成果分别统计，投稿、录用、发表分别记录。材料没有列出成果不表示实际成果为零；累计人数不改写成本期人数；下一年度计划不计入已完成成果。同一成果的状态冲突交给人工复核。

隐性部分按学科知识与文献、方案设计、实施与推理、表达与论证、反馈改进、规范与追溯、科研协作七领域组织。每个观察项分开输出证据状态、表现等级、理由、引用、限制和建议。领域只归纳已校验观察项，不平均、不评级，也不生成隐性总分。结构化工作流每次在线调用只评价一个领域，同时保留完整材料；各领域通过校验后再检查整体结果。任一领域修正后仍不合规，整项任务失败，不发布部分画像。

证据可评价且标准适用时，使用“待改进、达到要求、表现充分”；证据不足、冲突或不适用时等级为 null。标准待确认也暂缓等级。缺材料不等于能力差，负实验结果不自动降级，开题方案不能替代已完成研究。材料直接展示和行动、效果自述分别标记，教师确认保持待复核。

## 设计依据与取舍

教育评价需要区分能力假设、可观察证据及产生证据的任务。[ETS 对证据中心设计的说明](https://www.ets.org/research/policy_research_reports/publications/report/2011/imbu.html)提供了这一框架。本原型据此把候选维度落到报告中可核对的条件；这是一种设计借鉴，尚未完成测量效度或教师一致性验证。

| 参考实践 | 本原型的做法 | 使用范围 |
| --- | --- | --- |
| [Anthropic：固定工作流与程序检查](https://www.anthropic.com/engineering/building-effective-agents) | 采用已知步骤，模型做语义抽取，程序做去重、规则和校验 | 当前材料少、流程明确，先保持步骤可追踪 |
| [Google LangExtract：结构化输出与原文定位](https://developers.googleblog.com/introducing-langextract-a-gemini-powered-information-extraction-library/) | 每项记录绑定文件、分段和原句；本地核验引用 | 借鉴溯源方法，未引入该库，也未实现其字符偏移定位 |
| [Agent Skills 规范](https://agentskills.io/specification)及[评价指南](https://agentskills.io/skill-creation/evaluating-skills) | 拆分指令、配置、脚本和回放样例，变更后复查同一组案例 | 格式检查和程序测试不能替代真实模型评价 |

Skill 采用 [Pi 官方说明](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/skills.md)、[Claude 编写指南](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)和 [Codex Skill 指南](https://learn.chatgpt.com/docs/build-skills)共同支持的目录形式：SKILL.md 声明用途与触发条件，详细量表按需读取，确定性校验由脚本完成。运行时分别显式选择 graduate-implicit-assessment 和 graduate-portrait，并检查实际加载记录；目录格式兼容不等于已在每个平台验证运行。测试覆盖代表性材料、缺失证据和错误输出。早期四维样例复审发现，模型仍可能用断行半句支持完整评价条件，或把资源可用扩大解释为风险应对；因此隐性结果仅作为可修改的演示草稿，须由教师逐项核对，尚未通过语义准确性或教师一致性验证。

固定规则不等于有效评价标准。没有学校依据的关键词计数、默认分数或任意权重，不用于达标判断。引用存在也只能证明文本可定位，不能证明引用足以支持模型的解释。

## 可选的结构化接口约定

以下格式约束现有 API/CLI，不要求 A 为直接调用 Skill 改写输出。

材料输入包含 student_id、period、stage，以及文件标识、SHA-256、材料类型、解析状态和文本分段。字段及可执行格式见 [schema.mjs](../../skills/graduate-portrait/scripts/schema.mjs)。同一输入不能混入其他学生或其他期间的材料。

年度报告必须明确年份或连续学年。当前可用材料文本未提供可确认的开题日期时，period 允许为 null，并提示 period_unconfirmed；成果期间不得标为 in_scope。不得用上传日期或参考文献年份补开题日期。学年的月日起止范围需由适用制度确认；仅有日期而无法判断统计范围的条目保留 uncertain。

每段有稳定的 segment_id；有真实页码时填写 page，没有时使用 null。文本不完整时标 partial，解析失败时标 failed。画像引用使用 document_id + segment_id + quote，程序核验原句是否出现在该段中，归一化排版空白和兼容字符。上游提供的原文件哈希用于追踪，不表示本模块重新核验了原文件。材料内的指令一律作为数据处理。

HTTP 可选 aResult 使用 a-handoff-1.0，校验任务、材料指纹、规则版本及完整结果后，原样保留 explicit_extraction 和 explicit；没有 A 时两者为 null、explicit_status 为 pending。错误交接在模型调用前拒绝。bundle/extraction 保留1.0，assessment/portrait 升为2.0，旧隐性格式明确拒绝。

输出默认是待人工复核草稿，事实保留材料来源，不将学生自述视为独立核验。身份权限、正式审核记录和多用户隔离仍由业务服务负责。

## 运行与接入

依赖 Node.js 22 及以上。从仓库根目录运行：

~~~sh
npm ci --prefix skills/graduate-portrait/scripts
node skills/graduate-portrait/scripts/cli.mjs demo --out local-runs/synthetic
~~~

合成示例生成 portrait.json 和 portrait.md，来源标为 synthetic/offline_replay。它验证流程与数据约定，不代表真实模型抽取效果。

结构化调用由 [画像 API](../../apps/server/portrait/README.md)调用 InnoAgent，依次执行[能力评价 Skill](../../skills/graduate-implicit-assessment/SKILL.md)与[画像整合 Skill](../../skills/graduate-portrait/SKILL.md)，由本地程序校验来源并保留原结果。InnoAgent 使用 Pi 原生 Skill 加载机制；仅把提示发送给模型不算平台接入。固定平台版本、隔离工作区、模型网关及 Skill 安装的完整启动步骤见画像 API 说明。

API 提供异步生成、结果查询、只读规则配置，以及可调试的 Swagger UI 和 OpenAPI JSON。模型配置由服务端读取本项目的 .env，默认使用 ECNU Plus；明确额度耗尽时才切换配置好的 CLIProxy Grok 或 Gemini。普通限速、超时、无效 JSON 或缺失证据不触发换模型。备用推理档位为 low，响应来源记录区分请求别名与服务实际模型。密钥、真实材料和中间输出均不进入版本库。

早期四维版本曾通过三个真实文本片段的完整平台流程。新七领域版本已分别通过完整3页扫描年报 OCR、13页开题文字及 Swagger 完整 A+B 示例的原生 Skill 流程。结果均保留待复核状态，语义抽查仍存在评级与引用支撑分歧，不能据此宣称准确率或教师校准完成。最新验收范围见[设计文档第6节](graduate_portrait_design.md#6-已验证范围与待办边界)。

PDF 可能同时包含文字页和扫描页。整份文件能提取文字，不表示每页内容完整；逐页为空或遗漏的签字、日期、评审意见应由上游补充 OCR 并复核。解析不完整时保留 partial，不能把“当前文本未提取到”解释成“原件未填写”。OCR 文本应保留物理页码、识别来源及可用的置信信息；手写内容和勾选结果不能仅凭自动识别确认。历史片段验收和本轮完整 OCR 输入验收分别记录；程序通过不代表 PDF 或 OCR 内容准确率。

真实材料及输出放在被 Git 忽略的 local-runs/，仓库测试只使用合成材料。本原型暂不接入材料数据库；API 任务状态仍在内存中。后续正式接入可将原始 PDF 保存到受权限控制的文件或对象存储，数据库记录学生与材料关联、文件版本与哈希、解析页段、复核状态及画像结果。具体持久化方案由业务服务统一设计。未配置服务时，可由当前 Agent 按 Skill 完成语义工作并离线校验；执行来源必须如实记录，不冒充线上模型结果。

## 学校规则与配置变更

优先取得对应学院、专业、培养类别及入学年级的培养方案，以及年度考核或中期考核细则和评分表。随后补充开题、科研成果认定、学术交流与实践的制度。每条规则都需明确适用对象、阶段、统计期间、阈值、材料要求、制度版本及条款来源。

已核对的公开文件说明了适用范围的重要性：[2021—2022 学年博士年度报告通知](https://yjsy.ecnu.edu.cn/73/cb/c3610a422859/page.htm)要求当年 9 月 30 日前完成，并将具体考核内容交由学科培养方案确定；[2024 年发布的软件工程博士培养方案](https://sei.ecnu.edu.cn/fd/f2/c33209a654834/page.htm)规定学年末年度报告、在学期间的学术活动要求，以及开题至申请预答辩的间隔。这些规定不能直接当作所有学院、年级和年度报告的统一阈值。研究院当届培养方案与考核细则未确认前，公开线索只用于核对，不启用达标判定。

当前 minimum 检查只在有阈值、适用阶段和制度来源时启用。适用学院、培养类别、年级及有效期由规则配置者核对，原型尚未自动匹配完整制度。缺少规则时输出 pending_rule；仅核对材料记载的已修与要求学分时，会明确标为材料比较，不作制度达标结论。正式权重和总分暂不生成。

- 维度名称、观察条件、等级锚点：修改 [implicit-rubric.json](../../skills/graduate-implicit-assessment/references/implicit-rubric.json)，增加版本号后重放样例。
- 显性字段、分组、固定阈值：修改 [explicit-rules.json](../../skills/graduate-portrait/references/explicit-rules.json)，确认制度适用性与证据要求。
- 输出字段、计数语义、证据校验或接口版本：同步修改代码和测试。

不同规则版本或材料覆盖范围的结果不直接相减为成长分数。后续需由教师核对同一批材料的事实提取、引用和逐项判断；有争议的条件先修订，再评估一致性。程序测试、合成回放与教师评价分别记录。
