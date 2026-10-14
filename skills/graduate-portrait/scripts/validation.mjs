import Ajv from 'ajv';
import {jsonParseLocation} from './response.mjs';
import { bundleSchema, extractionSchema, assessmentSchema } from './schema.mjs';

const ajv = new Ajv({ strict: true, allErrors: true });
const compiled = new Map();
export const compact = value => value.normalize('NFKC').replace(/\s+/gu, '');
const fail = message => { throw new Error(message); };
function assessmentFail(message,path,category){const error=new Error(message);error.validation_issues=[{path,category}];throw error;}
function atPath(path,operation){try{return operation();}catch(error){error.validation_issues??=[{path,category:error.message.includes('quote not found')?'QUOTE_NOT_IN_SEGMENT':error.message.includes('numeric')?'NUMERIC_TOKEN':error.message.includes('scope')?'SCOPE_MISMATCH':'VALIDATION'}];throw error;}}
export function repairFeedback(error){
  const issues=error instanceof SyntaxError?[{path:'',category:'JSON_PARSE',...jsonParseLocation(error)}]:error.validation_issues??[{path:'',category:'VALIDATION'}];
  return '本地校验错误（仅路径、类别与可用数字位置）：'+JSON.stringify(issues.slice(0,12))+'。逐项修复并重新输出完整JSON。'+(error instanceof SyntaxError?'JSON_PARSE数字位置指待解析JSON内层文本；按schema检查每层数组[]与对象{}的配对及闭合，重新以多行缩进输出（非minified），不要自动补造或改写字段内容。':'')+'numeric_token只能写数字本身，例如数字3、120、20的字符串，不能含篇、场、余等单位或限定词；限定程度单独写qualifier。非unknown的work_status必须附直接引文，无引文改为unknown。可评价状态须属于当前criterion.allowed_work_statuses；不能为了合规把planned捏造为completed，也不能把unknown捏造为已执行。只有原文依据确足才认定真实状态；只有计划且该项要求已执行时用insufficient/null，状态未知而无法证明允许状态时也用insufficient/null，保留真实work_status并写具体缺口。quote必须是所指segment中连续的原文，不改写、不拼接不同位置句子。只输出JSON，不加Markdown代码块。';
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
    error.validation_issues=validate.errors.map(e=>({path:e.instancePath,category:'SCHEMA_'+e.keyword.toUpperCase(),...(e.keyword==='required'?{missing_property:e.params.missingProperty}:{})}));throw error;
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

export function standardStatus(bundle, criterion) {
  if (!criterion.applicable_stages.includes(bundle.stage)) return 'not_applicable';
  if (!criterion.standards || criterion.required_context.some(key => bundle.task_context?.[key] == null)) return 'pending_confirmation';
  return 'applicable';
}

export function validateAssessment(bundle, assessment, rubric) {
  validateBundle(bundle);
  if (rubric.schema_version !== '2.0') fail('unsupported rubric version');
  validateShape(assessmentSchema(rubric), assessment, 'assessment');
  sameScope(bundle, assessment);
  unique(assessment.dimensions.map(d => d.dimension_id), 'dimension_id');
  if (assessment.dimensions.length !== rubric.dimensions.length) fail('missing rubric dimension');
  for (const [dimensionIndex, dimension] of assessment.dimensions.entries()) {
    const definition = rubric.dimensions.find(d => d.id === dimension.dimension_id);
    unique(dimension.criteria.map(c => c.criterion_id), 'criterion_id');
    if (dimension.criteria.length !== definition.criteria.length) fail('missing rubric criterion');
    for (const [criterionIndex, c] of dimension.criteria.entries()) {
      const pointer = '/dimensions/' + dimensionIndex + '/criteria/' + criterionIndex;
      atPath(pointer, () => {
        const criterion = definition.criteria.find(x => x.id === c.criterion_id);
        if (!criterion) fail('unknown criterion');
        if (c.work_status !== 'unknown' && !c.evidence.length) {
          const error = new Error('work status requires direct evidence');
          error.validation_issues = [{ path: pointer + '/work_status', category: 'WORK_STATUS_WITHOUT_EVIDENCE' }];
          throw error;
        }
        if (c.condition_checks) {
          const checks = c.condition_checks;
          const count = criterion.required_conditions?.length ?? 0;
          if (checks.length !== count || new Set(checks.map(check => check.condition_index)).size !== count ||
              checks.some(check => check.condition_index >= count)) {
            assessmentFail('required conditions must each occur once', pointer+'/condition_checks', 'CONDITION_COVERAGE');
          }
          for (const [index, check] of checks.entries()) {
            if ((check.status !== 'unobserved' && !check.evidence_indices.length) ||
                check.evidence_indices.some(value => value >= c.evidence.length)) {
              assessmentFail('condition support requires valid evidence indices', pointer+'/condition_checks/'+index, 'CONDITION_EVIDENCE');
            }
          }
          if (['meets_requirements', 'well_demonstrated'].includes(c.performance_grade) && checks.some(check => check.status !== 'supported')) {
            assessmentFail('positive grade requires all necessary conditions supported', pointer+'/performance_grade', 'CONDITION_GRADE_CONFLICT');
          }
          if (c.performance_grade === 'needs_improvement' && !checks.some(check => check.status === 'contradicted')) {
            assessmentFail('low grade requires a direct counterexample', pointer+'/performance_grade', 'CONDITION_COUNTEREXAMPLE_REQUIRED');
          }
        }
        const configured = standardStatus(bundle, criterion);
        if (c.standard_status !== configured && !(configured === 'applicable' && c.standard_status === 'not_applicable' && c.evidence_state === 'not_applicable' && c.evidence.length)) fail('standard scope or context mismatch');
        const requiresEvidence = ['evaluable', 'conflicting'].includes(c.evidence_state) || (c.evidence_state === 'not_applicable' && configured !== 'not_applicable');
        validateEvidence(bundle, c.evidence, requiresEvidence);
        if (c.evidence_state !== 'evaluable' && c.performance_grade !== null) fail('non-evaluable criterion cannot have performance grade');
        if (c.standard_status !== 'applicable' && c.performance_grade !== null) fail('pending or inapplicable standard cannot have performance grade');
        if (c.evidence_state === 'evaluable' && c.standard_status === 'applicable' && c.performance_grade === null) fail('applicable evaluable criterion requires performance grade');
        if (c.evidence_state === 'insufficient' && !c.missing_evidence.length) fail('missing explanation of evidence gap');
        if (c.evidence_state === 'conflicting' && new Set(c.evidence.map(e=>JSON.stringify([e.document_id,e.segment_id,compact(e.quote)]))).size < 2) fail('conflicting evidence requires opposing references');
        if (c.evidence_state === 'not_applicable' && c.standard_status !== 'not_applicable') fail('not applicable requires task justification');
        if (configured === 'not_applicable' && c.evidence_state !== 'not_applicable') fail('criterion outside report stage');
        if (c.evidence_state === 'evaluable' && c.evidence_nature === 'unknown') assessmentFail('evaluable evidence nature required',pointer+'/evidence_nature','EVIDENCE_NATURE_REQUIRED');
        if (!c.evidence.length && c.evidence_nature !== 'unknown') assessmentFail('evidence nature without evidence',pointer+'/evidence_nature','EVIDENCE_NATURE_WITHOUT_EVIDENCE');
        if (c.evidence_state === 'evaluable' && !criterion.allowed_work_statuses.includes(c.work_status)) assessmentFail('work status cannot support this criterion',pointer+'/work_status','WORK_STATUS_NOT_ALLOWED');
        if (c.evidence_state === 'evaluable' && criterion.allowed_work_statuses.every(s => s === 'completed') && c.evidence.every(e => bundle.documents.find(d => d.document_id === e.document_id).kind === 'proposal')) fail('completed result requires annual or supporting evidence');
      });
    }
  }
  return assessment;
}
