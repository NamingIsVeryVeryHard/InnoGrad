import {portraitSources} from './synthesis.mjs';
const text=value=>String(value??'材料未提供').replaceAll('|','\\|').replace(/\r?\n/g,' ');
const labels={explicit_pending:'显性结果待接入',applicable:'标准适用',pending_confirmation:'评价标准待确认',evaluable:'可评价',insufficient:'证据不足',conflicting:'证据冲突',needs_improvement:'待改进',meets_requirements:'达到要求',well_demonstrated:'表现充分',self_report:'报告自述',mixed:'直接展示与自述并存',planned:'计划',in_progress:'进行中',under_review:'在审',accepted:'已录用',published:'已发表',completed:'已完成',unknown:'未确认',in_scope:'本期',out_of_scope:'非本期',uncertain:'期间待确认',supported:'有证据支持',contradicted:'有反证',not_observed:'未见足够证据',observed:'材料记载',conflict:'存在冲突',complete:'完整',partial:'部分覆盖',failed:'解析失败',met:'达到配置值',not_met:'未达到配置值',pending_rule:'规则待配置',needs_review:'待复核',insufficient_evidence:'证据不足',not_applicable:'不适用',consistent:'记录一致',period_unconfirmed:'期间待确认',draft:'待复核草稿',complete_listing:'完整清单',partial_listing:'部分清单',lower_bound:'至少',approximate:'约'};
const label=value=>labels[value]??value;
function number(value,qualifier,unit){if(value===null)return '材料未提供';return (qualifier&&qualifier!=='exact'?label(qualifier)+' ':'')+text(value)+(unit?' '+text(unit):'');}
export function renderPortrait(p) {
 const source=e=>{const d=p.sources.find(s=>s.document_id===e.document_id);const page=d?.pages.find(s=>s.segment_id===e.segment_id)?.page;return text(d?.source_name??e.document_id)+' / '+(page?'第'+page+'页':'段 '+text(e.segment_id))+'；“'+text(e.quote)+'”';};
 const lines=['# 研究生画像草稿','', '学生：'+text(p.student_id)+'；期间：'+(p.period===null?'期间待确认':text(p.period))+'；阶段：'+(p.stage==='annual'?'年度报告':'开题报告'),'', '状态：待人工复核。材料记载和自述未经独立验证。显性结果沿用上游口径；科研能力与研究素养初评使用项目试用标准，领域不定级。','', '生成方式：'+text(p.provenance.producer.mode)+'；运行标识：'+p.run_id];
 if(p.warnings.length)lines.push('','待确认：'+p.warnings.map(label).join('、'));
 if(p.synthesis){
  lines.push('','## 画像概览','');
  for(const [key,title]of [['current_work','当前研究与进展'],['demonstrated','材料中已呈现的表现'],['attention','需要关注的事项'],['next_steps','下一步行动']]){
   lines.push('### '+title,'');
   if(!p.synthesis[key].length)lines.push('当前结果没有提供足够依据。');
   for(const item of p.synthesis[key])lines.push('- '+text(item.text)+' '+item.source_refs.map(id=>'['+id+'](#source-'+id.toLowerCase()+')').join('、')+(item.completion_evidence?'；建议形成的核查材料：'+text(item.completion_evidence):''));
   lines.push('');
  }
  lines.push('未作跨期成长比较；以下保留完整评价与来源。');
 }
 function fact(id){const m=p.explicit.metrics[id];lines.push('- '+text(m.label)+'：'+number(m.value,m.qualifier,m.unit)+'；'+label(m.status));for(const o of m.observations){if(m.status==='conflict')lines.push('  冲突记录：'+number(o.value,o.qualifier,m.unit));for(const e of o.evidence)lines.push('  出处：'+source(e));}}
 if(p.explicit){
 const grouped=new Set(p.explicit.groups.flatMap(g=>g.fields));lines.push('','## 基础记录','');for(const id of Object.keys(p.explicit.metrics).filter(id=>!grouped.has(id)))fact(id);
 lines.push('','## 显性记录','');for(const g of p.explicit.groups){lines.push('### '+text(g.label),'');for(const id of g.fields)fact(id);const groups=p.explicit.items.filter(i=>g.item_kinds.includes(i.kind));if(!groups.length)lines.push('材料未提供逐项记录。');for(const item of groups)for(const r of item.records){lines.push('- '+text(r.title)+'：'+label(r.status)+'；'+label(r.period_status)+(r.occurred_on?'；日期 '+text(r.occurred_on):'')+(r.role?'；角色 '+text(r.role):''));for(const e of r.evidence)lines.push('  出处：'+source(e));}lines.push('');}
 lines.push('## 本期数量汇总','','| 类别 | 状态 | 本期列明项 | 数量解释 |','|---|---|---|---|');for(const [kind,d]of Object.entries(p.explicit.ledger_details))for(const [status,c]of Object.entries(d.counts))if(c.listed||c.status==='conflict')lines.push('| '+kind+' | '+label(status)+' | '+c.listed+' | '+label(c.status)+(d.partial_source?'；材料部分覆盖':'')+' |');
 lines.push('','未列明不表示实际零；计划、非本期和期间待确认记录保留在上方，本期完成数量不包含这些记录。');for(const c of p.explicit.potential_duplicates)lines.push('- 同名记录待核对：'+c.item_ids.map(text).join('、')+'。'+c.reason);
 lines.push('','## 规则检查','');for(const c of p.explicit.checks)lines.push('- '+text(c.label)+'：'+label(c.status)+(c.self_report!==undefined?'（自报 '+c.self_report+'；逐项 '+c.listed+'）':'')+(c.interpretation?'；'+c.interpretation:''));
 }else{lines.push('','## 显性结果','','显性结果待接入，当前包含科研能力与研究素养初评。');}
 lines.push('','## 隐性材料评价','','量规版本：'+text(p.implicit.rubric_version)+'；'+text(p.implicit.interpretation),'');for(const d of p.implicit.dimensions){lines.push('### '+text(d.label),'');for(const c of d.criteria){lines.push('', '- '+text(c.criterion_label)+'：'+label(c.evidence_state)+'；'+label(c.standard_status)+'；表现等级 '+(c.performance_grade===null?'暂缓':label(c.performance_grade))+'；'+label(c.work_status)+'。'+text(c.observed),'  判断：'+text(c.rationale),'  证据性质：'+label(c.evidence_nature)+'；个人贡献 '+text(c.contribution.individual)+'；教师复核待完成。');for(const gap of c.missing_evidence)lines.push('  缺失证据：'+text(gap));for(const e of c.evidence)lines.push('  出处：'+source(e)+'；支持：'+text(e.supports)+'；文件哈希 '+e.sha256);for(const l of c.limitations)lines.push('  限制：'+text(l));for(const advice of c.suggestions)lines.push('  建议：'+text(advice));}}
 if(p.synthesis){
  lines.push('','## 概览引用索引','');
  const used=new Set(Object.values(p.synthesis).flatMap(items=>items.flatMap(item=>item.source_refs)));
  for(const record of portraitSources(p).filter(record=>used.has(record.id))){
   lines.push('<a id="source-'+record.id.toLowerCase()+'"></a>','', '### '+record.id+' · '+text(record.label),'');
   const c=record.content;
   if(record.kind==='implicit'){
    lines.push(text(c.observed),'', '原评价：'+label(c.evidence_state)+'；'+(c.performance_grade===null?'暂缓定级':label(c.performance_grade))+'。'+text(c.rationale));
    for(const gap of c.missing_evidence)lines.push('- 待补：'+text(gap));
   }else if(c.observations){lines.push('上游记录：'+number(c.value,c.qualifier,c.unit)+'；'+label(c.status));}
   else if(c.kind&&c.input_evidence){lines.push('上游检查：'+label(c.status)+'；规则 '+text(c.rule_version));}
   else lines.push('上游记录：'+text(c.title)+'；'+label(c.status)+'；'+label(c.period_status));
   const refs=c.evidence??c.input_evidence??c.observations?.flatMap(o=>o.evidence)??[];
   for(const e of refs)lines.push('- 原文：'+source(e)+(e.supports?'；支持：'+text(e.supports):''));
   if(!refs.length)lines.push('该源结果没有提供原文引用；缺口及建议仅依据原评价记录。');
   lines.push('');
  }
 }
 lines.push('','## 来源覆盖','');for(const s of p.sources)lines.push('- '+text(s.source_name)+'：'+label(s.parse_status)+'；'+s.pages.length+'段；原始文件哈希由上游提供。');return lines.join('\n')+'\n';
}
