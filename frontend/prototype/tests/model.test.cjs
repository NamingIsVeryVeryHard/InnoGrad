const { before, test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const { webcrypto } = require("node:crypto");

let renderGrowth;
let renderWarnings;
let fieldLabels;
let formatValue;

before(async () => {
  ({ renderGrowth, renderWarnings } = await import("../growth-ui.js"));
  ({ fieldLabels, formatValue } = await import(
    "../../teacher-chat/field-labels.js"
  ));
});

const filename = require.resolve("../app.js");
const src = fs.readFileSync(filename, "utf8");
const model = new vm.Script(
  src
    .replace(/^import\s*\{[^}]+\}\s*from\s*["'][^"']+["'];/gm, "")
    .split(/^try\s*\{\s*me\s*=\s*await\s+api\(\s*["']\/me["']\s*\)/m)[0],
  { filename },
);
function setup(fetch = async () => ({ ok: true, json: async () => [] })) {
  const context = vm.createContext({
    renderGrowth,
    renderWarnings,
    fieldLabels,
    formatValue,
    AbortController,
    crypto: webcrypto,
    structuredClone,
    Date,
    Intl,
    URL,
    Blob,
    FormData,
    console,
    location: { hash: "" },
    window: { addEventListener: () => {} },
    document: {},
    setInterval: () => {},
    setTimeout: () => {},
    clearTimeout: () => {},
    fetch,
  });
  model.runInContext(context);
  return (code) => vm.runInContext(code, context);
}
const fixture = {
  id: "r1",
  student_id: "s1",
  reviewer_id: "t1",
  kind: "paper",
  task_id: null,
  status: "pending_review",
  lock_version: 2,
  current_version_id: "v1",
  draft: { form: { title: "private draft" }, file_ids: ["new"] },
  versions: [
    {
      id: "v1",
      number: 1,
      created_at: "2026-11-02T00:00:00Z",
      snapshot: {
        form: {
          title: "Submitted title",
          contribution: "Study",
          publication_status: "accepted",
        },
        file_ids: ["old"],
        references: [],
      },
    },
  ],
  files: [
    { id: "old", name: "proof.pdf", size: 100 },
    { id: "new", name: "unsubmitted.pdf", size: 100 },
  ],
  decisions: [],
  reviewer_changes: [],
  corrections: [],
  created_at: "2026-11-01T00:00:00Z",
};
test("server snapshot drives reviewer display; private drafts are not selected", () => {
  const run = setup();
  run(
    "me={id:'t1',name:'Teacher',role:'teacher'};role='teacher';people=[{id:'t1',name:'Teacher'}]",
  );
  const r = run(`normalize(${JSON.stringify(fixture)})`);
  assert.equal(r.title, "Submitted title");
  assert.deepEqual(
    Array.from(r.files, (f) => f.id),
    ["old"],
  );
  assert.equal(r.status, "pending");
});
test("student draft edits use owner draft and preserve effective archive metadata", () => {
  const run = setup();
  run("me={id:'s1'}");
  const f = structuredClone(fixture);
  f.status = "returned";
  f.effective_archive = {
    id: "a1",
    number: 1,
    snapshot: { form: { title: "Old recognition" } },
    created_at: "2026-11-01T00:00:00Z",
  };
  const r = run(`normalize(${JSON.stringify(f)})`);
  assert.equal(r.title, "private draft");
  assert.equal(r.effective.title, "Old recognition");
  assert.deepEqual(
    Array.from(r.files, (f) => f.id),
    ["new"],
  );
});
test("mutations send CSRF and idempotency headers to backend, no browser persistence", async () => {
  let captured;
  const run = setup(async (url, options) => {
    captured = { url, options };
    return { ok: true, json: async () => ({ id: "server-id" }) };
  });
  run("csrf='csrf-token'");
  const result = await run(
    "post('/submissions',{kind:'paper',reviewer_id:'t1'})",
  );
  assert.equal(result.id, "server-id");
  assert.equal(captured.url, "/api/v1/submissions");
  assert.equal(captured.options.headers["X-CSRF-Token"], "csrf-token");
  assert.ok(captured.options.headers["Idempotency-Key"]);
  assert.equal(captured.options.credentials, "same-origin");
  const growthSource = fs.readFileSync(
    require.resolve("../growth-ui.js"),
    "utf8",
  );
  for (const source of [src, growthSource]) {
    assert.ok(!source.includes("localStorage"));
    assert.ok(!source.includes("indexedDB"));
    assert.ok(!source.includes("function seed("));
  }
});
test("server conflict is surfaced rather than treated as saved", async () => {
  const run = setup(async () => ({
    ok: false,
    status: 409,
    json: async () => ({ detail: "版本已变化" }),
  }));
  await assert.rejects(
    () => run("patch('/submissions/r1/draft',{})"),
    /版本已变化/,
  );
});
test("a disposed Agent session cannot send another request", async () => {
  const run = setup(() => assert.fail("Aborted session made an API request"));
  await assert.rejects(
    () =>
      run(`{
        const controller = new AbortController();
        controller.abort();
        api("/teacher-agent/conversations", { signal: controller.signal });
      }`),
    { name: "AbortError" },
  );
});
test("all workspace renderers support empty real data and logged-in identities", () => {
  const run = setup();
  for (const role of ["manager", "teacher", "student", "operator"])
    for (const page of [
      "dashboard",
      "students",
      "tasks",
      "reviews",
      "papers",
      "competitions",
      "exchanges",
      "archives",
      "portraits",
      "alerts",
      "rules",
      "logs",
      "settings",
    ]) {
      assert.ok(
        run(
          `me={id:'s1',name:'Test',role:'${role}'};role='${role}';page='${page}';views[page]()`,
        ).includes("<"),
      );
    }
});
test("CSV quoted fields and Shanghai calendar dates are handled", () => {
  const run = setup();
  assert.equal(
    run(
      `parseCSV(${JSON.stringify('\uFEFF姓名,学号\r\n"林,同学",123\r\n')}).length`,
    ),
    2,
  );
  assert.equal(run(`parseCSV('"a""b",x')[0][0]`), 'a"b');
  assert.throws(() => run(`parseCSV('"broken')`));
  assert.equal(run("date('2026-11-01T18:00:00Z')"), "2026-11-02");
  assert.equal(run(`esc('<script>')`), "&lt;script&gt;");
});
test("growth page renders real evidence counts without fabricating scores or unsafe HTML", () => {
  const run = setup();
  const g = {
    periods: ["2026"],
    warnings: [],
    entries: [],
    counts: {
      materials: 1,
      archives: 1,
      papers: 0,
      annual: 1,
      pending: 0,
      returned: 0,
    },
    coverage: 1,
    dimensions: [
      "goals",
      "training",
      "contribution",
      "education",
      "exchange",
      "practice",
    ].map((key, i) => ({
      key,
      label: key,
      count: i === 0 ? 1 : 0,
      evidence: [],
      score: null,
    })),
    sources: [
      {
        submission_id: "r1",
        title: "<img src=x onerror=alert(1)>",
        kind: "annual",
        number: 1,
        archived_at: "2026-11-02",
        form: { summary: "Research" },
        files: [],
      },
    ],
    trend: [{ month: "2026-11", paper: 0, annual: 1 }],
    notice: "材料观察",
  };
  run(
    `me={id:'s1'};role='student';selectedStudent='s1';state.students=[{id:'s1',name:'Student',year:'2026',major:'研究',number:'001',teacher:'Institute'}];growthCache['s1|']=${JSON.stringify(g)}`,
  );
  const html = run("portraits()");
  assert.ok(html.includes("材料覆盖"));
  assert.ok(html.includes("1 / 6"));
  assert.ok(html.includes("&lt;img"));
  assert.ok(!html.includes("<img src=x"));
  assert.ok(html.includes("尚未关联依据"));
});
test("warning view separates cleared history from active support items", () => {
  const run = setup();
  run(
    "state.students=[{id:'s1',name:'Test'}];warningsData=[{id:'w1',student:'s1',title:'到期计划',text:'真实事项',kind:'goal_overdue',status:'cleared',severity:'medium',history:[],note:''}];role='teacher';filter='active'",
  );
  assert.ok(!run("alertsView()").includes("真实事项"));
  run("filter='closed'");
  assert.ok(run("alertsView()").includes("条件已消除"));
});
test("competition and exchange submissions normalize, filter, format versions, and render safely", () => {
  const run = setup();
  run("me={id:'t1',name:'Teacher',role:'teacher'};role='teacher';people=[{id:'t1',name:'Teacher'}]");
  const compSub = {
    id: "c1",
    student_id: "s1",
    reviewer_id: "t1",
    kind: "competition",
    task_id: null,
    status: "archived",
    lock_version: 2,
    current_version_id: "cv1",
    effective_archive_id: "ca1",
    effective_archive: {
      id: "ca1",
      number: 1,
      snapshot: { form: { competition_name: "全国数模<script>" } },
      created_at: "2026-11-10T00:00:00Z",
    },
    versions: [
      {
        id: "cv1",
        number: 1,
        created_at: "2026-11-10T00:00:00Z",
        snapshot: {
          form: {
            competition_name: "全国数模<script>",
            organizer: "学会",
            award_level: "一等奖",
            award_date: "2026-10-15",
            team_members: [
              { name: "张三", order: 1 },
              { name: "李四", order: 2 },
            ],
            my_role: "队长",
            publicity_url: "https://example.org/awards",
          },
          file_ids: [],
          references: [],
        },
      },
    ],
    files: [],
    decisions: [],
    reviewer_changes: [],
    corrections: [],
    created_at: "2026-11-10T00:00:00Z",
  };
  const exchSub = {
    id: "e1",
    student_id: "s1",
    reviewer_id: "t1",
    kind: "exchange",
    task_id: null,
    status: "pending_review",
    lock_version: 1,
    current_version_id: "ev1",
    versions: [
      {
        id: "ev1",
        number: 1,
        created_at: "2026-11-11T00:00:00Z",
        snapshot: {
          form: {
            activity_name: "智能教育论坛",
            activity_date: "2026-11-05",
            participation_mode: "practice_task",
            practice_task_description: "承担数据集清洗与评测",
          },
          file_ids: ["ef1"],
          references: [],
        },
      },
    ],
    files: [{ id: "ef1", name: "task.pdf", size: 1024, role: "practice_task_proof" }],
    decisions: [],
    reviewer_changes: [],
    corrections: [],
    created_at: "2026-11-11T00:00:00Z",
  };
  const compNorm = run(`normalize(${JSON.stringify(compSub)})`);
  const exchNorm = run(`normalize(${JSON.stringify(exchSub)})`);
  assert.equal(compNorm.title, "全国数模<script>");
  assert.equal(compNorm.awardLevel, "一等奖");
  assert.equal(exchNorm.participationMode, "practice_task");

  const compHtml = run(`versionFields('competition', ${JSON.stringify(compSub.versions[0].snapshot.form)})`);
  assert.ok(compHtml.includes("竞赛名称"));
  assert.ok(compHtml.includes("1. 张三、2. 李四"));
  assert.ok(!compHtml.includes("<script>"));

  const exchHtml = run(`versionFields('exchange', ${JSON.stringify(exchSub.versions[0].snapshot.form)})`);
  assert.ok(exchHtml.includes("承担具体实践任务"));
  assert.ok(exchHtml.includes("承担数据集清洗与评测"));

  run(`state.students=[{id:'s1',name:'Student',year:'2026',major:'研究',number:'001',teacher:'T'}];state.records=[normalize(${JSON.stringify(compSub)}), normalize(${JSON.stringify(exchSub)})]`);
  assert.ok(run("listing('competitions')").includes("竞赛与获奖"));
  assert.ok(run("listing('competitions')").includes("一等奖"));
  assert.ok(!run("listing('competitions')").includes("智能教育论坛"));
  assert.ok(run("listing('exchanges')").includes("学术交流"));
  assert.ok(run("listing('exchanges')").includes("承担具体实践任务"));
  assert.ok(!run("listing('exchanges')").includes("全国数模"));

  const growthData = {
    periods: ["2026"],
    warnings: [],
    entries: [],
    counts: {
      materials: 2,
      archives: 2,
      papers: 0,
      annual: 0,
      competitions: 1,
      exchanges: 1,
      pending: 0,
      returned: 0,
    },
    coverage: 2,
    dimensions: ["goals", "training", "contribution", "education", "exchange", "practice"].map(
      (key) => ({ key, label: key, count: 1, evidence: [], score: null }),
    ),
    sources: [
      {
        submission_id: "c1",
        title: "全国数模",
        kind: "competition",
        number: 1,
        archived_at: "2026-11-10T00:00:00Z",
        form: { award_level: "一等奖", my_role: "队长" },
        files: [],
      },
      {
        submission_id: "e1",
        title: "智能教育论坛",
        kind: "exchange",
        number: 1,
        archived_at: "2026-11-10T00:00:00Z",
        form: { practice_task_description: "承担数据集清洗与评测" },
        files: [],
      },
    ],
    trend: [{ month: "2026-11", paper: 0, annual: 0, competition: 1, exchange: 1 }],
    notice: "材料观察",
  };
  run(`selectedStudent='s1';growthCache['s1|']=${JSON.stringify(growthData)}`);
  const portraitHtml = run("portraits()");
  assert.ok(portraitHtml.includes("1 项竞赛获奖"));
  assert.ok(portraitHtml.includes("1 项学术交流"));
  assert.ok(portraitHtml.includes("2026-11归档2份"));
});
test("subFilter, summary strips, detail views, and duplicate detection work for competition & exchange", () => {
  const run = setup();
  run("me={id:'t1',name:'Teacher',role:'teacher'};role='teacher';people=[{id:'t1',name:'Teacher'}]");
  const compCertAndLink = {
    id: "c1",
    student_id: "s1",
    reviewer_id: "t1",
    kind: "competition",
    status: "archived",
    lock_version: 1,
    current_version_id: "cv1",
    effective_archive_id: "ca1",
    effective_archive: {
      id: "ca1",
      number: 1,
      snapshot: { form: { competition_name: "数模竞赛" } },
      created_at: "2026-11-10T00:00:00Z",
    },
    versions: [
      {
        id: "cv1",
        number: 1,
        created_at: "2026-11-10T00:00:00Z",
        snapshot: {
          form: {
            competition_name: "数模竞赛",
            organizer: "学会",
            award_level: "国家级一等奖",
            award_date: "2026-10-15",
            team_members: [
              { name: "张三", order: 1, is_self: true },
              { name: "李四", order: 2 },
            ],
            team_size: 2,
            my_role: "队长",
            proof_mode: "certificate_and_link",
            publicity_url: "https://example.org/award",
            competition_key: "dup-comp-key",
          },
          file_ids: ["cf1"],
          references: [],
        },
      },
    ],
    files: [{ id: "cf1", name: "cert.pdf", size: 100, role: "award_certificate" }],
    decisions: [],
    reviewer_changes: [],
    corrections: [],
    created_at: "2026-11-10T00:00:00Z",
  };
  const compLinkOnlyDup = {
    ...structuredClone(compCertAndLink),
    id: "c2",
    status: "pending_review",
    effective_archive_id: null,
    effective_archive: null,
    files: [],
    versions: [
      {
        id: "cv2",
        number: 1,
        created_at: "2026-11-12T00:00:00Z",
        snapshot: {
          form: {
            competition_name: "数模竞赛（重复）",
            organizer: "学会",
            award_level: "国家级一等奖",
            award_date: "2026-10-15",
            team_members: [{ name: "张三", order: 1 }],
            my_role: "队长",
            proof_mode: "link_only",
            publicity_url: "javascript:alert(1)",
            competition_key: "dup-comp-key",
          },
          file_ids: [],
          references: [],
        },
      },
    ],
  };
  const compOtherStudent = {
    ...structuredClone(compCertAndLink),
    id: "c3",
    student_id: "s2",
  };
  const exchTalk = {
    id: "e1",
    student_id: "s1",
    reviewer_id: "t1",
    kind: "exchange",
    status: "archived",
    lock_version: 1,
    current_version_id: "ev1",
    versions: [
      {
        id: "ev1",
        number: 1,
        created_at: "2026-11-05T00:00:00Z",
        snapshot: {
          form: {
            activity_name: "教育AI论坛",
            activity_date: "2026-11-01",
            end_date: "2026-11-03",
            participation_mode: "talk",
            presentation_title: "可追溯画像方法",
            reference_url: "https://example.org/talk",
            exchange_key: "k-talk",
          },
          file_ids: ["ef1"],
          references: [],
        },
      },
    ],
    files: [{ id: "ef1", name: "talk.pdf", size: 100, role: "presentation_proof" }],
    decisions: [],
    reviewer_changes: [],
    corrections: [],
    created_at: "2026-11-05T00:00:00Z",
  };
  const exchPractice = {
    ...structuredClone(exchTalk),
    id: "e2",
    versions: [
      {
        id: "ev2",
        number: 1,
        created_at: "2026-11-06T00:00:00Z",
        snapshot: {
          form: {
            activity_name: "智慧课堂试点",
            activity_date: "2026-11-04",
            participation_mode: "practice_task",
            practice_task_description: "负责数据清洗与模型验证",
            exchange_key: "k-practice",
          },
          file_ids: ["ef2"],
          references: [],
        },
      },
    ],
  };

  run(
    `state.students=[{id:'s1',name:'甲同学',number:'001'},{id:'s2',name:'乙同学',number:'002'}];` +
      `state.records=[${JSON.stringify(compCertAndLink)},${JSON.stringify(compLinkOnlyDup)},${JSON.stringify(compOtherStudent)},${JSON.stringify(exchTalk)},${JSON.stringify(exchPractice)}].map(normalize);`,
  );

  run("subFilter='link_only';filter='all'");
  const linkOnlyHtml = run("listing('competitions')");
  assert.ok(linkOnlyHtml.includes("竞赛总数"));
  assert.ok(linkOnlyHtml.includes("数模竞赛（重复）"));
  assert.ok(!linkOnlyHtml.includes("<td><div class=\"cell-title\" style=\"max-width:280px;overflow:hidden;text-overflow:ellipsis\">数模竞赛</div>"));

  run("subFilter='talk'");
  const talkHtml = run("listing('exchanges')");
  assert.ok(talkHtml.includes("教育AI论坛"));
  assert.ok(!talkHtml.includes("智慧课堂试点"));

  const compDetail = run("recordDetailBody(state.records[0])");
  assert.ok(compDetail.includes("member-chips"));
  assert.ok(compDetail.includes("团队赛 · 2 人"));
  assert.ok(compDetail.includes("证书+公示链接"));
  assert.ok(compDetail.includes('href="https://example.org/award"'));

  const unsafeDetail = run("recordDetailBody(state.records[1])");
  assert.ok(!unsafeDetail.includes('href="javascript:'));

  const talkDetail = run("recordDetailBody(state.records[3])");
  assert.ok(talkDetail.includes("画像归入：学术交流"));
  assert.ok(talkDetail.includes("报告题目"));
  assert.ok(talkDetail.includes("2026-11-01 至 2026-11-03"));

  const practiceDetail = run("recordDetailBody(state.records[4])");
  assert.ok(practiceDetail.includes("画像归入：实践落地"));
  assert.ok(practiceDetail.includes("负责数据清洗与模型验证"));

  const dupIds = run("findDuplicateRecords(state.records[0]).map((r) => r.id)");
  assert.deepEqual(Array.from(dupIds), ["c2"]);
});
