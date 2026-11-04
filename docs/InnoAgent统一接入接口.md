# InnoAgent 统一接入接口

日期：2026-11-04。

## 1. 责任和入口

学校 Agent 接入与材料审核由本分支负责，包括部署接入、连接配置、公共客户端、工作区和会话、调用控制、结构化结果，以及材料审核业务。

画像和预警负责人提供各自的 Skill、输入、输出模型和业务规则，通过同一个客户端调用同一个 InnoAgent。总工作台的页面合并与视觉收口由整合负责人负责；材料审核前端随本分支交付。

| 文件 | 职责 |
| --- | --- |
| [agent_client.py](../backend/app/agent_client.py) | 公共 HTTP/SSE 客户端、排队、超时、重试、结构化结果读取和资源清理 |
| [agent_contracts.py](../backend/app/agent_contracts.py) | `AgentTask`、`AgentExecution`、`AgentProgress`、`AgentRunResult`、`AgentFailure` |
| [adapters/innoagent.py](../backend/app/adapters/innoagent.py) | 材料审核适配器，复用公共客户端 |
| [review_execution.py](../backend/app/review_execution.py) | 材料规则覆盖、原文证据校验和引文定位恢复 |
| [jobs.py](../backend/app/jobs.py) | 材料审核持久任务、租约、执行令牌、重试和业务结果落库 |

公共客户端没有论文、年度报告、画像或预警的业务规则，也不要求输出必须包含 `checks`。

## 2. 业务模块如何调用

业务模块先定义自己的 Pydantic 输出模型，再构造 `AgentTask`。下面的函数可以由业务后台任务调用；`skill` 传入服务端已安装的 Skill 名称。

```python
from pydantic import BaseModel

from app.agent_client import AgentClient
from app.agent_contracts import AgentExecution, AgentTask


def run_business_agent(
    *,
    skill: str,
    payload: dict,
    result_model: type[BaseModel],
    instructions: str,
    on_progress=None,
    is_cancelled=None,
):
    task = AgentTask(
        skill=skill,
        input=payload,
        output_schema=result_model.model_json_schema(),
        validate_output=lambda value: result_model.model_validate(value).model_dump(mode="json"),
        instructions=instructions,
    )
    result = AgentClient().run(
        task,
        AgentExecution(on_progress=on_progress, is_cancelled=is_cancelled),
    )
    return result.output, result.metadata
```

`run()` 是同步调用，应放在后台任务中执行。业务模块保存自己的任务、关联对象和业务结果。材料审核已有 `AIJob`，画像和预警可以把公共进度回调接入各自的持久任务。

`validate_output` 是必填项。业务模块在这里校验自己的输出模型及业务约束；校验通过后，客户端才返回结果。公共层不会批准材料、生成学生画像或写入预警。

## 3. 请求契约

| `AgentTask` 字段 | 说明 |
| --- | --- |
| `skill` | 已安装的 Skill 名称 |
| `input` | 本次任务的完整输入，写入工作区 |
| `output_schema` | 本次任务的结构化结果 schema |
| `validate_output` | 接收结果字典，返回校验后的字典；校验失败时抛出异常 |
| `instructions` | 本次业务任务的执行说明 |
| `files` | 可选的补充文件映射，键为工作区内的相对路径，值为文本或字节 |
| `input_path` | 输入路径，默认 `input/request.json` |
| `schema_path` | 输出 schema 路径，默认 `input/output-schema.json` |
| `task_id` | 调用方任务标识，默认生成 UUID |
| `skill_version` | 可选的业务 Skill 版本记录 |
| `expected_skill_hash` | 可选的 Skill 入口版本约束 |

客户端把输入、schema 和补充文件上传至本次独立工作区。模型收到文件路径与任务说明，再由 InnoAgent 的工具循环读取文件。任务正文没有被分成多次独立审核。

业务需要额外核对工具读取或校验结果时，可提供以下回调：

| 回调 | 用途 |
| --- | --- |
| `observe_event(event, workspace_id)` | 接收原生事件，例如记录材料读取范围 |
| `collect_metadata()` | 收集业务执行元数据，在结束时写入结果 |
| `repair_prompt(failure)` | 返回本次校验失败后的修正说明 |
| `repair_codes` | 允许同会话修正一次的错误码，默认仅 `OUTPUT_INVALID` |

材料审核使用这些回调记录完整读取范围和证据问题。其他模块可以只使用基础请求字段。

## 4. 状态、错误和重试

`AgentExecution.on_progress` 接收 `AgentProgress`，包括 `task_id`、`state`、`attempt` 和 `queue_wait_seconds`。

| 状态 | 含义 |
| --- | --- |
| `queued` | 等待调用当前 InnoAgent |
| `running` | 已取得调用位置，开始本次执行 |
| `retrying` | 暂时性服务错误，准备下一次尝试 |
| `succeeded` | 结构化结果校验完成，工作区和会话已清理 |
| `failed` | 当前任务执行失败 |
| `cancelled` | 调用方取消任务或原生执行被中止 |

`is_cancelled()` 返回调用方的取消状态。客户端在排队、文件上传和流事件处理期间读取该状态；取消后清理本次会话与工作区。业务落库仍应使用任务令牌或版本条件，避免过期执行覆盖新结果。材料审核已使用 `execution_token` 和提交版本条件。

错误统一为 `AgentFailure`：

- `code`：稳定的技术错误码，供后台处理；
- `transient`：是否属于可重试的暂时性错误；
- `metadata`：本次任务、工作区、会话、校验反馈和清理状态。

客户端默认最多尝试三次，仅重试暂时性错误。结构或业务校验问题最多在同一会话内修正一次，由 `repair_codes` 控制。清理失败或状态不明时，不重复创建整套任务。

材料审核由 `AIJob` 负责持久重试，因此材料适配器将客户端整单尝试设为一次，避免内外两层叠加重试。

## 5. 会话和文件生命周期

```mermaid
flowchart LR
    A[业务后台任务] --> B[同一服务排队]
    B --> C[创建独立工作区]
    C --> D[上传完整输入和 schema]
    D --> E[创建会话并运行 Skill]
    E --> F[读取并校验结构化结果]
    F --> G[清理会话和工作区]
    G --> H[业务模块保存结果]
```

公共客户端同时提供 `create_workspace()`、`upload_input()`、`create_session()`、`run_skill()` 和 `cleanup()`。完整业务调用使用 `run()`，由它统一管理生命周期。

当前 native InnoAgent 使用一个活动运行时。客户端按服务地址共享本机进程锁，覆盖工作区创建至清理的整个调用过程；多个业务可以提交任务，实际执行依次进行。默认锁目录为 `backend/runtime/agent-locks`。同一部署内的模块应使用相同配置；跨主机调用应统一进入部署的后台任务入口。

客户端沿用 InnoAgent 自身的工具配置，不上传额外的权限 policy、marker，也不调用自定义权限预检接口。标准 InnoAgent 的工作区、会话和流式对话接口即可使用。

## 6. 配置和交接状态

公共配置读取 `AI_BASE_URL`、`AI_MODEL`、`AI_API_KEY`、`INNOAGENT_TIMEOUT_SECONDS`、`INNOAGENT_QUEUE_TIMEOUT_SECONDS`、`AI_MAX_ATTEMPTS` 和 `AI_RETRY_SECONDS`。密钥只从进程环境读取，不写入任务配置或报告。

InnoAgent 实际使用的模型及供应商在其服务端配置中选择。当前本机服务使用 `ecnu/ecnu-qwen-flash`，地址为 `http://127.0.0.1:3107`。仓库配置示例见 [backend/.env.example](../backend/.env.example)。

公共接入层及材料审核适配器已完成代码接线。画像与预警的业务适配器由对应负责人实现。本轮按要求优先完成功能，没有在此次公共层抽取后运行测试或浏览器验收；此前的运行记录不能代替本版本验收。
