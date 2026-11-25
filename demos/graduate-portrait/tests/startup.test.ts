import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadProjectEnv } from '../skill-bridge.mjs';
import { test } from 'node:test';
import { parseStartupOptions } from '../src/startup.js';

test('startup uses the existing port and five-minute job timeout defaults', () => {
  assert.deepEqual(parseStartupOptions({}), { port: 3001, timeoutMs: 300_000 });
});

test('startup accepts bounded integer job timeouts and an explicit port', () => {
  assert.deepEqual(parseStartupOptions({ PORTRAIT_PORT: '3012', PORTRAIT_JOB_TIMEOUT_MS: '900000' }), { port: 3012, timeoutMs: 900_000 });
  assert.equal(parseStartupOptions({ PORTRAIT_JOB_TIMEOUT_MS: '1000' }).timeoutMs, 1000);
});

test('startup rejects invalid, empty, non-integer and unbounded job timeouts', () => {
  for (const value of ['', ' ', '0', '-1', '999', '900001', '1.5', 'NaN', 'Infinity', 'unexpected']) {
    assert.throws(() => parseStartupOptions({ PORTRAIT_JOB_TIMEOUT_MS: value }), /PORTRAIT_JOB_TIMEOUT_MS must be an integer between 1000 and 900000/);
  }
});

test('startup preserves existing port validation', () => {
  for (const value of ['', '0', '65536', '1.5', 'NaN']) {
    assert.throws(() => parseStartupOptions({ PORTRAIT_PORT: value }), /PORTRAIT_PORT must be an integer between 1 and 65535/);
  }
});


test('startup reads the explicit project file and process variables override its timeout', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'portrait-startup-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const path = join(directory, '.env');
  await writeFile(path, 'PORTRAIT_JOB_TIMEOUT_MS=900000\nPORTRAIT_PORT=3013\n');
  const fileEnv = await loadProjectEnv({ env: {}, path });
  assert.deepEqual(parseStartupOptions(fileEnv), { port: 3013, timeoutMs: 900_000 });
  const overridden = await loadProjectEnv({ env: { PORTRAIT_JOB_TIMEOUT_MS: '600000' }, path });
  assert.equal(parseStartupOptions(overridden).timeoutMs, 600_000);
});
