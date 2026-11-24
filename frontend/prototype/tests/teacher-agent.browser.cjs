const { after, before, test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { chromium } = require("playwright");

let server;
let browser;
let origin;

before(async () => {
  const { createServer } = await import("vite");
  server = await createServer({
    root: path.resolve(__dirname, "../.."),
    server: { host: "127.0.0.1", port: 0, hmr: false, watch: null },
    optimizeDeps: { entries: ["index.html", "prototype/index.html"] },
    logLevel: "error",
  });
  await server.listen();
  origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch();
});

after(async () => {
  await browser?.close();
  await server?.close();
});

const stamp = "2026-11-22T12:00:00+00:00";
const firstRun = "run-overview";
const secondRun = "run-published";
const thirdRun = "run-doctor-published";
const clearedRun = "run-all-years";
const portraitRun = "run-portrait";
const csrfToken = "teacher-csrf";
const include = ["metrics", "items", "sources"];
const yearRange = {
  from: "2026-01-01",
  to: "2026-12-31",
  field: "status_date",
};
const patch = {
  operation: "list",
  basis: null,
  time_range: null,
  clear_time_range: false,
  set_filters: [],
  remove_filter_fields: [],
  group_by: [],
  distinct_subject: "paper_record",
  include,
  sort: null,
  page: 1,
  page_size: null,
  reset_page: true,
};
const publishedPatch = {
  ...patch,
  set_filters: [
    { field: "publication_status", operator: "eq", value: "published" },
  ],
};
const unsafeText = '<span data-untrusted-markup="true">不可信文本</span>';
const unrelatedRun = "run-outside-this-turn";
const externalMarkdown = "[外部资料](https://example.invalid/reference)";
const firstQuestion = "今年论文发表情况";
const secondQuestion = "只看博士";
const namedQuestion = "请列出联调学生甲已发表的论文。";
const savedNamedQuestion = "请列出指定学生已发表的论文";
async function captureVisual(page, filename) {
  if (process.env.VISUAL_ACCEPTANCE_DIR) {
    await page.screenshot({
      path: path.join(process.env.VISUAL_ACCEPTANCE_DIR, filename),
      animations: "disabled",
    });
  }
}
const visualHtml = `
  <style>
    h3 { margin: 0 0 6px; font-size: 15px }
    .plot { position: relative; height: 168px }
    #visual-data { margin: 6px 0; font-size: 13px }
    button { background: var(--ig-surface); border: 1px solid var(--ig-border); color: var(--ig-accent); padding: 4px 9px; border-radius: 6px; font-size: 13px }
  </style>
  <section id="visual-content">
    <h3 id="visual-headline">各发表状态的申报记录数</h3>
    <div class="plot"><canvas id="visual-chart"></canvas></div>
    <p id="visual-data"></p>
    <button id="open-submission" type="button">材料详情</button>
    <button id="open-portrait" type="button">成长画像</button>
    <button id="doctor-filter" type="button">只看博士</button>
  </section>
  <script>
    const run = window.__INNOGRAD_DATA__.runs[0];
    document.querySelector("#visual-data").textContent =
      run.items[0].studentName + " · " + run.items[0].title;
    new Chart(document.querySelector("#visual-chart"), {
      type: "bar",
      data: {
        labels: run.breakdown.map((row) => row.label),
        datasets: [{ data: run.breakdown.map((row) => row.recordCount), backgroundColor: "#a51f35" }],
      },
      options: { animation: false, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } }, plugins: { legend: { display: false } } },
    });
    document.querySelector("#open-submission").onclick = () =>
      window.innograd.openSubmission(run.items[0].submissionId);
    document.querySelector("#open-portrait").onclick = () =>
      window.innograd.openPortrait(run.items[0].studentId);
    document.querySelector("#doctor-filter").onclick = () =>
      window.innograd.drilldown(run.runId, { set_filters: [{ field: "degree", operator: "eq", value: "博士" }] }, "只看博士");
  </script>
`;

function visualResponse(reply, html = visualHtml) {
  return {
    ...reply,
    analysis: "今年共有 5 条论文申报记录，涉及 2 名学生，其中 3 条已发表。",
    visual: {
      kind: "html_sandbox",
      title: "年度论文统计",
      html,
      source_run_ids: [reply.results?.[0]?.query_run_id || firstRun],
    },
  };
}

function query(filters = [], overrides = {}) {
  return {
    domain: "paper",
    operation: "aggregate",
    basis: "current_effective_archives",
    time_range: yearRange,
    filters,
    group_by: ["publication_status"],
    distinct_subject: "paper_record",
    include,
    sort: { field: "status_date", direction: "desc" },
    page: 1,
    page_size: 50,
    ...overrides,
  };
}

function filter(field, value, operator = "eq") {
  return { field, value, operator };
}

function paper(overrides = {}) {
  const submissionId = overrides.submission_id || "sub-1";
  const studentId = overrides.student_id || "stu-1";
  return {
    item_kind: "paper_record",
    submission_id: submissionId,
    version_id: `version-${submissionId}`,
    archive_id: `arch-${submissionId}`,
    student_id: studentId,
    student_name: "联调学生甲",
    student_number: "001",
    year: "2026级",
    title: "合成甲当年发表",
    publication_status: "published",
    status_date: "2026-10-20",
    submission_date: "2026-06-11",
    publication_date: "2026-10-20",
    journal: "教育研究",
    contribution: "负责实验与论文撰写",
    major: "智能教育",
    direction: "教育数据挖掘",
    stage: "博士阶段",
    degree: "博士",
    version_number: 1,
    review_status: "archived",
    review_actor_type: "human",
    archived_at: stamp,
    source_ids: [`version-${submissionId}`],
    links: {
      submission_url: `/api/v1/submissions/${submissionId}`,
      portrait_url: `/api/v1/students/${studentId}/portrait`,
    },
    ...overrides,
  };
}

function result(id, headline, appliedQuery, items, metrics, breakdown = []) {
  return {
    schema_version: "teacher-agent-result-1",
    conversation_id: "c1",
    query_run_id: id,
    status: "ok",
    applied_query: appliedQuery,
    summary: {
      headline,
      metrics,
      breakdown,
      scope_student_count: 2,
      data_as_of: stamp,
      basis: appliedQuery.basis,
      notice: "同一成果可能有多条申报记录。",
    },
    items,
    portrait: null,
    pagination: {
      page: 1,
      page_size: 50,
      total: items.length,
      has_more: false,
    },
    sources: items.map((item) => ({
      source_id: item.version_id,
      kind: "paper",
      student_id: item.student_id,
      submission_id: item.submission_id,
      version_id: item.version_id,
      version_number: item.version_number,
      archive_id: item.archive_id,
      field_pointers: [
        "title",
        "publication_status",
        "submission_date",
        "publication_date",
        "contribution",
      ]
        .filter((field) => item[field])
        .map((field) => ({
          field,
          pointer: `/form/${field}`,
          value: item[field],
          verification: "human_approved_submission",
        })),
      ...item.links,
      files: [
        {
          file_id: "file-1",
          name: "发表证明.pdf",
          download_url: "/api/v1/files/file-1/download",
        },
        {
          file_id: "invalid-file",
          name: "无效地址",
          download_url: "data:text/plain,invalid",
        },
      ],
    })),
  };
}

function buildScenario() {
  const doctorQuery = query([filter("degree", "博士")]);
  const publishedQuery = query(
    [filter("degree", "博士"), filter("publication_status", "published")],
    { operation: "list", group_by: [] },
  );
  const doctorItems = [
    paper(),
    paper({
      submission_id: "sub-2",
      version_number: 2,
      status_date: "2026-03-14",
      publication_date: "2026-03-14",
    }),
    paper({
      submission_id: "sub-3",
      title: "合成甲当年录用",
      publication_status: "accepted",
      status_date: "2026-02-18",
      acceptance_date: "2026-02-18",
      publication_date: null,
    }),
  ];
  const overview = result(
    firstRun,
    "年度论文统计",
    query(),
    [
      ...doctorItems,
      paper({
        submission_id: "sub-4",
        student_id: "stu-2",
        student_name: "联调学生乙",
        degree: "硕士",
        title: "合成乙当年发表",
        status_date: "2026-02-09",
        publication_date: "2026-02-09",
      }),
      paper({
        submission_id: "sub-6",
        student_id: "stu-2",
        student_name: "联调学生乙",
        degree: "硕士",
        title: "合成乙当年投稿",
        publication_status: "submitted",
        status_date: "2026-01-11",
        submission_date: "2026-01-11",
        publication_date: null,
      }),
    ],
    [
      { label: "论文申报记录数", value: 5, unit: "条", drilldown_patch: patch },
      { label: "涉及学生人数", value: 2, unit: "人", drilldown_patch: patch },
      { label: "已投稿论文记录数", value: 1, unit: "条" },
      { label: "已录用论文记录数", value: 1, unit: "条" },
      {
        label: "已发表论文记录数",
        value: 3,
        unit: "条",
        drilldown_patch: patch,
      },
    ],
    [
      {
        group_key: { publication_status: "submitted" },
        label: "submitted",
        record_count: 1,
        student_count: 1,
        drilldown_patch: patch,
      },
      {
        group_key: { publication_status: "accepted" },
        label: "accepted",
        record_count: 1,
        student_count: 1,
        drilldown_patch: patch,
      },
      {
        group_key: { publication_status: "published" },
        label: "published",
        record_count: 3,
        student_count: 2,
        drilldown_patch: publishedPatch,
      },
    ],
  );
  const doctor = result(
    secondRun,
    "博士生论文统计",
    doctorQuery,
    doctorItems,
    [
      { label: "论文申报记录数", value: 3, unit: "条", drilldown_patch: patch },
      { label: "涉及学生人数", value: 1, unit: "人", drilldown_patch: patch },
      {
        label: "已发表论文记录数",
        value: 2,
        unit: "条",
        drilldown_patch: patch,
      },
      { label: "已录用论文记录数", value: 1, unit: "条" },
      { label: "已投稿论文记录数", value: 0, unit: "条" },
    ],
    [
      {
        group_key: { publication_status: "published" },
        label: "published",
        record_count: 2,
        student_count: 1,
        drilldown_patch: publishedPatch,
      },
    ],
  );
  const published = result(
    thirdRun,
    "已发表论文明细",
    publishedQuery,
    doctor.items.slice(0, 2),
    [
      {
        key: "paper_record_count",
        label: "论文申报记录数",
        value: 2,
        unit: "条",
        drilldown_patch: patch,
      },
      {
        key: "paper_student_count",
        label: "涉及学生人数",
        value: 1,
        unit: "人",
        drilldown_patch: patch,
      },
      {
        key: "paper_submitted_record_count",
        label: "已投稿论文记录数",
        value: 0,
        unit: "条",
      },
      {
        key: "paper_accepted_record_count",
        label: "已录用论文记录数",
        value: 0,
        unit: "条",
      },
      {
        key: "paper_published_record_count",
        label: "已发表论文记录数",
        value: 2,
        unit: "条",
        drilldown_patch: patch,
      },
      {
        key: "paper_published_student_count",
        label: "已发表涉及学生数",
        value: 1,
        unit: "人",
        drilldown_patch: patch,
      },
    ],
    [
      {
        group_key: { publication_status: "published" },
        label: "published",
        record_count: 2,
        student_count: 1,
        drilldown_patch: publishedPatch,
      },
    ],
  );
  const older = paper({
    submission_id: "sub-5",
    title: "往年正式归档论文",
    status_date: "2025-09-18",
    submission_date: "2025-06-11",
    publication_date: "2025-09-18",
  });
  const cleared = result(
    clearedRun,
    "不限日期的已发表论文",
    { ...publishedQuery, time_range: null },
    [...published.items, older],
    [{ label: "已发表论文记录数", value: 3, unit: "条" }],
  );
  const [item] = published.items;
  const named = result(
    firstRun,
    "联调学生甲已发表论文",
    query(
      [
        filter("publication_status", "published"),
        filter("student_id", "stu-1"),
      ],
      {
        operation: "list",
        time_range: null,
        group_by: [],
      },
    ),
    published.items,
    published.summary.metrics,
  );
  const portrait = result(
    portraitRun,
    "联调学生甲的成长画像",
    query([filter("student_id", item.student_id)], {
      operation: "portrait",
      time_range: null,
      group_by: [],
    }),
    [],
    [],
  );
  portrait.sources = published.sources.slice(0, 1);
  portrait.portrait = {
    student_id: item.student_id,
    student_name: item.student_name,
    student_number: item.student_number,
    year: item.year,
    degree: item.degree,
    major: item.major,
    direction: item.direction,
    stage: item.stage,
    teachers: [{ id: "teacher", name: "指导教师甲" }],
    basis: "current_effective_archives",
    counts: { paper_records: 2, annual_records: 1 },
    pending_snapshot_count: 0,
    ability_assessment: "待评价",
    inferences: [],
    records: [
      {
        source_id: item.version_id,
        archive_id: item.archive_id,
        submission_id: item.submission_id,
        version_id: item.version_id,
        version_number: item.version_number,
        decision_id: "decision-1",
        review_actor_type: "human",
        archived_at: stamp,
        title: item.title,
        publication_status: item.publication_status,
        status_date: item.status_date,
        journal: item.journal,
        doi: "",
        contribution: item.contribution,
      },
    ],
    portrait_url: item.links.portrait_url,
    notice: "画像只汇总可核实的归档材料。",
  };
  return { overview, doctor, published, cleared, named, portrait };
}

function holdResponse() {
  const entered = Promise.withResolvers();
  const released = Promise.withResolvers();
  return {
    entered: entered.promise,
    release: released.resolve,
    async wait() {
      entered.resolve();
      await released.promise;
    },
  };
}

async function openWorkspace(
  testContext,
  role,
  entry = "/prototype/",
  options = {},
) {
  const context = await browser.newContext({ serviceWorkers: "block" });
  const heldResponses = [];
  testContext.after(async () => {
    for (const response of heldResponses) response.release();
    await context.close();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  const errors = [];
  const reads = [];
  const writes = [];
  const scenario = buildScenario();
  const turns = [];
  const receipts = new Map();
  const faults = {
    revoked: false,
    revokedTurn: null,
    recompute: false,
    detailStatus: 200,
    runStatus: 200,
    loseNextReceipt: false,
    holdDetail: null,
    holdRun: null,
    holdTurn: null,
  };
  let created = false;

  const summary = () => ({
    id: "c1",
    title: "论文查询",
    active_domain: "paper",
    turn_count: turns.length,
    lock_version: turns.length,
    updated_at: stamp,
  });
  const currentScope = (card) =>
    faults.recompute
      ? {
          ...card,
          summary: {
            ...card.summary,
            headline: "当前有效归档中有 0 条符合条件的论文申报记录。",
            metrics: card.summary.metrics.map((metric) => ({
              ...metric,
              value: 0,
              drilldown_patch: null,
            })),
            breakdown: [],
            scope_student_count: 0,
            scope_recomputed: true,
          },
          items: [],
          sources: [],
          pagination: { ...card.pagination, total: 0 },
        }
      : card;
  const detail = () => {
    const latest = turns.at(-1);
    const isRevoked = (turn) =>
      faults.revoked || turn?.id === faults.revokedTurn;
    const latestRevoked = isRevoked(latest?.turn);
    return {
      conversation: summary(),
      active_query: latestRevoked ? null : latest?.turn.resolved_query || null,
      turns: turns.map(({ turn }) =>
        isRevoked(turn)
          ? {
              ...turn,
              user_message: "当时的查询范围已变更",
              resolved_query: null,
              access_revoked: true,
              run_id: null,
              run_ids: [],
            }
          : turn,
      ),
      latest_results: latestRevoked ? [] : latest?.results?.map(currentScope),
      latest_result:
        latestRevoked || !latest?.result ? null : currentScope(latest.result),
    };
  };
  const responseFor = (index, input) => {
    const mode = options.resultMode?.[index];
    const card = input.patch?.remove_filter_fields?.includes("degree")
      ? scenario.overview
      : input.message === "查看学生画像"
        ? scenario.portrait
        : input.message === namedQuestion
          ? scenario.named
          : [
              scenario.overview,
              scenario.doctor,
              scenario.published,
              scenario.cleared,
            ][index - 1];
    const batches = (
      ["fallback", "empty", "duplicate"].includes(mode)
        ? [scenario.overview, scenario.doctor]
        : [card]
    ).map((result) => ({ ...result, turn_id: `turn-${index}` }));
    const latest = batches.at(-1);
    const turn = {
      id: `turn-${index}`,
      turn_index: index,
      created_at: stamp,
      input_mode: input.mode,
      user_message:
        input.mode === "drilldown_patch"
          ? "筛选查询"
          : input.message === namedQuestion
            ? savedNamedQuestion
            : input.message,
      resolved_query: latest.applied_query,
      status: "succeeded",
      access_revoked: false,
      run_id: latest.query_run_id,
      run_ids: batches.map((item) => item.query_run_id),
      clarification: null,
      error_code: null,
    };
    return {
      conversation_id: "c1",
      turn,
      conversation_lock_version: index,
      ...(mode === "fallback"
        ? { result: latest }
        : {
            results:
              mode === "empty"
                ? []
                : mode === "duplicate"
                  ? [...batches, latest]
                  : batches,
            result: latest,
          }),
      analysis:
        index === 1
          ? `先统计论文 [${firstRun}]，再查看 [${unrelatedRun}]。\n${unsafeText}\n${externalMarkdown}`
          : null,
      analysis_notice:
        index === 2 ? "分析原文中的数值未能核实，请查看查询结果。" : undefined,
    };
  };

  page.on("pageerror", (error) => errors.push(error.message));
  await context.route(
    (url) =>
      ["http:", "https:"].includes(url.protocol) && url.origin !== origin,
    (route) => {
      errors.push(`External request: ${new URL(route.request().url()).origin}`);
      return route.abort();
    },
  );
  const hold = (kind) => {
    const barrier = holdResponse();
    faults[kind] = barrier;
    heldResponses.push(barrier);
    return barrier;
  };
  await context.route(
    (url) => url.origin === origin && url.pathname.startsWith("/api/v1/"),
    async (route) => {
      const request = route.request();
      const endpoint = new URL(request.url()).pathname.slice("/api/v1".length);
      if (endpoint === "/me")
        return route.fulfill({
          json: { id: role, name: "测试账号", role, csrf_token: csrfToken },
        });
      if (endpoint === "/people")
        return route.fulfill({
          json: [{ id: "stu-1", name: "联调学生甲", role: "student" }],
        });
      if (endpoint === "/students")
        return route.fulfill({
          json: [
            {
              id: "stu-1",
              name: "联调学生甲",
              number: "001",
              year: "2026",
              degree: "博士",
              major: "计算机科学",
              stage: "博士阶段",
              teachers: [],
            },
          ],
        });
      if (endpoint === "/submissions/sub-1")
        return route.fulfill({
          json: {
            id: "sub-1",
            student_id: "stu-1",
            reviewer_id: "teacher",
            kind: "paper",
            status: "archived",
            lock_version: 1,
            current_version_id: "version-1",
            versions: [
              {
                id: "version-1",
                number: 1,
                created_at: "2026-06-11T00:00:00Z",
                snapshot: {
                  form: {
                    title: "合成甲当年发表",
                    publication_status: "published",
                    submission_date: "2026-06-11",
                    publication_date: "2026-10-20",
                    contribution: "负责实验与论文撰写",
                  },
                  file_ids: ["file-1"],
                  references: [],
                },
              },
            ],
            files: [{ id: "file-1", name: "发表证明.pdf", size: 100 }],
            decisions: [],
            reviewer_changes: [],
            created_at: "2026-06-01T00:00:00Z",
            ai_jobs: [],
          },
        });
      if (endpoint === "/students/stu-1/portrait")
        return route.fulfill({
          json: {
            periods: ["2026"],
            warnings: [],
            entries: [],
            counts: {
              materials: 2,
              archives: 2,
              papers: 2,
              annual: 0,
              pending: 0,
              returned: 0,
            },
            dimensions: [],
            sources: [],
            trend: [],
            coverage: 1,
            notice: "材料观察",
          },
        });
      if (endpoint === "/students/stu-1/growth")
        return route.fulfill({
          json: {
            periods: ["2026"],
            warnings: [],
            entries: [],
            counts: {
              materials: 2,
              archives: 2,
              papers: 2,
              annual: 0,
              pending: 0,
              returned: 0,
            },
            dimensions: [],
            sources: [],
            trend: [],
            coverage: 1,
            notice: "材料观察",
          },
        });
      if (!endpoint.startsWith("/teacher-agent/"))
        return route.fulfill({ json: [] });
      if (request.method() === "GET") {
        reads.push(endpoint);
        if (endpoint.endsWith("/conversations"))
          return route.fulfill({ json: created ? [summary()] : [] });
        if (endpoint.includes("/runs/")) {
          await faults.holdRun?.wait();
          const runId = endpoint.split("/").at(-1);
          const card = turns
            .flatMap(({ results, result }) => results ?? [result])
            .find((item) => item.query_run_id === runId);
          const revoked =
            faults.revoked || card?.turn_id === faults.revokedTurn;
          if (revoked || faults.runStatus !== 200) {
            return route.fulfill({
              status: revoked ? 404 : faults.runStatus,
              json: { detail: "查询结果不可访问", code: "not_found" },
            });
          }
          return card
            ? route.fulfill({ json: currentScope(card) })
            : route.fulfill({
                status: 404,
                json: { detail: "查询结果不可访问" },
              });
        }
        await faults.holdDetail?.wait();
        if (faults.detailStatus !== 200) {
          return route.fulfill({
            status: faults.detailStatus,
            json: { detail: "对话不可访问" },
          });
        }
        return route.fulfill({ json: detail() });
      }
      const body = request.postDataJSON();
      writes.push({ endpoint, body, headers: request.headers() });
      if (endpoint.endsWith("/conversations")) {
        created = true;
        return route.fulfill({ status: 201, json: summary() });
      }
      const key = request.headers()["idempotency-key"];
      await faults.holdTurn?.wait();
      if (receipts.has(key)) return route.fulfill({ json: receipts.get(key) });
      if (
        faults.rejectNextTurn ||
        body.expected_lock_version !== turns.length
      ) {
        faults.rejectNextTurn = false;
        return route.fulfill({
          status: 409,
          json: { detail: "对话版本已更新" },
        });
      }
      const reply = responseFor(turns.length + 1, body.input);
      const response = options.turnResponse?.(reply) ?? reply;
      turns.push(response);
      receipts.set(key, response);
      if (faults.loseNextReceipt) {
        faults.loseNextReceipt = false;
        return route.abort();
      }
      return route.fulfill({ json: response });
    },
  );

  const panel = page.getByRole("dialog", { name: "InnoGrad Agent 对话" });
  const openAgent = async () => {
    await page
      .getByRole("button", { name: "打开 Agent 助手", exact: true })
      .click();
    await panel.waitFor();
    await panel
      .getByLabel(
        role === "teacher" || role === "manager" ? "你的问题" : "输入消息",
      )
      .waitFor();
  };
  const sendQuestion = async (question) => {
    const label =
      role === "teacher" || role === "manager" ? "你的问题" : "输入消息";
    await panel.getByLabel(label).fill(question);
    await panel
      .getByRole("button", {
        name:
          role === "teacher" || role === "manager"
            ? /发送问题|发送追问/
            : "发送消息",
      })
      .click();
  };
  await page.goto(origin + entry);
  await page
    .getByRole("button", {
      name: entry === "/" ? "退出" : "当前账号与系统设置",
      exact: true,
    })
    .waitFor();
  return {
    page,
    panel,
    openAgent,
    sendQuestion,
    errors,
    reads,
    writes,
    turns,
    faults,
    hold,
  };
}

const conversationEndpoint = "/teacher-agent/conversations/c1";
const turnEndpoint = `${conversationEndpoint}/turns`;
const runEndpoint = (id) => `/teacher-agent/runs/${id}`;
const resultCard = (panel, id) => panel.locator(`#agent-run-${id}`);
const userBubbles = (panel) => panel.locator(".teacher-turn .bubble.user");
const conversationPicker = (panel) => panel.getByLabel("最近对话");

async function assertTurnCount(panel, count) {
  const selected = await conversationPicker(panel)
    .locator("option:checked")
    .innerText();
  assert.match(selected, /论文查询/);
  assert.match(selected, new RegExp(`\\b${count}\\s*轮`));
}

function assertTurnRequest(write, expectedVersion, input) {
  assert.equal(write.endpoint, turnEndpoint);
  assert.deepEqual(write.body, {
    expected_lock_version: expectedVersion,
    input,
  });
  assert.equal(write.headers["x-csrf-token"], csrfToken);
  assert.ok(write.headers["idempotency-key"]);
}

test("teacher opens the floating popup without a redundant page", async (testContext) => {
  const { page, panel, openAgent, errors } = await openWorkspace(
    testContext,
    "teacher",
  );
  assert.equal(
    await page
      .getByRole("button", { name: "Agent 论文问答", exact: true })
      .count(),
    0,
  );
  await openAgent();
  await panel
    .getByRole("heading", { name: "你好，今天想查哪类论文成果？", exact: true })
    .waitFor();
  assert.equal(new URL(page.url()).hash, "");
  await page.keyboard.press("Escape");
  await panel.waitFor({ state: "hidden" });
  assert.equal(
    await page
      .getByRole("button", { name: "打开 Agent 助手", exact: true })
      .evaluate((button) => button.getRootNode().activeElement === button),
    true,
  );
  assert.deepEqual(errors, []);
});

test("teacher renders Chinese results, citations, evidence, and material details", async (testContext) => {
  const { page, panel, openAgent, sendQuestion, writes, errors } =
    await openWorkspace(testContext, "teacher");
  await openAgent();
  await sendQuestion(firstQuestion);
  const card = resultCard(panel, firstRun);
  await card.waitFor();
  assert.equal(await panel.locator(".agent-result").count(), 1);
  assert.equal(await userBubbles(panel).first().innerText(), firstQuestion);
  assert.deepEqual(writes[0].body, { domain: "paper" });
  assert.equal(writes[0].endpoint, "/teacher-agent/conversations");
  assert.ok(writes[0].headers["idempotency-key"]);
  assertTurnRequest(writes[1], 0, {
    mode: "natural_language",
    message: firstQuestion,
  });
  assert.equal(await conversationPicker(panel).inputValue(), "c1");
  await assertTurnCount(panel, 1);
  await card.getByText(/截至\s*2026-11-22/).waitFor();
  await card.getByRole("button", { name: /已发表\s*3\s*条.*2\s*人/ }).waitFor();
  const workspaceHash = new URL(page.url()).hash;
  await panel.getByRole("link", { name: `[${firstRun}]`, exact: true }).click();
  assert.equal(new URL(page.url()).hash, workspaceHash);
  assert.equal(
    await card.evaluate((node) => node.getRootNode().activeElement === node),
    true,
  );
  assert.ok(
    (await panel.locator(".agent-analysis").innerText()).includes(unsafeText),
  );
  assert.equal(await panel.locator("[data-untrusted-markup]").count(), 0);
  assert.equal(
    await panel
      .getByRole("link", { name: `[${unrelatedRun}]`, exact: true })
      .count(),
    0,
  );
  await panel.getByText("外部资料").first().waitFor();
  assert.equal(await panel.getByRole("link", { name: "外部资料" }).count(), 0);
  await panel.getByRole("button", { name: "展开宽浮窗", exact: true }).click();
  assert.equal(
    await panel.evaluate((node) => node.classList.contains("is-wide")),
    true,
  );
  const width = await panel.evaluate(
    (node) => node.getBoundingClientRect().width,
  );
  assert.ok(width >= 600);
  assert.equal(await card.locator(".paper-table-head").isVisible(), true);
  await panel
    .getByRole("button", { name: "恢复默认宽度", exact: true })
    .click();
  assert.equal(await panel.evaluate((element) => element.offsetWidth), 420);
  assert.equal(await card.locator(".paper-table-head").isVisible(), false);
  const evidence = card.locator(".evidence-details").first();
  await evidence.getByText(/查看材料依据/).click();
  await evidence.getByText("发表状态", { exact: true }).first().waitFor();
  await evidence.getByText("已发表", { exact: true }).first().waitFor();
  assert.equal(
    await evidence
      .getByRole("link", { name: "发表证明.pdf", exact: true })
      .first()
      .getAttribute("href"),
    "/api/v1/files/file-1/download",
  );
  assert.equal(
    await evidence.getByText("无效地址", { exact: true }).count(),
    0,
  );
  assert.equal(await evidence.locator('a[href^="data:"]').count(), 0);
  await card
    .getByRole("button", { name: "材料详情", exact: true })
    .first()
    .click();
  await page
    .getByRole("heading", { name: "论文成果 · 材料详情", exact: true })
    .waitFor();
  assert.equal(page.url().includes("/api/v1/submissions/"), false);
  assert.deepEqual(errors, []);
});

test(
  "visual sandbox renders offline Chart.js with strict permissions and verified actions",
  { timeout: 15000 },
  async (testContext) => {
    const { page, panel, openAgent, sendQuestion, writes, errors } =
      await openWorkspace(testContext, "teacher", "/prototype/", {
        turnResponse: visualResponse,
      });
    await page.setViewportSize({ width: 1440, height: 900 });
    await openAgent();
    await sendQuestion(firstQuestion);
    await page.evaluate(() => {
      window.__visualOpenCount = 0;
      window.addEventListener("innograd:open-submission", () => {
        window.__visualOpenCount += 1;
      });
    });
    const visual = panel.locator(".visual-sandbox-ready").first();
    await visual.waitFor();
    const frame = visual.locator("iframe").first();
    assert.equal(await frame.getAttribute("sandbox"), "allow-scripts");
    assert.equal(
      await frame.evaluate((node) =>
        node.getAttribute("sandbox").includes("allow-same-origin"),
      ),
      false,
    );
    assert.equal(
      await frame.evaluate((node) =>
        ["allow-forms", "allow-popups", "allow-top-navigation"].some((value) =>
          node.getAttribute("sandbox").includes(value),
        ),
      ),
      false,
    );
    const guest = frame.contentFrame().locator("iframe").first().contentFrame();
    await guest.locator("#visual-headline").waitFor();
    await guest.locator("#visual-chart").waitFor();
    assert.equal(
      await guest.locator("#visual-chart").evaluate((node) => node.tagName),
      "CANVAS",
    );
    assert.match(await guest.locator("#visual-data").innerText(), /联调学生甲/);
    assert.ok((await frame.boundingBox()).height >= 80);
    assert.equal(
      await visual
        .locator("details.visual-evidence-toggle")
        .evaluate((node) => node.open),
      false,
    );
    assert.equal(
      await frame.contentFrame().locator("iframe").getAttribute("sandbox"),
      "allow-scripts",
    );
    const canvas = await guest.locator("canvas").elementHandle();
    const guestFrame = await canvas.ownerFrame();
    const checkChart = async (minimumWidth) => {
      await guestFrame.waitForFunction(
        ({ canvas, minimumWidth }) => {
          const chart = window.Chart.getChart(canvas);
          return (
            canvas.isConnected &&
            chart?.width > minimumWidth &&
            chart.height > 160 &&
            chart.getDatasetMeta(0).data.length === 3 &&
            document.querySelector("#ig-root").getBoundingClientRect().bottom <=
              innerHeight
          );
        },
        { canvas, minimumWidth },
      );
    };
    await checkChart(0);
    const blockedDirective = await guest.locator("body").evaluate(
      () =>
        new Promise((resolve) => {
          document.addEventListener(
            "securitypolicyviolation",
            (event) => resolve(event.effectiveDirective),
            { once: true },
          );
          new Image().src = "https://example.invalid/visual.png";
        }),
    );
    assert.equal(blockedDirective, "img-src");
    const standardWidth = (await canvas.boundingBox()).width;
    await captureVisual(page, "01-visual-chart-standard.png");
    await panel
      .getByRole("button", { name: "展开宽浮窗", exact: true })
      .click();
    await checkChart(standardWidth + 160);
    await captureVisual(page, "02-visual-chart-wide.png");
    await panel
      .getByRole("button", { name: "恢复默认宽度", exact: true })
      .click();
    await guest.locator("#visual-chart").waitFor();
    assert.ok((await frame.boundingBox()).height > 160);
    assert.match(await guest.locator("#visual-data").innerText(), /联调学生甲/);
    await guest.locator("#open-submission").click();
    await page
      .getByRole("heading", { name: "论文成果 · 材料详情", exact: true })
      .waitFor();
    await captureVisual(page, "03-visual-action-to-modal.png");
    assert.equal(await page.evaluate(() => window.__visualOpenCount), 1);
    await page.getByLabel("关闭").click();
    await guest
      .locator("body")
      .evaluate(() => window.innograd.openSubmission("forged-id"));
    await guest
      .locator("body")
      .evaluate(() => window.innograd.openPortrait("forged-id"));
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.equal(
      await page
        .getByRole("heading", { name: "论文成果 · 材料详情", exact: true })
        .count(),
      0,
    );
    assert.equal(new URL(page.url()).hash, "");
    await guest
      .locator("body")
      .evaluate(() =>
        window.innograd.drilldown("run-overview", { page: 1 }, "查看已发表"),
      );
    await guest
      .locator("body")
      .evaluate(() => window.innograd.ask("请继续查看博士生"));
    await new Promise((resolve) => setTimeout(resolve, 250));
    assert.deepEqual(writes.at(-2).body.input, {
      mode: "drilldown_patch",
      parent_run_id: "run-overview",
      patch: { page: 1 },
      label: "查看已发表",
    });
    assert.deepEqual(writes.at(-1).body.input, {
      mode: "natural_language",
      message: "请继续查看博士生",
    });
    await guest.locator("#open-portrait").click();
    await page.waitForURL("**/#portraits");
    assert.deepEqual(errors, []);
  },
);

test("faulty visual HTML silently falls back to verified result cards", async (testContext) => {
  const { page, panel, openAgent, sendQuestion, errors } = await openWorkspace(
    testContext,
    "teacher",
    "/prototype/",
    {
      turnResponse: (reply) =>
        visualResponse(
          reply,
          `<div id="faulty-visual"></div><script>throw new Error("visual failed")</script>`,
        ),
    },
  );
  await page.setViewportSize({ width: 1440, height: 900 });
  await openAgent();
  await sendQuestion(firstQuestion);
  await panel.locator(".visual-fallback .agent-result").waitFor();
  await captureVisual(page, "04-visual-error-fallback.png");
  assert.equal(await panel.locator(".visual-frame").count(), 0);
  assert.equal(await panel.locator(".visual-loading-shimmer").count(), 0);
  assert.deepEqual(errors, ["visual failed"]);
});

test("empty visual HTML falls back when it has no visible content", async (testContext) => {
  const { panel, openAgent, sendQuestion, errors } = await openWorkspace(
    testContext,
    "teacher",
    "/prototype/",
    {
      turnResponse: (reply) =>
        visualResponse(reply, "<script>window.__INNOGRAD_DATA__</script>"),
    },
  );
  await openAgent();
  await sendQuestion(firstQuestion);
  await panel.locator(".visual-fallback .agent-result").waitFor();
  assert.equal(await panel.locator(".visual-frame").count(), 0);
  assert.deepEqual(errors, []);
});

test("visual payload is initial-only and clears on reload and access revocation", async (testContext) => {
  const { page, panel, openAgent, sendQuestion, faults, errors } =
    await openWorkspace(testContext, "teacher", "/prototype/", {
      turnResponse: visualResponse,
    });
  await openAgent();
  await sendQuestion(firstQuestion);
  await panel.locator(".visual-sandbox-ready").waitFor();
  await page.reload();
  await openAgent();
  await resultCard(panel, firstRun).waitFor();
  assert.equal(await panel.locator(".visual-sandbox").count(), 0);
  assert.equal(await panel.locator(".agent-result").count(), 1);
  faults.revoked = true;
  await panel.getByRole("button", { name: "刷新对话", exact: true }).click();
  await panel
    .getByText("查询范围已变更，本轮内容不可查看。", { exact: true })
    .waitFor();
  assert.equal(await panel.locator(".visual-sandbox").count(), 0);
  assert.deepEqual(errors, []);
});

test("result envelopes prefer explicit results and deduplicate by run ID", async (testContext) => {
  for (const [mode, expectedIds] of [
    ["fallback", [secondRun]],
    ["empty", []],
    ["duplicate", [firstRun, secondRun]],
  ]) {
    const { panel, openAgent, sendQuestion, errors } = await openWorkspace(
      testContext,
      "teacher",
      "/prototype/",
      { resultMode: { 1: mode } },
    );
    await openAgent();
    await sendQuestion("查询论文");
    await userBubbles(panel)
      .filter({ hasText: /^查询论文$/ })
      .waitFor();
    await panel.locator(".loading-indicator").waitFor({ state: "hidden" });
    assert.deepEqual(
      await panel
        .locator(".agent-result")
        .evaluateAll((cards) => cards.map((card) => card.id)),
      expectedIds.map((id) => `agent-run-${id}`),
    );
    assert.deepEqual(errors, []);
  }
});

test("card and turn clarifications survive reload and disappear after revocation", async (testContext) => {
  const turnPrompt = {
    message: "有两位同名学生，请明确选择。",
    suggestions: ["请补充年级或专业。"],
    student_candidates: [
      {
        student_id: "stu-1",
        student_name: "示例学生",
        year: "2024",
        degree: "master",
        major: "软件工程",
      },
      {
        student_id: "stu-2",
        student_name: "示例学生",
        year: "2025",
        degree: "doctoral",
        major: "计算机科学",
      },
    ],
  };
  const cardPrompt = { message: "论文统计需要补充发表状态。" };
  const { page, panel, openAgent, sendQuestion, reads, faults, errors } =
    await openWorkspace(testContext, "teacher", "/", {
      resultMode: { 1: "duplicate" },
      turnResponse: (reply) => {
        const [overview, doctor] = reply.results;
        const result = { ...doctor, clarification: cardPrompt };
        return {
          ...reply,
          turn: { ...reply.turn, clarification: turnPrompt },
          results: [{ ...overview, clarification: turnPrompt }, result],
          result,
        };
      },
    });
  const choices = [
    panel.getByRole("button", { name: turnPrompt.suggestions[0], exact: true }),
    panel.getByRole("button", { name: /示例学生.*2024.*软件工程/ }),
    panel.getByRole("button", { name: /示例学生.*2025.*计算机科学/ }),
  ];
  const turnMessage = panel.getByText(turnPrompt.message, { exact: true });
  const cardMessage = panel.getByText(cardPrompt.message, { exact: true });
  const assertPrompts = async () => {
    await resultCard(panel, firstRun).waitFor();
    await resultCard(panel, secondRun)
      .getByText(cardPrompt.message, { exact: true })
      .waitFor();
    for (const prompt of [turnMessage, cardMessage, ...choices]) {
      await prompt.waitFor();
      assert.equal(await prompt.count(), 1);
    }
  };

  await openAgent();
  await sendQuestion("先统计已发表论文，再查示例学生");
  await assertPrompts();
  await page.reload();
  await openAgent();
  await assertPrompts();

  faults.revoked = true;
  await page.reload();
  await openAgent();
  await panel
    .getByText("查询范围已变更，本轮内容不可查看。", { exact: true })
    .waitFor();
  for (const prompt of [turnMessage, cardMessage, ...choices]) {
    assert.equal(await prompt.count(), 0);
  }
  assert.equal(await panel.locator(".agent-result").count(), 0);
  assert.equal(await userBubbles(panel).count(), 0);
  assert.equal(await panel.getByRole("link").count(), 0);
  assert.equal(
    await panel.getByRole("button", { name: "查看本轮结果" }).count(),
    0,
  );
  assert.deepEqual(
    reads.filter((endpoint) => endpoint.includes("/runs/")),
    [],
  );
  assert.deepEqual(errors, []);
});

test("a loose legacy clarification shows one prompt with no cards or links across reload", async (testContext) => {
  const prompt = { message: "请补充要查询的年份。" };
  const { page, panel, openAgent, sendQuestion, errors } = await openWorkspace(
    testContext,
    "teacher",
    "/",
    {
      turnResponse: (reply) => ({
        ...reply,
        turn: {
          ...reply.turn,
          resolved_query: null,
          run_id: null,
          run_ids: [],
          status: "clarification_needed",
        },
        result: {
          status: "clarification_needed",
          query_run_id: null,
          clarification: prompt,
        },
        results: [],
        analysis: null,
      }),
    },
  );
  const message = panel.getByText(prompt.message, { exact: true });
  const assertPromptOnly = async () => {
    await message.waitFor();
    assert.equal(await message.count(), 1);
    assert.equal(await panel.locator(".agent-result").count(), 0);
    assert.equal(await panel.getByRole("link").count(), 0);
    assert.equal(
      await panel.getByRole("button", { name: "查看本轮结果" }).count(),
      0,
    );
  };

  await openAgent();
  await sendQuestion("查询论文");
  await assertPromptOnly();
  await page.reload();
  await openAgent();
  await assertPromptOnly();
  assert.deepEqual(errors, []);
});

test("follow-up, drilldown, and date removal advance one conversation with readable prompts", async (testContext) => {
  const { page, panel, openAgent, sendQuestion, writes, errors } =
    await openWorkspace(testContext, "teacher");
  await openAgent();
  await sendQuestion(firstQuestion);
  await resultCard(panel, firstRun).waitFor();
  await sendQuestion(secondQuestion);
  const doctor = resultCard(panel, secondRun);
  await doctor.waitFor();
  assertTurnRequest(writes[2], 1, {
    mode: "natural_language",
    message: secondQuestion,
  });
  await panel
    .getByText("分析原文中的数值未能核实，请查看查询结果。", { exact: true })
    .waitFor();
  await assertTurnCount(panel, 2);
  assert.equal(
    await doctor.getByText("已投稿论文记录数", { exact: true }).count(),
    0,
  );
  await doctor.getByRole("button", { name: /已发表\s*2\s*条.*1\s*人/ }).click();
  const published = resultCard(panel, thirdRun);
  await published.waitFor();
  assert.equal(
    await userBubbles(panel)
      .last()
      .evaluate((bubble) => {
        const message = bubble.getBoundingClientRect();
        const viewport = bubble
          .closest(".teacher-content")
          .getBoundingClientRect();
        return message.top < viewport.bottom && message.bottom > viewport.top;
      }),
    true,
    "the third prompt is visible in the chat before any test scrolling",
  );
  assertTurnRequest(writes[3], 2, {
    mode: "drilldown_patch",
    parent_run_id: secondRun,
    patch: publishedPatch,
    label: "已发表 2条",
  });
  await assertTurnCount(panel, 3);
  assert.equal(await published.locator(".kpi").count(), 2);
  assert.match(await userBubbles(panel).last().innerText(), /已发表/);
  const duplicateRows = published
    .locator(".paper-item")
    .filter({ hasText: "合成甲当年发表" });
  assert.equal(await duplicateRows.count(), 2);
  await published.getByText(/同标题.*合成甲当年发表.*2\s*份/).waitFor();
  for (const [index, id, version, date] of [
    [0, "sub-1", "V1", "2026年10月20日"],
    [1, "sub-2", "V2", "2026年3月14日"],
  ]) {
    const row = duplicateRows.nth(index);
    const publicationDate = row.locator(".paper-date");
    await row.getByText("已发表", { exact: true }).waitFor();
    await publicationDate.getByText("发表日期", { exact: true }).waitFor();
    await publicationDate.getByText(date, { exact: true }).waitFor();
    await row.getByText("材料字段", { exact: true }).click();
    await row.getByText(id, { exact: true }).waitFor();
    await row.getByText(new RegExp(`提交版本\\s*${version}\\b`)).waitFor();
  }
  await published.getByText("投稿日期", { exact: true }).first().waitFor();
  assert.doesNotMatch(
    await published.innerText(),
    /publication_status|submission_date|T12:00:00\+00:00/,
  );

  const dateChip = published
    .locator(".filter-chips")
    .getByRole("button", { name: /2026/ });
  await dateChip.click();
  const cleared = resultCard(panel, clearedRun);
  await cleared
    .locator(".paper-item")
    .filter({ hasText: "往年正式归档论文" })
    .waitFor();
  assertTurnRequest(writes[4], 3, {
    mode: "drilldown_patch",
    parent_run_id: thirdRun,
    patch: { clear_time_range: true },
    label: "移除时间范围：2026年",
  });
  const updatedPrompt = await userBubbles(panel).last().innerText();
  assert.match(
    updatedPrompt,
    /博士.*已发表|已发表.*博士|(?:移除|不限).*(?:2026|时间|日期|年份)/,
  );
  assert.doesNotMatch(updatedPrompt, /筛选查询|更新筛选条件|time_range/);
  assert.equal(
    await cleared
      .locator(".filter-chips")
      .getByRole("button", { name: /2026/ })
      .count(),
    0,
  );
  await cleared
    .locator(".filter-chips")
    .getByRole("button", { name: /博士/ })
    .waitFor();
  await cleared
    .locator(".filter-chips")
    .getByRole("button", { name: /已发表/ })
    .waitFor();
  await assertTurnCount(panel, 4);
  assert.equal(
    new Set(writes.map((write) => write.headers["idempotency-key"])).size,
    5,
  );

  await page.reload();
  await openAgent();
  await cleared.waitFor();
  assert.equal(await conversationPicker(panel).inputValue(), "c1");
  assert.equal(await userBubbles(panel).count(), 4);
  assert.match(
    await userBubbles(panel).last().innerText(),
    /博士.*已发表|已发表.*博士/,
  );
  await panel.getByRole("button", { name: "刷新对话", exact: true }).click();
  await cleared
    .locator(".paper-item")
    .filter({ hasText: "往年正式归档论文" })
    .waitFor();
  assert.equal(await conversationPicker(panel).inputValue(), "c1");
  await assertTurnCount(panel, 4);
  assert.equal(writes.length, 5);
  assert.deepEqual(errors, []);
});

test("removing the doctoral filter sends a QueryPatch to its parent run", async (testContext) => {
  const { panel, openAgent, sendQuestion, writes } = await openWorkspace(
    testContext,
    "teacher",
  );
  await openAgent();
  await sendQuestion(firstQuestion);
  await resultCard(panel, firstRun).waitFor();
  await sendQuestion(secondQuestion);
  const doctor = resultCard(panel, secondRun);
  await doctor
    .locator(".filter-chips")
    .getByRole("button", { name: "博士", exact: true })
    .click();
  await panel.locator(".teacher-turn").last().locator(".kpi").first().waitFor();
  assertTurnRequest(writes.at(-1), 2, {
    mode: "drilldown_patch",
    parent_run_id: secondRun,
    patch: { remove_filter_fields: ["degree"] },
    label: "移除筛选：博士",
  });
  await assertTurnCount(panel, 3);
  assert.equal(await userBubbles(panel).last().innerText(), "移除筛选：博士");
});

test("material and portrait actions stay inside the app", async (testContext) => {
  const { page, panel, openAgent, sendQuestion, errors } = await openWorkspace(
    testContext,
    "teacher",
  );
  await openAgent();
  await sendQuestion(firstQuestion);
  const overview = resultCard(panel, firstRun);
  await overview.getByText("材料详情", { exact: true }).first().click();
  await page
    .getByRole("heading", { name: "论文成果 · 材料详情", exact: true })
    .waitFor();
  await page.getByLabel("关闭").click();
  await overview
    .getByRole("button", { name: "成长画像", exact: true })
    .first()
    .click();
  await page.waitForURL(/#portraits$/);
  await page.getByLabel("选择画像学生").waitFor();
  assert.equal(new URL(page.url()).pathname, "/prototype/");
  assert.equal(new URL(page.url()).hash, "#portraits");
  assert.equal(page.url().includes("/api/v1/students/"), false);
  assert.deepEqual(errors, []);
});

test("a canonical portrait renders inline with paper records and verified facts", async (testContext) => {
  const { page, panel, openAgent, sendQuestion, reads, writes, errors } =
    await openWorkspace(testContext, "teacher");
  await openAgent();
  await sendQuestion("查看学生画像");
  const portrait = resultCard(panel, portraitRun);
  await portrait
    .getByRole("heading", { name: /联调学生甲.*成长画像/ })
    .waitFor();
  for (const fact of [
    "智能教育",
    "指导教师甲",
    "待评价",
    "合成甲当年发表",
    "画像只汇总可核实的归档材料。",
  ]) {
    await portrait.getByText(fact, { exact: false }).first().waitFor();
  }
  assert.match(await portrait.innerText(), /论文[^\d]*2|2[^\d]*论文/);
  assert.match(await portrait.innerText(), /年度[^\d]*1|1[^\d]*年度/);
  assert.equal(new URL(page.url()).hash, "");
  assert.deepEqual(reads, ["/teacher-agent/conversations"]);
  assertTurnRequest(writes[1], 0, {
    mode: "natural_language",
    message: "查看学生画像",
  });
  assert.deepEqual(errors, []);
});

test(
  "historical replay authorizes the turn before loading its run",
  { timeout: 15000 },
  async (testContext) => {
    const { page, panel, openAgent, sendQuestion, reads, hold, errors } =
      await openWorkspace(testContext, "teacher");
    await openAgent();
    await sendQuestion(firstQuestion);
    await resultCard(panel, firstRun).waitFor();
    await sendQuestion(secondQuestion);
    await resultCard(panel, secondRun).waitFor();
    await page.reload();
    await openAgent();
    await resultCard(panel, secondRun).waitFor();
    const replay = panel.getByRole("button", {
      name: "查看本轮结果",
      exact: true,
    });
    const detail = hold("holdDetail");
    const run = hold("holdRun");
    const previousReads = reads.length;
    await replay.click();
    await detail.entered;
    await panel
      .getByRole("status")
      .filter({ hasText: /正在读取本轮结果/ })
      .waitFor();
    assert.deepEqual(reads.slice(previousReads), [conversationEndpoint]);
    assert.equal(await panel.getByLabel("你的问题").isDisabled(), true);
    if (await replay.count()) assert.equal(await replay.isDisabled(), true);
    assert.equal(
      await panel.locator(".agent-result, .agent-analysis, a").count(),
      0,
    );
    assert.equal(await userBubbles(panel).count(), 0);
    detail.release();
    await run.entered;
    assert.deepEqual(reads.slice(previousReads), [
      conversationEndpoint,
      runEndpoint(firstRun),
    ]);
    assert.equal(await resultCard(panel, firstRun).count(), 0);
    run.release();
    await resultCard(panel, firstRun).waitFor();
    assert.equal(await resultCard(panel, secondRun).count(), 1);
    assert.equal(await replay.count(), 0);
    assert.deepEqual(errors, []);
  },
);

test("replay suppresses revoked prompts and skips unauthorized run requests", async (testContext) => {
  const { page, panel, openAgent, sendQuestion, reads, faults, errors } =
    await openWorkspace(testContext, "teacher");
  await openAgent();
  await sendQuestion(namedQuestion);
  await resultCard(panel, firstRun).waitFor();
  assert.equal(await userBubbles(panel).first().innerText(), namedQuestion);
  await sendQuestion(secondQuestion);
  await resultCard(panel, secondRun).waitFor();
  await page.reload();
  await openAgent();
  const replay = panel.getByRole("button", {
    name: "查看本轮结果",
    exact: true,
  });
  await replay.waitFor();
  assert.equal(
    await userBubbles(panel).first().innerText(),
    savedNamedQuestion,
  );
  faults.revokedTurn = "turn-1";
  const previousReads = reads.length;
  await replay.click();
  await panel
    .getByText("查询范围已变更，本轮内容不可查看。", { exact: true })
    .first()
    .waitFor();
  assert.deepEqual(reads.slice(previousReads), [conversationEndpoint]);
  assert.deepEqual(await userBubbles(panel).allInnerTexts(), [secondQuestion]);
  assert.equal(await resultCard(panel, firstRun).count(), 0);
  assert.equal(await resultCard(panel, secondRun).count(), 1);
  assert.equal(await replay.count(), 0);
  assert.deepEqual(errors, []);
});

test("replay hides a turn when its run access changes after the detail check", async (testContext) => {
  const { page, panel, openAgent, sendQuestion, reads, faults, errors } =
    await openWorkspace(testContext, "teacher");
  await openAgent();
  await sendQuestion(firstQuestion);
  await resultCard(panel, firstRun).waitFor();
  await sendQuestion(secondQuestion);
  await resultCard(panel, secondRun).waitFor();
  await page.reload();
  await openAgent();
  const replay = panel.getByRole("button", {
    name: "查看本轮结果",
    exact: true,
  });
  await replay.waitFor();
  faults.runStatus = 404;
  const previousReads = reads.length;
  await replay.click();
  await panel
    .getByText("查询范围已变更，本轮内容不可查看。", { exact: true })
    .waitFor();
  assert.deepEqual(reads.slice(previousReads), [
    conversationEndpoint,
    runEndpoint(firstRun),
  ]);
  assert.deepEqual(await userBubbles(panel).allInnerTexts(), [secondQuestion]);
  assert.equal(await resultCard(panel, firstRun).count(), 0);
  assert.equal(await resultCard(panel, secondRun).count(), 1);
  assert.equal(await replay.count(), 0);
  assert.deepEqual(errors, []);
});

test(
  "reopening checks access before showing history and refresh renders recomputed aggregates",
  { timeout: 15000 },
  async (testContext) => {
    const { panel, openAgent, sendQuestion, faults, hold, errors } =
      await openWorkspace(testContext, "teacher");
    await openAgent();
    await sendQuestion(firstQuestion);
    const overview = resultCard(panel, firstRun);
    await overview.waitFor();
    await panel.getByRole("button", { name: "收起对话", exact: true }).click();
    const detail = hold("holdDetail");
    faults.revoked = true;
    await openAgent();
    await detail.entered;
    await panel
      .getByRole("status")
      .filter({ hasText: /正在读取最近对话/ })
      .waitFor();
    assert.equal(await userBubbles(panel).count(), 0);
    assert.equal(
      await panel.locator(".agent-result, .agent-analysis, a").count(),
      0,
    );
    assert.equal(await panel.getByLabel("你的问题").isDisabled(), true);
    detail.release();
    await panel
      .getByText("查询范围已变更，本轮内容不可查看。", { exact: true })
      .waitFor();
    faults.revoked = false;
    faults.recompute = true;
    const refresh = panel.getByRole("button", {
      name: "刷新对话",
      exact: true,
    });
    await refresh.click();
    await overview.waitFor();
    assert.equal(await userBubbles(panel).innerText(), firstQuestion);
    assert.equal(
      await overview.locator(".paper-item, .evidence-details").count(),
      0,
    );
    await overview
      .getByText(/重新计算|重新核算|0\s*条|暂无/)
      .first()
      .waitFor();

    faults.detailStatus = 404;
    await refresh.click();
    await panel
      .getByRole("status")
      .filter({ hasText: "对话不可访问" })
      .waitFor();
    assert.equal(await userBubbles(panel).count(), 0);
    assert.equal(
      await panel.locator(".agent-result, .agent-analysis, a").count(),
      0,
    );
    assert.equal(await panel.getByLabel("你的问题").isDisabled(), true);
    assert.deepEqual(errors, []);
  },
);

test(
  "pending prompt appears immediately and a lost receipt retries the same write once",
  { timeout: 15000 },
  async (testContext) => {
    const {
      panel,
      openAgent,
      sendQuestion,
      writes,
      turns,
      faults,
      hold,
      errors,
    } = await openWorkspace(testContext, "teacher");
    await openAgent();
    await sendQuestion(firstQuestion);
    await resultCard(panel, firstRun).waitFor();
    const pending = hold("holdTurn");
    faults.loseNextReceipt = true;
    await sendQuestion(secondQuestion);
    await pending.entered;
    const loading = panel
      .locator(".loading-indicator")
      .filter({ hasText: "正在查询论文资料…" });
    await loading.waitFor();
    assert.equal(await userBubbles(panel).last().innerText(), secondQuestion);
    assert.equal(
      await panel
        .getByRole("button", { name: "发送追问", exact: true })
        .isDisabled(),
      true,
    );
    assert.equal(await panel.getByLabel("你的问题").isDisabled(), true);
    await assertTurnCount(panel, 1);
    assert.equal(await resultCard(panel, secondRun).count(), 0);
    pending.release();
    await panel
      .getByText(
        "无法连接服务器。请检查服务状态；未确认成功的操作请先刷新核对。",
        { exact: true },
      )
      .waitFor();
    assert.equal(
      await panel.getByLabel("你的问题").inputValue(),
      secondQuestion,
    );
    assert.equal(turns.length, 2);
    assert.equal(
      await userBubbles(panel).filter({ hasText: secondQuestion }).count(),
      1,
    );
    await panel.getByRole("button", { name: "发送追问", exact: true }).click();
    await panel
      .getByRole("status")
      .filter({ hasText: "无法连接服务器" })
      .waitFor({ state: "hidden" });
    await panel.locator(".loading-indicator").waitFor({ state: "hidden" });
    const turnWrites = writes.filter((item) => item.endpoint === turnEndpoint);
    assert.equal(turnWrites.length, 3);
    assert.deepEqual(turnWrites[1].body, turnWrites[2].body);
    assert.equal(
      turnWrites[1].headers["idempotency-key"],
      turnWrites[2].headers["idempotency-key"],
    );
    assert.equal(turns.length, 2);
    assert.equal(await userBubbles(panel).count(), 2);
    assert.equal(await resultCard(panel, secondRun).count(), 1);
    assert.equal(await panel.getByLabel("你的问题").inputValue(), "");
    await assertTurnCount(panel, 2);
    assert.deepEqual(errors, []);
  },
);

test("composer respects IME and Shift+Enter, then rotates the write key after a conflict", async (testContext) => {
  const { panel, openAgent, writes, faults } = await openWorkspace(
    testContext,
    "teacher",
  );
  await openAgent();
  const input = panel.getByLabel("你的问题");
  await input.fill("只看博士");
  await input.dispatchEvent("keydown", { key: "Enter", isComposing: true });
  await input.press("Shift+Enter");
  await input.press("End");
  await input.press("A");
  assert.match(await input.inputValue(), /\n/);
  assert.equal(writes.length, 0);
  faults.rejectNextTurn = true;
  await input.press("Enter");
  await panel.getByText("对话版本已更新", { exact: true }).waitFor();
  const original = writes.at(-1);
  assert.equal(await input.inputValue(), original.body.input.message);
  await input.press("Enter");
  await resultCard(panel, firstRun).waitFor();
  assert.notEqual(
    writes.at(-1).headers["idempotency-key"],
    original.headers["idempotency-key"],
  );
  assert.deepEqual(writes.at(-1).body, original.body);
});

test("student and operator keep preset guides without teacher-agent calls", async (testContext) => {
  for (const role of ["student", "operator"]) {
    const { page, panel, openAgent, sendQuestion, reads, writes, errors } =
      await openWorkspace(testContext, role, "/prototype/");
    await openAgent();
    assert.equal(
      await page
        .getByRole("button", { name: "Agent 论文问答", exact: true })
        .count(),
      0,
    );
    await panel
      .getByText("使用指引模式 · AI 对话服务暂未接入", { exact: true })
      .waitFor();
    assert.equal(await panel.getByLabel("最近对话").count(), 0);
    assert.equal(await panel.getByLabel("你的问题").count(), 0);
    await sendQuestion("如何提交论文材料？");
    await panel.getByText(/新建论文工作稿/).waitFor();
    assert.deepEqual(reads, []);
    assert.deepEqual(writes, []);
    assert.deepEqual(errors, []);
  }
});

test("manager starts a separate paper conversation in the root workspace", async (testContext) => {
  const { page, panel, openAgent, sendQuestion, reads, writes, errors } =
    await openWorkspace(testContext, "manager", "/");
  await openAgent();
  await panel
    .getByRole("heading", { name: "你好，今天想查哪类论文成果？", exact: true })
    .waitFor();
  assert.equal(await conversationPicker(panel).inputValue(), "");
  assert.deepEqual(reads, ["/teacher-agent/conversations"]);
  await sendQuestion("查看论文成果统计");
  await resultCard(panel, firstRun).waitFor();
  assertTurnRequest(writes[1], 0, {
    mode: "natural_language",
    message: "查看论文成果统计",
  });
  assert.equal(new URL(page.url()).pathname, "/");
  assert.equal(
    await page
      .getByRole("button", { name: "Agent 论文问答", exact: true })
      .count(),
    0,
  );
  assert.deepEqual(errors, []);
});

test("floating popup fits a 390px viewport without horizontal overflow", async (testContext) => {
  const { page, panel, openAgent, sendQuestion, errors } = await openWorkspace(
    testContext,
    "teacher",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await openAgent();
  await sendQuestion(firstQuestion);
  await resultCard(panel, firstRun).waitFor();
  const bounds = await panel.evaluate((node) => {
    const { left, right, top, bottom } = node.getBoundingClientRect();
    const content = node.querySelector(".teacher-content");
    return {
      left,
      right,
      top,
      bottom,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      panelWidth: node.clientWidth,
      panelScrollWidth: node.scrollWidth,
      contentWidth: content.clientWidth,
      contentScrollWidth: content.scrollWidth,
    };
  });
  assert.ok(bounds.left >= 0 && bounds.right <= bounds.viewportWidth);
  assert.ok(bounds.top >= 0 && bounds.bottom <= bounds.viewportHeight);
  assert.ok(bounds.panelScrollWidth <= bounds.panelWidth);
  assert.ok(bounds.contentScrollWidth <= bounds.contentWidth);
  assert.equal(await panel.locator(".width-toggle").isVisible(), false);
  assert.equal(await panel.getByLabel("你的问题").isVisible(), true);
  assert.deepEqual(errors, []);
});
