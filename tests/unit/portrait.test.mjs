import assert from 'node:assert/strict';
import test from 'node:test';
import { buildPortrait, validateExtraction, validateAssessment } from '../../.agents/skills/graduate-portrait/scripts/engine.mjs';
import { fixture } from '../fixtures/portrait.mjs';

test('缺失值不补零；自报数量与逐项成果矛盾时留待复核', () => {
  const f = fixture();
  const result = buildPortrait(f);
  assert.equal(result.explicit.metrics.credits_earned.value, null);
  assert.equal(result.explicit.metrics.papers_reported.value, 3);
  assert.equal(result.explicit.ledger.paper.published, 2);
  assert.equal(result.explicit.checks.find(x => x.id === 'papers-consistency').status, 'needs_review');
  assert.equal(result.explicit.overall_score, null);
  assert.equal(result.review_status, 'draft');
});

test('重复成果只计一次；在审、录用、发表和计划分开', () => {
  const f = fixture();
  f.extraction.items.push({ ...f.extraction.items[0], item_id: 'copy' });
  const inReview = { ...f.extraction.items[0], item_id: 'review', title: 'C 方法', status: 'under_review' };
  f.extraction.items.push(inReview);
  const r = buildPortrait(f);
  assert.equal(r.explicit.ledger.paper.published, 2);
  assert.equal(r.explicit.ledger.paper.under_review, 1);
});

test('引用不存在、学生不同或期间不同，均拒绝生成画像', () => {
  for (const mutate of [
    f => { f.extraction.facts[0].evidence[0].quote = '原文没有这句话'; },
    f => { f.extraction.student_id = 'other'; },
    f => { f.bundle.documents[0].period = '2023-2024'; },
  ]) {
    const f = fixture(); mutate(f);
    assert.throws(() => buildPortrait(f));
  }
});

test('不接受自动类型转换、额外字段或无依据的数字', () => {
  const f = fixture();
  f.extraction.facts[0].value = '3';
  assert.throws(() => validateExtraction(f.bundle, f.extraction, f.rules));
  f.extraction.facts[0].value = 100;
  assert.throws(() => validateExtraction(f.bundle, f.extraction, f.rules));
  f.extraction.facts[0].value = 3;
  f.extraction.score = 90;
  assert.throws(() => validateExtraction(f.bundle, f.extraction, f.rules));
});

test('计划不能支持已完成的检验；无证据不评为低能力', () => {
  const f = fixture();
  const criterion = f.assessment.dimensions.find(d => d.dimension_id === 'evidence-reasoning').criteria[0];
  criterion.judgment = 'supported';
  criterion.work_status = 'planned';
  criterion.evidence = f.extraction.facts[0].evidence;
  assert.throws(() => validateAssessment(f.bundle, f.assessment, f.rubric));
  criterion.judgment = 'not_observed';
  criterion.work_status = 'unknown';
  criterion.evidence = [];
  const dimension = buildPortrait(f).implicit.dimensions.find(d => d.id === 'evidence-reasoning');
  assert.equal(dimension.level, null);
  assert.equal(dimension.status, 'insufficient_evidence');
});

test('固定阈值按规则计算，缺失阈值不推测达标', () => {
  const f = fixture();
  f.rules.checks.push({ id: 'paper-min', label: '测试规则', kind: 'minimum', metric: 'paper.published', threshold: 2, source: '合成测试规则', applicable_stages: ['annual'] });
  let result = buildPortrait(f);
  assert.equal(result.explicit.checks.at(-1).status, 'met');
  f.rules.checks.at(-1).threshold = 3;
  result = buildPortrait(f);
  assert.equal(result.explicit.checks.at(-1).status, 'not_met');
  f.rules.checks.at(-1).threshold = null;
  assert.equal(buildPortrait(f).explicit.checks.at(-1).status, 'pending_rule');
});

test('配置变化反映在等级及可复现标识中', () => {
  const f = fixture();
  const r = buildPortrait(f);
  assert.deepEqual(buildPortrait(f), r);
  f.rubric.dimensions[0].label = '研究问题界定';
  assert.notEqual(buildPortrait(f).run_id, r.run_id);
  assert.equal(buildPortrait(f).implicit.dimensions[0].label, '研究问题界定');
});

test('数字token不能从100截出10，模糊量词必须保留', () => {
  const f=fixture(); const s=f.bundle.documents[0].segments[0]; s.text+=' 阅读100篇与120余篇文献。';
  f.extraction.facts=[{field:'literature_read_reported',value:10,qualifier:'exact',numeric_token:'10',evidence:[{document_id:'annual-1',segment_id:'body',quote:'阅读100篇'}]}];
  assert.throws(()=>validateExtraction(f.bundle,f.extraction,f.rules));
  Object.assign(f.extraction.facts[0],{value:120,numeric_token:'120',evidence:[{document_id:'annual-1',segment_id:'body',quote:'120余篇文献'}]});
  assert.throws(()=>validateExtraction(f.bundle,f.extraction,f.rules));
  f.extraction.facts[0].qualifier='lower_bound'; assert.doesNotThrow(()=>validateExtraction(f.bundle,f.extraction,f.rules));
});

test('冲突值保留，未完整列明的空类别不当学生实际零', () => {
  const f=fixture(); f.bundle.documents[0].segments[0].text+=' 另一处记载发表论文4篇。';
  f.extraction.facts.push({...f.extraction.facts[0],value:4,numeric_token:'4',evidence:[{document_id:'annual-1',segment_id:'body',quote:'另一处记载发表论文4篇。'}]});
  const r=buildPortrait(f); assert.equal(r.explicit.metrics.papers_reported.value,null);
  assert.equal(r.explicit.metrics.papers_reported.status,'conflict'); assert.equal(r.explicit.ledger.practice.completed,null);
});

test('跨期和不确定期间成果不计本期，输入保持不变', () => {
  const f=fixture(); f.extraction.items[0].period_status='uncertain'; f.extraction.items[1].period_status='out_of_scope';
  const before=structuredClone(f); const r=buildPortrait(f); assert.equal(r.explicit.ledger_details.paper.counts.published.listed,0); assert.equal(r.explicit.ledger.paper.published,null); assert.deepEqual(f,before);
});

test('重复成果状态冲突不会选取最好状态', () => {
  const f=fixture(); f.extraction.items.push({...f.extraction.items[0],item_id:'conflict',status:'accepted'});
  const r=buildPortrait(f); assert.equal(r.explicit.ledger.paper.published,null); assert.ok(r.explicit.item_conflicts.length);
});

test('开题计划不能伪称完成结果且不接受模型分数', () => {
  const f=fixture(); f.bundle.documents[0].kind='proposal';
  const c=f.assessment.dimensions[2].criteria[0]; Object.assign(c,{judgment:'supported',work_status:'completed',evidence:f.extraction.facts[0].evidence});
  assert.throws(()=>validateAssessment(f.bundle,f.assessment,f.rubric));
  c.judgment='not_observed'; c.work_status='unknown'; c.evidence=[]; f.assessment.official_decision='通过';
  assert.throws(()=>validateAssessment(f.bundle,f.assessment,f.rubric));
});

test('开题期次未知时允许null且禁止本期计数，年报不允许未知期次', () => {
  const f=fixture(); f.bundle.period=null; f.bundle.stage='proposal';f.bundle.documents[0].period=null;f.bundle.documents[0].kind='proposal';
  f.extraction.period=null;f.extraction.stage='proposal';f.assessment.period=null;f.assessment.stage='proposal';
  assert.throws(()=>buildPortrait(f)); f.extraction.items.forEach(i=>i.period_status='uncertain');
  const r=buildPortrait(f);assert.equal(r.period,null);assert.ok(r.warnings.includes('period_unconfirmed'));assert.equal(r.explicit.ledger.paper.published,null);
  f.bundle.stage='annual';assert.throws(()=>buildPortrait(f));
});

test('近似数字不自动达标；缺来源阈值待配，学分材料核对独立',()=>{
 const f=fixture(); f.bundle.documents[0].segments[0].text+=' 已修学分32，要求学分30。';
 for(const [field,value]of [['credits_earned',32],['credits_required',30]]) f.extraction.facts.push({field,value,qualifier:'exact',numeric_token:String(value),evidence:[{document_id:'annual-1',segment_id:'body',quote:'已修学分32，要求学分30。'}]});
 let r=buildPortrait(f);assert.equal(r.explicit.checks.find(c=>c.id==='credit-material-comparison').status,'met');assert.equal(r.explicit.checks.find(c=>c.id==='credit-requirement').status,'pending_rule');
 f.rules.checks.push({id:'no-source',label:'未配来源',kind:'minimum',metric:'credits_earned',threshold:20,source:null,applicable_stages:['annual']}); assert.equal(buildPortrait(f).explicit.checks.at(-1).status,'pending_rule');
 f.rules.checks.at(-1).source='合成测试制度';f.extraction.facts.find(x=>x.field==='credits_earned').qualifier='approximate'; assert.equal(buildPortrait(f).explicit.checks.at(-1).status,'insufficient_evidence');
});
test('维度名称与顺序可改，等级锚点变更确定性生效',()=>{
 const f=fixture(); f.rubric.dimensions.reverse();f.assessment.dimensions.reverse();f.rubric.dimensions.push({id:'custom',label:'自定义材料维度',criteria:[{id:'custom-observation',description:'自定义观察',allowed_work_statuses:['planned']}],levels:[{value:1,label:'自定义锚点',requires:['custom-observation']}]});
 f.assessment.dimensions.push({dimension_id:'custom',criteria:[{criterion_id:'custom-observation',judgment:'not_observed',work_status:'unknown',rationale:'材料未包含此条件。',evidence:[],missing_evidence:'缺少自定义观察。'}]});const r=buildPortrait(f);assert.equal(r.implicit.dimensions.at(-1).id,'custom');assert.equal(r.implicit.dimensions.at(-1).level,null);
 const problem=f.rubric.dimensions.find(d=>d.id==='problem-analysis');problem.levels[0].requires=['problem-context','problem-gap'];assert.equal(buildPortrait(f).implicit.dimensions.find(d=>d.id===problem.id).level,null);
});
test('完整列表中状态未知不产生已发表实际零',()=>{const f=fixture();f.extraction.items.forEach(i=>i.status='unknown');const r=buildPortrait(f);assert.equal(r.explicit.ledger.paper.published,null);assert.equal(r.explicit.ledger_details.paper.counts.published.listed,0);});

test('不同DOI或不同日期同名活动不合并，模糊重复待复核',()=>{
 const f=fixture();f.extraction.items[0].identifier='doi:one';f.extraction.items.push({...f.extraction.items[0],item_id:'doi-two',identifier:'doi:two'});
 let r=buildPortrait(f);assert.equal(r.explicit.ledger.paper.published,3);
 const event={...f.extraction.items[0],kind:'exchange',status:'completed',identifier:null,title:'实验室学术交流',occurred_on:'2026-01-01'};
 f.extraction.items.push({...event,item_id:'event-one'},{...event,item_id:'event-two',occurred_on:'2026-02-01'});r=buildPortrait(f);assert.equal(r.explicit.ledger.exchange.completed,2);
 f.extraction.items.push({...event,item_id:'uncertain-event',occurred_on:null,evidence:[{document_id:'annual-1',segment_id:'body',quote:'B方法已发表'}]});r=buildPortrait(f);assert.equal(r.explicit.ledger.exchange.completed,null);assert.ok(r.explicit.potential_duplicates.length);
});
test('配置拒绝多级metric和对文字字段设数值阈值',()=>{
 for(const metric of ['paper.published.extra','research_topic']){const f=fixture();f.rules.checks.push({id:'invalid-metric',label:'坏配置',kind:'minimum',metric,threshold:2,source:'合成规则',applicable_stages:['annual']});assert.throws(()=>buildPortrait(f));}
});

test('约数不可改成下界达标，限定词只约束对应数字且范围负数拒绝',()=>{
 const f=fixture();const fact=f.extraction.facts[0];fact.field='academic_events_reported';
 for(const [phrase,token,value,qualifier,valid]of [['约20次','20',20,'lower_bound',false],['约20次','20',20,'approximate',true],['至少20次','20',20,'exact',false],['至少20次','20',20,'lower_bound',true],['-20次','20',20,'exact',false],['20-30次','20',20,'exact',false],['约20次与论文3篇','3',3,'exact',true]]){
 f.bundle.documents[0].segments[0].text=phrase;f.extraction.items=[];f.extraction.coverage=[];Object.assign(fact,{numeric_token:token,value,qualifier,evidence:[{document_id:'annual-1',segment_id:'body',quote:phrase}]});
 if(valid)assert.doesNotThrow(()=>validateExtraction(f.bundle,f.extraction,f.rules));else assert.throws(()=>validateExtraction(f.bundle,f.extraction,f.rules));
 }
});
test('部分解析材料的完整清单声明降级为部分清单',()=>{const f=fixture();f.bundle.documents[0].parse_status='partial';const r=buildPortrait(f);assert.equal(r.explicit.ledger.paper.published,2);assert.equal(r.explicit.ledger.paper.accepted,null);assert.equal(r.explicit.ledger_details.paper.partial_source,true);assert.equal(r.explicit.ledger_details.paper.counts.published.qualifier,'lower_bound');});

test('引用截去限定词不能把约数变为精确数',()=>{const f=fixture();f.bundle.documents[0].segments[0].text+=' 学术交流约20场。';f.extraction.facts.push({field:'academic_events_reported',value:20,qualifier:'exact',numeric_token:'20',evidence:[{document_id:'annual-1',segment_id:'body',quote:'20场'}]});assert.throws(()=>buildPortrait(f));f.extraction.facts.at(-1).qualifier='approximate';assert.doesNotThrow(()=>buildPortrait(f));});

test('中文数量按原token解析，不截断连续数字或单位',()=>{const f=fixture();for(const [token,value]of [['三',3],['一百二十',120],['一二〇',120]]){f.bundle.documents[0].segments[0].text='文献'+token+'篇';f.extraction.facts=[{field:'literature_read_reported',value,qualifier:'exact',numeric_token:token,evidence:[{document_id:'annual-1',segment_id:'body',quote:'文献'+token+'篇'}]}];f.extraction.items=[];f.extraction.coverage=[];assert.doesNotThrow(()=>validateExtraction(f.bundle,f.extraction,f.rules));}});

test('上界及否定数量不能截成下界或精确值',()=>{for(const phrase of ['不超过20次','不足20次','至多20次','20次以下']){const f=fixture();f.bundle.documents[0].segments[0].text=phrase;f.extraction.facts=[{field:'academic_events_reported',value:20,qualifier:phrase.startsWith('不超过')?'lower_bound':'exact',numeric_token:'20',evidence:[{document_id:'annual-1',segment_id:'body',quote:phrase}]}];f.extraction.items=[];f.extraction.coverage=[];assert.throws(()=>validateExtraction(f.bundle,f.extraction,f.rules),/upper bound/);}});

test('标识确认的重复合并后移除已解决的疑似标志',()=>{const f=fixture();f.extraction.items[0].identifier='doi:a';f.extraction.items.push({...structuredClone(f.extraction.items[0]),item_id:'no-id',identifier:null});f.extraction.items.push({...structuredClone(f.extraction.items[0]),item_id:'confirmed-id',evidence:[{document_id:'annual-1',segment_id:'body',quote:'已发表'}]});const r=buildPortrait(f);assert.equal(r.explicit.ledger.paper.published,2);assert.equal(r.explicit.potential_duplicates.length,0);});

test('离线与合成来源不能伪称模型调用',()=>{for(const mode of ['synthetic','assistant_curated','offline_replay']){const f=fixture();f.provenance={mode,model:'fabricated-model'};assert.throws(()=>buildPortrait(f),/cannot name a model/);}});

test('证据修复反馈只含可信路径类别，不含伪造原句',async()=>{const {repairFeedback}=await import('../../.agents/skills/graduate-portrait/scripts/validation.mjs');const f=fixture();f.extraction.facts[0].evidence[0].quote='PRIVATE_FAKE_QUOTE';let caught;try{validateExtraction(f.bundle,f.extraction,f.rules);}catch(error){caught=error;}const feedback=repairFeedback(caught);assert.match(feedback,/QUOTE_NOT_IN_SEGMENT/);assert.match(feedback,/facts\/0/);assert.ok(!feedback.includes('PRIVATE_FAKE_QUOTE'));});

test('未见证据不能陈述实际工作状态，反馈定位criterion且有引文可保留计划',async()=>{const f=fixture();const c=f.assessment.dimensions[2].criteria[0];Object.assign(c,{judgment:'not_observed',work_status:'completed',evidence:[],missing_evidence:'缺少验证结果。'});const {repairFeedback}=await import('../../.agents/skills/graduate-portrait/scripts/validation.mjs');let caught;try{validateAssessment(f.bundle,f.assessment,f.rubric);}catch(error){caught=error;}assert.ok(caught);assert.match(repairFeedback(caught),/dimensions\/2\/criteria\/0/);assert.match(repairFeedback(caught),/WORK_STATUS_WITHOUT_EVIDENCE/);c.work_status='unknown';assert.doesNotThrow(()=>validateAssessment(f.bundle,f.assessment,f.rubric));c.work_status='planned';c.evidence=f.extraction.facts[0].evidence;assert.doesNotThrow(()=>validateAssessment(f.bundle,f.assessment,f.rubric));});

test('coverage重复的修复反馈定位后出现项及字段',async()=>{const f=fixture();f.extraction.coverage.push(structuredClone(f.extraction.coverage[0]));const {repairFeedback}=await import('../../.agents/skills/graduate-portrait/scripts/validation.mjs');let caught;try{validateExtraction(f.bundle,f.extraction,f.rules);}catch(error){caught=error;}assert.ok(caught);const issue=caught.validation_issues[0];assert.deepEqual(issue.path.split('/').filter(Boolean),['coverage',String(f.extraction.coverage.length-1),'kind']);assert.equal(issue.category,'DUPLICATE_IDENTIFIER');assert.match(repairFeedback(caught),/DUPLICATE_IDENTIFIER/);});
