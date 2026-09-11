const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {loadFrontend} = require('./frontend_helpers.cjs');

function guide(provider,locale) {
  const context=loadFrontend('workbench/provider-guide.js');context.args=[provider,locale];
  return JSON.parse(JSON.stringify(vm.runInContext('providerGuide(...args)',context)));
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
