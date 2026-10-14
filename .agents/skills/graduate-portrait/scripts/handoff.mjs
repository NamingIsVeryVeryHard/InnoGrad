import {createHash} from 'node:crypto';
import {scope,extractionSchema,evidenceSchema} from './schema.mjs';
import {explicitSchema} from './portrait-schema.mjs';
import {validateBundle,validateExtraction,validateEvidence,validateShape,unique} from './validation.mjs';
import {buildExplicit} from './engine.mjs';
const text={type:'string',minLength:1};
const nullableText={type:['string','null'],minLength:1};
const object=properties=>({type:'object',properties,required:Object.keys(properties),additionalProperties:false});
const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
export function materialFingerprints(bundle){
 return bundle.documents.map(d=>({document_id:d.document_id,sha256:d.sha256,content_sha256:digest({source_name:d.source_name,kind:d.kind,student_id:d.student_id,period:d.period,parse_status:d.parse_status,segments:d.segments})})).sort((a,b)=>a.document_id.localeCompare(b.document_id));
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
 if(JSON.stringify(aResult.material_fingerprints)!==JSON.stringify(materialFingerprints(bundle)))throw Error('A material fingerprints mismatch');
 if(!Number.isFinite(Date.parse(aResult.generated_at)))throw Error('A generation date invalid');
 if(aResult.producer.mode==='remote_model'&&!aResult.producer.model)throw Error('A remote provenance missing model');
 if(['synthetic','offline_replay','assistant_curated'].includes(aResult.producer.mode)&&aResult.producer.model)throw Error('A replay cannot name a model');
 validateExtraction(bundle,aResult.extraction,rules);
 unique(aResult.explicit.checks.map(c=>c.id),'A rule checks');
 if(aResult.explicit.checks.length!==rules.checks.length)throw Error('A missing rule checks');
 for(const check of aResult.explicit.checks){
  const definition=rules.checks.find(c=>c.id===check.id);
  const common=['not_applicable','period_unconfirmed','needs_review','insufficient_evidence'];
  const statuses={minimum:[...common,'pending_rule','met','not_met'],consistency:[...common,'consistent'],material_comparison:[...common,'met','not_met']};
  if(!statuses[check.kind]?.includes(check.status))throw Error('A invalid status for rule kind');
  if(!definition||check.rule_version!==rules.version)throw Error('A rule version mismatch');
  if(!check.applicable_scope||['student_id','period','stage'].some(key=>check.applicable_scope[key]!==bundle[key]))throw Error('A rule scope mismatch');
  validateEvidence(bundle,check.input_evidence,['met','not_met','consistent'].includes(check.status));
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
