# 竞赛与获奖及学术交流本地验收材料

本目录提供竞赛与获奖（`kind = "competition"`）和学术交流（`kind = "exchange"`）的合成标准正例、负例及边界测试样例，供接口联调、自动化回归和手工界面验收复用。

## 材料说明

- `competition-valid.json`：同时附带证书附件和公示链接的完整竞赛表单（团队赛）。
- `competition-link-only.json`：仅填写公示链接、未上传附件的竞赛表单（提交后应转交人工核验，不自动通过）。
- `competition-invalid.json`：竞赛负例集合（缺少奖项、无效日期、非 `http(s)` 公示链接、重复成员顺序、无效表单版本）。
- `exchange-modes.json`：涵盖全部四种参与方式（`attend`、`talk`、`poster`、`practice_task`）的正例集合及预期默认附件角色、画像映射维度。
- `exchange-invalid.json`：学术交流负例集合（作报告缺题目、海报缺题目、实践任务缺任务说明、结束早于开始日期、非法参与方式、非法链接）。

## 回归命令

在仓库根目录执行：

```bash
cd backend && ../.venv/bin/python -m pytest -q tests/test_competition_and_exchange.py
node --test frontend/prototype/tests/model.test.cjs
```
