import assert from 'node:assert/strict';
import test from 'node:test';
import {fixture} from '../fixtures/portrait.mjs';
import * as engine from '../../.agents/skills/graduate-portrait/scripts/engine.mjs';
import * as handoff from '../../.agents/skills/graduate-portrait/scripts/handoff.mjs';
const metadata={output_version:'A-trial.1',generated_at:'2026-10-14T04:00:00.000Z',producer:{mode:'offline_replay',name:'synthetic A fixture',model:null}};
test('B无A时显性部分待接入，外部A合并不改写抽取和固定结果',()=>{
 const f=fixture();const a=handoff.buildAResult({...f,metadata});const before=structuredClone(a);
 const p=engine.buildPortrait({...f,extraction:undefined,aResult:a});assert.equal(p.explicit_status,'merged');assert.deepEqual(p.explicit,a.explicit);assert.deepEqual(a,before);
 const b=engine.buildPortrait({...f,extraction:undefined});assert.equal(b.explicit,null);assert.equal(b.explicit_status,'pending');assert.ok(b.warnings.includes('explicit_pending'));
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
