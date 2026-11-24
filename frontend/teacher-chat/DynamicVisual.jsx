import React from "react";
import { formatDate, formatValue } from "./field-labels.js";

const titles = {
  bar: "分组统计",
  donut: "分组分布",
  metrics: "统计指标",
  records: "查询明细",
  timeline: "记录时间线",
};
const colors = ["#9e3048", "#356681", "#807044", "#5e7666", "#755779"];
const isCount = (value) => Number.isSafeInteger(value) && value >= 0;
const isId = (value) =>
  typeof value === "string" && value.length > 0 && !/[^A-Za-z0-9-]/.test(value);

function rowLabel(row, text, drilldown) {
  return drilldown && row.drilldown_patch ? (
    <button type="button" onClick={() => drilldown(row.drilldown_patch, text)}>
      {text}
    </button>
  ) : (
    <span>{text}</span>
  );
}

function chart(block, result, drilldown) {
  const students = block.measure === "student_count";
  const measure = students ? "student_count" : "record_count";
  const rows = (result.summary?.breakdown ?? []).filter((row) =>
    isCount(row[measure]),
  );
  if (!rows.length) return null;
  const maximum = Math.max(1, ...rows.map((row) => row[measure]));
  const total = rows.reduce((sum, row) => sum + row[measure], 0);
  const ring = block.type === "donut" && !students && total > 0;
  let cumulative = 0;
  const stops =
    ring &&
    rows.map((row, index) => {
      const start = (cumulative / total) * 100;
      cumulative += row[measure];
      return `${colors[index % colors.length]} ${start}% ${(cumulative / total) * 100}%`;
    });
  return (
    <>
      {ring && (
        <div className="dv-distribution">
          <div
            className="dv-ring"
            aria-hidden="true"
            style={{ backgroundImage: `conic-gradient(${stops.join(",")})` }}
          />
          <span>占所示各组记录数之和（{total} 条）的比例</span>
        </div>
      )}
      {students && <p>人数按组统计，同一学生可能出现在多个组中。</p>}
      <ul className="dv-chart">
        {rows.map((row, index) => {
          const label = row.label.split(" / ").map(formatValue).join(" / ");
          const text = `${label} ${row[measure]}${students ? "人" : "条"}`;
          const backgroundColor = colors[index % colors.length];
          return (
            <li key={index}>
              {ring && (
                <i
                  className="dv-key"
                  aria-hidden="true"
                  style={{ backgroundColor }}
                />
              )}
              {rowLabel(row, text, drilldown)}
              {!ring && (
                <div className="dv-track" aria-hidden="true">
                  <i
                    style={{
                      backgroundColor,
                      width: `${(100 * row[measure]) / maximum}%`,
                    }}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}

function metrics(block, result, drilldown) {
  const rows = (result.summary?.metrics ?? []).filter(
    (metric) =>
      isCount(metric.value) &&
      (!block.measure ||
        (block.measure === "student_count") === (metric.unit === "人")),
  );
  if (!rows.length) return null;
  return (
    <dl className="dv-metrics">
      {rows.map((metric, index) => (
        <div key={index}>
          <dt>{metric.label}</dt>
          <dd>
            {drilldown && metric.drilldown_patch ? (
              <button
                type="button"
                aria-label={`${metric.label} ${metric.value}${metric.unit}`}
                onClick={() =>
                  drilldown(
                    metric.drilldown_patch,
                    `${metric.label} ${metric.value}${metric.unit}`,
                  )
                }
              >
                {metric.value}
                {metric.unit}
              </button>
            ) : (
              <>
                {metric.value}
                {metric.unit}
              </>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function records(block, result, open) {
  const timeline = block.type === "timeline";
  const portrait = result.portrait;
  const items = result.items?.length
    ? result.items
    : (portrait?.records ?? []).map((record) => ({
        ...record,
        student_name: portrait.student_name,
        student_id: portrait.student_id,
      }));
  let rows = items.map((item) => {
    const date =
      item.status_date ||
      item.latest_status_date ||
      item.submitted_at ||
      item.archived_at;
    const dateLabel = item.status_date
      ? "状态日期"
      : item.latest_status_date
        ? "最近状态"
        : item.submitted_at
          ? "提交日期"
          : "归档日期";
    const title =
      item.title ||
      (isCount(item.matched_record_count)
        ? `${item.matched_record_count} 条论文记录`
        : item.award_names?.join("、") || "奖学金申报");
    return { item, title, date, dateLabel };
  });
  if (timeline)
    rows = rows
      .filter(({ date }) => Number.isFinite(Date.parse(date)))
      .sort(
        (first, second) => Date.parse(first.date) - Date.parse(second.date),
      );
  if (!rows.length) return null;
  return (
    <ol className={timeline ? "dv-timeline" : "dv-records"}>
      {rows.map(({ item, title, date, dateLabel }, index) => (
        <li key={index}>
          {date && (
            <small>
              {dateLabel} <time dateTime={date}>{formatDate(date)}</time>
            </small>
          )}
          <strong>{title}</strong>
          <span>
            {[
              item.student_name,
              item.publication_status && formatValue(item.publication_status),
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
          {open && (
            <div className="dv-actions">
              {isId(item.submission_id) && (
                <button
                  type="button"
                  onClick={() => open("submission", item.submission_id)}
                >
                  材料详情
                </button>
              )}
              {isId(item.student_id) && (
                <button
                  type="button"
                  onClick={() => open("portrait", item.student_id)}
                >
                  成长画像
                </button>
              )}
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}

export function DynamicVisual({ spec, results, onDrilldown, onOpen }) {
  if (!Array.isArray(spec?.blocks) || !Array.isArray(results)) return null;
  const runs = new Map(
    results
      .filter((result) => result?.status === "ok")
      .map((result) => [result.query_run_id, result]),
  );
  const blocks = spec.blocks.flatMap((block, index) => {
    if (
      typeof block?.run_id !== "string" ||
      typeof block.type !== "string" ||
      !Object.hasOwn(titles, block.type)
    )
      return [];
    const result = runs.get(block.run_id);
    if (!result) return [];
    const drilldown =
      block.interaction === "drilldown" && onDrilldown
        ? (patch, label) => onDrilldown(result.query_run_id, patch, label)
        : null;
    const content =
      block.type === "metrics"
        ? metrics(block, result, drilldown)
        : ["bar", "donut"].includes(block.type)
          ? chart(block, result, drilldown)
          : records(
              block,
              result,
              block.interaction === "open_record" && onOpen,
            );
    if (!content) return [];
    return (
      <section key={index}>
        <h4>
          {(typeof block.title === "string" && block.title.trim()) ||
            titles[block.type]}
        </h4>
        {content}
      </section>
    );
  });
  if (!blocks.length) return null;
  return (
    <div
      className={`dynamic-visual${spec.layout === "grid" ? " dv-grid" : ""}`}
    >
      {blocks}
    </div>
  );
}
