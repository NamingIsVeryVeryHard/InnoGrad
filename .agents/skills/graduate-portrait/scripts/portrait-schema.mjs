import { evidenceSchema, itemStatuses } from './schema.mjs';

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
const criterion = object({
  criterion_id: text, judgment: choice(['supported', 'contradicted', 'not_observed']),
  work_status: choice(['planned', 'in_progress', 'completed', 'unknown']), rationale: text,
  evidence, missing_evidence: nullableText,
});
const check = object({
  id: text, label: text, kind: choice(['minimum', 'consistency', 'material_comparison']),
  source: nullableText, metric: text,
  status: choice(['not_applicable', 'period_unconfirmed', 'pending_rule', 'needs_review', 'insufficient_evidence', 'met', 'not_met', 'consistent']),
  threshold: nullableNumber, observed: nullableNumber, qualifier,
  reference: nullableNumber, interpretation: text, self_report: number, listed: number,
  listing_coverage: choice(['complete', 'partial', 'not_reported']),
}, ['id', 'label', 'kind', 'source', 'metric', 'status']);
const hashes = object(Object.fromEntries(['input', 'extraction', 'assessment', 'rules', 'rubric', 'skill'].map(key => [key, { type: 'string', pattern: '^[a-f0-9]{64}$' }])));

// This schema describes buildPortrait's output and is shared by the HTTP boundary.
export const portraitSchema = object({
  schema_version: { type: 'string', const: '1.0' }, student_id: text,
  period: { type: ['string', 'null'] }, stage: choice(['annual', 'proposal']),
  run_id: { type: 'string', pattern: '^[a-f0-9]{64}$' }, review_status: { type: 'string', const: 'draft' },
  warnings: array(text),
  provenance: object({
    producer: object({
      mode: choice(['offline_replay', 'synthetic', 'assistant_curated', 'skill_execution', 'remote_model']),
      model: nullableText, description: nullableText,
    }),
    hashes, versions: object({ schema: text, rules: text, rubric: text, skill: text }),
  }),
  sources: array(object({
    document_id: text, source_name: text, sha256: text,
    parse_status: choice(['complete', 'partial', 'failed']),
    pages: array(object({ segment_id: text, page: { type: ['integer', 'null'], minimum: 1 } })),
  })),
  explicit: object({
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
  }),
  implicit: object({
    rubric_version: text, status: text, interpretation: text, overall_score: { type: 'null' },
    dimensions: array(object({
      id: text, label: text, level: { type: ['integer', 'null'], minimum: 1 }, level_label: nullableText,
      status: choice(['supported', 'contradicted', 'insufficient_evidence']), criteria: array(criterion),
      unmet_criteria: array(text), review_required: { type: 'boolean', const: true },
    })),
  }),
});
