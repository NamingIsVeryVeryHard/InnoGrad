import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

const unique = values => [...new Set(values)];
const compact = value => value.replace(/\s+/gu, '');
const fail = message => { throw new Error(message); };
const unknown = () => ({ status: 'unknown', value: null, source_refs: [] });

export async function loadRealCase(manifestPath) {
  const path = resolve(manifestPath);
  const manifest = JSON.parse(await readFile(path, 'utf8'));
  if (!Array.isArray(manifest.materials)) fail('manifest 缺少 materials');
  const materials = [];
  for (const entry of manifest.materials) {
    const read = async key => JSON.parse(await readFile(resolve(dirname(path), entry[key]), 'utf8'));
    const request = await read('bundle');
    materials.push({ id: entry.id, role: entry.role, bundle: request.bundle ?? request, portrait: await read('portrait') });
  }
  return { manifest, materials };
}

function atPointer(object, pointer) {
  if (typeof pointer !== 'string' || !pointer.startsWith('/')) fail('画像来源 pointer 无效');
  let value = object;
  for (const part of pointer.slice(1).split('/')) {
    const key = part.replaceAll('~1', '/').replaceAll('~0', '~');
    if (!value || !Object.hasOwn(value, key)) fail('画像来源 pointer 不存在');
    value = value[key];
  }
  if (!value || typeof value !== 'object') fail('画像来源未指向记录');
  return value;
}

export function analyzeRealCase({ manifest, materials }) {
  if (manifest?.schema_version !== 'portrait-history-real-1' ||
      !['real_materials', 'test_fixture'].includes(manifest.data_nature) || !manifest.student_id) fail('manifest 格式错误');
  if (!Array.isArray(materials) || materials.filter(m => m.role === 'current').length !== 1 ||
      !materials.some(m => m.role === 'reference')) fail('需要一个当前材料和参照材料');
  const sourceIndex = [], indexed = new Map(), models = new Map();
  for (const material of materials) {
    if (!/^[a-zA-Z0-9-]+$/.test(material.id) || models.has(material.id) ||
        !['current', 'reference'].includes(material.role)) fail('材料 ID 或角色无效');
    const { bundle, portrait } = material;
    if (bundle?.schema_version !== '1.0' || portrait?.schema_version !== '2.0') fail('仅支持 bundle 1.0 与 portrait 2.0');
    if (bundle.student_id !== manifest.student_id || portrait.student_id !== manifest.student_id) fail('学生身份不一致');
    if (bundle.stage !== portrait.stage || bundle.period !== portrait.period) fail('画像与 bundle 任务范围不一致');
    const docs = new Map(), declared = new Set();
    for (const doc of bundle.documents) {
      if (doc.student_id !== manifest.student_id) fail('文档学生身份不一致');
      if (!doc.document_id || docs.has(doc.document_id) || !/^[a-f0-9]{64}$/i.test(doc.sha256)) fail('文档 ID 或 hash 无效');
      const state = bundle.input_context?.sources?.find(s => s.document_id === doc.document_id);
      if (state?.authorization === 'denied' ||
          ['withdrawn', 'superseded', 'disputed'].includes(state?.validity)) fail('unavailable source');
      if (new Set(doc.segments.map(s => s.segment_id)).size !== doc.segments.length) fail('重复页段');
      docs.set(doc.document_id, doc);
    }
    for (const s of portrait.sources) {
      const doc = docs.get(s.document_id);
      if (!doc || doc.sha256 !== s.sha256 || declared.has(s.document_id)) fail('画像与 bundle 文档 ID/hash 不匹配');
      declared.add(s.document_id);
      for (const page of s.pages ?? []) {
        const segment = doc.segments.find(s => s.segment_id === page.segment_id);
        if (!segment || segment.page !== page.page) fail('画像来源页段不匹配');
      }
    }
    if (!docs.size || declared.size !== docs.size) fail('画像未覆盖 bundle 文档来源');
    const locate = evidence => {
      const doc = docs.get(evidence.document_id), segment = doc?.segments.find(s => s.segment_id === evidence.segment_id);
      if (!segment || typeof evidence.quote !== 'string' || !compact(evidence.quote) ||
          !compact(segment.text).includes(compact(evidence.quote))) fail(`引文无法定位：${material.id}/${evidence.segment_id ?? '?'}`);
      if ((evidence.page !== undefined && evidence.page !== segment.page) ||
          (evidence.sha256 !== undefined && evidence.sha256 !== doc.sha256)) fail('引文页码或 hash 不匹配');
      const key = JSON.stringify([material.id, doc.document_id, segment.segment_id, evidence.quote]);
      if (!indexed.has(key)) {
        const id = `${material.id}:E${sourceIndex.length + 1}`;
        indexed.set(key, id);
        sourceIndex.push({ id, material_id: material.id, document_id: doc.document_id, sha256: doc.sha256,
          segment_id: segment.segment_id, page: segment.page, quote: evidence.quote, segment_text: segment.text });
      }
      return indexed.get(key);
    };
    // Check every original quote, retaining punctuation and wording; ignore whitespace only.
    const evidenceRefs = value => {
      if (!value || typeof value !== 'object') return [];
      const refs = Object.hasOwn(value, 'quote') && value.document_id && value.segment_id ? [locate(value)] : [];
      for (const child of Object.values(value)) refs.push(...evidenceRefs(child));
      return unique(refs);
    };
    evidenceRefs(portrait);
    const criteria = new Map();
    for (const dimension of portrait.implicit.dimensions) for (const c of dimension.criteria) {
      if (!c.criterion_id || criteria.has(c.criterion_id)) fail('重复或无效评价项');
      criteria.set(c.criterion_id, { original: c, source_refs: evidenceRefs(c) });
    }
    const records = new Map();
    for (const r of portrait.synthesis_sources ?? []) {
      if (!r.id || records.has(r.id)) fail('画像来源 ID 重复或无效');
      const record = atPointer(portrait, r.pointer);
      records.set(r.id, { record, source_refs: evidenceRefs(record) });
    }
    const resolveRefs = refs => {
      if (!Array.isArray(refs) || refs.some(id => !records.has(id))) fail('上游 source_refs 引用不存在');
      return unique(refs.flatMap(id => records.get(id).source_refs));
    };
    const sections = {};
    for (const [section, claims] of Object.entries(portrait.synthesis ?? {})) sections[section] = claims.map(item => {
      const adapted = {text: item.text, source_refs: resolveRefs(item.source_refs), upstream_ref_ids: [...item.source_refs]};
      if (item.completion_evidence !== undefined) adapted.completion_evidence = item.completion_evidence;
      if (section === 'research_features') {
        if (item.basis !== undefined) adapted.basis = item.basis;
        if (item.rationale !== undefined) adapted.rationale = item.rationale;
      }
      return adapted;
    });
    models.set(material.id, { material, criteria, records, resolveRefs, sections, locate });
  }
  const current = [...models.values()].find(m => m.material.role === 'current');
  const references = [...models.values()].filter(m => m.material.role === 'reference');
  const selected = manifest.selected ?? {};
  const selection = key => {
    const value = selected[key];
    if (!value) return unknown();
    if (value.material_id !== current.material.id) fail('人工选取记录必须属于当前材料');
    return { status: 'documented', value: value.quote, source_refs: [current.locate(value)] };
  };
  const focusIds = manifest.focus_criteria ?? ['validation-design'];
  if (!Array.isArray(focusIds) || focusIds.some(id => !current.criteria.has(id))) fail('重点评价项不存在');
  const snapshot = (model, id) => {
    const c = model.criteria.get(id);
    if (!c) return null;
    const { evidence_state, performance_grade, work_status, rationale, observed, limitations = [], suggestions, missing_evidence } = c.original;
    return structuredClone({ material_id: model.material.id, criterion_id: id, evidence_state, performance_grade,
      work_status, rationale, observed, limitations, suggestions, missing_evidence, source_refs: c.source_refs });
  };
  const comparisons = [];
  for (const reference of references) for (const id of unique([...focusIds, ...reference.criteria.keys(), ...current.criteria.keys()])) {
    const previous = snapshot(reference, id), now = snapshot(current, id);
    comparisons.push({ criterion_id: id,
      label: current.criteria.get(id)?.original.criterion_label ?? reference.criteria.get(id)?.original.criterion_label ?? id,
      reference: previous, current: now,
      source_refs: unique([...(previous?.source_refs ?? []), ...(now?.source_refs ?? [])]),
      limitation: '任务和材料范围可能不同，保留原评定；不据此认定能力成长、材料先后或建议执行。' });
  }
  const recommendations = [];
  for (const id of unique(focusIds)) {
    const c = current.criteria.get(id), suggestions = c.original.suggestions.filter(s => s.trim() && s.trim() !== '无');
    if (!suggestions.length && !c.original.missing_evidence.length) continue;
    recommendations.push({ origin: 'current_criterion', criterion_id: id,
      action: `${c.original.evidence_state === 'evaluable' ? '先核对现有方案，再推进本项已记录的缺口：' : '先核对当前材料，再处理本项已记录的缺口：'}${suggestions.join('；') || c.original.missing_evidence.join('；')}`,
      source_refs: [...c.source_refs], suggestions: [...suggestions], missing_evidence: [...c.original.missing_evidence],
      completion_evidence: `修订材料逐项说明：${c.original.missing_evidence.join('；') || suggestions.join('；')}` });
  }
  for (const item of current.sections.next_steps ?? []) recommendations.push({
    origin: 'current_upstream_next_step', action: item.text, completion_evidence: item.completion_evidence,
    source_refs: [...item.source_refs], upstream_ref_ids: [...item.upstream_ref_ids] });
  const followUp = [];
  for (const reference of references) for (const item of reference.material.portrait.synthesis?.next_steps ?? []) {
    const matches = unique(item.source_refs.map(id => reference.records.get(id).record.criterion_id).filter(Boolean))
      .map(id => snapshot(current, id)).filter(Boolean);
    const found = matches.some(c => c.evidence_state === 'evaluable' && c.source_refs.length);
    followUp.push({ reference_material_id: reference.material.id, recommendation: item.text,
      completion_evidence: item.completion_evidence, criterion_matches: matches,
      status: found ? 'related_material_found' : 'no_completion_conclusion',
      label: found ? '发现相关材料，需核对具体完成依据' : '未取得完成结论，需核对材料或任务适用范围',
      previous_source_refs: reference.resolveRefs(item.source_refs),
      source_refs: unique([...reference.resolveRefs(item.source_refs), ...matches.flatMap(c => c.source_refs)]),
      accepted: 'unknown', executed: 'unknown',
      explanation: '对应的是既有材料与现在生成的旧建议；不能据此认定学生采纳或执行。材料先后、建议送达与学生反馈均未确认。' });
  }
  return {
    schema_version: 'portrait-history-result-1', student_id: manifest.student_id,
    provenance: { data_nature: manifest.data_nature, synthetic: manifest.data_nature === 'test_fixture',
      engine: 'local-evidence-adapter-v1', model_called: false,
      description: '本地规则适配已有画像与原文，不重新评分，不执行模型推理；非 TRIPLE 复现。' },
    materials: materials.map(m => ({ id: m.id, role: m.role, stage: m.bundle.stage, period: m.bundle.period,
      original_producer: structuredClone(m.portrait.provenance?.producer ?? null) })),
    current_portrait: { material_id: current.material.id, sections: current.sections },
    profile: { behavior_patterns: { status: 'unknown', events: [], source_refs: [], explanation: '未提供独立行为事件，不能推断稳定习惯或行动顺序。' },
      intention: { goal: selection('current_goal'), attitude: unknown(), perceived_expectations: unknown(), perceived_control: unknown(), difficulty: unknown() },
      context: { stage: current.material.bundle.stage, period: current.material.bundle.period, actual_resources: unknown(),
        schedule: selection('schedule'), resource_requirements: selection('resource_requirements'),
        explanation: '计划和资源需求不等于实际可用条件；任务计算复杂度不等于学生个人困难。' } },
    changes: { chronology: 'unknown', growth_score: null,
      explanation: '当前与参照是本次比较角色，不表示发生先后。旧材料的现有画像不是当时已送达的建议。' },
    comparisons, recommendations, follow_up: followUp, source_index: sourceIndex,
    upstream_integrity: '原画像保留在输入包中；本次不修改原评价、原建议或原始材料。',
  };
}

export function formatMarkdown(result) {
  const lines = ['# 真实材料画像对应与建议', '', result.provenance.description,
    '', `学生标识：${result.student_id}；数据性质：${result.provenance.data_nature}`, '', result.changes.explanation];
  const write = text => lines.push(text);
  const refs = item => item.source_refs.length ? `〔${item.source_refs.join('，')}〕` : '〔原文证据未提供〕';
  write('\n## 当前已有画像（保留原文）');
  for (const [section, items] of Object.entries(result.current_portrait.sections)) {
    write(`\n### ${section}`);
    for (const item of items) write(`\n- ${item.text} ${refs(item)}${item.basis ? `\n  依据性质：${item.basis}` : ''}${item.rationale ? `\n  推断解释：${item.rationale}` : ''}${item.completion_evidence ? `\n  完成依据：${item.completion_evidence}` : ''}`);
  }
  write('\n## 意图与实际情境');
  for (const [key, label] of Object.entries({ goal: '材料明确写出的研究目标', attitude: '态度', perceived_expectations: '感知他人期望', perceived_control: '主观控制感', difficulty: '个人困难' })) {
    const item = result.profile.intention[key];
    write(`\n- ${label}：${item.value ?? 'unknown（没有明确自述）'} ${refs(item)}`);
  }
  write(`\n- 实际可用资源：unknown。${result.profile.context.explanation}`);
  write(`\n- 任务：${result.profile.context.stage}；材料期间：${result.profile.context.period ?? '未知'}。`);
  for (const [key, label] of [['schedule', '进度计划'], ['resource_requirements', '资源计划或需求']]) {
    const item = result.profile.context[key];
    write(`\n- ${label}：${item.value ?? '未人工选取，不作抽取推断'} ${refs(item)}`);
  }
  write(`\n- 历史行为模式：unknown。${result.profile.behavior_patterns.explanation}`);
  write('\n## 材料逐项对应（保留原评定）');
  for (const item of result.comparisons) {
    const describe = c => c ? `${c.material_id} / ${c.evidence_state} / ${c.performance_grade ?? '未定级'} / ${c.work_status ?? 'unknown'}` : '无同名评价项';
    write(`\n### ${item.label} / ${item.criterion_id}\n\n- 参照：${describe(item.reference)}\n- 当前：${describe(item.current)}`);
    write(`- ${item.limitation} ${refs(item)}`);
    if (item.current?.missing_evidence.length) write(`- 当前未提供：${item.current.missing_evidence.join('；')}`);
  }
  write('\n## 依据当前缺口的建议');
  for (const [index, item] of result.recommendations.entries()) write(`\n${index + 1}. ${item.action} ${refs(item)}\n   完成依据：${item.completion_evidence}`);
  write('\n## 旧建议与相关材料（不是执行反馈）');
  for (const item of result.follow_up) write(`\n- 旧建议：${item.recommendation}\n- 原完成依据：${item.completion_evidence}\n- 对应状态：${item.label} ${refs(item)}\n- ${item.explanation}\n- 学生采纳：unknown；执行状态：unknown。`);
  write('\n## 来源索引');
  for (const s of result.source_index) write(`\n### ${s.id}\n\n材料 ${s.material_id} / 文档 ${s.document_id} / 第 ${s.page ?? '未知'} 页 / 段 ${s.segment_id}\n\n> ${s.quote.replaceAll('\n', '\n> ')}`);
  return lines.join('\n') + '\n';
}
