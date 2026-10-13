# 研究生画像原型 API

本地服务把已解析材料交给 InnoAgent 的 `graduate-portrait` Skill，返回待人工复核的画像草稿。显性部分按材料记录统计和核对，隐性部分按配置的评价标准判断材料支持程度。没有制度原文的阈值保持待配置，不得据此认定学生达标。

## 启动与调试

需要 Node.js 22 或更新版本。先按[画像 Skill](../../../.agents/skills/graduate-portrait/SKILL.md)配置服务端 InnoAgent 入口与工作区。模型密钥留在服务端配置中，接口不接受客户端密钥。

在本目录运行：

```sh
npm ci
npm start
```

默认只监听 `127.0.0.1:3001`。用 `PORTRAIT_PORT` 指定其他端口。浏览器打开 [Swagger UI](http://127.0.0.1:3001/docs/)可查看结构、展开接口并使用 **Try it out** 调试；[OpenAPI JSON](http://127.0.0.1:3001/openapi.json)供其他客户端读取。

| 接口 | 用途 |
| --- | --- |
| `POST /api/portraits` | 提交 `{ "bundle": ... }`，返回 `202`、任务标识和 `Location` |
| `GET /api/portraits/{id}` | 查询 `running`、`completed` 或 `failed`；完成时含 `portrait` |
| `GET /api/portrait-config` | 读取当前显性规则和隐性评价标准 |
| `GET /docs/` | 浏览并调试 API |
| `GET /openapi.json` | 获取 OpenAPI 3 文档 |

`bundle` 使用 Skill 的共享 JSON Schema，包括学生标识、期间、阶段、文档哈希和原文段落。材料必须已经完成解析，文件上传和 OCR 不在此服务范围内。输入上限为 1 MiB。可参考[合成材料构造器](../../../.agents/skills/graduate-portrait/scripts/synthetic.mjs)理解输入；合成样例只用于调试，不代表真实学生。

生成过程是异步任务。`202`只表示接受任务，按响应中的 `Location`查询结果。任务失败时，`error.code`说明配置、网络、超时、配额或结构校验问题；响应不包含上游错误原文。超过5分钟会停止本地等待，任务状态为 `failed`、错误代码为 `JOB_TIMEOUT`。InnoAgent 后端可能仍在执行，晚到结果不保存；确认上游执行结束前请勿重试。成功结果的 `review_status`始终为 `draft`。

## 原型范围

任务和结果仅保存在当前进程内，默认30分钟后删除，重启后丢失。最多保存20条任务，同时保留2次本地执行等待；这不保证上游超时后的执行数量。满额返回 `503`与 `Retry-After`。重复 `POST`会创建新任务并再次调用模型，重试前先查询已有任务。

服务通过 `skill-bridge.mjs`复用 MJS 画像实现，TypeScript 声明只描述接口边界，实际输入校验和输出 Schema 与 Skill 共享。默认执行函数调用真实 InnoAgent；缺少入口配置时返回失败任务。测试可注入执行函数，不能将测试结果当作在线运行证据。

这不是完整业务平台：没有登录授权、数据库、审核提交和正式档案写入。只在本机调试；需要多人访问或持久保存时，应先补齐服务端权限和存储设计。

## 验证

```sh
npm test
npm run typecheck
npm run build
```

接口测试覆盖输入一致性、异步任务、草稿结果、错误脱敏、超时取消、容量限制、过期、关闭取消、OpenAPI 和 Swagger 页面。真实 InnoAgent 与真实模型调用需要单独验证，测试中的合成执行函数不能证明在线效果。
