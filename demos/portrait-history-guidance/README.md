# 真实材料画像对应与建议 Demo

这个 Demo 用已有的本地材料和画像结果，演示一条不改动原评价的处理链：

1. 检查 bundle、portrait、学生标识、文档 hash 和引文页段是否一致；
2. 保留当前材料中的研究目标、任务计划和已有画像；
3. 将参照材料与当前材料按观察项对应；
4. 根据当前材料已有的缺口整理建议；
5. 将“发现相关材料”和“学生已经采纳或执行建议”分开记录。

它是 InnoGrad 接入 TRIPLE 思路的命令行方法 Demo。程序使用确定性规则，不调用模型、不重新评分，也不把材料中的研究计划当作已完成实验。材料没有明确提供的态度、感知他人期望、主观控制感、个人困难、实际可用资源、连续行为事件和学生反馈均保持 `unknown`。

## 运行真实案例

需要 Node.js 22 或更高版本，不需要安装 npm 依赖。真实 manifest 和结果放在 Git 忽略的 `local-runs/` 中，不能把姓名、原文或学号复制进仓库。

```sh
cd demos/portrait-history-guidance
npm start
node run.mjs --input /path/to/local-runs/portrait-history-guidance-real/case.json
node run.mjs --input /path/to/local-runs/portrait-history-guidance-real/case.json --json > /tmp/portrait-history-result.json
npm test
```

`npm start` 默认显示帮助。`--input` 指向本地 manifest；默认输出中文 Markdown，`--json` 输出输入包和结果 JSON。程序只读取 manifest 引用的本地文件，不启动网页或 HTTP 服务，也不访问外部服务。

真实案例使用两份已有 portrait 2.0 和对应 bundle：一份作为参照材料，一份作为当前材料。运行结果应继续保留在 `local-runs/`，不加入 Git。

## 输出边界

- 当前画像中的 `current_work`、`demonstrated`、`attention` 和 `next_steps` 原样保留，并将画像来源映射到原文页段。
- 同一观察项的参照结果和当前结果并列展示；任务不同、材料范围不同或时间关系不明确时，不输出成长分，也不把当前材料解释为收到旧建议后的结果。
- 当前材料中已出现基线、指标或实验计划时，建议转向仍缺少的数据划分、偏差控制、失败解释、风险应对、职责分工或伦理材料等缺口，不机械重复旧建议。
- “发现相关材料”只表示能找到对应材料。建议是否送达、学生是否采纳、是否执行以及是否有效，均保持未知，除非另有明确记录。
- 研究目标属于材料中明确写出的内容；态度、他人期望、控制感和困难需要学生自述，不能从研究主题、算力需求或画像文字反推。
- 程序不会根据两份材料之间的相似点推断稳定习惯、人格、实际能力变化或心理原因。

## 测试

```sh
npm test
```

测试使用仓库内的最小虚构 fixture，验证身份、hash、来源引用、页段定位、未知状态和建议边界。研究指导入口的测试还覆盖模型契约、引文修正重试、纯文本、跨材料同名页段和失败记录；需要先安装画像脚本已有的 Ajv 依赖，命令见[研究指导原生运行](#研究指导-skill-的原生运行)。测试不消耗模型额度，也不替代真实材料运行。

## 与现有画像 Skill 的关系

当前实现独立于 [`workflow.mjs`](../../skills/graduate-portrait/scripts/workflow.mjs)、[`synthesis.mjs`](../../skills/graduate-portrait/scripts/synthesis.mjs) 和 [`contracts.ts`](../graduate-portrait/src/contracts.ts)，不会修改生产画像契约。后续正式接入时，可以把经过授权的历史事件、学生自述、任务条件和反馈记录作为独立输入包，再由服务端校验权限、来源状态和业务身份。

本 Demo 只负责本地证据适配和结果组织。它没有实现语义抽取、心理推断、正式审核或模型效果评估。

若需真实模型生成研究指导，使用独立的[研究指导 Skill](../../skills/graduate-research-guidance/SKILL.md)。其 CLI 接收当前报告及可选历史材料、已有画像，输出 JSON、中文 Markdown 和调用记录。该模型入口与本 Demo 的 `run.mjs` 分别执行；模型结果按同组原始输入复验，不能用本地规则结果冒充模型生成。

## 研究指导 Skill 的原生运行

结构化入口的输入范围见[输入契约](input-contract.md)，字段及校验规则见[输出契约](output-contract.md)。

研究指导由 InnoAgent 加载 `graduate-research-guidance` 后执行。CLI 负责组装输入、校验结果和保存产物；模型请求由 InnoAgent 发出，经模型网关转交 ECNU Qwen。安装并启动固定版本 InnoAgent 与网关的方法见[画像 Demo](../graduate-portrait/README.md#安装-skill-与隔离配置)。不以单独调用 Qwen 的脚本代替 Skill 验收。

### 安装与加载

在该运行目录中增加业务 Skill，排除依赖和环境文件：

```sh
rsync -a --exclude=node_modules --exclude='.env' --exclude='.env.*' \
  skills/graduate-research-guidance/ \
  local-runs/innoagent/skills/graduate-research-guidance/
```

随后重载或重启 InnoAgent。通过 `GET /api/skills` 确认新 Skill 的 `loaded`、`enabled` 均为 true。入口还会读取 `/api/skills/graduate-research-guidance/content`，逐字核对仓库中的 SKILL.md；版本不一致时不执行。

### 执行与复验

需要 Node.js 22 或更高版本及画像脚本已有的 Ajv 依赖。模型网关使用显式指定的 `.env` 读取 ECNU URL、请求模型与密钥；研究指导入口只需要平台地址：

```sh
npm ci --prefix skills/graduate-portrait/scripts
export INNOAGENT_URL='http://127.0.0.1:3147'
export INNOAGENT_MODEL_AUDIT_URL='http://127.0.0.1:3148'
export INNOAGENT_TIMEOUT_MS='900000'
```

也可以设置 `PORTRAIT_ENV_FILE` 指向调用者选择的 `.env`。程序不搜索其他工作区的配置；指定文件无法读取时直接报错。

分别运行当前报告和含历史报告两组案例，输出目录须为空：

```sh
node skills/graduate-research-guidance/scripts/cli.mjs run \
  --current /path/to/current.report.json \
  --out local-runs/research-guidance/current-only

node skills/graduate-research-guidance/scripts/cli.mjs run \
  --current /path/to/current.report.json \
  --history /path/to/annual.report.json \
  --portrait /path/to/current.portrait.json \
  --out local-runs/research-guidance/with-history
```

入口新建独立 InnoAgent 会话，通过 `/skill:graduate-research-guidance` 调用。任务包内提供本轮原文和 Schema，模型无需再次读取文件或运行脚本。结构或引用失败时，在同一会话修正一次；仍失败则以非零状态退出。

成功后生成 `result.json`、中文 `result.md` 和 `run.json`。记录平台、会话、已加载 Skill 哈希、实际 provider、请求及接口返回模型和逐次请求状态；接口未返回模型名时保留 null。失败时 run.json 标为 failed；无法取得模型审计信息时不声称已确认模型调用。重跑使用新目录。密钥不写入结果或日志。

复验须提供生成时的同组原始输入：

```sh
node skills/graduate-research-guidance/scripts/validate.mjs \
  local-runs/research-guidance/with-history/result.json \
  --current /path/to/current.report.json \
  --history /path/to/annual.report.json \
  --portrait /path/to/current.portrait.json

npm test --prefix demos/portrait-history-guidance
```

测试使用虚构数据及本地模拟服务，不消耗模型额度。真实材料、结果和配置只保存在 Git 忽略目录。结构与引用定位通过后，仍须核对事实概括和建议的语义。
