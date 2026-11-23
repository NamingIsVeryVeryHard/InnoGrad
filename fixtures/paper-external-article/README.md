# 论文外部文章关联本地验收材料

本目录只包含合成演示数据，不能作为真实论文、录用或发表证明。验收时使用隔离数据库和隔离附件目录，避免影响 `D:\InnoGrad` 现有开发数据。

## 隔离启动

在 PowerShell 中打开两个终端。下面的环境变量只对当前终端有效：

```powershell
cd D:\InnoGrad-integration\frontend
npm ci
npm run build
```

API 终端执行：

```powershell
cd D:\InnoGrad-integration\backend
$env:DATABASE_URL = "sqlite:///D:/InnoGrad-integration/backend/runtime/paper-acceptance.db"
$env:FILE_ROOT = "D:/InnoGrad-integration/backend/runtime/paper-acceptance-files"
$env:AI_MODE = "rules"
$env:REVIEW_WORKFLOW = "manual"
& "D:\InnoGrad\.venv\Scripts\python.exe" -m alembic upgrade head
& "D:\InnoGrad\.venv\Scripts\python.exe" -m app.seed | Out-File -Encoding utf8 runtime/paper-acceptance-accounts.txt
& "D:\InnoGrad\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Worker 终端使用相同的四个环境变量：

```powershell
cd D:\InnoGrad-integration\backend
$env:DATABASE_URL = "sqlite:///D:/InnoGrad-integration/backend/runtime/paper-acceptance.db"
$env:FILE_ROOT = "D:/InnoGrad-integration/backend/runtime/paper-acceptance-files"
$env:AI_MODE = "rules"
$env:REVIEW_WORKFLOW = "manual"
& "D:\InnoGrad\.venv\Scripts\python.exe" -m app.worker
```

服务启动后打开 `http://127.0.0.1:8000/prototype/`。账号密码在 `backend/runtime/paper-acceptance-accounts.txt`，不要使用原开发库中的运行数据验收。

## 材料

- `valid-submission.json`：完整的论文工作稿表单，包含作者顺序、本人身份、状态、DOI、文章链接和本人贡献。
- `invalid-forms.json`：缺少 DOI/链接、作者顺序不存在和无效 DOI 的负例。
- `legacy-submission.json`：旧版本论文表单，用于确认历史数据仍能读取。
- `proof-author-order.pdf`：合成作者列表与本人位次证明。
- `proof-article-page.pdf`：合成外部文章页面证明。

## 推荐验收顺序

1. 使用新的临时数据库初始化账号，登录 `student1`。
2. 创建论文成果，按 `valid-submission.json` 填写表单。
3. 同时上传两个 PDF 作为证明附件，保存草稿后刷新页面，确认字段和附件仍在。
4. 正式提交，确认状态变为“待 Agent 审核”，生成一个新的版本号。
5. 用教师账号打开论文详情，确认题名、作者顺序、本人身份、DOI、文章链接和两个证明附件可追溯。
6. 在教师 Agent 中查询“今年论文情况”，打开论文结果来源，确认新论文出现在结果卡片和证据来源中。
7. 用 `invalid-forms.json` 中的三个负例分别保存并提交，确认服务端返回 422，且不会生成版本。
8. 用 `student2` 访问 `student1` 的提交和附件，确认返回 404。
9. 将 `legacy-submission.json` 写入测试数据或使用已有旧论文记录，确认历史论文仍能查看。旧记录被新版表单重新提交时，再要求补齐新字段。

## 通过标准

- 正例保存后重载数据完全一致，正式提交生成冻结版本。
- 作者顺序从 1 开始且无重复，`is_self` 只标记本人作者位次。
- DOI 会规范化为 `10.xxxx/xxxxx`，文章链接必须是完整的 `http` 或 `https` 地址，二者至少填写一项。
- 冻结快照包含 `external_article` 和 64 位 `external_article_key`。
- 教师 Agent 结果包含作者、本人身份、DOI、文章链接和来源指针。
- 任一负例不会创建提交版本，附件和草稿不被错误删除。
- 学生之间不能读取对方的提交或证明附件。

自动回归命令：

```powershell
$env:PYTHONUTF8 = "1"
& "D:\InnoGrad\.venv\Scripts\python.exe" -m pytest -q `
  backend/tests/test_paper_external_article.py `
  backend/tests/test_teacher_agent_papers.py `
  backend/tests/test_teacher_agent_contract.py
node --test frontend/prototype/tests/model.test.cjs
```
