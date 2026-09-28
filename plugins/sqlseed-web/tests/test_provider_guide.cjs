const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {loadFrontend} = require('./frontend_helpers.cjs');

function guide(provider,locale) {
  const context=loadFrontend('workbench/provider-guide.js');context.args=[provider,locale];
  return JSON.parse(JSON.stringify(vm.runInContext('providerGuide(...args)',context), (_, value) => context.isLocalized(value) ? String(value) : value));
}
test('provider guidance follows selection and distinguishes localized examples from live samples',()=>{
  const faker=guide('faker','zh_CN'),mimesis=guide('mimesis','en_US');
  assert.equal(faker.id,'faker');assert.equal(faker.recommended,true);
  assert.equal(mimesis.id,'mimesis');assert.equal(mimesis.recommended,false);
  assert.match(faker.examples.find(item=>item.label==='姓名').value,/[\u4e00-\u9fff]/);
  assert.match(mimesis.examples.find(item=>item.label==='姓名').value,/[a-z]+ [a-z]+/i);
  for(const value of [faker,mimesis]) {
    assert.match(value.exampleNote,/格式示例/);assert.match(value.exampleNote,/非实时/);
    assert.ok(value.features.length);assert.ok(value.limits.length);assert.ok(value.sources.every(item=>/^https:\/\//.test(item.url)));
  }
});
test('Base explains placeholder name output even when Chinese locale is selected',()=>{
  const base=guide('base','zh_CN');
  assert.match(base.summary,/占位/);assert.equal(base.recommended,false);
  assert.match(base.examples.find(item=>item.label==='姓名').value,/^first_\d{3}_\d{4} last_\d{3}_\d{4}$/);
  assert.match(base.limits.join(' '),/姓名|语言/);
});
test('unknown providers are identified honestly without silently recommending a replacement',()=>{
  const unknown=guide('custom-provider','zh_CN');
  assert.equal(unknown.id,'custom-provider');assert.equal(unknown.recommended,false);
  assert.equal(unknown.examples.length,0);assert.match(unknown.summary,/说明/);
});

test('provider and generator copy switches language while data locale examples and extension identifiers remain opaque',()=>{
  const context=loadFrontend('workbench/provider-guide.js');
  const result=context.providerGuide('faker','zh_CN');
  const missing=context.providerGuide('');
  assert.equal(String(result.examples[0].label),'姓名');
  context.setLanguage('en');
  assert.equal(String(result.examples[0].label),'Name'); assert.equal(result.examples[0].value,'王小明');
  assert.match(String(result.exampleNote),/not live/i); assert.doesNotMatch(String(missing.title),/[\u4e00-\u9fff]/);
  const labels=loadFrontend('labels.js');
  const label=labels.genLabel('integer'),param=labels.paramLabel('min_value'),description=labels.genGuide('integer').purpose;
  labels.setLanguage('en');
  assert.equal(String(label),'Integer'); assert.equal(String(param),'Minimum value');
  assert.doesNotMatch(String(description),/[\u4e00-\u9fff]/);
  assert.equal(labels.genLabel('我的扩展'),'我的扩展'); assert.equal(labels.paramLabel('我的参数'),'我的参数');
  assert.deepEqual(Array.from(context.missingMessages()),[]); assert.deepEqual(Array.from(labels.missingMessages()),[]);
});
