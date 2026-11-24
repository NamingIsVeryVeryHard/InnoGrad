import chartSource from "../node_modules/chart.js/dist/chart.umd.min.js?raw";
import { formatDate, formatValue, labelFor } from "./field-labels.js";

const PATCH_KEYS = new Set([
  "operation",
  "basis",
  "time_range",
  "clear_time_range",
  "set_filters",
  "remove_filter_fields",
  "group_by",
  "distinct_subject",
  "include",
  "sort",
  "page",
  "page_size",
  "reset_page",
]);

const publicationDates = {
  submitted: "submission_date",
  accepted: "acceptance_date",
  published: "publication_date",
};

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function itemDate(item) {
  const field = publicationDates[item.publication_status] || "status_date";
  return item[field] || item.status_date || item.latest_status_date || "";
}

function filterLabel(filter) {
  return `${labelFor(filter.field)}：${formatValue(filter.value)}`;
}

function mapItem(item, duplicateTitles) {
  const date = itemDate(item);
  return {
    statusLabel: formatValue(item.publication_status),
    dateLabel: date
      ? `${labelFor(publicationDates[item.publication_status] || "status_date")} ${formatDate(date)}`
      : "",
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
    duplicateTitle: Boolean(item.title && duplicateTitles.has(item.title)),
  };
}

function mapPortrait(portrait) {
  if (!portrait) return null;
  return {
    studentId: portrait.student_id || "",
    studentName: portrait.student_name || "",
    studentNumber: portrait.student_number || "",
    year: portrait.year || "",
    degree: formatValue(portrait.degree),
    major: portrait.major || "",
    direction: portrait.direction || "",
    stage: portrait.stage || "",
    counts: portrait.counts || {},
    notice: portrait.notice || "",
    records: asArray(portrait.records).map((record) => ({
      ...mapItem(record, new Set()),
      studentId: portrait.student_id || "",
      studentName: portrait.student_name || "",
    })),
  };
}

function mapRun(result) {
  const items = asArray(result.items).filter(
    (item) =>
      item.item_kind === "paper_record" || item.item_kind === "student_summary",
  );
  const duplicateTitles = new Set(
    [...new Set(items.map((item) => item.title).filter(Boolean))].filter(
      (title) => items.filter((item) => item.title === title).length > 1,
    ),
  );
  const query = result.applied_query || {};
  const summary = result.summary || {};
  return {
    runId: result.query_run_id,
    title: summary.headline || labelFor(query.operation || "paper"),
    headline: summary.headline || "",
    basisLabel: formatValue(summary.basis || query.basis),
    asOfDate: summary.data_as_of ? formatDate(summary.data_as_of) : "",
    scopeStudentCount: summary.scope_student_count ?? 0,
    filters: asArray(query.filters).map(filterLabel),
    metrics: asArray(summary.metrics)
      .filter((metric) => metric.value != null)
      .map((metric) => ({
        key: metric.key || "",
        label: metric.label || labelFor(metric.key),
        value: metric.value,
        unit: metric.unit || "",
      })),
    breakdown: asArray(summary.breakdown).map((row) => ({
      label: formatValue(row.label),
      recordCount: row.record_count ?? 0,
      studentCount: row.student_count ?? 0,
    })),
    items: items.map((item) => mapItem(item, duplicateTitles)),
    portrait: mapPortrait(result.portrait),
  };
}

export function buildVisualData(results) {
  return {
    runs: asArray(results)
      .filter((result) => result?.status === "ok" && result.query_run_id)
      .map(mapRun),
  };
}

export function buildAllowlist(results) {
  const submissionIds = new Set();
  const studentIds = new Set();
  const runIds = new Set();
  for (const result of asArray(results)) {
    if (result?.query_run_id) runIds.add(result.query_run_id);
    for (const item of asArray(result?.items)) {
      if (item.submission_id) submissionIds.add(item.submission_id);
      if (item.student_id) studentIds.add(item.student_id);
    }
    for (const source of asArray(result?.sources)) {
      if (source.submission_id) submissionIds.add(source.submission_id);
      if (source.student_id) studentIds.add(source.student_id);
    }
    const portrait = result?.portrait;
    if (portrait?.student_id) studentIds.add(portrait.student_id);
    for (const record of asArray(portrait?.records)) {
      if (record.submission_id) submissionIds.add(record.submission_id);
      if (record.student_id) studentIds.add(record.student_id);
    }
  }
  return { submissionIds, studentIds, runIds };
}

function serialize(value) {
  return JSON.stringify(value)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function proxyDocument() {
  return `<!doctype html><meta charset="utf-8"><style>
    html, body {
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
    }
  </style><script>
    var guest;
    window.addEventListener("message", function(event) {
      var message = event.data;
      if (!message || message.jsonrpc !== "2.0") return;
      if (event.source === parent) {
        if (message.method === "ui/notifications/sandbox-resource-ready") {
          guest = document.createElement("iframe");
          guest.setAttribute("sandbox", "allow-scripts");
          guest.style.cssText = "width:100%;height:100%;border:0;display:block";
          guest.srcdoc = message.params.html;
          document.body.replaceChildren(guest);
        } else if (guest) {
          guest.contentWindow.postMessage(message, "*");
        }
      } else if (guest && event.source === guest.contentWindow && message.method === "ui/message") {
        parent.postMessage(message, "*");
      }
    });
    parent.postMessage({
      jsonrpc: "2.0",
      method: "ui/notifications/sandbox-proxy-ready",
      params: {}
    }, "*");
  </script>`;
}

const sandboxProxyUrl = new URL(
  `data:text/html;charset=utf-8,${encodeURIComponent(proxyDocument())}`,
);

export function buildSandboxDocument({ channelId, html, data }) {
  const dataScript = serialize(data);
  const channelScript = serialize(channelId);
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; font-src 'none'; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none';">
  <style>
    :root {
      --ig-accent: #a51f35;
      --ig-bg: #ffffff;
      --ig-surface: #fffafa;
      --ig-border: #eee4e6;
      --ig-text: #29252a;
      --ig-muted: #766a6f;
      --ig-radius: 12px;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--ig-text);
      background: var(--ig-bg);
    }
    *, *::before, *::after { box-sizing: border-box; }
    body { margin: 0; overflow-x: hidden; padding: 14px; line-height: 1.55; }
    #ig-root { display: flow-root; }
    button, input, textarea, select { font: inherit; }
    button { cursor: pointer; }
    canvas, svg, img { max-width: 100%; }
  </style>
  <script>${chartSource}</script>
</head>
<body>
  <script>
    (() => {
      const channelId = ${channelScript};
      const data = ${dataScript};
      let messageId = 0;
      const post = (payload) => window.parent.postMessage({
        jsonrpc: "2.0",
        id: ++messageId,
        method: "ui/message",
        params: {
          role: "user",
          content: [{ type: "text", text: JSON.stringify({ channelId, ...payload }) }]
        }
      }, "*");
      document.addEventListener("DOMContentLoaded", () => requestAnimationFrame(() => {
        const root = document.getElementById("ig-root");
        const report = (type) => {
          const contentHeight = root.getBoundingClientRect().height;
          post({ type, height: contentHeight < 24 ? contentHeight : Math.ceil(contentHeight + 28) });
        };
        report("ready");
        new ResizeObserver(() => report("resize")).observe(root);
      }));
      const deepFreeze = (value) => {
        if (!value || typeof value !== "object" || Object.isFrozen(value)) return value;
        Object.freeze(value);
        Object.values(value).forEach(deepFreeze);
        return value;
      };
      window.__INNOGRAD_DATA__ = deepFreeze(data);
      window.innograd = Object.freeze({
        openSubmission: (submissionId) => post({ type: "intent", action: "open_submission", submissionId }),
        openPortrait: (studentId) => post({ type: "intent", action: "open_portrait", studentId }),
        drilldown: (runId, patch, label) => post({ type: "intent", action: "drilldown", runId, patch, label }),
        ask: (message) => post({ type: "prompt", message }),
      });
      window.addEventListener("error", (event) => post({ type: "error", message: event.message || "sandbox error" }));
      window.addEventListener("unhandledrejection", (event) => post({ type: "error", message: String(event.reason || "sandbox rejection") }));
    })();
  </script>
  <div id="ig-root">${html}</div>
</body>
</html>`;
}

function validPatch(patch) {
  if (!patch || typeof patch !== "object" || Array.isArray(patch)) return null;
  const keys = Object.keys(patch);
  if (keys.some((key) => !PATCH_KEYS.has(key))) return null;
  return patch;
}

export function validateSandboxAction(action, allowlist) {
  if (!action || typeof action !== "object") return null;
  const submissionIds = allowlist?.submissionIds || new Set();
  const studentIds = allowlist?.studentIds || new Set();
  const runIds = allowlist?.runIds || new Set();
  const type = action.action || action.type;
  if (type === "open_submission" && submissionIds.has(action.submissionId)) {
    return { type: "open_submission", submissionId: action.submissionId };
  }
  if (type === "open_portrait" && studentIds.has(action.studentId)) {
    return { type: "open_portrait", studentId: action.studentId };
  }
  if (type === "drilldown" && runIds.has(action.runId)) {
    const patch = validPatch(action.patch);
    const label =
      typeof action.label === "string" ? action.label.trim().slice(0, 80) : "";
    if (patch && label) return { type, runId: action.runId, patch, label };
  }
  if (type === "ask" || action.type === "prompt") {
    const message =
      typeof action.message === "string" ? action.message.trim() : "";
    if (message.length >= 1 && message.length <= 200)
      return { type: "ask", message };
  }
  return null;
}

export function parseSandboxMessage(raw, channelId, allowlist) {
  if (!raw || typeof raw !== "object") return null;
  if (raw.channelId && raw.channelId !== channelId) return null;
  const action =
    raw.type === "intent"
      ? { ...raw, type: raw.action }
      : raw.type === "prompt"
        ? { ...raw, type: "ask" }
        : raw;
  return validateSandboxAction(action, allowlist);
}

export { sandboxProxyUrl };
