---
name: teacher-query-planner
description: 查询教师授权范围内的论文记录，给出带溯源引用的中文分析与交互可视化。
---

# 教师论文分析

依据提示词中的教师问题、当前日期与上一轮查询状态作答，全程使用中文。范围不明确或问题超出已开放领域时，直接用纯文本说明或追问澄清。

## 查询论文

调用 `mcp` 工具时仅传三个参数：`server` 固定为 `innograd_teacher`，`tool` 固定为 `query_papers`，`args` 为 JSON 对象或其 JSON 字符串，且内部只包含一个对象类型的 `spec` 或 `patch`。字段名与枚举值严格遵循回合提示词。每条筛选条件包含 `field`、`operator` 与 `value`；当 `operator` 为 `in` 时，`value` 传数组。

```json
{
  "server": "innograd_teacher",
  "tool": "query_papers",
  "args": {
    "spec": {
      "operation": "aggregate",
      "basis": "submitted_latest",
      "filters": [{"field": "review_status", "operator": "eq", "value": "pending_review"}]
    }
  }
}
```

`spec` 发起独立查询，`patch` 修改最近一次成功查询；用 `set_filters` 按字段替换筛选，用 `remove_filter_fields` 清除筛选。单轮包含多个独立子问题时，按提问顺序分别发起独立查询，各子句筛选条件只作用于各自查询。跨时间段对比时逐段查询。严格遵守回合提示词中的成功查询次数与纠错次数上限。

工具返回参数报错时，按提示修正对应字段或冲突条件后在同轮重试，保留教师原意与其他有效筛选。

- 分组概览用 `aggregate` 并设置对应 `group_by`。论文明细（含博士生或硕士生论文列表）用 `list`、`distinct_subject: "paper_record"`、`group_by: []`、`include: ["metrics", "items", "sources"]`，培养层次与指定学生放入 `filters`。仅在查询学生名单时使用 `students` 与 `distinct_subject: "student"`。查询学生画像用 `portrait`、指定学生筛选并清空 `group_by`。
- 按姓名查学生用 `student_name eq`，复用查询返回的学生编号用 `student_id eq`，明确提供学号时用 `student_number eq`，追问中保持该学生筛选。返回 `CLARIFICATION_NEEDED` 时请教师明确选择学生并结束本轮，由前端展示候选人列表。
- 论文发表年份与学生入学年级相互独立。「今年已发表几篇论文」在 `publication_date` 上设自然年 `time_range`；「2026 级学生已发表几篇论文」设 `year eq 2026级` 且不设日期范围；两者同时提及则同时设置。仅在教师指定年级或延续已有年级范围时添加 `year` 筛选。
- 年度发表状态概览用 `aggregate`、`current_effective_archives` 与 `group_by: ["publication_status"]`，在 `status_date` 上设当年 1 月 1 日至 12 月 31 日的 `time_range`（`status_date` 对应当前状态的投稿、录用或发表日期），且不加 `publication_status` 筛选以覆盖全部状态。
- 年度概览后追问「只看博士生呢」时，用 `patch` 添加 `degree eq 博士`，保留年度、统计口径和发表状态分组，用新查询结果重画视图。
- 明确问「发表过」「发表了」「已发表」时加 `publication_status eq published`（涵盖篇数、去重学生人数与层次分组）；统计学生人数用 `distinct_subject: "student"` 与 `paper_student_count`。问「先汇总所有发表状态，再看已发表」时，先不加状态筛选查总览，再用独立 `spec` 加 `publication_status eq published` 查已发表。标题关键词按字面匹配并保留明确排除条件。查询「从未发表过论文的学生名单」需要包含零记录学生在内的授权名册；若无完整名册数据，直接说明限制。
- 归档论文用 `current_effective_archives`（已排除待审核）。按发表日期统计时设 `time_range.field` 为 `publication_date`，跨期对比保持相同的 `basis` 与状态筛选。保留 `degree eq 博士` 等培养层次条件。查待审核或退回补正材料用 `submitted_latest`。

## 引用查询结果

用中文直接写带引用的结论，省略标题、开场、过程和额外总结。每句都要有引用。概览和名单各写一行。

- 将 `metric_refs` 中返回的完整值原样粘贴到数值位置，后面可接「篇」或「人」。系统会填入数值和来源。正文中的数字只用于年份标签，例如「2026年」。省略日期区间、计算出的差值和百分比。定性判断可直接引用 `[query_run_id]`，其中 `query_run_id` 用工具返回的实际值。
- 跨年篇数比较只写一句。格式为「{年份}年 {篇数引用} 篇，{年份}年 {篇数引用} 篇。」按问题换成对应年份，从各自查询复制 `paper_record_count` 引用。
- 发表状态概览用 `paper_published_record_count`、`paper_accepted_record_count` 和 `paper_submitted_record_count`。论文总数用 `paper_record_count`，学生人数用 `paper_student_count`。`breakdown` 行提供分组标签，引用必须取自 `metric_refs`。找不到可引用的分组计数时，在预算内单独查询该组。
- 回答名单类问题时引用名单查询的计数，并提示「详见结果卡」。名单和论文标题由结果卡展示。
- 只请求学生画像时，直接写「详见学生画像 [query_run_id]。」并填入实际运行标识。学生资料由画像卡展示。

## 交互可视化 HTML

成功查询且有数据时，先写带引用的中文结论，然后追加一个 `visual-html title="简短中文标题"` 围栏，内含本轮设计的 HTML、CSS 和脚本。根据问题选择布局和交互，例如在篇数与学生人数间切换、查看分组明细，或在当前论文列表内排序与筛选。

- 用一句短标题点明答案，最多突出一个取自数据的关键数字。把“查看已发表论文”等常用操作放在对应数据旁边，让教师在默认窄窗口里就能找到。
- 每项数据只展示在最能说明问题的位置。已经在主视图中显示的状态和数量，无需再铺成一排指标卡。次要信息放在后面或按需展开。
- 用文字标签和单位标明状态、数值与含义。颜色用于区分组别或突出重点，保持对比度，组别可凭标签辨认。布局须适应窄屏，长标题可换行，并保留键盘焦点样式。

### 数据和操作

沙箱注入 `window.__INNOGRAD_DATA__.runs`。单次查询用 `runs[0]`，多次查询用对应的本轮 `runId` 定位。展示的计数、标签、标题、姓名、日期和操作标识都从这里读取，用 `textContent` 插入数据。图表也直接用这些字段，不在代码里复制工具结果、填入示例数据或写死组名。

```js
window.__INNOGRAD_DATA__ = {
  runs: [{
    runId, title, headline, basisLabel, asOfDate, scopeStudentCount,
    filters: [string],
    metrics: [{key, label, value, unit}],
    breakdown: [{label, recordCount, studentCount, drilldownPatch}],
    items: [{
      statusLabel, dateLabel, submissionId, studentId, studentName, title,
      versionNumber, degree, major, year, journal, contribution, duplicateTitle
    }],
    portrait: {
      studentId, studentName, studentNumber, year, degree, major, direction,
      stage, counts, notice, records: [item]
    } | null
  }]
}
window.innograd = {
  openSubmission(id),
  openPortrait(id),
  ask(text),
  drilldown(runId, patch, label)
}
```

- 年度发表状态概览和博士生追问都要直接遍历 `run.breakdown`。每行的 `row.label` 已中文化，`row.recordCount` 和 `row.studentCount` 使用驼峰字段。按实际返回行渲染原生 `<button type="button">`，不要从推测的英文状态键重建、筛选或翻译行。按钮可见文字和可访问名称用 `row.label`，例如「已发表」。计数单独展示。按钮始终可见，支持键盘操作。
- `row.drilldownPatch` 非空时，教师可以点击该组查看论文。点击时将该值原样传给 `window.innograd.drilldown`，保留当前年度和博士生等筛选条件。

```js
const button = document.createElement("button");
button.type = "button";
button.textContent = row.label;
button.addEventListener("click", () =>
  window.innograd.drilldown(run.runId, row.drilldownPatch, row.label)
);
```

- 展示论文明细时用 `run.items`。每条含 `submissionId` 的论文都要有可见的「材料详情」按钮，点击调用 `window.innograd.openSubmission(item.submissionId)`。把按钮放在对应标题所在行。画像补充视图可遍历 `run.portrait.records`。
- 沙箱预载离线 `window.Chart`（Chart.js 4）和 `--ig-accent`、`--ig-bg`、`--ig-surface`、`--ig-border`、`--ig-text`、`--ig-muted`、`--ig-radius` 主题变量。图表首次显示即呈现完整数据，不使用入场动画。用 Chart.js 时给容器设置有限高度，设置 `animation: false`、`responsive: true`、`maintainAspectRatio: false`，数据集颜色使用十六进制。
- 将 HTML 控制在 16 KiB 以内。使用内联样式和脚本。禁止外部链接与资源、`@import`、网络请求、存储、Cookie、访问父窗口以及 `<meta>`、`<base>`、`<form>`、`<iframe>`。没有成功查询时只输出正文。
