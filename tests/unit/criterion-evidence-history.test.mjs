import test from 'node:test';
import assert from 'node:assert/strict';
import {criterionEvidenceHistory} from '../../skills/graduate-portrait/scripts/overview.mjs';

const criterion = (grade, refs) => ({
  criterion_id: 'design', label: '方案设计', dimension_id: 'research-design',
  dimension_label: '研究问题与方案设计', observation: '合成任务中的方案表现',
  evidence_state: grade ? 'evaluable' : 'insufficient', performance_grade: grade,
  rationale: grade ? '合成开题材料展示了约定的方案要素。' : '本份合成年度报告未展示方案。',
  grading_standard: {needs_improvement: '方案存在明确矛盾', meets_requirements: '展示完整方案',
    well_demonstrated: '比较并解释方案取舍'}, source_refs: refs, suggestion: '保留方案记录',
});
const fixture = () => ({
  schema_version: 'portrait-overview-1.0', student_id: 'SYNTHETIC-HISTORY',
  status: 'generated', completion: 'partial',
  scopes: [{scope_id: 'proposal', stage: 'proposal', period: null},
    {scope_id: 'current', stage: 'annual', period: '2025-2026'}],
  overview: {current_work: [], research_plan: [], demonstrated: [], attention: [],
    next_steps: [], changes: []},
  evaluations: [
    {scope_id: 'proposal', rubric_version: 'synthetic.1', explicit: null,
      criteria: [criterion('meets_requirements', ['P1'])]},
    {scope_id: 'current', rubric_version: 'synthetic.1', explicit: null,
      criteria: [criterion(null, ['Y1'])]},
  ],
  source_records: [
    {id: 'P1', scope_id: 'proposal', document_id: 'synthetic-proposal',
      page: 3, quote: '合成方案原句', fields: null},
    {id: 'Y1', scope_id: 'current', document_id: 'synthetic-annual',
      page: 2, quote: '合成年度概述', fields: null},
  ], issues: [],
});

test('当期未覆盖不抹去另一任务已经定级的表现', () => {
  const value = fixture(), before = structuredClone(value);
  const [item] = criterionEvidenceHistory(value, {currentScopeId: 'current'});
  assert.equal(item.status, 'historical_graded');
  assert.equal(item.current.performance_grade, null);
  assert.equal(item.graded[0].scope_id, 'proposal');
  assert.equal(item.graded[0].criterion.performance_grade, 'meets_requirements');
  assert.deepEqual(item.graded[0].criterion.source_refs, ['P1']);
  assert.deepEqual(value, before);
});

test('保留当期较低等级与历史较高等级，不挑最高分冒充当前结论', () => {
  const value = fixture();
  value.evaluations[0].criteria[0].performance_grade = 'well_demonstrated';
  value.evaluations[1].criteria[0] = criterion('needs_improvement', ['Y1']);
  const [item] = criterionEvidenceHistory(value, {currentScopeId: 'current'});
  assert.equal(item.status, 'current_graded');
  assert.equal(item.current.performance_grade, 'needs_improvement');
  assert.equal(item.graded.length, 2);
  assert.equal(item.graded[0].criterion.performance_grade, 'well_demonstrated');
  assert.equal(item.graded[1].criterion.performance_grade, 'needs_improvement');
});

test('各任务均未覆盖时不生成等级，未知当前范围被拒绝', () => {
  const value = fixture();
  value.evaluations[0].criteria[0] = criterion(null, ['P1']);
  const [item] = criterionEvidenceHistory(value, {currentScopeId: 'current'});
  assert.equal(item.status, 'ungraded');
  assert.deepEqual(item.graded, []);
  assert.throws(() => criterionEvidenceHistory(value, {currentScopeId: 'absent'}), /scope/);
});
