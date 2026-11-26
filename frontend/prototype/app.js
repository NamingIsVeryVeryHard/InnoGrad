import { renderGrowth, renderWarnings } from "./growth-ui.js?v=campus-v1";
import { fieldLabels, formatValue } from "../teacher-chat/field-labels.js";
const $ = (s) => document.querySelector(s),
  esc = (v) =>
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
const authorNames = (authors) =>
  Array.isArray(authors) ? [...authors].sort((a, b) => a.order - b.order).map((a) => a.name).join("\n") : String(authors || "");
const memberNames = (members) =>
  Array.isArray(members)
    ? [...members]
        .sort((a, b) => (a.order || 0) - (b.order || 0))
        .map((m) => (typeof m === "string" ? m : m.name))
        .join("\n")
    : String(members || "");
const icons = {
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  users:
    "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M16 3a4 4 0 0 1 0 8 M22 21v-2a4 4 0 0 0-3-3.87 M13 7a4 4 0 1 1-8 0a4 4 0 0 1 8 0",
  task: "M9 3h6v4H9z M9 5H5v16h14V5h-4 M8 12h8 M8 16h5",
  review: "M9 3H4v18h16V9 M14 3l7 7 M10 14l10-10-3-3L7 11l-1 4z",
  paper: "M14 2H5v20h14V7z M14 2v6h5 M8 12h8 M8 16h6",
  archive: "M3 3h18v5H3z M5 8v13h14V8 M9 12h6",
  chart: "M4 3v18h17 M8 16v-5 M13 16V7 M18 16v-9",
  bell: "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9 M10 21h4",
  settings:
    "M12 8a4 4 0 1 0 0 8a4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2",
  search: "M21 21l-5-5 M18 10a8 8 0 1 1-16 0a8 8 0 0 1 16 0",
  arrow: "M5 12h14 M14 7l5 5-5 5",
  plus: "M12 5v14 M5 12h14",
  download: "M12 3v12 M7 10l5 5 5-5 M4 17v4h16v-4",
  calendar: "M4 5h16v16H4z M8 2v6 M16 2v6 M4 10h16",
  check: "M5 12l4 4L19 6",
  clock: "M12 8v5l3 2 M22 12a10 10 0 1 1-20 0a10 10 0 0 1 20 0",
  shield: "M12 2l9 4v6c0 6-9 10-9 10S3 18 3 12V6z M8 11l3 3 5-6",
  book: "M12 5v16 M12 5C8 2 3 3 2 4v16c3-2 7-2 10 1c3-3 7-3 10-1V4c-3-2-7-2-10 1",
  logout: "M9 3H3v18h6 M10 12h12 M18 8l4 4-4 4",
  menu: "M3 6h18 M3 12h18 M3 18h18",
  history: "M3 11a9 9 0 1 1 2 7 M3 3v8h8 M12 7v6l4 2",
  spark: "M12 2l3 7 7 3-7 3-3 7-3-7-7-3 7-3z",
  trophy:
    "M6 9H4.5a2.5 2.5 0 0 1 0-5H6 M18 9h1.5a2.5 2.5 0 0 0 0-5H18 M4 22h16 M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22 M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22 M18 2H6v7a6 6 0 0 0 12 0V2z",
  globe:
    "M12 2a10 10 0 1 0 0 20a10 10 0 0 0 0-20 M2 12h20 M12 2a15.3 15.3 0 0 1 4 10a15.3 15.3 0 0 1-4 10a15.3 15.3 0 0 1-4-10a15.3 15.3 0 0 1 4-10z",
};
const icon = (n, size = 18) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${icons[n] || icons.paper}"/></svg>`;
const randomId = () => {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const b = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(b);
  else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (v) => v.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
};
const id = () => randomId(),
  stamp = () =>
    new Date().toLocaleString("zh-CN", {
      timeZone: "Asia/Shanghai",
      hour12: false,
    }),
  date = (d) => {
    if (!d) return "";
    const v = new Date(d);
    return Number.isNaN(v.getTime())
      ? String(d).slice(0, 10)
      : new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(
          v,
        );
  },
  btn = (label, action, primary = false, ico = "") =>
    `<button type="button" class="btn ${primary ? "primary" : ""}" data-action="${action}">${ico ? icon(ico) : ""}${label}</button>`;
const statusLabels = {
    draft: "草稿",
    pending: "待 Agent 审核",
    returned: "待补正",
    archived: "已归档",
    approved: "待后台归档",
  },
  badge = (s) =>
    `<span class="badge ${{ pending: "amber", returned: "red", draft: "gray", archived: "" }[s] || ""}">${statusLabels[s] || esc(s)}</span>`;
const paperFileRoleLabels = {
  paper_fulltext: "论文全文",
  submission_proof: "投稿证明",
  author_order_proof: "作者顺位证明",
  acceptance_proof: "录用证明",
  publication_proof: "发表证明",
  article_page: "文章页面或 DOI 证明",
  contribution_proof: "本人贡献证明",
  other_proof: "其他证明材料",
};
const competitionFileRoleLabels = {
  award_certificate: "获奖证书",
  publicity_proof: "公示页面或获奖名单证明",
  team_role_proof: "团队成员与本人角色证明",
  other_proof: "其他证明材料",
};
const exchangeFileRoleLabels = {
  attendance_proof: "参会证明 / 邀请函",
  presentation_proof: "作报告证明 / 议程 / PPT",
  poster_proof: "海报展示证明 / 海报原件",
  practice_task_proof: "实践任务证明 / 结项或考核材料",
  other_proof: "其他证明材料",
};
const fileRoleLabelsByKind = {
  paper: paperFileRoleLabels,
  annual: paperFileRoleLabels,
  competition: competitionFileRoleLabels,
  exchange: exchangeFileRoleLabels,
};
const allFileRoleLabels = {
  ...paperFileRoleLabels,
  ...competitionFileRoleLabels,
  ...exchangeFileRoleLabels,
};
const exchangeModeLabels = {
  attend: "参会",
  talk: "作报告",
  poster: "展示海报",
  practice_task: "承担具体实践任务",
};
const exchangeModeMeta = [
  {
    value: "attend",
    label: "参会",
    summary: "参加学术会议、论坛或专题研讨",
    proofHint: "请上传参会证明、注册确认函或会议日程",
    portraitTarget: "学术交流",
  },
  {
    value: "talk",
    label: "作报告",
    summary: "在会议或学术活动中做口头报告",
    proofHint: "请填写报告题目，并上传议程、邀请函或报告 PPT",
    portraitTarget: "学术交流",
  },
  {
    value: "poster",
    label: "展示海报",
    summary: "在学术会议上展示研究成果海报",
    proofHint: "请填写海报题目，并上传海报原件或现场展示证明",
    portraitTarget: "学术交流",
  },
  {
    value: "practice_task",
    label: "承担具体实践任务",
    summary: "在科研实践项目或联合应用中承担明确任务",
    proofHint: "请详述承担的具体实践任务，并上传结项、考核或实践证明",
    portraitTarget: "实践落地",
  },
];
const proofModeLabels = {
  certificate_and_link: "证书+公示链接",
  certificate_only: "证书附件",
  link_only: "仅公示链接",
};
const exchangeModeFileRoles = {
  attend: "attendance_proof",
  talk: "presentation_proof",
  poster: "poster_proof",
  practice_task: "practice_task_proof",
};
const kindMeta = {
  paper: {
    label: "论文成果",
    short: "论文申报",
    detailTitle: "论文成果 · 材料详情",
    editTitle: "编辑论文成果",
    emptyTitle: "未命名论文",
  },
  annual: {
    label: "年度报告",
    short: "培养材料",
    detailTitle: "年度培养 · 材料详情",
    editTitle: "编辑年度报告",
    emptyTitle: "年度培养报告",
  },
  competition: {
    label: "竞赛与获奖",
    short: "竞赛获奖",
    detailTitle: "竞赛与获奖 · 材料详情",
    editTitle: "编辑竞赛与获奖",
    emptyTitle: "未命名竞赛",
  },
  exchange: {
    label: "学术交流",
    short: "学术交流",
    detailTitle: "学术交流 · 材料详情",
    editTitle: "编辑学术交流",
    emptyTitle: "未命名学术交流",
  },
};
const safeExternalLink = (url) =>
  /^https?:\/\//i.test(String(url || "").trim())
    ? `<a href="${esc(url.trim())}" target="_blank" rel="noopener noreferrer">${esc(url.trim())} ↗</a>`
    : esc(url || "—");
let me = null,
  role = "",
  csrf = "",
  people = [],
  state = {
    students: [],
    records: [],
    tasks: [],
    alerts: [],
    rules: [],
    logs: [],
    corrections: [],
  },
  capabilities = {},
  systemStatus = {},
  portraitsCache = {},
  reviewQueue = [];
let page = location.hash.slice(1) || "dashboard",
  filter = "all",
  subFilter = "all",
  query = "",
  pageNum = 1,
  selectedStudent = "",
  menu = false;
const roleName = () =>
    ({
      manager: "管理教师",
      teacher: "导师",
      student: "学生",
      operator: "技术管理员",
    })[role] || "",
  actor = () => me?.name || "";
function toast(text) {
  $("#toast").textContent = text;
  $("#toast").style.display = "block";
  clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(
    () => ($("#toast").style.display = "none"),
    5000,
  );
}
const student = (s) =>
    state.students.find((p) => p.id === s) || {
      id: s,
      name: "不可访问的学生",
      number: "—",
    },
  person = (sid) => {
    const s = student(sid);
    return `<div class="person"><span class="avatar">${esc(s.name.replace(/（模拟）$/, "").slice(-2))}</span><div><span class="cell-title">${esc(s.name)}</span><small>${esc(s.number)}</small></div></div>`;
  };
const visibleStudents = () => state.students,
  records = () => state.records,
  tasks = () => state.tasks;
const studentNavLabels = {
  papers: "我的论文成果",
  competitions: "我的竞赛与获奖",
  exchanges: "我的学术交流",
};
const pending = () => records().filter((r) => r.status === "pending");
const navs = [
  ["dashboard", "grid", "工作概览"],
  ["students", "users", "学生管理"],
  ["tasks", "task", "培养任务"],
  ["reviews", "spark", "Agent 审核"],
  ["papers", "paper", "论文成果"],
  ["competitions", "trophy", "竞赛与获奖"],
  ["exchanges", "globe", "学术交流"],
  ["archives", "archive", "成果档案"],
  ["portraits", "chart", "成长画像"],
  ["alerts", "bell", "关注与提醒"],
  ["rules", "shield", "规则与模板"],
  ["logs", "history", "操作记录"],
  ["settings", "settings", "系统设置"],
];
async function go(p) {
  $("#dialog").close();
  page = p;
  filter = p === "alerts" ? "active" : "all";
  subFilter = "all";
  query = "";
  pageNum = 1;
  menu = false;
  location.hash = p;
  await refresh();
}
function render() {
  if (!me) return loginView();
  if (role === "operator" && !["dashboard", "settings", "logs"].includes(page))
    page = "settings";
  if (
    (role === "student" &&
      ["students", "reviews", "rules", "logs"].includes(page)) ||
    (role !== "manager" && page === "rules")
  )
    page = "dashboard";
  if (!navs.some((n) => n[0] === page)) page = "dashboard";
  const title = navs.find((n) => n[0] === page)[2];
  const available = navs.filter(
    (n) =>
      (role !== "operator" ||
        ["dashboard", "settings", "logs"].includes(n[0])) &&
      !(
        role === "student" &&
        ["students", "reviews", "rules", "logs"].includes(n[0])
      ) &&
      !(role === "teacher" && n[0] === "rules"),
  );
  const notices = visibleAlerts().filter((a) => a.status === "open").length;
  $("#app").innerHTML =
    `<div class="shell campus-shell ${menu ? "menu-open" : ""}"><header class="campus-masthead"><button class="campus-menu" data-action="menu" aria-label="展开或收起导航">${icon("menu", 24)}</button><a class="campus-brand" href="#dashboard" data-page="dashboard"><span class="campus-seal">${icon("book", 25)}</span><span><strong>InnoGrad</strong><span class="campus-brand-title">研究生培养管理</span><small>上海智能教育研究院</small></span></a><nav class="campus-topnav" aria-label="主导航"><button data-page="dashboard" class="${page === "dashboard" ? "active" : ""}">我的首页</button>${role !== "operator" ? `<button data-page="portraits" class="${page === "portraits" ? "active" : ""}">学业生涯</button><button data-page="alerts" class="${page === "alerts" ? "active" : ""}">消息中心 ${notices ? `<em>${notices}</em>` : ""}</button><button data-page="tasks" class="${page === "tasks" ? "active" : ""}">培养任务</button>` : ""}</nav><form id="global-search" class="searchbox campus-search">${icon("search", 16)}<input aria-label="全局搜索" name="q" placeholder="搜索学生、任务、成果" autocomplete="off"></form><button class="campus-account" data-page="settings" aria-label="当前账号与系统设置"><span class="avatar">${esc(actor().slice(0, 1))}</span><span>${esc(actor())}<small>${roleName()}</small></span></button></header><div class="mobile-scrim" data-action="menu"></div><aside class="sidebar"><div class="campus-services">${icon("grid", 20)}<span>全部服务</span><span>›</span></div><nav aria-label="业务服务">${available.map((n) => `<button class="nav ${page === n[0] ? "active" : ""}" data-page="${n[0]}" title="${n[2]}"><span class="campus-nav-icon">${icon(n[1], 16)}</span><span class="nav-text">${role === "student" && studentNavLabels[n[0]] ? studentNavLabels[n[0]] : n[2]}</span>${n[0] === "reviews" && pending().length ? `<span class="count">${pending().length}</span>` : '<span class="nav-chevron">›</span>'}</button>`).join("")}</nav><div class="sidebar-bottom"><div class="campus-institute">上海智能教育研究院<br><small>InnoGrad 培养工作空间</small></div><button class="online" data-action="logout">${icon("logout", 16)}<span>退出登录</span></button></div></aside><div class="main"><header class="topbar"><button class="campus-home-tab" data-page="dashboard">首页</button><div class="campus-current-tab">${title}</div><div class="campus-tab-tools"><button data-action="refresh" aria-label="刷新当前页面">${icon("history", 15)}</button><span>${new Date().toLocaleDateString("zh-CN")}</span></div></header><main class="content">${views[page]()}<footer class="footer"><span>InnoGrad · 上海智能教育研究院</span><span>研究生培养与成长管理 · 服务端数据</span></footer></main></div></div>`;
  bind();
}
const heading = (title, sub, actions = "") =>
  `<div class="page-heading"><div><h1>${title}</h1><p>${sub}</p></div><div class="actions">${actions}</div></div>`;
const empty = (
  text = "暂无相关记录",
  sub = "调整筛选条件，或创建一条新记录。",
) => `<div class="empty">${icon("archive")}<h3>${text}</h3><p>${sub}</p></div>`;
function statCards() {
  const rr = records(),
    ss = visibleStudents();
  return `<div class="stats">${[
    [
      role === "student" ? "我的培养任务" : "在读研究生",
      role === "student" ? tasks().length : ss.length,
      role === "student" ? "项" : "人",
      "users",
      "当前授权范围内",
    ],
    ["待审材料", pending().length, "份", "review", "Agent 材料审核"],
    [
      "已归档成果",
      rr.filter((r) => r.effective).length,
      "份",
      "archive",
      "正式认定，保留版本",
    ],
    [
      "材料归档率",
      Math.round(
        (rr.filter((r) => r.status === "archived").length / (rr.length || 1)) *
          100,
      ),
      "%",
      "chart",
      "按当前材料记录计算",
    ],
  ]
    .map(
      ([label, value, unit, ico, foot]) =>
        `<div class="stat"><div class="stat-label">${label}</div><div class="stat-icon">${icon(ico)}</div><div class="stat-value">${value}<span>${unit}</span></div><div class="stat-foot"><em>↗</em>${foot}</div></div>`,
    )
    .join("")}</div>`;
}
function recordTable(rr, compact = false) {
  if (!rr.length)
    return empty("当前没有相关材料", "新的提交或状态变更会显示在这里。");
  return `<div class="table-wrap"><table><thead><tr><th>学生</th><th>材料类型 / 名称</th>${compact ? "" : "<th>复核教师</th><th>更新时间</th>"}<th>状态</th><th>操作</th></tr></thead><tbody>${rr.map((r) => {
    const meta = kindMeta[r.kind] || { label: "培养材料", short: "培养材料" };
    const compactTitle =
      r.kind === "paper"
        ? "论文成果申报"
        : r.kind === "annual"
          ? "年度考核报告"
          : r.title;
    const subBadges =
      r.kind === "competition"
        ? `${r.awardLevel ? `<span class="award-pill">${esc(r.awardLevel)}</span>` : ""}${r.proofMode ? `<span class="mode-pill mode-proof">${esc(proofModeLabels[r.proofMode] || r.proofMode)}</span>` : ""}`
        : r.kind === "exchange" && r.participationMode
          ? `<span class="mode-pill mode-${esc(r.participationMode)}">${esc(exchangeModeLabels[r.participationMode] || r.participationMode)}</span>`
          : "";
    return `<tr><td>${person(r.student)}</td><td><div class="cell-title" style="max-width:${compact ? "190" : "280"}px;overflow:hidden;text-overflow:ellipsis">${esc(compact ? compactTitle : r.title)}</div><small style="display:block;margin-top:6px">${esc(meta.label)}${subBadges ? " " + subBadges : ""} · ${r.versions.length ? "V" + r.versions.length : "工作稿"}</small></td>${compact ? "" : `<td>${esc(r.reviewer)}</td><td>${esc(date(r.updated))}</td>`}<td>${badge(r.status)}</td><td><button class="linkbtn" data-action="record:${r.id}">${role === "student" && ["draft", "returned"].includes(r.status) ? "继续填写" : r.status === "pending" && role === "teacher" && r.raw.reviewer_id === me.id ? "去审核" : "查看详情"} &nbsp;↗</button></td></tr>`;
  }).join("")}</tbody></table></div>`;
}
function progress(t) {
  const ids = t.students.filter((s) =>
      visibleStudents().some((v) => v.id === s),
    ),
    done = records().filter(
      (r) => r.task === t.id && r.effective && ids.includes(r.student),
    ).length,
    total = ids.length;
  return { done, total, percent: Math.round((done / (total || 1)) * 100) };
}
const heroArt = `<svg class="hero-art" viewBox="0 0 300 200" fill="none" aria-hidden="true"><circle cx="170" cy="115" r="87" stroke="#c4d4bd"/><circle cx="170" cy="115" r="66" stroke="#cfddc6"/><path d="M40 170L153 105l113 56-108 57z" fill="#d0dcc6"/><path d="M89 147l67-37 67 34-67 39z" fill="#a7bea1"/><path d="M89 147v12l67 34v-10z" fill="#789c7c"/><path d="M156 183l67-39v12l-67 37z" fill="#c1d0b2"/><path d="M95 132l67-37 67 34-67 39z" fill="#f9fbf2"/><path d="M95 132v10l67 34v-8z" fill="#bdcead"/><path d="M162 168l67-39v10l-67 37z" fill="#dce5d1"/><path d="M107 112l55-31 55 28-55 32z" fill="#5b8566"/><path d="M107 112v10l55 29v-10z" fill="#3d684e"/><path d="M162 141l55-32v10l-55 32z" fill="#82a17a"/><path d="M119 65l48-25 52 26-48 27z" fill="#284f3f"/><path d="M138 80v20c18 12 35 11 51-1V82" fill="#517b58"/><path d="M119 65l48-25 52 26-48 27z" fill="#355f49"/><path d="M171 67l29 15v30" stroke="#c4ba7f" stroke-width="2"/><path d="M196 111h8l2 16h-12z" fill="#c4ba7f"/><path d="M63 107v-18m-9 9h18M244 70V58m-6 6h12" stroke="#9eb497"/><circle cx="83" cy="53" r="3" fill="#a4ba9b"/><circle cx="250" cy="141" r="3" fill="#9ab391"/></svg>`;
function dashboard() {
  const rr = records(),
    todo = rr.filter((r) =>
      filter === "all"
        ? ["pending", "returned", "draft"].includes(r.status)
        : r.status === filter,
    );
  return (
    heading(
      role === "student"
        ? `${esc(actor())}，向下一程出发。`
        : "研究生培养工作台",
      "培养进展、审核待办与学生成长，在这里一目了然。",
      btn("导出概览", "export:overview", false, "download") +
        (role === "manager"
          ? btn("发布培养任务", "new-task", true, "plus")
          : role === "student"
            ? btn("竞赛获奖", "new-competition", false, "trophy") +
              btn("学术交流", "new-exchange", false, "globe") +
              btn("登记论文成果", "new-paper", true, "plus")
            : btn("Agent 审核", "navigate:reviews", true, "plus")),
    ) +
    `<section class="hero"><div class="hero-copy"><div class="eyebrow">EVERY STEP COUNTS</div><h2>每一份积累，都通向更远的未来</h2><p>当前有 ${tasks().length} 项培养任务，${pending().length} 份材料待审核。<br>关注研究进展，让审核有依据，让成长被看见。</p><button class="hero-link" data-page="tasks">查看本学年培养任务 ${icon("arrow", 15)}</button></div>${heroArt}<span class="hero-tag">GROWTH, WITH EVIDENCE.</span></section>${statCards()}<div class="dashboard-grid"><div class="stack" style="display:block"><section class="card"><div class="card-head"><h2>我的待办 <span class="badge amber">${todo.length} 项</span></h2><button class="linkbtn" data-page="${role === "student" ? "papers" : "reviews"}">查看全部 →</button></div><div class="tabs">${[
      ["all", "全部待办"],
      ["pending", "待 Agent 审核"],
      ["returned", "待补正"],
    ]
      .map(
        ([v, t]) =>
          `<button class="tab ${filter === v ? "active" : ""}" data-filter="${v}">${t}<span>${rr.filter((r) => (v === "all" ? ["pending", "returned", "draft"].includes(r.status) : r.status === v)).length}</span></button>`,
      )
      .join(
        "",
      )}</div>${recordTable(todo.slice(0, 4), true)}<div class="table-footer"><span>Agent 审核通过后自动归档，异常转交机构处理</span><span>显示 ${Math.min(todo.length, 4)} / ${todo.length}</span></div></section><section class="card" style="margin-top:22px"><div class="card-head"><div><h2>材料状态分布</h2><p>当前范围内全部材料 · 实时统计</p></div><div class="legend"><span><i style="background:#79a085"></i>材料数量</span></div></div><div class="chart">${distribution(rr)}</div></section></div><div class="stack"><section class="card"><div class="card-head"><h2>培养任务进度</h2><button class="linkbtn" data-page="tasks">全部 ↗</button></div><div class="progress-body">${
      tasks()
        .slice(0, 3)
        .map((t) => {
          const p = progress(t);
          return `<div class="progress-row"><div class="progress-top"><span>${esc(t.title)}</span><span>${p.percent}%</span></div><div class="progress-track"><i style="width:${p.percent}%"></i></div><div class="progress-meta"><span>已归档 ${p.done} / ${p.total} 人</span><span>${date(t.deadline)} 截止</span></div></div>`;
        })
        .join("") || empty("暂无培养任务")
    }</div></section><section class="card"><div class="card-head"><h2>值得关注</h2><span class="badge gray">培养提醒</span></div>${
      visibleAlerts()
        .filter((a) => a.status === "open")
        .slice(0, 3)
        .map(
          (a) =>
            `<div class="notice"><span class="notice-icon">${icon("bell")}</span><div><h3>${esc(student(a.student).name)} · ${esc(a.title)}</h3><p>${esc(a.text)}</p><button class="linkbtn" data-action="${a.automatic ? "warning" : "alert"}:${a.id}">查看并跟进 →</button></div></div>`,
        )
        .join("") ||
      '<div class="notice"><p>暂无待跟进提醒，培养工作有序进行。</p></div>'
    }<div class="notice"><span class="notice-icon" style="background:#edf5ff;color:#7596cc">${icon("shield")}</span><div><h3>让每项结论都有据可查</h3><p>画像用于辅助观察，不作为能力定论。</p></div></div></section></div></div>`
  );
}
function distribution(rr) {
  let max = Math.max(
    1,
    ...Object.keys(statusLabels).map(
      (s) => rr.filter((r) => r.status === s).length,
    ),
  );
  return `<svg viewBox="0 0 600 160" role="img" aria-label="材料状态数量柱状图">${[0, 1, 2, 3].map((i) => `<line x1="35" y1="${25 + i * 32}" x2="580" y2="${25 + i * 32}" stroke="#e6eaf1" stroke-dasharray="3 4"/>`).join("")}${Object.entries(
    statusLabels,
  )
    .map(([s, t], i) => {
      let n = rr.filter((r) => r.status === s).length,
        h = (n / max) * 85;
      return `<rect x="${65 + i * 110}" y="${120 - h}" width="64" height="${h}" rx="4" fill="${["#a4b2cd", "#ffb17b", "#e78b98", "#34b5a2", "#8a7bdc"][i]}"/><text x="${97 + i * 110}" y="${112 - h}" text-anchor="middle" fill="#68768b" font-size="11">${n}</text><text x="${97 + i * 110}" y="145" text-anchor="middle" fill="#8c96a5" font-size="11">${t}</text>`;
    })
    .join("")}</svg>`;
}
function listing(kind) {
  const kindRecords = records().filter((r) =>
    kind === "papers"
      ? r.kind === "paper"
      : kind === "competitions"
        ? r.kind === "competition"
        : kind === "exchanges"
          ? r.kind === "exchange"
          : kind === "archives"
            ? !!r.effective
            : role === "teacher"
              ? r.raw.reviewer_id === me.id
              : true,
  );
  let rr = kindRecords.filter(
    (r) =>
      (filter === "all" || r.status === filter) &&
      (kind !== "competitions" ||
        subFilter === "all" ||
        r.proofMode === subFilter) &&
      (kind !== "exchanges" ||
        subFilter === "all" ||
        r.participationMode === subFilter) &&
      (!query ||
        (
          r.title +
          " " +
          (r.searchText || "") +
          " " +
          student(r.student).name +
          " " +
          student(r.student).number
        )
          .toLowerCase()
          .includes(query.toLowerCase())),
  );
  const [title, subtitle, createAction] =
    {
      papers: [
        "论文成果",
        "记录每一次研究进展，保留成果事实与个人贡献。",
        role === "student" ? btn("登记论文", "new-paper", true, "plus") : "",
      ],
      competitions: [
        "竞赛与获奖",
        "登记竞赛名称、主办方、奖项、团队成员及本人角色，附证书或公示链接。",
        role === "student"
          ? btn("登记竞赛获奖", "new-competition", true, "plus")
          : "",
      ],
      exchanges: [
        "学术交流",
        "区分参会、作报告、展示海报及承担具体实践任务，上传对应证明材料。",
        role === "student"
          ? btn("登记学术交流", "new-exchange", true, "plus")
          : "",
      ],
      archives: [
        "成果档案",
        "正式认定与历史版本始终关联，更正期间原档案持续有效。",
        "",
      ],
    }[kind] || [
      "审核工作台",
      "从提交材料到正式归档，让每项审核有据可循。",
      "",
    ];
  const summaryStrip =
    kind === "competitions"
      ? `<div class="summary-strip">${[
          ["竞赛总数", kindRecords.length],
          ["已归档", kindRecords.filter((r) => r.effective).length],
          ["待审核", kindRecords.filter((r) => r.status === "pending").length],
          [
            "附证书附件",
            kindRecords.filter((r) =>
              ["certificate_only", "certificate_and_link"].includes(
                r.proofMode,
              ),
            ).length,
          ],
          [
            "附公示链接",
            kindRecords.filter((r) =>
              ["link_only", "certificate_and_link"].includes(r.proofMode),
            ).length,
          ],
        ]
          .map(
            ([label, count]) =>
              `<div class="summary-chip"><span>${label}</span><strong>${count}</strong></div>`,
          )
          .join("")}</div>`
      : kind === "exchanges"
        ? `<div class="summary-strip">${[
            ["交流总数", kindRecords.length],
            ...exchangeModeMeta.map((m) => [
              m.label,
              kindRecords.filter((r) => r.participationMode === m.value).length,
            ]),
          ]
            .map(
              ([label, count]) =>
                `<div class="summary-chip"><span>${esc(label)}</span><strong>${count}</strong></div>`,
            )
            .join("")}</div>`
        : "";
  const subTabs =
    kind === "competitions"
      ? `<div class="tabs sub-tabs">${[
          ["all", "全部证明方式"],
          ["certificate_and_link", "证书+公示链接"],
          ["certificate_only", "仅证书附件"],
          ["link_only", "仅公示链接"],
        ]
          .map(
            ([v, t]) =>
              `<button class="tab ${subFilter === v ? "active" : ""}" data-subfilter="${v}">${t}<span>${v === "all" ? kindRecords.length : kindRecords.filter((r) => r.proofMode === v).length}</span></button>`,
          )
          .join("")}</div>`
      : kind === "exchanges"
        ? `<div class="tabs sub-tabs">${[
            ["all", "全部方式"],
            ...exchangeModeMeta.map((m) => [m.value, m.label]),
          ]
            .map(
              ([v, t]) =>
                `<button class="tab ${subFilter === v ? "active" : ""}" data-subfilter="${v}">${esc(t)}<span>${v === "all" ? kindRecords.length : kindRecords.filter((r) => r.participationMode === v).length}</span></button>`,
            )
            .join("")}</div>`
        : "";
  return (
    heading(
      title,
      subtitle,
      btn("导出清单", "export:" + kind, false, "download") + createAction,
    ) +
    summaryStrip +
    `<section class="card">${subTabs}<div class="toolbar"><input id="list-query" aria-label="筛选材料" placeholder="搜索学生姓名、学号或材料标题" value="${esc(query)}"><select id="status-filter" aria-label="材料状态"><option value="all">全部状态</option>${Object.entries(
      statusLabels,
    )
      .map(
        ([v, t]) =>
          `<option value="${v}" ${filter === v ? "selected" : ""}>${t}</option>`,
      )
      .join(
        "",
      )}</select>${btn("查询", "search-list", true, "search")}</div>${recordTable(rr.slice((pageNum - 1) * 6, pageNum * 6))}<div class="table-footer"><span>共 ${rr.length} 条记录 · 当前角色：${roleName()}</span><div class="pagers">${Array.from({ length: Math.max(1, Math.ceil(rr.length / 6)) }, (_, i) => `<button data-pager="${i + 1}" class="${pageNum === i + 1 ? "active" : ""}">${i + 1}</button>`).join("")}</div></div></section>${kind === "archives" ? correctionPanel() : ""}`
  );
}
function correctionPanel() {
  const cc = state.corrections.filter((c) =>
    records().some((r) => r.id === c.record),
  );
  return cc.length
    ? `<section class="card" style="margin-top:22px"><div class="card-head"><h2>档案更正申请</h2></div>${cc.map((c) => `<div class="notice" style="justify-content:space-between"><div><h3>${esc(state.records.find((r) => r.id === c.record).title)}</h3><p>${esc(c.reason)} · ${esc(c.status)}</p></div>${role === "manager" && c.status === "待处理" ? btn("处理申请", "handle-correction:" + c.id) : ""}</div>`).join("")}</section>`
    : "";
}
function taskView() {
  return (
    heading(
      "培养任务",
      "围绕培养节点发布要求，跟踪应交名单与材料进展。",
      role === "manager" ? btn("发布培养任务", "new-task", true, "plus") : "",
    ) +
    `<div class="task-grid">${tasks()
      .map((t) => {
        const p = progress(t);
        return `<section class="card task-card"><div class="tagline"><span class="badge">${new Date(t.deadline) < new Date() ? "已截止" : "进行中"}</span><small>${esc(t.period)} 学年</small></div><h2>${esc(t.title)}</h2><p>${icon("calendar", 13)} &nbsp;截止日期 ${esc(date(t.deadline))}</p><p style="margin-top:7px">${icon("shield", 13)} &nbsp;${esc(t.template)}</p><div class="mini-progress"><div class="progress-top"><span>材料归档进度</span><span>${p.done} / ${p.total}</span></div><div class="progress-track"><i style="width:${p.percent}%"></i></div></div><div class="task-bottom"><small>复核教师 ${esc(t.reviewer)}</small><button class="linkbtn" data-action="task:${t.id}">${role === "student" ? "填写报告" : "查看任务"} →</button></div></section>`;
      })
      .join("")}</div>` +
    (tasks().length ? "" : empty("暂无任务"))
  );
}
function studentsView() {
  const ss = visibleStudents().filter((s) =>
    (s.name + s.number + s.major).includes(query),
  );
  return (
    heading(
      "学生管理",
      "学生主档、导师关系与研究方向，汇聚到同一份成长记录。",
      role === "manager"
        ? btn("导入名单", "import", false, "download") +
            btn("新增学生", "new-student", true, "plus")
        : "",
    ) +
    `<section class="card" style="margin-bottom:20px"><div class="toolbar"><input id="list-query" aria-label="搜索学生" placeholder="搜索姓名、学号或专业" value="${esc(query)}">${btn("查询", "search-list", true, "search")}</div></section><div class="student-grid">${ss.map((s) => `<section class="card"><div class="profile-head"><span class="avatar">${esc(s.name.replace(/（模拟）$/, "").slice(-2))}</span><div><h2>${esc(s.name)}</h2><small>${esc(s.number)} · ${esc(s.year)}${s.degree && s.degree !== "未标注" ? " · " + esc(s.degree) : ""}</small></div></div><div class="profile-body"><p>${esc(s.major)} <span class="badge gray">${esc(s.stage)}</span></p><p class="muted" style="margin-top:12px">研究方向 · ${esc(s.direction)}<br>指导教师 · ${esc(s.teacher)}</p><div class="task-bottom"><small>${records().filter((r) => r.student === s.id && r.effective).length} 份已归档材料</small><div class="actions">${role === "manager" ? btn("编辑资料", "profile:" + s.id) : ""}<button class="linkbtn" data-action="student:${s.id}">查看学生档案 →</button></div></div></div></section>`).join("")}</div>` +
    (ss.length ? "" : empty("未找到学生"))
  );
}
const visibleAlerts = () =>
  [
    ...warningsData
      .filter((w) => ["open", "tracking"].includes(w.status))
      .map((w) => ({ ...w, status: "open", automatic: true })),
    ...state.alerts,
  ].filter((a) => visibleStudents().some((s) => s.id === a.student));
function alertsView() {
  return renderWarnings({
    warnings: warningsData,
    esc,
    icon,
    btn,
    heading,
    role,
    filter,
    query,
    student,
    manualAlerts: state.alerts,
  });
}
function rulesView() {
  return (
    heading(
      "规则与模板",
      "发布即冻结；新版本仅作用于此后创建的任务。",
      role === "manager" ? btn("发布规则新版本", "new-rule", true, "plus") : "",
    ) +
    `<div class="callout">规则发布后写入服务器并冻结。新任务引用所选版本，正式提交时由后端校验必填项；历史任务与快照保持原版本。</div><div class="task-grid">${[
      ...state.rules,
    ]
      .reverse()
      .map(
        (r) =>
          `<section class="card task-card"><div class="tagline"><span class="badge">${esc(r.id.slice(0, 12))}</span><small>${esc(r.date)}</small></div><h2>${esc(r.title)}</h2><p>${esc(r.content)}</p><div class="task-bottom"><small>已发布 · 不可覆盖</small><button class="linkbtn" data-action="rule:${r.id}">查看要求 →</button></div></section>`,
      )
      .join("")}</div>`
  );
}
function logsView() {
  return (
    heading(
      "操作记录",
      "查看当前授权范围内的服务器审计记录，最近 1000 条可导出。",
      btn("导出记录", "export:logs", false, "download"),
    ) +
    `<section class="card"><div class="table-wrap"><table><thead><tr><th>操作时间</th><th>操作人</th><th>操作内容</th></tr></thead><tbody>${state.logs
      .slice(0, 100)
      .map(
        (l) =>
          `<tr><td>${esc(l.time)}</td><td>${esc(l.actor)}</td><td style="white-space:normal">${esc(l.action)}</td></tr>`,
      )
      .join("")}</tbody></table></div></section>`
  );
}
const views = {
  dashboard,
  students: studentsView,
  tasks: taskView,
  reviews: agentReviewView,
  papers: () => listing("papers"),
  competitions: () => listing("competitions"),
  exchanges: () => listing("exchanges"),
  archives: () => listing("archives"),
  portraits,
  alerts: alertsView,
  rules: rulesView,
  logs: logsView,
  settings: settingsView,
};
function modal(title, body, foot = "") {
  const d = $("#dialog");
  d.innerHTML = `<div class="dialog-head"><h2 id="dialog-title">${esc(title)}</h2><button class="close" data-close aria-label="关闭">×</button></div><div class="dialog-body">${body}</div>${foot ? `<div class="dialog-foot">${foot}</div>` : ""}`;
  if (!d.open) d.showModal();
  d.querySelectorAll("[data-close]").forEach(
    (b) => (b.onclick = () => d.close()),
  );
  bind(d);
}
function formModal(title, fields, save, submit = "保存") {
  modal(
    title,
    `<form id="modal-form"><div class="form-grid">${fields}</div><div style="display:flex;justify-content:flex-end;gap:10px;margin-top:25px"><button type="button" class="btn" data-close>取消</button><button class="btn primary">${submit}</button></div></form>`,
  );
  $("#modal-form").onsubmit = async (e) => {
    e.preventDefault();
    const b = e.submitter;
    b.disabled = true;
    try {
      const result = await save(new FormData(e.target));
      $("#dialog").close();
      await refresh().catch(showError);
      if (result?.created) credentialsDialog(result.created);
      if (result?.openEdit) await editRecord({ id: result.openEdit });
    } catch (err) {
      toast(err.message);
    } finally {
      b.disabled = false;
    }
  };
}
const degreeSelect = (value) =>
  `<label>培养层次<select name="degree">${["未标注", "博士", "硕士"].map((v) => `<option value="${v}" ${value === v ? "selected" : ""}>${v}</option>`).join("")}</select></label>`;
const field = (label, name, value = "", type = "text", full = false) =>
    `<label class="${full ? "full" : ""}">${label}<input type="${type}" name="${name}" value="${esc(value)}" required></label>`,
  area = (label, name, value = "", required = true) =>
    `<label class="full">${label}<textarea name="${name}" ${required ? "required" : ""}>${esc(value)}</textarea></label>`;
function taskDialog(t) {
  const ids = t.students.filter((s) =>
    visibleStudents().some((v) => v.id === s),
  );
  modal(
    t.title,
    `<div class="callout">${esc(t.period)} 学年 · ${esc(date(t.deadline))} 截止 · ${esc(t.template)}</div><p>复核教师：${esc(t.reviewer)}。请提交研究进展、下一阶段计划及证明材料。</p><h3 style="margin:20px 0">应交名单与当前进度</h3><div class="table-wrap"><table><thead><tr><th>学生</th><th>当前状态</th><th>操作</th></tr></thead><tbody>${ids
      .map((sid) => {
        const r = state.records.find(
          (r) => r.task === t.id && r.student === sid,
        );
        return `<tr><td>${person(sid)}</td><td>${r ? badge(r.status) : '<span class="badge gray">未提交</span>'}</td><td>${r ? `<button class="linkbtn" data-action="record:${r.id}">查看材料</button>` : role === "student" ? btn("开始填写", "start-task:" + t.id, true) : btn("添加提醒", "remind:" + t.id + ":" + sid)}</td></tr>`;
      })
      .join("")}</tbody></table></div>`,
  );
}
function download(name, data, type = "application/json") {
  const blob =
    data instanceof Blob
      ? data
      : new Blob(
          [typeof data === "string" ? data : JSON.stringify(data, null, 2)],
          { type },
        );
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function parseCSV(text) {
  const rows = [];
  let row = [],
    cell = "",
    quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"') {
      if (quoted && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else quoted = !quoted;
    } else if (ch === "," && !quoted) {
      row.push(cell);
      cell = "";
    } else if ((ch === "\n" || ch === "\r") && !quoted) {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      if (row.some((v) => v.trim())) rows.push(row);
      row = [];
      cell = "";
    } else cell += ch;
  }
  if (quoted) throw Error("CSV 引号不完整");
  row.push(cell);
  if (row.some((v) => v.trim())) rows.push(row);
  return rows.map((r) => r.map((v) => v.trim().replace(/^\uFEFF/, "")));
}
function bind(root = document) {
  root.querySelectorAll("[data-page]").forEach(
    (b) =>
      (b.onclick = (e) => {
        e.preventDefault();
        $("#dialog").close();
        go(b.dataset.page).catch(showError);
      }),
  );
  root.querySelectorAll("[data-action]").forEach((b) => {
    b.type = "button";
    b.onclick = async () => {
      if (b.disabled) return;
      b.disabled = true;
      try {
        await action(b.dataset.action);
      } catch (e) {
        showError(e);
      } finally {
        b.disabled = false;
      }
    };
  });
  root.querySelectorAll("[data-filter]").forEach(
    (b) =>
      (b.onclick = () => {
        filter = b.dataset.filter;
        pageNum = 1;
        render();
      }),
  );
  root.querySelectorAll("[data-subfilter]").forEach(
    (b) =>
      (b.onclick = () => {
        subFilter = b.dataset.subfilter;
        pageNum = 1;
        render();
      }),
  );
  root.querySelectorAll("[data-pager]").forEach(
    (b) =>
      (b.onclick = () => {
        pageNum = +b.dataset.pager;
        render();
      }),
  );
  root
    .querySelectorAll("[data-close]")
    .forEach((b) => (b.onclick = () => $("#dialog").close()));
  if (root !== document) return;
  if ($("#status-filter"))
    $("#status-filter").onchange = (e) => {
      filter = e.target.value;
      pageNum = 1;
      render();
    };
  if ($("#list-query"))
    $("#list-query").onkeydown = (e) => {
      if (e.key === "Enter") action("search-list");
    };
  if ($("#growth-period"))
    $("#growth-period").onchange = (e) => {
      growthPeriod = e.target.value;
      refresh().catch(showError);
    };
  if ($("#portrait-student"))
    $("#portrait-student").onchange = (e) => {
      selectedStudent = e.target.value;
      growthTab = "personal";
      refresh().catch(showError);
    };
  $("#global-search").onsubmit = (e) => {
    e.preventDefault();
    const q = new FormData(e.target).get("q").trim();
    if (!q) return;
    const hits = [
      ...visibleStudents()
        .filter((s) => (s.name + s.number).includes(q))
        .map((s) => ({
          title: s.name + " · " + s.number,
          action: "student:" + s.id,
        })),
      ...records()
        .filter((r) => r.title.includes(q))
        .map((r) => ({ title: r.title, action: "record:" + r.id })),
      ...tasks()
        .filter((t) => t.title.includes(q))
        .map((t) => ({ title: t.title, action: "task:" + t.id })),
    ];
    modal(
      "搜索结果",
      `<div class="search-results">${hits.map((h) => `<button data-action="${h.action}">${esc(h.title)} <span style="float:right">↗</span></button>`).join("") || empty("没有找到匹配内容", "尝试学生姓名、学号或材料标题。")}</div>`,
    );
  };
}

function publishSession() {
  window.dispatchEvent(
    new CustomEvent("innograd:session", {
      detail: me ? { user: me, api } : null,
    }),
  );
}
async function api(path, options = {}) {
  options.signal?.throwIfAborted();
  const requestUser = me;
  const headers = { "X-CSRF-Token": csrf, ...options.headers };
  if (options.body && !(options.body instanceof FormData))
    headers["Content-Type"] = "application/json";
  if (options.method === "POST")
    headers["Idempotency-Key"] = options.key || id();
  let response;
  try {
    response = await fetch("/api/v1" + path, {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
      headers,
    });
  } catch {
    options.signal?.throwIfAborted();
    throw Error(
      "无法连接服务器。请检查服务状态；未确认成功的操作请先刷新核对。",
    );
  }
  const data = await response
    .json()
    .catch(() => ({ detail: "服务器返回格式错误" }));
  options.signal?.throwIfAborted();
  if (!response.ok) {
    if (response.status === 401 && me === requestUser) {
      me = null;
      csrf = "";
      publishSession();
      state = {
        students: [],
        records: [],
        tasks: [],
        alerts: [],
        rules: [],
        logs: [],
        corrections: [],
      };
      $("#dialog").close();
      loginView();
    }
    const error = new Error(
      typeof data.detail === "string"
        ? data.detail
        : Array.isArray(data.detail)
          ? data.detail.map((v) => v.msg).join("；")
          : "请求失败",
    );
    error.status = response.status;
    throw error;
  }
  return data;
}
const post = (p, b = {}) => api(p, { method: "POST", body: JSON.stringify(b) });
const patch = (p, b) => api(p, { method: "PATCH", body: JSON.stringify(b) });
const personName = (id) => people.find((p) => p.id === id)?.name || "未分配";
function normalize(r) {
  const v = r.versions.at(-1),
    editable =
      me.id === r.student_id && ["draft", "returned"].includes(r.status),
    form = editable
      ? r.draft?.form || {}
      : v?.snapshot.form || r.draft?.form || {},
    fileIds = editable
      ? r.draft?.file_ids || []
      : v?.snapshot.file_ids || r.draft?.file_ids || [];
  const effective = r.effective_archive
    ? {
        id: r.effective_archive.id,
        number: r.effective_archive.number,
        title:
          r.effective_archive.snapshot.form.title ||
          r.effective_archive.snapshot.form.competition_name ||
          r.effective_archive.snapshot.form.activity_name ||
          "年度报告",
        time: r.effective_archive.created_at,
      }
    : null;
  return {
    id: r.id,
    raw: r,
    student: r.student_id,
    task: r.task_id,
    kind: r.kind,
    status: r.status === "pending_review" ? "pending" : r.status,
    title:
      form.title ||
      form.competition_name ||
      form.activity_name ||
      kindMeta[r.kind]?.emptyTitle ||
      "未命名材料",
    summary: form.summary || "",
    plan: form.plan || "",
    contribution: form.contribution || "",
    authors: form.authors || [],
    authorOrder: form.author_order || "",
    authorIdentity: form.author_identity || "",
    publication: form.publication_status || "submitted",
    journal: form.journal || "",
    doi: form.doi || "",
    articleUrl: form.article_url || "",
    competitionName: form.competition_name || form.title || "",
    organizer: form.organizer || "",
    awardLevel: form.award_level || "",
    awardDate: form.award_date || "",
    teamMembers: form.team_members || [],
    myRole: form.my_role || "",
    proofMode:
      form.proof_mode ||
      (fileIds.length && form.publicity_url
        ? "certificate_and_link"
        : fileIds.length
          ? "certificate_only"
          : form.publicity_url
            ? "link_only"
            : ""),
    teamSize:
      form.team_size ||
      (Array.isArray(form.team_members) ? form.team_members.length : 0),
    dedupeKey:
      form.competition_key ||
      form.exchange_key ||
      form.external_article_key ||
      "",
    publicityUrl: form.publicity_url || "",
    description: form.description || "",
    activityName: form.activity_name || form.title || "",
    activityDate: form.activity_date || "",
    endDate: form.end_date || "",
    participationMode: form.participation_mode || "",
    locationOrOrganizer: form.location_or_organizer || "",
    presentationTitle: form.presentation_title || "",
    practiceTaskDescription: form.practice_task_description || "",
    participationSummary: form.participation_summary || "",
    referenceUrl: form.reference_url || "",
    searchText: [
      form.title,
      form.competition_name,
      form.organizer,
      form.award_level,
      form.my_role,
      form.activity_name,
      form.location_or_organizer,
      form.presentation_title,
      form.practice_task_description,
      form.journal,
      form.doi,
    ]
      .filter(Boolean)
      .join(" "),
    reviewer: personName(r.reviewer_id),
    effective,
    updated: v?.created_at || r.created_at,
    files: (r.files || []).filter((f) => fileIds.includes(f.id)),
    versions: r.versions,
    refs: v?.snapshot.references || [],
    history: [
      ...r.versions.map((v) => ({
        text: "学生正式提交 · V" + v.number,
        time: v.created_at,
      })),
      ...r.decisions.map((d) => ({
        text:
          (d.outcome === "approved"
            ? d.actor_type === "simulation"
              ? "模拟审核记录："
              : d.actor_type === "agent"
                ? "Agent 自动审核通过："
                : "机构审核通过："
            : "退回补正：") + d.opinion,
        time: d.created_at,
      })),
      ...r.reviewer_changes.map((c) => ({
        text: c.reason,
        time: c.created_at,
      })),
    ].sort((a, b) => a.time.localeCompare(b.time)),
  };
}
let growthCache = {},
  growthPeriod = "",
  growthTab = "personal",
  growthOverview = null,
  warningsData = [];
let refreshInFlight = null;
async function refresh() {
  if (!me) return loginView();
  const sessionUser = me;
  if (refreshInFlight) {
    await refreshInFlight.catch(() => {});
    if (me === sessionUser) return refresh();
    return;
  }
  refreshInFlight = (async () => {
    let all = [],
      offset = 0;
    while (true) {
      const part = await api("/submissions?offset=" + offset + "&limit=100");
      all.push(...part);
      if (part.length < 100) break;
      offset += 100;
    }
    const [pp, ss, tt, aa, rr, ll, cap, sys, queue, warnings] =
      await Promise.all([
        api("/people"),
        api("/students"),
        api("/me/tasks"),
        api("/alerts"),
        api("/rules"),
        api("/audit-logs"),
        api("/ai/capabilities"),
        api("/workspace/status"),
        api("/review-queue"),
        api("/warnings"),
      ]);
    if (me !== sessionUser) return;
    people = pp;
    capabilities = cap;
    systemStatus = sys;
    reviewQueue = queue;
    warningsData = warnings;
    state = {
      students: ss.map((s) => ({
        ...s,
        teacher: s.teachers.map((t) => t.name).join("、") || "待分配",
      })),
      records: all.map(normalize),
      tasks: tt.map((t) => ({
        ...t,
        students: t.student_ids,
        reviewer: personName(t.reviewer_id),
        template: "年度报告 · " + t.requirements.version,
      })),
      alerts: aa,
      rules: rr,
      logs: ll,
      corrections: all.flatMap((r) =>
        r.corrections.map((c) => ({
          ...c,
          record: r.id,
          status: {
            pending: "待处理",
            opened: "更正中",
            rejected: "已驳回",
            completed: "已完成",
          }[c.status],
        })),
      ),
    };
    if (!selectedStudent || !ss.some((s) => s.id === selectedStudent))
      selectedStudent = ss[0]?.id || "";
    if (page === "portraits" && selectedStudent) {
      portraitsCache[selectedStudent] = await api(
        "/students/" + selectedStudent + "/portrait",
      );
      growthCache[selectedStudent + "|" + growthPeriod] = await api(
        "/students/" +
          selectedStudent +
          "/growth" +
          (growthPeriod ? "?period=" + encodeURIComponent(growthPeriod) : ""),
      );
      if (growthTab === "cohort" && role !== "student")
        growthOverview = await api(
          "/growth-overview" +
            (growthPeriod ? "?period=" + encodeURIComponent(growthPeriod) : ""),
        );
    }
    if (me === sessionUser) render();
  })().finally(() => (refreshInFlight = null));
  return refreshInFlight;
}
function showError(e) {
  toast(e.message || String(e));
}
function loginView() {
  $("#app").innerHTML =
    `<div class="login-shell"><section class="login-art"><div class="brand"><span class="brandmark">iG</span><div class="brandname">InnoGrad<small>GRADUATE OS</small></div></div><div><div class="eyebrow">EVERY STEP COUNTS</div><h1>每一步成长，<br>都有据可循。</h1><p>连接研究进展、成果审核与培养档案，<br>让每一次积累成为下一程的起点。</p></div>${heroArt}<small>研究生全周期智能审核与管理系统</small></section><section class="login-panel"><div class="eyebrow">WELCOME BACK</div><h1>登录培养工作空间</h1><p class="muted" style="margin:13px 0 30px">使用已建立的业务账号，进入你的授权工作空间。</p><form id="auth-form" class="form-grid"><label class="full">账号<input name="username" autocomplete="username" required placeholder="请输入账号或学号"></label><label class="full">密码<input name="password" type="password" autocomplete="current-password" required placeholder="请输入登录密码"></label><button class="btn primary full" style="padding:14px">登录工作台 ${icon("arrow")}</button><p class="full" id="auth-error" role="alert" style="color:#b76850"></p></form><div class="callout" style="margin-top:25px">账号身份与数据范围由服务器校验。学生、导师和管理教师分别登录自己的账号。</div></section></div>`;
  $("#auth-form").onsubmit = async (e) => {
    e.preventDefault();
    const b = e.submitter;
    b.disabled = true;
    try {
      const result = await post(
        "/auth/login",
        Object.fromEntries(new FormData(e.target)),
      );
      me = result.user;
      csrf = result.csrf_token;
      role = me.role;
      page = location.hash.slice(1) || "dashboard";
      publishSession();
      await refresh();
    } catch (err) {
      if ($("#auth-error")) $("#auth-error").textContent = err.message;
      else showError(err);
    } finally {
      b.disabled = false;
    }
  };
}
function growthContext() {
  return {
    esc,
    icon,
    btn,
    heading,
    state,
    role,
    me,
    selectedStudent,
    data: growthCache[selectedStudent + "|" + growthPeriod],
    period: growthPeriod,
    tab: growthTab,
    overview: growthOverview,
    query,
  };
}
function portraits() {
  return renderGrowth(growthContext());
}
function settingsView() {
  return (
    heading(
      "系统设置",
      "查看当前身份、后台作业和真实服务接入状态。",
      btn("刷新状态", "refresh", false, "history"),
    ) +
    `<section class="card"><div class="detail-content"><div class="switch-row"><div><h3>当前登录身份</h3><p>${esc(actor())} · ${roleName()}。授权范围由服务端控制。</p></div>${btn("退出登录", "logout")}</div><div class="switch-row"><div><h3>Agent 与归档 Worker</h3><p>${systemStatus.worker_last_seen ? "最近心跳：" + esc(new Date(systemStatus.worker_last_seen).toLocaleString("zh-CN")) : "尚未收到 Worker 心跳，请启动后台处理进程。"}</p></div><span class="badge ${systemStatus.worker_online ? "" : "amber"}">${systemStatus.worker_online ? "运行中" : "无近期心跳"}</span></div><div class="switch-row"><div><h3>Agent 审核服务</h3><p>${!capabilities.model_configured ? "Agent 服务待配置。设置接口后可启动材料解析、规则与证据审核。" : "已配置 Agent / 模型适配器，执行状态以任务结果为准。"} 审核通过自动归档；异常进入机构处理队列。</p></div><span class="badge">${capabilities.model_configured ? esc(capabilities.mode) : "待配置"}</span></div><div class="switch-row"><div><h3>附件与业务存储</h3><p>材料与版本写入数据库；附件保存于服务端受控目录。单份上限 50 MB。</p></div><span class="badge">服务端持久化</span></div><div class="switch-row"><div><h3>业务数据导出</h3><p>归档清单由后台生成，下载前重新校验授权与有效期。</p></div>${btn("打开成果档案", "navigate:archives")}</div><div class="callout amber" style="margin-top:20px">学校统一认证、OCR 与真实模型服务需要校方配置。当前仅显示已经执行的结果，不生成模拟评分或模拟审核结论。</div></div></section>`
  );
}
function versionFields(kind, form) {
  if (!["paper", "competition", "exchange"].includes(kind))
    return `<pre>${esc(JSON.stringify(form, null, 2))}</pre>`;
  const fields = Object.entries(form)
    .filter(([key, value]) => Object.hasOwn(fieldLabels, key) && value)
    .map(
      ([key, value]) =>
        `<div><dt>${esc(fieldLabels[key])}</dt><dd>${esc(formatValue(value))}</dd></div>`,
    );
  return `<dl class="facts">${fields.join("")}</dl>`;
}
function findDuplicateRecords(r) {
  if (!r.dedupeKey) return [];
  return records().filter(
    (other) =>
      other.id !== r.id &&
      other.student === r.student &&
      other.kind === r.kind &&
      other.dedupeKey === r.dedupeKey,
  );
}
function recordDetailBody(r) {
  if (r.kind === "competition") {
    const memberChips =
      Array.isArray(r.teamMembers) && r.teamMembers.length
        ? `<div class="member-chips">${r.teamMembers
            .map(
              (m) =>
                `<span class="member-chip">${m.order ? `<em>${m.order}</em>` : ""}${esc(typeof m === "string" ? m : m.name)}${m.is_self ? "（本人）" : ""}</span>`,
            )
            .join("")}</div>`
        : "—";
    const teamTag = r.teamSize
      ? `${r.teamSize > 1 ? `团队赛 · ${r.teamSize} 人` : "个人赛 · 1 人"}`
      : "—";
    return `<dl class="facts"><div><dt>材料类别</dt><dd>竞赛与获奖</dd></div><div><dt>获奖等级</dt><dd><span class="award-pill">${esc(r.awardLevel || "—")}</span></dd></div><div><dt>主办方</dt><dd>${esc(r.organizer || "—")}</dd></div><div><dt>获奖日期</dt><dd>${esc(r.awardDate || "—")}</dd></div><div><dt>本人角色</dt><dd>${esc(r.myRole || "—")}</dd></div><div><dt>团队规模</dt><dd>${esc(teamTag)}</dd></div><div><dt>证明方式</dt><dd><span class="mode-pill mode-proof">${esc(proofModeLabels[r.proofMode] || "—")}</span></dd></div><div><dt>公示链接</dt><dd>${r.publicityUrl ? safeExternalLink(r.publicityUrl) : "未填写"}</dd></div><div class="full"><dt>团队成员</dt><dd>${memberChips}</dd></div></dl>${r.description ? `<h3>补充说明</h3><p style="white-space:pre-wrap;margin:12px 0;color:#70816c">${esc(r.description)}</p>` : ""}`;
  }
  if (r.kind === "exchange") {
    const modeLabel = exchangeModeLabels[r.participationMode] || "—";
    const portraitTarget =
      r.participationMode === "practice_task" ? "实践落地" : "学术交流";
    const dateRange = r.endDate
      ? `${r.activityDate} 至 ${r.endDate}`
      : r.activityDate || "—";
    return `<dl class="facts"><div><dt>材料类别</dt><dd>学术交流</dd></div><div><dt>参与方式</dt><dd><span class="mode-pill mode-${esc(r.participationMode || "attend")}">${esc(modeLabel)}</span> <span class="mode-pill mode-target">画像归入：${portraitTarget}</span></dd></div><div><dt>活动日期</dt><dd>${esc(dateRange)}</dd></div><div><dt>主办单位 / 地点</dt><dd>${esc(r.locationOrOrganizer || "—")}</dd></div>${r.presentationTitle ? `<div><dt>${r.participationMode === "talk" ? "报告题目" : "海报题目"}</dt><dd>${esc(r.presentationTitle)}</dd></div>` : ""}<div><dt>活动链接</dt><dd>${r.referenceUrl ? safeExternalLink(r.referenceUrl) : "—"}</dd></div></dl>${r.practiceTaskDescription ? `<h3>承担的具体实践任务</h3><p style="white-space:pre-wrap;margin:12px 0;color:#70816c">${esc(r.practiceTaskDescription)}</p>` : ""}${r.participationSummary ? `<h3>参与说明</h3><p style="white-space:pre-wrap;margin:12px 0;color:#70816c">${esc(r.participationSummary)}</p>` : ""}`;
  }
  return `<dl class="facts"><div><dt>材料类别</dt><dd>${r.kind === "paper" ? "论文成果" : "年度报告"}</dd></div><div><dt>当前状态</dt><dd>${r.kind === "paper" ? { submitted: "已投稿", accepted: "已录用", published: "已发表" }[r.publication] : esc(state.tasks.find((t) => t.id === r.task)?.period || "—")}</dd></div></dl><h3>${r.kind === "paper" ? "本人贡献" : "研究进展"}</h3><p style="white-space:pre-wrap;margin:12px 0;color:#70816c">${esc(r.kind === "paper" ? r.contribution : r.summary)}</p>${r.plan ? `<h3>下一阶段计划</h3><p>${esc(r.plan)}</p>` : ""}`;
}
async function showRecord(record) {
  const raw = await api("/submissions/" + record.id),
    r = normalize(raw),
    mine = me.id === raw.student_id,
    editable = mine && ["draft", "returned"].includes(raw.status),
    review =
      (role === "manager" ||
        (role === "teacher" && raw.reviewer_id === me.id)) &&
      raw.status === "pending_review";
  const job = raw.ai_jobs
      .filter((j) => j.version_id === raw.current_version_id)
      .at(-1),
    ai = job ? await api("/ai-jobs/" + job.id) : null;
  const canConfirm =
    review && (capabilities.workflow !== "agent" || ai?.institution_required);
  const duplicates = findDuplicateRecords(r);
  const duplicateBanner = duplicates.length
    ? `<div class="callout amber" style="margin-top:14px">检测到同学生存在 ${duplicates.length} 条相同标识的申报记录：${duplicates.map((d) => `<button class="linkbtn" data-action="record:${d.id}">${esc(d.title)}（${esc(statusLabels[d.status] || d.status)}）↗</button>`).join("、")}。</div>`
    : "";
  const conclusions = {
      compliant: "符合",
      non_compliant: "不符合",
      unable_to_determine: "无法判断",
      not_applicable: "不适用",
    },
    jobNames = {
      queued: "排队中",
      running: "执行中",
      succeeded: "已完成",
      failed: "失败",
      cancelled: "已取消",
    };
  modal(
    kindMeta[r.kind]?.detailTitle || "材料详情",
    `<div class="actions" style="margin-bottom:18px">${badge(r.status)}<span class="muted">${esc(student(r.student).name)} · ${esc(r.reviewer)}复核 · ${r.versions.length ? "V" + r.versions.length : "工作稿"}</span></div><h2>${esc(r.title)}</h2>${r.effective ? `<div class="callout" style="margin-top:17px">有效认定 V${r.effective.number} · ${esc(r.effective.title)} · ${date(r.effective.time)}。新版本归档前，此认定持续有效。</div>` : ""}${r.status === "approved" ? '<div class="callout amber" style="margin-top:17px">审核已通过，正在自动归档并更新画像。点击“刷新详情”查看真实处理状态。</div>' : ""}${duplicateBanner}${recordDetailBody(r)}${r.refs.length ? `<h3>引用成果</h3>${r.refs.map((ref) => `<div class="evidence">${esc(ref.form.title)} · ${ref.recognition === "archived" ? "已认定" : "待核验"}<small> · 固定版本 ${esc(ref.version_id.slice(0, 8))}</small></div>`).join("")}` : ""}<h3>证明材料</h3>${r.files.map((f) => `<div class="file"><span>${icon("paper", 15)} ${esc(f.name)} <small>${esc(allFileRoleLabels[f.role] || "其他证明材料")} · ${Math.ceil(f.size / 1024)} KB</small></span><button class="linkbtn" data-action="file:${f.id}">下载原件</button></div>`).join("") || (r.kind === "competition" && r.publicityUrl ? `<p class="muted">本次未上传证书附件，已提供公示链接：${safeExternalLink(r.publicityUrl)}</p>` : '<p class="muted">尚无附件。</p>')}<div class="evidence" style="margin-top:23px"><h4>${icon("spark")} Agent 材料审核 · ${ai?.result?.simulation ? "模拟报告 · 未调用真实 Agent" : !capabilities.model_configured ? "待配置" : ai ? esc(jobNames[ai.status] || ai.status) : "尚未启动"}</h4><p>${ai ? "运行模式：" + esc(ai.mode) : "正式提交后自动进入 Agent 审核队列。"} ${ai?.historical_only ? "此结果仅供历史参考。" : ""}</p>${ai?.institution_required ? `<div class="callout amber">已转交机构处理：${esc(ai.material_review.label)}</div>` : ""}${ai?.error ? `<p class="warn">${esc(ai.error)}</p>` : ""}${(ai?.result?.checks || []).map((c) => `<div style="border-top:1px solid #dfe8d9;margin-top:10px;padding-top:10px"><strong>${esc(conclusions[c.conclusion] || c.conclusion)} · ${esc(c.rule_id)}</strong><p>${esc(c.explanation)}</p>${c.suggestion ? `<p>建议：${esc(c.suggestion)}</p>` : ""}${(c.evidence || []).map((e) => `<blockquote>${esc(e.quote)}</blockquote><button class="linkbtn" data-action="file:${e.file_id}">原件 ${e.page_number ? "第 " + e.page_number + " 页" : "段落 " + esc(e.paragraph_id)}</button>`).join("")}${(c.limitations || []).map((l) => `<p class="muted">${esc(l)}</p>`).join("")}</div>`).join("")}<div class="actions" style="margin-top:12px">${raw.current_version_id ? btn(capabilities.model_configured ? "启动 / 重试 Agent" : "查看 Agent 配置", "ai:" + r.id) : ""}${ai && ["queued", "running"].includes(ai.status) ? btn("取消 Agent 任务", "cancel-ai:" + ai.id + ":" + r.id) : ""}${btn("刷新详情", "record:" + r.id)}</div></div>${canConfirm ? `<h3 style="margin-top:20px">机构异常处理意见</h3><textarea id="opinion" aria-label="机构异常处理意见" style="width:100%;margin:12px 0" placeholder="填写复核依据或明确的补正要求"></textarea><label style="display:flex;gap:8px;margin-bottom:15px"><input id="confirm-evidence" type="checkbox">我已核对异常项与原件，确认此次处理意见</label><div class="actions">${btn("退回补正", "decide:" + r.id + ":returned")}${btn("异常核验通过并归档", "decide:" + r.id + ":approved", true, "check")}</div>` : ""}<h3 style="margin-top:25px">流转记录</h3><div class="timeline">${r.history.map((h) => `<div class="timeline-item"><p>${esc(h.text)}</p><small>${esc(new Date(h.time).toLocaleString("zh-CN"))}</small></div>`).join("")}</div><div class="version-list">${[
      ...r.versions,
    ]
      .reverse()
      .map(
        (v) =>
          `<details><summary>冻结版本 V${v.number} · ${date(v.created_at)}</summary>${versionFields(r.kind, v.snapshot.form)}${v.snapshot.file_ids.map((fid) => `<button class="linkbtn" data-action="file:${fid}">下载原件 · ${esc(raw.files.find((f) => f.id === fid)?.name || fid)} · ${esc(allFileRoleLabels[raw.files.find((f) => f.id === fid)?.role] || "其他证明材料")}</button><br>`).join("")}</details>`,
      )
      .join("")}</div>`,
    `${editable ? btn("编辑材料", "edit:" + r.id, true) : ""}${mine && r.status === "archived" && r.kind === "paper" ? btn("更新论文进展", "update:" + r.id) : ""}${r.effective ? btn("生成归档导出", "export-record:" + r.id) : ""}${r.status === "archived" ? btn("申请更正", "correct:" + r.id) : ""}${role === "manager" && ["pending", "returned"].includes(r.status) ? btn("调整复核教师", "reassign:" + r.id) : ""}<button class="btn" data-close>关闭</button>`,
  );
  $("#dialog").dataset.record = JSON.stringify({
    id: r.id,
    lock: raw.lock_version,
    version: raw.current_version_id,
  });
}
window.addEventListener("innograd:open-submission", (event) => {
  const submissionId = event.detail?.submissionId;
  if (!/^[A-Za-z0-9-]+$/.test(submissionId || "")) return;
  showRecord({ id: submissionId }).catch(showError);
});
window.addEventListener("innograd:open-portrait", (event) => {
  const studentId = event.detail?.studentId;
  if (!/^[A-Za-z0-9-]+$/.test(studentId || "")) return;
  selectedStudent = studentId;
  growthTab = "personal";
  growthPeriod = "";
  go("portraits").catch(showError);
});
async function editRecord(record) {
  const raw = await api("/submissions/" + record.id);
  if (raw.student_id !== me.id || !["draft", "returned"].includes(raw.status))
    throw Error("当前记录不可编辑");
  const form = raw.draft?.form || {},
    isPaper = raw.kind === "paper",
    isCompetition = raw.kind === "competition",
    isExchange = raw.kind === "exchange",
    task = state.tasks.find((t) => t.id === raw.task_id),
    required = task?.requirements.required_fields || ["summary"],
    roleOptions = fileRoleLabelsByKind[raw.kind] || paperFileRoleLabels;
  let lock = raw.lock_version,
    files = [
      ...(raw.files || []).filter((f) => raw.draft.file_ids.includes(f.id)),
    ],
    fileRoles = { ...(raw.draft.file_roles || {}) },
    customizedRoles = new Set(Object.keys(raw.draft.file_roles || {})),
    uploading = false;
  const activeExchangeMode = () =>
    $("#edit-form input[name='participation_mode']:checked")?.value ||
    form.participation_mode ||
    "attend";
  const defaultFileRole = () =>
    isCompetition
      ? "award_certificate"
      : isExchange
        ? exchangeModeFileRoles[activeExchangeMode()] || "attendance_proof"
        : "other_proof";
  const selectedExchangeMode = form.participation_mode || "attend";
  const formBody = isPaper
    ? field("材料标题", "title", form.title || "", "text", true) +
      `<label>论文状态<select name="publication_status">${[
        ["submitted", "已投稿"],
        ["accepted", "已录用"],
        ["published", "已发表"],
      ]
        .map(
          ([v, t]) =>
            `<option value="${v}" ${form.publication_status === v ? "selected" : ""}>${t}</option>`,
        )
        .join(
          "",
        )}</select></label><label>期刊 / 会议（选填）<input name="journal" value="${esc(form.journal || "")}"></label>${[
        ["submission_date", "投稿日期"],
        ["acceptance_date", "录用日期"],
        ["publication_date", "发表日期"],
      ]
        .map(
          ([n, l]) =>
            `<label>${l}<input name="${n}" type="date" value="${esc(form[n] || "")}"></label>`,
        )
        .join(
          "",
        )}<label class="full">作者列表（按作者顺序，每行一名）<textarea name="authors" required rows="3" placeholder="张三\n李四">${esc(authorNames(form.authors))}</textarea></label><label>本人作者顺序<input name="author_order" type="number" min="1" required value="${esc(form.author_order || "")}"></label><label>本人身份<select name="author_identity" required><option value="">请选择</option>${[
        ["first_author", "第一作者"],
        ["co_first_author", "共同第一作者"],
        ["corresponding_author", "通讯作者"],
        ["other_author", "其他作者"],
      ]
        .map(
          ([v, t]) =>
            `<option value="${v}" ${form.author_identity === v ? "selected" : ""}>${t}</option>`,
        )
        .join(
          "",
        )}</select></label><label>DOI（选填）<input name="doi" value="${esc(form.doi || "")}" placeholder="10.xxxx/xxxxx"></label><label>文章链接（DOI 或链接至少填一项）<input name="article_url" type="url" value="${esc(form.article_url || "")}" placeholder="https://..."></label>${area("本人贡献", "contribution", form.contribution || "")}`
    : isCompetition
      ? field("竞赛名称", "competition_name", form.competition_name || form.title || "", "text", true) +
        field("主办方", "organizer", form.organizer || "") +
        `<label>奖项（可选预设或自由输入）<input name="award_level" list="award-level-presets" value="${esc(form.award_level || "")}" placeholder="如：国家级一等奖" required></label><datalist id="award-level-presets"><option value="国家级特等奖"><option value="国家级一等奖"><option value="国家级二等奖"><option value="国家级三等奖"><option value="省级一等奖"><option value="省级二等奖"><option value="校级一等奖"></datalist>` +
        field("获奖日期", "award_date", form.award_date || "", "date") +
        `<label>本人角色（可选预设或自由输入）<input name="my_role" list="competition-role-presets" value="${esc(form.my_role || "")}" placeholder="如：队长 / 核心算法" required></label><datalist id="competition-role-presets"><option value="队长"><option value="核心成员"><option value="算法设计与实现"><option value="系统研发与测试"><option value="实验与数据分析"><option value="独立参赛"></datalist>` +
        `<label class="full">团队成员（按顺序列出，每行或逗号分隔一名）<textarea name="team_members" required rows="3" placeholder="张三\n李四">${esc(memberNames(form.team_members))}</textarea><small class="form-hint" id="competition-member-count"></small></label><label class="full">公示链接（上传证书或填写公示链接至少提供一项）<input name="publicity_url" type="url" value="${esc(form.publicity_url || "")}" placeholder="https://..."></label><div class="full proof-status" id="competition-proof-status"></div>${area("补充说明（选填）", "description", form.description || "", false)}`
      : isExchange
        ? `<div class="full"><span class="field-heading">参与方式（请严格区分）</span><div class="mode-cards">${exchangeModeMeta
            .map(
              (m) =>
                `<label class="mode-card ${selectedExchangeMode === m.value ? "active" : ""}"><input type="radio" name="participation_mode" value="${m.value}" ${selectedExchangeMode === m.value ? "checked" : ""} required><div><strong>${esc(m.label)}</strong><small>${esc(m.summary)}</small><span class="mode-target">画像归入：${esc(m.portraitTarget)}</span></div></label>`,
            )
            .join("")}</div><div class="callout" id="exchange-mode-guide" style="margin-top:10px"></div></div><label class="full"><span id="exchange-name-label">${selectedExchangeMode === "practice_task" ? "实践项目名称" : "会议 / 学术活动名称"}</span><input name="activity_name" value="${esc(form.activity_name || form.title || "")}" required></label><label class="full">主办单位 / 地点（选填）<input name="location_or_organizer" value="${esc(form.location_or_organizer || "")}" placeholder="如：华东师范大学 · 上海"></label>${field("活动 / 开始日期", "activity_date", form.activity_date || "", "date")}<label>结束日期（选填）<input name="end_date" type="date" value="${esc(form.end_date || "")}"></label><label id="exchange-presentation-wrap" class="full"><span id="exchange-presentation-label">${selectedExchangeMode === "talk" ? "报告题目" : "海报题目"}</span><input id="exchange-presentation-input" name="presentation_title" value="${esc(form.presentation_title || "")}" placeholder="作报告或展示海报时必填"></label><label id="exchange-practice-wrap" class="full">承担的具体实践任务<textarea id="exchange-practice-input" name="practice_task_description" rows="3" placeholder="承担具体实践任务时必填，说明具体任务分工与交付内容">${esc(form.practice_task_description || "")}</textarea></label><label class="full">活动 / 会议链接（选填）<input name="reference_url" type="url" value="${esc(form.reference_url || "")}" placeholder="https://..."></label>${area("参与说明（选填）", "participation_summary", form.participation_summary || "", false)}`
        : field("材料标题", "title", form.title || task?.title || "", "text", true) +
          `${task?.requirements.instructions ? `<div class="full callout">${esc(task.requirements.instructions)}</div>` : ""}${area("研究进展与总结", "summary", form.summary || "")}${area("下一阶段计划" + (required.includes("plan") ? "（必填）" : "（选填）"), "plan", form.plan || "", required.includes("plan"))}<div class="full"><p>引用本人已提交论文（待核验成果会明确标记）</p><div class="checklist">${
            records()
              .filter((p) => p.kind === "paper" && p.raw.current_version_id)
              .map(
                (p) =>
                  `<label><input type="checkbox" name="reference_ids" value="${p.id}" ${(raw.draft.reference_ids || []).includes(p.id) ? "checked" : ""}>${esc(p.effective?.title || p.title)} · ${p.effective ? "已认定" : "待核验"}</label>`,
              )
              .join("") || "<small>暂无可引用论文</small>"
          }</div></div>`;
  const uploadPrompt = isCompetition
    ? "证明材料（获奖证书 PDF / DOCX / JPG / PNG，与公示链接至少提供一项，单份 ≤ 50 MB）"
    : isExchange
      ? "参与证明材料（参会 / 报告 / 海报 / 实践任务证明，PDF / DOCX / JPG / PNG，单份 ≤ 50 MB）"
      : "证明材料（PDF / DOCX / JPG / PNG，单份 ≤ 50 MB）";
  modal(
    kindMeta[raw.kind]?.editTitle || "编辑材料",
    `<form id="edit-form"><div class="form-grid">${formBody}<label class="full">${uploadPrompt}<input type="file" id="attachments" multiple accept=".pdf,.docx,.jpg,.jpeg,.png"></label><div class="full" id="attached"></div></div><div class="actions" style="justify-content:flex-end;margin-top:22px"><button type="button" class="btn" data-close>取消</button><button class="btn" value="draft" formnovalidate>保存草稿</button><button class="btn primary" value="submit">确认并提交</button></div></form>`,
  );
  const syncCompetitionHints = () => {
    if (!isCompetition) return;
    const membersText =
      $("#edit-form textarea[name='team_members']")?.value || "";
    const memberCount = membersText
      .split(/[\r\n,，、]+/)
      .map((n) => n.trim())
      .filter(Boolean).length;
    const countNode = $("#competition-member-count");
    if (countNode) {
      countNode.textContent = memberCount
        ? `当前已识别 ${memberCount} 名成员 · ${memberCount > 1 ? "团队赛" : "个人赛"}`
        : "尚未填写成员（支持换行、逗号或顿号分隔）";
    }
    const urlVal =
      $("#edit-form input[name='publicity_url']")?.value.trim() || "";
    const statusNode = $("#competition-proof-status");
    if (statusNode) {
      const hasFiles = files.length > 0;
      const hasUrl = Boolean(urlVal);
      statusNode.className = `full proof-status ${hasFiles || hasUrl ? "ok" : "warn"}`;
      statusNode.textContent =
        hasFiles && hasUrl
          ? `已上传 ${files.length} 份附件并填写公示链接（完整双证）`
          : hasFiles
            ? `已上传 ${files.length} 份证明附件（满足提交条件）`
            : hasUrl
              ? "已填写公示链接（未上传附件时，提交后将由教师人工核对链接）"
              : "请至少上传一份获奖证书附件，或填写有效的公示链接";
    }
  };
  const renderFiles = () => {
    const fallbackRole = defaultFileRole();
    $("#attached").innerHTML = files
      .map((f) => {
        const activeRole = Object.hasOwn(roleOptions, fileRoles[f.id])
          ? fileRoles[f.id]
          : fallbackRole;
        return `<div class="file"><span>${esc(f.name)}</span><label class="file-role">材料类型<select data-role="${f.id}">${Object.entries(roleOptions).map(([value, label]) => `<option value="${value}" ${activeRole === value ? "selected" : ""}>${label}</option>`).join("")}</select></label><button type="button" class="linkbtn" data-remove="${f.id}">移除关联</button></div>`;
      })
      .join("");
    $("#attached")
      .querySelectorAll("[data-role]")
      .forEach((select) => {
        select.onchange = () => {
          customizedRoles.add(select.dataset.role);
          fileRoles[select.dataset.role] = select.value;
        };
      });
    $("#attached")
      .querySelectorAll("[data-remove]")
      .forEach(
        (b) =>
          (b.onclick = () => {
            files = files.filter((f) => f.id !== b.dataset.remove);
            renderFiles();
          }),
      );
    syncCompetitionHints();
  };
  const syncExchangeMode = () => {
    if (!isExchange) return;
    const mode = activeExchangeMode();
    const meta =
      exchangeModeMeta.find((item) => item.value === mode) ||
      exchangeModeMeta[0];
    const needPresentation = mode === "talk" || mode === "poster";
    const needPractice = mode === "practice_task";
    $("#exchange-name-label").textContent =
      mode === "practice_task" ? "实践项目名称" : "会议 / 学术活动名称";
    $("#exchange-mode-guide").textContent =
      `${meta.proofHint}（归档后将归入成长画像「${meta.portraitTarget}」维度）。`;
    $("#exchange-presentation-wrap").hidden = !needPresentation;
    $("#exchange-presentation-input").required = needPresentation;
    $("#exchange-presentation-label").textContent =
      mode === "talk" ? "报告题目" : "海报题目";
    $("#exchange-practice-wrap").hidden = !needPractice;
    $("#exchange-practice-input").required = needPractice;
    $("#edit-form")
      .querySelectorAll(".mode-card")
      .forEach((card) => {
        const input = card.querySelector("input[type='radio']");
        card.classList.toggle("active", Boolean(input?.checked));
      });
  };
  if (isCompetition) {
    $("#edit-form textarea[name='team_members']")?.addEventListener(
      "input",
      syncCompetitionHints,
    );
    $("#edit-form input[name='publicity_url']")?.addEventListener(
      "input",
      syncCompetitionHints,
    );
    syncCompetitionHints();
  }
  if (isExchange) {
    syncExchangeMode();
    $("#edit-form")
      .querySelectorAll("input[name='participation_mode']")
      .forEach((radio) => {
        radio.onchange = () => {
          const nextDefault =
            exchangeModeFileRoles[activeExchangeMode()] || "attendance_proof";
          for (const f of files) {
            if (!customizedRoles.has(f.id)) fileRoles[f.id] = nextDefault;
          }
          syncExchangeMode();
          renderFiles();
        };
      });
  }
  renderFiles();
  $("#attachments").onchange = async (e) => {
    uploading = true;
    const buttons = $("#edit-form").querySelectorAll("button");
    buttons.forEach((b) => (b.disabled = true));
    try {
      for (const f of e.target.files) {
        const data = new FormData();
        data.append("file", f);
        files.push(
          await api("/submissions/" + raw.id + "/files", {
            method: "POST",
            body: data,
          }),
        );
      }
      toast("上传完成，请保存草稿或正式提交");
    } catch (e) {
      showError(e);
    } finally {
      uploading = false;
      e.target.value = "";
      buttons.forEach((b) => (b.disabled = false));
      renderFiles();
    }
  };
  $("#edit-form").onsubmit = async (e) => {
    e.preventDefault();
    if (uploading) return;
    const b = e.submitter;
    b.disabled = true;
    try {
      const data = new FormData(e.target),
        values = Object.fromEntries(data);
      delete values.reference_ids;
      if (isPaper) {
        values.paper_metadata_version = 2;
        values.authors = String(values.authors || "")
          .split(/[\r\n,，、]+/)
          .map((name) => name.trim())
          .filter(Boolean)
          .map((name, index) => ({ name, order: index + 1 }));
        values.author_order = Number(values.author_order);
      } else if (isCompetition) {
        values.competition_metadata_version = 1;
        values.title = values.competition_name;
        values.team_members = String(values.team_members || "")
          .split(/[\r\n,，、]+/)
          .map((name) => name.trim())
          .filter(Boolean)
          .map((name, index) => ({ name, order: index + 1 }));
      } else if (isExchange) {
        values.exchange_metadata_version = 1;
        values.title = values.activity_name;
        if (!["talk", "poster"].includes(values.participation_mode))
          values.presentation_title = "";
        if (values.participation_mode !== "practice_task")
          values.practice_task_description = "";
      }
      if (b.value === "submit") {
        if (
          isCompetition &&
          !files.length &&
          !String(values.publicity_url || "").trim()
        )
          throw Error(
            "竞赛与获奖申报需上传证书等证明附件，或填写有效的公示链接（至少提供一项）",
          );
        if (isExchange) {
          if (values.end_date && values.end_date < values.activity_date)
            throw Error("结束日期不能早于活动日期");
          if (!files.length)
            throw Error("学术交流申报至少需要上传一份参与证明附件");
        }
      }
      const fallbackRole = defaultFileRole();
      const result = await patch("/submissions/" + raw.id + "/draft", {
        expected_lock_version: lock,
        form: values,
        file_ids: files.map((f) => f.id),
        file_roles: Object.fromEntries(
          files.map((f) => [
            f.id,
            Object.hasOwn(roleOptions, fileRoles[f.id])
              ? fileRoles[f.id]
              : fallbackRole,
          ]),
        ),
        reference_ids: data.getAll("reference_ids"),
      });
      lock = result.lock_version;
      if (b.value === "submit")
        await post("/submissions/" + raw.id + "/submit", {
          expected_lock_version: lock,
        });
      $("#dialog").close();
      await refresh();
      toast(
        b.value === "submit"
          ? "已正式提交，材料审核任务已创建，请查看 Agent 状态"
          : "草稿已保存到服务器",
      );
    } catch (e) {
      showError(e);
    } finally {
      b.disabled = false;
    }
  };
}
async function downloadFile(url, name) {
  const response = await fetch(url, {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) {
    let data = await response.json().catch(() => ({}));
    throw Error(data.detail || "下载失败，请重新登录或刷新");
  }
  download(name, await response.blob());
}
async function exportArchive(ids) {
  if (!ids.length) throw Error("当前没有可导出的有效档案");
  if (ids.length > 100)
    throw Error("单次最多导出 100 份，请使用档案详情逐份导出");
  const job = await post("/exports", { submission_ids: ids });
  await exportStatus(job.id);
}
async function exportStatus(ident) {
  const job = await api("/exports/" + ident);
  modal(
    "归档清单导出",
    `<div class="callout">${esc({ queued: "后台正在排队", running: "正在生成", succeeded: "导出已就绪", failed: "导出失败" }[job.status] || job.status)}</div><p>任务 ${esc(ident)}<br>有效期至 ${esc(new Date(job.expires_at).toLocaleString("zh-CN"))}</p>${job.error ? `<p class="warn">${esc(job.error)}</p>` : ""}`,
    job.status === "succeeded"
      ? btn("下载归档清单", "download-export:" + ident, true, "download")
      : btn("刷新导出状态", "export-status:" + ident, true),
  );
}
function credentialsDialog(rows) {
  modal(
    "学生账号已创建",
    `<div class="callout amber">初始密码仅在本次返回中显示，请妥善交付学生。刷新页面后无法再次查看。</div><div class="table-wrap"><table><thead><tr><th>姓名</th><th>账号</th><th>初始密码</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${esc(r.name)}</td><td>${esc(r.username)}</td><td><code>${esc(r.initial_password)}</code></td></tr>`).join("")}</tbody></table></div>`,
    '<button class="btn" data-close>已记录并关闭</button>',
  );
}
async function exportData(type) {
  if (type === "archives")
    return exportArchive(
      records()
        .filter((r) => r.effective)
        .map((r) => r.id),
    );
  let data =
    type === "logs"
      ? await api("/audit-logs")
      : type === "portrait"
        ? await api(
            "/students/" +
              selectedStudent +
              "/growth" +
              (growthPeriod
                ? "?period=" + encodeURIComponent(growthPeriod)
                : ""),
          )
        : type === "overview"
          ? {
              generated_at: new Date().toISOString(),
              scope: roleName(),
              students: state.students.length,
              tasks: tasks().length,
              pending: pending().length,
              archived: records().filter((r) => r.effective).length,
            }
          : records()
              .filter((r) => {
                const targetKind = {
                  papers: "paper",
                  competitions: "competition",
                  exchanges: "exchange",
                }[type];
                return !targetKind || r.kind === targetKind;
              })
              .map((r) => r.raw);
  download("InnoGrad-" + type + "-" + date(new Date()) + ".json", data);
  toast("已导出当前授权数据");
}
async function action(raw) {
  const [a, arg, extra] = raw.split(":");
  if (a.startsWith("growth-") || a === "warning" || a === "warning-method") {
    return growthAction(a, arg, extra);
  } else if (a === "menu") {
    menu = !menu;
    render();
  } else if (a === "navigate") await go(arg);
  else if (a === "agent-config") agentConfigDialog();
  else if (a === "refresh") {
    await refresh();
  } else if (a === "logout") {
    await post("/auth/logout");
    me = null;
    csrf = "";
    publishSession();
    portraitsCache = {};
    $("#dialog").close();
    loginView();
  } else if (a === "export") await exportData(arg);
  else if (a === "search-list") {
    query = $("#list-query").value.trim();
    pageNum = 1;
    render();
  } else if (a === "record") await showRecord({ id: arg });
  else if (a === "task") taskDialog(tasks().find((t) => t.id === arg));
  else if (a === "student") {
    selectedStudent = arg;
    growthTab = "personal";
    growthPeriod = "";
    await go("portraits");
  } else if (a === "edit") await editRecord({ id: arg });
  else if (
    a === "new-paper" ||
    a === "new-competition" ||
    a === "new-exchange"
  ) {
    const teachers = people.filter((p) => p.role === "teacher");
    if (!teachers.length) throw Error("尚无有效指导教师，请联系管理教师");
    const spec = {
      "new-paper": {
        kind: "paper",
        title: "登记论文成果",
        page: "papers",
        message: "论文工作稿已创建，请从列表继续填写",
      },
      "new-competition": {
        kind: "competition",
        title: "登记竞赛与获奖",
        page: "competitions",
        message: "竞赛与获奖工作稿已创建，请从列表继续填写",
      },
      "new-exchange": {
        kind: "exchange",
        title: "登记学术交流",
        page: "exchanges",
        message: "学术交流工作稿已创建，请从列表继续填写",
      },
    }[a];
    formModal(
      spec.title,
      `<label class="full">复核教师<select name="reviewer_id">${teachers.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select></label>`,
      async (d) => {
        const created = await post("/submissions", {
          kind: spec.kind,
          reviewer_id: d.get("reviewer_id"),
        });
        toast(spec.message);
        page = spec.page;
        location.hash = page;
        return { openEdit: created.id };
      },
      "创建工作稿",
    );
  } else if (a === "start-task") {
    let r = records().find((r) => r.task === arg && r.student === me.id);
    if (!r) r = await post("/submissions", { kind: "annual", task_id: arg });
    await editRecord(r);
  } else if (a === "new-task") {
    formModal(
      "发布培养任务",
      field("任务名称", "title") +
        field("统计周期", "period", String(new Date().getFullYear())) +
        field("截止日期", "deadline", "", "date") +
        `<label>复核教师<select name="reviewer_id">${people
          .filter((p) => p.role === "teacher")
          .map((p) => `<option value="${p.id}">${esc(p.name)}</option>`)
          .join(
            "",
          )}</select></label><label class="full">已发布规则版本<select name="rule_id">${[
          ...state.rules,
        ]
          .reverse()
          .map(
            (r) =>
              `<option value="${r.id}">${esc(r.title)} · ${esc(r.id.slice(0, 8))}</option>`,
          )
          .join(
            "",
          )}</select></label><div class="full"><p>应交学生名单（服务端会核验全部学生的导师范围）</p><div class="checklist">${state.students.map((s) => `<label><input type="checkbox" name="student_ids" value="${s.id}">${esc(s.name)}</label>`).join("")}</div></div>`,
      async (d) => {
        if (!d.getAll("student_ids").length) throw Error("请选择应交学生");
        await post("/cultivation-tasks", {
          title: d.get("title"),
          period: d.get("period"),
          deadline: d.get("deadline") + "T23:59:59+08:00",
          reviewer_id: d.get("reviewer_id"),
          rule_id: d.get("rule_id"),
          student_ids: d.getAll("student_ids"),
        });
        toast("培养任务已发布");
      },
      "确认发布",
    );
  } else if (a === "decide") {
    const context = JSON.parse($("#dialog").dataset.record),
      opinion = $("#opinion").value.trim();
    if (!opinion || !$("#confirm-evidence").checked)
      throw Error("请填写意见并确认已核对原件");
    await post("/submissions/" + arg + "/decision", {
      expected_lock_version: context.lock,
      version_id: context.version,
      outcome: extra,
      opinion,
    });
    await refresh();
    await showRecord({ id: arg });
    toast(
      extra === "approved"
        ? "机构已确认，后台将生成归档与画像快照"
        : "已退回学生补正",
    );
  } else if (a === "ai") {
    if (!capabilities.model_configured) {
      agentConfigDialog();
      return;
    }
    const r = await api("/submissions/" + arg);
    await post("/submissions/" + arg + "/ai-jobs", {
      version_id: r.current_version_id,
    });
    await showRecord({ id: arg });
  } else if (a === "cancel-ai") {
    await post("/ai-jobs/" + arg + "/cancel");
    await showRecord({ id: extra });
  } else if (a === "file") {
    let f = records()
      .flatMap((r) => r.raw.files)
      .find((f) => f.id === arg);
    await downloadFile(
      "/api/v1/files/" + arg + "/download",
      f?.name || "证明材料",
    );
  } else if (a === "export-record") await exportArchive([arg]);
  else if (a === "export-status") await exportStatus(arg);
  else if (a === "download-export")
    await downloadFile(
      "/api/v1/exports/" + arg + "/download",
      "归档清单-" + arg + ".json",
    );
  else if (a === "update" || a === "correct") {
    const r = await api("/submissions/" + arg);
    formModal(
      a === "update" ? "更新论文进展" : "申请档案更正",
      area("说明原因", "reason"),
      async (d) => {
        await post(
          "/submissions/" +
            arg +
            (a === "update" ? "/updates" : "/corrections"),
          { expected_lock_version: r.lock_version, reason: d.get("reason") },
        );
        toast(
          a === "update" ? "已重开工作稿，原认定持续有效" : "已提交更正申请",
        );
      },
    );
  } else if (a === "handle-correction") {
    const c = state.corrections.find((c) => c.id === arg),
      r = await api("/submissions/" + c.record);
    formModal(
      "处理档案更正",
      `<div class="full callout">${esc(c.reason)}</div><label class="full">处理决定<select name="outcome"><option value="approve">批准更正</option><option value="reject">驳回申请</option></select></label>` +
        area("处理意见", "opinion"),
      async (d) => {
        await post("/corrections/" + arg + "/handle", {
          expected_lock_version: r.lock_version,
          outcome: d.get("outcome"),
          opinion: d.get("opinion"),
        });
        toast("更正申请处理完成");
      },
    );
  } else if (a === "reassign") {
    const r = await api("/submissions/" + arg),
      s = student(r.student_id);
    formModal(
      "调整复核教师",
      `<label class="full">具有有效指导关系的教师<select name="reviewer_id">${s.teachers.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("")}</select></label>` +
        area("调整原因", "reason"),
      async (d) => {
        await post("/submissions/" + arg + "/reviewer", {
          expected_lock_version: r.lock_version,
          reviewer_id: d.get("reviewer_id"),
          reason: d.get("reason"),
        });
        toast("审核责任已更新");
      },
    );
  } else if (a === "alert") {
    const al = state.alerts.find((x) => x.id === arg);
    formModal(
      "提醒跟进 · " + student(al.student).name,
      `<div class="full callout">${esc(al.title)}<br>${esc(al.text)}</div>` +
        area("跟进记录", "note", al.note) +
        `<label class="full">状态<select name="status"><option value="open">持续关注</option><option value="done" ${al.status === "done" ? "selected" : ""}>已处理</option></select></label>`,
      async (d) => {
        await patch("/alerts/" + arg, {
          note: d.get("note"),
          status: d.get("status"),
          expected_lock_version: al.lock_version,
        });
        toast("跟进记录已保存");
      },
    );
  } else if (a === "remind") {
    const t = tasks().find((t) => t.id === arg);
    await post("/alerts", {
      student_id: extra,
      task_id: arg,
      title: "培养任务待提交",
      text: t.title + "，截止 " + date(t.deadline),
    });
    await refresh();
    toast("站内提醒已创建，学生登录后可见");
  } else if (a === "profile") {
    const s = student(arg);
    formModal(
      "编辑学生培养资料",
      field("年级", "year", s.year) +
        degreeSelect(s.degree) +
        field("专业", "major", s.major) +
        field("研究方向", "direction", s.direction) +
        field("培养阶段", "stage", s.stage),
      async (d) => {
        await patch("/students/" + arg + "/profile", Object.fromEntries(d));
        toast("培养资料已更新");
      },
    );
  } else if (a === "new-student") {
    formModal(
      "新增学生与业务账号",
      field("姓名", "name") +
        field("学号 / 登录账号", "number") +
        field("年级", "year") +
        degreeSelect("未标注") +
        field("专业", "major") +
        field("研究方向", "direction") +
        `<label>指导教师<select name="teacher_id">${people
          .filter((p) => p.role === "teacher")
          .map((p) => `<option value="${p.id}">${esc(p.name)}</option>`)
          .join("")}</select></label>`,
      async (d) => ({
        created: [await post("/students", Object.fromEntries(d))],
      }),
    );
  } else if (a === "import") importDialog();
  else if (a === "new-rule") {
    formModal(
      "发布年度报告规则新版本",
      field("规则名称", "title", "", "text", true) +
        area("材料要求与审核说明", "content") +
        `<div class="full"><p>服务端必填校验字段</p><div class="checklist"><label><input type="checkbox" checked disabled>研究总结（始终必填）</label><label><input type="checkbox" name="required_fields" value="title" checked>材料标题</label><label><input type="checkbox" name="required_fields" value="plan">下一阶段计划</label></div></div>`,
      async (d) => {
        await post("/rules", {
          title: d.get("title"),
          content: d.get("content"),
          required_fields: ["summary", ...d.getAll("required_fields")],
        });
        toast("新版本已冻结，历史任务保持原规则");
      },
      "发布新版本",
    );
  } else if (a === "rule") {
    const r = state.rules.find((r) => r.id === arg);
    modal(
      r.title,
      `<div class="callout">规则版本 ${esc(r.id)} · 必填字段 ${esc(r.requirements.required_fields.join("、"))}</div><p>${esc(r.content)}</p>`,
    );
  }
}
function importDialog() {
  modal(
    "导入学生名单",
    `<div class="callout">UTF-8 CSV 列名：姓名,学号,年级,专业,导师,研究方向,培养层次。兼容原六列格式；层次填写博士、硕士或未标注。导师需填写当前范围内的教师姓名；服务端预览校验后再确认导入。最多 100 行。</div><button class="btn" id="csv-template">下载 CSV 模板</button><input type="file" id="csv-file" accept=".csv" style="display:block;width:100%;margin:18px 0" aria-label="上传 CSV 名单"><div id="import-preview"></div>`,
  );
  $("#csv-template").onclick = () =>
    download(
      "学生导入模板.csv",
      "\uFEFF姓名,学号,年级,专业,导师,研究方向,培养层次\n",
      "text/csv;charset=utf-8",
    );
  $("#csv-file").onchange = async (e) => {
    try {
      const file = e.target.files[0];
      if (!file) return;
      if (file.size > 1024 * 1024) throw Error("名单文件不得超过 1 MB");
      const rows = parseCSV(await file.text());
      if (
        ![
          "姓名,学号,年级,专业,导师,研究方向",
          "姓名,学号,年级,专业,导师,研究方向,培养层次",
        ].includes(rows.shift()?.join(","))
      )
        throw Error("列名不匹配，请使用 CSV 模板");
      const entries = rows.map((v) => {
        const matches = people.filter(
          (p) => p.role === "teacher" && p.name === v[4],
        );
        if (matches.length !== 1)
          throw Error("导师姓名不存在或重名，请先核对：" + v[4]);
        return {
          name: v[0],
          number: v[1],
          year: v[2],
          major: v[3],
          degree: v[6] || "未标注",
          teacher_id: matches[0].id,
          direction: v[5],
        };
      });
      const result = await post("/student-imports", { rows: entries });
      $("#import-preview").innerHTML =
        `<p>共 ${result.checks.length} 行 · 服务端已校验</p><div class="table-wrap"><table><thead><tr><th>姓名</th><th>学号</th><th>校验结果</th></tr></thead><tbody>${result.checks.map((c) => `<tr><td>${esc(c.row.name)}</td><td>${esc(c.row.number)}</td><td>${esc(c.error || "可导入")}</td></tr>`).join("")}</tbody></table></div><button class="btn primary" id="confirm-import" style="margin-top:15px" ${result.valid ? "" : "disabled"}>确认导入</button>`;
      $("#confirm-import").onclick = async (e) => {
        e.target.disabled = true;
        try {
          const data = await post("/student-imports/" + result.id + "/commit");
          $("#dialog").close();
          await refresh();
          credentialsDialog(data.created);
        } catch (e) {
          showError(e);
        }
      };
    } catch (e) {
      $("#import-preview").textContent = e.message;
      showError(e);
    }
  };
}
function agentConfigDialog() {
  modal(
    "Agent 服务待配置",
    `<div class="callout amber">当前未连接 Agent 服务，不会生成模拟审核结论。</div><p>在服务器 <code>backend/.env</code> 中配置：</p><pre style="white-space:pre-wrap;line-height:1.8;background:#f4f7f0;padding:16px">AI_MODE=agent
AI_BASE_URL=你的 Agent 服务地址
AI_API_KEY=按需配置
REVIEW_WORKFLOW=agent</pre><p>Agent 接口需实现 POST /review；也可使用兼容 Chat Completions 的服务，设置 AI_MODE=chat 与 AI_MODEL。配置后重启 API 和 Worker，再点击“启动 / 重试 Agent”。</p>`,
    btn("查看系统状态", "navigate:settings"),
  );
}
function agentReviewView() {
  let rows = reviewQueue.filter((q) => {
    const r = records().find((r) => r.id === q.submission_id);
    return (
      r &&
      (!query || (r.title + student(r.student).name).includes(query)) &&
      (filter === "all" ||
        (filter === "exceptions" &&
          q.institution_required &&
          q.business_status === "pending_review") ||
        q.job_status === filter)
    );
  });
  return (
    heading(
      "Agent 审核",
      "材料解析 → 规则检查 → 证据核验 → 审核报告，全程保留版本与执行记录。",
      btn("服务配置", "agent-config", false, "settings") +
        btn("刷新任务", "refresh", true, "history"),
    ) +
    (!capabilities.model_configured
      ? '<div class="callout amber">Agent 服务待配置。材料和历史记录已保存在服务器；接口就绪后可逐项启动审核。既有规则检查不作为 Agent 审核结果。</div>'
      : '<div class="callout">Agent 审核通过后自动归档并更新学生画像；仅异常、证据不足、无法判断或执行失败的任务转交机构处理。</div>') +
    `<section class="card"><div class="review-flow"><span>01 材料解析</span> → <span>02 规则与证据核验</span> → <span>03 Agent 报告</span> → <span>04 自动归档与画像更新</span></div><div class="toolbar"><input id="list-query" aria-label="筛选材料" placeholder="搜索学生或材料标题" value="${esc(query)}"><select id="status-filter" aria-label="任务状态"><option value="all">全部任务</option><option value="exceptions" ${filter === "exceptions" ? "selected" : ""}>仅机构异常</option>${[
      ["queued", "排队中"],
      ["running", "执行中"],
      ["succeeded", "已完成"],
      ["failed", "失败"],
      ["cancelled", "已取消"],
    ]
      .map(
        ([v, t]) =>
          `<option value="${v}" ${filter === v ? "selected" : ""}>${t}</option>`,
      )
      .join(
        "",
      )}</select>${btn("查询", "search-list", false, "search")}</div><div class="callout" style="margin:16px 23px">${reviewQueue.filter((q) => q.institution_required && q.business_status === "pending_review").length} 项异常待机构处理 · 正常通过无需人工确认</div>${
      rows.length
        ? `<div class="table-wrap"><table><thead><tr><th>学生</th><th>材料与版本</th><th>Agent 状态</th><th>操作</th></tr></thead><tbody>${rows
            .map((q) => {
              const r = records().find((r) => r.id === q.submission_id);
              return `<tr><td>${person(r.student)}</td><td><span class="cell-title">${esc(r.title)}</span><small style="display:block;margin-top:5px">V${r.versions.length} · ${esc(r.reviewer)}</small></td><td><span class="badge ${q.outcome.state === "passed" ? "" : "amber"}">${q.simulation ? "模拟审核异常" : q.business_status === "archived" ? "已归档" : q.business_status === "approved" ? "正在自动归档" : capabilities.model_configured ? esc(q.outcome.label) : "Agent 待配置"}</span></td><td><div class="actions"><button class="linkbtn" data-action="record:${r.id}">查看材料与报告 ↗</button><button class="linkbtn" data-action="ai:${r.id}">${capabilities.model_configured ? "启动 / 重试" : "配置说明"}</button></div></td></tr>`;
            })
            .join("")}</tbody></table></div>`
        : empty("暂无审核任务", "学生正式提交后，任务会出现在这里。")
    }</section>`
  );
}
async function growthAction(a, arg, extra) {
  if (a === "growth-tab") {
    growthTab = arg;
    await refresh();
    return;
  }
  if (a === "growth-person") {
    selectedStudent = arg;
    growthTab = "personal";
    await refresh();
    return;
  }
  const current = growthCache[selectedStudent + "|" + growthPeriod];
  if (a === "growth-method") {
    modal(
      "材料观察的指标口径",
      `<div class="callout">参考页的六类方向用于组织材料，不替代历史八维量表，也不计算隐性能力分。</div><p>雷达图展示每类方向的可追溯来源条数。年度报告中的研究总结/计划关联“年度目标”；论文状态与竞赛奖项关联“科研训练”；论文个人贡献与竞赛本人角色关联“课题与贡献”；学术交流的参会/作报告/展示海报关联“学术交流”，承担具体实践任务关联“实践落地”。其他方向由授权教师引用已归档字段原文添加观察记录。</p><p style="margin-top:14px">相同版本、字段和引用文字只计一次；更正后的旧版本仍可追溯，但不继续计入当前覆盖。学年仅使用任务或记录中明确填写的周期，未标注学年的材料不自动推断。</p><p style="margin-top:14px">归档月份分布仅表示有效记录的归档时间。它不表示科研能力提升，也不用于学生排名。</p>`,
    );
    return;
  }
  if (a === "warning-method") {
    modal(
      "自动预警规则",
      `<div class="callout">规则版本 growth-alerts-1 · 只提示可核验事项，不判定学生能力或学业资格。</div><div class="evidence"><h4>材料与任务</h4><p>截止时间已过且没有正式提交：优先核验；未来 7 天内截止且未提交：提醒准备；材料退回或重开：提醒补正。</p></div><div class="evidence"><h4>Agent 审核</h4><p>当前版本的最新任务出现异常、无法判断、执行失败或取消时提示核验。Agent 尚未配置不会被解释为学生的问题。</p></div><div class="evidence"><h4>研究计划</h4><p>用户明确填写的目标/里程碑日期已过、状态仍为计划中时，提示沟通进展或调整安排。</p></div><p>同一来源版本只显示一个事项。条件消除后从待跟进队列移除，已有跟进历史仍保留。处理意见向学生和授权教师开放。</p>`,
    );
    return;
  }
  if (a === "growth-dimension") {
    const d = current.dimensions.find((d) => d.key === arg);
    modal(
      d.label + " · 材料依据",
      `<div class="callout">${esc(d.description)}。当前有 ${d.count} 条去重来源；暂无能力评分。</div>${d.evidence.map((ref) => `<div class="evidence"><h4>${esc(ref.title)}</h4><p>${ref.origin === "observation" ? "教师关联的观察依据" : "已归档材料字段"}</p><blockquote style="white-space:pre-wrap">${esc(ref.quote)}</blockquote><small>提交版本 ${esc(ref.version_id)} · 字段 ${esc(ref.field)}</small><br><button class="linkbtn" data-action="record:${ref.submission_id}">查看材料与原件 ↗</button></div>`).join("") || empty("尚未关联此方向的材料", "缺少材料不表示该项能力不足。")}`,
    );
    return;
  }
  if (a === "growth-history") {
    modal(
      "成长记录 · " + student(selectedStudent).name,
      `${(current?.entries || []).map((x) => `<div class="evidence"><h4>${esc({ goal: "阶段目标", milestone: "里程碑", reflection: "研究反思", feedback: "阶段反馈", observation: "材料观察" }[x.kind])} · ${esc(x.title)}</h4><p style="white-space:pre-wrap">${esc(x.body)}</p><small>${esc(x.author)} · ${esc(x.period)} · ${date(x.created_at)}</small>${x.source ? `<blockquote>${esc(x.source.quote)}</blockquote><button class="linkbtn" data-action="record:${x.source.submission_id}">来源 V${x.source.number} · ${x.source.current ? "当前有效" : "历史版本"}</button>` : ""}</div>`).join("") || empty("暂无成长记录")}`,
    );
    return;
  }
  if (a === "growth-complete") {
    const row = current.entries.find((x) => x.id === arg);
    await patch("/growth/" + arg, {
      expected_lock_version: row.lock_version,
      status: extra,
    });
    await refresh();
    toast("研究计划状态已保存");
    return;
  }
  if (a === "growth-edit") {
    const row = current.entries.find((x) => x.id === arg);
    formModal(
      "调整研究计划",
      field("计划标题", "title", row.title, "text", true) +
        area("计划内容", "body", row.body) +
        `<label class="full">计划完成日期（选填）<input name="due_date" type="date" value="${esc(row.due_date || "")}"></label>`,
      async (d) => {
        await patch("/growth/" + arg + "/plan", {
          expected_lock_version: row.lock_version,
          title: d.get("title"),
          body: d.get("body"),
          due_date: d.get("due_date") || null,
        });
        toast("研究计划已更新，预警将按新日期重新判断");
      },
    );
    return;
  }
  if (a === "growth-new") {
    if (!current) throw Error("请先选择学生画像");
    const names = {
      goal: "记录研究目标",
      milestone: "添加研究里程碑",
      reflection: "写一条研究反思",
      feedback: "记录阶段反馈",
      observation: "关联材料观察",
    };
    const dims = current.dimensions;
    formModal(
      names[arg],
      `<div class="full callout">记录向该学生和授权教师开放；计划和反思不会自动变成已认定成果。</div>${field("记录标题", "title", "", "text", true)}${field("所属学年 / 周期", "period", growthPeriod || current.periods[0] || String(new Date().getFullYear()))}${["goal", "milestone"].includes(arg) ? '<label>计划完成日期（选填）<input name="due_date" type="date"></label>' : ""}${area(arg === "feedback" ? "具体反馈与下一步建议" : arg === "observation" ? "观察内容与关联理由" : "具体内容", "body")}<label class="full">材料观察方向${arg === "observation" ? "（必选）" : "（选填）"}<select name="dimension" ${arg === "observation" ? "required" : ""}><option value="">不关联方向</option>${dims.map((d) => `<option value="${d.key}">${esc(d.label)}</option>`).join("")}</select></label><label class="full">来源档案${arg === "observation" ? "（必选）" : "（选填）"}<select id="growth-source" name="source_submission_id" ${arg === "observation" ? "required" : ""}><option value="">不关联档案</option>${current.sources.map((s) => `<option value="${s.submission_id}">${esc(s.title)} · V${s.number}</option>`).join("")}</select></label><div class="full" id="growth-source-fields"></div>`,
      async (d) => {
        const body = {
          kind: arg,
          title: d.get("title"),
          period: d.get("period"),
          body: d.get("body"),
          dimension: d.get("dimension") || null,
          due_date: d.get("due_date") || null,
          source_submission_id: d.get("source_submission_id") || null,
          source_field: d.get("source_field") || null,
          source_quote: d.get("source_quote") || null,
        };
        await post("/students/" + selectedStudent + "/growth", body);
        toast("成长记录已保存到服务器");
      },
    );
    $("#growth-source").onchange = (e) => {
      const source = current.sources.find(
        (s) => s.submission_id === e.target.value,
      );
      const box = $("#growth-source-fields");
      if (!source) {
        box.innerHTML = "";
        return;
      }
      const fields = Object.entries(source.form).filter(
        ([k, v]) => typeof v === "string" && v.trim(),
      );
      box.innerHTML = `<label style="display:block;margin-bottom:10px">引用字段<select id="growth-source-field" name="source_field" style="width:100%;margin-top:8px">${fields.map(([k, v]) => `<option value="${esc(k)}">${esc(fieldLabels[k] || { title: "标题", summary: "研究总结", plan: "下一阶段计划" }[k] || k)}</option>`).join("")}</select></label><label>原文摘录（须与所选字段原文一致）<textarea id="growth-source-quote" name="source_quote" required style="width:100%;margin-top:8px">${esc(fields[0]?.[1].slice(0, 4000) || "")}</textarea></label>`;
      $("#growth-source-field").onchange = (e) => {
        $("#growth-source-quote").value = source.form[e.target.value].slice(
          0,
          4000,
        );
      };
    };
    return;
  }
  if (a === "warning") {
    const w = warningsData.find((x) => x.id === arg);
    if (!w) throw Error("预警已更新，请刷新查看");
    const statusText = {
      open: "待跟进",
      tracking: "跟进中",
      resolved: "已处理",
      dismissed: "已排除",
      cleared: "条件已消除",
    };
    const body = `<div class="callout ${w.active ? "amber" : ""}">${esc(student(w.student).name)} · ${statusText[w.status]}<br>${esc(w.text)}</div><p class="muted">来源规则 ${esc(w.rule_version)} · 当前条件${w.active ? "仍存在" : "已消除"}</p><div class="actions" style="margin:15px 0">${btn("查看来源依据", "growth-warning-source:" + w.id)}</div><h3 style="margin:20px 0 12px">跟进历史</h3>${w.history.map((h) => `<div class="evidence"><h4>${statusText[h.status]} · ${esc(h.actor)}</h4><p style="white-space:pre-wrap">${esc(h.note)}</p><small>${esc(new Date(h.time).toLocaleString("zh-CN"))}</small></div>`).join("") || '<p class="muted">尚未记录跟进。</p>'}`;
    if (role === "student" || !w.active) {
      modal(w.title, body);
      return;
    }
    formModal(
      w.title,
      `<div class="full">${body}</div><label class="full">下一步状态<select name="status"><option value="tracking">正在跟进</option><option value="resolved">已沟通处理</option><option value="dismissed">核验后排除</option></select></label>${area("核对依据、沟通结果与下一步行动", "note")}`,
      async (d) => {
        await post("/warnings/" + w.id + "/actions", {
          expected_revision: w.revision,
          status: d.get("status"),
          note: d.get("note"),
        });
        toast("预警跟进已保存并留痕");
      },
      "保存跟进",
    );
    return;
  }
  if (a === "growth-warning-source") {
    const w = warningsData.find((x) => x.id === arg);
    if (w.source_type === "submission") {
      await showRecord({ id: w.source_id });
      return;
    }
    if (w.source_type === "task") {
      const t = tasks().find((t) => t.id === w.source_id);
      if (!t) throw Error("当前没有该任务的访问范围");
      taskDialog(t);
      return;
    }
    selectedStudent = w.student;
    growthTab = "personal";
    growthPeriod = "";
    $("#dialog").close();
    await go("portraits");
    toast("已打开对应学生的研究计划与里程碑");
    return;
  }
}
window.addEventListener("hashchange", () => {
  const next = location.hash.slice(1) || "dashboard";
  if (next !== page) {
    page = next;
    filter = "all";
    subFilter = "all";
    query = "";
    pageNum = 1;
    refresh().catch(showError);
  }
});
setInterval(() => {
  if (
    me &&
    !document.hidden &&
    !$("#dialog").open &&
    !$("#innograd-agent")?.shadowRoot?.querySelector("textarea:focus") &&
    !document.querySelector("input:focus,textarea:focus")
  )
    refresh().catch(showError);
}, 15000);
try {
  me = await api("/me");
  csrf = me.csrf_token;
  role = me.role;
  publishSession();
  await refresh();
} catch (e) {
  if (me) showError(e);
  else loginView();
}
