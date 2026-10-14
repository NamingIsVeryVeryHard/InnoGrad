# 研究生画像原型 API

本地服务把已解析材料交给 InnoAgent 的 `graduate-portrait` Skill，返回待人工复核的画像草稿。显性部分按材料记录统计和核对，隐性部分按配置的评价标准判断材料支持程度。没有制度原文的阈值保持待配置，不得据此认定学生达标。

## 准备本地运行环境

需要 Node.js 22 或更新版本、Git 和已登录的 GitHub CLI。下面的命令从仓库根目录执行。模型密钥只填入本地 `.env`；接口和浏览器不接受密钥。已有 `.env` 时补齐缺少的变量，不覆盖现有配置。

首次创建配置：

```sh
cp .env.example .env
npm --prefix .agents/skills/graduate-portrait/scripts ci
npm --prefix apps/server/portrait ci
```

按 `.env.example`填写 ECNU Plus 的 `PORTRAIT_API_KEY`，保留或按实际服务调整 `PORTRAIT_API_URL`、`PORTRAIT_API_MODEL`与超时值。备用服务使用模板中的 `PORTRAIT_FALLBACK_GROK_*`、`PORTRAIT_FALLBACK_GEMINI_*`；只有明确额度耗尽时才切换，普通429、结构或证据错误不换模型。以下本机端口须与后续命令一致：

```dotenv
INNOAGENT_URL=http://127.0.0.1:3147
INNOAGENT_MODEL_AUDIT_URL=http://127.0.0.1:3148
INNOAGENT_TIMEOUT_MS=240000
```

连接顺序为画像 API（3001）→ InnoAgent（3147）→ 模型网关（3148）→ `.env`指定的模型服务。`local-runs/`已被 Git 忽略，用于隔离实例和本地结果；其中的会话和工作区可能包含材料，不要提交。

### 构建固定版本的官方 InnoAgent

首次在新的目录检出[官方仓库](https://github.com/hhyqhh/inno-agent)，固定到已核对接口的提交。已有同名源码目录时先确认其版本，不覆盖本地修改。

```sh
mkdir -p local-runs
gh repo clone hhyqhh/inno-agent local-runs/innoagent-source
git -C local-runs/innoagent-source checkout --detach 5be785f8cc0a89394b858c123d60738078a597cb
(cd local-runs/innoagent-source && npm ci --ignore-scripts --no-audit --no-fund)
(cd local-runs/innoagent-source && npm --workspace inno-agent run build)
```

### 安装 Skill 与隔离配置

InnoAgent 不会自动发现仓库的 `.agents/skills/`。首次在新的运行目录安装[画像 Skill](../../../.agents/skills/graduate-portrait/SKILL.md)，排除依赖和环境文件；以后修改 Skill 时同步这些文件，再重启 InnoAgent。工作流会检查平台加载的 `SKILL.md`与仓库文件完全一致。

```sh
mkdir -p local-runs/innoagent/skills/graduate-portrait
mkdir -p local-runs/innoagent/home local-runs/innoagent/data local-runs/innoagent/workspace
rsync -a --exclude=node_modules --exclude='.env' --exclude='.env.*' \
  .agents/skills/graduate-portrait/ local-runs/innoagent/skills/graduate-portrait/
npm --prefix local-runs/innoagent/skills/graduate-portrait/scripts ci
```

新建 `local-runs/innoagent/config.json`：

```json
{
  "defaultProvider": "ecnu",
  "defaultModel": "ecnu-plus",
  "providers": {
    "ecnu": {
      "baseUrl": "http://127.0.0.1:3148/v1",
      "apiKey": "local-gateway",
      "api": "openai-completions",
      "bypassProxy": true,
      "models": [{
        "id": "ecnu-plus",
        "name": "ECNU Plus",
        "reasoning": false,
        "input": ["text"],
        "contextWindow": 128000,
        "maxTokens": 16000
      }]
    }
  },
  "memory": { "l1Enabled": false, "l2Enabled": false, "l3Enabled": false },
  "subagents": { "enabled": false },
  "mcp": { "enabled": false },
  "plugins": {
    "todo": { "enabled": false },
    "webAccess": { "enabled": false },
    "computerUse": { "enabled": false },
    "codemode": { "enabled": false },
    "permissionSystem": { "enabled": true, "mode": "default" }
  }
}
```

`local-gateway`是本机连接的占位字符串，真正的模型密钥由网关读取 `.env`。画像流程不需要持久记忆、子智能体或外部工具；保留默认权限审批。阶段任务若请求工具审批或用户交互，本地结束等待并返回 `TOOL_APPROVAL_REQUIRED`，同时尝试取消对应的 InnoAgent 执行；上游取消结果需确认，重试前请检查 InnoAgent。

该固定版本的官方服务按数字端口调用 `listen`，没有主机参数。创建以下启动适配文件，将监听限制在本机；它不修改官方源码，也不是隔离沙箱：

```sh
cat > local-runs/innoagent/loopback.mjs <<'JS'
import net from 'node:net';
const original = net.Server.prototype.listen;
net.Server.prototype.listen = function (...args) {
  if (typeof args[0] === 'number') args.splice(1, 0, '127.0.0.1');
  return original.apply(this, args);
};
JS
```

## 启动与调试

按以下顺序在三个终端启动。每个终端均从仓库根目录运行，并保持进程运行。

终端一启动模型网关，读取明确指定的环境文件，监听 `127.0.0.1:3148`：

```sh
PORTRAIT_ENV_FILE="$(pwd)/.env" node --input-type=module -e \
  "import { startModelGateway } from './.agents/skills/graduate-portrait/scripts/gateway.mjs'; await startModelGateway();"
```

终端二启动官方 InnoAgent，所有运行目录均明确指定，监听 `127.0.0.1:3147`：

```sh
node --import "$(pwd)/local-runs/innoagent/loopback.mjs" \
  "$(pwd)/local-runs/innoagent-source/apps/inno-agent/dist/server.js" \
  --home "$(pwd)/local-runs/innoagent/home" \
  --config "$(pwd)/local-runs/innoagent/config.json" \
  --data "$(pwd)/local-runs/innoagent/data" \
  --skills-dir "$(pwd)/local-runs/innoagent/skills" \
  --workspace-dir "$(pwd)/local-runs/innoagent/workspace" \
  --port 3147
```

先确认 [InnoAgent Skills](http://127.0.0.1:3147/api/skills)中的 `graduate-portrait`同时满足 `loaded: true`与 `enabled: true`。终端三启动画像 API：

```sh
PORTRAIT_ENV_FILE="$(pwd)/.env" npm --prefix apps/server/portrait start
```

`PORTRAIT_ENV_FILE`明确指定仓库根目录的环境文件，不搜索父目录。在 API 子目录启动时，也须把它设置为该文件的绝对路径。停止服务时在对应终端按 Ctrl+C；重启顺序同上。模型网关的调用记录仅存于进程内，重启后清空。

默认只监听 `127.0.0.1:3001`。用 `PORTRAIT_PORT` 指定其他端口。浏览器打开 [Swagger UI](http://127.0.0.1:3001/docs/)可查看结构、展开接口并使用 **Try it out** 调试；[OpenAPI JSON](http://127.0.0.1:3001/openapi.json)供其他客户端读取。

| 接口 | 用途 |
| --- | --- |
| `POST /api/portraits` | 提交 `{ "bundle": ... }`，返回 `202`、任务标识和 `Location` |
| `GET /api/portraits/{id}` | 查询 `running`、`completed` 或 `failed`；完成时含 `portrait` |
| `GET /api/portrait-config` | 读取当前显性规则和隐性评价标准 |
| `GET /docs/` | 浏览并调试 API |
| `GET /openapi.json` | 获取 OpenAPI 3 文档 |

`bundle` 使用 Skill 的共享 JSON Schema，包括学生标识、期间、阶段、文档哈希和原文段落。材料必须已经完成解析，文件上传和 OCR 不在此服务范围内。输入上限为 1 MiB。

Swagger 的请求示例下拉框提供两份独立编写的全虚构报告，也可直接读取 JSON 用于本地调试：

- [年度报告示例](examples/annual-report.synthetic.json)：封面、2027—2028学年学习科研总结、下一学年计划和未勾选评定意见。正文区分本期与累计成果、已发表、录用未见刊、审稿及写作状态，并说明作者角色和交流情况。
- [开题报告示例](examples/proposal-report.synthetic.json)：基本信息、研究意义与现状、问题目标、方法实验计划、可行性风险、进度安排及未填写评审意见。`period: null`表示没有确认统计学年，计划不算已完成成果。

示例中的姓名、学校、题目和数字均为虚构，没有复制真实材料正文。两份文本分别按4页和6页模拟分页；`page`只用于定位合成文本，不对应真实PDF。`sha256`是按 `segments`顺序将各段 `text`以换页符 `\f`连接后，计算 UTF-8 字节所得的哈希，不是PDF文件哈希。示例没有原始PDF，来源名称和各页均作了标注。`parse_status: complete`只说明这些合成文本完整提供，不证明真实材料完成解析。

旧[合成材料构造器](../../../.agents/skills/graduate-portrait/scripts/synthetic.mjs)继续用于边界测试，新演示文件不改变其测试语义。切换或编辑 Swagger 示例不会调用模型；点击 **Execute**提交 `POST`会启动真实生成任务。

生成过程是异步任务。`202`只表示接受任务，按响应中的 `Location`查询结果。任务失败时，`error.code`说明配置、网络、超时、配额或结构校验问题；响应不包含上游错误原文。超过5分钟会停止本地等待，任务状态为 `failed`、错误代码为 `JOB_TIMEOUT`。InnoAgent 后端可能仍在执行，晚到结果不保存；确认上游执行结束前请勿重试。成功结果的 `review_status`始终为 `draft`。

## 原型范围

任务和结果仅保存在当前进程内，默认30分钟后删除，重启后丢失。最多保存20条任务，同时保留2次本地执行等待；这不保证上游超时后的执行数量。满额返回 `503`与 `Retry-After`。重复 `POST`会创建新任务并再次调用模型，重试前先查询已有任务。

服务通过 `skill-bridge.mjs`复用 MJS 画像实现，TypeScript 声明只描述接口边界，实际输入校验和输出 Schema 与 Skill 共享。默认执行函数调用真实 InnoAgent；缺少入口配置时返回失败任务。测试可注入执行函数，不能将测试结果当作在线运行证据。

这不是完整业务平台：没有登录授权、数据库、审核提交和正式档案写入。只在本机调试；需要多人访问或持久保存时，应先补齐服务端权限和存储设计。

## 验证

在仓库根目录运行：

```sh
npm --prefix apps/server/portrait test
npm --prefix apps/server/portrait run typecheck
npm --prefix apps/server/portrait run build
```

接口测试覆盖输入一致性、异步任务、草稿结果、错误脱敏、超时取消、容量限制、过期、关闭取消、OpenAPI 和 Swagger 页面。真实 InnoAgent 与真实模型调用需要单独验证，测试中的合成执行函数不能证明在线效果。
