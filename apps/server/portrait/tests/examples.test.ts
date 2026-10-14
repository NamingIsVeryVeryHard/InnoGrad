import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import { portraitExamples } from '../src/examples.js';
import { createPortraitServer } from '../src/server.js';
import { validateBundle } from '../skill-bridge.mjs';
import type { ParsedMaterialBundle } from '../src/contracts.js';

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

test('both Swagger report examples pass HTTP validation unchanged without a model call', async t => {
  const received: ParsedMaterialBundle[] = [];
  const app = await createPortraitServer({ workflow: async ({ bundle }) => {
    received.push(bundle);
    throw Object.assign(new Error('synthetic example validation only'), { code: 'CONFIGURATION' });
  } });
  t.after(() => app.close());
  for (const example of Object.values(portraitExamples)) {
    const response = await app.inject({ method: 'POST', url: '/api/portraits', payload: example.value });
    assert.equal(response.statusCode, 202);
  }
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(received, Object.values(portraitExamples).map(example => example.value.bundle));
});
