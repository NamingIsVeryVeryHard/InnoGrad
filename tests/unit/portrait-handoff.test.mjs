import assert from 'node:assert/strict';
import test from 'node:test';
import {fixture} from '../fixtures/portrait.mjs';
import * as engine from '../../skills/graduate-portrait/scripts/engine.mjs';
import * as handoff from '../../skills/graduate-portrait/scripts/handoff.mjs';
const metadata={output_version:'A-trial.1',generated_at:'2026-10-14T04:00:00.000Z',producer:{mode:'offline_replay',name:'synthetic A fixture',model:null}};
test('B无A时显性部分待接入，外部A合并不改写抽取和固定结果',()=>{
 const f=fixture();const a=handoff.buildAResult({...f,metadata});const before=structuredClone(a);
 const p=engine.buildPortrait({...f,extraction:undefined,aResult:a});assert.equal(p.explicit_status,'merged');assert.deepEqual(p.explicit,a.explicit);assert.deepEqual(p.explicit_extraction,a.extraction);assert.deepEqual(a,before);
 const b=engine.buildPortrait({...f,extraction:undefined});assert.equal(b.explicit,null);assert.equal(b.explicit_extraction,null);assert.equal(b.explicit_status,'pending');assert.ok(b.warnings.includes('explicit_pending'));
});
test('A材料文本、原文件哈希、任务范围或版本不匹配拒绝整合',()=>{
 for(const mutate of [a=>{a.student_id='other';},a=>{a.task_id='other';},a=>{a.rules_version='other';},a=>{a.material_fingerprints[0].sha256='b'.repeat(64);},a=>{a.material_fingerprints[0].content_sha256='b'.repeat(64);},a=>{a.schema_version='other';}]){const f=fixture();const a=handoff.buildAResult({...f,metadata});mutate(a);assert.throws(()=>handoff.validateAResult(f.bundle,a,f.rules));}
});
test('A所有引用必须回到同范围bundle；不重算规则结果',()=>{
 const f=fixture();const a=handoff.buildAResult({...f,metadata});a.explicit.checks[0].status='consistent';assert.doesNotThrow(()=>handoff.validateAResult(f.bundle,a,f.rules));assert.equal(engine.buildPortrait({...f,extraction:undefined,aResult:a}).explicit.checks[0].status,'consistent');
 a.explicit.checks[0].input_evidence[0].quote='伪造';assert.throws(()=>handoff.validateAResult(f.bundle,a,f.rules));
});
test('A不能用空检查或不可能的规则状态声称完成整合',()=>{
 const f=fixture();const a=handoff.buildAResult({...f,metadata});a.explicit.checks=[];assert.throws(()=>handoff.validateAResult(f.bundle,a,f.rules));
 const b=handoff.buildAResult({...f,metadata});b.explicit.checks.find(c=>c.kind==='minimum').status='consistent';assert.throws(()=>handoff.validateAResult(f.bundle,b,f.rules));
});
test('A同版本规则的阈值、适用阶段和指标集合必须一致',()=>{
 const f=fixture();for(const mutate of [a=>{a.explicit.checks.find(c=>c.kind==='minimum').threshold=100;},a=>{a.explicit.checks[0].status='not_applicable';},a=>{delete a.explicit.metrics.credits_earned;}]){const a=handoff.buildAResult({...f,metadata});mutate(a);assert.throws(()=>handoff.validateAResult(f.bundle,a,f.rules));}
});
test('材料指纹不依赖对象字段顺序，文本与页段改变仍会变化',()=>{
 const f=fixture();const before=handoff.materialFingerprints(f.bundle);f.bundle.documents[0].segments[0]={text:f.bundle.documents[0].segments[0].text,page:null,segment_id:'body'};assert.deepEqual(handoff.materialFingerprints(f.bundle),before);f.bundle.documents[0].segments[0].page=2;assert.notDeepEqual(handoff.materialFingerprints(f.bundle),before);
});
test('A规则输入引用须来自实际交接抽取且计算字段不能缺少',()=>{
 const f=fixture();const a=handoff.buildAResult({...f,metadata});a.explicit.checks[0].input_evidence[0]={document_id:'annual-1',segment_id:'body',quote:'研究问题是在小样本课堂数据中提高反馈准确性。'};assert.throws(()=>handoff.validateAResult(f.bundle,a,f.rules));
 const b=handoff.buildAResult({...f,metadata});b.explicit.checks[0].status='consistent';delete b.explicit.checks[0].self_report;assert.throws(()=>handoff.validateAResult(f.bundle,b,f.rules));
});
test('A每类成果状态映射必须完整，单状态缺失或空映射不能整合',()=>{
 const f=fixture();for(const mutate of [a=>{delete a.explicit.ledger.paper.published;},a=>{delete a.explicit.ledger_details.paper.counts.published;},a=>{a.explicit.ledger.paper={};a.explicit.ledger_details.paper.counts={};},a=>{a.explicit.ledger.paper.unrecognized=null;},a=>{a.explicit.ledger_details.paper.counts.unrecognized=structuredClone(a.explicit.ledger_details.paper.counts.unknown);}]){const a=handoff.buildAResult({...f,metadata});mutate(a);assert.throws(()=>handoff.validateAResult(f.bundle,a,f.rules),/states mismatch/);assert.throws(()=>engine.buildPortrait({...f,extraction:undefined,aResult:a}),/states mismatch/);}
 const a=handoff.buildAResult({...f,metadata});assert.equal(a.explicit.ledger.practice.completed,null);assert.doesNotThrow(()=>handoff.validateAResult(f.bundle,a,f.rules));
});
