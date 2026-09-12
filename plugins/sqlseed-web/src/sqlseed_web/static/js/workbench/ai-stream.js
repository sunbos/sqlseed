const stages=new Set(['context','model','validation','preview']);
const invalid=()=>new Error('AI 进度格式不正确，请重试。');
function responseError(detail,status){
  const message=typeof detail==='string'?detail:Array.isArray(detail)
    ?detail.map(item=>`${(item.loc || []).join('.')}: ${item.msg || JSON.stringify(item)}`).join('；')
    :detail?.message || `HTTP ${status}`;
  const error=new Error(message);error.status=status;error.detail=detail;error.code=detail?.code;return error;
}

// A terminal result is required: an HTTP 200 or a progress event alone never
// makes suggestions reviewable. The caller owns epoch and modal lifecycle checks.
export async function requestAISuggestions(path,request,{signal,onProgress}={}){
  const checkAbort=()=>{
    if(signal?.aborted){const error=new Error('AI 分析已取消。');error.name='AbortError';throw error;}
  };
  checkAbort();
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/x-ndjson'},body:JSON.stringify(request),signal});
  checkAbort();
  const streamed=response.headers?.get('Content-Type')?.includes('application/x-ndjson');
  if(!response.ok||!streamed){
    const body=await response.json().catch(()=>null);checkAbort();
    if(!response.ok)throw responseError(body?.detail,response.status);
    if(!body||typeof body!=='object'||Array.isArray(body))throw invalid();
    return body;
  }
  if(!response.body?.getReader)throw invalid();
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
  const cancel=()=>{reader.cancel().catch(()=>{});};signal?.addEventListener('abort',cancel,{once:true});
  function event(line){
    let value;try{value=JSON.parse(line);}catch{throw invalid();}
    if(value?.type==='progress'&&stages.has(value.stage)&&typeof value.message==='string'){
      onProgress?.({type:'progress',stage:value.stage,message:value.message});return null;
    }
    if(value?.type==='result'&&value.result&&typeof value.result==='object'&&!Array.isArray(value.result))return value;
    if(value?.type==='error'&&typeof value.message==='string'){
      const error=new Error(value.message);error.code=value.code;throw error;
    }
    throw invalid();
  }
  try{
    for(;;){
      checkAbort();const {value,done}=await reader.read();checkAbort();
      buffer+=done?decoder.decode():decoder.decode(value,{stream:true});
      const lines=buffer.split('\n');buffer=lines.pop();
      if(done&&buffer.trim()){lines.push(buffer);buffer='';}
      for(const line of lines){
        checkAbort();if(!line.trim())continue;
        const terminal=event(line);if(terminal)return terminal.result;
      }
      if(done)throw new Error('AI 分析连接中断，未收到完整结果，请重试。');
    }
  }finally{
    signal?.removeEventListener('abort',cancel);
    await reader.cancel().catch(()=>{});reader.releaseLock();
  }
}
