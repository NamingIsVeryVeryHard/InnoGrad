import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {prepareTrajectoryUpdate, validateTrajectoryResponse, updateResearchTrajectory}
  from '../../skills/graduate-portrait/scripts/trajectory.mjs';

const bundle = (period = '2024-2025', id = 'synthetic-one', text = '合成报告：计划比较两种方法。') => ({
  schema_version: '1.0', student_id: 'SYNTHETIC-TRAJECTORY', stage: 'annual', period,
  documents: [{document_id: id, source_name: id + '.txt', kind: 'annual',
    sha256: createHash('sha256').update(text).digest('hex'), student_id: 'SYNTHETIC-TRAJECTORY',
    period, parse_status: 'complete', segments: [{segment_id: 'body', page: 1, text}]}],
});
function response(prepared) {
  const now = prepared.currentSourceIds[0], old = prepared.previous?.features[0];
  const claim = text => ({text, source_refs: [now]});
  return {
    current_focus: claim('合成任务中的方法比较'),
    features: [{previous_id: old?.id ?? null, change: old ? 'retain' : 'add', kind: 'method',
      text: old?.text ?? '以方法比较组织研究', basis: 'observed',
      reason: '合成原文展示了方法比较。', source_refs: [now]}],
    current_goals: [{previous_id: prepared.previous?.goals[0]?.id ?? null,
      ...claim('开展下一阶段的方法比较')}],
    conditions: [],
    plan_reviews: (prepared.previous?.goals ?? []).filter(g => g.status !== 'reported_complete')
      .map(g => ({goal_id: g.id, status: 'plan_repeated',
        observation: '新报告仍将方法比较列为计划。',
        explanation: '材料没有报告对应执行结果。',
        source_refs: [...g.source_refs, now]})),
    explanation: claim('已有方法取向与本次研究目标相关，执行状态仍须从记录判断。'),
    guidance: [{action: '按既有目标开展比较并保留结果', why: '回应材料中的当前目标',
      completion_evidence: '比较记录', uncertainty: [], source_refs: [now]}],
  };
}
function runnerFor(makeResponse = response) {
  const runner = {
    calls: 0, records: [], session_ids: ['synthetic-session'],
    installed_skill_hashes: {'graduate-portrait': 'a'.repeat(64)},
    async execute(task, validate) {
      runner.calls++;
      assert.equal(task.phase, 'synthesis');
      const value = makeResponse(task.testPrepared);
      validate(value);
      runner.records.push({phase: task.phase, attempts: 1});
      return value;
    },
    async provenance() {
      return {model: 'synthetic-model', model_attempts: [{provider: 'test',
        requested_model: 'synthetic-model', actual_model: 'synthetic-model',
        attempt: 1, status: 'completed'}]};
    },
  };
  return runner;
}
async function initial() {
  const input = {bundle: bundle(), recordedAt: '2025-06-01', dateBasis: '合成日期'};
  const prepared = prepareTrajectoryUpdate(input);
  const runner = runnerFor();
  runner.execute = async (task, validate) => {
    runner.calls++; const value = response(prepared); validate(value);
    runner.records.push({phase: task.phase, attempts: 1}); return value;
  };
  return {...await updateResearchTrajectory(input, {runner}), input};
}

test('首份材料建立有原文引用的研究画像，不生成能力分数', async () => {
  const {profile} = await initial();
  assert.equal(profile.version, 1);
  assert.equal(profile.features[0].id, 'F1');
  assert.equal(profile.goals[0].id, 'G1');
  assert.equal(profile.goals[0].status, 'current');
  assert.equal(profile.plan_reviews.length, 0);
  assert.equal(profile.source_index[0].id, 'C1');
  assert.equal('performance_grade' in profile.features[0], false);
});

test('新材料基于旧画像更新，保留特征编号、旧原文及计划对照', async () => {
  const {profile: previous} = await initial(), before = structuredClone(previous);
  const input = {bundle: bundle('2025-2026', 'synthetic-two', '合成报告：仍计划比较两种方法。'),
    previous, recordedAt: '2026-06-01', dateBasis: '合成日期'};
  const prepared = prepareTrajectoryUpdate(input), runner = runnerFor();
  runner.execute = async (task, validate) => {
    assert.equal(task.previous_profile.version, 1);
    assert.deepEqual(task.previous_profile.goals, previous.goals);
    const value = response(prepared); validate(value);
    runner.records.push({phase: task.phase, attempts: 1}); return value;
  };
  const {profile} = await updateResearchTrajectory(input, {runner});
  assert.equal(profile.version, 2);
  assert.equal(profile.previous_version.version, 1);
  assert.equal(profile.features[0].id, 'F1');
  assert.equal(profile.features[0].last_supported_version, 2);
  assert.equal(profile.source_index[0].quote, previous.source_index[0].quote);
  assert.equal(profile.plan_reviews[0].prior_goal.text, previous.goals[0].text);
  assert.equal(profile.plan_reviews[0].status, 'plan_repeated');
  assert.deepEqual(previous, before);
});

test('重复输入直接返回原版本，不再调用模型', async () => {
  const {profile, input} = await initial(), runner = runnerFor();
  const value = await updateResearchTrajectory({...input, previous: profile}, {runner});
  assert.equal(value.status, 'unchanged');
  assert.equal(value.profile.version, 1);
  assert.equal(value.provenance.model_called, false);
  assert.equal(runner.calls, 0);
});

test('没有本期证据不能冒充当前目标或旧计划完成', async () => {
  const {profile: previous} = await initial();
  const prepared = prepareTrajectoryUpdate({bundle: bundle('2025-2026', 'synthetic-two'),
    previous, recordedAt: '2026-06-01', dateBasis: '合成日期'});
  const stale = response(prepared);
  stale.current_goals[0].source_refs = previous.goals[0].source_refs;
  assert.throws(() => validateTrajectoryResponse(prepared, stale), /current material/);
  const completion = response(prepared);
  completion.plan_reviews[0].status = 'reported_completed';
  completion.plan_reviews[0].source_refs = previous.goals[0].source_refs;
  assert.throws(() => validateTrajectoryResponse(prepared, completion), /current material/);
  const fabricated = response(prepared);
  fabricated.guidance[0].source_refs = ['C99999'];
  assert.throws(() => validateTrajectoryResponse(prepared, fabricated), /source reference/);
});

test('未再次提及的研究特征及未跟进计划仍保留，不解释为退步或完成', async () => {
  const {profile: previous} = await initial();
  const input = {bundle: bundle('2025-2026', 'synthetic-two'), previous,
    recordedAt: '2026-06-01', dateBasis: '合成日期'};
  const prepared = prepareTrajectoryUpdate(input), value = response(prepared);
  value.features[0].source_refs = previous.features[0].source_refs;
  value.current_goals = [];
  value.plan_reviews[0].status = 'not_reported';
  value.plan_reviews[0].source_refs = previous.goals[0].source_refs;
  const runner = runnerFor();
  runner.execute = async (task, validate) => {
    validate(value); runner.records.push({phase: task.phase, attempts: 1}); return value;
  };
  const {profile} = await updateResearchTrajectory(input, {runner});
  assert.equal(profile.features[0].last_supported_version, 1);
  assert.equal(profile.goals[0].status, 'not_reaffirmed');
  assert.equal(profile.plan_reviews[0].status, 'not_reported');
});

test('不能静默删掉旧特征或未解决的计划，也不能混入其他学生或倒序材料', async () => {
  const {profile: previous} = await initial();
  const input = {bundle: bundle('2025-2026', 'synthetic-two'), previous,
    recordedAt: '2026-06-01', dateBasis: '合成日期'};
  const prepared = prepareTrajectoryUpdate(input), missingFeature = response(prepared);
  missingFeature.features = [];
  assert.throws(() => validateTrajectoryResponse(prepared, missingFeature), /feature coverage/);
  const missingPlan = response(prepared); missingPlan.plan_reviews = [];
  assert.throws(() => validateTrajectoryResponse(prepared, missingPlan), /goal coverage/);
  assert.throws(() => prepareTrajectoryUpdate({...input, previous: {...previous, student_id: 'OTHER'}}), /identity/);
  assert.throws(() => prepareTrajectoryUpdate({...input, recordedAt: '2024-01-01'}), /chronological/);
  const amended = bundle('2024-2025', 'synthetic-one', '修订后的合成报告');
  assert.throws(() => prepareTrajectoryUpdate({...input, bundle: amended}), /rebuild/);
});

test('模型等待期间调用者修改输入，不会改变结果绑定的学生', async () => {
  const input = {bundle: bundle(), recordedAt: '2025-06-01', dateBasis: '合成日期'};
  const prepared = prepareTrajectoryUpdate(input), runner = runnerFor();
  runner.execute = async (task, validate) => {
    input.bundle.student_id = 'CHANGED-WHILE-WAITING';
    const value = response(prepared); validate(value);
    runner.records.push({phase: task.phase, attempts: 1}); return value;
  };
  const result = await updateResearchTrajectory(input, {runner});
  assert.equal(result.profile.student_id, 'SYNTHETIC-TRAJECTORY');
});

test('新证据可修订旧解释并记录报告自述完成，保留前后文字和原计划', async () => {
  const {profile: previous} = await initial();
  const input = {bundle: bundle('2025-2026', 'synthetic-two', '合成报告：已完成比较，改为分析适用条件。'),
    previous, recordedAt: '2026-06-01', dateBasis: '合成日期'};
  const prepared = prepareTrajectoryUpdate(input), value = response(prepared);
  value.features[0] = {...value.features[0], change: 'refine',
    text: '由方法比较进一步分析适用条件',
    source_refs: [...previous.features[0].source_refs, prepared.currentSourceIds[0]]};
  value.plan_reviews[0].status = 'reported_completed';
  value.current_goals = [];
  const runner = runnerFor();
  runner.execute = async (task, validate) => {
    validate(value); runner.records.push({phase: task.phase, attempts: 1}); return value;
  };
  const {profile} = await updateResearchTrajectory(input, {runner});
  assert.equal(profile.features[0].id, 'F1');
  assert.equal(profile.features[0].text, value.features[0].text);
  assert.equal(profile.updates[0].before, previous.features[0].text);
  assert.equal(profile.goals[0].status, 'reported_complete');
  assert.deepEqual(profile.plan_reviews[0].prior_goal.source_refs, previous.goals[0].source_refs);
});

test('已完成目标不能作为当前目标复用', async () => {
  const {profile: previous} = await initial();
  const prepared = prepareTrajectoryUpdate({bundle: bundle('2025-2026', 'synthetic-two'),
    previous, recordedAt: '2026-06-01', dateBasis: '合成日期'});
  const completed = response(prepared);
  completed.plan_reviews[0].status = 'reported_completed';
  assert.throws(() => validateTrajectoryResponse(prepared, completed), /completed goal/i);

  const completedEarlier = structuredClone(previous);
  completedEarlier.goals[0].status = 'reported_complete';
  completedEarlier.current_goal_ids = [];
  const preparedEarlier = prepareTrajectoryUpdate({bundle: bundle('2025-2026', 'synthetic-two'),
    previous: completedEarlier, recordedAt: '2026-06-01', dateBasis: '合成日期'});
  const reused = response(preparedEarlier);
  assert.throws(() => validateTrajectoryResponse(preparedEarlier, reused), /completed goal/i);
});

test('转发的当前焦点和指导引用会保留对应来源', async () => {
  const {profile: previous} = await initial();
  const original = previous.source_index[0];
  previous.source_index.push({...original, id: 'C2'});
  previous.current_focus.source_refs = ['C2'];
  previous.guidance[0].source_refs = ['C2'];
  const prepared = prepareTrajectoryUpdate({bundle: bundle('2025-2026', 'synthetic-two'),
    previous, recordedAt: '2026-06-01', dateBasis: '合成日期'});
  assert.ok(prepared.task.sources.some(source => source.id === 'C2'));
});
