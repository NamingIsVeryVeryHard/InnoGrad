import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';
import { test } from 'node:test';
import { createPortraitServer } from '../src/server.js';
import { syntheticFixture, syntheticPortrait, buildAResult } from '../skill-bridge.mjs';

test('POST creates an asynchronous draft and GET returns the completed result', async t => {
  const fixture = await syntheticFixture();
  const result = await syntheticPortrait(fixture);
  const app = await createPortraitServer({ workflow: async () => result });
  t.after(() => app.close());
  const created = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
  assert.equal(created.statusCode, 202);
  assert.match(created.headers.location!, /^\/api\/portraits\//);
  const id = created.json().id;
  await delay(0);
  const fetched = await app.inject({ method: 'GET', url: `/api/portraits/${id}` });
  assert.equal(fetched.statusCode, 200);
  assert.equal(fetched.json().status, 'completed');
  assert.deepEqual(fetched.json().portrait, result);
  assert.equal(fetched.json().portrait.review_status, 'draft');
});

test('invalid and mismatched input never reaches the workflow', async t => {
  let calls = 0;
  const app = await createPortraitServer({ workflow: async () => { calls++; throw new Error('unreachable'); } });
  t.after(() => app.close());
  const fixture = await syntheticFixture();
  const extra = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle, apiKey: 'not-allowed' } });
  assert.equal(extra.statusCode, 400);
  const mismatch = structuredClone(fixture.bundle);
  mismatch.documents[0].student_id = 'another-student';
  const semantic = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: mismatch } });
  assert.equal(semantic.statusCode, 422);
  assert.equal(calls, 0);
  assert.equal((await app.inject('/api/portraits/unknown')).statusCode, 404);
});

test('OpenAPI and Swagger UI describe shared input, task states and read-only configuration', async t => {
  const app = await createPortraitServer();
  t.after(() => app.close());
  const response = await app.inject('/openapi.json');
  assert.equal(response.statusCode, 200);
  const document = response.json();
  assert.equal(document.openapi, '3.0.3');
  assert.ok(document.paths['/api/portraits'].post);
  const examples = document.paths['/api/portraits'].post.requestBody.content['application/json'].examples;
  assert.deepEqual(Object.keys(examples), ['annualReport', 'proposalReport', 'annualWithAResult']);
  assert.equal(examples.annualReport.value.bundle.stage, 'annual');
  assert.equal(examples.proposalReport.value.bundle.stage, 'proposal');
  for (const example of Object.values(examples) as { description: string; value: { bundle: { student_id: string } } }[]) {
    assert.match(example.description, /全虚构/);
    assert.match(example.value.bundle.student_id, /^SYNTHETIC-/);
  }
  assert.ok(document.paths['/api/portraits/{id}'].get);
  assert.ok(document.components.schemas.ParsedMaterialBundle);
  assert.ok(document.components.schemas.GraduatePortrait);
  assert.ok(document.components.schemas.AResult);
  const requestSchema = document.paths['/api/portraits'].post.requestBody.content['application/json'].schema;
  assert.deepEqual(requestSchema.required, ['bundle']);
  assert.deepEqual(requestSchema.properties.mode.enum, ['implicit_only', 'bundle_pipeline']);
  assert.match(requestSchema.properties.aResult.$ref, /AResult$/);
  const portrait = document.components.schemas.GraduatePortrait;
  assert.equal(portrait.properties.schema_version.enum[0], '2.0');
  const domain = portrait.properties.implicit.properties.dimensions.items.properties;
  assert.equal(domain.level, undefined);
  const criterion = domain.criteria.items.properties;
  assert.deepEqual(criterion.evidence_state.enum, ['evaluable', 'insufficient', 'conflicting', 'not_applicable']);
  assert.ok(criterion.performance_grade.enum.includes('well_demonstrated'));
  assert.ok(criterion.evidence.items.properties.supports);
  assert.ok(criterion.evidence.items.properties.sha256);
  assert.ok(criterion.evidence.items.properties.page);
  assert.match(document.paths['/api/portraits'].post.description, /implicit_only/);
  assert.match(document.info.description, /2\.0/);
  assert.match((await app.inject('/docs/')).body, /swagger-ui/);
  const configuration = await app.inject('/api/portrait-config');
  assert.equal(configuration.statusCode, 200);
  assert.equal(configuration.json().rules.status, 'draft');
  assert.equal(configuration.json().rubric.status, 'draft_uncalibrated');
  assert.equal((await app.inject({ method: 'POST', url: '/api/portrait-config', payload: {} })).statusCode, 404);
});


test('generation errors expose only safe fixed messages, and invalid results are rejected', async t => {
  const fixture = await syntheticFixture();
  const app = await createPortraitServer({ workflow: async () => { throw Object.assign(new Error('secret-token http://private-provider student-text'), { code: 'REMOTE_HTTP' }); } });
  t.after(() => app.close());
  const created = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
  await delay(0);
  const job = await app.inject(`/api/portraits/${created.json().id}`);
  assert.equal(job.json().status, 'failed');
  assert.equal(job.json().error.code, 'REMOTE_HTTP');
  assert.doesNotMatch(job.body, /secret-token|private-provider|student-text/);
  const malformed = await createPortraitServer({ workflow: async () => ({ review_status: 'approved' } as never) });
  t.after(() => malformed.close());
  const invalid = await malformed.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
  await delay(0);
  const rejected = await malformed.inject(`/api/portraits/${invalid.json().id}`);
  assert.equal(rejected.json().error.code, 'STRUCTURED_OUTPUT');
  assert.equal(rejected.json().portrait, undefined);
});

test('timeout aborts the workflow and retains its concurrency slot until it settles', async t => {
  const fixture = await syntheticFixture();
  const result = await syntheticPortrait(fixture);
  let signal: AbortSignal | undefined;
  let finish!: (value: typeof result) => void;
  const app = await createPortraitServer({
    maxConcurrent: 1, maxJobs: 2, timeoutMs: 20,
    workflow: input => { signal = input.signal; return new Promise(resolve => { finish = resolve; }); },
  });
  t.after(() => app.close());
  const created = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
  await delay(40);
  assert.equal(signal?.aborted, true);
  const failed = await app.inject(`/api/portraits/${created.json().id}`);
  assert.equal(failed.json().error.code, 'JOB_TIMEOUT');
  const blocked = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
  assert.equal(blocked.statusCode, 503);
  assert.equal(blocked.headers['retry-after'], '30');
  finish(result);
  await delay(0);
  const unchanged = await app.inject(`/api/portraits/${created.json().id}`);
  assert.equal(unchanged.json().status, 'failed');
  assert.equal(unchanged.json().portrait, undefined);
});

test('completed jobs expire and bounded storage rejects further material retention', async t => {
  const fixture = await syntheticFixture();
  const result = await syntheticPortrait(fixture);
  let currentTime = Date.now();
  const app = await createPortraitServer({ maxConcurrent: 1, maxJobs: 1, ttlMs: 1000, now: () => currentTime, workflow: async () => result });
  t.after(() => app.close());
  const created = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
  await delay(0);
  assert.equal((await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } })).statusCode, 503);
  currentTime += 1001;
  assert.equal((await app.inject(`/api/portraits/${created.json().id}`)).statusCode, 404);
  assert.equal((await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } })).statusCode, 202);
});

test('request size and server shutdown bound input and cancel active generation', async t => {
  const fixture = await syntheticFixture();
  let signal: AbortSignal | undefined;
  const app = await createPortraitServer({ workflow: input => { signal = input.signal; return new Promise(() => {}); } });
  t.after(() => app.close());
  const large = structuredClone(fixture.bundle);
  large.documents[0].segments[0].text = 'a'.repeat(1_048_577);
  const oversized = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: large } });
  assert.equal(oversized.statusCode, 413);
  const created = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
  assert.equal(created.statusCode, 202);
  await delay(0);
  await app.close();
  assert.equal(signal?.aborted, true);
});


test('default runner fails closed when the real InnoAgent entry is missing', async t => {
  const previous = process.env.INNOAGENT_URL;
  process.env.INNOAGENT_URL = '';
  t.after(() => { if (previous === undefined) delete process.env.INNOAGENT_URL; else process.env.INNOAGENT_URL = previous; });
  const app = await createPortraitServer();
  t.after(() => app.close());
  const fixture = await syntheticFixture();
  const response = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
  let fetched = await app.inject(`/api/portraits/${response.json().id}`);
  for (let attempt = 0; fetched.json().status === 'running' && attempt < 20; attempt++) {
    await delay(10);
    fetched = await app.inject(`/api/portraits/${response.json().id}`);
  }
  assert.equal(fetched.json().status, 'failed');
  assert.equal(fetched.json().error.code, 'CONFIGURATION');
  assert.equal(fetched.json().portrait, undefined);
});


test('interactive approval requirements become an explicit safe task failure', async t => {
  const fixture = await syntheticFixture();
  const app = await createPortraitServer({ workflow: async () => {
    throw Object.assign(new Error('private tool arguments'), { code: 'TOOL_APPROVAL_REQUIRED' });
  } });
  t.after(() => app.close());
  const response = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
  await delay(0);
  const job = await app.inject(`/api/portraits/${response.json().id}`);
  assert.equal(job.json().status, 'failed');
  assert.equal(job.json().error.code, 'TOOL_APPROVAL_REQUIRED');
  assert.match(job.json().error.message, /本地已停止等待/);
  assert.match(job.json().error.message, /上游取消结果需确认/);
  assert.match(job.json().error.message, /重试前请检查 InnoAgent/);
  assert.doesNotMatch(job.json().error.message, /生成已停止/);
  assert.doesNotMatch(job.body, /private tool arguments/);
});


test('unconfirmed upstream cancellation never claims the generation was cancelled', async t => {
  const fixture = await syntheticFixture();
  const app = await createPortraitServer({ workflow: async () => {
    throw Object.assign(new Error('backend cancellation unconfirmed'), { code: 'ABORTED' });
  } });
  t.after(() => app.close());
  const response = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
  await delay(0);
  const job = await app.inject(`/api/portraits/${response.json().id}`);
  assert.equal(job.json().status, 'failed');
  assert.equal(job.json().error.code, 'ABORTED');
  assert.match(job.json().error.message, /本地已停止等待/);
  assert.match(job.json().error.message, /上游取消结果需确认/);
  assert.match(job.json().error.message, /重试前请检查 InnoAgent/);
  assert.doesNotMatch(job.json().error.message, /画像任务已取消|生成已停止/);
});


test('default and explicit execution modes reach the workflow without changing the bundle', async t => {
  const fixture = await syntheticFixture();
  const received: { mode?: string; bundle: unknown }[] = [];
  const app = await createPortraitServer({ workflow: async input => {
    received.push(input);
    throw Object.assign(new Error('mode validation only'), { code: 'CONFIGURATION' });
  } });
  t.after(() => app.close());
  const defaultRequest = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
  assert.equal(defaultRequest.statusCode, 202);
  await delay(0);
  assert.equal(received[0]?.mode, 'implicit_only');
  assert.deepEqual(received[0]?.bundle, fixture.bundle);
  const pipeline = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle, mode: 'bundle_pipeline' } });
  assert.equal(pipeline.statusCode, 202);
  await delay(0);
  assert.equal(received[1]?.mode, 'bundle_pipeline');
  const invalidMode = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle, mode: 'legacy' } });
  assert.equal(invalidMode.statusCode, 400);
  assert.equal(received.length, 2);
});


test('v2 criterion grades and complete source references survive Fastify serialization', async t => {
  const fixture = await syntheticFixture();
  fixture.bundle.documents[0]!.segments[0]!.page = 7;
  const result = await syntheticPortrait(fixture);
  const app = await createPortraitServer({ workflow: async () => result });
  t.after(() => app.close());
  const created = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
  await delay(0);
  const response = await app.inject(created.headers.location!);
  const job = response.json();
  assert.equal(job.status, 'completed');
  assert.equal(job.portrait.schema_version, '2.0');
  assert.deepEqual(job.portrait.explicit_extraction, fixture.extraction);
  assert.equal(job.portrait.implicit.dimensions.length, 7);
  const domain = job.portrait.implicit.dimensions.find((item: { id: string }) => item.id === 'research-design');
  const criterion = domain.criteria.find((item: { criterion_id: string }) => item.criterion_id === 'problem-definition');
  assert.equal(criterion.evidence_state, 'evaluable');
  assert.equal(criterion.performance_grade, 'meets_requirements');
  assert.equal(criterion.review.status, 'pending');
  assert.deepEqual(criterion.evidence[0], {
    document_id: 'annual-1', segment_id: 'body', quote: '研究问题是在小样本课堂数据中提高反馈准确性。',
    supports: '支持研究对象、情境与目标。', source_name: fixture.bundle.documents[0]!.source_name,
    sha256: fixture.bundle.documents[0]!.sha256, page: 7,
  });
  for (const item of job.portrait.implicit.dimensions) {
    assert.equal('level' in item, false);
    assert.equal('level_label' in item, false);
    assert.ok(item.summary.every((entry: { criterion_ids: string[] }) => entry.criterion_ids.length > 0));
  }
  assert.deepEqual(job.portrait, result);
});


async function aFixture() {
  const fixture = await syntheticFixture();
  const aResult = buildAResult({
    bundle: fixture.bundle, extraction: fixture.extraction, rules: fixture.rules,
    metadata: { output_version: 'synthetic-a-test-1.0', generated_at: '2026-10-14T00:00:00Z', producer: { mode: 'synthetic', name: 'API test fixture', model: null } },
  });
  return { ...fixture, aResult };
}

test('external A scope, task, material and evidence mismatches fail before workflow execution', async t => {
  const fixture = await aFixture();
  let calls = 0;
  const app = await createPortraitServer({ workflow: async () => { calls++; throw new Error('unreachable'); } });
  t.after(() => app.close());
  const invalid: unknown[] = [];
  const identity = structuredClone(fixture.aResult); identity.student_id = 'another-student'; invalid.push(identity);
  const fingerprint = structuredClone(fixture.aResult); fingerprint.material_fingerprints[0]!.content_sha256 = 'b'.repeat(64); invalid.push(fingerprint);
  const task = structuredClone(fixture.aResult); task.task_id = 'another-task'; invalid.push(task);
  const quote = structuredClone(fixture.aResult); quote.extraction.facts[0]!.evidence[0]!.quote = 'private student text absent from material'; invalid.push(quote);
  for (const aResult of invalid) {
    const response = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle, aResult } });
    assert.equal(response.statusCode, 422);
    assert.equal(response.json().error.code, 'INVALID_A_RESULT');
    assert.doesNotMatch(response.body, /another-student|another-task|private student text/);
  }
  const legacy = structuredClone(fixture.aResult) as { schema_version: string };
  legacy.schema_version = '1.0';
  assert.equal((await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle, aResult: legacy } })).statusCode, 400);
  assert.equal(calls, 0);
});

test('valid external A is preserved and overrides a requested local bundle pipeline', async t => {
  const fixture = await aFixture();
  const original = structuredClone(fixture.aResult);
  const result = await syntheticPortrait({ ...fixture, extraction: undefined });
  let received: { aResult?: unknown; mode?: string } | undefined;
  const app = await createPortraitServer({ workflow: async input => {
    received = input;
    return result;
  } });
  t.after(() => app.close());
  const created = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle, aResult: fixture.aResult, mode: 'bundle_pipeline' } });
  assert.equal(created.statusCode, 202);
  await delay(0);
  assert.equal(received?.mode, 'implicit_only');
  assert.deepEqual(received?.aResult, original);
  const job = (await app.inject(created.headers.location!)).json();
  assert.equal(job.status, 'completed');
  assert.equal(job.portrait.explicit_status, 'merged');
  assert.deepEqual(job.portrait.explicit, original.explicit);
  assert.deepEqual(job.portrait.explicit_extraction, original.extraction);
  assert.equal(job.portrait.a_handoff.generated_at, original.generated_at);
  assert.deepEqual(job.portrait.a_handoff.producer, original.producer);
  assert.deepEqual(job.portrait.a_handoff.material_fingerprints, original.material_fingerprints);
  assert.deepEqual(fixture.aResult, original);
});

test('implicit-only output explicitly reports pending A and never fabricates explicit results', async t => {
  const fixture = await syntheticFixture();
  const result = await syntheticPortrait({ ...fixture, extraction: undefined });
  const app = await createPortraitServer({ workflow: async () => result });
  t.after(() => app.close());
  const created = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
  await delay(0);
  const job = (await app.inject(created.headers.location!)).json();
  assert.equal(job.status, 'completed');
  assert.equal(job.portrait.explicit, null);
  assert.equal(job.portrait.explicit_extraction, null);
  assert.equal(job.portrait.explicit_status, 'pending');
  assert.equal(job.portrait.a_handoff, null);
  assert.ok(job.portrait.warnings.includes('explicit_pending'));
  assert.equal(job.portrait.provenance.hashes.a_result, null);
  assert.equal(job.portrait.provenance.hashes.extraction, null);
});

test('model-generated review confirmations and old cumulative domain levels are rejected', async t => {
  const fixture = await syntheticFixture();
  const result = await syntheticPortrait(fixture);
  for (const malformed of [
    { ...result, review_status: 'review_confirmed' },
    (() => { const output = structuredClone(result); Object.assign(output.implicit.dimensions[0]!.criteria[0]!.review, { status: 'review_confirmed' }); return output; })(),
    (() => { const output = structuredClone(result); Object.assign(output.implicit.dimensions[0]!, { level: 3 }); return output; })(),
  ]) {
    const app = await createPortraitServer({ workflow: async () => malformed as never });
    t.after(() => app.close());
    const created = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: fixture.bundle } });
    await delay(0);
    const job = (await app.inject(created.headers.location!)).json();
    assert.equal(job.status, 'failed');
    assert.equal(job.error.code, 'STRUCTURED_OUTPUT');
    assert.equal(job.portrait, undefined);
  }
});


test('task context preserves explicit unknowns and rejects incomplete context objects', async t => {
  const fixture = await syntheticFixture();
  let received: unknown;
  const app = await createPortraitServer({ workflow: async input => {
    received = input.bundle.task_context;
    throw Object.assign(new Error('context validation only'), { code: 'CONFIGURATION' });
  } });
  t.after(() => app.close());
  const task_context = { task_id: 'synthetic-task', observation_period: fixture.bundle.period, training_category: null, training_year: null, support_conditions: null };
  const bundle = { ...fixture.bundle, task_context };
  const response = await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle } });
  assert.equal(response.statusCode, 202);
  await delay(0);
  assert.deepEqual(received, task_context);
  const incomplete = { ...fixture.bundle, task_context: { task_id: 'synthetic-task' } };
  assert.equal((await app.inject({ method: 'POST', url: '/api/portraits', payload: { bundle: incomplete } })).statusCode, 400);
});
