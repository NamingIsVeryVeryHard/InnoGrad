# 教师工作台分支代码评审记录

**建议暂缓合并 PR #44。** 教师工作台仍有一条涉及查询数据隔离的 P1 意见和五条影响查询结果或界面操作的 P2 意见。优先处理可视化组件的隔离问题，并补充浏览器验收。

## 评审范围与状态

2026 年 11 月 24 日核查了 `integration/xyt-teacher-agent`（`cd04e98`）向 `main`（`00d6ea3`）提交的 [PR #44](https://github.com/NamingIsVeryVeryHard/InnoGrad/pull/44)。GitHub 记录了 `chatgpt-codex-connector` 对 `5ba1f8e` 和 `cd04e98` 各一次 `COMMENTED` 评审。六条讨论均未解决，PR 仍开放，未记录批准。

下列意见均指向本分支新增的教师查询或教师聊天代码。已对照提交中的实现核查，最后一列列出每项仍需执行的验收。

## PR #44 待处理意见

| 优先级 | 位置与发现 | 用户影响 | 处理建议与验收条件 |
| --- | --- | --- | --- |
| P1 | `VisualSandbox.jsx` 将查询结果交给可执行生成内容的可视化组件。`visual-runtime.js` 的隔离策略对组件自身导航仍有未关闭的评审意见。 | 可视化内容能接触教师查询数据，外部导航会造成数据暴露风险。 | 用受控渲染器展示声明式图表数据；在浏览器自动化中验证图表可用且外部导航被阻止，再关闭此项。见 [PR #44](https://github.com/NamingIsVeryVeryHard/InnoGrad/pull/44)。 |
| P2 | `ResultBlocks.jsx` 的追问按钮把“查看论文申报明细”等标签作为自然语言发送。 | 在规则模式下点击确定性的界面操作，可能收到澄清，或保留本应清除的条件。 | 为明细和清除筛选按钮发送已有的 `drilldown_patch`。分别在规则与聊天模式点击，检查返回查询的操作和筛选字段。[原评审](https://github.com/NamingIsVeryVeryHard/InnoGrad/pull/44#discussion_r4675522885) |
| P2 | `privacy.roster` 将缺少学生档案的学号处理为空串，论文查询和工作台则显示 `User.username`。 | 教师按界面显示的学号查找已授权的老学生时，可能得到 404。 | 统一名单查询的学号回退规则。用无 `StudentProfile` 的可见学生验证显示值可查，再确认指导范围外的学生仍不可见。[原评审](https://github.com/NamingIsVeryVeryHard/InnoGrad/pull/44#discussion_r4675522894) |
| P2 | `ResultBlocks.jsx` 允许移除画像的 `student_id`；`PaperQuerySpec` 要求画像保留学生选择条件。 | 点击筛选标签的 × 后，请求可能因缺少必选条件返回 422。 | 禁用画像的必选学生标签移除操作，或先切换到允许清除该条件的列表。检查该操作产生的查询可以执行。[原评审](https://github.com/NamingIsVeryVeryHard/InnoGrad/pull/44#discussion_r4675522900) |
| P2 | 后端返回 `pagination.has_more`，结果卡片只渲染当前页的 `items`。 | 超过默认 50 条时，教师看不到后续论文或学生，也难以判断结果是否完整。 | 显示当前页与总数，按原筛选和排序翻页。用至少 51 条记录分别核对论文列表与学生列表的末项。[原评审](https://github.com/NamingIsVeryVeryHard/InnoGrad/pull/44#discussion_r4676717055) |
| P2 | `ResultBlocks.jsx` 的 `filterValue` 只格式化值，部分标题和标签忽略 `neq` 运算符。 | “排除已投稿”的结果可能显示为“已投稿”，让教师读出相反结论。 | 在标题和标签中保留排除语义，分别核对同一状态的 `eq` 与 `neq` 文案及列表内容。[原评审](https://github.com/NamingIsVeryVeryHard/InnoGrad/pull/44#discussion_r4676717063) |

## 分支验证结果

| 检查 | 实际结果 |
| --- | --- |
| 教师查询后端 `python -m pytest -q tests/test_teacher_agent_*.py` | `cd04e98` 的 **280 项通过**，1 条测试客户端依赖弃用提示 |
| 规划器扩展 `node --test tests/teacher-query-planner.test.mjs` | 2 项通过 |
| 教师聊天前端 `prettier --check 'teacher-chat/*.{js,jsx}'` | 6 个文件格式检查通过 |

以上结果来自 PR 当前提交。分支内已完成的五项改进及重构前后扫描截图见[代码质量报告](code_quality.md)。
