const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {loadFrontend} = require('./frontend_helpers.cjs');

function eligibility(table,column,rule) {
  const context=loadFrontend('workbench/ai-eligibility.js');
  context.args=[table,column,rule];
  return JSON.parse(JSON.stringify(vm.runInContext('fieldAIEligibility(...args)',context)));
}
const table={name:'orders',primary_key:['id'],foreign_keys:[{columns:['customer_id','region'],ref_table:'customers'}]};

for(const [column,rule,code] of [
  [{name:'id',is_primary_key:true,is_autoincrement:true},null,'database_generated'],
  [{name:'id'},null,'primary_key'],
  [{name:'customer_id'},null,'foreign_key'],
  [{name:'region'},null,'foreign_key'],
  [{name:'total',is_computed:true},null,'computed'],
  [{name:'total',default:'0'},{generator:'skip'},'database_default'],
  [{name:'total',default:'NULL'},null,'database_default'],
  [{name:'total',default:''},null,'database_default'],
  [{name:'total'},{derive_from:['quantity','price'],expression:'value[0]*value[1]'},'derived'],
  [{name:'total'},{expression:'row["quantity"]*2'},'derived'],
  [{name:'total'},{faker_method:'pyfloat'},'native'],
  [{name:'total'},{mimesis_method:'numeric.float_number'},'native'],
  [{name:'total'},{native_params:{provider:'faker'}},'native'],
]) test(`AI eligibility explains ${code}: ${column.name} ${JSON.stringify(rule)}`,()=>{
  const result=eligibility(table,column,rule);
  assert.equal(result.eligible,false);assert.equal(result.code,code);assert.ok(result.reason.length>5);
});

test('ordinary nullable NULL and empty advanced metadata remain AI-editable',()=>{
  for(const rule of [null,{generator:'skip'},{generator_name:'skip'},{generator:'float',native_params:{},derive_from:[]}]) {
    const result=eligibility(table,{name:'total',nullable:true,default:null},rule);
    assert.equal(result.eligible,true);assert.equal(result.reason,'');
  }
});

test('missing schema fields cannot advertise an actionable AI edit',()=>{
  assert.equal(eligibility(null,null,null).eligible,false);
});

test('DEFAULT only protects omitted values, not an active source generator',()=>{
  for(const rule of [{generator:'float'},{generator_name:'float'}])
    assert.equal(eligibility(table,{name:'balance',default:'0'},rule).eligible,true);
  assert.equal(eligibility({...table,mapping:{balance:{generator_name:'float'}}},{name:'balance',default:'0'},null).eligible,true);
  assert.equal(eligibility(table,{name:'balance',default:'0'},{generator:'float',derive_from:'amount',expression:'value'}).code,'derived');
});
