// 可运行的组件参考：固定样例，无业务请求；组件实现与正式工作台共用。
import { h, table } from './api.js';
import { button, icon, modal } from './workbench/ui.js';
import { createDropdown } from './dropdown.js';
import { createDatePicker } from './workbench/date-picker.js';
import { createSchemaGraph } from './workbench/graph.js';
import { createThemeControl } from './theme-control.js';
import './tab-motion.js';

const root = document.getElementById('design-reference');
const disposables = [];
const themeSlot = document.querySelector('[data-theme-control]');
if (themeSlot) {
  const themeControl = createThemeControl();
  themeSlot.append(themeControl.el);
  disposables.push(themeControl);
}
let activeLayer = null;
let loadingTimer = null;
let appliedRule = { generator: 'integer', minimum: '18', date: '2026-09-26' };

function status(text) {
  return h('p', { class: 'muted ds-status', role: 'status', 'aria-live': 'polite' }, text);
}
function notes(...items) {
  const action = h('span', { class: 'disclosure-action', 'aria-hidden': 'true' }, '展开');
  const details = h('details', { class: 'ds-notes' },
    h('summary', {}, icon('check'), h('span', {}, '验收时看什么'), action),
    h('ul', {}, items.map(item => h('li', {}, item))));
  details.addEventListener('toggle', () => { action.textContent = details.open ? '收起' : '展开'; });
  return details;
}
function section(id, title, description, glyph, ...children) {
  return h('section', { id, class: 'settings-panel ds-section', 'aria-labelledby': `${id}-title` },
    h('div', { class: 'ds-section-heading' }, icon(glyph), h('h2', { id: `${id}-title` }, title)),
    h('p', { class: 'muted' }, description), ...children);
}
function field(label, control, hint) {
  return h('div', { class: 'control ds-control' },
    h('label', {}, h('span', { class: 'editor-control-label' }, label), control),
    hint ? h('small', { class: 'muted' }, hint) : null);
}
function surface(kind, title, description, token) {
  return h('div', { class: `${kind} ds-surface` }, h('h3', {}, title),
    h('code', { class: 'mono' }, token), h('p', { class: 'muted' }, description));
}

const intro = h('div', { class: 'ds-intro' },
  h('p', { class: 'crumb' }, 'SQLSEED / DESIGN REFERENCE'),
  h('h1', {}, '把设计变成可操作的标准。'),
  h('p', {}, '直接试用正式工作台的控件，观察焦点、选中、错误和浮层。这里的样例与 8630 共用样式和组件源码。'),
  h('p', { class: 'wb-settings-note' }, '交互样例，不连接数据库。表、日期和配置均为固定样例；页面不会保存业务配置或生成数据。'));
const sections = [
  ['foundation', '材质与文字'], ['controls', '基础控件'], ['pickers', '下拉与日期'],
  ['layers', '弹窗与抽屉'], ['relationships', '关系图'], ['references', '设计依据']
];
const nav = h('nav', { class: 'ds-nav', 'aria-label': '组件目录' },
  sections.map(([id, title]) => h('a', { href: `#${id}`, class: 'btn small' }, title)));
root.append(intro, nav);

const readingTable = table(['#', '字段', '规则', '示例'], [
  ['01', h('code', { class: 'mono' }, 'full_name'), '姓名', '周书宁'],
  ['02', h('code', { class: 'mono' }, 'email'), '电子邮箱', 'shuning@example.test'],
  ['03', h('code', { class: 'mono' }, 'age'), '整数范围', '36']
]);
readingTable.classList.add('wb-preview-data');
root.append(section('foundation', '材质与文字', '透明度服从信息层级。功能层轻盈，数据与代码保持稳定阅读。', 'fields',
  h('div', { class: 'ds-grid ds-grid-three' },
    surface('wb-config-context', '控制层', '用于配置工具栏与导航，柔和区分背景。', '--glass'),
    surface('wb-content', '阅读层', '用于字段、记录和配置正文，减少背景干扰。', '--paper'),
    surface('drawer-help', '内嵌说明', '用于规则说明与样例，边缘保持自然。', '--glass')),
  h('div', { class: 'ds-fonts' }, h('div', { class: 'table-title' }, h('h2', {}, 'users · 用户基础信息')),
    h('span', {}, 'orders · 每一行，都有依据。'), h('code', { class: 'mono' }, 'user_id INTEGER'),
    h('span', {}, '1,024 行 · 2026-09-26')),
  h('div', { class: 'wb-content ds-reading-table' }, readingTable),
  h('div', { class: 'ds-grid ds-font-inputs' },
    h('label', { class: 'settings-field' }, h('span', {}, '单行输入 · 字形完整性'),
      h('input', { type: 'text', value: 'google/gemma-4-e2b · g j p q y · 中文', 'aria-label': '单行输入字形样例' })),
    h('label', { class: 'settings-field' }, h('span', {}, '只读输入 · 同一字体'),
      h('input', { type: 'text', value: 'Mimesis / Faker · ÁÉÅ · 简体中文', readOnly: true, 'aria-label': '只读输入字形样例' }))),
  notes('中英文 UI 使用同一套圆角字形；字段标识与代码保留原有等宽字体。',
    '对照“用户基础信息”和按钮标签的笔端；字体加载后文字不应裁切或挤出控件。',
    '对照输入框的 g/j/p/q/y 下伸部分和 Á/É/Å 顶部重音；聚焦、全选和窄屏时仍须完整显示。',
    '正文保持中性灰绿，绿色重点用于主操作与选中状态；柔和来自材质，不通过淡化文字实现。',
    '数据区域的稳定底色是刻意的层级区分；不让正文随玻璃折射而变形。',
    '在不同滚动位置检查边缘与文字，使用系统减少透明度或高对比度设置检查回退。')));

const actionStatus = status('可操作下方控件；反馈仅保留在当前页面。');
const primaryButton = button('确认示例', () => { actionStatus.textContent = '已确认这个交互样例，没有执行业务操作。'; }, { primary: true, glyph: 'check' });
const secondaryButton = button('普通操作', () => { actionStatus.textContent = '已触发普通操作示例。'; }, { glyph: 'save' });
const toggleButton = button('选中状态', () => {
  const next = toggleButton.getAttribute('aria-pressed') !== 'true';
  toggleButton.setAttribute('aria-pressed', String(next));
  actionStatus.textContent = next ? '按钮现为选中状态。' : '按钮已取消选中。';
}, { 'aria-pressed': 'true' });
const loadingButton = button('演示加载', () => {
  loadingButton.disabled = true;
  loadingButton.setAttribute('aria-busy', 'true');
  loadingButton.textContent = '处理中…';
  actionStatus.textContent = '正在演示加载状态，未发起网络请求。';
  loadingTimer = setTimeout(() => {
    loadingButton.disabled = false;
    loadingButton.removeAttribute('aria-busy');
    loadingButton.textContent = '演示加载';
    actionStatus.textContent = '加载演示结束，按钮恢复可用。';
    loadingTimer = null;
  }, 900);
}, { class: 'ds-loading' });
function checkbox(label, { checked = false, disabled = false, indeterminate = false } = {}) {
  const input = h('input', { type: 'checkbox', checked, disabled, onchange: () => {
    actionStatus.textContent = `${label}：${input.checked ? '已勾选' : '未勾选'}。`;
  } });
  input.indeterminate = indeterminate;
  return h('label', { class: 'ds-choice' }, input, h('span', {}, label));
}
const countError = h('small', { id: 'ds-count-error', class: 'editor-error' }, '请输入 1 至 1,000,000 的整数。');
const countInput = h('input', { type: 'text', inputmode: 'numeric', value: '0', 'aria-invalid': 'true',
  'aria-describedby': 'ds-count-error', oninput: () => {
    const valid = /^\d+$/.test(countInput.value) && Number(countInput.value) >= 1 && Number(countInput.value) <= 1000000;
    if (valid) countInput.removeAttribute('aria-invalid');
    else countInput.setAttribute('aria-invalid', 'true');
    countError.textContent = valid ? '' : '请输入 1 至 1,000,000 的整数。';
  } });
const countField = field('生成数量 · 错误恢复示例', countInput);
countField.append(countError);
const stageSample = h('ol', {class:'wb-guide-stages', 'aria-label':'生成流程样式示例'});
for (const [index, [label, hint]] of [['设定规则','选择表与字段'],['预览样例','只读查看结果'],['确认写入','核对生成计划']].entries()) {
  const stage = button('', () => {
    for (const item of stageSample.querySelectorAll('button')) item.removeAttribute('aria-current');
    stage.setAttribute('aria-current','step');
    actionStatus.textContent = `样式示例：${label}。正式工作台会进入对应操作。`;
  }, {plain:true, ...(index===0 ? {'aria-current':'step'} : {})});
  stage.append(h('span',{class:'wb-guide-number','aria-hidden':'true'},String(index+1)),
    h('span',{class:'wb-guide-label'},h('strong',{},label),h('small',{},hint)));
  stageSample.append(h('li',{},stage));
}
root.append(section('controls', '基础控件', '悬停、键盘焦点与选中分别表达，不通过尺寸变化提示状态。', 'sliders',
  h('div', { class: 'ds-row' }, primaryButton, secondaryButton, toggleButton,
    button('不可用', null, { disabled: true }), loadingButton),
  actionStatus,
  h('h3',{},'生成流程 · 分段导航'), stageSample,
  h('h3',{},'连接恢复 · 主次操作'),
  h('div', {class:'wb-welcome-actions'},
    button('重试', () => { actionStatus.textContent = '连接恢复样例：重试为主要操作，未发起连接请求。'; }, {primary:true}),
    button('选择数据库', () => { actionStatus.textContent = '连接恢复样例：选择数据库为次要操作，未更改当前连接。'; })),
  h('div', { class: 'ds-grid' },
    h('div', { class: 'ds-stack' }, h('h3', {}, '复选框与单选框'),
      h('div', { class: 'ds-row ds-row-wide' }, checkbox('users', { checked: true }), checkbox('orders'),
        checkbox('部分选择', { indeterminate: true }), checkbox('不可修改', { disabled: true, checked: true })),
      h('fieldset', { class: 'wb-write-strategy' }, h('legend', {}, '预览范围 · 单选样例'),
        ['当前表', '所选表'].map((label, index) => h('label', {},
          h('input', { type: 'radio', name: 'ds-scope', value: String(index), checked: index === 0,
            onchange: () => { actionStatus.textContent = `预览范围样例：${label}。`; } }), h('span', {}, label))))),
    h('div', { class: 'rule-editor' }, field('配置名称', h('input', { type: 'text', value: '电商测试数据' })),
      countField, field('数据库标识 · 禁用', h('input', { type: 'text', value: 'shop_demo.db', disabled: true })))),
  notes('Tab 逐项移动焦点，Space 切换复选框；焦点环不等同于已选状态。',
    '鼠标悬停呈现柔和阴影，按钮不移动；已选底色仍然保留，键盘焦点继续有清晰外圈。',
    '生成流程是一个分段容器：三项共用底槽，当前项只有柔和底板，没有独立外投影；窄屏保留编号和两行说明。',
    '连接恢复按钮居中并保持间距，窄屏自然换行；主操作和次操作使用正式按钮样式。',
    '错误值改为 100 后提示消失；错误时仍能继续输入，无效内容不会被悄悄替换。',
    '加载与禁用不可再次提交；前后保持布局宽度，反馈区域不会挤动其他控件。')));

const providerStatus = status('已提交值：Faker');
const provider = createDropdown({
  value: 'faker', label: '数据生成引擎',
  options: [{ value: 'faker', label: 'Faker' }, { value: 'mimesis', label: 'Mimesis' },
    { value: 'unavailable', label: '不可用选项 · 状态样例', disabled: true }],
  onChange: value => { providerStatus.textContent = `已提交值：${value === 'faker' ? 'Faker' : 'Mimesis'}`; }
});
const localeOptions = [
  { value: 'zh_CN', label: '中文 · 中国' },
  { value: 'zh_TW', label: '繁体中文 · 台湾' },
  { value: 'en_US', label: '英语 · 美国' },
  { value: 'en_GB', label: '英语 · 英国' },
  { value: 'ja_JP', label: '日语 · 日本' },
  { value: 'ko_KR', label: '韩语 · 韩国' },
  { value: 'fr_FR', label: '法语 · 法国' },
  { value: 'de_DE', label: '德语 · 德国' },
  { value: 'es_ES', label: '西班牙语 · 西班牙' },
  { value: 'it_IT', label: '意大利语 · 意大利' },
  { value: 'pt_BR', label: '葡萄牙语 · 巴西' },
  { value: 'ru_RU', label: '俄语 · 俄罗斯' }
];
const localeStatus = status('已提交值：中文 · 中国（zh_CN）');
const locale = createDropdown({
  value: 'zh_CN', label: '数据语言与地区', options: localeOptions,
  onChange: value => {
    const chosen = localeOptions.find(option => option.value === value);
    localeStatus.textContent = `已提交值：${chosen?.label || value}（${value}）`;
  }
});
const dateStatus = status('已提交日期：2026-09-26');
const datePicker = createDatePicker({ value: '2026-09-26', label: '起始日期样例',
  onChange: value => { dateStatus.textContent = `已提交日期：${value || '未设置'}`; }
});
disposables.push(provider, locale, datePicker);
root.append(section('pickers', '下拉与日期', '这里使用正式下拉和日历。展开后可以直接检查选中、探索和提交之间的区别。', 'sliders',
  h('div', { class: 'ds-grid rule-editor' },
    h('div', {}, field('数据生成引擎', provider.el), providerStatus,
      field('数据语言与地区', locale.el, '12 项固定样例，供滚动验收；不代表已安装引擎的支持列表，也不改变界面语言。'), localeStatus),
    h('div', {}, h('div', { class: 'control' }, h('p', { class: 'muted' }, '起始日期'), datePicker.el), dateStatus)),
  notes('下拉展开后用方向键探索，已提交值与勾号保持不变；Enter 或 Tab 提交，Escape 取消。',
    '活动项为浅灰，已选项保留浅绿底和勾号；两者重合时也能区分正在浏览与已经提交。',
    '展开“数据语言与地区”，用滚轮或上下按钮浏览；点击箭头只滚动，不改变已提交值，悬停不会自动滚动。',
    '短菜单不显示滚动按钮；长菜单到达端点后相应箭头消失，列表位置应保持稳定。Home / End 仍能浏览首尾。',
    '高对比度下恢复原生滑块并隐藏上下按钮；页面与表格的滚动条仍保留。',
    '日历方向键逐日或逐周移动，Page Up / Page Down 切月；Escape 只关闭日历并返回触发点。',
    '输入 2026-02-30 检查错误保留，再改为有效日期；未通过校验的日期不会成为已提交值。',
    '窄屏、滚动和浮层靠近窗口边缘时，菜单与日历仍应完整可操作。')));

const layerStatus = status('当前样例规则：整数，最小值 18，起始日期 2026-09-26。');
function showConfirmation() {
  let confirmed = false;
  const dialog = modal('确认样例', { dismiss: 'footer', onClose: () => {
    activeLayer = null;
    layerStatus.textContent = confirmed ? '已确认样例，未生成数据。' : '已关闭确认样例，焦点返回打开按钮。';
  } });
  activeLayer = dialog;
  dialog.body.append(h('p', { class: 'muted' }, '用于检查确认弹窗的材质、表名与操作层级。以下为固定样例。'),
    h('ul', { class: 'wb-summary-plan' },
      h('li', {}, h('span', { class: 'execution-table' }, 'users'), h('span', {}, '100 行')),
      h('li', {}, h('span', { class: 'execution-table' }, 'orders'), h('span', {}, '250 行'))),
    h('details', {}, h('summary', {}, '查看样例说明'),
      h('p', {}, '此页没有数据库连接，也不会调用检查、预览或生成接口。')));
  dialog.actions.append(button('返回样板', dialog.close), button('确认示例', () => {
    confirmed = true;
    dialog.close();
  }, { primary: true, glyph: 'check' }));
}
function showYaml() {
  const dialog = modal('YAML 交互样例', { wide: true, onClose: () => {
    activeLayer = null;
    layerStatus.textContent = '已关闭 YAML 样例；正文滚动位置与打开按钮焦点应保持。';
  } });
  activeLayer = dialog;
  dialog.body.append(h('p', { class: 'muted' }, '可编辑的固定文本，用于检查代码字体与滚动稳定性。关闭后丢弃修改。'),
    h('textarea', { class: 'wb-code ds-code-sample', rows: 12, 'aria-label': 'YAML 样例文本', spellcheck: 'false',
      value: 'provider: faker\nlocale: zh_CN\nseed: 42\ntables:\n  - name: users\n    count: 100\n  - name: orders\n    count: 250\n' }));
}
function showDrawer() {
  const draft = { ...appliedRule };
  let applied = false;
  let minimumValid = true;
  let dateValid = true;
  const children = [];
  const dialog = modal('字段规则样例', { drawer: true, dismiss: 'footer', onClose: () => {
    children.forEach(component => component.destroy());
    activeLayer = null;
    layerStatus.textContent = `${applied ? '已应用到页面样例' : '已取消修改'}：${appliedRule.generator === 'integer' ? '整数' : '小数'}，最小值 ${appliedRule.minimum}，起始日期 ${appliedRule.date || '未设置'}。`;
  } });
  activeLayer = dialog;
  const apply = button('应用到样例', () => {
    appliedRule = { ...draft };
    applied = true;
    dialog.close();
  }, { primary: true, glyph: 'check' });
  const validity = () => { apply.disabled = !minimumValid || !dateValid; };
  const rule = createDropdown({ value: draft.generator, label: '取值规则',
    options: [{ value: 'integer', label: '整数' }, { value: 'decimal', label: '小数' }],
    onChange: value => { draft.generator = value; }
  });
  const error = h('small', { class: 'editor-error', id: 'ds-minimum-error' });
  const minimum = h('input', { type: 'text', inputmode: 'numeric', value: draft.minimum,
    'aria-describedby': 'ds-minimum-error', oninput: () => {
      minimumValid = /^\d+$/.test(minimum.value) && Number(minimum.value) <= 1000000;
      if (minimumValid) {
        minimum.removeAttribute('aria-invalid');
        draft.minimum = minimum.value;
      } else minimum.setAttribute('aria-invalid', 'true');
      error.textContent = minimumValid ? '' : '请输入 0 至 1,000,000 的整数。';
      validity();
    }
  });
  const minimumField = field('最小值', minimum);
  minimumField.append(error);
  const date = createDatePicker({ value: draft.date, label: '样例规则起始日期',
    onChange: value => { draft.date = value || ''; },
    onValidity: message => { dateValid = !message; validity(); }
  });
  children.push(rule, date);
  dialog.body.append(h('p', { class: 'muted' }, '修改只存在于本页，应用后可再次打开检查；取消则保留原值。'),
    h('div', { class: 'rule-editor' }, field('取值规则', rule.el), minimumField,
      h('div', { class: 'control' }, h('p', { class: 'muted' }, '起始日期'), date.el)),
    h('div', { class: 'drawer-help' }, h('strong', {}, '嵌套浮层'),
      h('p', {}, '先打开下拉或日历，再按 Escape：先返回抽屉，再按一次关闭抽屉。')));
  dialog.actions.append(button('取消', dialog.close), apply);
}
root.append(section('layers', '弹窗与抽屉', '验证开合、背景锁定、内部滚动与焦点恢复，而不只看静态外观。', 'code',
  h('div', { class: 'ds-row' }, button('打开确认弹窗', showConfirmation, { glyph: 'check' }),
    button('编辑 YAML 样例', showYaml, { glyph: 'code' }), button('打开规则抽屉', showDrawer, { glyph: 'sliders' })),
  layerStatus,
  notes('连续打开和关闭 YAML 样例：页面左右位置、当前阅读位置不能跳动。',
    'Tab / Shift+Tab 留在当前浮层；关闭后回到打开它的按钮。背景控件不能被操作。',
    '抽屉无效输入保留原文并禁用应用；取消不修改样例，应用后再次打开应看到新值。',
    '先关闭日历或下拉，再关闭抽屉；每层分别恢复焦点，不能一次 Escape 关闭两层。')));

const fixture = {
  tables: [
    { name: 'users', row_count: 20, columns: [{ name: 'id' }, { name: 'full_name' }] },
    { name: 'products', row_count: 12, columns: [{ name: 'id' }, { name: 'name' }] },
    { name: 'orders', row_count: 0, columns: [{ name: 'id' }, { name: 'user_id' }] },
    { name: 'order_items', row_count: 0, columns: [{ name: 'id' }, { name: 'order_id' }, { name: 'product_id' }] },
    { name: 'audit', row_count: 0, columns: [{ name: 'id' }] }
  ],
  nodes: [
    { id: 'users', name: 'users', referenced: true },
    { id: 'products', name: 'products', referenced: true },
    { id: 'orders', name: 'orders', selected: true, count: 100 },
    { id: 'order_items', name: 'order_items', selected: true, count: 250 },
    { id: 'audit', name: 'audit' }
  ],
  edges: [
    { id: 'users-orders', source: 'users', target: 'orders', sourceColumns: ['id'], targetColumns: ['user_id'], nullable: false },
    { id: 'orders-items', source: 'orders', target: 'order_items', sourceColumns: ['id'], targetColumns: ['order_id'], nullable: false },
    { id: 'products-items', source: 'products', target: 'order_items', sourceColumns: ['id'], targetColumns: ['product_id'], nullable: false }
  ]
};
const graphStatus = status('当前查看 orders。固定样例范围：orders 100 行、order_items 250 行。');
const graph = createSchemaGraph({ schema: fixture, focus: 'orders',
  onSelect: name => {
    graphStatus.textContent = `当前查看 ${name}。固定样例范围仍为 orders 100 行、order_items 250 行。`;
    return true;
  },
  onEdge: edge => {
    graphStatus.textContent = `列映射：${edge.source}.${edge.sourceColumns.join(' + ')} → ${edge.target}.${edge.targetColumns.join(' + ')}。`;
  }
});
disposables.push(graph);
root.append(section('relationships', '关系图', '正式关系图组件，使用 5 张表、3 条外键的固定结构。仅检查浏览行为。', 'schema',
  graph.toolbar, graph.el, graphStatus,
  notes('点节点切换当前查看对象，固定生成范围不改变；点连线显示真实样例列映射。',
    '搜索、整库 / 依赖路径、缩放、100% 阅读、展开和字段标签均可操作。',
    '静态按钮与输入共用轻高光和短阴影；已选路径悬停后仍保留浅色选中态。',
    'orders → order_items 应直连；products → order_items 应从下方短路径接入，不穿过 orders，也不绕到顶部。',
    '在 125% / 150% 系统缩放下静置画布；节点与滚动条不得反复移动或出现。',
    '关系图包含仅引用和其他表状态；“检查问题”为空仅表示此固定样例未提供问题，不表示业务检查通过。')));

const references = [
  ['Apple HIG · Materials', 'https://developer.apple.com/design/human-interface-guidelines/materials', '官方原则：玻璃用于导航和控制，内容层保持清晰。'],
  ['Microsoft · Materials in Windows', 'https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/materials', '官方原则：区分长期背景材质与临时浮层。'],
  ['Microsoft · WinUI Gallery', 'https://github.com/microsoft/WinUI-Gallery', '官方原生交互样例：组件、代码和可访问性共同呈现。'],
  ['Microsoft · Fluent UI', 'https://github.com/microsoft/fluentui', '官方 Web 参考：复用状态、交互与设计变量的组织方式。'],
  ['社区 · Liquid Glass React', 'https://github.com/rdev/liquid-glass-react', '仅作折射视觉参考；作者说明 Safari / Firefox 不显示位移效果。本项目未引入此依赖。']
];
root.append(section('references', '设计依据', '采用共同的层级与交互原则，保留 sqlseed 自己的跨平台组件。', 'link',
  h('ol', { class: 'ds-source-list' }, references.map(([title, url, description]) => h('li', {},
    h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, title), h('p', { class: 'muted' }, description)))),
  h('p', {}, '本页是持续维护的交互参考，不是“所有平台已经验收通过”的报告。视觉、键盘、缩放和系统回退仍需逐项实测。')));
root.append(h('p', { class: 'muted ds-end' }, '所有示例共用正式 style.css 与组件模块。刷新本页会恢复固定初始值。'));

window.addEventListener('pagehide', event => {
  if (event.persisted) return;
  activeLayer?.close();
  disposables.forEach(component => component.destroy());
  if (loadingTimer !== null) clearTimeout(loadingTimer);
});
