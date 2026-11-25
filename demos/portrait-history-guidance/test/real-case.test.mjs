import test from 'node:test';
import assert from 'node:assert/strict';
import { fixture } from './fixtures/case.mjs';
import { analyzeRealCase, formatMarkdown } from '../src/real-case.mjs';

test('保留原画像和评定，生成逐项对应，不修改输入或推断成长', () => {
  const input = fixture(), before = structuredClone(input);
  const result = analyzeRealCase(input);
  assert.deepEqual(input, before);
  assert.equal(result.comparisons[0].current.performance_grade, 'meets_requirements');
  assert.equal(result.comparisons[0].reference.performance_grade, null);
  assert.deepEqual(result.current_portrait.sections.current_work[0].text, input.materials[1].portrait.synthesis.current_work[0].text);
  assert.equal(result.profile.behavior_patterns.status, 'unknown');
  assert.equal(result.changes.chronology, 'unknown');
  assert.equal(result.changes.growth_score, null);
});

test('目标有原文，心理自述和可用资源保持未知，真实资料不标合成', () => {
  const input = fixture();
  input.manifest.data_nature = 'real_materials';
  const result = analyzeRealCase(input);
  assert.equal(result.provenance.synthetic, false);
  assert.equal(result.provenance.model_called, false);
  assert.match(result.profile.intention.goal.value, /研究目标/);
  for (const key of ['attitude', 'perceived_expectations', 'perceived_control', 'difficulty']) {
    assert.equal(result.profile.intention[key].status, 'unknown');
  }
  assert.equal(result.profile.context.actual_resources.status, 'unknown');
});

test('已存在方案时，建议依据当前缺口，不机械重复旧建议', () => {
  const result = analyzeRealCase(fixture());
  assert.match(result.recommendations[0].action, /核对现有方案/);
  assert.match(result.recommendations[0].action, /数据划分/);
  assert.doesNotMatch(result.recommendations[0].action, /先列出测试集/);
  assert.equal(result.follow_up[0].status, 'related_material_found');
  assert.match(result.follow_up[0].label, /需核对具体完成依据/);
  assert.equal(result.follow_up[0].accepted, 'unknown');
  assert.equal(result.follow_up[0].executed, 'unknown');
});

test('所有结果来源引用可定位原文页段；空白差异可匹配，内容差异拒绝', () => {
  const input = fixture();
  input.materials[1].portrait.implicit.dimensions[0].criteria[0].evidence[0].quote = '方案已列出\n测试集、基线和指标。';
  const result = analyzeRealCase(input);
  const index = new Map(result.source_index.map(s => [s.id, s]));
  const visit = value => {
    if (!value || typeof value !== 'object') return;
    if (value.source_refs) for (const id of value.source_refs) {
      const source = index.get(id);
      assert.ok(source, id);
      assert.ok(source.document_id && source.segment_id && source.quote);
      assert.equal(source.page, 1);
      assert.ok(source.segment_text.replace(/\s+/gu, '').includes(source.quote.replace(/\s+/gu, '')));
    }
    for (const child of Object.values(value)) visit(child);
  };
  visit(result);
  input.materials[1].portrait.implicit.dimensions[0].criteria[0].evidence[0].quote = '不存在的引文';
  assert.throws(() => analyzeRealCase(input), /引文/);
});

test('身份、文档hash、页段、上游引用和目标定位错误均拒绝', () => {
  const mutations = [
    x => { x.materials[1].portrait.student_id = 'other'; },
    x => { x.materials[1].bundle.documents[0].student_id = 'other'; },
    x => { x.materials[1].portrait.sources[0].sha256 = 'c'.repeat(64); },
    x => { x.materials[1].portrait.sources[0].document_id = 'missing'; },
    x => { x.materials[1].portrait.implicit.dimensions[0].criteria[0].evidence[0].page = 2; },
    x => { x.materials[1].portrait.synthesis.current_work[0].source_refs = ['missing']; },
    x => { x.manifest.selected.current_goal.quote = '捏造目标'; },
  ];
  for (const mutate of mutations) {
    const input = fixture(); mutate(input);
    assert.throws(() => analyzeRealCase(input));
  }
});

test('当前材料不足或任务不适用时，不把旧建议标为完成', () => {
  for (const state of ['insufficient', 'not_applicable']) {
    const input = fixture();
    const criterion = input.materials[1].portrait.implicit.dimensions[0].criteria[0];
    criterion.evidence_state = state; criterion.performance_grade = null;
    const result = analyzeRealCase(input);
    assert.equal(result.follow_up[0].status, 'no_completion_conclusion');
    assert.equal(result.follow_up[0].executed, 'unknown');
  }
});

test('旧引用未提供原文时显式留空，不伪造页段；Markdown区分材料对应与执行', () => {
  const input = fixture();
  input.materials[0].portrait.implicit.dimensions[0].criteria[0].evidence = [];
  const result = analyzeRealCase(input);
  assert.deepEqual(result.follow_up[0].previous_source_refs, []);
  const md = formatMarkdown(result);
  assert.match(md, /不能据此认定学生采纳或执行/);
  assert.match(md, /原文证据未提供/);
  assert.match(md, /来源索引/);
});

test('研究特色保留推断依据和解释，并在Markdown中标明', () => {
  const input = fixture();
  const feature = {
    text: '材料可归纳出围绕验证设计组织研究的特点。',
    basis: 'inferred',
    rationale: '当前材料同时呈现研究目标和验证方案，因此只在该材料范围内作有限归纳。',
    source_refs: ['R1'],
  };
  input.materials[1].portrait.synthesis.research_features = [feature];
  const result = analyzeRealCase(input);
  const adapted = result.current_portrait.sections.research_features[0];
  assert.equal(adapted.text, feature.text);
  assert.equal(adapted.basis, feature.basis);
  assert.equal(adapted.rationale, feature.rationale);
  assert.deepEqual(adapted.upstream_ref_ids, feature.source_refs);
  assert.equal(adapted.source_refs.length, 1);
  const md = formatMarkdown(result);
  assert.match(md, /依据性质：inferred/);
  assert.match(md, new RegExp(feature.rationale));
});

test('明确撤销或不可用的材料来源不会进入本地适配', () => {
  for (const state of [
    {authorization: 'denied', validity: 'active'},
    {authorization: 'authorized', validity: 'withdrawn'},
    {authorization: 'authorized', validity: 'superseded'},
    {authorization: 'authorized', validity: 'disputed'},
  ]) {
    const input = fixture();
    input.materials[1].bundle.input_context = {
      sources: [{document_id: 'current', ...state}],
    };
    assert.throws(() => analyzeRealCase(input), /unavailable source/);
  }
});
