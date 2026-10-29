const text = {type: 'string', minLength: 1, pattern: '\\S'};
const refs = {type: 'array', items: text, minItems: 1};
const object = properties => ({
  type: 'object', properties, required: Object.keys(properties), additionalProperties: false,
});
const list = items => ({type: 'array', items});
const observation = object({
  status: {enum: ['documented', 'unknown']},
  value: {anyOf: [text, {type: 'null'}]},
  source_refs: list(text),
});
export const responseSchema = object({
  facts: list(object({
    kind: {enum: ['background', 'progress', 'plan', 'condition']},
    work_status: {enum: ['planned', 'reported_completed', 'unknown']},
    text, source_refs: refs,
  })),
  intent: object({
    goal: observation, attitude: observation, subjective_norm: observation,
    perceived_behavioral_control: observation,
  }),
  task_conditions: object({progress: observation, resources: observation, deadlines: observation}),
  relevant_history: list(object({
    material_id: text, relation: {const: 'related'}, text, source_refs: refs,
  })),
  gaps: list(object({text, needed_evidence: text, source_refs: refs})),
  guidance: {...list(object({
    action: text, why: text, completion_evidence: text,
    uncertainty: list(text), source_refs: refs,
  })), minItems: 1, maxItems: 3},
  unknowns: list(text),
});
const material = object({
  material_id: text, stage: {type: ['string', 'null']}, period: {type: ['string', 'null']},
});
export const resultSchema = object({
  schema_version: {const: 'research-guidance-1.0'}, status: {const: 'generated'},
  scope: object({
    student_id: {type: ['string', 'null']}, current: material,
    history: list(material), chronology: {const: 'unknown'},
  }),
  ...responseSchema.properties,
  source_index: {...list(object({
    id: text, quote: text, source_id: text,
    start_char: {type: 'integer', minimum: 0}, end_char: {type: 'integer', minimum: 1},
    material_id: text, document_id: text, segment_id: text,
    document: text, page: {type: ['integer', 'null'], minimum: 1},
    document_sha256: {type: ['string', 'null']},
  })), minItems: 1},
  provenance: object({
    platform: {const: 'InnoAgent'}, session_ids: {...list(text), minItems: 1},
    installed_skill_hashes: object({'graduate-research-guidance': {type: 'string', pattern: '^[a-f0-9]{64}$'}}),
    provider: text, requested_model: text, actual_model: {type: ['string', 'null']},
    attempts: {type: 'integer', minimum: 1}, model_called: {const: true},
    records: list(object({
      provider: text, requested_model: text, actual_model: {type: ['string', 'null']},
      attempt: {type: 'integer', minimum: 1}, status: text,
    })),
  }),
});
