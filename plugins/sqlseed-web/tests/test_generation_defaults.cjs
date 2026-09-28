const test = require('node:test');
const assert = require('node:assert/strict');
const {loadFrontend} = require('./frontend_helpers.cjs');

function harness(initial) {
  let stored = initial;
  const context = loadFrontend('generation-defaults.js', {window: {localStorage: {getItem: () => stored, setItem: (_, value) => {stored = value;}}}});
  return {context, saved: () => stored};
}
test('missing or malformed browser preferences preserve the caller new-document baseline', () => {
  for (const initial of [null, '{', JSON.stringify({provider:'oops',locale:'zh_CN',count:10})]) {
    const t = harness(initial), fallback = {provider:'faker',locale:'zh_TW',count:100};
    assert.equal(JSON.stringify(t.context.readGenerationDefaults(fallback)), JSON.stringify({...fallback,previewCount:10,seed:null}));
    assert.equal(t.saved(), initial);
  }
});
test('only validated preferences are stored, with independent objects on each read', () => {
  const t = harness(null);
  t.context.saveGenerationDefaults({provider:'mimesis',locale:'zh_CN',count:250, api_key:'not-stored',tables:[{name:'private'}]});
  assert.equal(t.saved(), '{"provider":"mimesis","locale":"zh_CN","count":250,"previewCount":10,"seed":null}');
  const first = t.context.readGenerationDefaults(); first.count = 999;
  assert.equal(t.context.readGenerationDefaults().count, 250);
});
test('invalid defaults and inaccessible browser storage never pretend to save', () => {
  const t = harness(null);
  for (const count of [0,-1,1.5,1000001,NaN,'100']) assert.throws(() => t.context.saveGenerationDefaults({provider:'faker',locale:'en_US',count}));
  assert.equal(t.saved(), null);
  const broken = loadFrontend('generation-defaults.js', {window: {get localStorage() {throw new Error('denied');}}});
  assert.equal(broken.readGenerationDefaults().count,100);
  assert.throws(() => broken.saveGenerationDefaults({provider:'faker',locale:'en_US',count:100}), /无法保存/);
});
test('preview and seed preferences migrate old values and reject unsafe input', () => {
  const t=harness(JSON.stringify({provider:'faker',locale:'zh_CN',count:40}));
  assert.equal(t.context.readGenerationDefaults().previewCount,10); assert.equal(t.context.readGenerationDefaults().seed,null);
  const base={provider:'faker',locale:'zh_CN',count:40,previewCount:30,seed:0};
  t.context.saveGenerationDefaults(base); assert.equal(t.context.readGenerationDefaults().seed,0);
  for(const value of [{...base,previewCount:101},{...base,previewCount:0},{...base,seed:-1},{...base,seed:1.5},{...base,seed:4294967296}]) assert.throws(()=>t.context.saveGenerationDefaults(value));
});

test('default-validation errors remain translatable without saving invalid preferences', () => {
  const t = harness(null);
  let error;
  try { t.context.saveGenerationDefaults({provider:'faker',locale:'zh_CN',count:0}); }
  catch (failure) { error = failure; }
  assert.ok(error);
  assert.match(String(t.context.errorText(error)), /1–1,000,000/);
  t.context.setLanguage('en');
  assert.match(String(t.context.errorText(error)), /row count must be an integer/);
  assert.equal(t.saved(), null);
});
