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
