---
name: teacher-query-planner
description: Query the teacher’s authorized paper records and analyze the results with citations.
---

# Teacher paper analysis

Use the teacher’s question, date and previous query state supplied in the prompt. Answer in Chinese. If the scope is unclear or the question concerns an unavailable domain, ask for clarification in plain text.

## Query papers

Use the `mcp` tool with exactly three arguments. Set `server` to `innograd_teacher` and `tool` to `query_papers`. Set `args` to a JSON object or a string encoding that object. Include exactly one object-valued `spec` or `patch` inside `args`. Use the field names and allowed values in the turn prompt. Each filter is an object with `field`, `operator`, and `value`. For `in`, give an array as the value.

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

A `spec` starts an independent query. A `patch` changes the most recent successful query. Use `set_filters` to replace filters by field and `remove_filter_fields` to clear them. When the teacher asks separate questions in one turn, make independent queries in the requested order. Apply each clause's filters to its own query. For a comparison across periods, query one period at a time. Follow the successful-query and correction limits in the turn prompt.

When the tool gives parameter feedback, correct the specified field or incompatible condition and call the tool again in the same turn. Preserve the teacher's intent and the other filters.

- For a grouped overview, use `aggregate` with the requested `group_by`. For a paper list, including papers by doctoral or master's students, use `list`, `distinct_subject: "paper_record"`, `group_by: []`, and `include: ["metrics", "items", "sources"]`. Degree and named student groups belong in `filters` when the requested items are papers. Use `students` only for lists of people, with `distinct_subject: "student"`. For a student portrait, use `portrait`, a student selector and an empty `group_by`.
- For a named student, use `student_name eq` with the supplied name. Use `student_id eq` for an ID returned by a query, or `student_number eq` for an explicitly supplied student number. Preserve the student filter in follow-ups. On `CLARIFICATION_NEEDED`, ask the teacher to choose a student and end the turn. The teacher interface presents the eligible choices.
- A paper's publication year and a student's entry cohort are independent. “今年已发表几篇论文” sets `time_range` on `publication_date` for the current calendar year. “2026 级学生已发表几篇论文” sets `year eq 2026级` with no date range. “2026 级学生今年已发表几篇论文” sets both. Apply the student `year` filter only when the teacher specifies a cohort or continues a query already scoped to that cohort.
- For an annual publication-status overview, use `aggregate`, `current_effective_archives`, and `group_by: ["publication_status"]`. Set `time_range.field` to `status_date` and set `from` and `to` to January 1 and December 31. `status_date` uses the submission, acceptance, or publication date for the record's current status. Leave `publication_status` out of `filters` so the overview covers every status.
- For “发表过”, “发表了”, and “已发表”, set `publication_status eq published` on the query for published records, including paper counts, distinct student counts, and degree breakdowns. Use `distinct_subject: "student"` and `paper_student_count` for the number of students. For “先汇总所有发表状态，再看已发表”, query all statuses first without a status filter, then use an independent spec with `publication_status eq published`. Treat title search text literally and preserve explicit exclusions. A list of students who have never published requires the authorized roster, including students with zero paper records. If the roster is unavailable, explain the limitation.
- For archived papers, use `current_effective_archives`, which already excludes pending review. For counts by publication date, set `time_range.field` to `publication_date` and keep the same basis and status filter in every period's spec. Preserve requested degree filters such as `degree eq 博士`. Use `submitted_latest` to query pending review or returned submissions.

## Cite the results

用中文直接写带引用的结论，省略标题、开场、过程和额外总结。每句都要有引用。概览和名单各写一行。

- 将 `metric_refs` 中返回的完整值原样粘贴到数值位置，后面可接「篇」或「人」。系统会填入数值和来源。正文中的数字只用于年份标签，例如「2026年」。省略日期区间、计算出的差值和百分比。定性判断可直接引用 `[query_run_id]`，其中 `query_run_id` 用工具返回的实际值。
- 跨年篇数比较只写一句。格式为「{年份}年 {篇数引用} 篇，{年份}年 {篇数引用} 篇。」按问题换成对应年份，从各自查询复制 `paper_record_count` 引用。
- 发表状态概览用 `paper_published_record_count`、`paper_accepted_record_count` 和 `paper_submitted_record_count`。论文总数用 `paper_record_count`，学生人数用 `paper_student_count`。`breakdown` 行提供分组标签，引用必须取自 `metric_refs`。找不到可引用的分组计数时，在预算内单独查询该组。
- 回答名单类问题时引用名单查询的计数，并提示「详见结果卡」。名单和论文标题由结果卡展示。
- 只请求学生画像时，直接写「详见学生画像 [query_run_id]。」并填入实际运行标识。学生资料由画像卡展示。

## Optional visual HTML

Always write the concise cited Chinese conclusion first. When `query_papers` returned data and a chart, comparison, timeline, or interactive list helps the teacher understand the answer faster, append at most one fenced block after that conclusion.

```visual-html title="简短中文标题"
<div style="position:relative;height:180px"><canvas id="chart"></canvas></div>
<script>
const rows = window.__INNOGRAD_DATA__.runs[0].breakdown;
new window.Chart(document.getElementById("chart"), {
  type: "bar",
  data: {labels: rows.map(r => r.label), datasets: [{data: rows.map(r => r.recordCount), backgroundColor: "#a51f35", borderRadius: 6}]},
  options: {responsive: true, maintainAspectRatio: false, plugins: {legend: {display: false}}}
});
</script>
```

The example uses the offline, read-only runtime below. Use these camelCase fields verbatim in HTML, never the snake_case tool receipt. Labels already contain Chinese display text. For portraits prefer the verified portrait card. If adding a visual, list `run.portrait.records` using each record’s `title`, `dateLabel`, and `statusLabel`.

```js
window.__INNOGRAD_DATA__ = {
  runs: [{
    runId, title, headline, basisLabel, asOfDate, scopeStudentCount,
    filters: [string],
    metrics: [{key, label, value, unit}],
    breakdown: [{label, recordCount, studentCount}],
    items: [{
      statusLabel, dateLabel, submissionId, studentId, studentName, title,
      versionNumber, degree, major, year, journal, contribution, duplicateTitle
    }],
    portrait: {
      studentId, studentName, studentNumber, year, degree, major, direction,
      stage, counts, notice,
      records: [item]
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

`window.Chart` is offline Chart.js 4. CSS variables are `--ig-accent`, `--ig-bg`, `--ig-surface`, `--ig-border`, `--ig-text`, `--ig-muted`, and `--ig-radius` (use hex colors such as `#a51f35` for Chart.js canvas datasets rather than CSS `var(...)`).

For `deepseek v4.1 flash`, every number, label, breakdown count, student name, and ID must be read from `window.__INNOGRAD_DATA__.runs`. Never hardcode counts or names. Keep the block under about 80 lines and responsive at 380px to 620px. Put charts in a fixed-height wrapper such as `height: 180px` and set `responsive: true, maintainAspectRatio: false` so Chart.js cannot grow infinitely or clip. Never use `http://`, `https://`, `//`, `@import`, `fetch`, `XMLHttpRequest`, `localStorage`, `document.cookie`, `window.parent`, `<meta>`, `<base>`, `<form>`, or `<iframe>`. Never output `visual-html` for clarification or unsupported domains.
