const fieldLabels = {
  title: "论文标题",
  publication_status: "发表状态",
  submission_date: "投稿日期",
  acceptance_date: "录用日期",
  publication_date: "发表日期",
  status_date: "状态日期",
  journal: "期刊 / 会议",
  doi: "DOI",
  article_url: "文章链接",
  authors: "作者列表",
  author_order: "本人作者顺序",
  author_identity: "本人身份",
  contribution: "本人贡献",
  competition_name: "竞赛名称",
  organizer: "主办方",
  award_level: "奖项",
  award_date: "获奖日期",
  team_members: "团队成员",
  team_size: "团队人数",
  my_role: "本人角色",
  proof_mode: "证明方式",
  publicity_url: "公示链接",
  description: "补充说明",
  activity_name: "会议或实践项目名称",
  activity_date: "活动日期",
  end_date: "结束日期",
  participation_mode: "参与方式",
  location_or_organizer: "主办单位 / 地点",
  presentation_title: "报告 / 海报题目",
  practice_task_description: "承担的具体实践任务",
  participation_summary: "参与说明",
  reference_url: "活动链接",
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
  competition: "竞赛与获奖",
  exchange: "学术交流",
  scholarship: "奖学金",
  attend: "参会",
  talk: "作报告",
  poster: "展示海报",
  practice_task: "承担具体实践任务",
  certificate_and_link: "证书附件 + 公示链接",
  certificate_only: "仅证书附件",
  link_only: "仅公示链接",
  first_author: "第一作者",
  co_first_author: "共同第一作者",
  corresponding_author: "通讯作者",
  other_author: "其他作者",
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
  if (Array.isArray(value)) {
    if (!value.length) return "—";
    return value
      .map((item) => {
        if (item && typeof item === "object" && "name" in item) {
          const prefix = item.order ? `${item.order}. ` : "";
          const selfTag = item.is_self ? "（本人）" : "";
          return `${prefix}${item.name}${selfTag}`;
        }
        return formatValue(item);
      })
      .join("、");
  }
  return String(value);
}

export { enumLabels, fieldLabels };
