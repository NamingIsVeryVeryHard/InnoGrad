# InnoAgent 材料审核运行说明

日期：2026-11-04。

材料审核通过公共 `AgentClient` 调用项目统一部署的 InnoAgent，使用其工作区、会话和工具循环。输入可以是上游 OCR 后的完整 `review_package`；现有提交任务也可由兼容层读取 PDF 或 DOCX 后组包。

## 1. 启动

在 InnoAgent 服务端安装完整的 `agent-skills/material-review` 目录，并配置实际模型。本机使用 `ecnu/ecnu-qwen-flash`。公共连接和调用契约见 [InnoAgent 统一接入接口](InnoAgent统一接入接口.md)。

复制配置模板并填写本机值；已有 `.env` 时保留原配置和密钥。

```dotenv
AI_MODE=innoagent
AI_BASE_URL=http://127.0.0.1:3107
AI_MODEL=ecnu/ecnu-qwen-flash
REVIEW_WORKFLOW=agent
INNOAGENT_SKILL=material-review
INNOAGENT_TIMEOUT_SECONDS=600
INNOAGENT_QUEUE_TIMEOUT_SECONDS=600
AI_MAX_ATTEMPTS=3
AI_RETRY_SECONDS=10
```

分别在 `backend` 目录启动 API 和 Worker：

```sh
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```sh
.venv/bin/python -m app.worker
```

连接配置或后端代码变化后重启这两个进程。密钥只放在进程环境或本机 `.env`，不写入仓库和报告。

客户端使用标准 InnoAgent 接口，沿用服务端工具配置；不上传额外的权限策略，也不调用自定义权限预检。

## 2. 输入和报告

`review_package` 包含本次版本、申报人、表单、完整附件原文、附件用途、规则快照、引用成果、周期和解析限制。具体 schema 随 Skill 交付。

| 工作区文件 | 内容 |
| --- | --- |
| `review/package.json` | 完整审核包 |
| `review/manifest.json` | 上下文、附件清单、原文路径和行数 |
| `review/sources/*.txt` | 带原始文件和证据位置的完整文本 |
| `review/output-schema.json` | 结构化报告 schema |

Agent 自主读取这些文件，最终返回一个 `checks` 对象。程序校验结构、读取覆盖、冻结规则和原文证据。需要修正时，仅在同一会话反馈一次具体问题；结束后清理会话和工作区。

公共客户端不会写入材料状态。材料业务层校验当前版本、最新任务和执行令牌后，决定通过、补正或异常；通过后由归档 outbox 完成归档。

## 3. 页面操作

学生在培养任务或论文成果中填写材料，上传附件并选择中文用途。正式提交后自动创建审核任务。

- 排队和执行期间，材料详情自动更新状态；
- 通过后显示归档进度和有效认定；
- 需补正时，学生按具体原因修改或补交，重新提交形成新版本；
- 异常任务进入机构队列，授权教师可重新审核或记录处理意见；
- 报告展示中文结论和原文证据，可直接打开原件；PDF 跳至对应页码。

报告明确区分预置演示数据、基础检查和真实内容审核。技术标识留在后台，不出现在默认报告正文。历史报告保留来源，不会产生新的机构待办。

## 4. 当前状态

本轮代码已接线，保留 `material-review-5` 及 v2 规则校准。按要求优先完成功能，公共层抽取后的版本尚未运行测试和浏览器验收。
