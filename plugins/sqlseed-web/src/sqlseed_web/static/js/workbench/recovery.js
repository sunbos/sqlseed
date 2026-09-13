// A new editable plan, never an automatic retry or a mutation of run history.
export function remainingRun(run) {
  const blocked=reason=>({ok:false,reason});
  if(run.status!=='error')return blocked('只有已结束的失败记录可计算剩余数量。');
  if(run.execution?.mode && run.execution.mode!=='append')return blocked('清空生成需重新核对完整计划，不能按追加数量恢复。');
  if(run.row_counts_exact!==true || run.count_complete===false)return blocked('提交数量不确定，请先核对数据库，不能自动计算剩余数量。');
  const configured=run.document?.tables,results=run.tables;
  const count=value=>Number.isSafeInteger(value)&&value>=0;
  if(!Array.isArray(configured)||!configured.length||!Array.isArray(results)||results.length!==configured.length)
    return blocked('逐表结果不完整，请核对数据库后调整配置。');
  const names=new Set(),remaining=[],tableDrafts={};let committed=0;
  for(const table of configured) {
    const matches=results.filter(result=>result.name===table.name),result=matches[0];
    if(names.has(table.name)||matches.length!==1||!count(table.count)||!count(result.rows_inserted)
      ||result.requested_count!==table.count||result.rows_inserted>table.count
      ||!['done','error','not_run'].includes(result.status)
      ||(result.status==='done'&&result.rows_inserted!==table.count)
      ||(result.status==='not_run'&&result.rows_inserted!==0))
      return blocked('逐表提交数量或状态不一致，请先核对数据库。');
    names.add(table.name);committed+=result.rows_inserted;
    const copy=structuredClone(table);copy.clear_before=false;
    if(table.count>result.rows_inserted)remaining.push({...copy,count:table.count-result.rows_inserted});
    else tableDrafts[table.name]=copy;
  }
  if(!count(run.rows_inserted)||committed!==run.rows_inserted)return blocked('总提交数量与逐表结果不一致，请先核对数据库。');
  if(!remaining.length)return blocked('计划行数已全部提交；请处理运行错误，无需再次生成。');
  return {ok:true,document:{...structuredClone(run.document),tables:remaining},tableDrafts};
}
