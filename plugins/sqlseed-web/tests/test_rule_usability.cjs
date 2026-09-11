const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const {createDom, loadFrontend} = require('./frontend_helpers.cjs');
const parameter = (name, type, defaultValue, required = false) => ({name, type, default: defaultValue, required});
const catalog = {entries:[
  {id:'string',output_type:'string',params:[parameter('min_length','integer',1),parameter('max_length','integer',100),parameter('charset','string',null)]},
  {id:'template',output_type:'string',params:[parameter('template','string',null,true),parameter('sequence_start','integer',1),parameter('sequence_step','integer',1)]},
  {id:'name',output_type:'string',params:[]},
  {id:'integer',output_type:'integer',params:[parameter('min_value','integer',0),parameter('max_value','integer',999999)]},
  {id:'date',output_type:'date',params:[parameter('start_year','integer',2000),parameter('end_year','integer',null),parameter('start_date','string',null),parameter('end_date','string',null),parameter('weekdays','json','all')]},
  {id:'datetime',output_type:'datetime',params:[parameter('start_year','integer',2000),parameter('end_year','integer',null),parameter('start_date','string',null),parameter('end_date','string',null),parameter('all_day','boolean',true),parameter('start_time','string',null),parameter('end_time','string',null),parameter('weekdays','json','all')]},
]};
function harness({column={},rule,baseline,table={},...rest}={}){
  const document=createDom(), labels=loadFrontend('labels.js',{document}), dropdown=loadFrontend('dropdown.js',{document});
  const calendar=loadFrontend('workbench/date-picker.js',{document});
  const labelNames=vm.runInContext('({genLabel,paramLabel, ...(typeof genGuide === "function" ? {genGuide} : {})})',labels);
  const context=loadFrontend('workbench/editor.js',{document,...labelNames,createDatePicker:vm.runInContext('createDatePicker',calendar),createDropdown:vm.runInContext('createDropdown',dropdown)});
  const changes=[], validity=[];
  column={name:'value',type:'TEXT',nullable:true,default:null,...column};
  context.options={table:{name:'items',columns:[column],primary_key:[],foreign_keys:[],unique_constraints:[],...table},column,rule,
    baseline:baseline||{generator_name:'string',params:{}},catalog,onChange:value=>changes.push(JSON.parse(JSON.stringify(value))),onValidity:value=>validity.push(value),...rest};
  const editor=vm.runInContext('createRuleEditor(options)',context);document.body.append(editor.el);
  const field=name=>editor.el.querySelector(`[data-field="${name}"]`);
  const input=async(name,value,event='input')=>{const node=field(name);assert.ok(node,name);typeof value==='boolean'?node.checked=value:node.value=String(value);await node.dispatchEvent(event);return node;};
  const choose=async(name,label)=>{
    const node=field(name);assert.ok(node,name);await node.querySelector('.dropdown-btn').click();
    const menus=document.querySelectorAll('.dropdown-floating');
    assert.equal(menus.length,1,`Expected one open dropdown for ${name}`);
    const option=menus[0].querySelectorAll('.dropdown-item').find(item=>item.textContent.includes(label));
    assert.ok(option,label);await option.click();
  };
  return {document,editor,field,input,choose,changes,validity};
}
test('switching a database-default column to generator selects a real generator without a skip error',async()=>{
  const ui=harness({column:{default:"'uncategorized'",nullable:false},baseline:{generator_name:'skip',params:{}}});
  assert.match(ui.editor.el.textContent,/uncategorized/);
  assert.equal(ui.field('generator'),null);
  await ui.choose('mode','生成器');
  assert.equal(ui.validity.at(-1),null);
  assert.equal(ui.changes.at(-1).generator,'string');
  await ui.choose('mode','数据库默认值');
  assert.equal(ui.changes.at(-1).generator,'skip');
});
test('NULL fallback and automatic IDs explain actual database behavior',()=>{
  const nullable=harness({baseline:{generator_name:'skip',params:{}}});
  assert.match(nullable.editor.el.textContent,/没有数据库默认值.*NULL/);
  const id=harness({column:{name:'id',type:'INTEGER',nullable:false,is_primary_key:true,is_autoincrement:true},baseline:{generator_name:'skip',params:{}}});
  assert.match(id.editor.el.textContent,/现有|已有/);assert.match(id.editor.el.textContent,/不会.*1|不.*从 1/);
});

test('NOT NULL generator and FK rules omit locked NULL controls without weakening their rules',async()=>{
  for(const foreign of [false,true]){
    const ui=harness({column:{nullable:false},
      table:foreign?{foreign_keys:[{columns:['value'],ref_table:'parents',ref_columns:['id']}]}:{},
      rule:{generator:foreign?'foreign_key_or_integer':'string',params:foreign?{strategy:'coverage'}:{min_length:3},
        null_ratio:0.2,constraints:{max_retries:0},custom_extension:{preserve:true}}});
    assert.equal(ui.field('nullable'),null);
    assert.equal(ui.field('null_ratio'),null);
    assert.doesNotMatch(ui.editor.el.textContent,/包含 NULL 值|NULL 百分比/);
    if(foreign) await ui.choose('strategy','随机采样');
    else await ui.input('min_length','4');
    const result=ui.changes.at(-1);
    assert.equal(result.null_ratio,undefined);
    assert.deepEqual(result.constraints,{max_retries:0});
    assert.deepEqual(result.custom_extension,{preserve:true});
    assert.equal(result.generator,foreign?'foreign_key_or_integer':'string');
    assert.deepEqual(result.params,foreign?{strategy:'random'}:{min_length:4});
  }
});

test('nullable rules reveal a percentage only when empty values are enabled and preserve other configuration',async()=>{
  const ui=harness({rule:{generator:'string',params:{min_length:3},provider:'faker',
    faker_method:'pystr',native_params:{max_chars:8},constraints:{max_retries:0}}});
  const percentage=()=>ui.field('null_ratio').closest('.wb-editor-row');
  assert.equal(ui.field('nullable').checked,false);
  assert.equal(ui.field('nullable').disabled,false);
  assert.equal(percentage().hidden,true);
  await ui.input('nullable',true,'change');
  assert.equal(percentage().hidden,false);
  assert.equal(ui.field('null_ratio').disabled,false);
  assert.equal(ui.field('null_ratio').value,'5');
  await ui.input('null_ratio','12.5');
  assert.equal(ui.changes.at(-1).null_ratio,0.125);
  await ui.input('nullable',false,'change');
  assert.equal(percentage().hidden,true);
  assert.equal(ui.field('null_ratio').disabled,true);
  assert.deepEqual(ui.changes.at(-1),{name:'value',generator:'string',params:{min_length:3},
    provider:'faker',faker_method:'pystr',native_params:{max_chars:8},constraints:{max_retries:0}});
});
test('date controls show effective defaults and keep existing partial or year-based config intact',async()=>{
  const ui=harness({rule:{generator:'date',params:{start_year:2022}}});
  assert.equal(ui.field('start_date').type,'text');assert.equal(ui.field('start_date').value,'2022-01-01');
  assert.ok(ui.field('start_date').closest('.wb-date-control').querySelector('.wb-date-trigger'));
  assert.match(ui.field('end_date').value,/^\d{4}-12-31$/);
  assert.equal(ui.changes.length,0);
  assert.deepEqual(JSON.parse(JSON.stringify(ui.editor.getDraft().current.params)),{start_year:2022});
  assert.match(ui.editor.el.textContent,/YYYY-MM-DD/);
  await ui.input('end_date','2024-05-31');
  assert.deepEqual(ui.changes.at(-1).params,{start_year:2022,end_date:'2024-05-31'});
  assert.match(ui.field('start_year').closest('details').textContent,/年份|兼容/);
});
test('date presets and weekday controls create executable values without requiring JSON syntax',async()=>{
  const ui=harness({rule:{generator:'date',params:{start_year:2020,end_year:2021}}});
  const preset=ui.editor.el.querySelector('[data-date-preset="this-year"]');assert.ok(preset);await preset.click();
  const year=new Date().getFullYear();assert.equal(ui.changes.at(-1).params.start_date,`${year}-01-01`);
  assert.equal(ui.changes.at(-1).params.end_date,`${year}-12-31`);assert.equal(ui.changes.at(-1).params.start_year,undefined);
  await ui.choose('weekdays','工作日');assert.equal(ui.changes.at(-1).params.weekdays,'workdays');
  await ui.choose('weekdays','自定义');await ui.input('weekday-0',false,'change');
  assert.deepEqual(ui.changes.at(-1).params.weekdays,[1,2,3,4]);
});
test('time controls communicate full-day behavior and enable explicit time windows',async()=>{
  const ui=harness({rule:{generator:'datetime',params:{start_time:'09:00',end_time:'18:30',all_day:true}}});
  assert.equal(ui.field('start_time').type,'time');assert.equal(ui.field('start_time').disabled,true);
  await ui.input('all_day',false,'change');assert.equal(ui.field('start_time').disabled,false);
  assert.equal(ui.field('start_time').value,'09:00');assert.equal(ui.changes.at(-1).params.end_time,'18:30');
  await ui.input('start_time','10:15');assert.equal(ui.changes.at(-1).params.start_time,'10:15');
});
test('charset choices use the actual core tokens and preserve imported custom characters',async()=>{
  const ui=harness({rule:{generator:'string',params:{charset:'甲乙丙'}}});
  assert.equal(ui.field('charset').value,'甲乙丙');assert.match(ui.editor.el.textContent,/候选字符|允许出现/);
  await ui.choose('charset-preset','字母和数字');assert.equal(ui.changes.at(-1).params.charset,'alphanumeric');
  await ui.choose('charset-preset','自定义');await ui.input('charset','ABC012');
  assert.equal(ui.changes.at(-1).params.charset,'ABC012');
  const count=ui.changes.length;await ui.input('charset','');assert.equal(ui.changes.length,count);assert.match(ui.validity.at(-1),/字符/);
});
test('generator choices explain their purpose and examples and only recommend without applying',async()=>{
  const ui=harness({column:{name:'sku'},rule:{generator:'string',params:{max_length:12}}});
  assert.match(ui.editor.el.textContent,/随机.*字符/);
  await ui.field('generator').querySelector('[data-generator-toggle]').click();
  const choices=ui.editor.el.querySelectorAll('[data-generator]');assert.equal(choices[0].getAttribute('data-generator'),'template');
  assert.match(choices[0].textContent,/SKU|编号/);assert.match(choices[0].textContent,/示例/);
  assert.equal(ui.changes.length,0);
});
test('advanced engine and native methods remain collapsed and explain inheritance while preserving overrides',async()=>{
  const ui=harness({rule:{generator:'string',params:{},provider:'faker',faker_method:'lexify',native_params:{text:'????'}}});
  const advanced=ui.field('provider').closest('details');assert.ok(advanced);assert.ok(!advanced.open);
  assert.match(advanced.textContent,/继承全局|沿用全局/);assert.match(advanced.textContent,/优先|覆盖/);
  await ui.input('max_length','8');assert.equal(ui.changes.at(-1).provider,'faker');assert.deepEqual(ui.changes.at(-1).native_params,{text:'????'});
});
test('database-default mode recommends a scalar matching the SQL type instead of the alphabetical first generator',async()=>{
  const expanded={entries:[{id:'address',output_type:'string',params:[]},{id:'boolean',output_type:'boolean',params:[]},...catalog.entries]};
  for(const [type,generator] of [['TEXT','string'],['INTEGER','integer']]){
    const ui=harness({column:{type,default:'0'},baseline:{generator_name:'skip',params:{}},catalog:expanded});
    await ui.choose('mode','生成器');assert.equal(ui.changes.at(-1).generator,generator);
  }
});
test('editing legacy years updates the effective date display without replacing explicit bounds',async()=>{
  const ui=harness({rule:{generator:'date',params:{start_year:2020,end_date:'2027-06-30'}}});
  await ui.input('start_year',2025);assert.equal(ui.field('start_date').value,'2025-01-01');
  await ui.input('end_year',2028);assert.equal(ui.field('end_date').value,'2027-06-30');
  assert.equal(ui.changes.at(-1).params.start_date,undefined);
});
test('malformed date text survives drawer draft restoration and blocks applying until corrected',async()=>{
  const ui=harness({rule:{generator:'date',params:{start_date:'not-a-date'}}});
  assert.equal(ui.field('start_date').type,'text');assert.equal(ui.field('start_date').value,'not-a-date');
  assert.ok(ui.validity.at(-1));await ui.input('start_date','bad-date');
  const restored=harness({draft:ui.editor.getDraft()});assert.equal(restored.field('start_date').value,'bad-date');
  assert.equal(restored.field('start_date').type,'text');assert.ok(restored.validity.at(-1));
  await restored.input('start_date','2026-01-01');assert.equal(restored.validity.at(-1),null);
});
test('database omission does not offer a misleading partial NULL percentage',()=>{
  const ui=harness({baseline:{generator_name:'skip',params:{}}});
  assert.equal(ui.field('null_ratio'),null);assert.equal(ui.field('nullable'),null);
  assert.match(ui.editor.el.textContent,/NULL/);
});
test('date presets retain invalid unrelated advanced input and keep Apply blocked',async()=>{
  const ui=harness({rule:{generator:'date',params:{start_year:2020}}});
  await ui.input('native_params','{');assert.ok(ui.validity.at(-1));
  await ui.editor.el.querySelector('[data-date-preset="today"]').click();
  assert.equal(ui.field('native_params').value,'{');assert.ok(ui.validity.at(-1));assert.equal(ui.changes.length,0);
});
test('full-day and provider hints describe product behavior instead of implementation defaults',()=>{
  const ui=harness({rule:{generator:'datetime',params:{},provider:'faker'}});
  const fullDay=ui.field('all_day').closest('.wb-editor-row');
  assert.match(fullDay.textContent,/00:00:00.*23:59:59/);assert.match(fullDay.textContent,/取消.*时间/);
  assert.doesNotMatch(fullDay.textContent,/默认值：true/);
  const provider=ui.field('provider').closest('.wb-editor-row');
  assert.match(provider.textContent,/继承|全局相同/);assert.match(provider.textContent,/其他值.*保留.*检查.*阻止/);
  assert.doesNotMatch(provider.textContent,/仅影响本列/);assert.equal(ui.field('provider').value,'faker');
});
test('weekday groups and ordinary fields have labels without nesting label elements',async()=>{
  const ui=harness({rule:{generator:'datetime',params:{weekdays:[0,2],all_day:false}}});
  const days=ui.editor.el.querySelector('.wb-weekday-control');
  assert.equal(days.getAttribute('role'),'group');assert.equal(days.getAttribute('aria-label'),'星期');
  for(const label of ui.editor.el.querySelectorAll('label'))assert.equal(label.querySelector('label'),null);
  for(let index=0;index<7;index++){
    const input=ui.field(`weekday-${index}`);assert.ok(input.closest('label'));assert.match(input.closest('label').textContent,/周/);
  }
  assert.match(ui.field('start_date').closest('label').textContent,/开始日期/);
  await ui.input('weekday-1',true,'change');assert.deepEqual(ui.changes.at(-1).params.weekdays,[0,1,2]);
});

test('calendar corrects an invalid rule draft without losing other parameters and is destroyed with the editor',async()=>{
  const ui=harness({rule:{generator:'datetime',params:{start_date:'2024-02-29',end_date:'2027-01-01',weekdays:[0,2],start_time:'09:00',all_day:false},constraints:{unique:true}}});
  await ui.input('start_date','2023-02-29');assert.ok(ui.validity.at(-1));assert.equal(ui.changes.length,0);
  const button=ui.field('start_date').closest('.wb-date-control').querySelector('.wb-date-trigger');await button.click();
  const calendar=ui.document.querySelector('.wb-date-dialog');assert.ok(calendar);
  await calendar.querySelector('[data-date]').click();
  assert.equal(ui.validity.at(-1),null);assert.equal(ui.document.querySelector('.wb-date-dialog'),null);
  assert.equal(ui.changes.at(-1).params.end_date,'2027-01-01');assert.deepEqual(ui.changes.at(-1).params.weekdays,[0,2]);
  assert.equal(ui.changes.at(-1).params.start_time,'09:00');assert.equal(ui.changes.at(-1).constraints.unique,true);
  await button.click();ui.editor.destroy();assert.equal(ui.document.querySelector('.wb-date-dialog'),null);
  assert.equal(ui.document.listeners.get('keydown')?.size,0);
});

test('clearing an explicit calendar bound restores year fallback without synthesizing new params',async()=>{
  const ui=harness({rule:{generator:'date',params:{start_date:'2024-02-29',start_year:2022,end_date:'2027-01-01'}}});
  await ui.field('start_date').closest('.wb-date-control').querySelector('.wb-date-trigger').click();
  const clear=ui.document.querySelector('.wb-date-dialog').querySelectorAll('button').find(button=>button.textContent==='清空');await clear.click();
  assert.deepEqual(ui.changes.at(-1).params,{start_year:2022,end_date:'2027-01-01'});
  assert.equal(ui.field('start_date').value,'');assert.equal(ui.validity.at(-1),null);
});

test('year-only bounds keep four-digit displays and recover when an out-of-range legacy year is corrected',async()=>{
  const ui=harness({rule:{generator:'date',params:{start_year:1}}});
  assert.equal(ui.field('start_date').value,'0001-01-01');assert.equal(ui.validity.at(-1),null);
  await ui.input('start_year',10000);assert.ok(ui.validity.at(-1));
  await ui.input('start_year',2025);assert.equal(ui.field('start_date').value,'2025-01-01');assert.equal(ui.validity.at(-1),null);
  assert.deepEqual(ui.changes.at(-1).params,{start_year:2025});
  await ui.input('start_date','2025-02-');await ui.input('start_year',2026);
  assert.equal(ui.field('start_date').value,'2025-02-');assert.ok(ui.validity.at(-1));
});
