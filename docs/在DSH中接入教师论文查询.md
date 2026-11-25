# 将 InnoGrad 教师论文查询接入 DSH

本文用于把 InnoGrad 的教师论文查询接入 DeepSeek Harness（DSH）。完成配置后，DSH 可以调用 InnoGrad MCP 查询论文、筛选学生、列出论文和查看学生画像。

当前接入使用 MCP Streamable HTTP。DSH 只需要 InnoGrad MCP 地址和当前教师的 Bearer token。对话记录由 DSH 保存，InnoGrad 每次查询都会重新校验登录状态和教师权限。

当前接入提供三个工具。

- `summarize_papers` 用于统计论文记录数、学生数和分组结果。
- `list_papers` 用于分页列出论文记录或去重学生。
- `get_student_portrait` 用于查看单个学生的画像和论文原件。

DSH 当前显示文字、Markdown 表格和原件链接。后端返回的分组结果已经包含下一次查询所需的筛选条件，但当前 DSH 通用 MCP 客户端不会把这些条件显示成按钮。因此，教师不能点击统计分组直接查看对应论文。要实现这个交互，需要 DSH 提供自定义结果卡或前端扩展。

## 准备连接信息

准备以下信息。

- 一个可以访问 InnoGrad 的 DSH 环境。官方 DSH `0.2.2-rc.5` 支持本指南使用的配置。
- InnoGrad MCP 地址，例如 `https://<InnoGrad域名>/api/v1/teacher-agent/mcp`。
- 当前教师登录 InnoGrad 后得到的 `session` 值。

MCP 地址必须同时满足两个条件。

- DSH 运行环境可以访问该地址。
- 教师使用 DSH Web 时，浏览器可以访问该地址对应的 InnoGrad 域名。

## 配置 MCP 客户端

把教师 token 放入启动环境变量。不要把真实 token 写入 patch 文件、仓库或对话。

```sh
export INNOGRAD_MCP_URL='https://<InnoGrad域名>/api/v1/teacher-agent/mcp'
export INNOGRAD_TEACHER_TOKEN='<当前教师的session值>'
```

创建 `innograd-mcp.patch.yml`。

```yaml
- insert:
    - id: mcp-innograd
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: innograd
        transport: streamable-http
        url: !!js process.env.INNOGRAD_MCP_URL
        headers:
          Authorization: !!js '`Bearer ${process.env.INNOGRAD_TEACHER_TOKEN}`'
```

如果项目已有 DSH patch 文件，把 `mcp-innograd` 插件加入现有 `insert` 列表。不要重复创建相同的 `id`。

启动 DSH Web。

```sh
dsh web --patch ./innograd-mcp.patch.yml
```

启动后，在 DSH 的 MCP 工具列表中确认出现以下工具。

- `summarize_papers`
- `list_papers`
- `get_student_portrait`

如果工具列表中出现的是 `query_papers`，DSH 连接的是 Pi 的旧入口。检查 MCP 地址、patch 文件和 Bearer token。

## 验证统计和追问

在一个新对话中发送第一句问题。

```text
2026 年我指导的学生有多少条论文申报记录，涉及多少名学生？
```

DSH 应调用 `summarize_papers`，并传入完整参数。

```json
{
  "year": 2026
}
```

继续在同一对话中发送追问。

```text
只看博士生
```

DSH 应保留上一轮的 `year`，并调用 `summarize_papers`。

```json
{
  "year": 2026,
  "degree": "博士"
}
```

发送论文列表请求。

```text
列出这些论文
```

DSH 应调用 `list_papers`，并保留年份和学位条件。

```json
{
  "year": 2026,
  "degree": "博士",
  "subject": "paper"
}
```

核对以下内容。

- 第一次回答包含论文记录数和涉及学生数。
- 第二次回答只统计博士生。
- 第三次调用仍然包含 `year=2026` 和 `degree=博士`。
- 列表中的每条论文包含学生信息、审核状态和 `files`。

## 查询学生画像和原件

从论文列表中选择一名学生，然后发送以下问题。

```text
查看这名学生的画像和原件
```

如果 DSH 已经知道学生 ID，应调用 `get_student_portrait` 并传入 `student_id`。

```json
{
  "student_id": "<列表中的student_id>"
}
```

也可以按姓名或学号查询。

```json
{
  "student_name": "<学生姓名>"
}
```

```json
{
  "student_number": "<学生学号>"
}
```

姓名匹配到多名学生时，工具返回 `candidates`。让教师根据候选中的学号选择学生，再用选中的 `student_id` 重新调用工具。

在 DSH Web 中打开原件前，先在同一个浏览器中登录 InnoGrad。然后点击画像或论文列表中的 `files[].download_url`。浏览器使用 InnoGrad 登录 Cookie 下载文件。

如果客户端代码自己下载文件，请使用当前教师的 Bearer token 发起 `GET` 请求。

## 检查权限边界

使用当前教师账号查询一名不在其指导范围内的学生。

```json
{
  "student_id": "<范围外学生ID>"
}
```

工具应返回 `NOT_FOUND`。不要根据错误响应推断该学生是否存在。

如果教师的指导关系被撤销，后续查询和原件下载都必须重新按当前权限判断。之前对话中的结果不会绕过新的权限检查。

## 处理常见错误

| 现象 | 处理 |
| --- | --- |
| 工具列表中只有 `query_papers` | 检查 DSH 是否使用 `/api/v1/teacher-agent/mcp`，并确认请求带有当前教师的 Bearer token。 |
| 返回 `401` | 重新登录 InnoGrad，更新 `INNOGRAD_TEACHER_TOKEN`，然后重启 DSH。 |
| 返回 `403` | 确认 token 对应的账号角色是教师或管理教师。 |
| 追问没有保留年份或学位 | 查看 `tools/call` 的 `arguments`。DSH 每次调用都必须传入完整筛选条件。 |
| 原件点击返回 `401` | 在同一个浏览器中登录 InnoGrad。DSH 的 MCP Bearer header 不会自动附加到浏览器点击请求。 |
| 原件点击返回 `404` | 检查原件是否属于当前教师可见的已归档版本。 |

## 读取 MCP 返回值

程序化客户端从 `structuredContent` 读取业务 JSON。

- `summarize_papers` 返回 `metrics`、`breakdown` 和 `data_as_of`。
- `list_papers` 返回 `items`、`pagination` 和每条记录的 `files`。
- `get_student_portrait` 返回 `portrait`，重名时返回 `candidates`。

`content[0].text` 是同一份结构化 JSON 的序列化文本，适合只读取文本内容的客户端。DSH 不需要安装 `teacher-query-planner`。该 skill 继续供原 Pi 入口使用。
