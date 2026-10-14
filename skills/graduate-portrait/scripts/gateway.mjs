import {createServer} from 'node:http';
import {adapterConfig,exhaustedQuota} from './adapter.mjs';
import {loadProjectEnv} from './env.mjs';
import {failure,requestFailure} from './errors.mjs';
export function createModelGateway({config,fetchImpl=fetch,onAttempt=()=>{}}) {
  const audit=new Map();
  return createServer(async(req,res)=>{
    const lookup=/^\/runs\/([0-9a-f-]{36})$/.exec(req.url??'');
    if(req.method==='GET'&&lookup){res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({attempts:audit.get(lookup[1])??[]}));return;}
    if(req.method!=='POST'||req.url!=='/v1/chat/completions'){res.writeHead(404);res.end();return;}
    const aborter=new AbortController();res.on('close',()=>{if(!res.writableFinished)aborter.abort();});let text='';
    try {
      for await(const part of req){text+=part;if(Buffer.byteLength(text)>4*1024*1024)throw failure('INVALID_INPUT','body too large');}
      const payload=JSON.parse(text);if(!payload||typeof payload!=='object'||!Array.isArray(payload.messages))throw failure('INVALID_INPUT','invalid body');
      const user=payload.messages.findLast(m=>m.role==='user');
      const userText=typeof user?.content==='string'?user.content:Array.isArray(user?.content)?user.content.filter(c=>c.type==='text').map(c=>c.text).join(''):'';
      const boundary=userText.indexOf('</skill>');const argumentsText=boundary>=0?userText.slice(boundary+'</skill>'.length).trimStart():userText;
      const marker=/^portrait_run_id:([0-9a-f-]{36})(?: |\n)/.exec(argumentsText);const runId=marker?.[1];
      // Only the leading caller marker selects the audit run; never scan student materials.
      function record(value){onAttempt(value);if(runId){if(!audit.has(runId)){if(audit.size>=200)audit.delete(audit.keys().next().value);audit.set(runId,[]);}audit.get(runId).push(value);}}
      const providers=[config,...(config.fallbacks??[])];
      for(let i=0;i<providers.length;i++) {
        const p=providers[i],body={...payload,model:p.model};
        if(p.effort==='low'&&/^(?:grok-4\.6|gemini-3-flash)$/.test(p.model))body.reasoning_effort='low';
        let response;try{response=await fetchImpl(p.url,{method:'POST',redirect:'error',headers:{'content-type':'application/json',authorization:'Bearer '+p.key},body:JSON.stringify(body),signal:AbortSignal.any([aborter.signal,AbortSignal.timeout(config.timeoutMs??240000)])});}catch(e){throw requestFailure(e,aborter.signal);}
        const metadata={provider:p.provider??'configured',requested_model:p.model,actual_model:null,attempt:i+1,status:'completed'};
        if(!response.ok){let error;try{error=await response.json();}catch{}const quota=exhaustedQuota(response.status,error);record({...metadata,status:quota?'quota_exhausted':'http_error'});if(quota&&i+1<providers.length)continue;throw failure(quota?'QUOTA_EXHAUSTED':'REMOTE_HTTP','provider request failed');}
        if(payload.stream) {
          if(!response.headers.get('content-type')?.includes('text/event-stream'))throw failure('INNOAGENT_PROTOCOL','provider did not return SSE');
          res.writeHead(200,{'content-type':'text/event-stream','cache-control':'no-cache'});
          const decoder=new TextDecoder();let pending='';let done=false;let recorded=false;metadata.status='in_progress';
          const parseLine=line=>{if(line==='data: [DONE]')done=true;else if(line.startsWith('data: ')){try{const event=JSON.parse(line.slice(6));if(typeof event.model==='string')metadata.actual_model=event.model;for(const choice of event.choices??[]){if(choice.index===0||choice.index===undefined){if(typeof choice.finish_reason==='string')metadata.finish_reason=choice.finish_reason;}}if(event.error)throw failure('INNOAGENT_PROTOCOL','provider SSE error');}catch(e){if(e.code)throw e;}}};
          const complete=()=>{metadata.status='completed';metadata.stream_termination='done_marker';record(metadata);recorded=true;res.end();};
          try {
          for await(const chunk of response.body) {
            pending+=decoder.decode(chunk,{stream:true});const lines=pending.split('\n');pending=lines.pop();
            for(const line of lines)parseLine(line.replace(/\r$/,''));
            res.write(chunk);
            // [DONE] terminates the SSE protocol; waiting for TCP EOF races client cleanup.
            if(done){complete();break;}
          }
          if(!recorded){pending+=decoder.decode();if(pending)parseLine(pending.replace(/\r$/,''));if(!done)throw failure('INNOAGENT_PROTOCOL','incomplete provider SSE');complete();}
          }catch(e){if(!recorded){metadata.status=aborter.signal.aborted?'aborted':'stream_failed';metadata.stream_termination=aborter.signal.aborted?'client_closed_before_done':'incomplete';record(metadata);}throw e;}
        } else {const envelope=await response.json();metadata.actual_model=typeof envelope.model==='string'?envelope.model:null;record(metadata);res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(envelope));}
        return;
      }
    }catch(e){if(res.destroyed)return;if(res.headersSent){res.end();return;}res.writeHead(e.code==='QUOTA_EXHAUSTED'?429:e.code==='INVALID_INPUT'?400:502,{'content-type':'application/json'});res.end(JSON.stringify({error:{code:e.code??'INVALID_REQUEST',message:'model gateway request failed'}}));}
  });
}
export async function startModelGateway({env,port=3148,onAttempt}={}) {
  const server=createModelGateway({config:adapterConfig(env??await loadProjectEnv()),onAttempt});
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);});return server;
}
