import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';
import { test } from 'node:test';
import { createPortraitServer } from '../src/server.js';
import { syntheticFixture, syntheticPortrait } from '../skill-bridge.mjs';

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
  const example = document.paths['/api/portraits'].post.requestBody.content['application/json'].example;
  assert.equal(example.bundle.student_id, 'SYNTHETIC-API-001');
  assert.ok(document.paths['/api/portraits/{id}'].get);
  assert.ok(document.components.schemas.ParsedMaterialBundle);
  assert.ok(document.components.schemas.GraduatePortrait);
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
