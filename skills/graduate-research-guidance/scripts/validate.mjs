#!/usr/bin/env node
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {parseArgs, isDeepStrictEqual} from 'node:util';
import {validateShape} from '../../graduate-portrait/scripts/validation.mjs';
import {responseSchema, resultSchema} from './schema.mjs';
import {loadContext} from './input.mjs';

function invalid(path, category) {
  const error = new Error(`invalid source or output at ${path}: ${category}`);
  error.validation_issues = [{path, category}];
  throw error;
}
export function referencedIds(value) {
  const ids = new Set();
  function visit(item) {
    if (!item || typeof item !== 'object') return;
    if (Array.isArray(item.source_refs)) for (const id of item.source_refs) ids.add(id);
    for (const child of Object.values(item)) visit(child);
  }
  visit(value);
  return [...ids];
}

export function validateGuidance(value, context, {modelResponse = false} = {}) {
  validateShape(modelResponse ? responseSchema : resultSchema, value, 'guidance schema');
  const catalog = context && new Map(context.sources.map(s => [s.id, s]));
  const sources = modelResponse ? catalog : new Map();
  if (!sources) throw new Error('model validation requires input context');
  for (const [i, entry] of (modelResponse ? [] : value.source_index).entries()) {
    const path = `/source_index/${i}`;
    if (sources.has(entry.id)) invalid(path, 'DUPLICATE_IDENTIFIER');
    sources.set(entry.id, entry);
    if (catalog) {
      const source = catalog.get(entry.id);
      if (!source) invalid(path, 'EVIDENCE_LOCATION');
      if (entry.quote !== source.text) invalid(path, 'QUOTE_NOT_IN_SEGMENT');
      for (const key of ['source_id', 'start_char', 'end_char', 'material_id', 'document_id', 'segment_id', 'document', 'page', 'document_sha256']) {
        if (entry[key] !== source[key]) invalid(path + '/' + key, 'SOURCE_METADATA');
      }
    }
  }
  if (!modelResponse && context && !isDeepStrictEqual(value.scope, context.scope)) invalid('/scope', 'SCOPE_MISMATCH');
  if (!modelResponse && referencedIds(value).length !== sources.size) invalid('/source_index', 'SOURCE_COVERAGE');
  const scope = context?.scope ?? value.scope;
  const checkRefs = (item, path) => {
    if (!item.source_refs.length) invalid(path, 'EVIDENCE_REQUIRED');
    for (const ref of item.source_refs) if (!sources.has(ref)) invalid(path, 'EVIDENCE_LOCATION');
  };
  for (const section of ['facts', 'relevant_history', 'gaps', 'guidance']) {
    for (const [i, item] of value[section].entries()) checkRefs(item, `/${section}/${i}/source_refs`);
  }
  for (const section of ['intent', 'task_conditions']) for (const [key, item] of Object.entries(value[section])) {
    const path = `/${section}/${key}`;
    if (item.status === 'unknown') {
      if (item.value !== null || item.source_refs.length) invalid(path, 'UNKNOWN_WITH_CLAIM');
    } else {
      if (item.value === null) invalid(path, 'DOCUMENTED_WITHOUT_VALUE');
      checkRefs(item, path + '/source_refs');
    }
  }
  for (const [i, item] of value.facts.entries()) {
    if ((item.kind === 'plan' && item.work_status !== 'planned') ||
        (item.work_status === 'reported_completed' && item.kind !== 'progress')) invalid(`/facts/${i}`, 'WORK_STATUS');
  }
  for (const [i, item] of value.relevant_history.entries()) {
    if (!scope.history.some(m => m.material_id === item.material_id) ||
        item.source_refs.some(id => (catalog?.get(id) ?? sources.get(id)).material_id !== item.material_id)) {
      invalid(`/relevant_history/${i}`, 'HISTORY_SCOPE');
    }
  }
  return value;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const {values, positionals} = parseArgs({allowPositionals: true, options: {
      current: {type: 'string'}, history: {type: 'string', multiple: true}, portrait: {type: 'string'},
    }});
    if (positionals.length !== 1 || !values.current) throw new Error('usage: validate.mjs RESULT --current REPORT [--history REPORT] [--portrait PORTRAIT]');
    const context = await loadContext(values);
    validateGuidance(JSON.parse(await readFile(positionals[0], 'utf8')), context);
    console.log('valid: schema, scope, source metadata, offsets and exact source text');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
