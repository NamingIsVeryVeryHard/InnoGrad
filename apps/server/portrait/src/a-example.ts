import { readFileSync } from 'node:fs';
import { buildAResult } from '../skill-bridge.mjs';
import type { AResult, EvidenceRef, Extraction, ParsedMaterialBundle } from './contracts.js';

// Use the complete annual report already shown in Swagger; this adds no student text.
export function buildAnnualAExample(bundle: ParsedMaterialBundle): AResult {
  const rules = JSON.parse(readFileSync(new URL('../../../../.agents/skills/graduate-portrait/references/explicit-rules.json', import.meta.url), 'utf8'));
  const cite = (quote: string): EvidenceRef[] => [{ document_id: 'synthetic-annual-report', segment_id: 'annual-page-2', quote }];
  const extraction: Extraction = {
    schema_version: '1.0', student_id: bundle.student_id, period: bundle.period, stage: bundle.stage,
    facts: [{ field: 'papers_reported', value: 1, qualifier: 'exact', numeric_token: '一', evidence: cite('论文方面，本年度正式发表一篇：') }],
    items: [
      {
        item_id: 'annual-published-paper', kind: 'paper', title: '协作任务中的证据追踪框架初探', status: 'published',
        role: '第二作者；整理编码手册和复核例句', identifier: null, occurred_on: null, period_status: 'in_scope',
        evidence: cite('本年度正式发表一篇：《协作任务中的证据追踪框架初探》，发表于《澄湾学习过程研究》2028年第2期。我为第二作者，负责整理编码手册和复核例句，第一作者负责主要方法设计。'),
      },
      {
        item_id: 'annual-submitted-paper', kind: 'paper', title: '任务修订前后的理由衔接模式', status: 'under_review',
        role: '第一作者', identifier: null, occurred_on: '2028-07', period_status: 'in_scope',
        evidence: cite('第一作者论文《任务修订前后的理由衔接模式》于2028年7月投稿，目前仍在审稿，尚未收到录用通知。'),
      },
      {
        item_id: 'annual-accepted-paper', kind: 'paper', title: '探究片段的上下文标注方法', status: 'accepted',
        role: '第三作者；试标注材料整理', identifier: null, occurred_on: '2028-08', period_status: 'in_scope',
        evidence: cite('另一篇合作论文《探究片段的上下文标注方法》已于2028年8月收到《学习记录与方法》的录用通知，尚未见刊；我为第三作者，主要承担试标注材料整理。'),
      },
      {
        item_id: 'annual-draft-paper', kind: 'paper', title: '标注分歧处理工作稿', status: 'in_progress',
        role: null, identifier: null, occurred_on: null, period_status: 'in_scope',
        evidence: cite('关于标注分歧处理的工作稿仍在写作，尚未投稿。'),
      },
    ],
    coverage: [{
      kind: 'paper', status: 'partial',
      evidence: cite('本次材料只附年度总结，论文出版信息、录用邮件与作者贡献记录尚待补齐。'),
    }],
  };
  return buildAResult({
    bundle, extraction, rules,
    metadata: {
      output_version: 'synthetic-a-example-1.0',
      generated_at: '2028-09-06T00:00:00Z',
      producer: { mode: 'synthetic', name: 'Swagger 全虚构 A 交接示例', model: null },
    },
  });
}
