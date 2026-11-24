import { formatDate, formatValue, labelFor } from "./field-labels.js";

const publicationDates = {
  submitted: "submission_date",
  accepted: "acceptance_date",
  published: "publication_date",
};
const groupFields = new Set([
  "publication_status",
  "review_status",
  "degree",
  "major",
  "year",
  "stage",
  "award_name",
  "award_level",
  "application_status",
]);

function mapItem(item, titleCounts) {
  const dateField = publicationDates[item.publication_status] || "status_date";
  const date = item[dateField] || item.status_date || item.latest_status_date;
  return {
    statusLabel: formatValue(item.publication_status),
    dateLabel: date ? `${labelFor(dateField)} ${formatDate(date)}` : "",
    submissionId: item.submission_id || "",
    studentId: item.student_id || "",
    studentName: item.student_name || "未标注学生",
    title: item.title || "",
    versionNumber: item.version_number ?? null,
    degree: formatValue(item.degree),
    major: item.major || "",
    year: item.year || "",
    journal: item.journal || "",
    contribution: item.contribution || "",
    duplicateTitle: titleCounts.get(item.title) > 1,
  };
}

function mapPortrait(portrait) {
  if (!portrait) return null;
  const { student_id, student_name } = portrait;
  return {
    studentId: student_id,
    studentName: student_name,
    studentNumber: portrait.student_number || "",
    year: portrait.year || "",
    degree: formatValue(portrait.degree),
    major: portrait.major || "",
    direction: portrait.direction || "",
    stage: portrait.stage || "",
    counts: portrait.counts || {},
    notice: portrait.notice || "",
    records: (portrait.records ?? []).map((record) =>
      mapItem({ ...record, student_id, student_name }, new Map()),
    ),
  };
}

export function visualRuns(visual, results) {
  if (
    visual?.kind !== "html_sandbox" ||
    typeof visual.html !== "string" ||
    !visual.html.trim() ||
    !Array.isArray(visual.source_run_ids) ||
    !visual.source_run_ids.length
  ) {
    return [];
  }

  const byId = new Map(
    results
      .filter((result) => result.status === "ok")
      .map((result) => [result.query_run_id, result]),
  );
  const sources = [...new Set(visual.source_run_ids)].map((id) => byId.get(id));
  return sources.every(Boolean) ? sources : [];
}

export function buildVisualData(results) {
  return {
    runs: results.map((result) => {
      const query = result.applied_query ?? {};
      const summary = result.summary ?? {};
      const items = (result.items ?? []).filter(
        ({ item_kind }) =>
          item_kind === "paper_record" || item_kind === "student_summary",
      );
      const titleCounts = new Map();
      for (const { title } of items) {
        if (title) titleCounts.set(title, (titleCounts.get(title) ?? 0) + 1);
      }
      return {
        runId: result.query_run_id,
        title: summary.headline || labelFor(query.operation || "paper"),
        headline: summary.headline || "",
        basisLabel: formatValue(summary.basis || query.basis),
        asOfDate: summary.data_as_of ? formatDate(summary.data_as_of) : "",
        scopeStudentCount: summary.scope_student_count ?? 0,
        filters: (query.filters ?? []).map(
          (filter) => `${labelFor(filter.field)}：${formatValue(filter.value)}`,
        ),
        metrics: (summary.metrics ?? []).map((metric) => ({
          key: metric.key,
          label: metric.label,
          value: metric.value,
          unit: metric.unit,
          drilldownPatch: metric.drilldown_patch ?? null,
        })),
        breakdown: (summary.breakdown ?? []).map((row) => ({
          label: row.label.split(" / ").map(formatValue).join(" / "),
          group_key: Object.fromEntries(
            Object.entries(row.group_key ?? {}).filter(
              ([field, value]) =>
                groupFields.has(field) && typeof value === "string",
            ),
          ),
          recordCount: row.record_count,
          studentCount: row.student_count,
          drilldownPatch: row.drilldown_patch ?? null,
        })),
        items: items.map((item) => mapItem(item, titleCounts)),
        portrait: mapPortrait(result.portrait),
      };
    }),
  };
}

export function resolveVisualAction(action, data, sources) {
  if (action.type === "ask") {
    const message =
      typeof action.message === "string" ? action.message.trim() : "";
    return message.length && message.length <= 200
      ? { type: "ask", message }
      : null;
  }
  if (action.type === "drilldown") {
    if (action.group !== "breakdown" && action.group !== "metrics") return null;
    const run = data.runs.find(({ runId }) => runId === action.runId);
    if (!run || !Number.isSafeInteger(action.index) || action.index < 0)
      return null;
    const rows = action.group === "breakdown" ? run.breakdown : run.metrics;
    const row = rows[action.index];
    return row?.drilldownPatch
      ? {
          type: "drilldown",
          runId: run.runId,
          patch: row.drilldownPatch,
          label: row.label,
        }
      : null;
  }

  if (typeof action.id !== "string" || !action.id) return null;
  const evidence = sources.flatMap((result) => result.sources ?? []);
  if (
    action.type === "open_submission" &&
    evidence.some(({ submission_id }) => submission_id === action.id)
  ) {
    return { type: "open", target: "submission", id: action.id };
  }
  if (
    action.type === "open_portrait" &&
    evidence.some(({ student_id }) => student_id === action.id)
  ) {
    return { type: "open", target: "portrait", id: action.id };
  }
  for (const run of data.runs) {
    const items = [...run.items, ...(run.portrait?.records ?? [])];
    if (
      action.type === "open_submission" &&
      items.some(({ submissionId }) => submissionId === action.id)
    ) {
      return { type: "open", target: "submission", id: action.id };
    }
    if (
      action.type === "open_portrait" &&
      (run.portrait?.studentId === action.id ||
        items.some(({ studentId }) => studentId === action.id))
    ) {
      return { type: "open", target: "portrait", id: action.id };
    }
  }
  return null;
}
