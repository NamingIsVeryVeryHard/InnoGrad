const assert = require("node:assert/strict");
const fs = require("node:fs");
const {execFileSync} = require("node:child_process");
const {chromium} = require("playwright");

const {accounts, fixture, studentLogin} = JSON.parse(fs.readFileSync(0, "utf8"));
const root = process.env.TEST_WORKSPACE_URL;
const output = process.env.EVIDENCE_DIR;
const invalidReceipt = process.env.TEST_INVALID_RECEIPT === "1";
const liveOutput = process.env.VISUAL_LIVE_SCREENSHOTS;
const statusLabels = {submitted: "已投稿", accepted: "已录用", published: "已发表"};
const observations = {checks: [], phases: {}, console: [], pageErrors: [], failedRequests: [], httpErrors: []};
const paths = {
  turns: /\/api\/v1\/teacher-agent\/conversations\/[^/?]+\/turns$/,
  detail: /\/api\/v1\/teacher-agent\/conversations\/[^/?]+$/,
  conversations: /\/api\/v1\/teacher-agent\/conversations$/,
  runs: /\/api\/v1\/teacher-agent\/runs\/[^/?]+$/,
};
const aliases = new Map();
const uuid = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/ig;
const dateField = {accepted: "acceptance_date", published: "publication_date", submitted: "submission_date"};

function check(name, actual, expected) {
  try {
    assert.deepEqual(actual, expected);
    observations.checks.push({name, pass: true});
  } catch {
    observations.checks.push({name, pass: false, actual, expected});
    console.log(`FAIL ${name}`);
  }
}

function save() {
  const serialized = JSON.stringify(observations, null, 2)
    .replace(uuid, (id) => {
      if (!aliases.has(id)) aliases.set(id, `<id-${aliases.size + 1}>`);
      return aliases.get(id);
    })
    .replace(/http:\/\/127\.0\.0\.1:\d+/g, "<local-origin>");
  fs.writeFileSync(`${output}/browser-observations.json`, `${serialized}\n`);
}

function responseFor(page, pattern, method = "GET") {
  return page.waitForResponse((response) => pattern.test(new URL(response.url()).pathname)
    && response.request().method() === method, {timeout: 150000});
}

function sorted(values) {
  return [...values].sort();
}

function roster(rows) {
  return sorted(rows.map((row) => JSON.stringify(row)));
}

function apiRow(item) {
  return {
    id: item.submission_id, owner: item.student_id, name: item.student_name, degree: item.degree,
    title: item.title, status: item.publication_status, date: item.status_date,
  };
}

function uiRow({name, title}) {
  return {title, name};
}

function expectedSource(row) {
  const {title, status, date} = row;
  return {title, status, date};
}

function sourceRow(cardSource) {
  const {title, publication_status: status, ...fields} =
    Object.fromEntries(cardSource.field_pointers.map(({field, value}) => [field, value]));
  return {title, status, date: fields[dateField[status]]};
}

function filters(spec) {
  return spec?.filters?.map((item) => `${item.field}:${item.operator}:${item.value}`).sort();
}

function metrics(card) {
  return Object.fromEntries((card?.summary?.metrics ?? []).map((item) => [item.key, item.value]));
}

function groups(card) {
  return Object.fromEntries((card?.summary?.breakdown ?? []).map((row) => [
    row.group_key.publication_status, [row.record_count, row.student_count],
  ]));
}

async function snapshot(panel) {
  return {
    status: await panel.locator('[role="status"]').allTextContents(),
    turns: await panel.locator(".teacher-turn").evaluateAll((turns) => {
      const fields = (root) => Object.fromEntries(
        Array.from(root.querySelectorAll(".paper-fields > div"), (entry) => [
          entry.querySelector("dt")?.textContent,
          entry.querySelector("dd")?.textContent,
        ]),
      );
      return turns.map((turn) => ({
        heading: turn.querySelector("h4")?.textContent,
        prompt: turn.querySelector(".bubble.user")?.textContent,
        text: turn.innerText,
        cards: Array.from(turn.querySelectorAll(".agent-result"), (card) => ({
          id: card.id,
          heading: card.querySelector("h4")?.textContent,
          asOf: card.querySelector(".data-as-of time")?.dateTime,
          text: card.textContent,
          chart: Array.from(card.querySelectorAll(".breakdown-segment"), (node) => node.title),
          buttons: Array.from(card.querySelectorAll(".breakdown-pills button"), (node) => node.textContent),
          metrics: Array.from(card.querySelectorAll(".kpi"), (node) => node.textContent),
          rows: Array.from(card.querySelectorAll(".paper-item"), (row) => ({
            title: row.querySelector(".paper-title h5")?.textContent,
            name: row.querySelector(".paper-student")?.textContent,
            submissionId: fields(row)["提交编号"],
            actions: Array.from(row.querySelectorAll(".paper-actions button"), (node) => node.textContent),
          })),
          sources: Array.from(card.querySelectorAll(".source-detail"), (row) => {
            const values = fields(row);
            const status = values["发表状态"];
            return {
              title: row.querySelector("strong")?.textContent.split(" · 提交版本")[0],
              status,
              date: values[{"已发表": "发表日期", "已录用": "录用日期", "已投稿": "投稿日期"}[status]],
            };
          }),
          source_titles: Array.from(card.querySelectorAll(".evidence-details > summary"), (node) => node.textContent),
        })),
      }));
    }),
  };
}

async function waitForReady(panel) {
  await panel.locator(".teacher-chat").waitFor();
  const loading = panel.locator(".loading-indicator");
  if (await loading.count()) await loading.last().waitFor({state: "hidden"});
}

async function visualGuest(turn) {
  const iframe = await turn.locator("iframe").first().elementHandle({timeout: 15000});
  let frame = await iframe.contentFrame();
  while (frame.childFrames().length === 1) frame = frame.childFrames()[0];
  return frame;
}

async function revealEvidence(turn) {
  const closed = turn.locator(".visual-evidence-toggle:not([open]) > summary");
  if (await closed.count()) await closed.click();
}

async function capture(response, panel, started) {
  const body = await response.json();
  const latencyMs = started == null ? undefined : Math.round(performance.now() - started);
  const latest = body.turn ?? body.turns?.at(-1);
  if (latest?.id) {
    const turn = panel.locator(`[data-turn-id="${latest.id}"]`);
    await turn.waitFor();
    await panel.locator('textarea[aria-label="你的问题"]:enabled').waitFor();
    if (body.visual) await turn.locator(".visual-sandbox-ready, .visual-fallback").waitFor();
  }
  return {
    latencyMs,
    status: response.status(),
    request: response.request().postDataJSON(),
    body,
    ui: await snapshot(panel),
  };
}

async function login(page, username) {
  const form = page.locator("#auth-form");
  await form.locator('input[name="username"]').fill(username);
  try {
    await form.locator('input[name="password"]').fill(accounts[username]);
  } catch {
    throw new Error("Could not fill the login password field");
  }
  const auth = responseFor(page, /\/api\/v1\/auth\/login$/, "POST");
  await form.getByRole("button", {name: /登录工作台/}).click();
  const response = await auth;
  assert.equal(response.status(), 200);
  const {user} = await response.json();
  await page.locator(".campus-shell").waitFor();
  return user.role;
}

async function logout(page) {
  await page.getByRole("button", {name: "退出登录", exact: true}).first().click();
  await page.locator("#auth-form").waitFor();
}

async function openAgent(page, paperQuery = true) {
  const launcher = page.getByRole("button", {name: "打开 Agent 助手", exact: true});
  if (await launcher.count()) await launcher.click();
  const panel = page.getByRole("dialog", {name: "InnoGrad Agent 对话"});
  await panel.waitFor();
  if (paperQuery) await waitForReady(panel);
  return panel;
}

async function send(page, panel, message, followup = false) {
  await panel.getByLabel("你的问题").fill(message);
  const turn = responseFor(page, paths.turns, "POST");
  const started = performance.now();
  await panel.getByRole("button", {name: followup ? "发送追问" : "发送问题", exact: true}).click();
  const response = await turn;
  const result = await capture(response, panel, started);
  check(`${message} HTTP`, result.status, invalidReceipt ? 502 : 200);
  check(`${message} request`, result.request.input, {mode: "natural_language", message});
  return result;
}

async function refresh(page, panel) {
  const detail = responseFor(page, paths.detail);
  await panel.getByRole("button", {name: "刷新对话", exact: true}).click();
  const response = await detail;
  await waitForReady(panel);
  return capture(response, panel);
}

async function selectConversation(page, panel, id) {
  const detail = id ? responseFor(page, paths.detail) : null;
  await panel.getByLabel("最近对话").selectOption(id);
  await waitForReady(panel);
  if (detail) return capture(await detail, panel);
}

function revoke() {
  const script = `
import os, sqlite3
with sqlite3.connect(os.environ["TEST_FIXTURE_DB"]) as conn:
    rows = conn.execute(
        "update supervisions set valid_to='2000-01-01T00:00:00+00:00' where teacher_id=?",
        (os.environ["TEST_TEACHER_ID"],),
    )
    assert rows.rowcount == 2, rows.rowcount
`;
  execFileSync("python3", ["-c", script], {stdio: "pipe"});
}

function inspectAggregate(phase, captured, expected, dates, clock) {
  const cards = captured.body.results ?? [];
  const card = cards[0];
  const spec = card?.applied_query;
  const ui = captured.ui.turns.at(-1)?.cards ?? [];
  check(`${phase} HTTP card count`, cards.length, 1);
  check(`${phase} applied spec`, {
    basis: spec?.basis, operation: spec?.operation, dates: spec?.time_range,
    group: spec?.group_by, subject: spec?.distinct_subject, filters: filters(spec),
  }, {
    basis: "current_effective_archives", operation: "aggregate", dates,
    group: ["publication_status"], subject: "paper_record", filters: expected.filters,
  });
  check(`${phase} group counts (records, students)`, groups(card), expected.groups);
  check(`${phase} overall record count`, metrics(card).paper_record_count, expected.total);
  check(`${phase} overall student count`, metrics(card).paper_student_count, expected.students);
  check(`${phase} API data time`, card?.summary?.data_as_of, clock);
  check(`${phase} UI cards bind to HTTP runs`, ui.map((entry) => entry.id),
    cards.map((entry) => `agent-run-${entry.query_run_id}`));
  check(`${phase} UI data time`, ui[0]?.asOf, clock);
  check(`${phase} UI overall counts`, ui[0]?.metrics?.filter((label) =>
    /^\d+(条论文申报记录数|人涉及学生人数)$/.test(label)), [
    `${expected.total}条论文申报记录数`, `${expected.students}人涉及学生人数`,
  ]);
  check(`${phase} host chart segments`, sorted(ui.flatMap((entry) => entry.chart)), sorted(Object.entries(expected.groups).map(
    ([status, [count]]) => `${statusLabels[status]} ${count}条`,
  )));
  check(`${phase} UI group rows`, sorted(ui.flatMap((entry) => entry.buttons)), sorted(Object.entries(expected.groups).map(
    ([status, [count, students]]) => `${statusLabels[status]} ${count}条 · ${students}人`,
  )));
  const expectedItems = spec?.include?.includes("items") ? expected.rows : [];
  check(`${phase} UI item rows equal HTTP items`, ui.flatMap((entry) => entry.rows.map(uiRow)),
    cards.flatMap((entry) => (entry.items ?? []).map((item) => uiRow(apiRow(item)))));
  check(`${phase} HTTP items match the requested projection`, roster((card?.items ?? []).map(apiRow)),
    roster(expectedItems.map(apiRowFromFixture)));
  check(`${phase} UI items match the requested projection`, roster(ui.flatMap((entry) => entry.rows.map(uiRow))),
    roster(expectedItems.map(uiRow)));
  const sources = spec?.include?.includes("sources") || expectedItems.length ? expected.rows.map(expectedSource) : [];
  check(`${phase} HTTP evidence identity, status and date`, roster((card?.sources ?? []).map(sourceRow)), roster(sources));
  check(`${phase} UI evidence identity, status and date`, roster(ui.flatMap((entry) => entry.sources)),
    roster(sources.map(({title, status, date}) => {
      const [year, month, day] = date.split("-");
      return {title, status: statusLabels[status], date: `${year}年${Number(month)}月${Number(day)}日`};
    })));
  return card;
}

function apiRowFromFixture({id, owner, name, degree, title, status, date}) {
  return {id, owner, name, degree, title, status, date};
}

function inspectDrill(phase, card, ui, expected, dates) {
  const spec = card?.applied_query;
  check(`${phase} applied spec`, {
    basis: spec?.basis, operation: spec?.operation, dates: spec?.time_range,
    group: spec?.group_by, subject: spec?.distinct_subject, filters: filters(spec),
  }, {
    basis: "current_effective_archives", operation: "list", dates,
    group: [], subject: "paper_record", filters: ["degree:eq:博士", "publication_status:eq:published"],
  });
  check(`${phase} explicitly requests items`, spec?.include?.includes("items"), true);
  check(`${phase} API full roster count`, card?.pagination?.total, expected.length);
  check(`${phase} API full roster fits on the page`, card?.pagination?.has_more, false);
  check(`${phase} UI card binds to the drill run`, ui?.id, `agent-run-${card?.query_run_id}`);
  check(`${phase} API list matches every archived submission`, roster((card?.items ?? []).map(apiRow)),
    roster(expected.map(apiRowFromFixture)));
  check(`${phase} API publication date matches every row`, roster((card?.items ?? []).map((item) =>
    [item.submission_id, item.publication_date])), roster(expected.map(({id, date}) => [id, date])));
  check(`${phase} UI list matches every archived submission`, roster((ui?.rows ?? []).map(uiRow)),
    roster(expected.map(uiRow)));
  check(`${phase} UI entries retain API order`, (ui?.rows ?? []).map(uiRow),
    (card?.items ?? []).map((item) => uiRow(apiRow(item))));
  check(`${phase} same-title submission identifiers`, sorted((ui?.rows ?? []).map(row => row.submissionId)),
    sorted(expected.map(row => row.id)));
  check(`${phase} in-app row actions`, (ui?.rows ?? []).map(row => row.actions),
    expected.map(() => ["材料详情", "成长画像"]));
}

async function run() {
  let browser;
  try {
    browser = await chromium.launch({headless: true});
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
    const page = await context.newPage();
    page.setDefaultTimeout(30000);
    page.on("console", (message) => {
      if (["error", "warning"].includes(message.type())) observations.console.push({
        type: message.type(), text: message.text(), url: message.location().url,
      });
    });
    page.on("pageerror", (error) => observations.pageErrors.push(error.message));
    page.on("requestfailed", (request) => observations.failedRequests.push({
      url: request.url(), method: request.method(), error: request.failure()?.errorText,
    }));
    page.on("response", (response) => {
      if (response.status() >= 400) observations.httpErrors.push({
        url: response.url(), status: response.status(), method: response.request().method(),
      });
    });
    const screenshot = async (name, panel, showRows = false) => {
      const rows = panel.locator(".teacher-turn").last().locator(".agent-result .paper-item");
      if (showRows && await rows.count() && await rows.last().isVisible()) await rows.last().scrollIntoViewIfNeeded();
      await panel.screenshot({
        path: `${output}/${name}.png`, mask: [panel.locator(".agent-analysis a")], maskColor: "#6b7280",
      });
      save();
    };
    const liveShot = async (name, target) => {
      if (!liveOutput) return;
      await target.scrollIntoViewIfNeeded();
      await page.screenshot({path: `${liveOutput}/${name}.png`, animations: "disabled"});
    };
    const liveTurnShot = async (name) => {
      if (!liveOutput) return;
      const turn = panel.locator(".teacher-turn").last();
      await liveShot(name, turn.locator(".agent-result").first());
    };

    await page.goto(`${root}/prototype/`);
    check("teacher login role", await login(page, "teacher"), "teacher");
    check("teacher navigation count", await page.getByRole("button", {name: "Agent 论文问答", exact: true}).count(), 0);
    let panel = await openAgent(page);
    const {dates, clock, overview, doctoral, drill: drillRoster, studentName, namedPapers, published} = fixture;

    const first = await send(page, panel, "今年论文发表情况怎么样？");
    observations.phases.overview = first;
    if (invalidReceipt) {
      check("injected receipt returns planner error", first.body.code, "INVALID_PLANNER_OUTPUT");
      check("no uncaught page errors", observations.pageErrors, []);
      return;
    }
    if (first.status !== 200) return;
    inspectAggregate("annual overview", first, overview, dates, clock);
    const overviewTurn = panel.locator(".teacher-turn").last();
    check("overview has a generated HTML answer", Boolean(first.body.visual?.html), true);
    const overviewGuest = await visualGuest(overviewTurn);
    await overviewGuest.getByText(/已发表/).first().waitFor();
    check("overview uses everyday teacher language", (await overviewGuest.locator("body").innerText()).includes("下钻"), false);
    await overviewTurn.locator("iframe").first().scrollIntoViewIfNeeded();
    await page.screenshot({path: `${output}/teacher-chart.png`, animations: "disabled"});
    await liveTurnShot("01-live-turn1-overview");
    if (liveOutput) {
      await panel.getByRole("button", {name: "展开宽浮窗"}).click();
      await liveTurnShot("01b-live-turn1-wide");
      await panel.getByRole("button", {name: "恢复默认宽度"}).click();
    }
    await screenshot("01-overview", panel, true);

    const followup = await send(page, panel, "只看博士生呢？", Boolean(first.body.turn));
    observations.phases.followup = followup;
    check("follow-up uses same conversation", followup.body.conversation_id, first.body.conversation_id);
    check("follow-up uses previous lock version", followup.request.expected_lock_version, first.body.conversation_lock_version);
    const doctoralCard = inspectAggregate("doctoral follow-up", followup, doctoral, dates, clock);
    await liveTurnShot("02-live-turn2-doctor");
    await screenshot("02-doctoral-followup", panel, true);

    const doctoralGuest = await visualGuest(panel.locator(".teacher-turn").last());
    check("follow-up uses everyday teacher language", (await doctoralGuest.locator("body").innerText()).includes("下钻"), false);
    let groupButton = doctoralGuest.getByRole("button", {name: /已发表/}).first();
    if (!await groupButton.count()) {
      const publishedLabel = doctoralGuest.getByText("已发表", {exact: true}).first();
      const publishedRow = publishedLabel.locator("xpath=ancestor::*[.//button][1]");
      groupButton = publishedRow.getByRole("button", {name: /查看|明细|论文/}).first();
    }
    let drill;
    if (await groupButton.count()) {
      const drillPending = responseFor(page, paths.turns, "POST");
      const started = performance.now();
      await groupButton.click();
      const drillResponse = await drillPending;
      drill = await capture(drillResponse, panel, started);
      observations.phases.drill = drill;
      check("drill HTTP", drill.status, 200);
      check("drill request mode", drill.request.input.mode, "drilldown_patch");
      check("drill targets follow-up card", drill.request.input.parent_run_id, doctoralCard?.query_run_id);
      check("drill uses follow-up lock version", drill.request.expected_lock_version, followup.body.conversation_lock_version);
      check("drill stays in the conversation", drill.body.conversation_id, first.body.conversation_id);
      inspectDrill("drill", drill.body.result, drill.ui.turns.at(-1)?.cards[0], drillRoster, dates);
      await screenshot("03-drill", panel, true);
    } else {
      check("doctoral published group has drill button", false, true);
    }

    if (liveOutput) {
      const card = panel.locator(".teacher-turn").last().locator(".agent-result").first();
      const note = card.locator(".duplicate-note");
      await note.waitFor();
      await liveShot("03-live-turn3-published", note);
      await card.getByRole("button", {name: "材料详情", exact: true}).first().click();
      const modal = page.getByRole("heading", {name: "论文成果 · 材料详情", exact: true});
      await modal.waitFor();
      await liveShot("04-live-inapp-modal", modal);
      check("material opens in app", new URL(page.url()).pathname, "/prototype/");
      await page.getByLabel("关闭").click();
      panel = await openAgent(page);
      const portrait = await send(page, panel, `看看${studentName}的成长画像`, true);
      observations.phases.portrait = portrait;
      await revealEvidence(panel.locator(".teacher-turn").last());
      const portraitCard = panel.locator(".teacher-turn").last().locator(".agent-result").first();
      const button = portraitCard.getByRole("button", {name: "查看完整成长画像"});
      await button.waitFor();
      await liveShot("05-live-turn4-portrait", portraitCard.getByRole("heading", {name: `${studentName}的成长画像`}).first());
      await button.click();
      await page.waitForURL(/#portraits$/);
      check("portrait opens in app", new URL(page.url()).pathname, "/prototype/");
      check("portrait opens the requested student", await page.getByLabel("选择画像学生").inputValue(), fixture.studentId);
      check("no uncaught page errors", observations.pageErrors, []);
      return;
    }

    const conversationId = await panel.getByLabel("最近对话").inputValue();
    const reloadPending = responseFor(page, paths.detail);
    await page.reload();
    await page.locator(".campus-shell").waitFor();
    panel = await openAgent(page);
    const reloaded = await capture(await reloadPending, panel);
    observations.phases.reload = reloaded;
    check("browser reload detail HTTP", reloaded.status, 200);
    check("browser reload restored conversation", reloaded.body.conversation.id, conversationId);
    check("browser reload restored all three turns", reloaded.body.turns.map((item) => item.turn_index), [1, 2, 3]);
    if (drill) {
      check("browser reload restores drill run", reloaded.body.latest_result?.query_run_id, drill.body.result?.query_run_id);
      inspectDrill("browser reload", reloaded.body.latest_result, reloaded.ui.turns.at(-1)?.cards[0], drillRoster, dates);
      const refreshed = await refresh(page, panel);
      observations.phases.refresh = refreshed;
      check("conversation refresh detail HTTP", refreshed.status, 200);
      check("conversation refresh keeps the same selection", await panel.getByLabel("最近对话").inputValue(), conversationId);
      check("conversation refresh returns the same conversation", refreshed.body.conversation?.id, conversationId);
      check("conversation refresh restores all three turns", refreshed.body.turns.map((item) => item.turn_index), [1, 2, 3]);
      check("conversation refresh preserves drill run", refreshed.body.latest_result?.query_run_id, drill.body.result?.query_run_id);
      inspectDrill("conversation refresh", refreshed.body.latest_result, refreshed.ui.turns.at(-1)?.cards[0], drillRoster, dates);
    }
    await screenshot("04-browser-reload", panel, true);

    await selectConversation(page, panel, "");
    const summary = await send(page, panel, "今年论文发表情况怎么样？");
    const listed = await send(page, panel, "已发表的是哪几篇？", true);
    check("publication list follows the overview", listed.body.conversation_id, summary.body.conversation_id);
    const listedRows = panel.locator(".teacher-turn").last().locator(".agent-result .paper-item");
    check("teacher sees the published titles", sorted(listed.ui.turns.at(-1)?.cards.flatMap(card => card.rows.map(row => row.title)) ?? []),
      sorted(overview.rows.filter(row => row.status === "published").map(row => row.title)));
    if (await listedRows.count()) {
      const listTurn = panel.locator(".teacher-turn").last();
      const listGuest = await visualGuest(listTurn);
      const material = listGuest.getByRole("button", {name: /材料详情/}).first();
      await material.waitFor();
      await listTurn.locator("iframe").first().scrollIntoViewIfNeeded();
      await page.screenshot({path: `${output}/teacher-published-list.png`, animations: "disabled"});
      await material.click();
      await page.getByRole("heading", {name: "论文成果 · 材料详情", exact: true}).waitFor();
      await page.screenshot({path: `${output}/teacher-material.png`, animations: "disabled"});
      await page.getByLabel("关闭").click();
      panel = await openAgent(page);
    }

    await selectConversation(page, panel, "");
    const named = await send(page, panel, `请列出${studentName}已发表的论文。`);
    observations.phases.named = named;
    const namedCard = named.body.result;
    const namedId = named.body.conversation_id;
    check("named query resolves to one synthetic student ID", filters(namedCard?.applied_query), [
      "publication_status:eq:published", `student_id:eq:${fixture.studentId}`,
    ]);
    check("named API records", sorted((namedCard?.items ?? []).map((item) => item.title)), sorted(namedPapers));
    check("named UI rows", sorted((named.ui.turns.at(-1)?.cards[0]?.rows ?? []).map((row) =>
      `${row.title}:${row.name}`)), sorted(namedPapers.map((title) => `${title}:${studentName}`)));
    await screenshot("05-named-query", panel, true);
    const namedRows = panel.locator(".teacher-turn").last().locator(".paper-item");
    await revealEvidence(panel.locator(".teacher-turn").last());
    const firstNamedRow = namedRows.first();
    await firstNamedRow.getByRole("button", {name: "材料详情", exact: true}).click();
    await page.getByRole("heading", {name: "论文成果 · 材料详情", exact: true}).waitFor();
    check("material action stays in app", new URL(page.url()).pathname, "/prototype/");
    check("material action avoids raw API navigation", new URL(page.url()).pathname.includes("/api/"), false);
    await page.getByLabel("关闭").click();
    await firstNamedRow.getByRole("button", {name: "成长画像", exact: true}).click();
    await page.waitForURL(/#portraits$/);
    check("portrait action stays in app", new URL(page.url()).pathname, "/prototype/");
    check("portrait action avoids raw API navigation", new URL(page.url()).pathname.includes("/api/"), false);
    revoke();
    panel = await openAgent(page);
    await panel.getByText("查询范围已变更，本轮内容不可查看。", {exact: true}).waitFor();
    const revoked = await refresh(page, panel);
    observations.phases.namedAfterRevocation = revoked;
    check("revoked named detail HTTP", revoked.status, 200);
    check("named history is revoked", revoked.body.turns.at(-1)?.access_revoked, true);
    check("revoked named detail has no latest cards", revoked.body.latest_results, []);
    check("revoked named UI hides cards", revoked.ui.turns.flatMap((turn) => turn.cards), []);
    check("revoked named UI notice", revoked.ui.turns.at(-1)?.text.includes("查询范围已变更，本轮内容不可查看。"), true);
    check("revoked named UI hides prompt text", revoked.ui.turns.at(-1)?.text.includes(studentName), false);
    if (namedCard?.query_run_id) {
      const reply = await context.request.get(`${root}/api/v1/teacher-agent/runs/${namedCard.query_run_id}`);
      observations.phases.revokedNamedRun = {status: reply.status(), body: await reply.json()};
      check("revoked named run HTTP", reply.status(), 404);
    }
    await screenshot("06-named-revoked", panel);

    const recomputed = await selectConversation(page, panel, conversationId);
    observations.phases.aggregateAfterRevocation = recomputed;
    check("aggregate conversation detail after revocation HTTP", recomputed.status, 200);
    check("aggregate history remains readable", recomputed.body.turns.map((turn) => turn.access_revoked),
      recomputed.body.turns.map(() => false));
    check("aggregate latest result recomputed", recomputed.body.latest_result?.summary.scope_recomputed, true);
    check("aggregate latest result scope is empty", recomputed.body.latest_result?.summary.scope_student_count, 0);
    check("aggregate latest result has zero matches", metrics(recomputed.body.latest_result).paper_record_count, 0);
    check("scope-checked UI has no paper rows", recomputed.ui.turns.flatMap((turn) => turn.cards.flatMap((card) => card.rows)), []);
    check("scope-checked UI shows empty result", /0 条符合条件|没有符合条件/.test(recomputed.ui.turns.at(-1)?.cards[0]?.text), true);
    if (doctoralCard?.query_run_id) {
      const reply = await context.request.get(`${root}/api/v1/teacher-agent/runs/${doctoralCard.query_run_id}`);
      const body = await reply.json();
      observations.phases.recomputedGroupRun = {status: reply.status(), body};
      check("aggregate group run after revocation HTTP", reply.status(), 200);
      check("aggregate group run recomputed", body.summary?.scope_recomputed, true);
      check("aggregate group run has no groups", body.summary?.breakdown, []);
      check("aggregate group run has zero matches", metrics(body).paper_record_count, 0);
    }
    await screenshot("07-aggregate-recomputed", panel);

    await logout(page);
    check("manager login role", await login(page, "manager"), "manager");
    panel = await openAgent(page);
    check("manager starts without teacher history", await panel.getByLabel("最近对话").locator("option").count(), 1);
    const manager = await send(page, panel, "请列出今年已发表的论文。");
    observations.phases.manager = manager;
    const managerCard = manager.body.result;
    check("manager applied publication-date range", managerCard?.applied_query?.time_range, {...dates, field: "publication_date"});
    check("manager API visible publications", sorted((managerCard?.items ?? []).map((item) => item.title)), sorted(published));
    check("manager UI visible publications", sorted((manager.ui.turns.at(-1)?.cards[0]?.rows ?? []).map((row) => row.title)),
      sorted(published));
    check("manager has distinct conversation", [conversationId, namedId].includes(manager.body.conversation_id), false);
    await screenshot("08-manager", panel, true);

    await logout(page);
    check("student login role", await login(page, studentLogin), "student");
    const studentAgentRequests = [];
    page.on("request", (request) => {
      const pathname = new URL(request.url()).pathname;
      if (pathname.startsWith("/api/v1/teacher-agent/")) studentAgentRequests.push({method: request.method(), pathname});
    });
    panel = await openAgent(page, false);
    const guide = panel.getByText("使用指引模式 · AI 对话服务暂未接入", {exact: true});
    await guide.waitFor();
    await panel.getByLabel("输入消息").fill("查询我的个人数据");
    await panel.getByRole("button", {name: "发送消息", exact: true}).click();
    const reply = panel.getByText(/无法查询个人数据或执行操作/);
    await reply.waitFor();
    observations.phases.student = {
      guide: await guide.innerText(),
      reply: await reply.innerText(),
      teacherPanelCount: await panel.locator(".teacher-chat").count(),
      teacherNavCount: await page.getByRole("button", {name: "Agent 论文问答", exact: true}).count(),
      agentRequests: studentAgentRequests,
    };
    check("student teacher panel count", observations.phases.student.teacherPanelCount, 0);
    check("student teacher navigation count", observations.phases.student.teacherNavCount, 0);
    check("student guide sends no teacher-agent requests", studentAgentRequests, []);
    check("no uncaught page errors", observations.pageErrors, []);
    await screenshot("09-student-guide", panel);
  } catch (error) {
    observations.harness_error = {name: error.name, message: error.message.replace(/\x1b\[[\d;]*m/g, "")};
    console.error(`${error.name}: ${observations.harness_error.message}`);
    process.exitCode = 2;
  } finally {
    save();
    await browser?.close();
    const failed = observations.checks.filter((item) => !item.pass).length;
    console.log(`${observations.checks.length} browser checks, ${failed} failed`);
    if (failed && !process.exitCode) process.exitCode = 1;
  }
}

run();
