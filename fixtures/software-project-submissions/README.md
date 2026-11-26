# 软件著作权与科研项目阶段成果验收材料（Issue #25 / #26）

本目录仅包含合成测试数据，不含任何真实学生个人信息或学校内部凭据。

## 包含文件

- `valid-software-registered.json`：已登记软著正例（包含登记号、登记日期与软著登记证书附件角色 `copyright_certificate`）。
- `valid-software-unregistered.json`：未登记/申请中软著正例（不填登记号与登记日期，允许暂不上传附件）。
- `invalid-software-forms.json`：已登记缺少登记号/日期、未登记误填登记号、版本号含非法字符的负例。
- `valid-research-project-minimal.json`：科研项目阶段成果极简正例（验证**不将关联材料和附件设为必填**）。
- `valid-research-project-with-artifacts.json`：科研项目阶段成果完整正例（同时关联实验报告、数据集、代码、原型四类可选材料）。
- `invalid-research-project-forms.json`：`javascript:` 危险链接、选“其他”角色缺少说明、无效完成日期的负例。

## 自动回归命令

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests/test_software_copyright.py tests/test_research_project.py
cd ..\frontend
node --test prototype/tests/model.test.cjs prototype/tests/achievements-ui.test.cjs
npm run build
```
