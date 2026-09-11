const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {loadFrontend}=require('./frontend_helpers.cjs');
const run=()=>({status:'error',execution:{mode:'append'},row_counts_exact:true,rows_inserted:125,
  document:{provider:'base',tables:[{name:'users',count:100,columns:[]},{name:'orders',count:100,columns:[{name:'amount',generator:'float'}]},{name:'items',count:100,seed:8,columns:[]}]},
  tables:[{name:'users',status:'done',requested_count:100,rows_inserted:100},{name:'orders',status:'error',requested_count:100,rows_inserted:25},{name:'items',status:'not_run',requested_count:100,rows_inserted:0}]});
function recover(record){const context=loadFrontend('workbench/recovery.js');context.record=record;return JSON.parse(JSON.stringify(vm.runInContext('remainingRun(record)',context)));}
test('remaining recovery subtracts committed rows and preserves immutable rules',()=>{
  const record=run(),before=structuredClone(record),result=recover(record);
  assert.equal(result.ok,true);assert.deepEqual(result.document.tables.map(t=>[t.name,t.count]),[['orders',75],['items',100]]);
  assert.deepEqual(result.document.tables[0].columns,record.document.tables[1].columns);assert.equal(result.document.tables[1].seed,8);
  assert.equal(result.tableDrafts.users.count,100);assert.deepEqual(record,before);
});
for(const change of [r=>r.status='running',r=>r.status='interrupted',r=>r.row_counts_exact=false,r=>r.row_counts_exact=undefined,r=>r.count_complete=false,r=>r.tables[1].rows_inserted=null,r=>r.tables[1].rows_inserted=101,r=>r.rows_inserted=124,r=>r.tables.pop(),r=>r.execution.mode='replace_selected',r=>r.tables[1].status='done'])test(`unsafe recovery stays blocked: ${change}`,()=>{const r=run();change(r);const result=recover(r);assert.equal(result.ok,false);assert.equal(result.document,undefined);assert.ok(result.reason);});
