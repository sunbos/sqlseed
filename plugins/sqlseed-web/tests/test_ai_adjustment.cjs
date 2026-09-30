const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const {createDom, loadFrontend} = require('./frontend_helpers.cjs');

const tick = () => new Promise(resolve => setImmediate(resolve));
const catalog = {entries:[{id:'integer',params:[
  {name:'min_value',type:'integer',default:0}, {name:'max_value',type:'integer',default:100},
]}]};

function harness(request) {
  const document = createDom(), calls = [], committed = [], completed = [];
  const ui = loadFrontend('workbench/ui.js', {document});
  const labels = loadFrontend('labels.js', {document});
  const dropdown = loadFrontend('dropdown.js', {document});
  const calendar = loadFrontend('workbench/date-picker.js', {document});
  const editor = loadFrontend('workbench/editor.js', {document,
    createDropdown:dropdown.createDropdown, createDatePicker:calendar.createDatePicker,
    ...vm.runInContext('({genLabel,paramLabel,genGuide})', labels)});
  const context = loadFrontend('workbench/ai-adjustment.js', {document, AbortController,
    ...vm.runInContext('({button})', ui), createRuleEditor:editor.createRuleEditor,
    api:async (url, options) => {calls.push({url, options}); return request();}});
  const item = {table:'orders',column:'amount',after:{name:'amount',generator:'integer',params:{min_value:1,max_value:10}}};
  const column = {name:'amount',type:'INTEGER',nullable:false};
  const table = {name:'orders',columns:[column],primary_key:[],unique_constraints:[],foreign_keys:[]};
  let current = true;
  return {document, calls, committed, completed, item,
    stale:() => {current = false;},
    open:() => context.openSuggestionAdjustment({item,table,column,catalog:null,host:document.body,
      isCurrent:() => current, onCommit:value => committed.push(value), onDone:() => completed.push(true)}),
    button:label => document.querySelectorAll('button').find(element => element.textContent === label)};
}

test('failed adjustment metadata remains non-applicable and cancelling permits a successful retry', async () => {
  let fail = true;
  const ui = harness(() => {if (fail) throw new Error('metadata unavailable'); return catalog;});
  const before = JSON.stringify(ui.item);
  ui.open(); await tick();
  assert.match(ui.document.querySelector('[role="status"]').textContent, /无法读取规则编辑器/);
  assert.equal(ui.button('保存调整').disabled, true);
  assert.deepEqual(ui.committed, []);
  await ui.button('取消调整').click();
  assert.equal(ui.document.querySelector('.wb-ai-adjustment'), null);
  assert.equal(ui.calls[0].options.signal.aborted, true);
  fail = false;
  ui.open(); await tick();
  const minimum = ui.document.querySelector('[data-field="min_value"]');
  minimum.value = '3'; await minimum.dispatchEvent('input');
  assert.equal(ui.button('保存调整').disabled, false);
  await ui.button('保存调整').click();
  assert.equal(ui.committed.length, 1);
  assert.equal(ui.committed[0].params.min_value, 3);
  assert.equal(ui.committed[0].params.max_value, 10);
  assert.equal(JSON.stringify(ui.item), before);
  assert.deepEqual(ui.calls.map(call => call.url), ['/api/workbench/generators','/api/workbench/generators']);
  assert.equal(ui.completed.length, 2);
});

for (const action of ['close','stale']) test(`late adjustment metadata rejection respects ${action}`, async () => {
  let reject;
  const gate = new Promise((_, failed) => {reject = failed;});
  const ui = harness(() => gate), adjustment = ui.open();
  const notice = ui.document.querySelector('[role="status"]'), initial = notice.textContent;
  const before = JSON.stringify(ui.item);
  if (action === 'close') adjustment.close(); else ui.stale();
  reject(new Error('late metadata failure')); await tick();
  assert.deepEqual(ui.committed, []);
  assert.equal(JSON.stringify(ui.item), before);
  if (action === 'close') {
    assert.equal(ui.document.querySelector('.wb-ai-adjustment'), null);
    assert.equal(notice.textContent, initial);
    assert.equal(ui.calls[0].options.signal.aborted, true);
  } else {
    assert.match(notice.textContent, /配置已变化/);
    assert.equal(ui.button('保存调整').disabled, true);
    adjustment.close();
  }
});
