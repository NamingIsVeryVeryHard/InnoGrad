# 校内 / 自部署 AI Agent 接入说明

## 当前能力

v0.2.0 在每次正式提交时创建绑定固定版本的初审任务，人工待办同时可用。Worker 领取任务后解析 PDF 原生文本或 DOCX 段落，执行规则检查，并在启用模型模式时调用校内服务。AI 输出不修改业务状态，也没有审批权限。

默认 `AI_MODE=rules`，完全在本机进行规则初审，不向模型服务发送材料。界面会明确显示“未调用语言模型”。PDF 扫描页、图片 OCR 尚未实现，进入无法判断/人工核对提示；不能将解析成功等同于事实审核通过。

## 配置校内模型

将 `backend/.env.example` 复制为 `backend/.env`，按实际服务配置，重启 API 和 Worker。`.env` 被 Git 忽略；密钥不填写在前端和聊天中。

兼容 Chat Completions 的校内或自部署模型：

```dotenv
AI_MODE=chat
AI_BASE_URL=https://学校实际模型域名/v1
AI_MODEL=学校实际模型名
AI_API_KEY=在本机填写
```

程序请求 `{AI_BASE_URL}/chat/completions`，使用 `messages` 和 `response_format: {"type":"json_object"}`。服务须支持这一契约；不兼容时需要按服务文档调整适配器，而非直接认为接入成功。无需 API Key 的内部服务可以不设置 `AI_API_KEY`。

若已有一个执行完整分析的校内 Agent：

```dotenv
AI_MODE=agent
AI_BASE_URL=https://学校实际Agent域名
AI_API_KEY=在本机填写
```

程序向 `{AI_BASE_URL}/review` POST 以下结构：

```json
{
  "schema_version": "1.0",
  "instruction": "服务端固定的审核边界说明",
  "input": {
    "version_id": "提交版本UUID",
    "form": {"title": "示例论文"},
    "requirements": {"version": "paper-1", "review_policy": "manual_all"},
    "blocks": [
      {"file_id": "文件UUID", "page_number": 1, "paragraph_id": null, "text": "论文已录用"}
    ],
    "limitations": [],
    "output_schema": {}
  }
}
```

`output_schema` 实际发送完整的 `AgentResult` JSON Schema，以上空对象只为缩短示例。请求不携带对象存储键、服务器路径、账号密码或学生全量历史。业务表单中包含的信息及限定长度正文会被发送至配置的服务，因此真实材料接入须使用学校批准的地址。

Agent 响应必须为以下 JSON；Chat 模式则将同样 JSON 放在 `choices[0].message.content` 字符串中：

```json
{
  "checks": [
    {
      "rule_id": "PAPER_STATUS_CONSISTENCY",
      "conclusion": "compliant",
      "severity": "info",
      "explanation": "指定证明中存在录用表述，仍需教师核对其真实性和归属。",
      "evidence": [
        {"file_id": "文件UUID", "page_number": 1, "paragraph_id": null, "quote": "已录用"}
      ],
      "suggestion": "核对论文标题、作者及通知来源。",
      "limitations": []
    }
  ]
}
```

枚举：

- `conclusion`：`compliant`、`non_compliant`、`unable_to_determine`、`not_applicable`。
- `severity`：`blocking`、`suggestion`、`info`。
- PDF 使用从 1 开始的物理页码；DOCX 使用 `paragraph_id=p-N`，页码为空，不伪造 Word 分页。

模型作出符合或不符合结论时必须提供证据，文件、页码/段落及摘录必须在本次实际发送的文本中匹配。包外引用、虚构摘录、结构错误将导致任务失败，不会成为有效结果。模型语义判断准确性仍需独立标注评测。

## 网络与运行限制

- 默认允许 HTTPS 和本机 HTTP 服务。如学校批准的内网服务仅提供 HTTP，显式设置 `AI_ALLOW_INTERNAL_HTTP=1`；只在受控内网使用。
- 地址只能由服务端配置提供，材料和模型输出中的 URL 不会被当作工具调用执行；不跟随 HTTP 重定向。
- 单次请求超时 60 秒，连接超时 10 秒；发送正文最多约 60000 字符，截断以局限说明显示。当前原生 PDF 解析最多 200 页。
- 每个作业保存版本、输入摘要、规则/解析/提示词版本和模型标识；密钥不写入作业配置。
- 运行中的任务使用 10 分钟租约和执行令牌；中断后最多领取 3 次。取消或旧执行者的迟到结果不会写回。
- 模型异常/输出错误不会自动无限重试，可从界面“重新执行当前版本初审”创建新运行；过期租约恢复不等于外部调用精确执行一次。
- 未实现独立 OCR、解析进程资源隔离、跨 Worker 的模型限流和正式质量门槛；当前不是 AI 模块全部验收通过。

## 接入验收步骤

1. 先使用合成/脱敏材料验证 DNS、TLS、认证、模型名和响应格式。
2. 提交一份有原生文本的 PDF 或 DOCX，确认页面出现实际模型模式与任务成功结果。
3. 核对证据位置及原文，记录模型输出和人工结论；输出合法不能代替语义质量评测。
4. 验证超时、错误响应、包外证据和取消后的迟到输出；人工审批应始终可继续。
5. 按开发计划 AI-06 组织独立样本评测，再决定是否启用真实业务辅助审核。

截至本轮交付，未获得校内接口地址和模型名，已完成适配器与模拟协议测试，尚未完成真实模型连通性或推理质量验收。自动审批保持关闭。
