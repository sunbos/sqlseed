const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {loadFrontend}=require('./frontend_helpers.cjs');
const plain=value=>JSON.parse(JSON.stringify(value));
function load(fetch){
  assert.ok(fs.existsSync(path.join(__dirname,'../src/sqlseed_web/static/js/workbench/ai-stream.js')),'AI stream reader must exist');
  const context=loadFrontend('workbench/ai-stream.js',{fetch,TextDecoder});
  return vm.runInContext('requestAISuggestions',context);
}
function response(chunks,{close=true,onCancel=()=>{}}={}){
  return new Response(new ReadableStream({start(controller){for(const chunk of chunks)controller.enqueue(chunk);if(close)controller.close();},cancel:onCancel}),{headers:{'Content-Type':'application/x-ndjson'}});
}
const bytes=text=>new TextEncoder().encode(text);
const encode=value=>JSON.stringify(value)+'\n';

test('stream reader decodes byte-split UTF-8, multiple events and a terminal line without a newline',async()=>{
  const progress=[],events=encode({type:'progress',stage:'model',message:'等待模型'})+encode({type:'progress',stage:'preview',message:'检查只读样例'})+JSON.stringify({type:'result',result:{suggestions:[]}});
  const chunks=[...bytes(events)].map(byte=>new Uint8Array([byte]));let sent;
  const request=load(async(path,options)=>{sent={path,options};return response(chunks);});
  const value=await request('/suggest',{tables:['users']},{onProgress:event=>progress.push(plain(event))});
  assert.deepEqual(plain(value),{suggestions:[]});assert.deepEqual(progress.map(item=>item.message),['等待模型','检查只读样例']);
  assert.equal(sent.options.headers.Accept,'application/x-ndjson');assert.deepEqual(JSON.parse(sent.options.body),{tables:['users']});
});

test('ordinary JSON success and structured HTTP errors remain supported',async()=>{
  const request=load(async()=>new Response(JSON.stringify({suggestions:[]}),{headers:{'Content-Type':'application/json'}}));
  assert.deepEqual(plain(await request('/suggest',{})),{suggestions:[]});
  const reject=load(async()=>new Response(JSON.stringify({detail:{code:'not_found',message:'unknown connection: old'}}),{status:404,headers:{'Content-Type':'application/json'}}));
  await assert.rejects(()=>reject('/suggest',{}),error=>error.status===404&&error.code==='not_found'&&error.message==='unknown connection: old');
});

for(const [name,text,pattern] of [
  ['missing terminal',encode({type:'progress',stage:'model',message:'等待'}),/中断|完整结果/],
  ['invalid JSON','broken\n',/格式/],
  ['invalid final line without a newline','broken',/格式/],
  ['unknown stage',encode({type:'progress',stage:'fake',message:'fake'}),/格式/],
  ['unknown event',encode({type:'token',text:'hidden model output'}),/格式/],
  ['invalid result',encode({type:'result',result:null}),/格式/],
])test(`stream reader rejects ${name} instead of accepting an incomplete analysis`,async()=>{
  const request=load(async()=>response([bytes(text)]));await assert.rejects(()=>request('/suggest',{}),pattern);
});

test('stream error preserves its public code and closes the reader',async()=>{
  let cancelled=false;
  const request=load(async()=>response([bytes(encode({type:'error',code:'ai_timeout',message:'候选检查超时'}))],{close:false,onCancel:()=>{cancelled=true;}}));
  await assert.rejects(()=>request('/suggest',{}),error=>error.code==='ai_timeout'&&error.message==='候选检查超时');assert.equal(cancelled,true);
});

test('terminal results close a still-open transport without waiting for further model output',async()=>{
  let cancelled=false;
  const request=load(async()=>response([bytes(encode({type:'result',result:{suggestions:[]}}))],{close:false,onCancel:()=>{cancelled=true;}}));
  assert.deepEqual(plain(await request('/suggest',{})),{suggestions:[]});assert.equal(cancelled,true);
});

test('abort cancels a pending stream read and never publishes late progress',async()=>{
  let cancelled=false,received=0;
  const request=load(async()=>response([],{close:false,onCancel:()=>{cancelled=true;}})),controller=new AbortController();
  const pending=request('/suggest',{},{signal:controller.signal,onProgress:()=>received++});
  await new Promise(resolve=>setImmediate(resolve));controller.abort();
  await assert.rejects(()=>pending,error=>error.name==='AbortError');assert.equal(cancelled,true);assert.equal(received,0);
});

test('stream pulls one chunk at a time and stops at the terminal event in the same chunk',async()=>{
  let source,reads=0,active=0,maxActive=0,cancels=0,releases=0;
  const transport=new ReadableStream({start(controller){source=controller;}});
  transport[Symbol.asyncIterator]=undefined;
  const nativeReader=transport.getReader.bind(transport);
  transport.getReader=()=>{
    const reader=nativeReader();
    return {
      read(){reads++;active++;maxActive=Math.max(maxActive,active);return reader.read().finally(()=>active--);},
      cancel(){cancels++;return reader.cancel();},
      releaseLock(){releases++;reader.releaseLock();}
    };
  };
  const progress=[],request=load(async()=>new Response(transport,{headers:{'Content-Type':'application/x-ndjson'}}));
  const pending=request('/suggest',{},{onProgress:event=>{progress.push(event.message);assert.equal(reads,1);}});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(reads,1);assert.equal(active,1);
  source.enqueue(bytes(encode({type:'progress',stage:'model',message:'第一块'})));
  await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(progress,['第一块']);assert.equal(reads,2);assert.equal(active,1);
  source.enqueue(bytes(encode({type:'result',result:{suggestions:[]}})+'broken\n'+encode({type:'progress',stage:'preview',message:'迟到进度'})));
  assert.deepEqual(plain(await pending),{suggestions:[]});
  assert.deepEqual(progress,['第一块']);assert.equal(reads,2);assert.equal(maxActive,1);
  assert.equal(cancels,1);assert.equal(releases,1);assert.equal(transport.locked,false);
});

test('a synchronous progress callback failure rejects the request and releases the stream',async()=>{
  let cancelled=false,received=0;
  const failure=new Error('progress observer failed');
  const transport=response([bytes(encode({type:'progress',stage:'model',message:'进度'})+encode({type:'result',result:{suggestions:[]}}))],{close:false,onCancel:()=>{cancelled=true;}});
  const request=load(async()=>transport);
  await assert.rejects(()=>request('/suggest',{},{onProgress:()=>{received++;throw failure;}}),error=>error===failure);
  assert.equal(received,1);assert.equal(cancelled,true);assert.equal(transport.body.locked,false);
});

test('a reader failure remains the request error when cancellation also rejects',async()=>{
  let source;
  const transport=new ReadableStream({start(controller){source=controller;}}),failure=new Error('transport failed');
  const request=load(async()=>new Response(transport,{headers:{'Content-Type':'application/x-ndjson'}}));
  const pending=request('/suggest',{});
  await new Promise(resolve=>setImmediate(resolve));source.error(failure);
  await assert.rejects(()=>pending,error=>error===failure);assert.equal(transport.locked,false);
});

test('abort inside a progress callback prevents later events in the same chunk',async()=>{
  const controller=new AbortController(),messages=[];
  const transport=response([bytes(encode({type:'progress',stage:'model',message:'取消前'})+encode({type:'progress',stage:'preview',message:'取消后'})+encode({type:'result',result:{suggestions:[]}}))],{close:false});
  const request=load(async()=>transport);
  await assert.rejects(()=>request('/suggest',{},{signal:controller.signal,onProgress:event=>{messages.push(event.message);controller.abort();}}),error=>error.name==='AbortError');
  assert.deepEqual(messages,['取消前']);assert.equal(transport.body.locked,false);
});
