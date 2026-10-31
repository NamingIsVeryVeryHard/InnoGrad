// Fictional records for boundary tests; never presented as a real student case.
export function fixture() {
  const make = (id, role) => {
    const current = role === 'current';
    const quote = current ? '方案已列出测试集、基线和指标。' : '计划验证方案效果。';
    const goal = '研究目标：检验一种方案。';
    const hash = (current ? 'b' : 'a').repeat(64);
    const bundle = {
      schema_version: '1.0', student_id: 'FIXTURE-001', stage: current ? 'proposal' : 'annual',
      period: current ? null : '2000-2001',
      documents: [{ document_id: id, student_id: 'FIXTURE-001', sha256: hash,
        segments: [{ segment_id: 's1', page: 1, text: `${goal}\n${quote}` }] }],
    };
    const evidence = [{ document_id: id, segment_id: 's1', quote, page: 1, sha256: hash }];
    const criterion = {
      criterion_id: 'validation-design', criterion_label: '验证设计',
      evidence_state: current ? 'evaluable' : 'insufficient',
      performance_grade: current ? 'meets_requirements' : null,
      work_status: 'planned', rationale: current ? '方案设计条件已呈现。' : '材料条件不足。',
      observed: quote, evidence, limitations: ['只评价方案设计，不评价执行结果。'],
      missing_evidence: current ? ['数据划分办法'] : ['测试集、基线和指标'],
      suggestions: current ? ['补充数据划分办法。'] : ['先列出测试集、基线和指标。'],
    };
    const portrait = {
      schema_version: '2.0', student_id: bundle.student_id, stage: bundle.stage, period: bundle.period,
      sources: [{ document_id: id, sha256: hash, pages: [{ segment_id: 's1', page: 1 }] }],
      provenance: { producer: { mode: 'synthetic', model: null } },
      implicit: { rubric_version: 'fixture-v1', dimensions: [{ id: 'design', label: '研究设计', criteria: [criterion] }] },
      synthesis_sources: [{ id: 'R1', kind: 'implicit', label: '验证设计', pointer: '/implicit/dimensions/0/criteria/0' }],
      synthesis: {
        current_work: [{ text: quote, source_refs: ['R1'] }], demonstrated: [], attention: [],
        next_steps: [{ text: criterion.suggestions[0], source_refs: ['R1'], completion_evidence: criterion.missing_evidence[0] }],
      },
    };
    return { id, role, bundle, portrait };
  };
  return {
    manifest: { schema_version: 'portrait-history-real-1', student_id: 'FIXTURE-001',
      data_nature: 'test_fixture', focus_criteria: ['validation-design'],
      selected: { current_goal: { material_id: 'current', document_id: 'current', segment_id: 's1', quote: '研究目标：检验一种方案。' } } },
    materials: [make('reference', 'reference'), make('current', 'current')],
  };
}
