import {tr} from '../i18n.js';
import '../i18n/messages/components.js';
// A new editable plan, never an automatic retry or a mutation of run history.
export function remainingRun(run) {
  const blocked=reason=>({ok:false,reason});
  if(run.status!=='error')return blocked(tr('recovery.onlyFailed'));
  if(run.execution?.mode && run.execution.mode!=='append')return blocked(tr('recovery.replacement'));
  if(run.row_counts_exact!==true || run.count_complete===false)return blocked(tr('recovery.uncertain'));
  const configured=run.document?.tables,results=run.tables;
  const count=value=>Number.isSafeInteger(value)&&value>=0;
  if(!Array.isArray(configured)||!configured.length||!Array.isArray(results)||results.length!==configured.length)
    return blocked(tr('recovery.incomplete'));
  const names=new Set(),remaining=[],tableDrafts={};let committed=0;
  for(const table of configured) {
    const matches=results.filter(result=>result.name===table.name),result=matches[0];
    if(names.has(table.name)||matches.length!==1||!count(table.count)||!count(result.rows_inserted)
      ||result.requested_count!==table.count||result.rows_inserted>table.count
      ||!['done','error','not_run'].includes(result.status)
      ||(result.status==='done'&&result.rows_inserted!==table.count)
      ||(result.status==='not_run'&&result.rows_inserted!==0))
      return blocked(tr('recovery.inconsistentTable'));
    names.add(table.name);committed+=result.rows_inserted;
    const copy=structuredClone(table);copy.clear_before=false;
    if(table.count>result.rows_inserted)remaining.push({...copy,count:table.count-result.rows_inserted});
    else tableDrafts[table.name]=copy;
  }
  if(!count(run.rows_inserted)||committed!==run.rows_inserted)return blocked(tr('recovery.inconsistentTotal'));
  if(!remaining.length)return blocked(tr('recovery.complete'));
  return {ok:true,document:{...structuredClone(run.document),tables:remaining},tableDrafts};
}
