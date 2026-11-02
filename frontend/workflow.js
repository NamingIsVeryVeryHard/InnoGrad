const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n};
const labels={queued:'排队中',running:'执行中',succeeded:'已完成',failed:'失败',cancelled:'已取消',pending:'待管理处理',opened:'更正进行中',rejected:'申请已驳回',completed:'更正已完成'};
const conclusions={compliant:'符合',non_compliant:'不符合',unable_to_determine:'无法判断',not_applicable:'不适用'};
const factLabels={title:'论文标题',publication_status:'申报状态',submission_date:'投稿日期',acceptance_date:'录用日期',publication_date:'发表日期',contribution:'本人贡献',summary:'年度总结'};
export function renderPortrait(data){
 const section=el('section',null,'version');section.dataset.testid='evidence-portrait';
 section.append(el('h3','证据型成长画像'),el('p',data.notice,'muted'),el('p','能力评价：'+data.ability_assessment));
 section.append(el('p','有效论文申报记录 '+data.counts.paper_records+' · 年度记录 '+data.counts.annual_records));
 if(data.pending_snapshot_count)section.append(el('p','有 '+data.pending_snapshot_count+' 份历史档案尚未生成画像快照，请联系维护人员。'));
 if(!data.records.length)section.append(el('p','暂无画像快照；材料通过人工复核并归档后更新。'));
 for(const record of data.records){const item=el('details');item.append(el('summary',(record.kind==='paper'?'论文申报':'年度材料')+' · 版本 '+record.version_number+' · '+(record.period||'未标注学年')));
 item.append(el('p','画像规则 '+record.rule_version+' · 材料规则 '+(record.requirements.version||'未标注')));
 for(const fact of record.facts)item.append(el('p',(factLabels[fact.field]||fact.field)+'：'+fact.value),el('small','来源版本 '+fact.source.version_id+' '+fact.source.pointer));
 for(const file of record.files){const p=el('p'),link=el('a','查看证据原件：'+file.name);link.href='/api/v1/files/'+encodeURIComponent(file.file_id)+'/download';link.target='_blank';link.rel='noopener';p.append(link);item.append(p)}
 item.append(el('p',record.limitation,'muted'));section.append(item)}
 return section;
}
export async function enhanceRecord({record:r,box,me,people,api,refresh,message,guard}){
 if(r.effective_archive_id){const data=await api('/students/'+r.student_id+'/portrait');box.append(renderPortrait(data))}
 const section=el('section',null,'version');section.append(el('h3','审核管理与档案操作'));
 const actions=el('div',null,'actions');section.append(actions);box.append(section);
 function button(label,action){const b=el('button',label,'secondary');b.type='button';b.onclick=()=>guard(async()=>{b.disabled=true;try{await action()}finally{b.disabled=false}});actions.append(b);return b}
 function reasonInput(label){const l=el('label',label);const input=el('textarea');l.append(input);section.append(l);return input}
 let correctionReason=null;
 if(r.status==='archived'){
  correctionReason=reasonInput('更正申请或论文进展更新说明');
  button('申请档案更正',async()=>{if(!correctionReason.value.trim())throw Error('请填写更正原因');await api('/submissions/'+r.id+'/corrections',{method:'POST',body:JSON.stringify({expected_lock_version:r.lock_version,reason:correctionReason.value})});message('更正申请已提交，原档案继续有效');await refresh()});
  if(me.id===r.student_id&&r.kind==='paper')button('更新论文进展',async()=>{if(!correctionReason.value.trim())throw Error('请填写进展更新说明');await api('/submissions/'+r.id+'/updates',{method:'POST',body:JSON.stringify({expected_lock_version:r.lock_version,reason:correctionReason.value})});message('已建立更新工作稿，原认定保留');await refresh()});
 }
 for(const c of r.corrections||[]){const item=el('div');item.append(el('p',(labels[c.status]||c.status)+'：'+c.reason));if(c.opinion)item.append(el('p','处理意见：'+c.opinion));
  if(me.role==='manager'&&c.status==='pending'){const opinion=el('textarea');opinion.placeholder='管理处理意见';item.append(opinion);for(const [outcome,label] of [['approve','批准更正'],['reject','驳回申请']]){const b=el('button',label,'secondary');b.onclick=()=>guard(async()=>{if(!opinion.value.trim())throw Error('请填写处理意见');await api('/corrections/'+c.id+'/handle',{method:'POST',body:JSON.stringify({expected_lock_version:r.lock_version,outcome,opinion:opinion.value})});await refresh()});item.append(b)}}section.append(item)}
 if(me.role==='manager'&&['pending_review','returned'].includes(r.status)){
  const select=el('select');for(const p of people.filter(p=>p.role==='teacher')){const o=el('option',p.name);o.value=p.id;select.append(o)}select.value=r.reviewer_id;const reason=reasonInput('审核责任调整原因');section.append(select);
  button('调整复核教师',async()=>{if(!reason.value.trim())throw Error('请填写调整原因');await api('/submissions/'+r.id+'/reviewer',{method:'POST',body:JSON.stringify({expected_lock_version:r.lock_version,reviewer_id:select.value,reason:reason.value})});await refresh()})
 }
 for(const c of r.reviewer_changes||[])section.append(el('p','责任/更新记录：'+c.reason,'muted'));
 if(r.effective_archive_id){const exportState=el('div');section.append(exportState);button('生成归档清单导出',async()=>{const job=await api('/exports',{method:'POST',body:JSON.stringify({submission_ids:[r.id]})});exportState.replaceChildren(el('p','导出已排队。运行 Worker 后检查进度。'));const check=el('button','检查导出进度','secondary');check.onclick=()=>guard(async()=>{const result=await api('/exports/'+job.id);message(labels[result.status]||result.status);if(result.status==='succeeded'){const link=el('a','下载归档清单 JSON');link.href='/api/v1/exports/'+job.id+'/download';exportState.replaceChildren(link)}else if(result.error)message(result.error,true)});exportState.append(check)})}
 if(!r.current_version_id)return;
 const ai=el('section',null,'version');ai.append(el('h3','AI Agent 辅助初审'));box.append(ai);
 const cap=await api('/ai/capabilities');ai.append(el('p',cap.mode==='rules'?'当前为本地规则初审，尚未连接校内语言模型。':cap.mode==='configuration_error'?'模型配置不完整，请联系管理员；人工复核可继续。':'已配置校内/自部署接口；执行结果将显示本次调用是否成功。'));
 ai.append(el('p','初审仅提供辅助证据，正式结论由教师决定。图片及扫描件 OCR 尚未配置。','muted'));
 const run=el('button','重新执行当前版本初审','secondary');run.onclick=()=>guard(async()=>{await api('/submissions/'+r.id+'/ai-jobs',{method:'POST',body:JSON.stringify({version_id:r.current_version_id})});message('初审任务已排队');await refresh()});ai.append(run);
 const current=(r.ai_jobs||[]).filter(j=>j.version_id===r.current_version_id).at(-1);
 if(!current)return;
 const result=await api('/ai-jobs/'+current.id);ai.append(el('p','任务状态：'+(labels[result.status]||result.status)+(result.historical_only?' · 仅供历史参考':'')));
 if(result.error)ai.append(el('p',result.error));
 if(['queued','running'].includes(result.status)){const cancel=el('button','取消本次初审','secondary');cancel.onclick=()=>guard(async()=>{await api('/ai-jobs/'+result.id+'/cancel',{method:'POST'});await refresh()});ai.append(cancel)}
 for(const c of result.result?.checks||[]){const item=el('div',null,'version');item.append(el('h3',(conclusions[c.conclusion]||c.conclusion)+' · '+c.rule_id),el('p',c.explanation));if(c.suggestion)item.append(el('p','建议：'+c.suggestion));for(const e of c.evidence){const a=el('a','查看原件 · '+(e.page_number?'第 '+e.page_number+' 页':e.paragraph_id));a.href='/api/v1/files/'+e.file_id+'/download'+(e.page_number?'#page='+e.page_number:'');a.target='_blank';item.append(a,el('blockquote',e.quote))}for(const l of c.limitations)item.append(el('p',l,'muted'));ai.append(item)}
 if(result.result?.blocks?.length){const details=el('details');details.append(el('summary','展开本次提取文本与位置'));for(const b of result.result.blocks){details.append(el('p',b.page_number?'原件第 '+b.page_number+' 页':'DOCX 段落 '+b.paragraph_id,'muted'),el('pre',b.text))}ai.append(details)}
}
