import { buildAnnualAExample } from './a-example.js';
import { readFileSync } from 'node:fs';
import { validateBundle } from '../skill-bridge.mjs';
import type { ParsedMaterialBundle } from './contracts.js';

function readExample(file: string): { bundle: ParsedMaterialBundle } {
  const request = JSON.parse(readFileSync(new URL(`../examples/${file}`, import.meta.url), 'utf8'));
  validateBundle(request.bundle);
  return request;
}

const annual = readExample('annual-report.synthetic.json');

export const portraitExamples = {
  annualReport: {
    summary: '全虚构博士年报：总结、成果状态与下一学年计划',
    description: '全虚构合成文本，无原始 PDF；4 个模拟页。sha256 为各页原文以换页符连接后的 UTF-8 字节哈希，不是 PDF 哈希。含本期与累计数量、发表/录用未见刊/审稿/写作状态、作者角色、交流记录及未勾选评定意见。',
    value: annual,
  },
  proposalReport: {
    summary: '全虚构开题报告：研究问题、方法、风险与进度',
    description: '全虚构合成文本，无原始 PDF；6 个模拟页。sha256 为各页原文以换页符连接后的 UTF-8 字节哈希。period 为 null，表示未确认统计学年；计划不代表完成，评审与签章均留空。',
    value: readExample('proposal-report.synthetic.json'),
  },
  annualWithAResult: {
    summary: '全虚构年度报告与 A 显性结果交接',
    description: '沿用 annualReport 的完整全虚构报告，附上合成 A 结果；显性规则保持待配置或待复核。generated_at 为示例固定时间，producer.mode 为 synthetic，不是当前时间或真实 A 运行记录。传入 aResult 后只执行 B 的评价。',
    value: { bundle: annual.bundle, aResult: buildAnnualAExample(annual.bundle) },
  },
};
