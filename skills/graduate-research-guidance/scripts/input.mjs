import {readFile} from 'node:fs/promises';
import {basename, resolve} from 'node:path';
import {createHash} from 'node:crypto';

const fail = message => { throw new Error(message); };
const nonempty = value => typeof value === 'string' && Boolean(value.trim());
const unique = values => new Set(values).size === values.length;

function citationRanges(text) {
  const ranges = [];
  let start = 0, end = 0;
  const append = () => {
    while (start < end && /\s/u.test(text[start])) start++;
    while (end > start && /\s/u.test(text[end - 1])) end--;
    if (end > start) ranges.push([start, end]);
  };
  // Keep sentences intact, including a long sentence; offsets address the original JS string.
  for (const part of new Intl.Segmenter('zh', {granularity: 'sentence'}).segment(text)) {
    const next = part.index + part.segment.length;
    if (end > start && next - start > 600) {
      append();
      start = part.index;
    }
    end = next;
  }
  append();
  return ranges;
}

export async function loadContext({current, history = [], portrait}) {
  const report = async path => {
    const raw = await readFile(resolve(path), 'utf8');
    if (path.endsWith('.json')) return JSON.parse(raw);
    return {text: raw, source: basename(path)};
  };
  return prepareContext({
    current: await report(current),
    history: await Promise.all(history.map(report)),
    portrait: portrait ? JSON.parse(await readFile(resolve(portrait), 'utf8')) : null,
  });
}

export function prepareContext({current, history = [], portrait = null}) {
  const sources = [], groups = [current, ...history].map((input, index) => {
    const material_id = index ? `history-${index}` : 'current';
    let value = input?.bundle ?? input;
    if (nonempty(value?.text)) value = {student_id: null, stage: null, period: null,
      documents: [{document_id: 'text', source_name: value.source ?? 'report.txt',
        segments: [{segment_id: 'text', page: null, text: value.text}]}]};
    if (!Array.isArray(value?.documents) || !value.documents.length) fail('empty report');
    const student_id = value.student_id ?? null;
    if (student_id !== null && !nonempty(student_id)) fail('invalid student identity');
    const group = {material_id, stage: value.stage ?? null, period: value.period ?? null};
    const docIds = value.documents.map(d => d.document_id);
    if (!docIds.every(nonempty) || !unique(docIds)) fail('invalid document identifiers');
    for (const doc of value.documents) {
      if (doc.parse_status === 'failed' ||
          (doc.student_id !== undefined && doc.student_id !== student_id) ||
          (doc.period !== undefined && doc.period !== group.period)) fail('document scope mismatch');
      const state = value.input_context?.sources?.find(s => s.document_id === doc.document_id);
      if (state?.authorization === 'denied' ||
          ['withdrawn', 'superseded', 'disputed'].includes(state?.validity)) fail('unavailable source');
      if (!Array.isArray(doc.segments) || !doc.segments.length) fail('empty document');
      const segmentIds = doc.segments.map(s => s.segment_id);
      if (!segmentIds.every(nonempty) || !unique(segmentIds)) fail('invalid segment identifiers');
      let count = 0;
      for (const segment of doc.segments) {
        if (typeof segment.text !== 'string') fail('invalid segment text');
        if (!segment.text.trim()) continue;
        if (segment.page != null && (!Number.isInteger(segment.page) || segment.page < 1)) fail('invalid page');
        count++;
        const version = createHash('sha256').update(segment.text).digest('hex');
        const source_id = [material_id, doc.document_id, segment.segment_id, version].map(encodeURIComponent).join(':');
        for (const [start_char, end_char] of citationRanges(segment.text)) sources.push({
          id: `C${sources.length + 1}`, source_id, start_char, end_char,
          material_id, document_id: doc.document_id, segment_id: segment.segment_id,
          document: doc.source_name ?? doc.document_id, page: segment.page ?? null,
          document_sha256: doc.sha256 ?? null, text: segment.text.slice(start_char, end_char),
        });
      }
      if (!count) fail('empty document text');
    }
    return {group, student_id, bundle: value};
  });
  const students = new Set(groups.map(g => g.student_id).filter(id => id !== null));
  if (students.size > 1) fail('student identity conflict');
  // Explicitly paired unidentified text remains unidentified; filenames never establish identity.
  const student_id = groups[0].student_id;
  if (portrait) {
    if (!student_id || portrait.student_id !== student_id) fail('portrait identity conflict');
    if (portrait.stage !== groups[0].group.stage || portrait.period !== groups[0].group.period) fail('portrait scope mismatch');
    for (const source of portrait.sources ?? []) {
      const doc = groups[0].bundle.documents.find(d => d.document_id === source.document_id);
      if (!doc || (source.sha256 && source.sha256 !== doc.sha256)) fail('portrait source version mismatch');
    }
  }
  return {scope: {student_id, current: groups[0].group,
    history: groups.slice(1).map(g => g.group), chronology: 'unknown'}, sources, portrait};
}
