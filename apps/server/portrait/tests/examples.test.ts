import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import { portraitExamples } from '../src/examples.js';
import { createPortraitServer } from '../src/server.js';
import { validateBundle, validateAResult, loadConfiguration } from '../skill-bridge.mjs';
import type { ParsedMaterialBundle } from '../src/contracts.js';
import { execFileSync } from 'node:child_process';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

test('synthetic report examples have reproducible text hashes and explicit simulated provenance', () => {
  for (const { value: { bundle } } of Object.values(portraitExamples)) {
    validateBundle(bundle);
    for (const document of bundle.documents) {
      assert.match(document.source_name, /全虚构.*模拟分页.*无原PDF/);
      const text = document.segments.map(segment => segment.text).join('\f');
      assert.equal(document.sha256, createHash('sha256').update(text, 'utf8').digest('hex'));
      assert.deepEqual(document.segments.map(segment => segment.page), document.segments.map((_, index) => index + 1));
      assert.ok(document.segments.every(segment => /全虚构合成示例/.test(segment.text)));
    }
  }
  assert.equal(portraitExamples.annualReport.value.bundle.period, '2027-2028');
  assert.equal(portraitExamples.proposalReport.value.bundle.period, null);
});

test('all Swagger examples pass HTTP validation unchanged without a model call', async t => {
  const received: ParsedMaterialBundle[] = [];
  const app = await createPortraitServer({ workflow: async ({ bundle }) => {
    received.push(bundle);
    throw Object.assign(new Error('synthetic example validation only'), { code: 'CONFIGURATION' });
  } });
  t.after(() => app.close());
  for (const example of Object.values(portraitExamples)) {
    const response = await app.inject({ method: 'POST', url: '/api/portraits', payload: example.value });
    assert.equal(response.statusCode, 202);
    await new Promise(resolve => setImmediate(resolve));
  }
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(received, Object.values(portraitExamples).map(example => example.value.bundle));
});


test('A handoff Swagger example reuses full annual material and passes the shared contract', async t => {
  const annual = JSON.parse(readFileSync(new URL('../examples/annual-report.synthetic.json', import.meta.url), 'utf8'));
  const proposal = JSON.parse(readFileSync(new URL('../examples/proposal-report.synthetic.json', import.meta.url), 'utf8'));
  assert.deepEqual(portraitExamples.annualReport.value, annual);
  assert.deepEqual(portraitExamples.proposalReport.value, proposal);
  assert.deepEqual(portraitExamples.annualWithAResult.value.bundle, annual.bundle);
  const { rules } = await loadConfiguration();
  const { bundle, aResult } = portraitExamples.annualWithAResult.value;
  validateAResult(bundle, aResult, rules);
  assert.equal(aResult.producer.mode, 'synthetic');
  assert.equal(aResult.producer.model, null);
  assert.equal(aResult.extraction.items.length, 4);
  assert.deepEqual(aResult.extraction.items.map(item => item.status), ['published', 'under_review', 'accepted', 'in_progress']);
  assert.equal(aResult.explicit.checks.find(check => check.id === 'credit-requirement')?.status, 'pending_rule');
  let received: unknown;
  const app = await createPortraitServer({ workflow: async input => {
    received = input.aResult;
    throw Object.assign(new Error('example contract validation only'), { code: 'CONFIGURATION' });
  } });
  t.after(() => app.close());
  const response = await app.inject({ method: 'POST', url: '/api/portraits', payload: portraitExamples.annualWithAResult.value });
  assert.equal(response.statusCode, 202);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(received, aResult);
});

test('CLI prepare retains full Swagger annual material and A extraction without explicit results', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'portrait-swagger-context-'));
  try {
    const { bundle, aResult } = portraitExamples.annualWithAResult.value;
    await writeFile(join(directory, 'bundle.json'), JSON.stringify(bundle));
    await writeFile(join(directory, 'a-result.json'), JSON.stringify(aResult));
    const cli = fileURLToPath(new URL('../../../../skills/graduate-portrait/scripts/cli.mjs', import.meta.url));
    execFileSync(process.execPath, [cli, 'prepare', '--bundle', join(directory, 'bundle.json'), '--a-result', join(directory, 'a-result.json'), '--out', join(directory, 'task')]);
    const task = JSON.parse(await readFile(join(directory, 'task', 'assessment-task.json'), 'utf8'));
    assert.deepEqual(task.bundle, bundle);
    assert.deepEqual(task.explicit_context.extraction, aResult.extraction);
    assert.equal(task.explicit_context.producer.mode, 'synthetic');
    assert.equal(Object.hasOwn(task.explicit_context, 'explicit'), false);
    assert.equal(Object.hasOwn(task, 'aResult'), false);
    assert.equal(task.configuration.dimensions.length, 7);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
