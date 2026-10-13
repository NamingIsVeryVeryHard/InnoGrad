import { readFileSync } from 'node:fs';

const root = new URL('../references/', import.meta.url);
const read = name => JSON.parse(readFileSync(new URL(name, root), 'utf8'));
const cite = quote => [{ document_id: 'annual-1', segment_id: 'body', quote }];

export function fixture() {
  const rubric = read('implicit-rubric.json');
  return {
    rules: read('explicit-rules.json'), rubric,
    bundle: {
      schema_version: '1.0', student_id: 'SYNTHETIC-001', period: '2025-2026', stage: 'annual',
      documents: [{
        document_id: 'annual-1', sha256: 'a'.repeat(64), source_name: '合成年报.txt', kind: 'annual',
        student_id: 'SYNTHETIC-001', period: '2025-2026', parse_status: 'complete',
        segments: [{ segment_id: 'body', page: null, text: '本年度发表论文3篇。逐项成果：A方法已发表；B方法已发表。研究问题是在小样本课堂数据中提高反馈准确性。' }],
      }],
    },
    extraction: {
      schema_version: '1.0', student_id: 'SYNTHETIC-001', period: '2025-2026', stage: 'annual',
      facts: [{ field: 'papers_reported', value: 3, qualifier: 'exact', numeric_token: '3', evidence: cite('本年度发表论文3篇。') }],
      items: [
        { item_id: 'a', kind: 'paper', title: 'A 方法', status: 'published', role: null, identifier: null, occurred_on: null, period_status: 'in_scope', evidence: cite('A方法已发表') },
        { item_id: 'b', kind: 'paper', title: 'B 方法', status: 'published', role: null, identifier: null, occurred_on: null, period_status: 'in_scope', evidence: cite('B方法已发表') },
      ],
      coverage: [{ kind: 'paper', status: 'complete', evidence: cite('逐项成果：A方法已发表；B方法已发表。') }],
    },
    assessment: {
      schema_version: '1.0', student_id: 'SYNTHETIC-001', period: '2025-2026', stage: 'annual', rubric_version: rubric.version,
      dimensions: rubric.dimensions.map((d, i) => ({
        dimension_id: d.id,
        criteria: d.criteria.map((c, j) => ({
          criterion_id: c.id, judgment: i === 0 && j === 0 ? 'supported' : 'not_observed',
          work_status: i === 0 && j === 0 ? 'planned' : 'unknown',
          rationale: i === 0 && j === 0 ? '指出小样本课堂反馈的具体问题。' : '材料未提供足够信息。',
          evidence: i === 0 && j === 0 ? cite('研究问题是在小样本课堂数据中提高反馈准确性。') : [],
          missing_evidence: i === 0 && j === 0 ? null : '需要对应条件的原文证据。',
        })),
      })),
    },
  };
}
