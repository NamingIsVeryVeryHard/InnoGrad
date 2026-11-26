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
  fileRoleLabelsForKind,
  safeHttpUrl,
} from "./achievements-labels.js";

export {
  ALL_FILE_ROLE_LABELS,
  ARTIFACT_TYPE_LABELS,
  KIND_LABELS,
  KIND_SHORT_TITLES,
  REGISTRATION_STATUS_LABELS,
  STUDENT_ROLE_LABELS,
  fileRoleLabelsForKind,
  safeHttpUrl,
};

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

function holdersToText(holders) {
  if (Array.isArray(holders)) return holders.join("\n");
  return String(holders || "");
}

function buildOptions(entries, selected) {
  return entries
    .map(
      ([val, label]) =>
        `<option value="${val}" ${selected === val ? "selected" : ""}>${label}</option>`,
    )
    .join("");
}

export function renderSoftwareCopyrightFields(form, esc) {
  const status = form.registration_status || "unregistered";
  const isRegistered = status === "registered";
  const hiddenStyle = isRegistered ? "" : ' style="display:none"';
  const reqAttr = isRegistered ? "required" : "disabled";
  return [
    `<label class="full">软件全称<input name="software_name" value="${esc(form.software_name || form.title || "")}" required maxlength="200" placeholder="请输入软件全称"></label>`,
    `<label>版本号<input name="version" value="${esc(form.version || "")}" required maxlength="50" placeholder="如 V1.0"></label>`,
    `<label>登记状态<select name="registration_status" id="sw-reg-status" required>${buildOptions(Object.entries(REGISTRATION_STATUS_LABELS), status)}</select></label>`,
    `<label class="full">著作权人（每行或以逗号、顿号分隔一名）<textarea name="copyright_holders" required rows="3" placeholder="华东师范大学\n张三">${esc(holdersToText(form.copyright_holders))}</textarea></label>`,
    `<label class="sw-reg-only"${hiddenStyle}>登记号（已登记必填）<input name="registration_number" value="${esc(form.registration_number || "")}" ${reqAttr} maxlength="64" placeholder="如 2026SR1234567"></label>`,
    `<label class="sw-reg-only"${hiddenStyle}>登记日期（已登记必填）<input name="registration_date" type="date" value="${esc(form.registration_date || "")}" ${reqAttr}></label>`,
    `<label class="full">所属学年 / 周期（选填）<input name="period" value="${esc(form.period || "")}" maxlength="40" placeholder="如 2025—2026学年"></label>`,
    `<label class="full">学生承担的开发工作<textarea name="development_work" required rows="4" maxlength="4000" placeholder="请具体说明本人承担的架构设计、核心模块编码、测试验证等工作">${esc(form.development_work || "")}</textarea></label>`,
  ].join("");
}

function renderArtifactRow(item, files, esc) {
  const selectedType = item.artifact_type || "experiment_report";
  const fileOptions = [
    `<option value="">不关联已上传附件</option>`,
    ...files.map(
      (f) =>
        `<option value="${esc(f.id)}" ${item.file_id === f.id ? "selected" : ""}>${esc(f.name)}</option>`,
    ),
  ].join("");
  return `<div class="evidence artifact-row" style="margin-top:10px;padding:12px"><div class="form-grid"><label>材料类别<select data-art="artifact_type">${buildOptions(Object.entries(ARTIFACT_TYPE_LABELS), selectedType)}</select></label><label>材料名称<input data-art="name" value="${esc(item.name || "")}" maxlength="200" required placeholder="如 消融实验报告 v1"></label><label class="full">访问链接（选填，仅支持 http/https）<input data-art="url" type="url" value="${esc(item.url || "")}" maxlength="2000" placeholder="https://..."></label><label class="full">关联本次上传附件（选填）<select data-art="file_id">${fileOptions}</select></label><label class="full">简要说明（选填）<input data-art="description" value="${esc(item.description || "")}" maxlength="500" placeholder="补充说明版本、范围或使用方式"></label></div><button type="button" class="linkbtn" data-remove-artifact style="margin-top:8px">移除此关联材料</button></div>`;
}

export function renderResearchProjectFields(form, files, esc) {
  const roleVal = form.student_role || "core_member";
  const artifacts = Array.isArray(form.linked_artifacts)
    ? form.linked_artifacts
    : [];
  const roleDetailReq = roleVal === "other" ? "required" : "";
  return [
    `<label class="full">项目或课题名称<input name="project_name" value="${esc(form.project_name || form.title || "")}" required maxlength="200" placeholder="请输入项目或课题全称"></label>`,
    `<label>学生本人角色<select name="student_role" id="rp-student-role" required>${buildOptions(Object.entries(STUDENT_ROLE_LABELS), roleVal)}</select></label>`,
    `<label>完成时间<input name="completion_date" type="date" value="${esc(form.completion_date || "")}" required></label>`,
    `<label class="full">角色补充说明（选“其他”时必填）<input name="role_description" id="rp-role-detail" value="${esc(form.role_description || "")}" ${roleDetailReq} maxlength="100" placeholder="如 数据管线负责人、前端交互开发"></label>`,
    `<label class="full">所属学年 / 周期（选填）<input name="period" value="${esc(form.period || "")}" maxlength="40" placeholder="如 2025—2026学年"></label>`,
    `<label class="full">本阶段完成的具体事项<textarea name="stage_deliverables" required rows="4" maxlength="4000" placeholder="请具体说明本阶段完成的研究任务、实验结果或系统交付">${esc(form.stage_deliverables || "")}</textarea></label>`,
    `<div class="full"><div style="display:flex;justify-content:space-between;align-items:center;gap:12px"><span>按需关联材料（实验报告、数据集、代码或原型，选填）</span><button type="button" class="btn" id="add-artifact-btn">+ 添加关联材料</button></div><div id="artifact-list">${artifacts.map((item) => renderArtifactRow(item, files, esc)).join("")}</div></div>`,
  ].join("");
}

export function bindSoftwareCopyrightForm(formEl) {
  const statusEl = formEl.querySelector("#sw-reg-status");
  if (!statusEl) return;
  const sync = () => {
    const registered = statusEl.value === "registered";
    formEl.querySelectorAll(".sw-reg-only").forEach((wrap) => {
      wrap.style.display = registered ? "" : "none";
      const input = wrap.querySelector("input");
      if (!input) return;
      input.disabled = !registered;
      input.required = registered;
      if (!registered) input.value = "";
    });
  };
  statusEl.onchange = sync;
  sync();
}

export function bindResearchProjectForm(formEl, getFiles, esc) {
  const roleEl = formEl.querySelector("#rp-student-role");
  const detailEl = formEl.querySelector("#rp-role-detail");
  if (roleEl && detailEl) {
    const syncRole = () => {
      detailEl.required = roleEl.value === "other";
    };
    roleEl.onchange = syncRole;
    syncRole();
  }
  const listEl = formEl.querySelector("#artifact-list");
  const addBtn = formEl.querySelector("#add-artifact-btn");
  if (!listEl || !addBtn) return;
  const bindRowRemovers = () => {
    listEl.querySelectorAll("[data-remove-artifact]").forEach((btn) => {
      btn.onclick = () => btn.closest(".artifact-row")?.remove();
    });
  };
  addBtn.onclick = () => {
    if (listEl.querySelectorAll(".artifact-row").length >= 20) return;
    listEl.insertAdjacentHTML(
      "beforeend",
      renderArtifactRow({}, getFiles(), esc),
    );
    bindRowRemovers();
  };
  bindRowRemovers();
}

export function syncResearchProjectFileOptions(formEl, files, esc) {
  const selects = formEl.querySelectorAll('.artifact-row [data-art="file_id"]');
  selects.forEach((select) => {
    const prev = select.value;
    select.innerHTML = [
      `<option value="">不关联已上传附件</option>`,
      ...files.map(
        (f) =>
          `<option value="${esc(f.id)}" ${prev === f.id ? "selected" : ""}>${esc(f.name)}</option>`,
      ),
    ].join("");
  });
}

export function extractSoftwareCopyrightForm(formData) {
  const status = String(formData.get("registration_status") || "unregistered");
  const holders = String(formData.get("copyright_holders") || "")
    .split(/[\r\n,，、;；]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  const payload = {
    metadata_version: 1,
    software_name: String(formData.get("software_name") || "").trim(),
    version: String(formData.get("version") || "").trim(),
    copyright_holders: holders,
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
    return '<p class="muted">未关联可选材料（实验报告、数据集、代码或原型不作为必填项）。</p>';
  }
  return artifacts
    .map((item) => {
      const typeLabel =
        ARTIFACT_TYPE_LABELS[item.artifact_type] || item.artifact_type;
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
      return `<div class="evidence"><strong>${esc(typeLabel)} · ${esc(item.name)}</strong>${item.description ? `<p>${esc(item.description)}</p>` : ""}<div class="actions" style="margin-top:6px">${linkHtml}${fileHtml}</div></div>`;
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
  return pairs;
}

function projectFactPairs(form, fallback = "") {
  const roleLabel =
    STUDENT_ROLE_LABELS[form.student_role] || form.student_role || fallback;
  const roleText =
    roleLabel + (form.role_description ? `（${form.role_description}）` : "");
  return [
    ["项目或课题名称", form.project_name || fallback],
    ["学生本人角色", roleText],
    ["完成时间", form.completion_date || fallback],
  ];
}

export function renderAchievementDetail(kind, form, files, esc) {
  if (kind === "software_copyright") {
    return `${renderFactList(softwareFactPairs(form, "—"), esc)}<h3>学生承担的开发工作</h3><p style="white-space:pre-wrap;margin:12px 0;color:#70816c">${esc(form.development_work || "")}</p>`;
  }
  if (kind === "research_project") {
    return `${renderFactList(projectFactPairs(form, "—"), esc)}<h3>本阶段完成的具体事项</h3><p style="white-space:pre-wrap;margin:12px 0;color:#70816c">${esc(form.stage_deliverables || "")}</p><h3>关联材料（选填）</h3>${renderArtifactDetailList(form.linked_artifacts, files, esc)}`;
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
