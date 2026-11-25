import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { fixture } from './fixtures/case.mjs';

const cli = fileURLToPath(new URL('../run.mjs', import.meta.url));
const run = (...args) => spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8' });
async function localCase(t) {
  const dir = await mkdtemp(join(tmpdir(), 'portrait-case-test-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const input = fixture(), entries = [];
  for (const m of input.materials) {
    await writeFile(join(dir, m.id + '-bundle.json'), JSON.stringify({ bundle: m.bundle }));
    await writeFile(join(dir, m.id + '-portrait.json'), JSON.stringify(m.portrait));
    entries.push({ id: m.id, role: m.role, bundle: m.id + '-bundle.json', portrait: m.id + '-portrait.json' });
  }
  const manifestPath = join(dir, 'case.json');
  await writeFile(manifestPath, JSON.stringify({ ...input.manifest, materials: entries }));
  return manifestPath;
}

test('默认与--help只显示真实本地输入用法，不运行合成故事', () => {
  for (const args of [[], ['--help']]) {
    const result = run(...args);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /--input/);
    assert.doesNotMatch(result.stdout, /SYNTHETIC|先实现后/);
  }
});

test('相对manifest路径加载原始画像，CLI输出完整JSON与中文Markdown', async t => {
  const path = await localCase(t);
  const json = run('--input', path, '--json');
  assert.equal(json.status, 0, json.stderr);
  const data = JSON.parse(json.stdout);
  assert.equal(data.input.materials.length, 2);
  assert.equal(data.result.provenance.data_nature, 'test_fixture');
  assert.equal(data.result.provenance.model_called, false);
  assert.equal(data.input.materials[1].portrait.implicit.dimensions[0].criteria[0].performance_grade, 'meets_requirements');
  const markdown = run('--input', path);
  assert.equal(markdown.status, 0, markdown.stderr);
  assert.match(markdown.stdout, /# 真实材料画像对应与建议/);
  assert.match(markdown.stdout, /不能据此认定学生采纳或执行/);
  assert.equal(markdown.stderr, '');
});

test('输入错误、JSON错误及已移除的合成参数退出1，不输出半份结果', async t => {
  const path = await localCase(t);
  await writeFile(path, '{');
  for (const args of [['--input', path], ['--input', path + '-missing'], ['--json'], ['--scenario', 'design'], ['--feedback']]) {
    const result = run(...args);
    assert.equal(result.status, 1);
    assert.equal(result.stdout, '');
    assert.match(result.stderr, /错误/);
  }
});

test('实现仅使用Node原生模块，不依赖网络或第三方包', async () => {
  const pkg = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
  assert.equal(Object.keys(pkg.dependencies ?? {}).length, 0);
  for (const path of ['../run.mjs', '../src/real-case.mjs']) {
    const text = await readFile(new URL(path, import.meta.url), 'utf8');
    assert.doesNotMatch(text, /\bfetch\s*\(|https?:\/\/|from\s+['"](?!\.|node:)/);
  }
});
