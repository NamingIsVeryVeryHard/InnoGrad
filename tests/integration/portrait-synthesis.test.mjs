import test from 'node:test';
import assert from 'node:assert/strict';
import {fixture} from '../fixtures/portrait.mjs';
import {buildPortrait,buildAResult,validateAssessment} from '../../skills/graduate-portrait/scripts/engine.mjs';
import {prepareSynthesisTask,validateSynthesis} from '../../skills/graduate-portrait/scripts/synthesis.mjs';
import {runPortraitWorkflow} from '../../skills/graduate-portrait/scripts/workflow.mjs';
const empty=()=>({current_work:[],demonstrated:[],attention:[],next_steps:[]});

test('整合概览引用已有评价，显性与全部隐性结果保持不变',async()=>{
 const f=fixture();const aResult=buildAResult({...f,metadata:{output_version:'synthetic-explicit.1',generated_at:'2026-10-14T04:00:00Z',producer:{mode:'synthetic',name:null,model:null}}});
 const baseline=buildPortrait({...f,aResult,extraction:undefined});const calls=[];
 const portrait=await runPortraitWorkflow({...f,aResult,runner:{async execute(task,validate){calls.push(task.phase);const data=task.phase==='synthesis'?{...empty(),attention:[{text:'现有材料还不足以评价该观察项，建议补充对应任务记录。',source_refs:[task.source_records.find(r=>r.kind==='implicit'&&r.content.evidence_state==='insufficient').id]}]}:{...f.assessment,dimensions:f.assessment.dimensions.filter(d=>d.dimension_id===task.dimension_id)};validate(data);return data;}}});
 assert.equal(calls.at(-1),'synthesis');assert.deepEqual(portrait.explicit,aResult.explicit);assert.deepEqual(portrait.implicit,baseline.implicit);assert.equal(portrait.synthesis.attention.length,1);assert.equal(portrait.review_status,'draft');
 const reference=portrait.synthesis_sources.find(r=>r.id===portrait.synthesis.attention[0].source_refs[0]);
 const source=reference.pointer.slice(1).split('/').reduce((value,key)=>value[key.replaceAll('~1','/').replaceAll('~0','~')],portrait);
 assert.equal(source.evidence_state,'insufficient');
 assert.deepEqual(source,baseline.implicit.dimensions.flatMap(d=>d.criteria).find(c=>c.criterion_id===source.criterion_id));
});

test('拒绝不存在的画像引用和将未评价项用作正面能力结论',()=>{
 const f=fixture();const p=buildPortrait(f);const task=prepareSynthesisTask(p);const missing=task.source_records.find(r=>r.kind==='implicit'&&r.content.evidence_state==='insufficient');
 assert.throws(()=>validateSynthesis(p,{...empty(),current_work:[{text:'无来源的内容',source_refs:['R9999']}]}));
 assert.throws(()=>validateSynthesis(p,{...empty(),demonstrated:[{text:'证据不足却声称表现充分',source_refs:[missing.id]}]}));
 assert.doesNotThrow(()=>validateSynthesis(p,{...empty(),attention:[{text:'该项材料需要补充。',source_refs:[missing.id]}]}));
});

test('整合阶段失败不返回假成功画像',async()=>{
 const f=fixture();await assert.rejects(runPortraitWorkflow({...f,runner:{async execute(task){return task.phase==='synthesis'?{...empty(),next_steps:[{text:'补充材料',source_refs:['R9999'],completion_evidence:'材料'}]}:{...f.assessment,dimensions:f.assessment.dimensions.filter(d=>d.dimension_id===task.dimension_id)};}}}));
});

test('整条工作流使用入口时的快照，调用方中途改动不污染后续阶段',async()=>{
 const f=fixture();
 f.bundle.input_context={snapshot_id:'entry-snapshot',statistics_cutoff_at:null,trigger:'manual',
  sources:f.bundle.documents.map(d=>({document_id:d.document_id,source_version:'v1',
   authorization:'authorized',validity:'active',review_status:'pending'}))};
 let calls=0;
 const portrait=await runPortraitWorkflow({...f,runner:{async execute(task,validate){
  if(calls++===0){
   f.bundle.input_context.snapshot_id='changed-during-run';
   f.bundle.input_context.sources[0].validity='withdrawn';
  }
  const context=task.phase==='synthesis'?task.context.input_context:task.bundle.input_context;
  assert.equal(context.snapshot_id,'entry-snapshot');
  assert.equal(context.sources[0].validity,'active');
  const data=task.phase==='synthesis'?empty():{...f.assessment,dimensions:f.assessment.dimensions.filter(d=>d.dimension_id===task.dimension_id)};
  validate(data);return data;
 }}});
 assert.equal(portrait.input_context.snapshot_id,'entry-snapshot');
 assert.equal(portrait.review_status,'draft');
});

test('必要条件缺失、重复或无对应证据时不能保留达到要求',()=>{
 const f=fixture();const c=f.assessment.dimensions.flatMap(d=>d.criteria).find(c=>c.criterion_id==='problem-definition');
 const definition=f.rubric.dimensions.flatMap(d=>d.criteria).find(item=>item.id==='problem-definition');
 c.condition_checks=definition.required_conditions.map((_,i)=>({condition_index:i,status:'supported',evidence_indices:[0],reason:'原文陈述了该条件。'}));
 assert.doesNotThrow(()=>validateAssessment(f.bundle,f.assessment,f.rubric));
 c.condition_checks[0].status='unobserved';c.condition_checks[0].evidence_indices=[];
 assert.throws(()=>validateAssessment(f.bundle,f.assessment,f.rubric),e=>e.validation_issues?.[0].category==='CONDITION_GRADE_CONFLICT');
 c.performance_grade=null;c.evidence_state='insufficient';c.missing_evidence=['研究对象尚不明确'];
 assert.doesNotThrow(()=>validateAssessment(f.bundle,f.assessment,f.rubric));
 c.condition_checks[1].evidence_indices=[999];
 assert.throws(()=>validateAssessment(f.bundle,f.assessment,f.rubric),e=>e.validation_issues?.[0].category==='CONDITION_EVIDENCE');
 c.condition_checks[1].evidence_indices=[0];c.condition_checks[1].condition_index=0;
 assert.throws(()=>validateAssessment(f.bundle,f.assessment,f.rubric),e=>e.validation_issues?.[0].category==='CONDITION_COVERAGE');
});
