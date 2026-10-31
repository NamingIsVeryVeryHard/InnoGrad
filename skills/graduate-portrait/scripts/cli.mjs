#!/usr/bin/env node
import { readFile,writeFile,mkdir } from 'node:fs/promises';
import { resolve,join } from 'node:path';
import { buildPortrait,validateExtraction,validateAssessment,validateAResult } from './engine.mjs';
import { prepareTask } from './prompts.mjs';
import { renderPortrait } from './report.mjs';
import { adapterConfig,requestStructured } from './adapter.mjs';
import { runPortraitWorkflow } from './workflow.mjs';
import { loadProjectEnv } from './env.mjs';
import { fixture } from './synthetic.mjs';
const json=async path=>{let contents;try{contents=await readFile(path,'utf8');}catch{throw new Error('input JSON file cannot be read');}try{return JSON.parse(contents);}catch{throw new Error('input JSON file is invalid');}};
const save=async(path,data)=>writeFile(path,JSON.stringify(data,null,2)+'\n',{mode:0o600});
function options(args) {
  const result={};for(let i=0;i<args.length;i+=2){if(!args[i].startsWith('--')||!args[i+1]||args[i+1].startsWith('--'))throw new Error('arguments require --name value');result[args[i].slice(2)]=args[i+1];}
  for(const k of Object.keys(result))if(!['bundle','extraction','assessment','out','rules','rubric','mode','producer-note','model','a-result','workflow-mode'].includes(k))throw new Error('unknown option');return result;
}
async function output(out,input){const result=buildPortrait(input);await mkdir(out,{recursive:true,mode:0o700});await save(join(out,'portrait.json'),result);await writeFile(join(out,'portrait.md'),renderPortrait(result),{mode:0o600});return result;}
async function main() {
  const [command,...args]=process.argv.slice(2);const o=options(args);
  if(command==='demo'){const f=fixture();f.provenance={mode:'synthetic',description:'synthetic/offline_replay'};const out=resolve(o.out??'local-runs/synthetic');await mkdir(out,{recursive:true,mode:0o700});for(const k of ['bundle','extraction','assessment'])await save(join(out,k+'.json'),f[k]);await output(out,f);console.log('synthetic/offline_replay completed');return;}
  if(!['prepare','validate','build','remote','workflow'].includes(command))throw new Error('commands: prepare, validate, build, demo, remote');
  if(!o.bundle)throw new Error('--bundle required');const bundle=await json(o.bundle);
  const rules=await json(o.rules??new URL('../references/explicit-rules.json',import.meta.url));const rubric=await json(o.rubric??new URL('../../graduate-implicit-assessment/references/implicit-rubric.json',import.meta.url));
  const out=o.out&&resolve(o.out);
  const workflowMode=o['workflow-mode']??'implicit_only';if(!['implicit_only','bundle_pipeline'].includes(workflowMode))throw new Error('unknown workflow mode');
  const aResult=o['a-result']?await json(o['a-result']):undefined;if(aResult)validateAResult(bundle,aResult,rules);
  if(command==='prepare'){if(!out)throw new Error('--out required');const tasks={...(workflowMode==='bundle_pipeline'&&!aResult?{extraction:prepareTask({bundle,rules,rubric})}:{}),assessment:prepareTask({bundle,rules,rubric,aResult},'assessment')};await mkdir(out,{recursive:true,mode:0o700});for(const [phase,task]of Object.entries(tasks)){await save(join(out,phase+'-task.json'),task);await save(join(out,phase+'-schema.json'),task.schema);}console.log('local task packages prepared');return;}
  if(command==='workflow'){if(!out)throw new Error('--out required');const result=await runPortraitWorkflow({bundle,rules,rubric,aResult,mode:workflowMode});await mkdir(out,{recursive:true,mode:0o700});await save(join(out,'portrait.json'),result);await writeFile(join(out,'portrait.md'),renderPortrait(result),{mode:0o600});console.log('InnoAgent Skill workflow completed');return;}
  if(command==='remote'){
    if(!out)throw new Error('--out required');const config=adapterConfig(await loadProjectEnv());
    const extracted=!aResult&&workflowMode==='bundle_pipeline'?await requestStructured(prepareTask({bundle,rules,rubric}),{config,validate:d=>validateExtraction(bundle,d,rules)}):null;
    const assessed=await requestStructured(prepareTask({bundle,rules,rubric,aResult},'assessment'),{config,validate:d=>validateAssessment(bundle,d,rubric)});
    await mkdir(out,{recursive:true,mode:0o700});if(extracted)await save(join(out,'extraction.json'),extracted.data);await save(join(out,'assessment.json'),assessed.data);
    await output(out,{bundle,rules,rubric,aResult,extraction:extracted?.data,assessment:assessed.data,provenance:{mode:'remote_model',model:assessed.model,description:JSON.stringify({protocol:'Chat Completions',extraction:extracted?.records??[],assessment:assessed.records})}});console.log('remote workflow completed');return;
  }
  if(o.mode==='remote_model')throw new Error('local build is a replay; remote_model is recorded only by a real request');
  if(o.model&&['synthetic','assistant_curated'].includes(o.mode))throw new Error('synthetic or curated mode cannot name a model');
  if(!o.assessment)throw new Error('--assessment required');if(aResult&&o.extraction)throw new Error('choose --a-result or --extraction');
  const input={bundle,rules,rubric,aResult,extraction:o.extraction?await json(o.extraction):undefined,assessment:await json(o.assessment),provenance:{mode:o.mode??'offline_replay',model:o.model??null,description:o['producer-note']??null}};
  if(command==='validate'){buildPortrait(input);console.log('validated');return;}if(!out)throw new Error('--out required');await output(out,input);console.log('local portrait built');
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
