// One in-memory, explicitly requested trip to settings. No document edits,
// suggestions, credentials, URL payloads or browser storage belong here.
let pending=null;
const valid=connId=>Boolean(pending && pending.connId===connId
  && pending.model.epoch===pending.epoch
  && pending.model.lifecycleVersion===pending.lifecycle
  && pending.model.schema.schema_hash===pending.schemaHash
  && pending.model.schema.target_key===pending.targetKey
  && pending.model.saved?.id===pending.savedId);
export function clearAIHandoff(){pending=null;}
export function rememberAIHandoff({model,connId,returnTo,context}){
  pending={model,connId,returnTo,context:structuredClone(context),armed:false,
    epoch:model.epoch,lifecycle:model.lifecycleVersion,schemaHash:model.schema.schema_hash,
    targetKey:model.schema.target_key,savedId:model.saved?.id};
}
export function peekAIHandoff(connId){
  if(!valid(connId)){pending=null;return null;}
  return {returnTo:pending.returnTo};
}
export function requestAIReturn(connId){
  if(!peekAIHandoff(connId))return null;
  pending.armed=true;return pending.returnTo;
}
export function leaveAISettings(destinationHash){
  if(!pending?.armed || pending.returnTo!==destinationHash)pending=null;
}
export function consumeAIHandoff({model,connId,returnTo}){
  const context=valid(connId)&&pending.armed&&pending.model===model&&pending.returnTo===returnTo
    ?structuredClone(pending.context):null;
  pending=null;return context;
}
