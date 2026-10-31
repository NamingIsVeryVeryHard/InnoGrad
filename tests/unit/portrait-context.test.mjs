import test from 'node:test';
import assert from 'node:assert/strict';
import {fixture} from '../fixtures/portrait.mjs';
import {buildPortrait, buildAResult} from '../../skills/graduate-portrait/scripts/engine.mjs';
import {validateBundle, validateShape} from '../../skills/graduate-portrait/scripts/validation.mjs';
import {portraitSchema} from '../../skills/graduate-portrait/scripts/portrait-schema.mjs';
import {prepareSynthesisTask} from '../../skills/graduate-portrait/scripts/synthesis.mjs';
import {renderPortrait} from '../../skills/graduate-portrait/scripts/report.mjs';

export function inputContext(bundle) {
  return {
    snapshot_id: 'snapshot-synthetic-1', statistics_cutoff_at: '2026-10-22T12:00:00Z',
    trigger: 'corrected',
    sources: bundle.documents.map(d => ({
      document_id: d.document_id, source_version: 'v2',
      authorization: 'authorized', validity: 'active', review_status: 'confirmed',
    })),
  };
}
const metadata = {output_version: 'synthetic-1', generated_at: '2026-10-22T12:00:00Z',
  producer: {mode: 'synthetic', name: null, model: null}};

test('旧输入保留未知来源状态，不默认为事实已确认', () => {
  const p = buildPortrait(fixture());
  assert.equal(p.input_context, null);
  assert.ok(p.warnings.includes('input_context_unknown'));
  assert.doesNotMatch(renderPortrait(p), /## 本次输入快照/);
  assert.ok(p.implicit.dimensions.every(d => d.review_required === false));
  validateShape(portraitSchema, p, 'portrait');
  assert.equal(p.review_status, 'draft');
});

test('同一次输入上下文原样传给整合和报告，文档复核不升级事实或解释状态', () => {
  const f = fixture();
  f.bundle.input_context = inputContext(f.bundle);
  const before = structuredClone(f);
  const p = buildPortrait(f);
  validateShape(portraitSchema, p, 'portrait');
  assert.deepEqual(p.input_context, f.bundle.input_context);
  assert.deepEqual(prepareSynthesisTask(p).context.input_context, f.bundle.input_context);
  assert.equal(p.review_status, 'draft');
  assert.equal(p.explicit.metrics.papers_reported.verification, 'material_report');
  assert.equal(p.implicit.dimensions[0].criteria[0].review.status, 'pending');
  const report = renderPortrait(p);
  assert.match(report, /snapshot-synthetic-1/);
  assert.match(report, /2026-10-22T12:00:00Z/);
  assert.match(report, /^# 研究生画像\n/);
  assert.match(report, /文档复核声明/);
  assert.match(report, /已复核/);
  assert.doesNotMatch(report, /待教师确认|教师复核待完成|待人工复核/);
  p.input_context.sources[0].source_version = 'changed';
  assert.deepEqual(f, before);
});

test('上下文完整绑定输入文档，拒绝重复、多余、遗漏与无效日期', () => {
  for (const mutate of [
    c => { c.sources.push(structuredClone(c.sources[0])); },
    c => { c.sources[0].document_id = 'missing'; },
    c => { c.sources = []; },
    c => { c.statistics_cutoff_at = '2026-02-30T12:00:00Z'; },
  ]) {
    const f = fixture(); f.bundle.input_context = inputContext(f.bundle);
    mutate(f.bundle.input_context);
    assert.throws(() => validateBundle(f.bundle));
  }
});

test('不允许明确未授权、撤销、被替代或争议来源进入当前评价快照', () => {
  for (const state of [
    {authorization: 'denied'}, {validity: 'withdrawn'},
    {validity: 'superseded'}, {validity: 'disputed'},
  ]) {
    const f = fixture(); f.bundle.input_context = inputContext(f.bundle);
    Object.assign(f.bundle.input_context.sources[0], state);
    assert.throws(() => buildPortrait(f));
  }
});

test('未知声明可以保留，警示不可替代正式授权与事实核验', () => {
  const f = fixture(); f.bundle.input_context = inputContext(f.bundle);
  Object.assign(f.bundle.input_context.sources[0],
    {authorization: 'unknown', validity: 'unknown', review_status: 'unknown'});
  const p = buildPortrait(f);
  for (const code of ['source_authorization_unknown', 'source_validity_unknown', 'source_review_unknown']) {
    assert.ok(p.warnings.includes(code));
  }
});

test('正文未变但快照、截止时间、培养背景或来源状态变化时拒绝复用旧显性结果', () => {
  for (const mutate of [
    f => { f.bundle.input_context.snapshot_id = 'snapshot-synthetic-2'; },
    f => { f.bundle.input_context.statistics_cutoff_at = '2026-10-23T12:00:00Z'; },
    f => { f.bundle.input_context.sources[0].review_status = 'pending'; },
    f => { f.bundle.input_context.sources[0].source_version = 'v3'; },
    f => { f.bundle.task_context = {task_id: null, observation_period: null,
      training_category: '专业硕士', training_year: 2, support_conditions: null}; },
  ]) {
    const f = fixture(); f.bundle.input_context = inputContext(f.bundle);
    const aResult = buildAResult({...f, metadata});
    const before = buildPortrait({...f, aResult, extraction: undefined});
    mutate(f);
    assert.throws(() => buildPortrait({...f, aResult, extraction: undefined}));
    assert.notEqual(buildPortrait(f).run_id, before.run_id);
    const fresh = buildAResult({...f, metadata});
    assert.doesNotThrow(() => buildPortrait({...f, aResult: fresh, extraction: undefined}));
  }
});

test('没有上下文的旧交接只兼容旧快照，新旧上下文不能混用', () => {
  const f = fixture(); const legacy = buildAResult({...f, metadata});
  assert.doesNotThrow(() => buildPortrait({...f, aResult: legacy, extraction: undefined}));
  f.bundle.input_context = inputContext(f.bundle);
  assert.throws(() => buildPortrait({...f, aResult: legacy, extraction: undefined}));
  const current = buildAResult({...f, metadata});
  delete f.bundle.input_context;
  assert.throws(() => buildPortrait({...f, aResult: current, extraction: undefined}));
});
