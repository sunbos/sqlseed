import {h, api} from '../api.js';
import {modal, button, valueText} from './ui.js';

/** Read current database rows without changing the active connection or generation document. */
export function openTableData({connId=null, runId=null, table, targetKey, targetLabel='', isCurrent=()=>true}) {
  let closed=false, busy=false, controller=null, result=null;
  let connection=runId?null:connId;
  const limit=50;
  const dialog=modal('数据库当前数据',{wide:true,onClose:()=>{closed=true;controller?.abort();}});
  dialog.el.classList.add('wb-table-data');
  const target=h('p',{class:'mono wb-table-data-target'},targetLabel);
  const status=h('p',{class:'wb-table-data-status',role:'status','aria-live':'polite'},'正在读取数据库…');
  const error=h('p',{class:'wb-table-data-error',role:'alert'});
  const records=h('section',{class:'wb-table-data-records','aria-label':`${table} 当前记录`});
  const page=h('span',{class:'muted'});
  const refreshed=h('p',{class:'muted wb-table-data-read-at'});
  const ordering=h('p',{class:'muted wb-table-data-order'});
  const refreshButton=button('刷新数据',()=>load(result?.offset || 0));
  const previous=button('上一页',()=>load(Math.max(0,(result?.offset || 0)-limit)));
  const next=button('下一页',()=>load((result?.offset || 0)+limit));
  dialog.body.append(h('div',{class:'wb-table-data-heading'},h('h3',{class:'mono'},table),refreshButton),target,
    h('p',{class:'muted'},'查询时表内的实际记录，可能包含原有、本次提交及后续变化的数据；不是某次运行的数据快照。'),
    status,error,records,h('div',{class:'wb-table-data-pagination'},page,h('div',{},previous,next)),refreshed,ordering);
  dialog.actions.append(button('关闭',dialog.close));
  const live=()=>!closed && dialog.el.isConnected && isCurrent();
  function setBusy(value) {
    busy=value;refreshButton.disabled=value;
    previous.disabled=value || !result || result.offset===0;
    next.disabled=value || !result || result.offset+result.limit>=result.total;
    records.setAttribute('aria-busy',String(value));
  }
  function displayValue(value) {
    const text=valueText(value);
    return text.length>160?h('details',{class:'wb-table-data-value'},
      h('summary',{},`${text.slice(0,80)}… 展开完整值`),h('pre',{},text)):text;
  }
  function render(data) {
    target.textContent=`${data.dialect==='postgresql'?'PostgreSQL':data.dialect==='sqlite'?'SQLite':data.dialect} · ${data.target_label}`;
    const grid=h('table',{},h('caption',{},`${table} · 数据库当前数据`),
      h('thead',{},h('tr',{},...data.columns.map(column=>h('th',{scope:'col'},
        h('span',{class:'mono'},column.name),h('small',{},[column.type,column.is_primary_key?'PK':null].filter(Boolean).join(' · ')))))),
      h('tbody',{},...data.rows.map(row=>h('tr',{},...data.columns.map(column=>h('td',{},displayValue(row[column.name])))))));
    records.replaceChildren(h('div',{class:'wb-table-data-scroll',tabindex:0,'aria-label':`${table} 当前数据，可横向滚动`},grid),
      ...(data.rows.length?[]:[h('p',{class:'wb-table-data-empty'},data.total?'本页暂无记录，请返回上一页或刷新。':'表中暂无记录。')]));
    page.textContent=`${data.rows.length?`${data.offset+1}–${data.offset+data.rows.length}`:'0'} / ${data.total} 行 · 每页 ${limit} 行`;
    const date=new Date(data.read_at);
    refreshed.textContent=`读取时间：${Number.isNaN(date.getTime())?data.read_at:date.toLocaleString('zh-CN',{hour12:false})}`;
    ordering.textContent=data.order_by?.length?`按主键 ${data.order_by.join('、')} 排序；数据库变化时，不同页的内容可能随之变化。`:
      '此表没有主键，分页顺序可能变化。';
  }
  async function load(offset=0) {
    if(!live() || busy)return;
    controller=new AbortController();setBusy(true);error.textContent='';
    status.textContent=result?'正在刷新，暂时保留上次读取的记录…':'正在读取数据库…';
    try {
      if(!connection && runId) {
        const matched=await api(`/api/workbench/runs/${encodeURIComponent(runId)}/data-connections`,{signal:controller.signal});
        if(!live())return;
        if(matched.target_key!==targetKey)throw new Error('运行记录的数据库目标已变化，请重新打开。');
        connection=matched.connections?.[0]?.conn_id || null;
        if(!connection)throw new Error('请先连接此运行的相同数据库：关闭面板，通过顶栏连接数据库，然后重新查看。');
      }
      if(!connection)throw new Error('连接已失效，请重新连接数据库后查看。');
      const params=new URLSearchParams({limit:String(limit),offset:String(offset)});
      if(runId)params.set('run_id',runId);
      const data=await api(`/api/workbench/connections/${encodeURIComponent(connection)}/tables/${encodeURIComponent(table)}/data?${params}`,{signal:controller.signal});
      if(!live())return;
      if(data.target_key!==targetKey || data.table!==table)throw new Error('返回数据的目标或表不匹配，请重新打开。');
      result=data;render(data);status.textContent='已读取数据库当前数据。';
    } catch(failure) {
      if(!live() || failure.name==='AbortError')return;
      if(runId && failure.status===404)connection=null;
      error.textContent=`无法读取数据：${failure.message}`;
      status.textContent=result?'仍显示上次读取的记录。':'尚未读取到数据库记录。';
    } finally {if(live())setBusy(false);}
  }
  const ready=load();
  return {dialog,ready,refresh:()=>load(result?.offset || 0),close:dialog.close};
}
