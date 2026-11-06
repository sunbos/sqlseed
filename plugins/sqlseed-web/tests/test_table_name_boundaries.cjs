const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {loadFrontend} = require('./frontend_helpers.cjs');
const {harness, schema, plain} = require('./workbench_harness.cjs');

for (const name of ['ordinary', '__proto__', 'constructor', 'toString']) {
  test(`completed ${name} recovery retains its editable draft through JSON`, () => {
    const record = {status:'error', execution:{mode:'append'}, row_counts_exact:true, rows_inserted:7,
      document:{tables:[{name,count:7,seed:42,columns:[{name:'amount',generator:'integer',params:{min_value:4}}]},
        {name:'unfinished',count:9,columns:[]}]},
      tables:[{name,status:'done',requested_count:7,rows_inserted:7},
        {name:'unfinished',status:'error',requested_count:9,rows_inserted:0}]};
    const before = structuredClone(record);
    const context = loadFrontend('workbench/recovery.js'); context.record = record;
    const result = vm.runInContext('remainingRun(record)', context);
    assert.equal(result.ok, true);
    assert.deepEqual(record, before);
    assert.equal(Object.hasOwn(result.tableDrafts, name), true);
    assert.equal(Object.getPrototypeOf(result.tableDrafts), vm.runInContext("Object.getPrototypeOf({})", context));
    const restored = plain(result);
    assert.equal(restored.tableDrafts[name].seed, 42);
    assert.deepEqual(restored.document.tables.map(table=>table.name), ['unfinished']);
    const modelContext = loadFrontend('workbench/model.js');
    modelContext.schema = {tables:[{name},{name:'unfinished'}]}; modelContext.doc = restored.document;
    const model = vm.runInContext('new WorkbenchDocument(schema, doc)', modelContext);
    model.restoreView({tableDrafts:restored.tableDrafts}); model.toggleTable(name, true);
    assert.equal(model.table(name).count, 7);
    assert.equal(model.table(name).columns[0].params.min_value, 4);
  });

  test(`${name} can be selected, edited, deselected and restored`, () => {
    const context = loadFrontend('workbench/model.js'); context.schema = {tables:[{name}]};
    const model = vm.runInContext('new WorkbenchDocument(schema)', context);
    assert.equal(model.table(name).name, name);
    const originalPrototype = Object.getPrototypeOf(model.view.tableDrafts);
    model.toggleTable(name, true); model.setCount(name, '17');
    model.setColumn(name, 'amount', {generator:'integer',params:{min_value:7}});
    model.toggleTable(name, false);
    assert.equal(Object.getPrototypeOf(model.view.tableDrafts), originalPrototype);
    const saved = plain(model.payload('test'));
    assert.equal(Object.hasOwn(saved.view_state.tableDrafts, name), true);
    context.doc = saved.document;
    const restored = vm.runInContext('new WorkbenchDocument(schema, doc)', context);
    restored.restoreView(saved.view_state); restored.toggleTable(name, true);
    assert.equal(restored.table(name).count, 17);
    assert.equal(restored.table(name).columns[0].params.min_value, 7);
  });

  test(`${name} workbench edits its count only after explicit selection without writing`, async () => {
    const ui = harness(); const data = schema(); const table = data.tables[0]; table.name = name;
    data.tables = [table]; data.nodes = [{id:name}]; data.edges = [];
    ui.routes.set('/api/workbench/connections/A/schema', ()=>data);
    try {
      await ui.mount();
      let input = ui.root().querySelector(`[aria-label="${name} 生成数量"]`);
      assert.ok(input, 'count control must render');
      assert.equal(String(input.value), '100');
      assert.equal(input.disabled, true);
      const checkbox = ui.root().querySelector(`[data-table="${name}"]`).querySelector('input[type="checkbox"]');
      checkbox.checked = true; await checkbox.dispatchEvent('change');
      input = ui.root().querySelector(`[aria-label="${name} 生成数量"]`);
      assert.equal(input.disabled, false);
      input.value = '19'; await input.dispatchEvent('input');
      assert.equal(ui.modelState().table(name).count, 19);
      assert.equal(ui.modelState().selected(name), true);
      assert.equal(ui.requests.some(request=>request.url==='/api/workbench/runs'), false);
    } finally {ui.leave();}
  });
}

for (const name of ['ordinary', '__proto__', 'constructor', 'toString']) {
  test(`${name} invalid count survives restoration and correction without selecting`, () => {
    const context = loadFrontend('workbench/model.js'); context.schema = {tables:[{name}]};
    const model = vm.runInContext('new WorkbenchDocument(schema)', context);
    assert.equal(model.setCount(name, '1.5'), false);
    assert.equal(model.countInput(name), '1.5');
    assert.equal(model.inputIssues()[0].value, '1.5');
    assert.throws(()=>model.payload('invalid'));
    const savedView = plain(model.view);
    const restored = vm.runInContext('new WorkbenchDocument(schema)', context);
    restored.restoreView(savedView);
    assert.equal(restored.countInput(name), '1.5');
    assert.equal(restored.inputIssues()[0].value, '1.5');
    restored.setCount(name, '11');
    assert.equal(restored.countInput(name), 11);
    assert.equal(restored.errors.size, 0);
    assert.equal(restored.selected(name), false);
    assert.equal(plain(restored.payload('valid')).view_state.tableDrafts[name].count, 11);
  });

  test(`${name} column patches preserve unselected rules across JSON restoration`, () => {
    const context = loadFrontend('workbench/model.js');
    context.schema = {tables:[{name,columns:[{name:'amount'}]}]};
    const model = vm.runInContext('new WorkbenchDocument(schema)', context);
    model.applyPatches([{table:name,column:'amount',after:{generator:'integer',params:{min_value:13}}}]);
    const saved = plain(model.payload('patched'));
    assert.equal(saved.document.tables.length, 0);
    assert.equal(Object.hasOwn(saved.view_state.tableDrafts, name), true);
    const restored = vm.runInContext('new WorkbenchDocument(schema)', context);
    restored.restoreView(saved.view_state); restored.toggleTable(name, true);
    assert.equal(restored.table(name).columns[0].params.min_value, 13);
  });

  test(`${name} completed run route retains original rules without submitting a run`, async () => {
    const ui = harness(); const data = schema(); data.tables[0].name = name;
    data.tables = [data.tables[0], data.tables[2]]; data.nodes = [{id:name},{id:'audit'}]; data.edges = [];
    const run = {id:'partial',name:'Partial',status:'error',target_key:'target-A',row_counts_exact:true,
      rows_inserted:13,execution:{mode:'append'},document:{provider:'base',tables:[
        {name,count:10,seed:23,columns:[{name:'amount',generator:'integer',params:{min_value:6}}]},
        {name:'audit',count:10,columns:[]}]},tables:[
        {name,status:'done',requested_count:10,rows_inserted:10},
        {name:'audit',status:'error',requested_count:10,rows_inserted:3}]};
    const before = structuredClone(run);
    ui.routes.set('/api/workbench/connections/A/schema',()=>data);
    ui.routes.set('/api/workbench/runs/partial',()=>run);
    ui.location.hash = '#/workbench?run=partial&recover=remaining';
    try {
      await ui.mount(); const model = ui.modelState();
      assert.deepEqual(plain(model.document.tables.map(table=>[table.name,table.count])), [['audit',7]]);
      assert.equal(model.selected(name), false);
      const saved = plain(model.payload('recovery'));
      assert.equal(saved.view_state.tableDrafts[name].seed, 23);
      assert.equal(saved.view_state.tableDrafts[name].columns[0].params.min_value, 6);
      assert.deepEqual(run, before);
      assert.equal(ui.requests.some(request=>request.url==='/api/workbench/runs'), false);
    } finally {ui.leave();}
  });
}

for (const name of ['ordinary', '__proto__', 'constructor', 'toString']) {
  for (const [tableName, column] of [['ordinary', name], [name, 'amount']]) {
    test(`rule lookup treats ${tableName}.${column} as data through reflected and checked rules`, () => {
      const context = loadFrontend('workbench/model.js');
      context.schema = {tables:[{name:tableName,columns:[{name:column}],mapping:{}}]};
      const model = vm.runInContext('new WorkbenchDocument(schema)', context);
      assert.deepEqual(plain(model.rule(tableName, column)), {});
      model.schema.tables[0].mapping = JSON.parse(JSON.stringify({[column]:{generator_name:'integer',params:{min_value:3}}}));
      assert.equal(model.rule(tableName, column).params.min_value, 3);
      model.check = {effective_rules:{}};
      assert.equal(model.rule(tableName, column).params.min_value, 3);
      model.check.effective_rules = JSON.parse(JSON.stringify({[tableName]:{[column]:{generator_name:'integer',params:{min_value:9}}}}));
      const returned = model.rule(tableName, column);
      assert.equal(returned.params.min_value, 9);
      returned.params.min_value = 100;
      assert.equal(model.check.effective_rules[tableName][column].params.min_value, 9);
    });
  }
}
