const assert = require('node:assert/strict');
const test = require('node:test');
const {createDom, loadFrontend} = require('./frontend_helpers.cjs');

const tick = () => new Promise(resolve => setImmediate(resolve));
const directory = (path, entries = []) => ({path, entries});
const entry = (name, path, is_dir, is_db = false) => ({name, path, is_dir, is_db, size: null});

function harness(request, mode = 'file') {
  const document = createDom(), requests = [], picked = [];
  const context = loadFrontend('filepicker.js', {document, get: path => {
    requests.push(path);
    return request(path);
  }});
  context.openFilePicker({mode, startPath: '/home', onPick: path => picked.push(path)});
  return {document, requests, picked,
    button: text => document.querySelectorAll('button').find(node => node.textContent === text)};
}

test('file picker reports an initial failure and Enter retry restores selectable files', async () => {
  let fail = true;
  const ui = harness(() => {
    if (fail) return Promise.reject(new Error('directory unavailable'));
    return Promise.resolve(directory('/recovered', [entry('sample.db', '/recovered/sample.db', false, true)]));
  });
  await tick();
  assert.match(ui.document.querySelector('.file-list').textContent, /directory unavailable/);
  fail = false;
  const input = ui.document.querySelector('.file-path-input');
  input.value = ' /recovered ';
  await input.dispatchEvent({type: 'keydown', key: 'Enter'});
  assert.equal(input.value, '/recovered');
  assert.deepEqual(ui.requests, ['/api/fs/browse?path=%2Fhome', '/api/fs/browse?path=%2Frecovered']);
  await ui.document.querySelector('.file-entry').dispatchEvent({type: 'keydown', key: 'Enter'});
  assert.deepEqual(ui.picked, ['/recovered/sample.db']);
  assert.equal(ui.document.querySelector('.modal-overlay'), null);
});

test('directory keyboard activation and show-all change return the completed listing', async () => {
  const ui = harness(path => Promise.resolve(path.includes('%2Fhome%2Fchild')
    ? directory('/home/child', [entry('data.db', '/home/child/data.db', false, true)])
    : directory('/home', [entry('child', '/home/child', true)])));
  await tick();
  await ui.document.querySelector('.file-entry').dispatchEvent({type: 'keydown', key: ' '});
  assert.equal(ui.document.querySelector('.file-path-input').value, '/home/child');
  const checkbox = ui.document.querySelector('input[type="checkbox"]');
  checkbox.checked = true;
  await checkbox.dispatchEvent('change');
  assert.equal(ui.requests.at(-1), '/api/fs/browse?path=%2Fhome%2Fchild&all_files=true');
  assert.match(ui.document.querySelector('.file-list').textContent, /data.db/);
});

test('stale directory failure does not replace a newer listing', async () => {
  let reject;
  const pending = new Promise((_, failed) => {reject = failed;});
  const ui = harness(path => path.includes('%2Fhome') ? pending : Promise.resolve(directory('/', [entry('current.db', '/current.db', false, true)])));
  await ui.button('主目录').click();
  assert.equal(ui.document.querySelector('.file-path-input').value, '/');
  reject(new Error('old listing failed'));
  await tick();
  assert.match(ui.document.querySelector('.file-list').textContent, /current.db/);
  assert.doesNotMatch(ui.document.querySelector('.file-list').textContent, /old listing failed/);
});

test('closing the picker consumes a late rejection without changing its detached contents', async () => {
  let reject;
  const pending = new Promise((_, failed) => {reject = failed;});
  const ui = harness(() => pending);
  const overlay = ui.document.querySelector('.modal-overlay'), before = overlay.textContent;
  await ui.button('取消').click();
  reject(new Error('closed picker failed'));
  await tick();
  assert.equal(ui.document.querySelector('.modal-overlay'), null);
  assert.equal(overlay.textContent, before);
  assert.deepEqual(ui.picked, []);
});
