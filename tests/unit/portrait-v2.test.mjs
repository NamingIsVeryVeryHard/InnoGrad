import assert from 'node:assert/strict';
import test from 'node:test';
import {fixture} from '../fixtures/portrait.mjs';
import {buildPortrait,validateAssessment} from '../../.agents/skills/graduate-portrait/scripts/engine.mjs';
import {assessmentSchema} from '../../.agents/skills/graduate-portrait/scripts/schema.mjs';
const criterion=f=>f.assessment.dimensions[1].criteria[0];
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
test('评价提示要求精炼全部观察项而保留必要条件引用和反证',async()=>{
 const {prepareTask}=await import('../../.agents/skills/graduate-portrait/scripts/prompts.mjs');const f=fixture();const task=prepareTask(f,'assessment');const instructions=task.instructions.join('\n');
 assert.match(instructions,/observed.*rationale.*各.*1.?2.*短句/);assert.match(instructions,/limitations.*missing_evidence.*suggestions.*1.?2/);assert.match(instructions,/最少.*完整.*引文/);assert.match(instructions,/缺证据.*长成果清单/);assert.match(instructions,/保留全部.*观察项/);assert.match(instructions,/必要反证.*多条引用/);
 assert.equal(task.configuration.dimensions.flatMap(d=>d.criteria).length,23);assert.deepEqual(task.schema,assessmentSchema(f.rubric));assert.ok(!JSON.stringify(task.schema).includes('maxLength'));
});
test('评价schema直接限定领域与各自观察项清单，漏域漏项及跨域项在结构层拒绝',async()=>{
 const {validateShape}=await import('../../.agents/skills/graduate-portrait/scripts/validation.mjs');const f=fixture();const schema=assessmentSchema(f.rubric);assert.equal(schema.properties.dimensions.minItems,f.rubric.dimensions.length);assert.equal(schema.properties.dimensions.maxItems,f.rubric.dimensions.length);
 for(const mutate of [a=>{a.dimensions.pop();},a=>{a.dimensions[0].criteria.pop();},a=>{a.dimensions[0].criteria[0].criterion_id=a.dimensions[1].criteria[0].criterion_id;},a=>{a.dimensions[0]=structuredClone(a.dimensions[1]);}]){const a=structuredClone(f.assessment);mutate(a);assert.throws(()=>validateShape(schema,a,'assessment'));}
 assert.doesNotThrow(()=>validateShape(schema,f.assessment,'assessment'));
});
test('任务输出动态完整清单，改量规后的数量与ID同步并要求结束前自查',async()=>{
 const {prepareTask}=await import('../../.agents/skills/graduate-portrait/scripts/prompts.mjs');const f=fixture();f.rubric.dimensions=f.rubric.dimensions.slice(0,2);f.rubric.dimensions[0].criteria=f.rubric.dimensions[0].criteria.slice(0,1);const task=prepareTask(f,'assessment');
 assert.deepEqual(task.expected_dimension_ids,f.rubric.dimensions.map(d=>d.id));assert.deepEqual(task.expected_criterion_ids,Object.fromEntries(f.rubric.dimensions.map(d=>[d.id,d.criteria.map(c=>c.id)])));assert.match(task.instructions.join('\n'),/结束前.*expected_dimension_ids.*expected_criterion_ids.*自查/);assert.equal(task.schema.properties.dimensions.minItems,2);assert.equal(task.schema.properties.dimensions.items.oneOf[0].properties.criteria.minItems,1);
});
