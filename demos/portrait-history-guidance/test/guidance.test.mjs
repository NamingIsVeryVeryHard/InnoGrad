import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile, writeFile, rm, access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {createHash} from 'node:crypto';
import {createInnoAgentRunner} from '../../../skills/graduate-portrait/scripts/workflow.mjs';
import {requestStructured} from '../../../skills/graduate-portrait/scripts/adapter.mjs';
import {prepareContext} from '../../../skills/graduate-research-guidance/scripts/input.mjs';
import {generateGuidance, guidanceRepairFeedback} from '../../../skills/graduate-research-guidance/scripts/workflow.mjs';
import {validateGuidance} from '../../../skills/graduate-research-guidance/scripts/validate.mjs';

const bundle = (text = '计划比较基线，尚未开展实验。') => ({
  student_id: 'SYNTHETIC', stage: 'proposal', period: null,
  documents: [{document_id: 'doc', student_id: 'SYNTHETIC', period: null,
    source_name: 'synthetic.txt', parse_status: 'complete',
    segments: [{segment_id: 'same-segment', page: 1, text}]}],
});
const context = () => prepareContext({current: bundle(), history: [bundle('报告自述已完成初步试验。')]});
const unknown = () => ({status: 'unknown', value: null, source_refs: []});
function response(ctx) {
  const source = ctx.sources[0];
  return {
    facts: [{kind: 'plan', work_status: 'planned', text: '计划比较基线。', source_refs: [source.id]}],
    intent: {goal: unknown(), attitude: unknown(), subjective_norm: unknown(), perceived_behavioral_control: unknown()},
    task_conditions: {progress: unknown(), resources: unknown(), deadlines: unknown()},
    relevant_history: ctx.scope.history.length ? [{
      material_id: 'history-1', relation: 'related', text: '参照材料描述了初步试验。',
      source_refs: [ctx.sources[1].id],
    }] : [],
    gaps: [],
    guidance: [{action: '记录基线比较方案。', why: '当前材料仍是实验计划。',
      completion_evidence: '包含基线及指标的实验方案。', uncertainty: [], source_refs: [source.id]}],
    unknowns: [],
  };
}
const config = {url: 'http://localhost/test', key: 'synthetic-secret', provider: 'ecnu', model: 'ecnu-plus'};
const completion = data => new Response(JSON.stringify({
  model: 'test-qwen', choices: [{finish_reason: 'stop', message: {content: JSON.stringify(data)}}],
}), {headers: {'content-type': 'application/json'}});

test('模型只选择引用编号，重复使用由程序去重并从原文生成来源表', async () => {
  const ctx = prepareContext({current: bundle()});
  const raw = response(ctx);
  delete raw.source_index;
  raw.guidance[0].source_refs.push(ctx.sources[0].id);
  const result = await generateTestGuidance(ctx, {config, fetchImpl: async () => completion(raw)});
  assert.equal(result.source_index.length, 1);
  assert.deepEqual(result.guidance[0].source_refs, [ctx.sources[0].id]);
  assert.equal(result.source_index[0].quote, ctx.sources[0].text);
  assert.ok(result.source_index[0].source_id);
  assert.equal(result.source_index[0].start_char, 0);
});

test('引用单元保留全部原文和精确偏移，展示编号与来源版本分开', () => {
  const text = '  ' + '甲'.repeat(400) + '。\n\n' + '乙'.repeat(400) + '。🙂最后一段。\n';
  const ctx = prepareContext({current: bundle(text)});
  assert.ok(ctx.sources.length > 1);
  assert.equal(ctx.sources.map(s => s.text).join('').replace(/\s/gu, ''), text.replace(/\s/gu, ''));
  for (const s of ctx.sources) assert.equal(text.slice(s.start_char, s.end_char), s.text);
  assert.equal(ctx.sources[0].source_id, ctx.sources[1].source_id);
  const changed = prepareContext({current: bundle(text + '新增材料。')});
  assert.equal(changed.sources[0].id, ctx.sources[0].id);
  assert.notEqual(changed.sources[0].source_id, ctx.sources[0].source_id);
});

async function generateTestGuidance(ctx, options) {
  let result;
  const runner = {
    session_ids: ['synthetic-session'],
    installed_skill_hashes: {'graduate-research-guidance': '0'.repeat(64)}, records: [],
    async execute(task, validate) {
      result = await requestStructured(task, {...options, validate, formatRepairFeedback: guidanceRepairFeedback});
      this.records.push({attempts: result.attempts});
      return result.data;
    },
    async provenance() { return {model_attempts: result.records}; },
  };
  return generateGuidance(ctx, {runner});
}

test('原生执行核对Skill正文，通过slash命令调用并记录会话、Skill哈希和模型来源', async () => {
  const ctx = context(), prompts = [];
  await assert.rejects(generateGuidance(ctx, {}), /InnoAgent runner/);
  const content = await readFile(new URL('../../../skills/graduate-research-guidance/SKILL.md', import.meta.url), 'utf8');
  const origin = {provider: 'ecnu', requested_model: 'ecnu-plus', actual_model: 'test-qwen', attempt: 1, status: 'completed'};
  const fetchImpl = async (url, init) => {
    if (url.endsWith('/api/skills')) return Response.json([{name: 'graduate-research-guidance', loaded: true, enabled: true}]);
    if (url.endsWith('/content')) return Response.json({content});
    if (url.endsWith('/api/sessions') || url.endsWith('/api/sessions/native-session')) {
      return Response.json({id: 'native-session', workspaceId: 'native-workspace'});
    }
    if (url.includes('/runs/')) return Response.json({attempts: [origin]});
    assert.ok(url.endsWith('/api/chat/stream'));
    const prompt = JSON.parse(init.body).prompt; prompts.push(prompt);
    assert.match(prompt, /^\/skill:graduate-research-guidance portrait_run_id:/);
    const event = {sessionId: 'native-session', turnId: 'native-turn',
      event: {type: 'done', fullText: JSON.stringify(response(ctx))}};
    return new Response('data: ' + JSON.stringify(event) + '\n\n', {headers: {'content-type': 'text/event-stream'}});
  };
  const runner = await createInnoAgentRunner({url: 'http://localhost', auditUrl: 'http://localhost/audit', timeoutMs: 1000},
    {fetchImpl, skillNames: ['graduate-research-guidance'], formatRepairFeedback: guidanceRepairFeedback});
  const result = await generateGuidance(ctx, {runner});
  assert.equal(prompts.length, 1);
  assert.equal(result.provenance.platform, 'InnoAgent');
  assert.equal(result.provenance.actual_model, 'test-qwen');
  assert.deepEqual(result.provenance.session_ids, ['native-session']);
  assert.equal(result.provenance.installed_skill_hashes['graduate-research-guidance'],
    createHash('sha256').update(content).digest('hex'));
  await assert.rejects(createInnoAgentRunner({url: 'http://localhost', timeoutMs: 1000},
    {skillNames: ['graduate-research-guidance'], fetchImpl: async url =>
      url.endsWith('/api/skills') ? Response.json([{name: 'graduate-research-guidance', loaded: true, enabled: true}])
        : Response.json({content: 'stale Skill'})}), /differs/);
});

test('引用编号区分跨材料、跨文档的同名页段；原文后半段仍可定位', async () => {
  const current = bundle('前'.repeat(1300) + '计划比较基线，尚未开展实验。');
  current.documents.push({...structuredClone(current.documents[0]), document_id: 'other-doc'});
  const ctx = prepareContext({current, history: [bundle()]});
  assert.equal(new Set(ctx.sources.map(s => s.id)).size, 3);
  const raw = response(ctx);
  raw.relevant_history = [];
  const result = await generateTestGuidance(ctx, {config, fetchImpl: async () => completion(raw)});
  assert.equal(result.source_index[0].segment_id, 'same-segment');
  assert.equal(result.source_index[0].quote, ctx.sources[0].text);
  assert.ok(result.source_index[0].quote.endsWith('计划比较基线，尚未开展实验。'));
  assert.equal(result.scope.chronology, 'unknown');
});

test('身份冲突、空材料和文档范围冲突在调用前拒绝；纯文本保留原文', () => {
  const other = bundle(); other.student_id = 'OTHER'; other.documents[0].student_id = 'OTHER';
  assert.throws(() => prepareContext({current: bundle(), history: [other]}), /identity/);
  const bad = bundle(); bad.documents[0].student_id = 'OTHER';
  assert.throws(() => prepareContext({current: bad}), /scope/);
  assert.throws(() => prepareContext({current: {text: '   '}}), /empty/);
  const ctx = prepareContext({current: {text: '真实的纯文本输入。', source: 'report.txt'}});
  assert.equal(ctx.sources[0].text, '真实的纯文本输入。');
  assert.equal(ctx.scope.student_id, null);
  assert.equal(ctx.sources[0].page, null);
});

test('契约进入模型请求，结果保持计划、未知状态及实际调用来源', async () => {
  const ctx = context();
  const result = await generateTestGuidance(ctx, {config, fetchImpl: async (_url, options) => {
    const payload = JSON.parse(options.body);
    assert.match(payload.messages[0].content, /source_refs/);
    assert.match(payload.messages[0].content, /completion_evidence/);
    assert.match(payload.messages[1].content, /same-segment/);
    return completion(response(ctx));
  }});
  assert.equal(validateGuidance(result, ctx), result);
  assert.equal(result.facts[0].work_status, 'planned');
  assert.equal(result.intent.attitude.status, 'unknown');
  assert.equal(result.provenance.actual_model, 'test-qwen');
  assert.equal(result.provenance.model_called, true);
  assert.equal(result.provenance.provider, 'ecnu');
});

test('每个输出栏目都检查引用，不丢弃坏引用；一次重试仍无效就失败', async () => {
  const ctx = context();
  const mutations = [
    raw => { raw.facts[0].source_refs = ['missing']; },
    raw => { raw.guidance[0].source_refs = []; },
    raw => { raw.intent.goal = {status: 'documented', value: '目标', source_refs: ['missing']}; },
    raw => { raw.task_conditions.resources = {status: 'unknown', value: '已有GPU', source_refs: []}; },
    raw => { raw.relevant_history[0].source_refs = [ctx.sources[0].id]; },
    raw => { raw.source_index = [{id: ctx.sources[0].id, quote: '原文中不存在的引文'}]; },
    raw => { raw.facts[0].work_status = 'reported_completed'; },
    raw => { raw.relevant_history[0].relation = 'changed'; },
  ];
  for (const mutate of mutations) {
    let calls = 0;
    const raw = response(ctx); mutate(raw);
    await assert.rejects(generateTestGuidance(ctx, {config, fetchImpl: async () => {
      calls++; return completion(raw);
    }}), /validation/);
    assert.equal(calls, 2);
  }
});

test('修正重试收到明确路径和类别，修正后才生成结果', async () => {
  const ctx = context(); let calls = 0;
  const result = await generateTestGuidance(ctx, {config, fetchImpl: async (_url, options) => {
    calls++;
    const raw = response(ctx);
    if (calls === 1) raw.guidance[0].source_refs = ['forged'];
    else {
      const feedback = JSON.parse(options.body).messages.at(-1).content;
      assert.match(feedback, /EVIDENCE_LOCATION/);
      assert.match(feedback, /guidance\/0\/source_refs/);
      assert.doesNotMatch(feedback, /numeric_token|criterion/);
    }
    return completion(raw);
  }});
  assert.equal(result.provenance.attempts, 2);
});

test('无历史时不生成历史比较，最终文件篡改仍被校验器拒绝', async () => {
  const ctx = prepareContext({current: bundle()});
  const result = await generateTestGuidance(ctx, {config, fetchImpl: async () => completion(response(ctx))});
  assert.deepEqual(result.relevant_history, []);
  result.source_index[0].page = 99;
  assert.throws(() => validateGuidance(result, ctx), /source/);
  result.source_index[0].page = 1;
  result.source_index[0].quote = '计划比较基线，已经开展实验。';
  assert.throws(() => validateGuidance(result, ctx), /QUOTE_NOT_IN_SEGMENT/);
  result.source_index[0].quote = ctx.sources[0].text;
  result.source_index[0].start_char = 1;
  assert.throws(() => validateGuidance(result, ctx), /SOURCE_METADATA/);
  assert.throws(() => validateGuidance({status: 'generated'}), /schema|SCHEMA/i);
});

test('CLI模型失败写失败记录，退出非零，不生成成功结果；参数错误不调用模型', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'guidance-test-'));
  t.after(() => rm(dir, {recursive: true, force: true}));
  const current = join(dir, 'current.json');
  await writeFile(current, JSON.stringify(bundle()));
  let calls = 0;
  const server = createServer((_req, res) => {
    calls++; res.writeHead(503, {'content-type': 'application/json'}); res.end('{"error":{}}');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const cli = new URL('../../../skills/graduate-research-guidance/scripts/cli.mjs', import.meta.url);
  const run = args => new Promise(resolve => {
    const proc = spawn(process.execPath, [cli.pathname, ...args], {
      env: {...process.env, PORTRAIT_ENV_FILE: '', INNOAGENT_URL: `http://127.0.0.1:${server.address().port}`,
        PORTRAIT_API_URL: `http://127.0.0.1:${server.address().port}/`,
        PORTRAIT_API_KEY: 'synthetic-secret', PORTRAIT_API_MODEL: 'test', PORTRAIT_API_TIMEOUT_MS: '1000'},
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stderr = ''; proc.stderr.on('data', chunk => { stderr += chunk; });
    proc.on('close', code => resolve({code, stderr}));
  });
  const out = join(dir, 'failed');
  const failed = await run(['run', '--current', current, '--out', out]);
  assert.equal(failed.code, 1);
  assert.doesNotMatch(failed.stderr, /synthetic-secret/);
  assert.equal(JSON.parse(await readFile(join(out, 'run.json'))).status, 'failed');
  await assert.rejects(access(join(out, 'result.json')));
  const before = calls;
  assert.equal((await run(['run', '--current', current, '--out'])).code, 1);
  assert.equal((await run(['run', '--current', current, '--out', out])).code, 1);
  assert.equal(calls, before);
});
