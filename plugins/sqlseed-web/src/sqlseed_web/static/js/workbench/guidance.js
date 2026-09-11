// Guidance describes evidence already available to the workbench. It never
// changes rules, starts AI, or grants permission to write data.
export function nextStep(model, previews = new Map()) {
  const tables=model.document.tables;
  const scope=`已选 ${tables.length} 张表 · 计划生成 ${tables.reduce((sum,table)=>sum+table.count,0)} 行`;
  if(!tables.length)return {scope:'尚未选择生成表',title:'先选择要生成的表',body:'在左侧勾选本次需要生成数据的表，再设置每张表的生成数量。浏览表名不会加入生成范围。',action:'select',label:'选择生成表'};
  if(model.errors.size)return {scope,title:'先修正无效输入',body:[...model.errors.values()].join('；'),action:'edit',label:'检查输入'};
  if(model.check?.issues?.some(issue=>issue.severity==='error'))return {scope,title:'先处理检查发现的问题',body:'查看具体字段、引用来源和处理建议，修正后重新检查。',action:'check',label:'查看检查问题'};
  const current=new Set(tables.filter(table=>{
    const preview=previews.get(table.name);
    return preview?.epoch===model.epoch && preview.result.ok && preview.result.preview_complete!==false
      && Array.isArray(preview.result.samples?.[table.name]) && preview.result.samples[table.name].length>0;
  }).map(table=>table.name));
  if(current.size===tables.length)return {scope,title:`已预览所选 ${tables.length} 张表`,body:'请确认样例符合业务要求。下一步查看写入计划，系统会重新检查依赖；确认后才写入数据库。',action:'generate',label:'查看生成计划'};
  const applied=model.aiApplied?.epoch===model.epoch?model.aiApplied.targets.filter(item=>tables.some(table=>table.name===item.table)):[];
  if(applied.some(item=>!current.has(item.table)))return {scope,title:`已应用 ${applied.length} 条 AI 建议，请预览`,body:'建议已进入当前生成配置。请查看实际样例，核对业务要求是否都已覆盖；AI 建议不代表数据库写入一定成功。',action:'preview',label:'预览 AI 调整结果'};
  if(current.size)return {scope,title:`已预览 ${current.size}/${tables.length} 张所选表`,body:'可以继续查看其余表的样例，再核对写入计划。预览不会写入数据库。',action:'preview',label:'预览已选范围'};
  if(tables.some(table=>previews.get(table.name)?.epoch<model.epoch))return {scope,title:'配置已变化，请重新预览',body:'已有样例对应之前的规则或生成范围。重新查看样例，确认本次配置的实际效果。',action:'preview',label:'重新预览'};
  if(tables.some(table=>previews.get(table.name)?.epoch===model.epoch))return {scope,title:'部分样例暂不可用',body:'查看预览中的具体原因；依赖尚未生成的父键时，可先核对依赖计划。',action:'check',label:'检查依赖'};
  return {scope,title:'先确认规则是否符合业务',body:'检查数值范围、日期和字段含义。可以手动调整，也可让 AI 根据业务说明建议规则；已有配置合适时可直接预览。',action:'preview',label:'直接预览'};
}

export function guideAIState(config) {
  if(config?.availability_status==='import_error')return {label:'检查 AI 插件',status:'插件加载异常 · 规则建议不可用'};
  if(config?.available===false)return {label:'安装 AI 扩展',status:'AI 扩展未安装 · 规则建议不可用'};
  if(config?.available && !config.ready)return {label:'配置 AI 助手',status:'可选 · 需配置服务'};
  if(config?.ready)return {label:'用 AI 建议规则',status:'可选 · 服务配置已填写'};
  return {label:'查看 AI 助手',status:'可选 · 状态待确认'};
}
