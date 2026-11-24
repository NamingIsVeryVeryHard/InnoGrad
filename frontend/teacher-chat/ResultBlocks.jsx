import React, { useEffect, useRef } from "react";
import { renderMarkdown } from "../chat-markdown.js";
import { formatDate, formatValue, labelFor } from "./field-labels.js";

const publicationDates = {
  submitted: "submission_date",
  accepted: "acceptance_date",
  published: "publication_date",
};
const resourcePaths = {
  submission: /^\/api\/v1\/submissions\/([A-Za-z0-9-]+)$/,
  portrait: /^\/api\/v1\/students\/([A-Za-z0-9-]+)\/portrait$/,
  file: /^\/api\/v1\/files\/([A-Za-z0-9-]+)\/download$/,
};

function validId(value, allowed = /[^A-Za-z0-9-]/) {
  return typeof value === "string" && value.length > 0 && !allowed.test(value);
}

function runAnchor(id) {
  return validId(id, /[^A-Za-z0-9_-]/) ? `agent-run-${id}` : undefined;
}

function appliedQuery(result, query) {
  return result?.applied_query ?? query ?? result?.resolved_query;
}

function filterValue(filter) {
  if (filter.field !== "year") return formatValue(filter.value);
  const values = Array.isArray(filter.value) ? filter.value : [filter.value];
  return values
    .map((value) => `${String(value).replace(/[级年]$/, "")}级`)
    .join("、");
}

function rangeText(range) {
  if (!range?.from || !range.to) return "";
  if (
    /^\d{4}-01-01$/.test(range.from) &&
    range.to === `${range.from.slice(0, 4)}-12-31`
  ) {
    return `${range.from.slice(0, 4)}年`;
  }
  if (range.from === range.to) return formatDate(range.from);
  return `${formatDate(range.from)}至${formatDate(range.to)}`;
}

export function titleFromQuery(query, fallback = "论文查询") {
  const filters = query?.filters ?? [];
  const period = rangeText(query?.time_range);
  const parts = period ? [period] : [];
  for (const filter of filters) {
    if (
      ["year", "degree", "publication_status", "review_status"].includes(
        filter.field,
      )
    ) {
      parts.push(filterValue(filter));
    }
    if (filter.field === "student_name")
      parts.push(`${filterValue(filter)}的论文`);
  }
  return parts.join(" · ") || fallback;
}

export function Analysis({ text, runIds }) {
  const ref = useRef(null);
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const fragment = renderMarkdown(text, { controlled: true });
    const anchors = new Map(
      (runIds ?? []).map((runId, index) => [runAnchor(runId), index + 1]),
    );
    const doc = root.ownerDocument;
    const walker = doc.createTreeWalker(fragment, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      if (node.parentElement?.closest("a, code, pre")) continue;
      const replacement = doc.createDocumentFragment();
      let offset = 0;
      for (const match of node.data.matchAll(
        /\[(?:run )?([A-Za-z0-9_-]+)\]/g,
      )) {
        const id = runAnchor(match[1]);
        if (!anchors.has(id)) continue;
        replacement.append(node.data.slice(offset, match.index));
        const link = doc.createElement("a");
        link.className = "analysis-citation";
        link.href = `#${id}`;
        link.textContent = `依据 ${anchors.get(id)}`;
        link.addEventListener("click", (event) => {
          event.preventDefault();
          const turn = root.closest(".teacher-turn") ?? root.getRootNode();
          const card = turn.querySelector(`#${id}`);
          const evidence = card?.closest("details.visual-evidence-toggle");
          if (evidence) evidence.open = true;
          card?.focus({ preventScroll: true });
          card?.scrollIntoView({ block: "start" });
        });
        replacement.append(link);
        offset = match.index + match[0].length;
      }
      if (offset) {
        replacement.append(node.data.slice(offset));
        node.replaceWith(replacement);
      }
    }
    root.replaceChildren(fragment);
  }, [text, runIds]);
  return text ? <div ref={ref} className="agent-analysis" /> : null;
}

function SafeLink({ type, url, expectedId, children, onOpen }) {
  if (expectedId != null && !validId(expectedId)) return null;
  let id = expectedId;
  if (url != null && url !== "") {
    const match =
      typeof url === "string" ? url.match(resourcePaths[type]) : null;
    if (!match || match[0] !== url || (id != null && id !== match[1]))
      return null;
    id = match[1];
  }
  if (type === "file") {
    return id && url ? <a href={url}>{children}</a> : null;
  }
  if (!id) return null;
  return (
    <button
      type="button"
      className="agent-link"
      onClick={() => onOpen?.(type, id)}
    >
      {children}
    </button>
  );
}

function FilterChips({ query, basis, names, onDrilldown }) {
  const filters = query?.filters ?? [];
  const period = rangeText(query?.time_range);
  if (!filters.length && !period && !basis) return null;
  return (
    <div className="filter-chips" aria-label="当前筛选条件">
      {period ? (
        <button
          type="button"
          className="filter-chip"
          onClick={() =>
            onDrilldown({ clear_time_range: true }, `移除时间范围：${period}`)
          }
        >
          {period} <span aria-hidden="true">×</span>
        </button>
      ) : null}
      {filters.map((filter) => {
        const field = filter.field;
        const selected = Array.isArray(filter.value)
          ? filter.value
          : [filter.value];
        const label = field === "student_id" ? "学生" : labelFor(field);
        const value =
          field === "student_id"
            ? selected.map((id) => names.get(id) || "指定学生").join("、")
            : filterValue(filter);
        const text = [
          "year",
          "degree",
          "publication_status",
          "review_status",
        ].includes(field)
          ? value
          : `${label}：${value}`;
        return (
          <button
            key={field}
            type="button"
            className="filter-chip"
            onClick={() =>
              onDrilldown(
                { remove_filter_fields: [field] },
                `移除筛选：${text}`,
              )
            }
          >
            {text} <span aria-hidden="true">×</span>
          </button>
        );
      })}
      {basis ? <span className="basis-chip">{formatValue(basis)}</span> : null}
    </div>
  );
}

function publicationFilter(query) {
  return query?.filters?.find(
    ({ field, operator }) =>
      field === "publication_status" && operator === "eq",
  )?.value;
}

function MetricStrip({ metrics = [], status, onDrilldown }) {
  const visible = metrics.filter(({ value }) => value > 0);
  const cards = visible.filter(({ key, value }) => {
    if (!status || !["paper_record_count", "paper_student_count"].includes(key))
      return true;
    const specific = key.replace("paper_", `paper_${status}_`);
    return !visible.some(
      (metric) => metric.key === specific && metric.value === value,
    );
  });
  if (!visible.length) return null;
  return (
    <div className="kpi-strip">
      {cards.map((item) => (
        <button
          key={item.key ?? item.label}
          type="button"
          className="kpi"
          disabled={!item.drilldown_patch}
          onClick={() =>
            onDrilldown(
              item.drilldown_patch,
              `${item.label} ${item.value}${item.unit}`,
            )
          }
        >
          <strong>
            {item.value}
            <small>{item.unit}</small>
          </strong>
          <span>{item.label}</span>
        </button>
      ))}
    </div>
  );
}

function publicationBreakdown(result, query) {
  if (result.summary?.breakdown?.length) return result.summary.breakdown;
  if (query?.domain !== "paper" || query.operation !== "list") return [];

  const metrics = new Map(
    (result.summary?.metrics ?? []).map((metric) => [metric.key, metric]),
  );
  return Object.keys(publicationDates).flatMap((status) => {
    const recordMetric = metrics.get(`paper_${status}_record_count`);
    const studentMetric = metrics.get(`paper_${status}_student_count`);
    if (!recordMetric?.value || !studentMetric?.value) return [];
    return [
      {
        label: status,
        record_count: recordMetric.value,
        student_count: studentMetric.value,
        drilldown_patch: (query.distinct_subject === "student"
          ? studentMetric
          : recordMetric
        ).drilldown_patch,
      },
    ];
  });
}

function Breakdown({ rows, onDrilldown }) {
  const visible = rows
    .filter((row) => row.record_count > 0)
    .map((row) => ({
      ...row,
      displayLabel: (row.label ?? "").split(" / ").map(formatValue).join(" / "),
    }));
  if (!visible.length) return null;
  return (
    <div className="breakdown">
      <div className="breakdown-bar" aria-hidden="true">
        {visible.map((row) => (
          <span
            key={row.label}
            className="breakdown-segment"
            style={{ flex: `${row.record_count} 1 0` }}
            title={`${row.displayLabel} ${row.record_count}条`}
          />
        ))}
      </div>
      <div className="breakdown-pills" aria-label="论文分布">
        {visible.map((row) => (
          <button
            type="button"
            className="breakdown-pill"
            key={row.label}
            disabled={!row.drilldown_patch}
            onClick={() =>
              onDrilldown(
                row.drilldown_patch,
                `${row.displayLabel} ${row.record_count}条`,
              )
            }
          >
            {row.displayLabel} {row.record_count}条 · {row.student_count}人
          </button>
        ))}
      </div>
    </div>
  );
}

function MaterialFields({ fields }) {
  const visible = fields.filter(([, value]) => value != null && value !== "");
  if (!visible.length) return null;
  return (
    <dl className="paper-fields">
      {visible.map(([key, value]) => (
        <div key={key}>
          <dt>{labelFor(key)}</dt>
          <dd>{formatValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function PaperItem({ item, duplicate, onOpen }) {
  const isStudent = item.item_kind === "student_summary";
  const dateField = Object.hasOwn(publicationDates, item.publication_status)
    ? publicationDates[item.publication_status]
    : null;
  const date = isStudent
    ? item.latest_status_date
    : (item.status_date ?? item[dateField]);
  const dateLabel = labelFor(
    isStudent ? "latest_status_date" : (dateField ?? "status_date"),
  );
  const statusCounts = Object.entries(item.status_counts ?? {})
    .filter(([, count]) => count > 0)
    .map(([status, count]) => `${formatValue(status)} ${count}条`);
  const fields = isStudent
    ? ["student_number", "year", "degree", "major", "direction", "stage"]
    : [
        "submission_date",
        "acceptance_date",
        "publication_date",
        "journal",
        "doi",
        "contribution",
        "review_status",
        "review_actor_type",
        "archived_at",
      ];
  const details = fields.map((field) => [field, item[field]]);
  if (duplicate) details.push(["submission_id", item.submission_id]);
  return (
    <article className="paper-item">
      <div className="paper-student">{item.student_name || "未标注学生"}</div>
      <div className="paper-title">
        <h5>
          {isStudent
            ? `${item.matched_record_count} 条论文记录`
            : item.title || "未命名论文"}
        </h5>
        {item.version_number != null ? (
          <span className="paper-meta">
            提交版本 <span>V{item.version_number}</span>
          </span>
        ) : null}
      </div>
      <div className="paper-status">
        {isStudent ? (
          statusCounts.join(" · ") || "—"
        ) : (
          <span className="status-badge">
            {formatValue(item.publication_status)}
          </span>
        )}
      </div>
      <div className="paper-date">
        {date ? (
          <>
            <span className="paper-date-label">{dateLabel} </span>
            <time dateTime={date}>{formatDate(date)}</time>
          </>
        ) : (
          "—"
        )}
      </div>
      <div className="paper-actions">
        <SafeLink
          type="submission"
          url={item.links?.submission_url}
          expectedId={item.submission_id}
          onOpen={onOpen}
        >
          材料详情
        </SafeLink>
        <SafeLink
          type="portrait"
          url={item.links?.portrait_url}
          expectedId={item.student_id}
          onOpen={onOpen}
        >
          成长画像
        </SafeLink>
      </div>
      {details.some(([, value]) => value != null && value !== "") ? (
        <details>
          <summary>{isStudent ? "学生信息" : "材料字段"}</summary>
          <MaterialFields fields={details} />
        </details>
      ) : null}
    </article>
  );
}

function PaperTable({ items, onOpen }) {
  if (!items.length) return null;
  const submissionsByTitle = new Map();
  for (const item of items) {
    if (
      item.item_kind !== "paper_record" ||
      !item.title ||
      !validId(item.submission_id)
    )
      continue;
    if (!submissionsByTitle.has(item.title))
      submissionsByTitle.set(item.title, new Set());
    submissionsByTitle.get(item.title).add(item.submission_id);
  }
  const grouped = items[0].item_kind === "student_summary";
  return (
    <>
      {[...submissionsByTitle]
        .filter(([, submissions]) => submissions.size > 1)
        .map(([title, submissions]) => (
          <p className="duplicate-note" key={title}>
            同标题存在多份申报：“{title}”有 {submissions.size}{" "}
            份提交，请结合提交编号核对。
          </p>
        ))}
      <div className="paper-table">
        <div className="paper-table-head">
          <span className="paper-student">学生</span>
          <span className="paper-title">
            {grouped ? "论文记录" : "论文标题"}
          </span>
          <span className="paper-status">发表状态</span>
          <span className="paper-date">
            {grouped ? "最近状态日期" : "状态日期"}
          </span>
          <span className="paper-actions">操作</span>
        </div>
        {items.map((item, index) => (
          <PaperItem
            key={
              item.version_id ??
              `${item.submission_id ?? item.student_id}-${index}`
            }
            item={item}
            duplicate={submissionsByTitle.get(item.title)?.size > 1}
            onOpen={onOpen}
          />
        ))}
      </div>
    </>
  );
}

function Portrait({ portrait, sources, onOpen }) {
  const sourceById = new Map(
    sources.map((source) => [source.source_id, source]),
  );
  const records = (portrait.records ?? []).map((record) => {
    const source = sourceById.get(record.source_id);
    return {
      ...record,
      item_kind: "paper_record",
      student_name: portrait.student_name,
      student_id: portrait.student_id,
      links: {
        submission_url: source?.submission_url,
        portrait_url: portrait.portrait_url,
      },
    };
  });
  return (
    <div className="agent-portrait">
      <p>
        {[
          portrait.student_name,
          portrait.year,
          portrait.degree,
          portrait.major,
          portrait.stage,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
      {portrait.teachers?.length ? (
        <p>指导教师：{portrait.teachers.map(({ name }) => name).join("、")}</p>
      ) : null}
      <p>
        论文 {portrait.counts?.paper_records ?? 0} 条 · 年度报告{" "}
        {portrait.counts?.annual_records ?? 0} 条
      </p>
      {portrait.ability_assessment ? (
        <p>能力评价：{portrait.ability_assessment}</p>
      ) : null}
      {portrait.pending_snapshot_count > 0 ? (
        <p>待生成画像快照 {portrait.pending_snapshot_count} 条</p>
      ) : null}
      {portrait.notice ? <p>{portrait.notice}</p> : null}
      <div className="paper-actions">
        <SafeLink
          type="portrait"
          url={portrait.portrait_url}
          expectedId={portrait.student_id}
          onOpen={onOpen}
        >
          查看完整成长画像
        </SafeLink>
      </div>
      <PaperTable items={records} onOpen={onOpen} />
    </div>
  );
}

function Evidence({ sources, notice, onOpen }) {
  if (!sources.length) {
    return notice ? <p className="data-as-of">{notice}</p> : null;
  }
  return (
    <details className="evidence-details">
      <summary>查看材料依据（{sources.length}）</summary>
      {notice ? <p>{notice}</p> : null}
      {sources.map((source, index) => {
        const fields = source.field_pointers ?? [];
        const title = fields.find(({ field }) => field === "title")?.value;
        const verification = [
          ...new Set(fields.map((field) => field.verification).filter(Boolean)),
        ];
        return (
          <div className="source-detail" key={source.source_id ?? index}>
            <strong>
              {title || labelFor(source.kind) || "材料依据"}
              {source.version_number
                ? ` · 提交版本 V${source.version_number}`
                : ""}
            </strong>
            {verification.length || source.archived_at ? (
              <p>
                {[
                  ...verification.map(formatValue),
                  source.archived_at
                    ? `归档于${formatDate(source.archived_at)}`
                    : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            ) : null}
            <MaterialFields
              fields={fields
                .filter(({ field }) => field !== "title")
                .map(({ field, value }) => [field, value])}
            />
            <div className="paper-actions">
              <SafeLink
                type="submission"
                url={source.submission_url}
                expectedId={source.submission_id}
                onOpen={onOpen}
              >
                原始提交
              </SafeLink>
              <SafeLink
                type="portrait"
                url={source.portrait_url}
                expectedId={source.student_id}
                onOpen={onOpen}
              >
                学生画像
              </SafeLink>
              {(source.files ?? []).map((file) => (
                <SafeLink
                  key={file.file_id ?? file.download_url}
                  type="file"
                  url={file.download_url}
                  expectedId={file.file_id}
                >
                  {file.name || "下载附件"}
                </SafeLink>
              ))}
            </div>
          </div>
        );
      })}
    </details>
  );
}

function singleStudentName(result) {
  const items = result.items ?? [];
  const student = items[0];
  if (
    !student?.student_name ||
    !validId(student.student_id) ||
    !items.every(
      ({ student_id, student_name }) =>
        student_id === student.student_id &&
        student_name === student.student_name,
    )
  ) {
    return "";
  }
  const count = result.summary?.metrics?.find(
    ({ key }) => key === "paper_student_count",
  )?.value;
  const page = result.pagination;
  const complete =
    page?.page === 1 && page.has_more === false && page.total === items.length;
  return count === 1 || (count == null && complete) ? student.student_name : "";
}

export function ResultCard({
  result,
  query,
  onDrilldown,
  onAction,
  onOpen,
  showAnalysis,
}) {
  const specification = appliedQuery(result, query);
  const summary = result.summary ?? {};
  const items = (result.items ?? []).filter(
    ({ item_kind }) =>
      item_kind === "paper_record" || item_kind === "student_summary",
  );
  const portrait = result.portrait;
  const student = singleStudentName(result);
  const sources = result.sources ?? [];
  const names = new Map(
    [...items, ...(portrait ? [portrait] : [])]
      .filter((item) => item.student_name)
      .map((item) => [item.student_id, item.student_name]),
  );
  const heading = portrait
    ? `${portrait.student_name}的成长画像`
    : titleFromQuery(specification, student ? `${student}的论文` : "论文查询");
  const recordCount = summary.metrics?.find(
    ({ key }) => key === "paper_record_count",
  )?.value;
  const conclusion =
    student && recordCount != null && !summary.headline?.includes(student)
      ? `${student}有 ${recordCount} 条符合条件的论文申报记录。`
      : summary.headline;
  return (
    <section
      className="agent-result"
      id={runAnchor(result.query_run_id)}
      tabIndex={-1}
    >
      <h4>{heading}</h4>
      <FilterChips
        query={specification}
        basis={specification?.basis ?? summary.basis}
        names={names}
        onDrilldown={onDrilldown}
      />
      {summary.data_as_of ? (
        <p className="data-as-of">
          <time dateTime={summary.data_as_of}>
            截至 {summary.data_as_of.slice(0, 10)}
          </time>
        </p>
      ) : null}
      <Clarification prompt={result.clarification} onAction={onAction} />
      {showAnalysis && conclusion ? (
        <div className="agent-analysis">
          <p>{conclusion}</p>
        </div>
      ) : null}
      <MetricStrip
        metrics={summary.metrics}
        status={publicationFilter(specification)}
        onDrilldown={onDrilldown}
      />
      <Breakdown
        rows={publicationBreakdown(result, specification)}
        onDrilldown={onDrilldown}
      />
      {!portrait || specification?.operation !== "portrait" ? (
        <PaperTable items={items} onOpen={onOpen} />
      ) : null}
      {result.pagination?.total === 0 && !portrait && !showAnalysis ? (
        <p>当前筛选范围内没有符合条件的论文申报记录。</p>
      ) : null}
      {portrait ? (
        <Portrait portrait={portrait} sources={sources} onOpen={onOpen} />
      ) : null}
      <Evidence sources={sources} notice={summary.notice} onOpen={onOpen} />
    </section>
  );
}

export function Clarification({ prompt, onAction }) {
  if (!prompt) return null;
  const suggestions = [...new Set(prompt.suggestions ?? [])];
  const candidates = (prompt.student_candidates ?? []).filter(
    (candidate) => validId(candidate.student_id) && candidate.student_name,
  );
  return (
    <div className="clarification">
      <p>{prompt.message}</p>
      {suggestions.length || candidates.length ? (
        <div className="action-chips">
          {suggestions.map((suggestion) => (
            <button
              type="button"
              key={suggestion}
              onClick={() => onAction(suggestion)}
            >
              {suggestion}
            </button>
          ))}
          {candidates.map((candidate) => {
            const label = [
              candidate.student_name,
              candidate.year,
              candidate.degree,
              candidate.major,
            ]
              .filter(Boolean)
              .map(formatValue)
              .join(" · ");
            const subject = prompt.message?.includes("画像")
              ? "成长画像"
              : "论文";
            return (
              <button
                type="button"
                key={candidate.student_id}
                onClick={() =>
                  onAction(
                    `查看${label}的${subject}（学生编号：${candidate.student_id}）`,
                  )
                }
              >
                {label}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export function Followups({ result, onAction }) {
  const query = appliedQuery(result);
  if (query?.domain !== "paper" || result.clarification) return null;
  const questions = [];
  const student = result.portrait?.student_name || singleStudentName(result);
  if (student) {
    questions.push([
      "查看该生全部成果",
      `查看${student}的全部论文成果，不限日期和发表状态`,
    ]);
  }
  if (query.operation === "portrait") {
    if (
      student &&
      result.portrait?.records?.some(
        ({ publication_status }) => publication_status === "published",
      )
    ) {
      questions.push(["查看该生已发表论文", `查看${student}已发表的论文`]);
    }
  } else {
    questions.push(
      query.filters?.some(({ field }) => field === "degree")
        ? ["查看全部培养层次"]
        : ["只看博士"],
      publicationFilter(query) === "published"
        ? ["查看全部发表状态"]
        : ["只看已发表"],
    );
    if (query.operation === "aggregate") questions.push(["查看论文申报明细"]);
  }
  if (!questions.length) return null;
  return (
    <div className="follow-ups">
      {questions.slice(0, 3).map(([label, question = label]) => (
        <button type="button" key={label} onClick={() => onAction(question)}>
          {label}
        </button>
      ))}
    </div>
  );
}
