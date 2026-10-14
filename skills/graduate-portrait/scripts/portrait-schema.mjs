import {synthesisSchema} from './synthesis.mjs';
import { evidenceSchema, itemStatuses, criterionSchema, taskContextSchema, extractionSchema } from './schema.mjs';
import { readFileSync } from 'node:fs';
const defaultRules=JSON.parse(readFileSync(new URL('../references/explicit-rules.json',import.meta.url),'utf8'));
const portraitExtractionSchema=extractionSchema(defaultRules);
portraitExtractionSchema.properties.facts.items.properties.field={type:'string',minLength:1};
portraitExtractionSchema.properties.items.items.properties.kind={type:'string',minLength:1};
portraitExtractionSchema.properties.coverage.items.properties.kind={type:'string',minLength:1};

const text = { type: 'string' };
const nullableText = { type: ['string', 'null'] };
const number = { type: 'number', minimum: 0 };
const nullableNumber = { type: ['number', 'null'], minimum: 0 };
const choice = values => ({ type: 'string', enum: values });
const array = items => ({ type: 'array', items });
const object = (properties, required = Object.keys(properties)) => ({ type: 'object', properties, required, additionalProperties: false });
const dictionary = additionalProperties => ({ type: 'object', additionalProperties });
const evidence = array(evidenceSchema);
const qualifier = choice(['exact', 'lower_bound', 'approximate']);
const fact = object({ field: text, value: { anyOf: [{ type: 'string' }, { type: 'number' }] }, qualifier, numeric_token: nullableText, evidence });
const item = object({
  item_id: text, kind: text, title: text, status: choice(itemStatuses), role: nullableText,
  identifier: nullableText, occurred_on: nullableText,
  period_status: choice(['in_scope', 'out_of_scope', 'uncertain']), evidence,
});
const enrichedEvidence = object({ ...criterionSchema.properties.evidence.items.properties, source_name: text, sha256: text, page: { type: ['integer','null'], minimum: 1 } });
const criterion = object({ ...criterionSchema.properties, criterion_label: text, evidence: array(enrichedEvidence),
  review: object({ status: {const:'pending'}, reviewer: {type:'null'}, reviewed_at: {type:'null'}, modification_reason: {type:'null'}, independent_corroboration: {const:'unverified'} }),
}, [...criterionSchema.required, 'criterion_label', 'review']);
const check = object({
  rule_version: text, applicable_scope: object({ student_id: text, period: nullableText, stage: choice(['annual','proposal']) }), input_evidence: evidence,
  id: text, label: text, kind: choice(['minimum', 'consistency', 'material_comparison']),
  source: nullableText, metric: text,
  status: choice(['not_applicable', 'period_unconfirmed', 'pending_rule', 'needs_review', 'insufficient_evidence', 'met', 'not_met', 'consistent']),
  threshold: nullableNumber, observed: nullableNumber, qualifier,
  reference: nullableNumber, interpretation: text, self_report: number, listed: number,
  listing_coverage: choice(['complete', 'partial', 'not_reported']),
}, ['id', 'label', 'kind', 'source', 'metric', 'status', 'rule_version', 'applicable_scope', 'input_evidence']);
export const hashesSchema = object(Object.fromEntries(['input', 'extraction', 'assessment', 'rules', 'rubric', 'skill', 'a_result'].map(key => [key, { type: ['extraction','a_result'].includes(key)?['string','null']:'string', pattern: '^[a-f0-9]{64}$' }])));

export const explicitSchema = object({
    overall_score: { type: 'null' },
    metrics: dictionary(object({
      label: text, unit: nullableText, value: { anyOf: [{ type: 'string' }, { type: 'number' }, { type: 'null' }] },
      qualifier: { type: ['string', 'null'], enum: ['exact', 'lower_bound', 'approximate', null] },
      status: choice(['conflict', 'observed', 'not_observed']), verification: { type: 'string', const: 'material_report' },
      observations: array(fact),
    })),
    ledger: dictionary(dictionary(nullableNumber)),
    ledger_details: dictionary(object({
      coverage: choice(['complete', 'partial', 'not_reported']),
      declared_coverage: choice(['complete', 'partial', 'not_reported']), partial_source: { type: 'boolean' },
      counts: dictionary(object({
        listed: number, value: nullableNumber, qualifier: choice(['exact', 'lower_bound']),
        status: choice(['conflict', 'complete_listing', 'partial_listing', 'not_observed']),
      })), excluded_item_ids: array(text),
    })),
    item_conflicts: array(object({ kind: text, item_ids: array(text), statuses: array(choice(itemStatuses)), period_statuses: array(choice(['in_scope', 'out_of_scope', 'uncertain'])) })),
    potential_duplicates: array(object({ kind: text, item_ids: array(text), status: { type: 'string', const: 'needs_review' }, reason: text })),
    items: array(object({ kind: text, item_ids: array(text), records: array(item) })),
    checks: array(check), groups: array(object({ id: text, label: text, fields: array(text), item_kinds: array(text) })),
  });

// This schema describes buildPortrait's output and is shared by the HTTP boundary.
export const portraitSchema = object({
  schema_version: { type: 'string', const: '2.0' }, student_id: text,
  period: { type: ['string', 'null'] }, stage: choice(['annual', 'proposal']),
  run_id: { type: 'string', pattern: '^[a-f0-9]{64}$' }, review_status: { type: 'string', const: 'draft' },
  warnings: array(text), task_context: {anyOf:[taskContextSchema,{type:'null'}]},
  provenance: object({
    producer: object({
      mode: choice(['offline_replay', 'synthetic', 'assistant_curated', 'skill_execution', 'remote_model']),
      model: nullableText, description: nullableText,
    }),
    hashes: hashesSchema, versions: object({ schema: text, rules: text, rubric: text, skill: text }),
  }),
  sources: array(object({
    document_id: text, source_name: text, sha256: text,
    parse_status: choice(['complete', 'partial', 'failed']),
    pages: array(object({ segment_id: text, page: { type: ['integer', 'null'], minimum: 1 } })),
  })),
  explicit_extraction: {anyOf:[portraitExtractionSchema,{type:'null'}]},
  explicit: { anyOf: [explicitSchema, {type:'null'}] },
  explicit_status: choice(['pending','local_pipeline','merged']),
  a_handoff: { anyOf: [object({schema_version:text,output_version:text,generated_at:text,producer:object({mode:text,name:nullableText,model:nullableText}),material_fingerprints:array(object({document_id:text,sha256:text,content_sha256:text})),rules_version:text}), {type:'null'}] },

  implicit: object({
    rubric_version: text, status: text, interpretation: text,
    dimensions: array(object({
      id: text, label: text, criteria: array(criterion),
      summary: array(object({criterion_ids: array(text), text})), review_required: {const:true},
    })),
  }),
});

// Optional for compatibility with offline replay results created before synthesis.
portraitSchema.properties.synthesis=synthesisSchema;

portraitSchema.properties.synthesis_sources = array(object({
  id: text, kind: choice(['explicit', 'implicit']), label: text, pointer: text,
}));
