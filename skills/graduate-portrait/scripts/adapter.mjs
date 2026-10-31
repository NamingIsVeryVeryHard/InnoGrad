import {parseStructuredResponse} from './response.mjs';
import {repairFeedback} from './validation.mjs';
import {failure,requestFailure} from './errors.mjs';
export function endpoint(value,label='remote URL') {
  let parsed;try{parsed=new URL(value);}catch{throw failure('CONFIGURATION','invalid '+label);}
  const loopback=['127.0.0.1','localhost','[::1]'].includes(parsed.hostname);
  if((parsed.protocol!=='https:'&&!(parsed.protocol==='http:'&&loopback))||parsed.username||parsed.password||parsed.search||parsed.hash)throw failure('CONFIGURATION',label+' requires HTTPS or loopback HTTP without credentials/query/fragment');
  return parsed.href;
}
function timeout(value) {const n=Number(value??240000);if(!Number.isInteger(n)||n<1000||n>900000)throw failure('CONFIGURATION','timeout must be 1000–900000 ms');return n;}
export function adapterConfig(env) {
  const url=env.PORTRAIT_API_URL,model=env.PORTRAIT_API_MODEL,key=env.PORTRAIT_API_KEY;
  if(!url||!model?.trim()||!key?.trim())throw failure('CONFIGURATION','remote adapter requires PORTRAIT_API_URL, PORTRAIT_API_MODEL and PORTRAIT_API_KEY');
  const primary={url:endpoint(url),model:model.trim(),key,provider:'ecnu',timeoutMs:timeout(env.PORTRAIT_API_TIMEOUT_MS)};
  const fallbacks=[];
  for(const [prefix,provider] of [['GROK','cliproxy_grok'],['GEMINI','cliproxy_gemini']]) {
    const values=['URL','MODEL','KEY'].map(k=>env['PORTRAIT_FALLBACK_'+prefix+'_'+k]);
    if(values.every(v=>!v))continue;
    if(values.some(v=>!v?.trim()))throw failure('CONFIGURATION','incomplete fallback configuration');
    const effort=env['PORTRAIT_FALLBACK_'+prefix+'_EFFORT'];
    if(effort&&effort!=='low')throw failure('CONFIGURATION','fallback effort must be low');
    fallbacks.push({url:endpoint(values[0]),model:values[1].trim(),key:values[2],provider,timeoutMs:primary.timeoutMs,effort:effort??'low'});
  }
  return {...primary,fallbacks};
}
// Fail closed: a generic 429 means rate limiting, not exhausted quota.
export function exhaustedQuota(status,envelope) {
  const code=envelope?.error?.code??envelope?.error?.type;
  return [400,402,403,429].includes(status)&&['insufficient_quota','quota_exceeded','quota_exhausted','credit_balance_exhausted'].includes(code);
}
function safeRecord(config,attempt,status,model=null) {return {provider:config.provider??'configured',requested_model:config.model,actual_model:typeof model==='string'?model:null,attempt,status};}
export async function requestCompletion(payload,{config,fetchImpl=fetch,signal,timeoutMs=config.timeoutMs??240000,onAttempt=()=>{}}) {
  const providers=[config,...(config.fallbacks??[])];const records=[];
  for(let i=0;i<providers.length;i++) {
    signal?.throwIfAborted();const p=providers[i];let response;
    const body={...payload,model:p.model,stream:false};
    // These configured CLIProxy models support low effort. Unknown aliases omit it.
    if(p.effort==='low'&&/^(?:grok-4\.6|gemini-3-flash)$/.test(p.model))body.reasoning_effort='low';
    try{response=await fetchImpl(p.url,{method:'POST',redirect:'error',headers:{'content-type':'application/json',authorization:'Bearer '+p.key},body:JSON.stringify(body),signal:signal?AbortSignal.any([signal,AbortSignal.timeout(timeoutMs)]):AbortSignal.timeout(timeoutMs)});}catch(e){throw requestFailure(e,signal);}
    let envelope;try{envelope=await response.json();}catch{throw failure('INNOAGENT_PROTOCOL',`invalid remote response envelope (status ${response.status}, content-type ${response.headers.get('content-type')??'unknown'})`);}
    const record=safeRecord(p,i+1,response.ok?'completed':exhaustedQuota(response.status,envelope)?'quota_exhausted':'http_error',envelope.model);records.push(record);onAttempt(record);
    if(!response.ok) {
      if(exhaustedQuota(response.status,envelope)){if(i+1<providers.length)continue;throw failure('QUOTA_EXHAUSTED','configured provider quota exhausted',{attempts:records});}
      throw failure('REMOTE_HTTP','remote HTTP failure '+response.status,{status:response.status,attempts:records});
    }
    return {envelope,attempts:records};
  }
}
export async function requestStructured(task,{config,validate,fetchImpl=fetch,repairLimit=1,timeoutMs=config.timeoutMs??240000,signal,onAttempt=()=>{},formatRepairFeedback=repairFeedback}) {
  if(![0,1].includes(repairLimit))throw failure('CONFIGURATION','repair limit must be zero or one');
  const messages=[{role:'system',content:task.instructions.join('\n')},{role:'user',content:JSON.stringify(task)}];const records=[];
  for(let attempt=0;attempt<=repairLimit;attempt++) {
    const {envelope,attempts}=await requestCompletion({messages,response_format:{type:'json_object'}},{config,fetchImpl,timeoutMs,signal,onAttempt});records.push(...attempts);
    const choice=envelope.choices?.[0];
    if(envelope.choices?.length!==1||choice?.finish_reason!=='stop'||choice?.message?.refusal||choice?.message?.tool_calls?.length||typeof choice?.message?.content!=='string')throw failure('STRUCTURED_OUTPUT','remote completion incomplete or refused');
    try{const data=parseStructuredResponse(choice.message.content);validate(data);return {data,attempts:attempt+1,model:envelope.model??config.model,requested_model:config.model,records};}catch(error){
      if(attempt===repairLimit)throw failure('STRUCTURED_OUTPUT','remote structured output failed validation',{validation_issues:error.validation_issues??[{path:'',category:error instanceof SyntaxError?'JSON_PARSE':'VALIDATION'}]});
      messages.push({role:'user',content:formatRepairFeedback(error)});
    }
  }
}
