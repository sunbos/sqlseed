import {tr, joinText, formatNumber} from '../i18n.js';
import '../i18n/messages/flow.js';
// Guidance describes evidence already available to the workbench. It never
// changes rules, starts AI, or grants permission to write data.
export function nextStep(model, previews = new Map()) {
  const tables=model.document.tables;
  const invalidCount=[...model.errors.keys()].some(key=>key.startsWith('count:'));
  const total=invalidCount ? null : tables.reduce((sum,table)=>sum+BigInt(table.count),0n);
  const scope=invalidCount ? tr("flow.guide.invalidScope", {count: tables.length}) : tr("flow.guide.scope", {count: tables.length, rows: formatNumber(total)});
  if(!tables.length)return {stage:1,scope:tr("flow.guide.noSelection"),title:tr("flow.guide.chooseTitle"),body:tr("flow.guide.chooseBody"),action:'select',label:tr("flow.guide.chooseAction")};
  if(model.errors.size)return {stage:1,scope,title:tr("flow.guide.invalidTitle"),body:joinText([...model.errors.values()], '；'),action:'edit',label:tr("flow.guide.invalidAction")};
  if(model.check?.issues?.some(issue=>issue.severity==='error'))return {stage:1,scope,title:tr("flow.guide.issueTitle"),body:tr("flow.guide.issueBody"),action:'check',label:tr("flow.guide.issueAction")};
  const current=new Set(tables.filter(table=>{
    const preview=previews.get(table.name);
    return preview?.epoch===model.epoch && preview.result.ok && preview.result.preview_complete!==false
      && Array.isArray(preview.result.samples?.[table.name]) && preview.result.samples[table.name].length>0;
  }).map(table=>table.name));
  if(current.size===tables.length)return {stage:3,scope,title:tr("flow.guide.previewedTitle", {count: tables.length}),body:tr("flow.guide.previewedBody"),action:'generate',label:tr("flow.guide.planAction")};
  const applied=model.aiApplied?.epoch===model.epoch?model.aiApplied.targets.filter(item=>tables.some(table=>table.name===item.table)):[];
  if(applied.some(item=>!current.has(item.table)))return {stage:2,scope,title:tr("flow.guide.aiAppliedTitle", {count: applied.length}),body:tr("flow.guide.aiAppliedBody"),action:'preview',label:tr("flow.guide.aiPreviewAction")};
  if(current.size)return {stage:2,scope,title:tr("flow.guide.partialTitle", {previewed: current.size, total: tables.length}),body:tr("flow.guide.partialBody"),action:'preview',label:tr("flow.guide.previewSelected")};
  if(tables.some(table=>previews.get(table.name)?.epoch<model.epoch))return {stage:2,scope,title:tr("flow.guide.changedTitle"),body:tr("flow.guide.changedBody"),action:'preview',label:tr("flow.guide.previewAgain")};
  if(tables.some(table=>previews.get(table.name)?.epoch===model.epoch))return {stage:2,scope,title:tr("flow.guide.unavailableTitle"),body:tr("flow.guide.unavailableBody"),action:'check',label:tr("flow.guide.checkDependencies")};
  return {stage:1,scope,title:tr("flow.guide.reviewTitle"),body:tr("flow.guide.reviewBody"),action:'preview',label:tr("flow.guide.previewNow")};
}

export function guideAIState(config) {
  if(config?.availability_status==='import_error')return {label:tr("flow.guide.checkAI"),status:tr("flow.guide.aiImportError")};
  if(config?.available===false)return {label:tr("flow.guide.installAI"),status:tr("flow.guide.aiMissing")};
  if(config?.available && !config.ready)return {label:tr("flow.guide.configureAI"),status:tr("flow.guide.aiNeedsSetup")};
  if(config?.ready)return {label:tr("flow.guide.useAI"),status:tr("flow.guide.aiConfigured")};
  return {label:tr("flow.guide.viewAI"),status:tr("flow.guide.aiUnknown")};
}
