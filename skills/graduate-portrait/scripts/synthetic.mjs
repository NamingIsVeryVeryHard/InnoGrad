import { readFileSync } from 'node:fs';

const root = new URL('../references/', import.meta.url);
const read = name => JSON.parse(readFileSync(new URL(name, root), 'utf8'));
const cite = quote => [{ document_id: 'annual-1', segment_id: 'body', quote }];

export function fixture() {
  const rubric = JSON.parse(readFileSync(new URL('../../graduate-implicit-assessment/references/implicit-rubric.json', import.meta.url), 'utf8'));
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
      schema_version: '2.0', student_id: 'SYNTHETIC-001', period: '2025-2026', stage: 'annual', rubric_version: rubric.version,
      dimensions: rubric.dimensions.map(d => ({
        dimension_id: d.id,
        criteria: d.criteria.map(c => ({
          criterion_id: c.id, evidence_state: c.id === 'problem-definition' ? 'evaluable' : 'insufficient',
          performance_grade: c.id === 'problem-definition' ? 'meets_requirements' : null,
          standard_status: 'applicable', work_status: c.id === 'problem-definition' ? 'planned' : 'unknown',
          observed: c.id === 'problem-definition' ? '材料界定了小样本课堂反馈准确性的研究问题。' : '未定位到本项所需表现。',
          rationale: c.id === 'problem-definition' ? '对象、情境和目标具体，按试用问题界定标准初评。' : '缺少对应任务表现与依据，暂不评级。',
          evidence: c.id === 'problem-definition' ? cite('研究问题是在小样本课堂数据中提高反馈准确性。').map(e => ({ ...e, supports: '支持研究对象、情境与目标。' })) : [],
          evidence_nature: c.id === 'problem-definition' ? 'observed' : 'unknown',
          contribution: { individual: null, guidance: null, tools: null },
          limitations: ['仅描述报告中的表现，独立贡献与效果未经核验。'],
          missing_evidence: c.id === 'problem-definition' ? [] : ['需要本观察项对应的具体原文。'],
          suggestions: ['按当前任务补充可定位材料并请教师复核。'],
        })),
      })),
    },
  };
}
