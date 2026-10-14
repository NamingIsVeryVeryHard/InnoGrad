import test from 'node:test';
import assert from 'node:assert/strict';
import {runPortraitWorkflow,createInnoAgentRunner} from '../../skills/graduate-portrait/scripts/workflow.mjs';
import {fixture} from '../fixtures/portrait.mjs';
import {createModelGateway} from '../../skills/graduate-portrait/scripts/gateway.mjs';
import {loadProjectEnv} from '../../skills/graduate-portrait/scripts/env.mjs';
import {mkdtemp,writeFile,rm,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
const skillBody=await readFile(new URL('../../skills/graduate-portrait/SKILL.md',import.meta.url),'utf8');
const implicitSkillBody=await readFile(new URL('../../skills/graduate-implicit-assessment/SKILL.md',import.meta.url),'utf8');
const skillList=['graduate-portrait','graduate-implicit-assessment'].map(name=>({name,loaded:true,enabled:true}));
const emptySynthesis=()=>({current_work:[],demonstrated:[],attention:[],next_steps:[]});
const reply=data=>({ok:true,json:async()=>data});
function onlineFixture(){
 const f=fixture();
 for(const d of f.assessment.dimensions)for(const c of d.criteria){
  const definition=f.rubric.dimensions.find(x=>x.id===d.dimension_id).criteria.find(x=>x.id===c.criterion_id);
  c.condition_checks=definition.required_conditions.map((_,i)=>({condition_index:i,status:c.performance_grade?'supported':'unobserved',evidence_indices:c.performance_grade?[0]:[],reason:c.rationale}));
 }
 return f;
}
test('InnoAgent必须实际加载Skill、新建独立工作区并验证session',async()=>{let paths=[];const f=onlineFixture();let phase=0;const runner=await createInnoAgentRunner({url:'http://localhost:3147',timeoutMs:1000},{fetchImpl:async(url,init)=>{paths.push(new URL(url).pathname);if(url.endsWith('/api/skills'))return reply(skillList);if(url.endsWith('/content'))return reply({content:url.includes('graduate-implicit-assessment')?implicitSkillBody:skillBody});if(url.endsWith('/api/sessions')){assert.equal(JSON.parse(init.body).newWorkspace.isTemp,false);return reply({id:'s',workspaceId:'portrait-123'});}if(url.endsWith('/api/sessions/s'))return reply({id:'s'});const task=JSON.parse(JSON.parse(init.body).prompt.split('\n').at(-1));const command=JSON.parse(init.body).prompt.split(' ')[0];if(task.phase!=='extraction')assert.equal(command,task.phase==='assessment'?'/skill:graduate-implicit-assessment':'/skill:graduate-portrait');const result=JSON.stringify(task.phase==='synthesis'?emptySynthesis():phase++===0?f.extraction:{...f.assessment,dimensions:f.assessment.dimensions.filter(d=>d.dimension_id===task.dimension_id)});return new Response('data: '+JSON.stringify({sessionId:'s',turnId:'t',event:{type:'text_delta',delta:result}})+'\n\ndata: '+JSON.stringify({sessionId:'s',turnId:'t',event:{type:'done'}})+'\n\n');}});const p=await runPortraitWorkflow({...f,mode:'bundle_pipeline',runner});assert.equal(p.explicit.checks[0].status,'needs_review');assert.equal(p.provenance.producer.mode,'skill_execution');assert.equal(paths.filter(x=>x==='/api/chat/stream').length,2+f.rubric.dimensions.length);assert.deepEqual(runner.records,[{phase:'extraction',attempts:1},...f.rubric.dimensions.map(d=>({phase:'assessment',dimension_id:d.id,attempts:1})),{phase:'synthesis',attempts:1}]);await assert.rejects(createInnoAgentRunner({url:'http://localhost',timeoutMs:1000},{fetchImpl:async()=>reply([])}),e=>e.code==='CONFIGURATION');});
test('环境加载只读显式文件且进程环境优先',async()=>{const dir=await mkdtemp(join(tmpdir(),'portrait-env-'));try{const path=join(dir,'.env');await writeFile(path,'PORTRAIT_API_MODEL=file-model\nPORTRAIT_API_KEY=synthetic\n');const env=await loadProjectEnv({env:{PORTRAIT_ENV_FILE:path,PORTRAIT_API_MODEL:'process-model'}});assert.equal(env.PORTRAIT_API_MODEL,'process-model');assert.equal(env.PORTRAIT_API_KEY,'synthetic');}finally{await rm(dir,{recursive:true,force:true});}});
test('网关保留stream与tools，SSE实际model和备用记录不含key',async()=>{const records=[];let calls=0;const gateway=createModelGateway({config:{url:'https://primary.invalid',model:'ecnu-plus',key:'SECRET',provider:'ecnu',timeoutMs:1000,fallbacks:[{url:'http://127.0.0.1:8318/v1/chat/completions',model:'grok-4.6',key:'SECRET2',provider:'grok',effort:'low'}]},onAttempt:r=>records.push(r),fetchImpl:async(_url,init)=>{const b=JSON.parse(init.body);assert.equal(b.stream,true);assert.equal(b.tools[0].type,'function');if(calls++===0)return new Response(JSON.stringify({error:{code:'insufficient_quota'}}),{status:429});assert.equal(b.reasoning_effort,'low');return new Response('data: '+JSON.stringify({model:'actual-grok',choices:[{delta:{tool_calls:[{index:0,id:'call',type:'function',function:{name:'read',arguments:'{}'}}]},finish_reason:'tool_calls'}]})+'\n\ndata: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});}});await new Promise(r=>gateway.listen(0,'127.0.0.1',r));try{const url='http://127.0.0.1:'+gateway.address().port;const response=await fetch(url+'/v1/chat/completions',{method:'POST',body:JSON.stringify({messages:[{role:'user',content:'<skill name="graduate-portrait">body</skill>\n\nportrait_run_id:00000000-0000-0000-0000-000000000000 phase data' }],stream:true,tools:[{type:'function'}]})});assert.equal(response.status,200);assert.match(await response.text(),/actual-grok/);assert.equal(records.length,2);assert.equal(records[1].actual_model,'actual-grok');assert.ok(!JSON.stringify(records).includes('SECRET'));const audit=await(await fetch(url+'/runs/00000000-0000-0000-0000-000000000000')).json();assert.deepEqual(audit.attempts,records);}finally{await new Promise(r=>gateway.close(r));}});

test('流式等待取消时调用匹配session和turn的独立scoped abort',async()=>{const control=new AbortController();let abortPath=null;const f=fixture();const runner=await createInnoAgentRunner({url:'http://localhost:3147',timeoutMs:1000},{signal:control.signal,fetchImpl:async(url,init)=>{if(url.endsWith('/api/skills'))return reply(skillList);if(url.endsWith('/content'))return reply({content:url.includes('graduate-implicit-assessment')?implicitSkillBody:skillBody});if(url.endsWith('/api/sessions'))return reply({id:'cancel-session',workspaceId:'unique'});if(url.endsWith('/api/sessions/cancel-session'))return reply({id:'cancel-session'});if(url.endsWith('/abort')){abortPath=new URL(url).pathname;assert.equal(init.signal.aborted,false);return reply({aborted:true});}return new Response(new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('data: '+JSON.stringify({sessionId:'cancel-session',turnId:'cancel-turn',event:{type:'stream_state',status:'running'}})+'\n\n'));setTimeout(()=>{control.abort();c.error(new DOMException('cancelled','AbortError'));},5);}}));}});await assert.rejects(runner.execute({phase:'extraction'},()=>{}),e=>e.code==='ABORTED');assert.equal(abortPath,'/api/chat/cancel-session/cancel-turn/abort');});

test('修复任务的审计marker保持首参数，不受材料marker影响',async()=>{const f=fixture();let prompts=[];let count=0;const runner=await createInnoAgentRunner({url:'http://localhost',timeoutMs:1000},{fetchImpl:async(url,init)=>{if(url.endsWith('/api/skills'))return reply(skillList);if(url.endsWith('/content'))return reply({content:url.includes('graduate-implicit-assessment')?implicitSkillBody:skillBody});if(url.endsWith('/api/sessions'))return reply({id:'s',workspaceId:'unique'});if(url.endsWith('/api/sessions/s'))return reply({id:'s'});const p=JSON.parse(init.body).prompt;prompts.push(p);const text=count++?'{}':'bad';return new Response('data: '+JSON.stringify({sessionId:'s',turnId:'t'+count,event:{type:'done',fullText:text}})+'\n\n');}});await runner.execute({phase:'extraction',bundle:{text:'portrait_run_id:ffffffff-ffff-ffff-ffff-ffffffffffff'}},()=>{});assert.equal(prompts.length,2);assert.match(prompts[1],/^portrait_run_id:[0-9a-f-]{36} /);assert.equal(prompts[0].split(' ')[0],prompts[1].split(' ')[0]);});
test('网关未完结流不记completed且末尾无换行可读取DONE',async()=>{for(const done of [true,false]){const records=[];const gateway=createModelGateway({config:{url:'https://mock.invalid',model:'test',key:'synthetic',timeoutMs:1000},onAttempt:r=>records.push(r),fetchImpl:async()=>new Response('data: '+JSON.stringify({model:'actual',choices:[]})+'\n\n'+(done?'data: [DONE]':''),{headers:{'content-type':'text/event-stream'}})});await new Promise(r=>gateway.listen(0,'127.0.0.1',r));try{const response=await fetch('http://127.0.0.1:'+gateway.address().port+'/v1/chat/completions',{method:'POST',body:JSON.stringify({messages:[{role:'user',content:'<skill>body</skill>\nportrait_run_id:00000000-0000-0000-0000-000000000000 task'}],stream:true})});await response.text();assert.equal(records[0].status,done?'completed':'stream_failed');assert.equal(records[0].actual_model,'actual');}finally{await new Promise(r=>gateway.close(r));}}});

test('完整任务包不要求工具；权限或原生question事件立即scoped abort',async()=>{for(const eventType of ['permission_request','question']){let abortCalls=0;const runner=await createInnoAgentRunner({url:'http://localhost',timeoutMs:240000},{fetchImpl:async(url,init)=>{if(url.endsWith('/api/skills'))return reply(skillList);if(url.endsWith('/content'))return reply({content:url.includes('graduate-implicit-assessment')?implicitSkillBody:skillBody});if(url.endsWith('/api/sessions'))return reply({id:'permission-session',workspaceId:'unique'});if(url.endsWith('/api/sessions/permission-session'))return reply({id:'permission-session'});if(url.endsWith('/abort')){abortCalls++;assert.match(url,/permission-session\/permission-turn\/abort$/);return reply({cancelRequested:true});}const prompt=JSON.parse(init.body).prompt;assert.match(prompt,/任务包已完整包含/);assert.match(prompt,/禁止使用read、bash/);return new Response('data: '+JSON.stringify({sessionId:'permission-session',turnId:'permission-turn',event:{type:eventType,toolName:'bash'}})+'\n\n');}});await assert.rejects(runner.execute({phase:'extraction'},()=>{}),e=>e.code==='TOOL_APPROVAL_REQUIRED');assert.equal(abortCalls,1);}});

test('权限挂起后的取消失败明确保留后端取消未确认',async()=>{const runner=await createInnoAgentRunner({url:'http://localhost',timeoutMs:1000},{fetchImpl:async(url)=>{if(url.endsWith('/api/skills'))return reply(skillList);if(url.endsWith('/content'))return reply({content:url.includes('graduate-implicit-assessment')?implicitSkillBody:skillBody});if(url.endsWith('/api/sessions'))return reply({id:'permission-session',workspaceId:'unique'});if(url.endsWith('/api/sessions/permission-session'))return reply({id:'permission-session'});if(url.endsWith('/abort'))return {ok:false,status:503};return new Response('data: '+JSON.stringify({sessionId:'permission-session',turnId:'permission-turn',event:{type:'permission_request'}})+'\n\n');}});await assert.rejects(runner.execute({phase:'extraction'},()=>{}),e=>e.code==='TOOL_APPROVAL_REQUIRED'&&e.message.includes('backend cancellation unconfirmed'));});

test('网关在DONE后结束转发，客户端关闭和上游未EOF不改写完成审计',async()=>{let upstreamCancelled=false;const records=[];const gateway=createModelGateway({config:{url:'https://mock.invalid',model:'test',key:'synthetic',timeoutMs:1000},onAttempt:r=>records.push(r),fetchImpl:async()=>new Response(new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('data: '+JSON.stringify({model:'actual',choices:[{finish_reason:'stop',delta:{content:'{}'}}]})+'\n\ndata: [DONE]\n\n'));},cancel(){upstreamCancelled=true;}}),{headers:{'content-type':'text/event-stream'}})});await new Promise(r=>gateway.listen(0,'127.0.0.1',r));try{const response=await fetch('http://127.0.0.1:'+gateway.address().port+'/v1/chat/completions',{method:'POST',body:JSON.stringify({messages:[],stream:true})});const reader=response.body.getReader();const chunk=await reader.read();assert.match(new TextDecoder().decode(chunk.value),/\[DONE\]/);await reader.cancel();await new Promise(r=>setImmediate(r));assert.equal(records.length,1);assert.equal(records[0].status,'completed');assert.equal(records[0].stream_termination,'done_marker');assert.equal(records[0].finish_reason,'stop');assert.equal(upstreamCancelled,true);}finally{gateway.closeAllConnections();await new Promise(r=>gateway.close(r));}});

test('仅收到finish_reason而未DONE的客户端取消仍记aborted',async()=>{const records=[];const gateway=createModelGateway({config:{url:'https://mock.invalid',model:'test',key:'synthetic',timeoutMs:1000},onAttempt:r=>records.push(r),fetchImpl:async(_url,init)=>new Response(new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('data: '+JSON.stringify({model:'actual',choices:[{finish_reason:'stop',delta:{content:'{}'}}]})+'\n\n'));init.signal.addEventListener('abort',()=>c.error(new DOMException('cancelled','AbortError')),{once:true});}}),{headers:{'content-type':'text/event-stream'}})});await new Promise(r=>gateway.listen(0,'127.0.0.1',r));try{const response=await fetch('http://127.0.0.1:'+gateway.address().port+'/v1/chat/completions',{method:'POST',body:JSON.stringify({messages:[],stream:true})});const reader=response.body.getReader();await reader.read();await reader.cancel();for(let i=0;i<50&&!records.length;i++)await new Promise(r=>setTimeout(r,5));assert.equal(records.length,1);assert.equal(records[0].status,'aborted');assert.equal(records[0].finish_reason,'stop');assert.equal(records[0].stream_termination,'client_closed_before_done');}finally{gateway.closeAllConnections();await new Promise(r=>gateway.close(r));}});
test('默认B只评价；显式联调才抽取，已有A结果绝不重算',async()=>{
 const f=fixture();const phases=[];const runner={async execute(task,validate){phases.push(task.phase);if(task.phase==='synthesis'){const data=emptySynthesis();validate(data);return data;}const data=task.phase==='extraction'?f.extraction:{...f.assessment,dimensions:f.assessment.dimensions.filter(d=>d.dimension_id===task.dimension_id)};validate(data);return data;}};
 let p=await runPortraitWorkflow({...f,runner});assert.deepEqual(phases,[...f.rubric.dimensions.map(()=> 'assessment'),'synthesis']);assert.equal(p.explicit_status,'pending');
 phases.length=0;p=await runPortraitWorkflow({...f,mode:'bundle_pipeline',runner});assert.deepEqual(phases,['extraction',...f.rubric.dimensions.map(()=> 'assessment'),'synthesis']);assert.equal(p.explicit_status,'local_pipeline');
 const {buildAResult}=await import('../../skills/graduate-portrait/scripts/handoff.mjs');const aResult=buildAResult({...f,metadata:{output_version:'A-synthetic.1',generated_at:'2026-10-14T04:00:00Z',producer:{mode:'synthetic',name:null,model:null}}});
 phases.length=0;p=await runPortraitWorkflow({...f,aResult,mode:'bundle_pipeline',runner});assert.deepEqual(phases,[...f.rubric.dimensions.map(()=> 'assessment'),'synthesis']);assert.deepEqual(p.explicit,aResult.explicit);
});

test('逐域workflow传入同一A事实快照且不传显性计算结果',async()=>{
 const f=fixture();const {buildAResult}=await import('../../skills/graduate-portrait/scripts/handoff.mjs');
 const aResult=buildAResult({...f,metadata:{output_version:'A-synthetic-context.1',generated_at:'2026-10-14T04:00:00Z',producer:{mode:'synthetic',name:null,model:null}}});
 const before=structuredClone(aResult);const tasks=[];
 const runner={async execute(task,validate){if(task.phase==='synthesis'){assert.deepEqual(task.context.explicit_status,'merged');return emptySynthesis();}tasks.push(task);assert.deepEqual(task.explicit_context.extraction,aResult.extraction);assert.equal(Object.hasOwn(task.explicit_context,'explicit'),false);const result={...f.assessment,dimensions:f.assessment.dimensions.filter(d=>d.dimension_id===task.dimension_id)};validate(result);return result;}};
 const p=await runPortraitWorkflow({...f,aResult,runner});
 assert.equal(tasks.length,f.rubric.dimensions.length);assert.deepEqual(p.explicit,before.explicit);assert.deepEqual(p.explicit_extraction,before.extraction);assert.deepEqual(aResult,before);
});

test('平台创建会话409 session_busy明确报告忙且不重试',async()=>{
 let creationCalls=0;
 const config={url:'http://localhost',timeoutMs:1000};
 const fetchImpl=async url=>{
  if(url.endsWith('/api/skills'))return reply(skillList);
  if(url.endsWith('/content'))return reply({content:url.includes('graduate-implicit-assessment')?implicitSkillBody:skillBody});
  if(url.endsWith('/api/sessions')){creationCalls++;return new Response(JSON.stringify({error:'session_busy',blocking:{sessionId:'other-student',turnId:'active-turn'}}),{status:409});}
  throw new Error('unexpected request');
 };
 await assert.rejects(createInnoAgentRunner(config,{fetchImpl}),e=>e.code==='INNOAGENT_BUSY'&&e.status===409&&!e.message.includes('other-student'));
 assert.equal(creationCalls,1);
});

test('平台同会话活跃turn冲突报告忙且不重试或取消既有turn',async()=>{
 let streamCalls=0;
 const runner=await createInnoAgentRunner({url:'http://localhost',timeoutMs:1000},{fetchImpl:async url=>{
  if(url.endsWith('/api/skills'))return reply(skillList);
  if(url.endsWith('/content'))return reply({content:url.includes('graduate-implicit-assessment')?implicitSkillBody:skillBody});
  if(url.endsWith('/api/sessions'))return reply({id:'s',workspaceId:'unique'});
  if(url.endsWith('/api/sessions/s'))return reply({id:'s'});
  if(url.endsWith('/api/chat/stream')){streamCalls++;return new Response(JSON.stringify({error:'Session already has an active chat turn'}),{status:409});}
  throw new Error('unexpected request');
 }});
 await assert.rejects(runner.execute({phase:'assessment'},()=>{}),e=>e.code==='INNOAGENT_BUSY'&&e.status===409);
 assert.equal(streamCalls,1);
});

test('其他HTTP错误或无法识别的409保留REMOTE_HTTP',async()=>{
 for(const [status,body] of [[409,'{"error":"unexpected_conflict"}'],[409,'not-json'],[503,'{"error":"session_busy"}']]){
  await assert.rejects(createInnoAgentRunner({url:'http://localhost',timeoutMs:1000},{fetchImpl:async()=>new Response(body,{status})}),e=>e.code==='REMOTE_HTTP'&&e.status===status);
 }
});

test('在线评价按动态量规顺序逐域执行并完整合并，不将先前评价传入任务',async()=>{
 const f=fixture();f.rubric.dimensions=f.rubric.dimensions.slice().reverse();const seen=[];let active=0;
 const runner={async execute(task,validate){
  if(task.phase==='synthesis')return emptySynthesis();
  assert.equal(active++,0);seen.push(task.dimension_id);assert.deepEqual(task.configuration.dimensions.map(d=>d.id),[task.dimension_id]);assert.deepEqual(task.bundle,f.bundle);assert.equal(Object.hasOwn(task,'previous_assessments'),false);
  await new Promise(r=>setImmediate(r));active--;const local={...f.assessment,dimensions:f.assessment.dimensions.filter(d=>d.dimension_id===task.dimension_id)};validate(local);return local;
 }};
 const p=await runPortraitWorkflow({...f,runner});assert.deepEqual(seen,f.rubric.dimensions.map(d=>d.id));assert.deepEqual(p.implicit.dimensions.map(d=>d.id),seen);assert.equal(p.implicit.dimensions.flatMap(d=>d.criteria).length,23);
});

test('分域错误即失败，任何漏项、错误域、非法等级或状态都不生成画像',async()=>{
 for(const mutate of [a=>a.dimensions[0].criteria.pop(),a=>{a.dimensions[0].dimension_id='research-collaboration';},a=>{a.dimensions[0].criteria[0].performance_grade='adequate';},a=>{a.dimensions[0].criteria[0].work_status='not_applicable';},a=>{a.student_id='another-student';}]){
  const f=fixture();const seen=[];let provenanceCalls=0;
  const runner={async execute(task){seen.push(task.dimension_id);const a={...f.assessment,dimensions:structuredClone(f.assessment.dimensions.filter(d=>d.dimension_id===task.dimension_id))};mutate(a);return a;},async provenance(){provenanceCalls++;return {};}};
  await assert.rejects(runPortraitWorkflow({...f,runner}));assert.deepEqual(seen,[f.rubric.dimensions[0].id]);assert.equal(provenanceCalls,0);
 }
});

test('原生runner同一隔离会话逐域运行，每域最多修正一次且失败后不继续',async()=>{
 const f=onlineFixture();const tasks=[];let sessions=0;let audits=0;
 const runner=await createInnoAgentRunner({url:'http://localhost',timeoutMs:1000,auditUrl:'http://audit.local'},{fetchImpl:async(url,init)=>{
  if(url.endsWith('/api/skills'))return reply(skillList);
  if(url.endsWith('/content'))return reply({content:url.includes('graduate-implicit-assessment')?implicitSkillBody:skillBody});
  if(url.endsWith('/api/sessions')){sessions++;return reply({id:'one-student-session',workspaceId:'unique'});}
  if(url.endsWith('/api/sessions/one-student-session'))return reply({id:'one-student-session'});
  if(url.includes('/runs/')){audits++;return reply({attempts:[]});}
  assert.equal(new URL(url).pathname,'/api/chat/stream');const body=JSON.parse(init.body);assert.equal(body.sessionId,'one-student-session');const task=JSON.parse(body.prompt.split('\n').at(-1));tasks.push(task);
  const data={...f.assessment,dimensions:structuredClone(f.assessment.dimensions.filter(d=>d.dimension_id===task.dimension_id))};
  if(task.dimension_id===f.rubric.dimensions[1].id)data.dimensions[0].criteria[0].performance_grade='invalid-value';
  return new Response('data: '+JSON.stringify({sessionId:body.sessionId,turnId:'t'+tasks.length,event:{type:'done',fullText:JSON.stringify(data)}})+'\n\n');
 }});
 await assert.rejects(runPortraitWorkflow({...f,runner}),e=>e.code==='STRUCTURED_OUTPUT');assert.equal(sessions,1);assert.equal(audits,0);
 assert.deepEqual(tasks.map(t=>t.dimension_id),[f.rubric.dimensions[0].id,f.rubric.dimensions[1].id,f.rubric.dimensions[1].id]);assert.deepEqual(tasks[1],tasks[2]);
 assert.deepEqual(runner.records,[{phase:'assessment',dimension_id:f.rubric.dimensions[0].id,attempts:1}]);
});

test('分域之间或末域收到取消立即终止，不创建部分画像或继续后续领域',async()=>{
 for(const cancelIndex of [0,6]){
  const f=fixture();const control=new AbortController();const seen=[];let audits=0;
  const runner={async execute(task,validate){seen.push(task.dimension_id);const local={...f.assessment,dimensions:f.assessment.dimensions.filter(d=>d.dimension_id===task.dimension_id)};validate(local);if(seen.length===cancelIndex+1)control.abort();return local;},async provenance(){audits++;return {};}};
  await assert.rejects(runPortraitWorkflow({...f,runner,signal:control.signal}),e=>e.code==='ABORTED');assert.deepEqual(seen,f.rubric.dimensions.slice(0,cancelIndex+1).map(d=>d.id));assert.equal(audits,0);
 }
});


test("原生runner接受纯json代码块包装，拒绝前后文字与数组且不改写非法状态",async()=>{
 const f=onlineFixture();const {prepareDimensionTask}=await import("../../skills/graduate-portrait/scripts/prompts.mjs");const {validateAssessment}=await import("../../skills/graduate-portrait/scripts/validation.mjs");const d=f.rubric.dimensions[0];const task=prepareDimensionTask(f,d.id);const local={...f.assessment,dimensions:[f.assessment.dimensions[0]]};const fence=String.fromCharCode(96).repeat(3);const fenced=fence+"json\n"+JSON.stringify(local)+"\n"+fence;
 const bad=structuredClone(local);bad.dimensions[0].criteria[0].work_status="not_applicable";
 for(const [content,valid] of [[fenced,true],["解释\n"+fenced,false],[fenced+"\n解释",false],[fence+"json\n[]\n"+fence,false],[fence+"json\n"+JSON.stringify(bad)+"\n"+fence,false]]){
  let calls=0;const runner=await createInnoAgentRunner({url:"http://localhost",timeoutMs:1000},{fetchImpl:async url=>{
   if(url.endsWith("/api/skills"))return reply(skillList);if(url.endsWith("/content"))return reply({content:url.includes("graduate-implicit-assessment")?implicitSkillBody:skillBody});if(url.endsWith("/api/sessions"))return reply({id:"s",workspaceId:"unique"});if(url.endsWith("/api/sessions/s"))return reply({id:"s"});
   calls++;return new Response("data: "+JSON.stringify({sessionId:"s",turnId:"t"+calls,event:{type:"done",fullText:content}})+"\n\n");
  }});
  const execute=()=>runner.execute(task,a=>validateAssessment(f.bundle,a,{...f.rubric,dimensions:[d]}));
  if(valid){assert.deepEqual(await execute(),local);assert.equal(calls,1);}else{await assert.rejects(execute(),e=>e.code==="STRUCTURED_OUTPUT");assert.equal(calls,2);assert.deepEqual(runner.records,[]);}
 }
});
