/**
 * Modular UI renderers and form extractors for software copyright (Issue #25)
 * and research project stage achievement (Issue #26) submissions.
 */

import {
  ALL_FILE_ROLE_LABELS,
  ARTIFACT_TYPE_LABELS,
  KIND_LABELS,
  KIND_SHORT_TITLES,
  REGISTRATION_STATUS_LABELS,
  STUDENT_ROLE_LABELS,
  achievementPrimaryText,
  achievementStatusSummary,
  achievementTitle,
  fileRoleLabelsForKind,
  safeHttpUrl,
} from "./achievements-labels.js";
import {
  QUICK_PERIODS,
  achievementRowMeta,
  bindArtifactRowEvents,
  bindCharCounters,
  bindFormShortcutsAndDirty,
  bindHolderPreview,
  bindQuickPeriods,
  bindRoleDetailToggle,
  bindUploadDropzone,
  defaultFileRoleForSubmission,
  holdersToText,
  parseCopyrightHolders,
  syncResearchProjectFileOptions,
} from "./achievements-enhance.js";

export {
  ALL_FILE_ROLE_LABELS,
  ARTIFACT_TYPE_LABELS,
  KIND_LABELS,
  KIND_SHORT_TITLES,
  REGISTRATION_STATUS_LABELS,
  STUDENT_ROLE_LABELS,
  achievementPrimaryText,
  achievementRowMeta,
  achievementStatusSummary,
  achievementTitle,
  bindFormShortcutsAndDirty,
  bindUploadDropzone,
  defaultFileRoleForSubmission,
  fileRoleLabelsForKind,
  parseCopyrightHolders,
  safeHttpUrl,
  syncResearchProjectFileOptions,
};

const ARTIFACT_EMPTY_HTML =
  '<div class="artifact-empty">未添加关联材料（实验报告、数据集、代码或原型均为选填）</div>';

function buildOptions(entries, selected) {
  return entries
    .map(
      ([val, label]) =>
        `<option value="${val}" ${selected === val ? "selected" : ""}>${label}</option>`,
    )
    .join("");
}

function labelTag(text, required = false, rightHtml = "") {
  const mark = required
    ? '<span class="req-mark" aria-hidden="true">*</span>'
    : '<span class="opt-text">选填</span>';
  return `<span class="label-row"><span>${text}</span>${mark}${rightHtml}</span>`;
}

function sectionHead(title, rightHtml = "") {
  return `<div class="ach-section-head"><span class="ach-section-title">${title}</span>${rightHtml}</div>`;
}

function quickPeriodRow() {
  return `<div class="quick-chips">${QUICK_PERIODS.map((p) => `<button type="button" class="quick-chip" data-quick-period="${p}">${p}</button>`).join("")}</div>`;
}

export function renderSoftwareCopyrightFields(form, esc) {
  const status = form.registration_status || "unregistered";
  const isRegistered = status === "registered";
  const hiddenStyle = isRegistered ? "" : ' style="display:none"';
  const noteStyle = isRegistered ? ' style="display:none"' : "";
  const reqAttr = isRegistered ? "required" : "disabled";
  return [
    sectionHead("基础信息"),
    `<label class="full">${labelTag("软件全称", true)}<input name="software_name" value="${esc(form.software_name || form.title || "")}" required maxlength="200" placeholder="请输入软件全称"></label>`,
    `<label>${labelTag("版本号", true)}<input name="version" value="${esc(form.version || "")}" required maxlength="50" placeholder="如 V1.0"></label>`,
    `<label>${labelTag("登记状态", true)}<select name="registration_status" id="sw-reg-status" required>${buildOptions(Object.entries(REGISTRATION_STATUS_LABELS), status)}</select></label>`,
    `<label class="full">${labelTag("著作权人", true)}<textarea name="copyright_holders" required rows="3" placeholder="华东师范大学&#10;张三">${esc(holdersToText(form.copyright_holders))}</textarea><span class="field-hint">每行或以逗号、顿号分隔一名，自动去重</span><div class="holder-chips" id="sw-holders-preview"></div></label>`,
    sectionHead("登记信息"),
    `<div class="ach-reg-note" id="sw-reg-note"${noteStyle}>未登记或申请中无需填写登记号与日期，获证后可通过「更新成果进展」补录。</div>`,
    `<div class="ach-reg-panel" id="sw-reg-panel"${hiddenStyle}><div class="form-grid"><label class="sw-reg-only"${hiddenStyle}>${labelTag("登记号", true)}<input name="registration_number" value="${esc(form.registration_number || "")}" ${reqAttr} maxlength="64" placeholder="如 2026SR1234567"></label><label class="sw-reg-only"${hiddenStyle}>${labelTag("登记日期", true)}<input name="registration_date" type="date" value="${esc(form.registration_date || "")}" ${reqAttr}></label></div></div>`,
    sectionHead("开发贡献"),
    `<label class="full">${labelTag("所属学年 / 周期", false)}<input name="period" value="${esc(form.period || "")}" maxlength="40" placeholder="2025—2026学年">${quickPeriodRow()}</label>`,
    `<label class="full">${labelTag("学生承担的开发工作", true, '<span class="char-counter" data-counter-for="development_work">0 / 4000</span>')}<textarea name="development_work" data-counter required rows="4" maxlength="4000" placeholder="说明本人承担的架构设计、核心编码与测试工作">${esc(form.development_work || "")}</textarea></label>`,
  ].join("");
}

function renderArtifactRow(item, files, esc, entering = false) {
  const selectedType = item.artifact_type || "experiment_report";
  const fileOptions = [
    `<option value="">不关联已上传附件</option>`,
    ...files.map(
      (f) =>
        `<option value="${esc(f.id)}" ${item.file_id === f.id ? "selected" : ""}>${esc(f.name)}</option>`,
    ),
  ].join("");
  const animCls = entering ? " is-entering" : "";
  return `<div class="artifact-row${animCls}"><div class="artifact-row-head"><span class="artifact-row-title">${ARTIFACT_TYPE_LABELS[selectedType] || "关联材料"}</span><button type="button" class="linkbtn danger-link" data-remove-artifact>移除</button></div><div class="form-grid"><label>${labelTag("类别", true)}<select data-art="artifact_type">${buildOptions(Object.entries(ARTIFACT_TYPE_LABELS), selectedType)}</select></label><label>${labelTag("名称", true)}<input data-art="name" value="${esc(item.name || "")}" maxlength="200" required placeholder="消融实验报告 v1"></label><label>${labelTag("访问链接", false)}<input data-art="url" type="url" value="${esc(item.url || "")}" maxlength="2000" placeholder="https://..."></label><label>${labelTag("关联附件", false)}<select data-art="file_id">${fileOptions}</select></label><label class="full">${labelTag("说明", false)}<input data-art="description" value="${esc(item.description || "")}" maxlength="500" placeholder="补充说明版本或用途"></label></div></div>`;
}

export function renderResearchProjectFields(form, files, esc) {
  const roleVal = form.student_role || "core_member";
  const artifacts = Array.isArray(form.linked_artifacts)
    ? form.linked_artifacts
    : [];
  const roleDetailReq = roleVal === "other" ? "required" : "";
  const artifactBody = artifacts.length
    ? artifacts.map((item) => renderArtifactRow(item, files, esc)).join("")
    : ARTIFACT_EMPTY_HTML;
  const quickAddBtns = Object.entries(ARTIFACT_TYPE_LABELS)
    .map(
      ([key, label]) =>
        `<button type="button" class="quick-chip" data-add-artifact="${key}">+ ${label}</button>`,
    )
    .join("");
  return [
    sectionHead("项目信息"),
    `<label class="full">${labelTag("项目或课题名称", true)}<input name="project_name" value="${esc(form.project_name || form.title || "")}" required maxlength="200" placeholder="请输入项目或课题全称"></label>`,
    `<label>${labelTag("学生本人角色", true)}<select name="student_role" id="rp-student-role" required>${buildOptions(Object.entries(STUDENT_ROLE_LABELS), roleVal)}</select></label>`,
    `<label>${labelTag("完成时间", true)}<input name="completion_date" type="date" value="${esc(form.completion_date || "")}" required></label>`,
    `<label class="full" id="rp-role-detail-wrap">${labelTag("角色补充说明（选“其他”时必填）", roleVal === "other")}<input name="role_description" id="rp-role-detail" value="${esc(form.role_description || "")}" ${roleDetailReq} maxlength="100" placeholder="如 数据管线负责人、前端开发"></label>`,
    `<label class="full">${labelTag("所属学年 / 周期", false)}<input name="period" value="${esc(form.period || "")}" maxlength="40" placeholder="2025—2026学年">${quickPeriodRow()}</label>`,
    sectionHead("阶段事项"),
    `<label class="full">${labelTag("本阶段完成的具体事项", true, '<span class="char-counter" data-counter-for="stage_deliverables">0 / 4000</span>')}<textarea name="stage_deliverables" data-counter required rows="4" maxlength="4000" placeholder="说明本阶段完成的研究任务、实验结果或交付物">${esc(form.stage_deliverables || "")}</textarea></label>`,
    sectionHead(
      `按需关联材料（选填）<span class="pm-sheet-meta" id="rp-artifact-count" style="margin-left:8px">${artifacts.length} / 20</span>`,
      `<button type="button" class="btn pbtn" id="add-artifact-btn">添加材料</button>`,
    ),
    `<div class="full quick-chips">${quickAddBtns}</div>`,
    `<div class="full" id="artifact-list">${artifactBody}</div>`,
  ].join("");
}

export function bindSoftwareCopyrightForm(formEl, esc) {
  const statusEl = formEl.querySelector("#sw-reg-status");
  if (!statusEl) return;
  const sync = (focusReg = false) => {
    const registered = statusEl.value === "registered";
    const panel = formEl.querySelector("#sw-reg-panel");
    const note = formEl.querySelector("#sw-reg-note");
    const uploadTitle = formEl.querySelector("#upload-section-title");
    if (panel) {
      panel.style.display = registered ? "" : "none";
      panel.classList.toggle("is-entering", registered);
    }
    if (note) note.style.display = registered ? "none" : "";
    if (uploadTitle) {
      uploadTitle.textContent = registered
        ? "证明材料（已登记必传，至少 1 份）"
        : "证明材料（当前状态选填）";
    }
    formEl.querySelectorAll(".sw-reg-only").forEach((wrap) => {
      wrap.style.display = registered ? "" : "none";
      const input = wrap.querySelector("input");
      if (!input) return;
      input.disabled = !registered;
      input.required = registered;
      if (!registered) input.value = "";
    });
    if (focusReg && registered) {
      formEl.querySelector('input[name="registration_number"]')?.focus();
    }
  };
  statusEl.onchange = () => sync(true);
  sync(false);
  bindQuickPeriods(formEl);
  bindCharCounters(formEl);
  if (esc) bindHolderPreview(formEl, esc);
}

export function bindResearchProjectForm(formEl, getFiles, esc) {
  bindRoleDetailToggle(formEl);
  const listEl = formEl.querySelector("#artifact-list");
  const countEl = formEl.querySelector("#rp-artifact-count");
  if (!listEl) return;
  const refreshRows = () =>
    bindArtifactRowEvents(listEl, countEl, ARTIFACT_EMPTY_HTML);
  const appendArtifact = (presetType = "experiment_report") => {
    if (listEl.querySelectorAll(".artifact-row").length >= 20) return;
    listEl.querySelector(".artifact-empty")?.remove();
    listEl.insertAdjacentHTML(
      "beforeend",
      renderArtifactRow({ artifact_type: presetType }, getFiles(), esc, true),
    );
    refreshRows();
    const last = listEl.querySelector(".artifact-row:last-child");
    last?.querySelector('[data-art="name"]')?.focus();
    last?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };
  const addBtn = formEl.querySelector("#add-artifact-btn");
  if (addBtn) addBtn.onclick = () => appendArtifact("experiment_report");
  formEl.querySelectorAll("[data-add-artifact]").forEach((btn) => {
    btn.onclick = () => appendArtifact(btn.dataset.addArtifact);
  });
  refreshRows();
  bindQuickPeriods(formEl);
  bindCharCounters(formEl);
}

export function extractSoftwareCopyrightForm(formData) {
  const status = String(formData.get("registration_status") || "unregistered");
  const payload = {
    metadata_version: 1,
    software_name: String(formData.get("software_name") || "").trim(),
    version: String(formData.get("version") || "").trim(),
    copyright_holders: parseCopyrightHolders(formData.get("copyright_holders")),
    development_work: String(formData.get("development_work") || "").trim(),
    registration_status: status,
    registration_number:
      status === "registered"
        ? String(formData.get("registration_number") || "").trim()
        : "",
    registration_date:
      status === "registered"
        ? String(formData.get("registration_date") || "").trim()
        : "",
  };
  const period = String(formData.get("period") || "").trim();
  if (period) payload.period = period;
  return payload;
}

export function extractResearchProjectForm(formEl, formData) {
  const rows = Array.from(formEl.querySelectorAll(".artifact-row"));
  const artifacts = rows
    .map((row) => ({
      artifact_type:
        row.querySelector('[data-art="artifact_type"]')?.value || "",
      name: (row.querySelector('[data-art="name"]')?.value || "").trim(),
      url: (row.querySelector('[data-art="url"]')?.value || "").trim(),
      file_id: (row.querySelector('[data-art="file_id"]')?.value || "").trim(),
      description: (
        row.querySelector('[data-art="description"]')?.value || ""
      ).trim(),
    }))
    .filter(
      (item) => item.name || item.url || item.file_id || item.description,
    );
  const payload = {
    metadata_version: 1,
    project_name: String(formData.get("project_name") || "").trim(),
    student_role: String(formData.get("student_role") || "").trim(),
    role_description: String(formData.get("role_description") || "").trim(),
    stage_deliverables: String(formData.get("stage_deliverables") || "").trim(),
    completion_date: String(formData.get("completion_date") || "").trim(),
    linked_artifacts: artifacts,
  };
  const period = String(formData.get("period") || "").trim();
  if (period) payload.period = period;
  return payload;
}

function renderArtifactDetailList(artifacts, files, esc) {
  if (!Array.isArray(artifacts) || !artifacts.length) {
    return '<div class="artifact-empty">未关联可选材料（实验报告、数据集、代码或原型不作为必填项）。</div>';
  }
  return artifacts
    .map((item) => {
      const typeKey = item.artifact_type || "experiment_report";
      const typeLabel = ARTIFACT_TYPE_LABELS[typeKey] || typeKey;
      const safeLink = safeHttpUrl(item.url);
      const linkedFile = item.file_id
        ? files.find((f) => f.id === item.file_id)
        : null;
      const linkHtml = safeLink
        ? `<a class="linkbtn" href="${esc(safeLink)}" target="_blank" rel="noopener noreferrer">打开外部链接 ↗</a>`
        : "";
      const fileHtml = linkedFile
        ? `<button class="linkbtn" data-action="file:${esc(linkedFile.id)}">下载关联附件 · ${esc(linkedFile.name)}</button>`
        : "";
      const actionsHtml =
        linkHtml || fileHtml
          ? `<div class="actions" style="margin-top:10px">${linkHtml}${fileHtml}</div>`
          : "";
      return `<div class="ach-artifact-card"><div class="ach-artifact-head"><span class="pm-field">${esc(typeLabel)}</span><strong>${esc(item.name)}</strong></div>${item.description ? `<p>${esc(item.description)}</p>` : ""}${actionsHtml}</div>`;
    })
    .join("");
}

function renderFactList(pairs, esc) {
  return `<dl class="facts">${pairs
    .filter(([, val]) => val)
    .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`)
    .join("")}</dl>`;
}

function softwareFactPairs(form, fallback = "") {
  const holders = Array.isArray(form.copyright_holders)
    ? form.copyright_holders.join("、")
    : String(form.copyright_holders || fallback);
  const status =
    REGISTRATION_STATUS_LABELS[form.registration_status] ||
    form.registration_status ||
    fallback;
  const pairs = [
    ["软件全称", form.software_name || fallback],
    ["版本号", form.version || fallback],
    ["著作权人", holders],
    ["登记状态", status],
  ];
  if (form.registration_status === "registered") {
    pairs.push(
      ["登记号", form.registration_number || fallback],
      ["登记日期", form.registration_date || fallback],
    );
  }
  if (form.period) pairs.push(["所属学年 / 周期", form.period]);
  if (form.software_copyright_key) {
    pairs.push(["核验指纹", String(form.software_copyright_key).slice(0, 12)]);
  }
  return pairs;
}

function projectFactPairs(form, fallback = "") {
  const roleLabel =
    STUDENT_ROLE_LABELS[form.student_role] || form.student_role || fallback;
  const roleText =
    roleLabel + (form.role_description ? `（${form.role_description}）` : "");
  const count = Array.isArray(form.linked_artifacts)
    ? form.linked_artifacts.length
    : 0;
  const pairs = [
    ["项目或课题名称", form.project_name || fallback],
    ["学生本人角色", roleText],
    ["完成时间", form.completion_date || fallback],
    ["可选关联材料", count ? `已关联 ${count} 项` : "未关联（选填）"],
  ];
  if (form.period) pairs.push(["所属学年 / 周期", form.period]);
  if (form.research_project_key) {
    pairs.push(["核验指纹", String(form.research_project_key).slice(0, 12)]);
  }
  return pairs;
}

export function renderAchievementDetail(kind, form, files, esc) {
  if (kind === "software_copyright") {
    return `${renderFactList(softwareFactPairs(form, "—"), esc)}<h3>学生承担的开发工作</h3><div class="ach-prose-card">${esc(form.development_work || "暂无填写")}</div>`;
  }
  if (kind === "research_project") {
    return `${renderFactList(projectFactPairs(form, "—"), esc)}<h3>本阶段完成的具体事项</h3><div class="ach-prose-card">${esc(form.stage_deliverables || "暂无填写")}</div><h3>关联材料（选填）</h3>${renderArtifactDetailList(form.linked_artifacts, files, esc)}`;
  }
  return "";
}

export function renderVersionStructuredFields(kind, form, esc, paperFormat) {
  if (kind === "software_copyright") {
    return renderFactList(
      [
        ...softwareFactPairs(form),
        ["学生承担的开发工作", form.development_work],
      ],
      esc,
    );
  }
  if (kind === "research_project") {
    const artifacts = Array.isArray(form.linked_artifacts)
      ? form.linked_artifacts
          .map(
            (a) =>
              `${ARTIFACT_TYPE_LABELS[a.artifact_type] || a.artifact_type}：${a.name}`,
          )
          .join("；")
      : "";
    return renderFactList(
      [
        ...projectFactPairs(form),
        ["本阶段完成的具体事项", form.stage_deliverables],
        ["关联材料", artifacts],
      ],
      esc,
    );
  }
  if (kind !== "paper") {
    return `<pre>${esc(JSON.stringify(form, null, 2))}</pre>`;
  }
  const { fieldLabels, formatValue } = paperFormat;
  const pairs = Object.entries(form)
    .filter(([key, value]) => Object.hasOwn(fieldLabels, key) && value)
    .map(([key, value]) => [fieldLabels[key], formatValue(value)]);
  return renderFactList(pairs, esc);
}
