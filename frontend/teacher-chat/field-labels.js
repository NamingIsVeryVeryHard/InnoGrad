const fieldLabels = {
  title: "论文标题",
  publication_status: "发表状态",
  submission_date: "投稿日期",
  acceptance_date: "录用日期",
  publication_date: "发表日期",
  status_date: "状态日期",
  journal: "期刊 / 会议",
  doi: "DOI",
  contribution: "本人贡献",
  review_status: "审核状态",
  review_actor_type: "审核方式",
  degree: "培养层次",
  major: "专业",
  direction: "研究方向",
  year: "年级",
  stage: "培养阶段",
  student_name: "学生",
  student_id: "学生编号",
  student_number: "学号",
  submission_id: "提交编号",
  version_number: "提交版本",
  archived_at: "归档日期",
  latest_status_date: "最近状态日期",
  matched_record_count: "符合条件的论文记录数",
  has_doi: "是否有 DOI",
  simulation: "模拟记录",
  verification: "核验状态",
  summary: "摘要",
  plan: "下一阶段计划",
  notice: "说明",
};

const enumLabels = {
  submitted: "已投稿",
  accepted: "已录用",
  published: "已发表",
  pending_review: "待审核",
  returned: "待补正",
  approved: "已通过",
  archived: "已归档",
  current_effective_archives: "当前有效归档",
  submitted_latest: "最新提交版本",
  doctoral: "博士",
  master: "硕士",
  paper_record: "论文申报",
  student: "学生",
  aggregate: "统计",
  list: "明细",
  portrait: "学生画像",
  paper: "论文成果",
  annual: "年度报告",
  scholarship: "奖学金",
  human: "人工审核",
  agent: "智能审核",
  simulation: "模拟审核",
  human_approved_submission: "人工审核通过",
  agent_approved_submission: "智能审核通过",
  simulated_approved_submission: "模拟审核通过",
  submitted_unarchived_version: "已提交，尚未归档",
};

export function labelFor(value) {
  if (Object.hasOwn(fieldLabels, value)) return fieldLabels[value];
  return Object.hasOwn(enumLabels, value)
    ? enumLabels[value]
    : String(value ?? "");
}

export function formatDate(value) {
  if (!value) return "";
  const match = String(value).match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (match) {
    const formatted = `${match[1]}年${Number(match[2])}月${Number(match[3])}日`;
    return formatted;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const formatted = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "numeric",
    day: "numeric",
  }).format(date);
  return formatted;
}

export function formatValue(value) {
  if (value == null || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string") {
    if (/^\d{4}-\d{2}-\d{2}/.test(value)) return formatDate(value);
    return Object.hasOwn(enumLabels, value) ? enumLabels[value] : value;
  }
  if (Array.isArray(value)) return value.map(formatValue).join("、");
  return String(value);
}

export { enumLabels, fieldLabels };
