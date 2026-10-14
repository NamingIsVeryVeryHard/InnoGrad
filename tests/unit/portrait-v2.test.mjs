import assert from 'node:assert/strict';
import test from 'node:test';
import {fixture} from '../fixtures/portrait.mjs';
import {buildPortrait,validateAssessment} from '../../skills/graduate-portrait/scripts/engine.mjs';
import {assessmentSchema} from '../../skills/graduate-portrait/scripts/schema.mjs';
const criterion=f=>f.assessment.dimensions[1].criteria[0];
test('评价任务保留已校验A事实和出处，但不向模型提供显性规则结果',async()=>{
 const {prepareTask,prepareDimensionTask}=await import('../../skills/graduate-portrait/scripts/prompts.mjs');
 const {buildAResult}=await import('../../skills/graduate-portrait/scripts/handoff.mjs');
 const f=fixture();f.bundle.task_context={task_id:'synthetic-task',observation_period:f.bundle.period,training_category:null,training_year:null,support_conditions:null};
 const aResult=buildAResult({...f,metadata:{output_version:'synthetic-a-context.1',generated_at:'2026-10-14T04:00:00Z',producer:{mode:'synthetic',name:'synthetic A context',model:null}}});
 const before=structuredClone(aResult);
 for(const task of [prepareTask({...f,aResult},'assessment'),prepareDimensionTask({...f,aResult},f.rubric.dimensions[0].id)]){
  assert.deepEqual(task.explicit_context.extraction,aResult.extraction);
  assert.equal(task.explicit_context.task_id,f.bundle.task_context.task_id);
  assert.equal(task.explicit_context.rules_version,aResult.rules_version);
  assert.deepEqual(task.explicit_context.material_fingerprints,aResult.material_fingerprints);
  assert.equal(Object.hasOwn(task.explicit_context,'explicit'),false);
  assert.equal(Object.hasOwn(task,'aResult'),false);
  assert.deepEqual(task.bundle,f.bundle);
  task.explicit_context.extraction.facts.length=0;
 }
 assert.deepEqual(aResult,before);
 assert.equal(Object.hasOwn(prepareTask(f,'assessment'),'explicit_context'),false);
 assert.equal(Object.hasOwn(prepareTask({...f,aResult},'extraction'),'explicit_context'),false);
 const invalid=structuredClone(aResult);invalid.student_id='other';
 assert.throws(()=>prepareTask({...f,aResult:invalid},'assessment'));
});
test('默认七领域按观察项评级且不输出领域等级或隐性总分',()=>{
 const f=fixture();assert.equal(f.rubric.schema_version,'2.0');assert.equal(f.rubric.dimensions.length,7);
 const p=buildPortrait(f);assert.equal(p.schema_version,'2.0');assert.equal(p.implicit.dimensions.length,7);
 for(const d of p.implicit.dimensions){assert.ok(!Object.hasOwn(d,'level'));for(const s of d.summary)assert.ok(s.criterion_ids.every(id=>d.criteria.some(c=>c.criterion_id===id)));}
 assert.ok(!Object.hasOwn(p.implicit,'overall_score'));
});
test('证据不足与冲突均暂缓等级，不能将缺失评为待改进',()=>{
 for(const state of ['insufficient','conflicting']){const f=fixture();const c=criterion(f);c.evidence_state=state;c.performance_grade='needs_improvement';assert.throws(()=>validateAssessment(f.bundle,f.assessment,f.rubric));}
});
test('未提到协作不能判不适用；模型不能确认教师复核',()=>{
 const f=fixture();const c=f.assessment.dimensions.at(-1).criteria[0];c.evidence_state='not_applicable';assert.throws(()=>validateAssessment(f.bundle,f.assessment,f.rubric));
 c.evidence_state='insufficient';c.review_status='confirmed';assert.throws(()=>validateAssessment(f.bundle,f.assessment,f.rubric));
});
test('引用从bundle补齐文件哈希物理页，保留多条支持说明及未知贡献',()=>{
 const f=fixture();f.bundle.documents[0].segments[0].page=2;const p=buildPortrait(f);const c=p.implicit.dimensions[1].criteria[0];assert.equal(c.evidence[0].source_name,f.bundle.documents[0].source_name);assert.equal(c.evidence[0].sha256,f.bundle.documents[0].sha256);assert.equal(c.evidence[0].page,2);assert.equal(c.contribution.individual,null);assert.equal(c.review.status,'pending');
});
test('任务标准未知时保留可观察事实，暂不评级；模型不能绕过培养背景条件',()=>{
 const f=fixture();const c=criterion(f);const def=f.rubric.dimensions[1].criteria[0];def.required_context=['training_category'];c.standard_status='applicable';assert.throws(()=>validateAssessment(f.bundle,f.assessment,f.rubric));c.standard_status='pending_confirmation';c.performance_grade=null;assert.doesNotThrow(()=>validateAssessment(f.bundle,f.assessment,f.rubric));
});
test('旧评价版本与累计等级量规明确拒绝而非改名转换',()=>{
 const f=fixture();f.assessment.schema_version='1.0';assert.throws(()=>validateAssessment(f.bundle,f.assessment,f.rubric));assert.equal(assessmentSchema(f.rubric).properties.schema_version.const,'2.0');
});
test('冲突不能重复同条引用凑数量；可评价证据性质不能unknown',()=>{
 const f=fixture();const c=criterion(f);c.evidence_state='conflicting';c.performance_grade=null;c.evidence.push(structuredClone(c.evidence[0]));assert.throws(()=>validateAssessment(f.bundle,f.assessment,f.rubric));
 c.evidence_state='evaluable';c.performance_grade='meets_requirements';c.evidence_nature='unknown';assert.throws(()=>validateAssessment(f.bundle,f.assessment,f.rubric));
});
test('多条引用分别保留支持说明，未知页码和贡献不补造',()=>{
 const f=fixture();const c=criterion(f);c.evidence.push({...c.evidence[0],quote:'小样本课堂数据',supports:'仅支持研究情境，与首条不是独立佐证。'});const p=buildPortrait(f);const actual=p.implicit.dimensions[1].criteria[0];assert.equal(actual.evidence.length,2);assert.equal(actual.evidence[1].supports,c.evidence[1].supports);assert.equal(actual.evidence[1].page,null);assert.deepEqual(actual.contribution,{individual:null,guidance:null,tools:null});
});
test('负结果可以支持检查表现；完成自述保持未独立核验',()=>{
 const f=fixture();f.bundle.documents[0].segments[0].text+=' 同一留出集调整后准确率未提高；比较前后样本一致，报告区间重叠，因此尚不能确认有效。';
 const c=f.assessment.dimensions[4].criteria.find(x=>x.criterion_id==='effect-check');Object.assign(c,{evidence_state:'evaluable',performance_grade:'well_demonstrated',work_status:'completed',evidence_nature:'self_report',observed:'自述以同一留出集比较前后效果，尚不能确认有效。',rationale:'提供了比较条件和区间限制，负结果本身不降级。',evidence:[{document_id:'annual-1',segment_id:'body',quote:'同一留出集调整后准确率未提高；比较前后样本一致，报告区间重叠，因此尚不能确认有效。',supports:'支持检查设计、结果解释和限制。'}],missing_evidence:[]});
 const p=buildPortrait(f);const actual=p.implicit.dimensions[4].criteria.find(x=>x.criterion_id==='effect-check');assert.equal(actual.performance_grade,'well_demonstrated');assert.equal(actual.review.independent_corroboration,'unverified');assert.match(f.rubric.dimensions[4].criteria.find(x=>x.id==='effect-check').standards.needs_improvement,/目标未达或负结果本身不降级/);
});
test('年级专属标准只在明确上下文下适用，通用开题标准可以使用',()=>{
 const f=fixture();const c=criterion(f);f.rubric.dimensions[1].criteria[0].required_context=['training_year'];c.standard_status='pending_confirmation';c.performance_grade=null;assert.doesNotThrow(()=>validateAssessment(f.bundle,f.assessment,f.rubric));
 f.bundle.task_context={task_id:'T1',observation_period:null,training_category:null,training_year:2,support_conditions:null};c.standard_status='applicable';c.performance_grade='meets_requirements';assert.doesNotThrow(()=>validateAssessment(f.bundle,f.assessment,f.rubric));
});
test('评价schema直接限定领域与各自观察项清单，漏域漏项及跨域项在结构层拒绝',async()=>{
 const {validateShape}=await import('../../skills/graduate-portrait/scripts/validation.mjs');const f=fixture();const schema=assessmentSchema(f.rubric);assert.equal(schema.properties.dimensions.minItems,f.rubric.dimensions.length);assert.equal(schema.properties.dimensions.maxItems,f.rubric.dimensions.length);
 for(const mutate of [a=>{a.dimensions.pop();},a=>{a.dimensions[0].criteria.pop();},a=>{a.dimensions[0].criteria[0].criterion_id=a.dimensions[1].criteria[0].criterion_id;},a=>{a.dimensions[0]=structuredClone(a.dimensions[1]);}]){const a=structuredClone(f.assessment);mutate(a);assert.throws(()=>validateShape(schema,a,'assessment'));}
 assert.doesNotThrow(()=>validateShape(schema,f.assessment,'assessment'));
});
test('任务输出动态完整清单，改量规后的数量与ID同步并要求结束前自查',async()=>{
 const {prepareTask}=await import('../../skills/graduate-portrait/scripts/prompts.mjs');const f=fixture();f.rubric.dimensions=f.rubric.dimensions.slice(0,2);f.rubric.dimensions[0].criteria=f.rubric.dimensions[0].criteria.slice(0,1);const task=prepareTask(f,'assessment');
 assert.deepEqual(task.expected_dimension_ids,f.rubric.dimensions.map(d=>d.id));assert.deepEqual(task.expected_criterion_ids,Object.fromEntries(f.rubric.dimensions.map(d=>[d.id,d.criteria.map(c=>c.id)])));assert.equal(task.schema.properties.dimensions.minItems,2);assert.equal(task.schema.properties.dimensions.items.oneOf[0].properties.criteria.minItems,1);
});

test('分域任务仅含当前动态领域配置与schema，但保留完整原文和身份范围',async()=>{
 const {prepareDimensionTask,prepareTask}=await import('../../skills/graduate-portrait/scripts/prompts.mjs');const {validateShape}=await import('../../skills/graduate-portrait/scripts/validation.mjs');const f=fixture();
 for(const d of f.rubric.dimensions){
  const task=prepareDimensionTask(f,d.id);assert.equal(task.phase,'assessment');assert.equal(task.dimension_id,d.id);assert.deepEqual(task.bundle,f.bundle);assert.deepEqual(task.configuration,{...f.rubric,dimensions:[d]});
  assert.deepEqual(task.expected_dimension_ids,[d.id]);assert.deepEqual(task.expected_criterion_ids,{[d.id]:d.criteria.map(c=>c.id)});assert.deepEqual(Object.keys(task.criterion_standard_status),d.criteria.map(c=>c.id));
  assert.equal(task.schema.properties.dimensions.minItems,1);assert.equal(task.schema.properties.dimensions.maxItems,1);assert.equal(task.schema.properties.dimensions.items.oneOf[0].properties.dimension_id.const,d.id);
  const local={...f.assessment,dimensions:structuredClone(f.assessment.dimensions.filter(x=>x.dimension_id===d.id))};
  for(const c of local.dimensions[0].criteria)c.condition_checks=d.criteria.find(x=>x.id===c.criterion_id).required_conditions.map((_,i)=>({condition_index:i,status:'unobserved',evidence_indices:[],reason:'仅验证领域结构。'}));
  assert.doesNotThrow(()=>validateShape(task.schema,local,'assessment'));assert.throws(()=>validateShape(task.schema,f.assessment,'assessment'));
 }
 assert.throws(()=>prepareDimensionTask(f,'unknown-domain'));assert.equal(prepareTask(f,'assessment').schema.properties.dimensions.minItems,f.rubric.dimensions.length);
});

test('可评价工作状态不符合当前观察项时给精确类别，计划可保留为证据不足',async()=>{
 const {repairFeedback}=await import('../../skills/graduate-portrait/scripts/validation.mjs');
 for(const status of ['planned','in_progress','unknown']){
  const f=fixture();f.bundle.documents[0].segments[0].text+=' 计划与同伴共同处理样本不平衡问题，尚未执行。';const c=f.assessment.dimensions.at(-1).criteria.at(-1);
  Object.assign(c,{evidence_state:'evaluable',performance_grade:'meets_requirements',work_status:status,evidence_nature:'self_report',evidence:[{document_id:'annual-1',segment_id:'body',quote:'计划与同伴共同处理样本不平衡问题，尚未执行。',supports:'仅支持计划记录。'}]});
  assert.deepEqual(f.rubric.dimensions.at(-1).criteria.at(-1).allowed_work_statuses,['completed']);let error;try{validateAssessment(f.bundle,f.assessment,f.rubric);}catch(e){error=e;}
  assert.deepEqual(error?.validation_issues,[{path:'/dimensions/6/criteria/2/work_status',category:'WORK_STATUS_NOT_ALLOWED'}]);const feedback=repairFeedback(error);assert.match(feedback,/criterion.allowed_work_statuses/);assert.match(feedback,/不能.*planned.*completed/);assert.match(feedback,/只有计划.*已执行.*insufficient.*null/);assert.match(feedback,/unknown.*捏造.*已执行/);assert.match(feedback,/原文依据确足.*真实状态/);assert.match(feedback,/状态未知.*insufficient.*null/);assert.match(feedback,/保留真实work_status/);assert.ok(!feedback.includes(c.evidence[0].quote));
  c.evidence_state='insufficient';c.performance_grade=null;c.missing_evidence=['缺少共同处理问题的实际过程。'];assert.doesNotThrow(()=>validateAssessment(f.bundle,f.assessment,f.rubric));assert.equal(c.work_status,status);
 }
});

test('可评价证据性质unknown给明确类别而不伪造观察性质',async()=>{
 const f=fixture();const c=criterion(f);c.evidence_nature='unknown';let error;try{validateAssessment(f.bundle,f.assessment,f.rubric);}catch(e){error=e;}
 assert.deepEqual(error?.validation_issues,[{path:'/dimensions/1/criteria/0/evidence_nature',category:'EVIDENCE_NATURE_REQUIRED'}]);
});
