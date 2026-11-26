/**
 * Domain label dictionaries and URL sanitizer for achievement submissions.
 */

export const KIND_LABELS = {
  paper: "论文成果",
  annual: "年度报告",
  software_copyright: "软件著作权",
  research_project: "科研项目",
};

export const KIND_SHORT_TITLES = {
  paper: "论文成果申报",
  annual: "年度考核报告",
  software_copyright: "软件著作权申报",
  research_project: "科研项目阶段成果",
};

export const REGISTRATION_STATUS_LABELS = {
  unregistered: "未登记",
  applying: "申请登记中",
  registered: "已登记",
};

export const STUDENT_ROLE_LABELS = {
  lead: "项目/子课题负责人",
  core_member: "核心成员",
  participant: "参与成员",
  other: "其他",
};

export const ARTIFACT_TYPE_LABELS = {
  experiment_report: "实验报告",
  dataset: "数据集",
  code: "代码",
  prototype: "原型",
};

const PAPER_FILE_ROLES = {
  paper_fulltext: "论文全文",
  submission_proof: "投稿证明",
  author_order_proof: "作者顺位证明",
  acceptance_proof: "录用证明",
  publication_proof: "发表证明",
  article_page: "文章页面或 DOI 证明",
  contribution_proof: "本人贡献证明",
  other_proof: "其他证明材料",
};

const SOFTWARE_FILE_ROLES = {
  copyright_certificate: "软件著作权登记证书",
  registration_application: "登记申请或受理证明",
  source_code_doc: "源代码或设计说明书",
  development_proof: "个人开发工作证明",
  other_proof: "其他证明材料",
};

const PROJECT_FILE_ROLES = {
  experiment_report: "实验报告",
  dataset_doc: "数据集说明或清单",
  code_artifact: "代码文档或仓库说明",
  prototype_doc: "原型设计或演示材料",
  project_proof: "项目参与或结题证明",
  other_proof: "其他证明材料",
};

export const ALL_FILE_ROLE_LABELS = {
  ...PAPER_FILE_ROLES,
  ...SOFTWARE_FILE_ROLES,
  ...PROJECT_FILE_ROLES,
};

export function fileRoleLabelsForKind(kind) {
  if (kind === "software_copyright") return SOFTWARE_FILE_ROLES;
  if (kind === "research_project") return PROJECT_FILE_ROLES;
  return PAPER_FILE_ROLES;
}

export function safeHttpUrl(raw) {
  if (typeof raw !== "string" || !raw.trim()) return "";
  try {
    const parsed = new URL(raw.trim());
    const validScheme =
      parsed.protocol === "http:" || parsed.protocol === "https:";
    if (!validScheme || parsed.username || parsed.password) return "";
    return parsed.href;
  } catch {
    return "";
  }
}

export function achievementTitle(kind, form) {
  if (kind === "software_copyright") {
    return form.software_name || form.title || "未命名软件著作权";
  }
  if (kind === "research_project") {
    return form.project_name || form.title || "未命名科研项目";
  }
  if (kind === "annual") return form.title || "年度培养报告";
  return form.title || "未命名论文";
}

export function achievementPrimaryText(kind, form) {
  if (kind === "software_copyright") return form.development_work || "";
  if (kind === "research_project") return form.stage_deliverables || "";
  if (kind === "paper") return form.contribution || "";
  return form.summary || "";
}

export function achievementStatusSummary(kind, form, taskPeriod = "") {
  if (kind === "software_copyright") {
    const status =
      REGISTRATION_STATUS_LABELS[form.registration_status] || "未登记";
    return form.registration_status === "registered" && form.registration_number
      ? `${status} · ${form.registration_number}`
      : status;
  }
  if (kind === "research_project") {
    const roleLabel =
      STUDENT_ROLE_LABELS[form.student_role] || form.student_role || "—";
    return form.completion_date
      ? `${roleLabel} · ${form.completion_date}`
      : roleLabel;
  }
  if (kind === "paper") {
    return (
      { submitted: "已投稿", accepted: "已录用", published: "已发表" }[
        form.publication_status || "submitted"
      ] || "已投稿"
    );
  }
  return taskPeriod || "—";
}

export function renderAchievementSummaryBar(items) {
  const archived = items.filter((r) => r.status === "archived").length;
  const reviewing = items.filter((r) =>
    ["pending", "approved"].includes(r.status),
  ).length;
  const editing = items.filter((r) =>
    ["draft", "returned"].includes(r.status),
  ).length;
  return `<div class="ach-summary-bar"><div class="ach-kpi is-brand"><span>全部记录</span><strong>${items.length}</strong></div><div class="ach-kpi is-ok"><span>已归档认定</span><strong>${archived}</strong></div><div class="ach-kpi is-warn"><span>审核流转中</span><strong>${reviewing}</strong></div><div class="ach-kpi"><span>草稿与待补正</span><strong>${editing}</strong></div></div>`;
}
