export function adapterConfig(env) {
  const url=env.PORTRAIT_API_URL,model=env.PORTRAIT_API_MODEL,key=env.PORTRAIT_API_KEY;
  if(!url||!model?.trim()||!key?.trim())throw new Error('remote adapter requires PORTRAIT_API_URL, PORTRAIT_API_MODEL and PORTRAIT_API_KEY');
  let parsed;try{parsed=new URL(url);}catch{throw new Error('invalid remote URL');}
  if(parsed.protocol!=='https:'||parsed.username||parsed.password||parsed.search||parsed.hash)throw new Error('remote URL must be HTTPS without credentials/query/fragment');
  return {url,model,key};
}
export async function requestStructured(task,{config,validate,fetchImpl=fetch,repairLimit=1,timeoutMs=30000}) {
  if(![0,1].includes(repairLimit))throw new Error('repair limit must be zero or one');
  const messages=[{role:'system',content:task.instructions.join('\n')},{role:'user',content:JSON.stringify(task)}];
  for(let attempt=0;attempt<=repairLimit;attempt++) {
    let response;
    try{response=await fetchImpl(config.url,{method:'POST',redirect:'error',headers:{'content-type':'application/json',authorization:'Bearer '+config.key},body:JSON.stringify({model:config.model,messages,stream:false,response_format:{type:'json_object'}}),signal:AbortSignal.timeout(timeoutMs)});}catch{throw new Error('remote request failed');}
    if(!response.ok)throw new Error('remote HTTP failure '+response.status);
    let envelope;try{envelope=await response.json();}catch{throw new Error('invalid remote response envelope');}
    const choice=envelope.choices?.[0];
    if(envelope.choices?.length!==1||choice?.finish_reason!=='stop'||choice?.message?.refusal||choice?.message?.tool_calls?.length||typeof choice?.message?.content!=='string')throw new Error('remote completion incomplete or refused');
    try{const data=JSON.parse(choice.message.content);validate(data);return {data,attempts:attempt+1,model:envelope.model??config.model};}catch{
      if(attempt===repairLimit)throw new Error('remote structured output failed validation');
      // Do not echo provider text or secrets; regenerate once from the original task.
      messages.push({role:'user',content:'前次JSON无法通过schema或证据校验。依据原任务重新输出完整JSON；不增加字段，不伪造引用。'});
    }
  }
}
