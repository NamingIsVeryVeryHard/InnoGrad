import assert from 'node:assert/strict';
import test from 'node:test';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp,readFile,rm,cp,mkdir,writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const run=promisify(execFile);
const script=fileURLToPath(new URL('../../skills/graduate-portrait/scripts/cli.mjs',import.meta.url));
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
 await assert.rejects(run(process.execPath,[script,'remote','--bundle',join(dir,'bundle.json'),'--out',join(dir,'remote')],{env:{PATH:process.env.PATH,PORTRAIT_API_URL:'',PORTRAIT_API_MODEL:'',PORTRAIT_API_KEY:''}}),/PORTRAIT_API_URL/);
 } finally {await rm(dir,{recursive:true,force:true});}
});

test('可读报告保留六组、开题计划、被排除记录和真实出处',async()=>{
 const {fixture}=await import('../fixtures/portrait.mjs');const {buildPortrait}=await import('../../skills/graduate-portrait/scripts/engine.mjs');const {renderPortrait}=await import('../../skills/graduate-portrait/scripts/report.mjs');
 const f=fixture();f.bundle.documents[0].segments[0].page=2;f.extraction.items.push({...f.extraction.items[0],item_id:'plan',kind:'goal',title:'下一年完成验证',status:'planned',period_status:'out_of_scope'});const md=renderPortrait(buildPortrait(f));assert.match(md,/下一年完成验证：计划；非本期/);assert.match(md,/第2页/);assert.match(md,/A方法已发表/);assert.match(md,/材料未提供/);for(const g of f.rules.groups)assert.ok(md.includes(g.label));
});

test('业务Skill包复制后demo无需仓库fixture且哈希不依赖安装位置',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'portrait-standalone-'));try{const source=fileURLToPath(new URL('../../skills/graduate-portrait/',import.meta.url));await cp(source,join(dir,'graduate-portrait'),{recursive:true});await cp(fileURLToPath(new URL('../../skills/graduate-implicit-assessment/',import.meta.url)),join(dir,'graduate-implicit-assessment'),{recursive:true});const standalone=join(dir,'graduate-portrait','scripts','cli.mjs');await run(process.execPath,[standalone,'demo','--out',join(dir,'result')]);const result=JSON.parse(await readFile(join(dir,'result','portrait.json'),'utf8'));assert.equal(result.explicit.ledger.paper.published,2);const module=await import('../../skills/graduate-portrait/scripts/engine.mjs');const {fixture}=await import('../fixtures/portrait.mjs');const f=fixture();f.provenance={mode:'synthetic',description:'synthetic/offline_replay'};assert.equal(result.run_id,module.buildPortrait(f).run_id);
 await writeFile(join(dir,'invalid.json'),'{"PRIVATE_MARKER":');try{await run(process.execPath,[standalone,'prepare','--bundle',join(dir,'invalid.json'),'--out',join(dir,'task')]);assert.fail('invalid JSON should fail');}catch(e){assert.match(e.stderr,/input JSON file is invalid/);assert.ok(!e.stderr.includes('PRIVATE_MARKER'));}
 }finally{await rm(dir,{recursive:true,force:true});}
});
test('CLI只评价准备和B-only构建，以及完整A结果重放',async()=>{
 const {fixture}=await import('../fixtures/portrait.mjs');const {buildAResult}=await import('../../skills/graduate-portrait/scripts/handoff.mjs');const f=fixture();const dir=await mkdtemp(join(tmpdir(),'portrait-b-cli-'));
 try{for(const key of ['bundle','assessment'])await writeFile(join(dir,key+'.json'),JSON.stringify(f[key]));
 await run(process.execPath,[script,'prepare','--bundle',join(dir,'bundle.json'),'--out',join(dir,'task')]);await assert.rejects(readFile(join(dir,'task','extraction-task.json')));
 await run(process.execPath,[script,'build','--bundle',join(dir,'bundle.json'),'--assessment',join(dir,'assessment.json'),'--out',join(dir,'b')]);let p=JSON.parse(await readFile(join(dir,'b','portrait.json')));assert.equal(p.explicit_status,'pending');assert.match(await readFile(join(dir,'b','portrait.md'),'utf8'),/显性结果待接入/);
 const aResult=buildAResult({...f,metadata:{output_version:'A-fixture.1',generated_at:'2026-10-14T04:00:00Z',producer:{mode:'synthetic',name:null,model:null}}});await writeFile(join(dir,'a-result.json'),JSON.stringify(aResult));
 await run(process.execPath,[script,'prepare','--bundle',join(dir,'bundle.json'),'--a-result',join(dir,'a-result.json'),'--out',join(dir,'a-task')]);const aTask=JSON.parse(await readFile(join(dir,'a-task','assessment-task.json'),'utf8'));assert.deepEqual(aTask.explicit_context.extraction,aResult.extraction);assert.equal(Object.hasOwn(aTask.explicit_context,'explicit'),false);
 await run(process.execPath,[script,'build','--bundle',join(dir,'bundle.json'),'--assessment',join(dir,'assessment.json'),'--a-result',join(dir,'a-result.json'),'--out',join(dir,'merged')]);p=JSON.parse(await readFile(join(dir,'merged','portrait.json')));assert.equal(p.explicit_status,'merged');assert.deepEqual(p.explicit,aResult.explicit);
 }finally{await rm(dir,{recursive:true,force:true});}
});
test('年度与开题完整公共材料保留原文并生成七领域任务包',async()=>{
 const {validateBundle}=await import('../../skills/graduate-portrait/scripts/validation.mjs');const {loadConfiguration}=await import('../../skills/graduate-portrait/scripts/workflow.mjs');const {prepareTask}=await import('../../skills/graduate-portrait/scripts/prompts.mjs');const {rubric,rules}=await loadConfiguration();
 for(const name of ['annual-report.synthetic.json','proposal-report.synthetic.json']){const {bundle}=JSON.parse(await readFile(new URL('../../demos/graduate-portrait/examples/'+name,import.meta.url),'utf8'));validateBundle(bundle);const before=structuredClone(bundle);const task=prepareTask({bundle,rubric,rules},'assessment');assert.deepEqual(task.bundle,before);assert.equal(task.configuration.dimensions.length,7);assert.equal(task.schema.properties.schema_version.const,'2.0');assert.equal(task.criterion_standard_status['effect-check'],bundle.stage==='proposal'?'not_applicable':'applicable');}
});
