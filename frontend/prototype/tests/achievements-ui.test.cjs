const { test } = require("node:test");
const assert = require("node:assert/strict");
const {
  achievementStatusSummary,
  achievementTitle,
  extractSoftwareCopyrightForm,
  fileRoleLabelsForKind,
  renderAchievementDetail,
  renderAchievementSummaryBar,
  renderResearchProjectFields,
  renderSoftwareCopyrightFields,
  renderVersionStructuredFields,
  safeHttpUrl,
} = require("../achievements-ui.js");
const { renderGrowth } = require("../growth-ui.js");

const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[c],
  );

test("safeHttpUrl permits http/https and rejects dangerous schemes or credentials", () => {
  assert.equal(
    safeHttpUrl("https://github.com/org/repo"),
    "https://github.com/org/repo",
  );
  assert.equal(
    safeHttpUrl("http://127.0.0.1:8000/demo"),
    "http://127.0.0.1:8000/demo",
  );
  assert.equal(safeHttpUrl("javascript:alert(1)"), "");
  assert.equal(safeHttpUrl("data:text/html,<script>alert(1)</script>"), "");
  assert.equal(safeHttpUrl("https://user:pass@example.com/a"), "");
  assert.equal(safeHttpUrl("not a url"), "");
});

test("software copyright form conditionally requires registration fields only when registered", () => {
  const unregHtml = renderSoftwareCopyrightFields(
    {
      software_name: "测试软件<script>",
      version: "V1.0",
      registration_status: "unregistered",
    },
    esc,
  );
  assert.ok(unregHtml.includes("&lt;script&gt;"));
  assert.ok(!unregHtml.includes("<script>"));
  assert.ok(unregHtml.includes('class="sw-reg-only" style="display:none"'));
  assert.ok(unregHtml.includes('name="registration_number" value="" disabled'));

  const regHtml = renderSoftwareCopyrightFields(
    {
      software_name: "已登记系统",
      version: "V2.0",
      registration_status: "registered",
      registration_number: "2026SR1234567",
      registration_date: "2026-10-15",
    },
    esc,
  );
  assert.ok(
    regHtml.includes(
      'name="registration_number" value="2026SR1234567" required',
    ),
  );
  assert.ok(
    regHtml.includes(
      'name="registration_date" type="date" value="2026-10-15" required',
    ),
  );
});

test("extractSoftwareCopyrightForm clears registration details unless registered", () => {
  const makeFormData = (obj) => ({ get: (k) => obj[k] ?? null });
  const unreg = extractSoftwareCopyrightForm(
    makeFormData({
      software_name: "工具A",
      version: "V1.0",
      copyright_holders: "华东师范大学，张三\n李四",
      development_work: "核心编码",
      registration_status: "applying",
      registration_number: "2026SR9999999",
      registration_date: "2026-11-01",
    }),
  );
  assert.deepEqual(unreg.copyright_holders, ["华东师范大学", "张三", "李四"]);
  assert.equal(unreg.registration_number, "");
  assert.equal(unreg.registration_date, "");

  const reg = extractSoftwareCopyrightForm(
    makeFormData({
      software_name: "工具A",
      version: "V1.0",
      copyright_holders: "华东师范大学",
      development_work: "核心编码",
      registration_status: "registered",
      registration_number: "2026SR9999999",
      registration_date: "2026-11-01",
    }),
  );
  assert.equal(reg.registration_number, "2026SR9999999");
  assert.equal(reg.registration_date, "2026-11-01");
});

test("research project detail escapes XSS and drops unsafe external artifact links", () => {
  const detail = renderAchievementDetail(
    "research_project",
    {
      project_name: "项目<img src=x onerror=1>",
      student_role: "lead",
      completion_date: "2026-11-10",
      stage_deliverables: "完成原型与实验",
      linked_artifacts: [
        {
          artifact_type: "code",
          name: "恶意链接",
          url: "javascript:alert(1)",
        },
        {
          artifact_type: "prototype",
          name: "演示系统",
          url: "https://example.org/demo",
          file_id: "f1",
        },
      ],
    },
    [{ id: "f1", name: "demo.pdf" }],
    esc,
  );
  assert.ok(!detail.includes("<img src=x"));
  assert.ok(!detail.includes("javascript:alert"));
  assert.ok(detail.includes('href="https://example.org/demo"'));
  assert.ok(detail.includes('rel="noopener noreferrer"'));
  assert.ok(detail.includes("demo.pdf"));

  const fieldsHtml = renderResearchProjectFields(
    { project_name: "测试课题", student_role: "core_member" },
    [],
    esc,
  );
  assert.ok(fieldsHtml.includes("按需关联材料"));
  assert.ok(fieldsHtml.includes("add-artifact-btn"));
});

test("kind-specific role maps, titles, summaries, and growth bars handle new kinds", () => {
  assert.ok(
    "copyright_certificate" in fileRoleLabelsForKind("software_copyright"),
  );
  assert.ok(!("paper_fulltext" in fileRoleLabelsForKind("software_copyright")));
  assert.ok("experiment_report" in fileRoleLabelsForKind("research_project"));
  assert.equal(
    achievementTitle("software_copyright", { software_name: "软著X" }),
    "软著X",
  );
  assert.equal(
    achievementStatusSummary("software_copyright", {
      registration_status: "registered",
      registration_number: "2026SR1111111",
    }),
    "已登记 · 2026SR1111111",
  );
  const verHtml = renderVersionStructuredFields(
    "research_project",
    {
      project_name: "课题A",
      student_role: "other",
      role_description: "算法设计",
      completion_date: "2026-11-01",
      stage_deliverables: "完成基线",
      linked_artifacts: [{ artifact_type: "dataset", name: "数据集1" }],
    },
    esc,
    { fieldLabels: {}, formatValue: (v) => String(v) },
  );
  assert.ok(verHtml.includes("其他（算法设计）"));
  assert.ok(verHtml.includes("数据集：数据集1"));

  const growthHtml = renderGrowth({
    esc,
    icon: () => "",
    btn: () => "",
    heading: (t) => `<h1>${t}</h1>`,
    state: {
      students: [
        {
          id: "s1",
          name: "学生甲",
          year: "2026",
          major: "人工智能",
          number: "001",
          teacher: "导师",
        },
      ],
    },
    role: "student",
    me: { id: "s1" },
    selectedStudent: "s1",
    period: "",
    tab: "personal",
    data: {
      periods: ["2026"],
      warnings: [],
      entries: [],
      counts: {
        materials: 2,
        archives: 2,
        papers: 0,
        annual: 0,
        software_copyrights: 1,
        research_projects: 1,
        pending: 0,
        returned: 0,
      },
      coverage: 2,
      dimensions: [
        "goals",
        "training",
        "contribution",
        "education",
        "exchange",
        "practice",
      ].map((key) => ({
        key,
        label: key,
        count: 0,
        evidence: [],
        score: null,
      })),
      sources: [
        {
          submission_id: "r1",
          title: "系统V1",
          kind: "software_copyright",
          number: 1,
          archived_at: "2026-11-10",
          form: { development_work: "负责后端开发" },
          files: [],
        },
      ],
      trend: [
        {
          month: "2026-11",
          paper: 0,
          annual: 0,
          software_copyright: 1,
          research_project: 1,
        },
      ],
      notice: "材料观察",
    },
  });
  assert.ok(growthHtml.includes("1 份软著"));
  assert.ok(growthHtml.includes("1 份科研项目"));
  assert.ok(growthHtml.includes("2026-11归档2份"));

  const kpiHtml = renderAchievementSummaryBar([
    { status: "archived" },
    { status: "pending" },
    { status: "draft" },
    { status: "returned" },
  ]);
  assert.ok(kpiHtml.includes("ach-summary-bar"));
  assert.ok(kpiHtml.includes("<strong>4</strong>"));
  assert.ok(kpiHtml.includes("<strong>1</strong>"));
  assert.ok(kpiHtml.includes("<strong>2</strong>"));
});
