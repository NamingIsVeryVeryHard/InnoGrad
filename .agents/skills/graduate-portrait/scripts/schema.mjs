const text = { type: 'string', minLength: 1 };
const nullableText = { type: ['string', 'null'], minLength: 1 };
const array = items => ({ type: 'array', items });
const object = properties => ({ type: 'object', properties, required: Object.keys(properties), additionalProperties: false });
const choice = values => ({ type: 'string', enum: values });
const scope = {
  schema_version: { const: '1.0' },
  student_id: text,
  period: { type: ['string', 'null'], pattern: '^\\d{4}(?:-\\d{4})?$' },
  stage: choice(['annual', 'proposal']),
};
export const itemStatuses = ['planned', 'in_progress', 'under_review', 'accepted', 'published', 'completed', 'unknown'];
export const evidenceSchema = object({ document_id: text, segment_id: text, quote: text });
const evidence = array(evidenceSchema);

export const bundleSchema = object({
  ...scope,
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

export function assessmentSchema(rubric) {
  return object({
    ...scope, rubric_version: { const: rubric.version },
    dimensions: array(object({
      dimension_id: choice(rubric.dimensions.map(d => d.id)),
      criteria: array(object({
        criterion_id: text, judgment: choice(['supported', 'contradicted', 'not_observed']),
        work_status: choice(['planned', 'in_progress', 'completed', 'unknown']),
        rationale: text, evidence, missing_evidence: nullableText,
      })),
    })),
  });
}

export const schemas = { bundle: bundleSchema, extraction: extractionSchema, assessment: assessmentSchema };
