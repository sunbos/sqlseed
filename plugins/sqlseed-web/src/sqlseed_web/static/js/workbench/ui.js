import { h } from '../api.js';
import { lockPageScroll } from './scroll-lock.js';

const paths={
  sparkles:'m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5ZM20 2v4m-2-2h4',
  schema:'M12 7v5M5.5 17v-5h13v5',
  check:'m3 6 2 2 4-4M12 6h9M3 13h3m6 0h9M3 20h3m6 0h9',
  fields:'M3 9h18M9 9v11M3 14h18',
  save:'M4 3h13l4 4v14H3V3zM7 3v6h10V3M7 21v-8h10v8',
  download:'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',
  upload:'M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5',
  code:'m8 6-6 6 6 6m8-12 6 6-6 6m-3-14-2 16',
  refresh:'M3 11a9 9 0 0 1 15.4-6.4L21 7M21 3v4h-4M21 13a9 9 0 0 1-15.4 6.4L3 17M3 21v-4h4',
  database:'M4 5v7c0 4 16 4 16 0V5M4 12v7c0 4 16 4 16 0',
  link:'m10 13 4-4m-6 7-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 0 1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0',
  search:'m15 15 5 5',
  arrow:'M3 12h17m-5-5 5 5-5 5',
  edit:'m15 4 5 5M4 20l5-1L21 7l-5-5L4 14Z',
  reset:'M3 4v6h6M3 10a9 9 0 1 1 .6 7M12 7v5l3 2',
  sliders:'M4 6h6m4 0h6M4 12h10m4 0h2M4 18h2m4 0h10M10 3v6m4 0v6M6 15v6',
};
export function icon(name) {
  name={checklist:'check',table:'fields',db:'database',settings:'sliders'}[name] || name;
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  for(const [key,value] of Object.entries({class:'icon',viewBox:'0 0 24 24',width:16,height:16,fill:'none',stroke:'currentColor','stroke-width':1.5,'stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'})) svg.setAttribute(key,value);
  const shape=(tag,attrs,text)=>{
    const element=document.createElementNS('http://www.w3.org/2000/svg',tag);
    for(const [key,value] of Object.entries(attrs))element.setAttribute(key,value);
    if(text)element.textContent=text;
    svg.append(element);
  };
  if(name==='derive') {
    shape('text',{x:2,y:18,fill:'currentColor',stroke:'none','font-family':'Georgia,serif','font-style':'italic','font-size':20},'ƒx');
    return svg;
  }
  if(name==='schema')for(const [x,y,width,height] of [[8,2,8,5],[2,17,7,5],[15,17,7,5]])shape('rect',{x,y,width,height,rx:1});
  if(name==='fields')shape('rect',{x:3,y:4,width:18,height:16,rx:2});
  if(name==='database')shape('ellipse',{cx:12,cy:5,rx:8,ry:3});
  if(name==='search')shape('circle',{cx:10,cy:10,r:6});
  shape('path',{d:paths[name] || paths.fields,...(name==='link'?{transform:'translate(1 0)'}:{})});
  return svg;
}
export function button(label,action,{glyph,primary=false,small=false,plain=false,class:extraClass='',...attrs}={}) {
  const baseClass=plain?'wb-button':`btn wb-button${primary?' primary wb-primary':''}${small?' small wb-small':''}`;
  if(action?.databaseAction)attrs['data-db-action']='';
  return h('button',{type:'button',class:`${baseClass}${extraClass?' '+extraClass:''}`,onclick:action,...attrs},glyph?icon(glyph):null,label);
}
export function download(name,text,type='application/json') {
  const url=URL.createObjectURL(new Blob([text],{type}));
  const a=h('a',{href:url,download:name}); document.body.append(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
let activeModalClose=null;
export function modal(title,{onClose,wide=false,drawer=false}={}) {
  activeModalClose?.();
  let closed=false;
  const previous=document.activeElement;
  const unlockScroll=lockPageScroll();
  const background=[...document.body.children].map(element=>({element,inert:Boolean(element.inert)}));
  const body=h('div',{class:`${drawer?'drawer-body':'modal-body'} wb-modal-body`}),actions=h('div',{class:`${drawer?'drawer-footer':'modal-footer'} wb-modal-actions`});
  const close=()=>{
    if(closed)return;closed=true;overlay.remove();document.removeEventListener('keydown',key);
    unlockScroll();
    for(const {element,inert} of background)element.inert=inert;
    if(activeModalClose===close)activeModalClose=null;
    onClose?.();previous?.focus?.({preventScroll:true});
  };
  const header=h('header',{class:drawer?'drawer-head':'modal-head'},h('h2',{},title),
    h('button',{type:'button',class:'close','aria-label':'关闭',onclick:close},'×'));
  const panel=h('section',{class:`${drawer?'drawer':'modal'} wb-modal${drawer?' wb-drawer':''}${wide?' modal-wide wb-modal-wide':''}`,role:'dialog','aria-modal':'true','aria-label':title},header,body,actions);
  const overlay=h('div',{class:'overlay open wb-overlay'},panel);
  overlay.onclick=event=>{if(event.target===overlay)close();};
  function key(event) {
    if(event.key==='Escape') close();
    if(event.key==='Tab') {
      const summaryOf=details=>[...details.children].find(child=>child.tagName==='SUMMARY');
      const controls=[...overlay.querySelectorAll('button,input,textarea,a[href],summary')].filter(el=>{
        if(el.disabled || el.getAttribute('tabindex')==='-1')return false;
        if(el.tagName==='SUMMARY' && (el.parentElement?.tagName!=='DETAILS' || summaryOf(el.parentElement)!==el))return false;
        for(let ancestor=el;ancestor&&ancestor!==overlay;ancestor=ancestor.parentElement) {
          if(ancestor.hidden || ancestor.getAttribute('hidden')!==null)return false;
          if(ancestor.tagName==='DETAILS' && !ancestor.open && !summaryOf(ancestor)?.contains(el))return false;
        }
        return true;
      });
      const first=controls[0],last=controls.at(-1);
      if(event.shiftKey && document.activeElement===first){event.preventDefault();last?.focus();}
      else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first?.focus();}
    }
  }
  for(const {element} of background)element.inert=true;
  document.body.append(overlay);document.addEventListener('keydown',key);overlay.querySelector('button')?.focus();
  activeModalClose=close;
  return {body,actions,close,el:panel,overlay,header};
}
export function valueText(value) {
  if(value===null) return 'NULL';
  if(value===undefined) return '—';
  return typeof value==='object'?JSON.stringify(value):String(value);
}
