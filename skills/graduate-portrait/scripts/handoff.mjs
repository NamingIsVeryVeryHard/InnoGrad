import {createHash} from 'node:crypto';
import {scope,extractionSchema,evidenceSchema,itemStatuses} from './schema.mjs';
import {explicitSchema} from './portrait-schema.mjs';
import {validateBundle,validateExtraction,validateEvidence,validateShape,unique,compact} from './validation.mjs';
import {buildExplicit} from './engine.mjs';
const text={type:'string',minLength:1};
const nullableText={type:['string','null'],minLength:1};
const object=properties=>({type:'object',properties,required:Object.keys(properties),additionalProperties:false});
function canonical(value){if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';return JSON.stringify(value);}
const digest=value=>createHash('sha256').update(canonical(value)).digest('hex');
export function materialFingerprints(bundle){
 return bundle.documents.map(d=>({document_id:d.document_id,sha256:d.sha256,content_sha256:digest({source_name:d.source_name,kind:d.kind,student_id:d.student_id,period:d.period,parse_status:d.parse_status,segments:d.segments,...(bundle.input_context?{input_context:bundle.input_context}:{})})})).sort((a,b)=>a.document_id.localeCompare(b.document_id));
}
export const producerSchema=object({mode:{enum:['skill_execution','remote_model','offline_replay','assistant_curated','synthetic']},name:nullableText,model:nullableText});
export function aResultSchema(rules){return object({
 ...scope,schema_version:{const:'a-handoff-1.0'},task_id:nullableText,
 task_context_sha256:{type:'string',pattern:'^[a-f0-9]{64}$'},
 material_fingerprints:{type:'array',minItems:1,items:object({document_id:text,sha256:{type:'string',pattern:'^[a-f0-9]{64}$'},content_sha256:{type:'string',pattern:'^[a-f0-9]{64}$'}})},
 output_version:text,generated_at:{type:'string',pattern:'^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$'},producer:producerSchema,
 rules_version:{const:rules.version},extraction:extractionSchema(rules),explicit:explicitSchema,
 });}
export function validateAResult(bundle,aResult,rules){
 validateBundle(bundle);validateShape(aResultSchema(rules),aResult,'aResult');
 for(const key of ['student_id','period','stage'])if(aResult[key]!==bundle[key])throw Error('A scope mismatch: '+key);
 if(aResult.task_id!==(bundle.task_context?.task_id??null)||aResult.task_context_sha256!==digest(bundle.task_context??null))throw Error('A task context mismatch');
 if(canonical([...aResult.material_fingerprints].sort((a,b)=>a.document_id.localeCompare(b.document_id)))!==canonical(materialFingerprints(bundle)))throw Error('A material fingerprints mismatch');
 if(!Number.isFinite(Date.parse(aResult.generated_at)))throw Error('A generation date invalid');
 if(aResult.producer.mode==='remote_model'&&!aResult.producer.model)throw Error('A remote provenance missing model');
 if(['synthetic','offline_replay','assistant_curated'].includes(aResult.producer.mode)&&aResult.producer.model)throw Error('A replay cannot name a model');
 validateExtraction(bundle,aResult.extraction,rules);
 function sameKeys(actual,expected,label){if(canonical(Object.keys(actual).sort())!==canonical([...expected].sort()))throw Error('A '+label+' mismatch');}
 sameKeys(aResult.explicit.metrics,rules.fields.map(f=>f.id),'metric fields');
 sameKeys(aResult.explicit.ledger,rules.item_kinds,'ledger kinds');sameKeys(aResult.explicit.ledger_details,rules.item_kinds,'ledger detail kinds');
 for(const kind of rules.item_kinds){
  sameKeys(aResult.explicit.ledger[kind],itemStatuses,'ledger '+kind+' states');
  sameKeys(aResult.explicit.ledger_details[kind].counts,itemStatuses,'ledger detail '+kind+' states');
 }
 if(canonical(aResult.explicit.groups)!==canonical(rules.groups.map(g=>({id:g.id,label:g.label,fields:g.fields,item_kinds:g.item_kinds}))))throw Error('A explicit groups mismatch');
 unique(aResult.explicit.checks.map(c=>c.id),'A rule checks');
 if(aResult.explicit.checks.length!==rules.checks.length)throw Error('A missing rule checks');
 for(const check of aResult.explicit.checks){
  const definition=rules.checks.find(c=>c.id===check.id);
  const common=['not_applicable','period_unconfirmed','needs_review','insufficient_evidence'];
  const statuses={minimum:[...common,'pending_rule','met','not_met'],consistency:[...common,'consistent'],material_comparison:[...common,'met','not_met']};
  if(!statuses[check.kind]?.includes(check.status))throw Error('A invalid status for rule kind');
  if(!definition||check.rule_version!==rules.version)throw Error('A rule version mismatch');
  if(!check.applicable_scope||['student_id','period','stage'].some(key=>check.applicable_scope[key]!==bundle[key]))throw Error('A rule scope mismatch');
  if(!Array.isArray(check.input_evidence))throw Error('A rule input evidence required');
  const allowedRefs=aResult.extraction.facts.filter(f=>[definition.metric,definition.reported_field,definition.required_field].includes(f.field)).flatMap(f=>f.evidence).concat(aResult.extraction.items.filter(i=>i.kind===definition.metric.split('.')[0]).flatMap(i=>i.evidence));
  const refKey=e=>canonical([e.document_id,e.segment_id,compact(e.quote)]);const extractedRefs=new Set(allowedRefs.map(refKey));
  if(check.input_evidence.some(e=>!extractedRefs.has(refKey(e))))throw Error('A rule input reference not in extraction');
  if(['met','not_met','consistent'].includes(check.status)){const required=check.kind==='consistency'?['self_report','listed','listing_coverage']:check.kind==='minimum'?['threshold','observed']:['observed','reference'];if(required.some(key=>!Object.hasOwn(check,key)||check[key]===null))throw Error('A evaluated rule missing inputs');}
  validateEvidence(bundle,check.input_evidence,['met','not_met','consistent'].includes(check.status));
  if(!definition.applicable_stages.includes(bundle.stage)&&check.status!=='not_applicable')throw Error('A stage requires not applicable');
  if(definition.applicable_stages.includes(bundle.stage)&&check.status==='not_applicable')throw Error('A rule stage mismatch');
  if(bundle.period===null&&definition.applicable_stages.includes(bundle.stage)&&check.status!=='period_unconfirmed')throw Error('A unconfirmed period cannot evaluate rule');
  if(bundle.period!==null&&check.status==='period_unconfirmed')throw Error('A confirmed period mismatch');
  if(definition.kind==='minimum'&&Object.hasOwn(check,'threshold')&&check.threshold!==definition.threshold)throw Error('A threshold version mismatch');
  if(check.kind!==definition.kind||check.metric!==definition.metric||check.source!==(definition.source??null))throw Error('A rule definition mismatch');
  if(definition.kind==='minimum'&&(definition.threshold==null||!definition.source?.trim())&&check.status!=='pending_rule'&&definition.applicable_stages.includes(bundle.stage)&&bundle.period!==null)throw Error('A unconfirmed rule must remain pending');
 }
 // Traverse every reference including metric observations and ledger records; never trust a copied quote.
 function walk(value){if(!value||typeof value!=='object')return;if(Object.hasOwn(value,'document_id')&&Object.hasOwn(value,'segment_id')&&Object.hasOwn(value,'quote')){validateShape(evidenceSchema,value,'A evidence');validateEvidence(bundle,[value]);return;}for(const child of Object.values(value))walk(child);}
 walk(aResult.explicit);
 return aResult;
}
export function buildAResult({bundle,extraction,rules,metadata}){
 if(!metadata)throw Error('A output metadata required');
 const result={schema_version:'a-handoff-1.0',student_id:bundle.student_id,period:bundle.period,stage:bundle.stage,task_id:bundle.task_context?.task_id??null,task_context_sha256:digest(bundle.task_context??null),material_fingerprints:materialFingerprints(bundle),output_version:metadata.output_version,generated_at:metadata.generated_at,producer:metadata.producer,rules_version:rules.version,extraction:structuredClone(extraction),explicit:buildExplicit({bundle,extraction,rules})};
 return validateAResult(bundle,result,rules);
}
