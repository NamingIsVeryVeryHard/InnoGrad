import {readFile, writeFile, mkdir, readdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {prepareTrajectoryUpdate, updateResearchTrajectory}
  from '../../../skills/graduate-portrait/scripts/trajectory.mjs';
import {createInnoAgentRunner, innoAgentConfig} from '../../../skills/graduate-portrait/scripts/workflow.mjs';
import {loadProjectEnv} from '../../../skills/graduate-portrait/scripts/env.mjs';

export async function runProfileUpdate(values) {
  if (!values.current || !values.out) throw new Error('update 需要 --current 和 --out');
  const read = async path => JSON.parse(await readFile(resolve(path), 'utf8'));
  const input = {bundle: await read(values.current),
    previous: values.previous ? await read(values.previous) : null,
    recordedAt: values.date ?? null, dateBasis: values['date-basis'] ?? null};
  const prepared = prepareTrajectoryUpdate(input);
  const out = resolve(values.out);
  await mkdir(out, {recursive: true});
  if ((await readdir(out)).length) throw new Error('--out 必须指向空目录，已有版本不覆盖');
  const save = (name, data) => writeFile(resolve(out, name), JSON.stringify(data, null, 2) + '\n', {mode: 0o600});
  const run = {status: 'running', started_at: new Date().toISOString(), mode: 'research_trajectory_update'};
  await save('input.json', input);
  await save('run.json', run);
  let runner;
  try {
    if (prepared.status !== 'unchanged') {
      const env = await loadProjectEnv(process.env);
      runner = await createInnoAgentRunner(await innoAgentConfig(env), {skillNames: ['graduate-portrait']});
    }
    const result = await updateResearchTrajectory(input, {runner});
    await save('profile.json', result.profile);
    Object.assign(run, {status: 'completed', update_status: result.status,
      version: result.profile.version, finished_at: new Date().toISOString(), provenance: result.provenance});
    await save('run.json', run);
    console.log(JSON.stringify({out, status: result.status, version: result.profile.version,
      model: result.provenance.model ?? null}));
  } catch (error) {
    Object.assign(run, {status: 'failed', finished_at: new Date().toISOString(),
      error: error.code ?? error.message, session_ids: runner?.session_ids ?? []});
    await save('run.json', run);
    throw error;
  }
}
