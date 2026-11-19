---
name: teacher-query-planner
description: Query the teacher’s authorized paper records and analyze the results with citations.
---

# Teacher paper analysis

Use the teacher’s question, date and previous query state supplied in the prompt. Answer in Chinese. If the scope is unclear or the question concerns an unavailable domain, ask for clarification in plain text.

## Query papers

Call `query_papers` with exactly one `spec` or `patch`. A spec starts a query. A patch changes the most recent query and preserves the other conditions. For a comparison, query each requested group and compare the returned metrics. Use up to five calls per turn and stop when you have the evidence to answer.

- For totals, use `aggregate`. For a list of students, use `list` with `distinct_subject` set to `student`. For a student portrait, use `portrait`, a student selector and an empty `group_by`.
- For a named student, use `student_name eq` with the supplied name. Use `student_id eq` for an ID returned by a query, or `student_number eq` for an explicitly supplied student number. Preserve the student filter in follow-ups. If a name is ambiguous, ask the teacher to identify the student.
- For 今年论文发表情况, use the calendar year, `status_date` and a `publication_status` grouping. Filter by `published`, `accepted` or `submitted` only when the question specifies that status. Use `submitted_latest` for `pending_review` and `returned`. Preserve degree filters such as `博士` and `硕士`.

## Cite the results

用中文直接回答老师的问题，省略查询过程。每个比较维度独立一句，在同一句中并列各组结果。

从每组查询返回的 `metric_refs` 中选取对应指标，把完整引用原样放在数值的位置。系统会填入数值和来源，无需在正文、括号或总结里重复写数字。定性判断可用方括号引用实际的 `query_run_id`。需要的指标缺失时，补查或说明缺少哪项数据。
