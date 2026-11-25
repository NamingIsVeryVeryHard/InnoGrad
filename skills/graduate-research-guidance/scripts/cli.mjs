#!/usr/bin/env node
import {chmod, mkdir, readdir, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {loadEnvFile} from 'node:process';
import {parseArgs} from 'node:util';
import {innoAgentConfig, createInnoAgentRunner} from '../../graduate-portrait/scripts/workflow.mjs';
import {loadContext} from './input.mjs';
import {generateGuidance, formatGuidance, guidanceRepairFeedback} from './workflow.mjs';

async function main() {
  const {values, positionals} = parseArgs({allowPositionals: true, options: {
    current: {type: 'string'}, history: {type: 'string', multiple: true},
    portrait: {type: 'string'}, out: {type: 'string'}, help: {type: 'boolean'},
  }});
  if (values.help) {
    console.log('Usage: node cli.mjs run --current REPORT --out NEW_DIR [--history REPORT] [--portrait PORTRAIT.json]');
    return;
  }
  if (positionals.length !== 1 || positionals[0] !== 'run' || !values.current || !values.out) {
    throw new Error('expected run --current REPORT --out NEW_DIR');
  }
  if (process.env.PORTRAIT_ENV_FILE) loadEnvFile(process.env.PORTRAIT_ENV_FILE);
  const context = await loadContext(values);
  const config = await innoAgentConfig(process.env);
  const out = resolve(values.out);
  await mkdir(out, {recursive: true, mode: 0o700});
  await chmod(out, 0o700);
  if ((await readdir(out)).length) throw new Error('output directory must be empty; choose a new --out');
  const save = (path, content) => writeFile(path, content, {mode: 0o600});
  let runner;
  try {
    runner = await createInnoAgentRunner(config, {skillNames: ['graduate-research-guidance'],
      formatRepairFeedback: guidanceRepairFeedback});
    const result = await generateGuidance(context, {runner});
    await save(`${out}/result.json`, JSON.stringify(result, null, 2) + '\n');
    await save(`${out}/result.md`, formatGuidance(result));
    await save(`${out}/run.json`, JSON.stringify({
      status: 'generated', history_count: context.scope.history.length, provenance: result.provenance,
    }, null, 2) + '\n');
    console.log(JSON.stringify({out, provenance: result.provenance, recommendations: result.guidance.length}, null, 2));
  } catch (error) {
    let origin = null;
    if (runner) try { origin = await runner.provenance(); } catch {}
    await save(`${out}/run.json`, JSON.stringify({
      status: 'failed', error_code: error.code ?? 'OUTPUT_FAILURE',
      ...(error.validation_issues ? {validation_issues: error.validation_issues} : {}),
      provenance: {platform: 'InnoAgent', model_called: origin ? origin.model_attempts.length > 0 : null,
        session_ids: runner?.session_ids ?? [], installed_skill_hashes: runner?.installed_skill_hashes ?? {},
        records: origin?.model_attempts ?? []},
    }, null, 2) + '\n');
    throw error;
  }
}
main().catch(error => {
  console.error(`guidance failed: ${error.message}`);
  process.exitCode = 1;
});
