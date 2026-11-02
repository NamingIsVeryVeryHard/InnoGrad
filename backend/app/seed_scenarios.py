"""Explicit, idempotent synthetic cohort loader. Never runs on API startup.

All generated accounts, documents and review results are marked as simulations.
No external model is contacted; existing accounts and records are never replaced.
"""
from datetime import date,datetime,time,timedelta,timezone
from pathlib import Path
from uuid import uuid5,NAMESPACE_URL
from zoneinfo import ZoneInfo
import argparse,hashlib,io,json,os,secrets,zipfile
from xml.sax.saxutils import escape
from sqlalchemy import select
from .db import (User,Supervision,StudentProfile,Task,Assignment,Submission,Version,File,
    Decision,Archive,AIJob,GrowthEntry,WarningAction,FollowUp,Audit,connect,now)
from .main import password_hash
from .portraits import ensure_snapshot
from .growth import warning_candidates

BATCH='innograd-synthetic-cohort-v1'
STUDENTS=[
 ('林知远',2023,'学习分析与教育测评','毕业研究','stable'),
 ('陈予安',2023,'多智能体与数学导学','成果整理','due_soon'),
 ('周沐清',2023,'跨域视觉与教学行为','论文研究','overdue'),
 ('许景行',2024,'个性化学习支持','课题研究','returned'),
 ('苏以宁',2024,'教育大模型与学习反馈','实验验证','agent_exception'),
 ('沈书言',2024,'智能教育系统与实践','系统试验','goal_overdue'),
 ('顾南乔',2025,'学习分析与教育测评','方案设计','cleared'),
 ('陆星禾',2025,'多智能体与数学导学','科研训练','dismissed'),
 ('江映月',2025,'跨域视觉与教学行为','实验验证','pending'),
 ('程亦舟',2026,'个性化学习支持','课程与文献训练','early_stage'),
 ('叶清和',2026,'教育大模型与学习反馈','入学训练','returned_tracking'),
 ('唐若溪',2026,'智能教育系统与实践','入学训练','planned'),
]


def ident(key):return str(uuid5(NAMESPACE_URL,BATCH+'/'+key))
def stamp(day):return datetime.combine(day,time(10),tzinfo=ZoneInfo('Asia/Shanghai')).astimezone(timezone.utc).isoformat()
def docx_bytes(title,form):
    paragraphs=[title,'模拟数据 · 仅用于 InnoGrad 功能演示，不对应真实学生或真实成果。']+[str(k)+'：'+str(v) for k,v in form.items()]
    xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+''.join('<w:p><w:r><w:t xml:space="preserve">'+escape(p)+'</w:t></w:r></w:p>' for p in paragraphs)+'</w:body></w:document>'
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/document.xml',xml)
    return output.getvalue()


def seed_scenarios(factory,root,bundle,as_of):
    root=Path(root);bundle=Path(bundle);marker=ident('loaded')
    with factory() as session:
        if session.get(Audit,marker):return {'status':'already_loaded','batch':BATCH,'credentials_file':str(bundle/'accounts.json')}
        for i in range(12):
            if session.scalar(select(User).where(User.username==f'sim_student_{i+1:02}')):
                raise ValueError('Simulation account collision; refusing to overwrite existing data')
    if bundle.exists():raise ValueError('Output bundle exists without a batch marker; inspect it before retrying')
    bundle.mkdir(parents=True,mode=0o700);root.mkdir(parents=True,exist_ok=True)
    written=[];accounts=[];manifest={'batch':BATCH,'simulation':True,'as_of':as_of.isoformat(),'students':[]}
    try:
        with factory.begin() as session:
            manager=session.scalar(select(User).where(User.username=='manager',User.role=='manager'))
            teacher=session.scalar(select(User).where(User.username=='teacher',User.role=='teacher'))
            if not manager or not teacher:raise ValueError('Existing manager and teacher accounts are required')
            sim_actor=User(id=ident('simulation-actor'),username='__innograd_simulation__',name='InnoGrad 模拟场景生成器',role='service',enabled=0,password_hash='disabled$disabled')
            session.add(sim_actor);session.flush()
            def task(key,title,sid,period,deadline):
                t=Task(id=ident('task/'+key),title='[模拟] '+title,period=period,deadline=stamp(deadline),reviewer_id=teacher.id,
                    requirements={'version':'simulation-annual-v1','required_fields':['summary','plan'],'attachment_required':True,'review_policy':'simulation','simulation':True},created_by=manager.id)
                session.add(t);session.flush();session.add(Assignment(id=ident('assignment/'+key),task_id=t.id,student_id=sid));return t
            def material(key,student,kind,title,form,period,day,status='archived',task_row=None):
                form={'title':'[模拟] '+title,**form,'simulation_notice':'全部内容为模拟，不用于真实评价'}
                sub=Submission(id=ident('submission/'+key),student_id=student.id,kind=kind,task_id=task_row.id if task_row else None,
                    reviewer_id=teacher.id,status=status,lock_version=3 if status=='archived' else 2,created_at=stamp(day))
                session.add(sub);session.flush()
                data=docx_bytes(form['title'],form);storage=ident('storage/'+key)
                path=root/storage
                if path.exists():raise ValueError('Synthetic file collision; no file overwritten')
                path.write_bytes(data);written.append(path)
                f=File(id=ident('file/'+key),owner_id=student.id,submission_id=sub.id,name=form['title']+'.docx',media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',storage_key=storage,sha256=hashlib.sha256(data).hexdigest(),size=len(data))
                session.add(f);session.flush()
                sub.draft={'form':form,'file_ids':[f.id],'reference_ids':[]}
                if status=='draft':return sub,None,None
                v=Version(id=ident('version/'+key),submission_id=sub.id,number=1,created_at=stamp(day),snapshot={'simulation':True,'form':form,'file_ids':[f.id],'references':[],
                    'requirements':task_row.requirements if task_row else {'version':'simulation-paper-v1','review_policy':'simulation'},'period':period,'late':False,'review_workflow':'simulation'})
                session.add(v);session.flush();sub.current_version_id=v.id
                if status in ('archived','returned'):
                    d=Decision(id=ident('decision/'+key),version_id=v.id,reviewer_id=sim_actor.id,actor_type='simulation',outcome='approved' if status=='archived' else 'returned',
                        opinion='[模拟审核记录] 材料结构与引用记录完整，供界面演示。' if status=='archived' else '[模拟退回意见] 请补充实验条件、本人贡献说明与对应证据。',created_at=stamp(day+timedelta(days=1)))
                    session.add(d);session.flush()
                    if status=='archived':
                        a=Archive(id=ident('archive/'+key),version_id=v.id,decision_id=d.id,created_at=stamp(day+timedelta(days=2)))
                        session.add(a);session.flush();sub.effective_archive_id=a.id
                        snap=ensure_snapshot(session,a,sub);snap.created_at=a.created_at
                session.add(Audit(actor_id=sim_actor.id,action='simulation.material_loaded',object_id=sub.id,created_at=stamp(day)))
                return sub,v,f
            def growth(key,sid,kind,title,body,period,day,due=None,status=None,dimension=None,version=None,field=None,quote=None):
                row=GrowthEntry(id=ident('growth/'+key),student_id=sid,created_by=teacher.id if kind in ('observation','feedback') else sid,kind=kind,
                    title='[模拟] '+title,body=body+'（模拟记录）',period=period,dimension=dimension,due_date=due.isoformat() if due else None,
                    status=status or ('planned' if kind in ('goal','milestone') else 'done'),source_version_id=version.id if version else None,
                    source_field=field,source_quote=quote,created_at=stamp(day),updated_at=stamp(day))
                session.add(row);return row
            for i,(name,year,direction,stage,scenario) in enumerate(STUDENTS):
                prefix=f's{i+1:02}';password=secrets.token_urlsafe(14);username=f'sim_student_{i+1:02}'
                student=User(id=ident(prefix),username=username,name=name+'（模拟）',role='student',password_hash=password_hash(password))
                session.add(student);session.flush()
                session.add(StudentProfile(user_id=student.id,number=f'SIM{year}{i+1:04}',year=f'{year}级',degree='硕士' if i%2 else '博士',major='人工智能' if i%2 else '智能教育',direction=direction,stage=stage))
                for actor in (manager,teacher):session.add(Supervision(id=ident(prefix+'/relation/'+actor.role),student_id=student.id,teacher_id=actor.id,valid_from=stamp(as_of-timedelta(days=400))))
                accounts.append({'username':username,'password':password,'name':student.name,'role':'student','scenario':scenario})
                base_day=as_of-timedelta(days=35 if year==2026 else 220-i*7)
                period='2026—2027' if year==2026 else '2025—2026'
                annual=task(prefix+'/baseline','入学研究训练记录' if year==2026 else '年度研究进展报告',student.id,period,base_day+timedelta(days=10))
                form={'summary':f'围绕{direction}完成问题梳理、文献比较与研究方案设计，明确研究问题和评价方法。',
                    'plan':f'围绕{direction}补充对照实验与结果解释，整理可复核的研究记录。',
                    'education_context':f'研究面向{direction}的教学与学习场景，分析学习者需求、教师反馈和使用限制。',
                    'academic_exchange':f'在专题组会交流{direction}的研究设计，记录方法选择讨论与收到的改进建议。',
                    'practice_record':f'搭建{direction}的可演示原型，整理测试流程、样例数据与应用边界。'}
                baseline,bv,bf=material(prefix+'/baseline',student,'annual',annual.title.removeprefix('[模拟] '),form,period,base_day,task_row=annual)
                versions=[bv];files=[bf.id];submissions=[baseline.id]
                for j in range(1 if year>=2025 else 2):
                    paper_day=as_of-timedelta(days=20+j*4 if year==2026 else 95-j*35-i)
                    publication='submitted' if year==2026 else 'published' if year==2023 and j==0 else 'accepted'
                    paper_form={'publication_status':publication,'journal':'模拟教育智能研究会议（非真实刊物）','doi':'',
                        {'submitted':'submission_date','accepted':'acceptance_date','published':'publication_date'}[publication]:paper_day.isoformat(),
                        'contribution':f'本人负责{direction}研究中的方案设计、实验实现与结果分析；整理代码、数据说明及实验复核记录。'}
                    sp,vp,fp=material(prefix+f'/paper{j}',student,'paper',direction+('：研究方法与实验验证' if j==0 else '：系统原型与应用研究'),paper_form,'2026—2027',paper_day)
                    submissions.append(sp.id);versions.append(vp);files.append(fp.id)
                # Current-period report ensures current-year six-direction coverage for senior cohorts.
                current_v=bv
                if year!=2026:
                    t=task(prefix+'/current','秋季阶段研究记录',student.id,'2026—2027',as_of+timedelta(days=15))
                    ss,vv,ff=material(prefix+'/current',student,'annual',direction+'阶段总结',form,'2026—2027',as_of-timedelta(days=12+i%5),task_row=t)
                    submissions.append(ss.id);versions.append(vv);files.append(ff.id);current_v=vv
                for dim,field in [('education','education_context'),('exchange','academic_exchange'),('practice','practice_record')]:
                    if scenario=='early_stage' and dim=='practice':continue
                    growth(prefix+'/observation/'+dim,student.id,'observation',{'education':'教育场景材料依据','exchange':'学术交流材料依据','practice':'原型实践材料依据'}[dim],
                        '根据已归档报告中的对应字段关联研究过程证据，不作能力评分。','2026—2027',as_of-timedelta(days=7),dimension=dim,version=current_v,field=field,quote=current_v.snapshot['form'][field])
                growth(prefix+'/goal',student.id,'goal',direction+'阶段目标','完成研究问题界定、方法验证与证据整理，明确下一阶段需要的支持。','2026—2027',as_of-timedelta(days=10),due=as_of+timedelta(days=25))
                for j,title in enumerate(['研究问题与方案梳理','基线实验与记录整理','结果复核与阶段汇报']):
                    growth(prefix+f'/milestone{j}',student.id,'milestone',title,'保留阶段产出、实验条件和下一步安排。','2026—2027',as_of-timedelta(days=24-j*7),due=as_of+timedelta(days=14) if j==2 else as_of-timedelta(days=20-j*7),status='planned' if j==2 else 'done')
                growth(prefix+'/reflection',student.id,'reflection','阶段研究反思','已完成的问题分析较清晰，下一阶段重点补充对照条件、失败案例和结论适用范围。','2026—2027',as_of-timedelta(days=5))
                growth(prefix+'/feedback',student.id,'feedback','把反馈连接到下一步实验','建议明确个人承担的工作，保留实验版本与原始依据，并将下一步计划拆解为可复核节点。','2026—2027',as_of-timedelta(days=4))
                demo_entry=None;extra_task=None
                if scenario in ('due_soon','overdue'):
                    extra_task=task(prefix+'/warning-task','待提交年度补充报告',student.id,'2026—2027',as_of+timedelta(days=3) if scenario=='due_soon' else as_of-timedelta(days=7))
                    if scenario=='overdue':
                        ss,_,_=material(prefix+'/private-draft',student,'annual','尚未正式提交的报告工作稿',{'summary':'模拟私人草稿，教师不能读取正文。','plan':'补充后正式提交'},'2026—2027',as_of-timedelta(days=8),'draft',extra_task)
                        submissions.append(ss.id)
                if scenario in ('returned','returned_tracking','agent_exception','pending'):
                    extra_task=task(prefix+'/review-task','阶段材料补充任务',student.id,'2026—2027',as_of+timedelta(days=14))
                    ss,vv,ff=material(prefix+'/review',student,'annual','需要核验的阶段报告',form,'2026—2027',as_of-timedelta(days=3),'returned' if scenario.startswith('returned') else 'pending_review',extra_task)
                    submissions.append(ss.id);files.append(ff.id)
                    if scenario=='agent_exception':
                        pack={'version_id':vv.id,'snapshot':vv.snapshot,'files':[{'id':ff.id,'name':ff.name,'storage_key':ff.storage_key,'sha256':ff.sha256,'media_type':ff.media_type}]}
                        session.add(AIJob(id=ident(prefix+'/mock-agent'),submission_id=ss.id,version_id=vv.id,requested_by=student.id,input_pack=pack,input_hash=hashlib.sha256(json.dumps(pack,sort_keys=True).encode()).hexdigest(),
                            config={'mode':'agent','workflow':'simulation','simulation':True},status='succeeded',attempts=1,created_at=stamp(as_of-timedelta(days=2)),finished_at=stamp(as_of-timedelta(days=2)),
                            result={'simulation':True,'automatic_approval':False,'mode':'agent','checks':[{'rule_id':'SIMULATED_EVIDENCE_GAP','conclusion':'unable_to_determine','severity':'suggestion','explanation':'[模拟结果，未调用真实 Agent] 报告中的实验条件与个人贡献依据需要进一步核验。','evidence':[],'limitations':['模拟审核场景，不是真实模型执行结果']}],'blocks':[],'limitations':['模拟证据不足场景']}))
                if scenario in ('goal_overdue','cleared','dismissed','planned'):
                    demo_entry=growth(prefix+'/warning-goal',student.id,'milestone','预警演示：补齐研究记录','用于演示计划到期、跟进与自动消除；完成后可在预警中心查看保留的历史。','2026—2027',as_of-timedelta(days=9),due=as_of-timedelta(days=2))
                session.flush()
                warnings=warning_candidates(session,[student.id],datetime.combine(as_of,time(12),tzinfo=ZoneInfo('Asia/Shanghai')))
                for w in warnings:
                    if scenario in ('goal_overdue','cleared','returned_tracking','dismissed'):
                        session.add(WarningAction(id=ident(prefix+'/action/'+w['kind']),warning_key=w['id'],student_id=student.id,actor_id=teacher.id,
                            status='dismissed' if scenario=='dismissed' else 'tracking',note='[模拟跟进] 已核对来源并沟通下一步安排。'+('本项仅为测试提醒，核验后排除。' if scenario=='dismissed' else '完成对应计划或补齐材料后，系统自动消除预警。'),payload=w,created_at=stamp(as_of-timedelta(days=1))))
                if scenario=='cleared':demo_entry.status='done';demo_entry.updated_at=stamp(as_of);demo_entry.lock_version=1
                if i%3==0:
                    session.add(FollowUp(id=ident(prefix+'/manual-reminder'),student_id=student.id,created_by=teacher.id,title='[模拟] 阶段材料沟通',text='请整理本阶段研究记录，明确下一步支持需求。',note='[模拟反馈] 已确认提交与沟通安排。' if i==0 else '',status='done' if i==0 else 'open'))
                manifest['students'].append({'id':student.id,'name':student.name,'username':username,'year':year,'degree':'硕士' if i%2 else '博士','major':'人工智能' if i%2 else '智能教育','direction':direction,'scenario':scenario,
                    'submission_ids':submissions,'file_ids':files,'warning_goal_id':demo_entry.id if demo_entry else None,'task_id':extra_task.id if extra_task else None})
            session.add(Audit(id=marker,actor_id=manager.id,action='simulation.cohort_loaded',object_id=marker))
            # Create credentials with restrictive permissions before DB commit; clean on rollback.
            for name,payload in [('accounts.json',accounts),('manifest.json',manifest)]:
                path=bundle/name
                with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:json.dump(payload,f,ensure_ascii=False,indent=2)
        return {'status':'created','batch':BATCH,'students':len(accounts),'files':len(written),'credentials_file':str(bundle/'accounts.json'),'manifest_file':str(bundle/'manifest.json')}
    except Exception:
        for path in written:path.unlink(missing_ok=True)
        for name in ('accounts.json','manifest.json'):(bundle/name).unlink(missing_ok=True)
        try:bundle.rmdir()
        except OSError:pass
        raise


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--as-of',type=date.fromisoformat,default=datetime.now(ZoneInfo('Asia/Shanghai')).date())
    parser.add_argument('--bundle',default='runtime/simulation-cohort-v1')
    args=parser.parse_args();_,factory=connect()
    print(json.dumps(seed_scenarios(factory,os.getenv('FILE_ROOT','runtime/files'),args.bundle,args.as_of),ensure_ascii=False))


if __name__=='__main__':main()
