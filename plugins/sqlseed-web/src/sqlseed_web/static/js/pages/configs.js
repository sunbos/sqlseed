import { h, get, api, store, safeTargetLabel } from '../api.js';
import { button, modal, download, icon } from '../workbench/ui.js';
let root, list, notice, count, search, currentFilter, connectionHint;
let records = [],
  query = '',
  onlyCurrent = false,
  scope = null,
  version = 0,
  sequence = 0,
  dialog = null;
const draftPath = id => `/api/workbench/drafts/${encodeURIComponent(id)}`;
const workbenchLink = (label, suffix, primary = false, glyph = null) => h('a', {
  href: `#/workbench?${suffix}`,
  class: `btn wb-button${primary ? ' primary' : ''}`
}, glyph ? icon(glyph) : null, label);
export function render() {
  version++;
  records = [];
  scope = null;
  query = '';
  onlyCurrent = Boolean(store.connId);
  notice = h('p', {
    class: 'config-notice wb-notice',
    role: 'status',
    'aria-live': 'polite'
  });
  count = h('p', {
    class: 'config-count muted'
  });
  list = h('section', {
    class: 'config-list',
    role: 'list',
    'aria-label': '已保存配置'
  });
  search = h('input', {
    type: 'search',
    value: '',
    'aria-label': '查找配置',
    placeholder: '配置名称或数据库',
    oninput: () => {
      query = search.value;
      drawList();
    }
  });
  currentFilter = h('input', {
    type: 'checkbox',
    checked: onlyCurrent,
    'aria-label': '仅当前数据库',
    onchange: () => {
      onlyCurrent = currentFilter.checked && Boolean(store.connId);
      return refresh();
    }
  });
  connectionHint = h('p', {
    class: 'config-filter-hint muted'
  });
  root = h('div', {
    class: 'page configs-page'
  }, h('header', {
    class: 'heading'
  }, h('div', {}, h('h1', {}, '配置管理'), h('p', {
    class: 'subtitle'
  }, '保存、复用和管理生成规则，打开配置后在工作台编辑。')), h('div', {
    class: 'heading-actions'
  }, workbenchLink('导入配置', 'new=1&import=1', false, 'upload'), workbenchLink('新建配置', 'new=1', true))), h('section', {
    class: 'config-toolbar',
    'aria-label': '查找和筛选配置'
  }, h('label', {
    class: 'config-search'
  }, h('span', {}, '查找配置'), search), h('div', {
    class: 'config-scope'
  }, h('label', {
    class: 'config-filter'
  }, currentFilter, '仅当前数据库'), connectionHint), button('刷新列表', () => refresh(), {
    glyph: 'refresh'
  })), notice, count, list);
  updateFilter();
  return root;
}
export function mount() {
  window.addEventListener('sqlseed:connection-changed', connectionChanged);
  return refresh();
}
export function unmount() {
  version++;
  sequence++;
  dialog?.close();
  dialog = null;
  window.removeEventListener('sqlseed:connection-changed', connectionChanged);
}
function updateFilter() {
  if (!store.connId) {
    onlyCurrent = false;
  }
  currentFilter.disabled = !store.connId;
  currentFilter.checked = onlyCurrent;
  connectionHint.textContent = store.connId ? `当前：${safeTargetLabel(store.target)}` : '连接数据库后可按当前库筛选';
}
function connectionChanged() {
  updateFilter();
  return refresh();
}
async function refresh(message = '') {
  const expected = version,
    request = ++sequence;
  const target = onlyCurrent && store.connId ? `?conn_id=${encodeURIComponent(store.connId)}` : '';
  if (target !== scope) {
    records = [];
    scope = target;
    list.replaceChildren(h('p', {
      class: 'config-empty'
    }, '正在读取配置…'));
  }
  list.setAttribute('aria-busy', 'true');
  notice.textContent = message;
  const current = () => expected === version && request === sequence;
  try {
    const response = await get(`/api/workbench/drafts${target}`);
    if (!current()) {
      return;
    }
    records = Array.isArray(response) ? response : response.drafts || [];
    drawList();
  } catch (error) {
    if (!current()) {
      return;
    }
    notice.textContent = `无法读取配置：${error.message}。请重试刷新列表。`;
    if (!records.length) {
      list.replaceChildren(h('p', {
        class: 'config-empty'
      }, '配置暂时无法读取，已保存内容不会因此丢失。'));
    }
  } finally {
    if (current()) {
      list.setAttribute('aria-busy', 'false');
    }
  }
}
function savedTime(value) {
  const date = new Date(typeof value === 'number' ? value * 1000 : value);
  if (value == null || value === '' || !Number.isFinite(date.getTime())) {
    return '保存时间未知';
  }
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  });
}
function drawList() {
  const term = query.trim().toLocaleLowerCase();
  const visible = records.filter(record => `${record.name} ${record.target_label}`.toLocaleLowerCase().includes(term));
  count.textContent = `${visible.length} 份配置${term ? " · 共 " + records.length + " 份" : ''}`;
  if (!visible.length) {
    list.replaceChildren(h('div', {
      class: 'config-empty'
    }, h('h2', {}, term ? '没有匹配的配置' : '还没有保存的配置'), h('p', {}, term ? '尝试其他名称，或关闭“仅当前数据库”查看更多配置。' : '在工作台选择表并保存规则，下次可以直接打开复用。'), term ? null : workbenchLink('新建配置', 'new=1', true)));
    return;
  }
  list.replaceChildren(...visible.map(record => {
    const document = record.document || {},
      tables = Array.isArray(document.tables) ? document.tables : [];
    const planned = tables.every(table => Number.isInteger(table.count) && table.count >= 0) ? tables.reduce((sum, table) => sum + table.count, 0).toLocaleString() : '待设置';
    const provider = {
      base: 'Base',
      faker: 'Faker',
      mimesis: 'Mimesis'
    }[document.provider] || document.provider || '待设置';
    return h('article', {
      class: 'config-card',
      role: 'listitem',
      'data-config-id': record.id
    }, h('div', {
      class: 'config-card-main'
    }, h('div', {
      class: 'config-card-heading'
    }, h('h2', {}, record.name), h('span', {
      class: 'config-revision'
    }, `v${record.revision}`)), h('p', {
      class: 'config-target'
    }, icon('database'), record.target_label || '数据库信息未记录'), h('p', {
      class: 'config-facts'
    }, `${tables.length} 张表 · ${planned} 行 · ${provider} · ${document.locale || '语言待设置'}`), h('p', {
      class: 'config-updated muted'
    }, `最后保存 ${savedTime(record.updated_at)}`)), h('div', {
      class: 'config-card-actions',
      role: 'group',
      'aria-label': `${record.name} 的操作`
    }, workbenchLink('打开', `draft=${encodeURIComponent(record.id)}`), button('复制', () => editName(record, true)), button('重命名', () => editName(record, false)), button('导出', () => exportConfig(record), {
      glyph: 'download'
    }), button('删除', () => deleteConfig(record), {
      class: 'config-delete'
    })));
  }));
}
function createDialog(title) {
  const page = version;
  let closed = false;
  const owned = modal(title, {
    onClose: () => {
      closed = true;
      if (dialog === owned) {
        dialog = null;
      }
    }
  });
  dialog = owned;
  owned.el.classList.add('config-dialog');
  return {
    owned,
    pageCurrent: () => page === version,
    current: () => page === version && !closed && dialog === owned
  };
}
function publish(type, detail) {
  window.dispatchEvent(new CustomEvent(type, {
    detail
  }));
}
async function mutationFailure(error, context, alert, confirm) {
  if (!context.current()) {
    return;
  }
  if ([404, 409].includes(error.status)) {
    alert.textContent = error.status === 409 ? '配置已被其他操作更新。列表已刷新，请取消后核对最新版本再重试。' : '配置已不存在。请关闭窗口，在更新后的列表中重新选择。';
    confirm.disabled = true;
    await refresh();
  } else {
    alert.textContent = `未能确认操作结果：${error.message}。请刷新列表核对后再重试。`;
  }
}
function editName(record, copy) {
  const context = createDialog(copy ? '复制配置' : '重命名配置'),
    {
      owned
    } = context;
  const input = h('input', {
    type: 'text',
    value: copy ? `${record.name.slice(0, 197)} 副本` : record.name,
    maxlength: 200,
    'aria-label': '配置名称',
    onkeydown: event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        return submit();
      }
    }
  });
  const alert = h('p', {
    role: 'alert',
    class: 'config-error'
  });
  const confirm = button(copy ? '创建副本' : '保存名称', submit, {
    primary: true
  });
  let pending = false;
  owned.body.append(h('p', {
    class: 'muted'
  }, copy ? '复制已保存的完整规则，原配置保持不变。' : '只修改配置名称，生成规则保持不变。'), h('label', {
    class: 'config-name-field'
  }, h('span', {}, '配置名称'), input), alert);
  owned.actions.append(button('取消', owned.close), confirm);
  input.focus();
  async function submit() {
    if (pending || confirm.disabled || !context.current()) {
      return;
    }
    const name = input.value.trim();
    if (!name) {
      alert.textContent = '请输入配置名称。';
      input.focus();
      return;
    }
    if (name.length > 200) {
      alert.textContent = '配置名称不能超过 200 个字符。';
      return;
    }
    pending = true;
    confirm.disabled = true;
    input.disabled = true;
    alert.textContent = '';
    let failed = null;
    try {
      const saved = await api(`${draftPath(record.id)}${copy ? '/copy' : ''}`, {
        method: copy ? 'POST' : 'PATCH',
        body: JSON.stringify({
          revision: record.revision,
          name
        })
      });
      if (!copy) {
        publish('sqlseed:draft-renamed', {
          id: saved.id,
          revision: saved.revision,
          name: saved.name
        });
      }
      if (!context.pageCurrent()) {
        return;
      }
      if (context.current()) {
        owned.close();
      }
      await refresh(copy ? `已创建“${saved.name}”，可以打开继续编辑。` : `已重命名为“${saved.name}”。`);
    } catch (error) {
      failed = error;
      await mutationFailure(error, context, alert, confirm);
    } finally {
      pending = false;
      if (context.current()) {
        input.disabled = false;
        confirm.disabled = [404, 409].includes(failed?.status);
      }
    }
  }
}
function deleteConfig(record) {
  const context = createDialog('删除配置'),
    {
      owned
    } = context;
  const alert = h('p', {
      role: 'alert',
      class: 'config-error'
    }),
    cancel = button('取消', owned.close);
  let pending = false;
  const confirm = button('删除配置', async () => {
    if (pending || confirm.disabled || !context.current()) {
      return;
    }
    pending = true;
    confirm.disabled = true;
    alert.textContent = '';
    let failed = null;
    try {
      await api(`${draftPath(record.id)}?revision=${record.revision}`, {
        method: 'DELETE'
      });
      publish('sqlseed:draft-deleted', {
        id: record.id,
        revision: record.revision
      });
      if (!context.pageCurrent()) {
        return;
      }
      if (context.current()) {
        owned.close();
      }
      await refresh(`已删除“${record.name}”。运行记录和数据库数据均保留。`);
    } catch (error) {
      failed = error;
      await mutationFailure(error, context, alert, confirm);
    } finally {
      pending = false;
      if (context.current()) {
        confirm.disabled = [404, 409].includes(failed?.status);
      }
    }
  }, {
    class: 'config-delete-confirm'
  });
  owned.body.append(h('p', {}, '删除此配置？'), h('strong', {
    class: 'config-delete-name'
  }, record.name), h('p', {
    class: 'muted'
  }, `数据库：${record.target_label} · 已保存版本 v${record.revision}`), h('p', {}, '只删除这份已保存的配置。运行记录、已提交的运行快照与数据库中的数据都会保留，正在执行的任务继续运行。'), alert);
  owned.actions.append(cancel, confirm);
  cancel.focus();
}
function exportConfig(record) {
  const context = createDialog('导出配置'),
    {
      owned
    } = context;
  const alert = h('p', {
      role: 'alert',
      class: 'config-error'
    }),
    result = h('p', {
      role: 'status',
      'aria-live': 'polite'
    });
  const actions = ['JSON', 'YAML'].map(format => button(`下载 ${format}`, () => saveFile(format), {
    glyph: 'download'
  }));
  let pending = false;
  owned.body.append(h('strong', {}, record.name), h('p', {}, '导出服务器上已保存的生成规则。文件可在工作台导入，不包含数据库连接凭据。'), alert, result);
  owned.actions.append(button('关闭', owned.close), ...actions);
  async function saveFile(format) {
    if (pending || !context.current()) {
      return;
    }
    pending = true;
    alert.textContent = '';
    actions.forEach(action => {
      action.disabled = true;
    });
    try {
      const saved = await get(`${draftPath(record.id)}/export`);
      if (!context.current()) {
        return;
      }
      const name = String(saved.name || 'sqlseed').replace(/[^\p{L}\p{N}._-]+/gu, '_').slice(0, 80) || 'sqlseed';
      download(`${name}.${format === 'JSON' ? 'json' : 'yaml'}`, format === 'JSON' ? JSON.stringify(saved.json, null, 2) : saved.yaml, format === 'JSON' ? 'application/json' : 'application/yaml');
      result.textContent = `已导出 v${saved.revision} 的 ${format} 文件。`;
    } catch (error) {
      if (context.current()) {
        alert.textContent = `导出失败：${error.message}`;
      }
    } finally {
      pending = false;
      if (context.current()) {
        actions.forEach(action => {
          action.disabled = false;
        });
      }
    }
  }
}
