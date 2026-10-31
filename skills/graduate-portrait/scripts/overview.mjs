import {readFileSync} from 'node:fs';
import {validateShape, unique} from './validation.mjs';

export const overviewSchema = JSON.parse(readFileSync(
  new URL('../references/portrait-overview.schema.json', import.meta.url), 'utf8'));

export function validateOverview(value) {
  validateShape(overviewSchema, value, 'portrait overview');
  unique(value.scopes.map(s => s.scope_id), 'scope_id');
  unique(value.source_records.map(r => r.id), 'source record id');
  unique(value.evaluations.map(e => e.scope_id), 'evaluation scope');
  const scopes = new Set(value.scopes.map(s => s.scope_id));
  const sources = new Map(value.source_records.map(r => [r.id, r]));
  for (const record of value.source_records) {
    if (!scopes.has(record.scope_id)) throw Error('unknown source scope');
    if (!record.quote && !record.fields) throw Error('source record has no content');
  }
  const checkRefs = (item, scope) => {
    for (const id of item.source_refs) {
      const source = sources.get(id);
      if (!source) throw Error('unknown source reference');
      if (scope && source.scope_id !== scope) throw Error('evaluation source scope mismatch');
    }
  };
  for (const items of Object.values(value.overview)) for (const item of items) checkRefs(item);
  for (const evaluation of value.evaluations) {
    if (!scopes.has(evaluation.scope_id)) throw Error('unknown evaluation scope');
    unique(evaluation.criteria.map(c => c.criterion_id), 'criterion_id');
    for (const criterion of evaluation.criteria) {
      checkRefs(criterion, evaluation.scope_id);
      if (criterion.performance_grade !== null && !criterion.source_refs.length) {
        throw Error('graded criterion has no evidence');
      }
      if (criterion.performance_grade !== null &&
          !['evaluable', '可评价'].includes(criterion.evidence_state)) {
        throw Error('insufficient or conflicting evidence cannot receive a grade');
      }
      if (value.completion && (!criterion.rationale || !criterion.grading_standard ||
          !criterion.dimension_id || !criterion.dimension_label)) {
        throw Error('criterion is missing grading rationale or standard');
      }
    }
  }
  if (value.completion === 'complete' && (!scopes.size || value.scopes.some(scope => {
    const evaluation = value.evaluations.find(e => e.scope_id === scope.scope_id);
    return !evaluation?.explicit || !evaluation.criteria.length;
  }))) {
    throw Error('complete portrait requires explicit results and implicit evaluations');
  }
  if (value.completion && (value.completion === 'not_generated') !==
      ['identity_conflict', 'missing_input'].includes(value.status)) {
    throw Error('portrait completion does not match generation status');
  }
  if (value.status === 'unchanged' && value.overview.changes.length) throw Error('unchanged portrait has changes');
  if (['identity_conflict', 'missing_input'].includes(value.status) &&
      (Object.values(value.overview).some(items => items.length) || value.evaluations.length)) {
    throw Error('input issue cannot produce a portrait');
  }
  return value;
}

export function criterionEvidenceHistory(value, {currentScopeId}) {
  validateOverview(value);
  if (!value.scopes.some(scope => scope.scope_id === currentScopeId)) {
    throw Error('unknown current scope');
  }
  const items = new Map();
  for (const evaluation of value.evaluations) {
    for (const criterion of evaluation.criteria) {
      if (!items.has(criterion.criterion_id)) {
        items.set(criterion.criterion_id, {
          criterion_id: criterion.criterion_id, label: criterion.label,
          dimension_id: criterion.dimension_id, dimension_label: criterion.dimension_label,
          current: null, records: [], graded: [], status: 'ungraded',
        });
      }
      const item = items.get(criterion.criterion_id);
      const record = {scope_id: evaluation.scope_id,
        rubric_version: evaluation.rubric_version, criterion};
      item.records.push(record);
      if (evaluation.scope_id === currentScopeId) item.current = criterion;
      if (criterion.performance_grade !== null) item.graded.push(record);
    }
  }
  // Preserve task-specific judgments; a missing annual observation does not revoke a proposal judgment.
  for (const item of items.values()) {
    item.status = item.current?.performance_grade != null ? 'current_graded'
      : item.graded.length ? 'historical_graded' : 'ungraded';
  }
  return [...items.values()];
}
