const text = { type: 'string', minLength: 1 };
const nullableText = { type: ['string', 'null'], minLength: 1 };
const array = items => ({ type: 'array', items });
const object = properties => ({ type: 'object', properties, required: Object.keys(properties), additionalProperties: false });
const choice = values => ({ type: 'string', enum: values });
export const scope = {
  schema_version: { const: '1.0' },
  student_id: text,
  period: { type: ['string', 'null'], pattern: '^\\d{4}(?:-\\d{4})?$' },
  stage: choice(['annual', 'proposal']),
};
export const itemStatuses = ['planned', 'in_progress', 'under_review', 'accepted', 'published', 'completed', 'unknown'];
export const evidenceSchema = object({ document_id: text, segment_id: text, quote: text });
const evidence = array(evidenceSchema);

export const taskContextSchema = object({
  task_id: nullableText, observation_period: nullableText, training_category: nullableText,
  training_year: { type: ['integer', 'null'], minimum: 1 }, support_conditions: nullableText,
});

export const bundleSchema = object({
  ...scope,
  task_context: taskContextSchema,
  documents: {
    type: 'array', minItems: 1,
    items: object({
      document_id: text, source_name: text, sha256: { type: 'string', pattern: '^[a-f0-9]{64}$' },
      kind: choice(['annual', 'proposal', 'assessment', 'supporting']),
      student_id: text, period: scope.period,
      parse_status: choice(['complete', 'partial', 'failed']),
      segments: array(object({ segment_id: text, page: { type: ['integer', 'null'], minimum: 1 }, text: { type: 'string' } })),
    }),
  },
});

bundleSchema.required = bundleSchema.required.filter(key => key !== 'task_context');

export function extractionSchema(rules) {
  return object({
    ...scope,
    facts: array(object({
      field: choice(rules.fields.map(f => f.id)),
      value: { oneOf: [{ type: 'string', minLength: 1 }, { type: 'number', minimum: 0 }] },
      qualifier: choice(['exact', 'lower_bound', 'approximate']),
      numeric_token: {type:['string','null'],pattern:"^(?:[0-9０-９]+(?:[,，][0-9０-９]{3})*(?:[.．][0-9０-９]+)?|[零〇一二两三四五六七八九十百千万]+)$"}, evidence,
    })),
    items: array(object({
      item_id: text, kind: choice(rules.item_kinds), title: text,
      status: choice(itemStatuses), role: nullableText, identifier: nullableText,
      occurred_on: nullableText, period_status: choice(['in_scope', 'out_of_scope', 'uncertain']), evidence,
    })),
    coverage: array(object({ kind: choice(rules.item_kinds), status: choice(['complete', 'partial', 'not_reported']), evidence })),
  });
}

export const evidenceStates = ['evaluable', 'insufficient', 'conflicting', 'not_applicable'];
export const performanceGrades = ['needs_improvement', 'meets_requirements', 'well_demonstrated'];
export const criterionSchema = object({
  criterion_id: text, evidence_state: choice(evidenceStates),
  performance_grade: { type: ['string', 'null'], enum: [...performanceGrades, null] },
  standard_status: choice(['applicable', 'pending_confirmation', 'not_applicable']),
  work_status: choice(['planned', 'in_progress', 'completed', 'unknown']),
  observed: text, rationale: text,
  evidence: array(object({ ...evidenceSchema.properties, supports: text })),
  evidence_nature: choice(['observed', 'self_report', 'mixed', 'unknown']),
  contribution: object({ individual: nullableText, guidance: nullableText, tools: nullableText }),
  limitations: array(text), missing_evidence: array(text), suggestions: array(text),
});
// Optional on stored v2 assessments; required by new online task schemas.
criterionSchema.properties.condition_checks = array(object({
  condition_index: {type: 'integer', minimum: 0},
  status: choice(['supported', 'contradicted', 'unobserved']),
  evidence_indices: {type:'array',uniqueItems:true,items:{type:'integer',minimum:0}},
  reason: text,
}));
export function assessmentSchema(rubric, {requireConditions = false} = {}) {
  const containsId = (key, id) => ({ contains: { type: 'object', properties: { [key]: { const: id } }, required: [key] } });
  const branches = rubric.dimensions.map(d => object({
    dimension_id: { const: d.id },
    criteria: {
      type: 'array', minItems: d.criteria.length, maxItems: d.criteria.length,
      items: { allOf: [
        { $ref: '#/definitions/criterion' },
        { type: 'object', properties: { criterion_id: choice(d.criteria.map(c => c.id)) } },
      ] },
      allOf: d.criteria.map(c => containsId('criterion_id', c.id)),
    },
  }));
  const orderedCriterion = {...criterionSchema, properties: Object.fromEntries(['criterion_id','observed','evidence','condition_checks','contribution','evidence_nature','work_status','missing_evidence','limitations','rationale','evidence_state','standard_status','performance_grade','suggestions'].map(key=>[key,criterionSchema.properties[key]]))};
  return {
    ...object({
      ...scope, schema_version: { const: '2.0' }, rubric_version: { const: rubric.version },
      dimensions: {
        type: 'array', minItems: rubric.dimensions.length, maxItems: rubric.dimensions.length,
        items: { oneOf: branches }, allOf: rubric.dimensions.map(d => containsId('dimension_id', d.id)),
      },
    }),
    definitions: { criterion: {...orderedCriterion, required: requireConditions ? [...criterionSchema.required, 'condition_checks'] : criterionSchema.required} },
  };
}
export const schemas = { bundle: bundleSchema, extraction: extractionSchema, assessment: assessmentSchema };
