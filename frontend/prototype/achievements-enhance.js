/**
 * Interactive UX enhancements for software copyright (#25) and research project (#26) forms:
 * live holder chips, character counters, quick period pills, drag-and-drop upload,
 * keyboard shortcuts, dirty tracking, and concise list-row summaries.
 */

import {
  ARTIFACT_TYPE_LABELS,
  REGISTRATION_STATUS_LABELS,
  STUDENT_ROLE_LABELS,
} from "./achievements-labels.js";

export const QUICK_PERIODS = ["2025—2026学年", "2026—2027学年"];

export function parseCopyrightHolders(raw) {
  const seen = new Set();
  const list = [];
  String(raw || "")
    .split(/[\r\n,，、;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .forEach((name) => {
      if (!seen.has(name)) {
        seen.add(name);
        list.push(name);
      }
    });
  return list;
}

export function defaultFileRoleForSubmission(kind, form = {}) {
  if (kind === "software_copyright") {
    if (form.registration_status === "registered") {
      return "copyright_certificate";
    }
    if (form.registration_status === "applying") {
      return "registration_application";
    }
    return "source_code_doc";
  }
  if (kind === "research_project") return "experiment_report";
  if (kind === "paper") return "paper_fulltext";
  return "other_proof";
}

export function achievementRowMeta(record) {
  const form = record.form || {};
  const parts = [];
  if (record.kind === "software_copyright") {
    if (form.version) parts.push(form.version);
    const status =
      REGISTRATION_STATUS_LABELS[form.registration_status] || "未登记";
    parts.push(status);
    if (form.registration_status === "registered" && form.registration_number) {
      parts.push(form.registration_number);
    }
    if (record.files?.length) parts.push(`${record.files.length} 份附件`);
    return parts.join(" · ");
  }
  if (record.kind === "research_project") {
    if (form.student_role) {
      parts.push(STUDENT_ROLE_LABELS[form.student_role] || form.student_role);
    }
    if (form.completion_date) parts.push(form.completion_date);
    const artCount = Array.isArray(form.linked_artifacts)
      ? form.linked_artifacts.length
      : 0;
    if (artCount) parts.push(`${artCount} 项关联材料`);
    if (record.files?.length) parts.push(`${record.files.length} 份附件`);
    return parts.join(" · ") || "科研项目 · 工作稿";
  }
  const ver = record.versions?.length ? `V${record.versions.length}` : "工作稿";
  return `${record.kind === "paper" ? "论文成果" : "年度报告"} · ${ver}`;
}

export function bindCharCounters(formEl) {
  formEl.querySelectorAll("[data-counter]").forEach((field) => {
    const out = formEl.querySelector(`[data-counter-for="${field.name}"]`);
    if (!out) return;
    const max = Number(field.getAttribute("maxlength") || 4000);
    const sync = () => {
      const len = field.value.length;
      out.textContent = `${len} / ${max}`;
      out.classList.toggle("is-near-limit", len > max * 0.9);
    };
    field.addEventListener("input", sync);
    sync();
  });
}

export function bindQuickPeriods(formEl) {
  const input = formEl.querySelector('input[name="period"]');
  if (!input) return;
  formEl.querySelectorAll("[data-quick-period]").forEach((btn) => {
    btn.onclick = () => {
      input.value = btn.dataset.quickPeriod || "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.focus();
    };
  });
}

export function bindHolderPreview(formEl, esc) {
  const input = formEl.querySelector('textarea[name="copyright_holders"]');
  const box = formEl.querySelector("#sw-holders-preview");
  if (!input || !box) return;
  const sync = () => {
    const names = parseCopyrightHolders(input.value);
    if (!names.length) {
      box.innerHTML = "";
      return;
    }
    const chips = names
      .slice(0, 8)
      .map((name) => `<span class="holder-chip">${esc(name)}</span>`)
      .join("");
    const extra =
      names.length > 8
        ? `<span class="holder-chip">+${names.length - 8}</span>`
        : "";
    box.innerHTML = `${chips}${extra}<span class="holder-count">共 ${names.length} 名</span>`;
  };
  input.addEventListener("input", sync);
  sync();
}

export function bindUploadDropzone(dropEl, inputEl, onFiles) {
  if (!dropEl || !inputEl) return;
  const setOver = (flag) => dropEl.classList.toggle("is-dragover", flag);
  ["dragenter", "dragover"].forEach((ev) => {
    dropEl.addEventListener(ev, (e) => {
      e.preventDefault();
      setOver(true);
    });
  });
  ["dragleave", "dragend"].forEach((ev) => {
    dropEl.addEventListener(ev, () => setOver(false));
  });
  dropEl.addEventListener("drop", (e) => {
    e.preventDefault();
    setOver(false);
    const files = Array.from(e.dataTransfer?.files || []);
    if (files.length) onFiles(files);
  });
}

export function bindFormShortcutsAndDirty(formEl, dialogEl) {
  const dirtyEl = dialogEl?.querySelector("#form-dirty-state");
  const markDirty = () => {
    if (dirtyEl) dirtyEl.hidden = false;
  };
  formEl.addEventListener("input", markDirty);
  formEl.addEventListener("change", markDirty);
  formEl.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      const draftBtn = dialogEl?.querySelector('button[value="draft"]');
      if (draftBtn && !draftBtn.disabled) draftBtn.click();
    }
  });
}

export function bindRoleDetailToggle(formEl) {
  const roleEl = formEl.querySelector("#rp-student-role");
  const detailEl = formEl.querySelector("#rp-role-detail");
  if (!roleEl || !detailEl) return;
  const syncRole = (focusDetail = false) => {
    const isOther = roleEl.value === "other";
    detailEl.required = isOther;
    const mark = formEl.querySelector(
      "#rp-role-detail-wrap .req-mark, #rp-role-detail-wrap .opt-text",
    );
    if (mark) {
      mark.className = isOther ? "req-mark" : "opt-text";
      mark.textContent = isOther ? "*" : "选填";
    }
    if (focusDetail && isOther) detailEl.focus();
  };
  roleEl.onchange = () => syncRole(true);
  syncRole(false);
}

export function holdersToText(holders) {
  if (Array.isArray(holders)) return holders.join("\n");
  return String(holders || "");
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

export function bindArtifactRowEvents(listEl, countEl, emptyHtml) {
  const syncCount = () => {
    const n = listEl.querySelectorAll(".artifact-row").length;
    if (countEl) countEl.textContent = `${n} / 20`;
  };
  listEl.querySelectorAll(".artifact-row").forEach((row) => {
    const sel = row.querySelector('[data-art="artifact_type"]');
    const title = row.querySelector(".artifact-row-title");
    if (sel && title) {
      sel.onchange = () => {
        title.textContent = ARTIFACT_TYPE_LABELS[sel.value] || "关联材料";
      };
    }
    const rm = row.querySelector("[data-remove-artifact]");
    if (rm) {
      rm.onclick = () => {
        row.classList.add("is-leaving");
        setTimeout(() => {
          row.remove();
          if (!listEl.querySelector(".artifact-row")) {
            listEl.innerHTML = emptyHtml;
          }
          syncCount();
        }, 150);
      };
    }
  });
  syncCount();
}
