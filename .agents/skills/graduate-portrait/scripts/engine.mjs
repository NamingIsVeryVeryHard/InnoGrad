import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { validateExtraction, validateAssessment, unique, compact } from './validation.mjs';
import { itemStatuses } from './schema.mjs';
export { validateExtraction, validateAssessment } from './validation.mjs';
export const skillVersion = '0.1.0';
export function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
export const hash = value => createHash('sha256').update(typeof value === 'string' ? value : canonical(value)).digest('hex');
function implementationHash() {
  const files = readdirSync(new URL('.', import.meta.url)).filter(f => /\.(mjs|json)$/.test(f)).sort();
  return hash(files.map(f => [f, readFileSync(new URL(f, import.meta.url),'utf8')]).concat([['SKILL.md',readFileSync(new URL('../SKILL.md',import.meta.url),'utf8')]]));
}
function validateConfig(rules, rubric) {
  if (!rules.version || !rubric.version || !rules.fields?.length || !rules.item_kinds?.length || !rubric.dimensions?.length) throw new Error('invalid configuration');
  unique(rules.fields.map(f=>f.id),'rule field'); unique(rules.item_kinds,'item kind'); unique(rules.groups.map(g=>g.id),'rule group'); unique(rules.checks.map(c=>c.id),'rule check'); unique(rubric.dimensions.map(d=>d.id),'rubric dimension');
  for (const f of rules.fields) if (!['number','string'].includes(f.type)) throw new Error('invalid field type');
  for (const g of rules.groups) if (g.fields.some(x=>!rules.fields.some(f=>f.id===x)) || g.item_kinds.some(x=>!rules.item_kinds.includes(x))) throw new Error('unknown group field or kind');
  const knownMetric = id => typeof id==='string' && (rules.fields.some(f=>f.id===id && f.type==='number') || (id.split('.').length===2 && rules.item_kinds.includes(id.split('.')[0]) && itemStatuses.includes(id.split('.')[1])));
  for (const c of rules.checks) {
    if (!['minimum','consistency','material_comparison'].includes(c.kind) || !knownMetric(c.metric) || !c.applicable_stages?.length || c.applicable_stages.some(s=>!['annual','proposal'].includes(s))) throw new Error('invalid check configuration');
    if (c.kind==='minimum' && c.threshold!==null && (!Number.isFinite(c.threshold) || c.threshold<0)) throw new Error('invalid threshold');
    if (c.kind==='consistency' && (c.metric.split('.').length!==2 || !rules.fields.some(f=>f.id===c.reported_field && f.type==='number'))) throw new Error('invalid reported field');
    if (c.kind==='material_comparison' && (!rules.fields.some(f=>f.id===c.metric && f.type==='number') || !rules.fields.some(f=>f.id===c.required_field && f.type==='number'))) throw new Error('invalid required field');
  }
  for (const d of rubric.dimensions) {
    if (!d.criteria?.length || !d.levels?.length) throw new Error('empty rubric dimension');
    unique(d.criteria.map(c=>c.id),'rubric criterion'); unique(d.levels.map(l=>l.value),'rubric level');
    for (const c of d.criteria) if (!c.allowed_work_statuses?.length || c.allowed_work_statuses.some(s=>!['planned','in_progress','completed'].includes(s))) throw new Error('invalid criterion work status');
    const levels=[...d.levels].sort((a,b)=>a.value-b.value);
    for (let i=0;i<levels.length;i++) {
      const l=levels[i]; if (!Number.isInteger(l.value) || l.value<1 || !l.requires?.length || l.requires.some(id=>!d.criteria.some(c=>c.id===id)) || (i && levels[i-1].requires.some(id=>!l.requires.includes(id)))) throw new Error('invalid cumulative rubric level');
    }
  }
}
function metricsFor(extraction,rules) {
  return Object.fromEntries(rules.fields.map(f=> {
    const observations=extraction.facts.filter(x=>x.field===f.id).map(x=>structuredClone(x));
    const values=new Map(observations.map(x=>[canonical([x.value,x.qualifier]),x]));
    const one=values.size===1 ? [...values.values()][0] : null;
    return [f.id,{label:f.label,unit:f.unit,value:one?.value??null,qualifier:one?.qualifier??null,status:values.size>1?'conflict':one?'observed':'not_observed',verification:'material_report',observations}];
  }));
}
function ledgerFor(extraction,rules,bundle) {
  // Merge exact normalized titles or identifiers within a kind. Never merge students by name.
  const groups=[];
  const potentialDuplicates=[];
  const eventKinds=new Set(['exchange','practice','training']);
  const sameEvidence=(a,b)=>canonical(a.evidence)===canonical(b.evidence);
  function relationship(a,b) {
    if(a.kind!==b.kind)return 'different';
    const ai=a.identifier&&compact(a.identifier).toLowerCase(),bi=b.identifier&&compact(b.identifier).toLowerCase();
    if(ai&&bi)return ai===bi?'same':'different';
    if(compact(a.title).toLowerCase()!==compact(b.title).toLowerCase())return 'different';
    if(eventKinds.has(a.kind)&&a.occurred_on&&b.occurred_on&&a.occurred_on!==b.occurred_on)return 'different';
    if(eventKinds.has(a.kind)&&a.occurred_on&&a.occurred_on===b.occurred_on)return 'same';
    if(sameEvidence(a,b)&&a.occurred_on===b.occurred_on)return 'same';
    return 'uncertain';
  }
  for (const item of extraction.items) {
    let matches=groups.filter(g=>g.items.some(i=>relationship(i,item)==='same') && g.items.every(i=>relationship(i,item)!=='different'));
    for(const g of groups)if(g.items.some(i=>relationship(i,item)==='uncertain'))potentialDuplicates.push({kind:item.kind,item_ids:[...g.items.map(i=>i.item_id),item.item_id],status:'needs_review',reason:'同名记录缺少可确认的标识或日期。'});
    if(matches.length>1 && matches.some(a=>matches.some(b=>a!==b&&a.items.some(ai=>b.items.some(bi=>relationship(ai,bi)==='different'))))) {
      potentialDuplicates.push({kind:item.kind,item_ids:[...matches.flatMap(g=>g.items.map(i=>i.item_id)),item.item_id],status:'needs_review',reason:'同名记录连接到不同标识，无法确认重复。'});matches=[];
    }
    let g=matches[0];
    if (!g) {g={kind:item.kind,items:[]};groups.push(g);}
    for (const other of matches.slice(1)) {g.items.push(...other.items);groups.splice(groups.indexOf(other),1);}
    g.items.push(item);
  }
  const itemConflicts=groups.filter(g=>new Set(g.items.map(i=>i.status)).size>1 || new Set(g.items.map(i=>i.period_status)).size>1).map(g=>({kind:g.kind,item_ids:g.items.map(i=>i.item_id),statuses:[...new Set(g.items.map(i=>i.status))],period_statuses:[...new Set(g.items.map(i=>i.period_status))]}));
  const ledger={}, details={};
  for (const kind of rules.item_kinds) {
    const declaredCoverage=extraction.coverage.find(c=>c.kind===kind);
    const partialSource=bundle.documents.some(d=>d.parse_status!=='complete' && (declaredCoverage?.evidence.some(e=>e.document_id===d.document_id)||extraction.items.some(i=>i.kind===kind&&i.evidence.some(e=>e.document_id===d.document_id))));
    const coverage=partialSource&&declaredCoverage?.status==='complete'?'partial':declaredCoverage?.status??'not_reported';
    const relevant=groups.filter(g=>g.kind===kind);
    const conflicted=potentialDuplicates.some(p=>p.kind===kind)||relevant.some(g=>itemConflicts.some(c=>c.item_ids.includes(g.items[0].item_id)));
    const uncertain=bundle.period===null || relevant.some(g=>g.items.some(i=>i.period_status==='uncertain'||i.status==='unknown'));
    ledger[kind]={};details[kind]={coverage,declared_coverage:declaredCoverage?.status??'not_reported',partial_source:partialSource,counts:{},excluded_item_ids:[]};
    for (const status of itemStatuses) {
      const observed=relevant.filter(g=>new Set(g.items.map(i=>i.status)).size===1 && new Set(g.items.map(i=>i.period_status)).size===1 && g.items[0].period_status==='in_scope' && g.items[0].status===status).length;
      const exact=coverage==='complete'&&!conflicted&&!uncertain;
      ledger[kind][status]=conflicted ? null : observed||exact ? observed : null;
      details[kind].counts[status]={listed:observed,value:ledger[kind][status],qualifier:exact?'exact':'lower_bound',status:conflicted?'conflict':exact?'complete_listing':observed?'partial_listing':'not_observed'};
    }
    details[kind].excluded_item_ids=relevant.flatMap(g=>g.items.filter(i=>i.period_status!=='in_scope').map(i=>i.item_id));
  }
  return {ledger,ledger_details:details,item_conflicts:itemConflicts,potential_duplicates:potentialDuplicates,items:groups.map(g=>({kind:g.kind,item_ids:g.items.map(i=>i.item_id),records:structuredClone(g.items)}))};
}
function checkRules(bundle,rules,metrics,details) {
  const getMetric=id=>id.includes('.') ? details[id.split('.')[0]].counts[id.split('.')[1]] : metrics[id];
  return rules.checks.map(c=> {
    const base={id:c.id,label:c.label,kind:c.kind,source:c.source??null,metric:c.metric};
    if(!c.applicable_stages.includes(bundle.stage))return {...base,status:'not_applicable'};
    if(bundle.period===null)return {...base,status:'period_unconfirmed'};
    const m=getMetric(c.metric); const observed=m.value;
    if(c.kind==='minimum') {
      if(c.threshold===null||!c.source?.trim()) return {...base,status:'pending_rule',threshold:c.threshold,observed};
      if(observed===null)return {...base,status:m.status==='conflict'?'needs_review':'insufficient_evidence',threshold:c.threshold,observed};
      const status=observed>=c.threshold && m.qualifier!=='approximate'?'met':m.qualifier==='exact'?'not_met':'insufficient_evidence';
      return {...base,status,threshold:c.threshold,observed,qualifier:m.qualifier};
    }
    const reference=metrics[c.kind==='consistency'?c.reported_field:c.required_field];
    if(m.status==='conflict'||reference.status==='conflict')return {...base,status:'needs_review',observed,reference:reference.value};
    if(observed===null||reference.value===null)return {...base,status:'insufficient_evidence',observed,reference:reference.value};
    if(c.kind==='material_comparison') {
      const status=m.qualifier==='approximate'||reference.qualifier!=='exact'?'insufficient_evidence':observed>=reference.value?'met':m.qualifier==='exact'?'not_met':'insufficient_evidence';
      return {...base,status,observed,reference:reference.value,interpretation:'仅核对材料记载学分，不是学校制度达标结论。'};
    }
    const status=reference.qualifier!=='exact'?'insufficient_evidence':reference.value!==m.listed?'needs_review':m.qualifier==='exact'?'consistent':'insufficient_evidence';
    return {...base,status,self_report:reference.value,listed:m.listed,listing_coverage:details[c.metric.split('.')[0]].coverage};
  });
}
function implicitFor(assessment,rubric) {
  return {rubric_version:rubric.version,status:rubric.status,interpretation:rubric.interpretation,overall_score:null,dimensions:rubric.dimensions.map(d=> {
    const criteria=structuredClone(assessment.dimensions.find(x=>x.dimension_id===d.id).criteria);
    const supported=new Set(criteria.filter(c=>c.judgment==='supported').map(c=>c.criterion_id));
    const level=[...d.levels].sort((a,b)=>b.value-a.value).find(l=>l.requires.every(id=>supported.has(id)));
    return {id:d.id,label:d.label,level:level?.value??null,level_label:level?.label??null,status:level?'supported':criteria.some(c=>c.judgment==='contradicted')?'contradicted':'insufficient_evidence',criteria,unmet_criteria:d.criteria.filter(c=>!supported.has(c.id)).map(c=>c.id),review_required:true};
  })};
}
export function buildPortrait({bundle,extraction,assessment,rules,rubric,provenance={}}) {
  validateConfig(rules,rubric);validateExtraction(bundle,extraction,rules);validateAssessment(bundle,assessment,rubric);
  const mode=provenance.mode??'offline_replay';
  if(!['offline_replay','synthetic','assistant_curated','skill_execution','remote_model'].includes(mode))throw new Error('unknown producer mode');
  const producer={mode,model:provenance.model??null,description:provenance.description??null};
  if(mode==='remote_model'&&!producer.model)throw new Error('remote model provenance required');
  const hashes={input:hash(bundle),extraction:hash(extraction),assessment:hash(assessment),rules:hash(rules),rubric:hash(rubric),skill:implementationHash()};
  const versions={schema:'1.0',rules:rules.version,rubric:rubric.version,skill:skillVersion};
  const metrics=metricsFor(extraction,rules);const {ledger,ledger_details,item_conflicts,potential_duplicates,items}=ledgerFor(extraction,rules,bundle);
  return {schema_version:'1.0',student_id:bundle.student_id,period:bundle.period,stage:bundle.stage,run_id:hash({hashes,versions,producer}),review_status:'draft',warnings:bundle.period===null?['period_unconfirmed']:[],provenance:{producer,hashes,versions},sources:bundle.documents.map(d=>({document_id:d.document_id,source_name:d.source_name,sha256:d.sha256,parse_status:d.parse_status,pages:d.segments.map(s=>({segment_id:s.segment_id,page:s.page}))})),explicit:{overall_score:null,metrics,ledger,ledger_details,item_conflicts,potential_duplicates,items,checks:checkRules(bundle,rules,metrics,ledger_details),groups:rules.groups.map(g=>({id:g.id,label:g.label,fields:g.fields,item_kinds:g.item_kinds}))},implicit:implicitFor(assessment,rubric)};
}
