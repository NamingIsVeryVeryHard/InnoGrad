import Ajv from 'ajv';
import { bundleSchema, extractionSchema, assessmentSchema } from './schema.mjs';

const ajv = new Ajv({ strict: true, allErrors: true });
const compiled = new Map();
export const compact = value => value.normalize('NFKC').replace(/\s+/gu, '');
const fail = message => { throw new Error(message); };
function atPath(path,operation){try{return operation();}catch(error){error.validation_issues??=[{path,category:error.message.includes('quote not found')?'QUOTE_NOT_IN_SEGMENT':error.message.includes('numeric')?'NUMERIC_TOKEN':error.message.includes('scope')?'SCOPE_MISMATCH':'VALIDATION'}];throw error;}}
export function repairFeedback(error){
  const issues=error instanceof SyntaxError?[{path:'',category:'JSON_PARSE'}]:error.validation_issues??[{path:'',category:'VALIDATION'}];
  return '本地校验错误（仅路径与类别）：'+JSON.stringify(issues.slice(0,12))+'。逐项修复并重新输出完整JSON。numeric_token只能写数字本身，例如数字3、120、20的字符串，不能含篇、场、余等单位或限定词；限定程度单独写qualifier。非unknown的work_status必须附直接引文，无引文改为unknown。quote必须是所指segment中连续的原文，不改写、不拼接不同位置句子。只输出JSON，不加Markdown代码块。';
}

export function validateShape(schema, data, label) {
  const key = JSON.stringify(schema);
  if (!compiled.has(key)) {
    if (compiled.size >= 32) compiled.delete(compiled.keys().next().value);
    compiled.set(key, ajv.compile(schema));
  }
  const validate = compiled.get(key);
  if (!validate(data)) {
    // Paths and error categories suffice; source data and provider responses stay out of logs.
    const error=new Error(label + ': ' + validate.errors.map(e => e.instancePath + ' ' + e.keyword).join('; '));
    error.validation_issues=validate.errors.map(e=>({path:e.instancePath,category:'SCHEMA_'+e.keyword.toUpperCase()}));throw error;
  }
}

export function unique(values, label, pointer) {
  const seen=new Set();
  for(const [index,value]of values.entries()){if(seen.has(value)){const error=new Error(label+': duplicate identifier');if(pointer)error.validation_issues=[{path:pointer(index),category:'DUPLICATE_IDENTIFIER'}];throw error;}seen.add(value);}
}

function sameScope(bundle, input) {
  for (const key of ['student_id', 'period', 'stage']) {
    if (bundle[key] !== input[key]) fail('scope mismatch: ' + key);
  }
}

export function validateBundle(bundle) {
  validateShape(bundleSchema, bundle, 'bundle');
  unique(bundle.documents.map(d => d.document_id), 'document_id');
  if (bundle.period === null && bundle.stage !== 'proposal') fail('annual period required');
  const years = bundle.period === null ? [] : bundle.period.split('-').map(Number);
  if (years.length === 2 && years[1] !== years[0] + 1) fail('period must be consecutive years');
  for (const doc of bundle.documents) {
    if (doc.student_id !== bundle.student_id || doc.period !== bundle.period) fail('document scope mismatch');
    unique(doc.segments.map(s => s.segment_id), 'segment_id');
    if (doc.parse_status === 'complete' && !doc.segments.some(s => compact(s.text))) fail('empty complete document');
  }
  return bundle;
}

export function validateEvidence(bundle, refs, required = true) {
  if (required && refs.length === 0) fail('missing evidence');
  for (const ref of refs) {
    const doc = bundle.documents.find(d => d.document_id === ref.document_id);
    const segment = doc?.segments.find(s => s.segment_id === ref.segment_id);
    if (!doc || doc.parse_status === 'failed' || !segment) fail('unknown evidence location');
    if (!compact(ref.quote) || !compact(segment.text).includes(compact(ref.quote))) fail('quote not found in source segment');
  }
}

function tokenValue(token) {
  const normalized = compact(token).replace(/,/g, '');
  if (/^\d+(?:\.\d+)?$/.test(normalized)) return Number(normalized);
  const digits = { 零: 0, 〇: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
  if ([...normalized].every(c => Object.hasOwn(digits, c))) return Number([...normalized].map(c => digits[c]).join(''));
  const units = { 十: 10, 百: 100, 千: 1000 };
  let total = 0, digit = null, previousUnit = Infinity;
  for (const c of normalized) {
    if (Object.hasOwn(digits, c)) {
      if (digit !== null && digit !== 0) return NaN;
      digit = digits[c];
    } else if (Object.hasOwn(units, c)) {
      if (units[c] >= previousUnit) return NaN;
      total += (digit ?? 1) * units[c]; digit = null; previousUnit = units[c];
    } else return NaN;
  }
  return total + (digit ?? 0);
}

export function validateExtraction(bundle, extraction, rules) {
  validateBundle(bundle);
  validateShape(extractionSchema(rules), extraction, 'extraction');
  sameScope(bundle, extraction);
  unique(extraction.items.map(i => i.item_id), 'item_id');
  unique(extraction.coverage.map(c => c.kind), 'coverage', index=>'/coverage/'+index+'/kind');
  for (const [factIndex,fact] of extraction.facts.entries()) {
    atPath('/facts/'+factIndex,()=>{
    const field = rules.fields.find(f => f.id === fact.field);
    if (typeof fact.value !== field.type) fail('fact value type mismatch: ' + field.id);
    validateEvidence(bundle, fact.evidence);
    if (field.type === 'number') {
      if (!fact.numeric_token || tokenValue(fact.numeric_token) !== fact.value) fail('numeric value does not match source token');
      const token = compact(fact.numeric_token);
      const occurrences = fact.evidence.flatMap(e => {
        const quoted=compact(e.quote),q=compact(bundle.documents.find(d=>d.document_id===e.document_id).segments.find(s=>s.segment_id===e.segment_id).text);
        const starts=[];for(let from=0;(from=q.indexOf(quoted,from))!==-1;from++)starts.push(from);
        return [...q.matchAll(/[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千万]+/gu)].filter(m=>m[0]===token&&starts.some(start=>m.index>=start&&m.index+token.length<=start+quoted.length)).map(m=>({q,index:m.index}));
      });
      if (!occurrences.length) fail('numeric token not found at number boundary');
      for (const {q,index} of occurrences) {
        const before=q.slice(0,index),after=q.slice(index+token.length);
        if (/(?:不超过|未超过|不多于|不高于|至多|最多|不足|少于|小于|低于|不到|不满|上限(?:为)?|不(?:大于|足))$/.test(before)||/^(?:[^0-9零〇一二两三四五六七八九十百千万，。；：、]{0,3})(?:以下|以内)/u.test(after)) fail('upper bound or negated quantity unsupported');
        if (/[-−]$/.test(before)||/[0-9零〇一二两三四五六七八九十百千万][~～至到]$/u.test(before)||/^[-−~～至到][0-9零〇一二两三四五六七八九十百千万]/u.test(after)) fail('negative number or range unsupported');
        const approximate=/(?:大约|约|近)$/.test(before)||/^(?:[^0-9零〇一二两三四五六七八九十百千万，。；：、]{0,3})左右/u.test(after);
        const lower=/(?:超过|超|多于|至少|不少于)$/.test(before)||/^(?:余|多|[^0-9零〇一二两三四五六七八九十百千万，。；：、]{0,3}以上)/u.test(after);
        if (approximate && lower) fail('ambiguous numeric qualifier');
        if (approximate && fact.qualifier!=='approximate') fail('approximate source number requires approximate qualifier');
        if (lower && fact.qualifier!=='lower_bound') fail('source lower bound requires lower_bound qualifier');
        if (!approximate && !lower && fact.qualifier==='lower_bound') fail('lower bound requires source qualifier');
      }
    } else if (fact.numeric_token !== null || fact.qualifier !== 'exact') {
      fail('text facts must use exact qualifier and no numeric token');
    }
    });
  }
  for (const [itemIndex,item] of extraction.items.entries()) {
    atPath('/items/'+itemIndex,()=>{
    validateEvidence(bundle, item.evidence);
    if (bundle.period === null && item.period_status === 'in_scope') fail('period unconfirmed: cannot claim in-scope item');
    if (item.kind === 'paper' && !['planned', 'in_progress', 'under_review', 'accepted', 'published', 'unknown'].includes(item.status)) {
      fail('paper requires a publication status');
    }
    if (item.kind !== 'paper' && ['under_review', 'accepted', 'published'].includes(item.status)) fail('invalid non-paper status');
    });
  }
  for (const [coverageIndex,coverage] of extraction.coverage.entries()) atPath('/coverage/'+coverageIndex,()=>validateEvidence(bundle, coverage.evidence, coverage.status === 'complete'));
  return extraction;
}

export function validateAssessment(bundle, assessment, rubric) {
  validateBundle(bundle);
  validateShape(assessmentSchema(rubric), assessment, 'assessment');
  sameScope(bundle, assessment);
  unique(assessment.dimensions.map(d => d.dimension_id), 'dimension_id');
  if (assessment.dimensions.length !== rubric.dimensions.length) fail('missing rubric dimension');
  for (const [dimensionIndex,dimension] of assessment.dimensions.entries()) {
    const definition = rubric.dimensions.find(d => d.id === dimension.dimension_id);
    unique(dimension.criteria.map(c => c.criterion_id), 'criterion_id');
    if (dimension.criteria.length !== definition.criteria.length) fail('missing rubric criterion');
    for (const [criterionIndex,c] of dimension.criteria.entries()) {
      atPath('/dimensions/'+dimensionIndex+'/criteria/'+criterionIndex,()=>{
      const criterion = definition.criteria.find(x => x.id === c.criterion_id);
      if (!criterion) fail('unknown criterion');
      if(c.work_status!=='unknown'&&!c.evidence.length){const error=new Error('work status requires direct evidence');error.validation_issues=[{path:'/dimensions/'+dimensionIndex+'/criteria/'+criterionIndex+'/work_status',category:'WORK_STATUS_WITHOUT_EVIDENCE'}];throw error;}
      validateEvidence(bundle, c.evidence, c.judgment !== 'not_observed');
      if (c.judgment === 'not_observed' && !c.missing_evidence?.trim()) fail('missing explanation of evidence gap');
      if (c.judgment === 'supported' && !criterion.allowed_work_statuses.includes(c.work_status)) fail('work status cannot support this criterion');
      if (c.judgment === 'supported' && c.work_status === 'completed' &&
          criterion.allowed_work_statuses.every(s => s === 'completed') &&
          c.evidence.every(e => bundle.documents.find(d => d.document_id === e.document_id).kind === 'proposal')) {
        fail('completed result requires annual or supporting evidence');
      }
      });
    }
  }
  return assessment;
}
