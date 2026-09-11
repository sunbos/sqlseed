const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {Element,createDom,loadFrontend}=require('./frontend_helpers.cjs');

function fixture({width=1144,maxHeight=800,above=250,rowHeights=Array(100).fill(39)}={}) {
  const document=createDom(),window=new Element('window');
  const modal=new Element('section'),body=new Element('div'),header=new Element('header'),actions=new Element('footer');
  const results=new Element('section'),summary=new Element('p'),scroll=new Element('div'),table=new Element('table');
  const thead=new Element('thead'),tbody=new Element('tbody'),error=new Element('p');
  modal.classList.add('modal','wb-data-preview');scroll.classList.add('wb-preview-scroll');
  body.append(error,results);results.append(summary,scroll);scroll.append(table);table.append(thead,tbody);
  for(const height of rowHeights){const row=new Element('tr');row.getBoundingClientRect=()=>({height});tbody.append(row);}
  modal.append(header,body,actions);document.body.append(modal);
  const geometry={width,maxHeight,above};
  const bodyLimit=()=>geometry.maxHeight-56-24-40;
  const tableHeight=()=>90+rowHeights.reduce((sum,height)=>sum+height,0);
  const scrollHeight=()=>Math.min(tableHeight()+10,parseFloat(scroll.style.maxHeight)||Infinity);
  let bodyTop=0,tableTop=0;
  Object.defineProperties(body,{
    clientTop:{get:()=>0},clientHeight:{get:bodyLimit},
    scrollHeight:{get:()=>geometry.above+scrollHeight()+4},
    scrollTop:{get:()=>bodyTop,set:value=>{bodyTop=Math.max(0,Math.min(value,body.scrollHeight-body.clientHeight));}},
  });
  Object.defineProperties(scroll,{
    offsetHeight:{get:scrollHeight},clientHeight:{get:()=>scrollHeight()-10},scrollHeight:{get:tableHeight},
    scrollTop:{get:()=>tableTop,set:value=>{tableTop=Math.max(0,Math.min(value,scroll.scrollHeight-scroll.clientHeight));}},
  });
  scroll.scrollLeft=240;
  body.getBoundingClientRect=()=>({top:100,height:bodyLimit()});
  scroll.getBoundingClientRect=()=>({top:100+geometry.above-body.scrollTop,height:scrollHeight()});
  header.getBoundingClientRect=()=>({height:24});actions.getBoundingClientRect=()=>({height:40});
  thead.getBoundingClientRect=()=>({height:90});
  const observers=[],frames=new Map();let nextFrame=0;
  class ResizeObserver {
    constructor(callback){this.callback=callback;this.targets=new Set();observers.push(this);}
    observe(node){this.targets.add(node);}
    disconnect(){this.targets.clear();}
  }
  const context=loadFrontend('workbench/preview-scroll-layout.js',{document,window,ResizeObserver,
    getComputedStyle:node=>({maxHeight:node===modal?`${geometry.maxHeight}px`:'none',
      paddingTop:node===modal?'28px':'4px',paddingBottom:node===modal?'28px':node===body?'4px':'0px',
      borderTopWidth:'0px',borderBottomWidth:'0px',marginTop:'0px',marginBottom:'0px'}),
    requestAnimationFrame:callback=>{frames.set(++nextFrame,callback);return nextFrame;},
    cancelAnimationFrame:id=>frames.delete(id),
  });
  Object.defineProperty(document.documentElement,'clientWidth',{get:()=>geometry.width});
  const create=vm.runInContext('createPreviewScrollLayout',context);
  const layout=create({dialog:{el:modal,body},results});
  const frame=()=>{const pending=[...frames.values()];frames.clear();for(const callback of pending)callback();};
  const resized=()=>{for(const observer of observers)observer.callback();frame();};
  return {layout,modal,body,scroll,table,thead,tbody,error,geometry,observers,frames,window,frame,resized};
}

test('desktop table budget subtracts real controls and reserves borders and horizontal scrollbar',()=>{
  const t=fixture();t.layout.setTable(t.scroll);
  assert.equal(t.modal.classList.contains('wb-preview-table-scroll'),true);
  assert.equal(t.scroll.style.maxHeight,'426px');
  assert.equal(t.body.scrollHeight,t.body.clientHeight);
  assert.ok(t.scroll.scrollHeight>t.scroll.clientHeight);
  assert.equal(t.scroll.scrollLeft,240);
  assert.equal(t.scroll.querySelector('table'),t.table);
  t.layout.destroy();
});

test('narrow, short, and control-heavy previews use the body without a nested table limit',()=>{
  for(const geometry of [{width:390},{maxHeight:400},{above:660}]) {
    const t=fixture(geometry);t.layout.setTable(t.scroll);
    assert.equal(t.modal.classList.contains('wb-preview-table-scroll'),false);
    assert.equal(t.scroll.style.maxHeight,'');
    assert.equal(t.scroll.scrollHeight,t.scroll.clientHeight);
    assert.ok(t.body.scrollHeight>t.body.clientHeight);
    t.layout.destroy();
  }
});

test('minimum readable space includes each of the first three differently wrapped rows',()=>{
  const t=fixture({rowHeights:[39,180,180,...Array(97).fill(39)]});t.layout.setTable(t.scroll);
  assert.equal(t.modal.classList.contains('wb-preview-table-scroll'),false);
  assert.equal(t.scroll.style.maxHeight,'');
  t.layout.destroy();
});

test('growing errors transfer the visible table offset to body scrolling and back',()=>{
  const t=fixture();t.layout.setTable(t.scroll);t.scroll.scrollTop=320;
  t.geometry.above=660;t.resized();
  assert.equal(t.modal.classList.contains('wb-preview-table-scroll'),false);
  assert.equal(t.body.scrollTop,320);assert.equal(t.scroll.scrollTop,0);
  assert.equal(t.scroll.scrollLeft,240);
  t.geometry.above=250;t.resized();
  assert.equal(t.modal.classList.contains('wb-preview-table-scroll'),true);
  assert.equal(t.scroll.scrollTop,320);assert.equal(t.body.scrollTop,0);
  t.layout.destroy();
});

test('reopening at another size restores the saved vertical offset into the current owner',()=>{
  for(const width of [390,1144]) {
    const t=fixture({width});t.layout.setTable(t.scroll);
    t.layout.restoreVertical(width===390?320:0,width===390?0:320);
    assert.equal(t.body.scrollTop,width===390?320:0);
    assert.equal(t.scroll.scrollTop,width===390?0:320);
    assert.equal(t.scroll.scrollLeft,240);
    t.layout.destroy();
  }
});

test('repeated observer delivery is stable and clearing results releases old row observers',()=>{
  const t=fixture();t.layout.setTable(t.scroll);t.scroll.scrollTop=200;
  t.resized();t.resized();
  assert.equal(t.scroll.style.maxHeight,'426px');assert.equal(t.scroll.scrollTop,200);
  const row=t.tbody.firstChild;
  assert.ok(t.observers.some(observer=>observer.targets.has(row)));
  t.layout.setTable(null);
  assert.equal(t.modal.classList.contains('wb-preview-table-scroll'),false);
  assert.equal(t.scroll.style.maxHeight,'');
  assert.equal(t.observers.some(observer=>observer.targets.has(row)||observer.targets.has(t.thead)),false);
  t.layout.destroy();
});

test('closing disconnects size observation and cancels queued layout work',()=>{
  const t=fixture();t.layout.setTable(t.scroll);
  for(const observer of t.observers)observer.callback();
  assert.equal(t.frames.size,1);
  t.layout.destroy();
  assert.equal(t.frames.size,0);
  assert.equal(t.observers.every(observer=>observer.targets.size===0),true);
  assert.equal(t.window.listeners.get('resize').size,0);
  t.geometry.above=660;t.frame();
  assert.equal(t.modal.classList.contains('wb-preview-table-scroll'),false);
});
