import assert from 'node:assert/strict';
import test from 'node:test';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp,readFile,rm,cp,mkdir,writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const run=promisify(execFile);
const script=fileURLToPath(new URL('../../.agents/skills/graduate-portrait/scripts/cli.mjs',import.meta.url));
test('CLI从合成输入准备任务包、严格校验并一致重放',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'portrait-cli-'));try {
 await run(process.execPath,[script,'demo','--out',dir]);
 const first=JSON.parse(await readFile(join(dir,'portrait.json'),'utf8'));
 assert.equal(first.provenance.producer.mode,'synthetic');assert.equal(first.explicit.checks[0].status,'needs_review');
 const input=['--bundle',join(dir,'bundle.json'),'--extraction',join(dir,'extraction.json'),'--assessment',join(dir,'assessment.json')];
 await run(process.execPath,[script,'validate',...input]);
 await run(process.execPath,[script,'prepare','--bundle',join(dir,'bundle.json'),'--out',join(dir,'task')]);
 const task=JSON.parse(await readFile(join(dir,'task','assessment-task.json'),'utf8')); assert.equal(task.phase,'assessment'); assert.equal(task.schema.additionalProperties,false);
 await run(process.execPath,[script,'build',...input,'--out',join(dir,'replay'),'--mode','synthetic','--producer-note','synthetic/offline_replay']);
 assert.deepEqual(JSON.parse(await readFile(join(dir,'replay','portrait.json'),'utf8')),first);
 const md=await readFile(join(dir,'portrait.md'),'utf8');assert.match(md,/待人工复核/);assert.match(md,/自报 3；逐项 2/);
 await assert.rejects(run(process.execPath,[script,'remote','--bundle',join(dir,'bundle.json'),'--out',join(dir,'remote')],{env:{PATH:process.env.PATH}}),/PORTRAIT_API_URL/);
 } finally {await rm(dir,{recursive:true,force:true});}
});

test('可读报告保留六组、开题计划、被排除记录和真实出处',async()=>{
 const {fixture}=await import('../fixtures/portrait.mjs');const {buildPortrait}=await import('../../.agents/skills/graduate-portrait/scripts/engine.mjs');const {renderPortrait}=await import('../../.agents/skills/graduate-portrait/scripts/report.mjs');
 const f=fixture();f.bundle.documents[0].segments[0].page=2;f.extraction.items.push({...f.extraction.items[0],item_id:'plan',kind:'goal',title:'下一年完成验证',status:'planned',period_status:'out_of_scope'});const md=renderPortrait(buildPortrait(f));assert.match(md,/下一年完成验证：计划；非本期/);assert.match(md,/第2页/);assert.match(md,/A方法已发表/);assert.match(md,/材料未提供/);for(const g of f.rules.groups)assert.ok(md.includes(g.label));
});

test('Skill独立复制后demo无需仓库fixture且哈希不依赖安装位置',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'portrait-standalone-'));try{const source=fileURLToPath(new URL('../../.agents/skills/graduate-portrait/',import.meta.url));await cp(source,join(dir,'skill'),{recursive:true});const standalone=join(dir,'skill','scripts','cli.mjs');await run(process.execPath,[standalone,'demo','--out',join(dir,'result')]);const result=JSON.parse(await readFile(join(dir,'result','portrait.json'),'utf8'));assert.equal(result.explicit.ledger.paper.published,2);const module=await import('../../.agents/skills/graduate-portrait/scripts/engine.mjs');const {fixture}=await import('../fixtures/portrait.mjs');const f=fixture();f.provenance={mode:'synthetic',description:'synthetic/offline_replay'};assert.equal(result.run_id,module.buildPortrait(f).run_id);
 await writeFile(join(dir,'invalid.json'),'{"PRIVATE_MARKER":');try{await run(process.execPath,[standalone,'prepare','--bundle',join(dir,'invalid.json'),'--out',join(dir,'task')]);assert.fail('invalid JSON should fail');}catch(e){assert.match(e.stderr,/input JSON file is invalid/);assert.ok(!e.stderr.includes('PRIVATE_MARKER'));}
 }finally{await rm(dir,{recursive:true,force:true});}
});
