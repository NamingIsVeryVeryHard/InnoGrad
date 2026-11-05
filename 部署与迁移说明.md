# InnoGrad 可迁移版本部署与运维说明

版本：20261104-portable-rc1。交付日期：2026-11-04。

本包包含当前 FastAPI、业务前端、Worker、数据库迁移和材料审核 Skill，加上容器部署与迁移脚本。不包含数据库、令牌、演示密码、真实材料、模型权重、InnoAgent 运行时和 Pi 依赖。适用于一台主机、一个 API、一个 Worker 的受控试点。

## 1. 交付内容与已验证边界

原工作区后端 132 项测试通过、前端 8 项测试通过。发布副本的新增脚本与完整复验以 `验证记录.md` 为准。本机没有 Docker，故没有执行镜像构建与跨主机容器启动，不将配置文件静态检查写成已上线。目标主机需要联网获取 Python 基础镜像和锁定依赖，以及访问 ECNUChat。

建议初始资源为 2 核 CPU、4 GB 内存、20 GB 可用磁盘，属于试点起始建议，不是压测结论。文件增长应独立估算。本方案使用 SQLite 数据卷，不支持多主机共享 SQLite 或多副本横向扩展。

## 2. 干净安装

在服务器安装 Docker Engine 与 Compose v2，将压缩包解压后进入项目根目录。Windows 使用 Docker Desktop 的 Linux 容器模式。

```sh
cp .env.example .env
```

用编辑器在 `.env` 填入 `AI_API_KEY`。默认使用 ECNUChat `ecnu-max`，先保留 `REVIEW_WORKFLOW=manual`，这样模型执行完成后仍由教师确认。令牌不应写入命令行、源码、镜像或共享文档。Linux 可执行 `chmod 600 .env`。

```sh
docker compose build
docker compose up -d
docker compose ps -a
docker compose logs --tail=100 migrate api worker
curl http://127.0.0.1:8000/health
```

`migrate` 一次执行成功后退出属于正常状态；API 与 Worker 在其成功后启动。首次部署数据库为空，不会自动导入演示账户。

```sh
docker compose exec api python /app/deploy/bootstrap.py
```

按交互提示创建一个管理教师和一个导师，密码至少 12 字符。脚本拒绝覆盖现有账户，不输出密码。管理教师登录后新增学生，建立指导范围并发布培养任务；新建学生接口返回的凭据应按学校方式交接。不要运行 `app.seed` 导入演示账户用于正式环境。

本地查看入口：`http://127.0.0.1:8000/prototype/`；API 文档：`http://127.0.0.1:8000/docs`。

## 3. HTTPS 和访问入口

Compose 只将端口绑定宿主机回环地址。将 `deploy/nginx.conf.example` 配置到同机 Nginx，替换域名与证书路径，确保 51 MB 请求大小和代理超时。证书申请、域名解析和防火墙开放需在目标服务器完成。

配置 HTTPS 后将 `.env` 设置 `COOKIE_SECURE=1`，再执行：

```sh
docker compose up -d --force-recreate api worker
```

检查 Host 与 `X-Forwarded-Proto` 正确传递，否则同源登录校验可能出现 403。API 信任代理头的配置要求宿主机端口不公开暴露，外部只能经过受信反向代理。若将 Nginx 改为容器部署，必须相应调整网络与 `proxy_pass`，不能直接照抄同机配置。

## 4. 模型模式与自动审核

| 变量 | 示例与含义 |
| --- | --- |
| `AI_MODE` | `chat`：ECNUChat 直接调用；`innoagent`：独立 Agent；`rules`：离线规则 |
| `AI_BASE_URL` | `https://chat.ecnu.edu.cn/open/api/v1` |
| `AI_MODEL` | `ecnu-max`，按令牌实际授权模型调整 |
| `AI_API_KEY` | ECNUChat 令牌；原生模式下是 Agent 端认证令牌，非必然为模型令牌 |
| `REVIEW_WORKFLOW` | `manual` 试运行；`agent` 开启程序自动决策 |
| `COOKIE_SECURE` | HTTPS 为 `1`，仅本地 HTTP 为 `0` |
| `AI_MAX_ATTEMPTS` | `3` |
| `AI_RETRY_SECONDS` | `10`，指数退避基数 |
| `INNOAGENT_SKILL` | `material-review` |
| `INNOAGENT_TIMEOUT_SECONDS` | 原生模式执行期限 `600` 秒，Chat 目前固定请求期限 180 秒 |

先用明确标记的合成材料验收：标题、作者、状态、会议、日期、贡献和用途相互一致；验证报告完整、证据可打开、手动通过后归档。然后验证错标题、匿名作者、缺附件、坏格式、取消与模型故障。只有确认自动流转规则符合机构要求后，再改为 `REVIEW_WORKFLOW=agent` 并重建 API/Worker 容器。

当前 Chat 与原生模式不是完全相同的验证链。Chat 的任务 `succeeded` 不等于所有规则通过，更不代表学术事实成立；图片无 OCR、长文截断、身份信息缺失时应检查具体限制。旧失败任务不会因重启而变为正确，使用界面“重新审核”创建新任务，避免直接改数据库抹去历史。

如需要 InnoAgent，须单独部署其运行时、模型提供方和完整 Skill。容器内 `127.0.0.1` 指向容器自身，不能用于连接宿主机或其他容器上的 Agent；应使用网络服务名或经核验的内网域名。内网 HTTP 需根据项目配置显式允许。不得将无业务认证的 Agent 工具端口直接公开。

## 5. 从当前 Windows 本机迁移已有数据

当前本机使用 `D:/InnoGrad/backend/runtime/development.db` 和其 `files` 目录。先确认 `.env` 没有覆盖 DATABASE_URL/FILE_ROOT；若覆盖，应按实际位置操作。本步骤会迁入当前所有演示记录和账户，仅适合迁移现有测试站，正式站优先空库安装。

1. 暂停 API 与 Worker，停止提交和附件上传。
2. 建立中间目录，将数据库与附件复制到统一布局。SQLite 仍通过 backup API 生成快照，勿在服务运行时随意复制 WAL 文件。
3. 生成迁移备份，单独安全保管环境变量与令牌。

在发布包目录运行 PowerShell：

```powershell
New-Item -ItemType Directory -Force migration-input | Out-Null
Copy-Item -LiteralPath D:\InnoGrad\backend\runtime\development.db -Destination migration-input\innograd.db
Copy-Item -LiteralPath D:\InnoGrad\backend\runtime\files -Destination migration-input\files -Recurse
python deploy/backup.py --data migration-input --output innograd-backup.tar.gz
```

上述命令以服务已完全停止、数据库关闭完成为前提。已有业务另设数据库目录时不要复制错误位置。备份归档包含文件清单与 SHA-256，但不包含令牌。

## 6. 容器站备份

先进入部署根目录，创建 backups 目录并停止业务容器，保留数据卷：

```sh
mkdir -p backups
docker compose stop api worker
docker compose run --rm --no-deps -v "$PWD/backups:/backups" api python /app/deploy/backup.py --data /data --output /backups/innograd-backup.tar.gz
docker compose start api worker
```

备份文件名应每次不同，脚本拒绝覆盖。数据库与文件在停写期间同时备份；脚本只读取数据库和文件，不将 `.env` 打入归档。定期把备份复制到另一主机并做恢复演练。备份是否可恢复不能只看文件是否存在。

## 7. 异地恢复

在新主机解压相同版本代码、设置新的 `.env` 并构建镜像，暂不启动业务。创建空数据卷并恢复：

```sh
docker compose build
docker volume create innograd_innograd-data
docker run --rm --user 0 -v innograd_innograd-data:/restore -v "$PWD/backups:/backups:ro" innograd:20261104 python /app/deploy/restore.py --archive /backups/innograd-backup.tar.gz --data /restore
docker run --rm --user 0 -v innograd_innograd-data:/restore innograd:20261104 chown -R 10001:10001 /restore
docker compose up -d
```

默认 Compose 项目名为 `innograd`，故卷名如上；若通过 `-p` 改名，需同步调整卷名。恢复脚本拒绝向非空目录恢复，先校验归档路径、成员和全部文件哈希，再写入。归档必须来自可信备份渠道；哈希验证不等同于来源认证。

数据卷新文件使用容器用户 UID 10001 创建。外部恢复若由 root 写入，需确保 UID 10001 可读写。成功后核对账户、材料数、原件下载、哈希、当前有效归档和画像；执行一份新的合成提交。恢复的登录会话和账户仍属于旧库，应按机构策略更新密码或会话。

## 8. 升级与回滚

升级前记录 `release.json`、镜像标识与备份；停止服务并完成一致备份后替换代码、构建镜像、执行迁移，再启动。迁移服务失败时不要强行启动新 API。禁止以 `docker compose down -v` 作为普通重启命令，它会删除命名数据卷。

回滚需要同时考虑数据库模式。若新版本已经修改数据结构，应恢复升级前备份到新空卷，再使用旧版本镜像；不能只回退代码后继续访问不兼容数据库。保留失败环境以便诊断，不覆盖唯一备份。

## 9. 非容器运行

Python 3.12 环境下：

```sh
python -m venv .venv
# Linux: source .venv/bin/activate
# Windows PowerShell: .venv/Scripts/Activate.ps1
pip install -r backend/requirements.lock.txt
```

将根目录 `.env.example` 复制为 `backend/.env`，填写配置。进入 backend 运行迁移；初始化脚本需让 Python 能导入 backend 下的 app：

```sh
cd backend
python -m alembic upgrade head
# Linux: PYTHONPATH=. python ../deploy/bootstrap.py
# PowerShell: $env:PYTHONPATH=(Get-Location).Path; python ../deploy/bootstrap.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

在相同 backend 工作目录、相同环境文件下，另开受进程管理器保护的进程运行 `python -m app.worker`。生产需 systemd 或 Windows 服务管理器维护两个进程；关闭终端会导致普通前台进程退出。两者必须使用同一个数据库和 FILE_ROOT。

## 10. 验收与故障定位

| 现象 | 检查顺序 |
| --- | --- |
| 401 登录失败 | 账户、密码、Cookie、HTTPS Secure 标志 |
| 登录 403 | 代理 Host/协议与请求 Origin；不要关闭同源保护 |
| 页面启用但任务排队 | Worker 容器、心跳、相同数据库、领取状态 |
| 任务 failed | 具体原因码、模型授权、网络、结构与引文校验 |
| 任务成功但未归档 | routing、阻断项、人工模式、原件覆盖及 Outbox |
| 原件无法下载 | 文件目录、权限、版本归属、哈希与恢复清单 |
| 容器启动失败 | migrate 日志、锁定依赖可用性、卷权限、端口占用 |

必须分别验证 API、Worker、模型和业务归档，不把 `/health` 返回 200 作为全系统验收。当前心跳可能在长任务执行期间延迟刷新，监控阈值要覆盖最长任务耗时。

## 11. 生产扩展清单

正式广泛开放前完成学校规则确认、身份认证与登录限流、依赖漏洞检查、标注集评测、容量测试、恢复演练及日志策略。PostgreSQL、对象存储、SSO 和高可用均需另行建设和验收；已有 psycopg 依赖不代表这些能力已经验证。
