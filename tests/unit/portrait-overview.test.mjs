import test from 'node:test';
import assert from 'node:assert/strict';
import {validateOverview} from '../../skills/graduate-portrait/scripts/overview.mjs';

const fixture = () => ({
  schema_version: 'portrait-overview-1.0', student_id: 'synthetic-student', status: 'generated',
  scopes: [{scope_id: 'annual', stage: 'annual', period: '2025-2026'},
    {scope_id: 'proposal', stage: 'proposal', period: null}],
  overview: {current_work: [{text: '合成示例中的研究工作', source_refs: ['Y1']}],
    research_plan: [{text: '合成示例中的研究计划', source_refs: ['P1']}],
    demonstrated: [], attention: [], next_steps: [], changes: []},
  evaluations: [{scope_id: 'annual', rubric_version: 'synthetic.1', explicit: null,
    criteria: [{criterion_id: 'c1', label: '合成观察项', observation: '原有观察',
      evidence_state: '证据不足', performance_grade: null, source_refs: ['Y1'], suggestion: '原有建议',
      dimension_id: 'synthetic-domain', dimension_label: '合成领域', rationale: '合成证据未展示关键条件。',
      grading_standard: {needs_improvement: '存在明确错误', meets_requirements: '展示约定行为',
        well_demonstrated: '展示约定行为并解释替代方案'}}]}],
  source_records: [
    {id: 'Y1', scope_id: 'annual', document_id: 'synthetic-annual', page: 1, quote: '合成原句', fields: null},
    {id: 'P1', scope_id: 'proposal', document_id: 'synthetic-proposal', page: 1, quote: '合成计划', fields: null},
  ], issues: [],
});

test('统一 JSON 保留年报与开题范围、原等级以及逐项引用', () => {
  const value = fixture(), original = structuredClone(value);
  assert.equal(validateOverview(value), value);
  assert.deepEqual(value, original);
});

test('拒绝全文字符串、无效引用及评价串用其他任务来源', () => {
  assert.throws(() => validateOverview({portrait: 'Markdown 全文'}));
  const value = fixture();
  value.overview.current_work[0].source_refs = ['missing'];
  assert.throws(() => validateOverview(value), /source reference/);
  const other = fixture();
  other.evaluations[0].criteria[0].source_refs = ['P1'];
  assert.throws(() => validateOverview(other), /scope/);
});

test('身份冲突和缺输入时不生成画像，重复输入不新增变化', () => {
  for (const status of ['identity_conflict', 'missing_input', 'unchanged']) {
    const value = fixture(); value.status = status;
    if (status === 'unchanged') {
      assert.doesNotThrow(() => validateOverview(value));
      value.overview.changes = [{text: '凭空新增', source_refs: ['Y1']}];
    }
    assert.throws(() => validateOverview(value));
  }
});

test('输入问题使用同一 JSON 结构返回，不生成其他学生的评价', () => {
  const value = fixture();
  value.status = 'identity_conflict';
  value.overview = Object.fromEntries(Object.keys(value.overview).map(key => [key, []]));
  value.evaluations = [];
  value.source_records = [];
  value.issues = ['合成输入中的学生标识与目标学生不同'];
  assert.doesNotThrow(() => validateOverview(value));
});

test('画像不能把缺少显性结果的产物声明为完整联调结果', () => {
  const value = fixture();
  value.completion = 'partial';
  assert.doesNotThrow(() => validateOverview(value));
  value.completion = 'complete';
  assert.throws(() => validateOverview(value), /explicit/);
  value.scopes = [value.scopes[0]];
  value.source_records = [value.source_records[0]];
  value.overview.research_plan = [];
  value.evaluations[0].explicit = {
    rules_version: 'synthetic-explicit.1', dimensions: [{id: 'synthetic-d1', score: 70}],
  };
  const originalExplicit = structuredClone(value.evaluations[0].explicit);
  assert.doesNotThrow(() => validateOverview(value));
  assert.deepEqual(value.evaluations[0].explicit, originalExplicit);
});

test('有等级的评分须有原判级理由、适用标准和证据', () => {
  const value = fixture();
  Object.assign(value.evaluations[0].criteria[0], {
    performance_grade: '达到要求', evidence_state: '可评价',
    dimension_id: 'synthetic-domain', dimension_label: '合成领域',
    rationale: '合成证据展示了本项约定的行为。',
    grading_standard: {needs_improvement: '存在明确错误', meets_requirements: '展示约定行为',
      well_demonstrated: '展示约定行为并解释替代方案'},
  });
  assert.doesNotThrow(() => validateOverview(value));
  value.evaluations[0].criteria[0].source_refs = [];
  assert.throws(() => validateOverview(value), /graded.*evidence/);
  const missingReason = fixture();
  missingReason.completion = 'partial';
  delete missingReason.evaluations[0].criteria[0].rationale;
  assert.throws(() => validateOverview(missingReason), /rationale/);
  const unsupported = fixture();
  unsupported.evaluations[0].criteria[0].performance_grade = '待改进';
  assert.throws(() => validateOverview(unsupported), /cannot receive a grade/);
});
