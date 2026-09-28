import './graph-layout.js';
import './dependency-view.js';
const SVG_NS = 'http://www.w3.org/2000/svg';
const GRAPH_MODES = ['plan', 'all', 'paths', 'issues'];
let graphSequence = 0;
function html(tag, attributes = {}, text = '') {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    el.setAttribute(key, value);
  }
  if (text) {
    el.textContent = text;
  }
  return el;
}
function svgElement(tag, attributes = {}, text = '') {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) {
    el.setAttribute(key, value);
  }
  if (text) {
    el.textContent = text;
  }
  return el;
}
function relationText(edge) {
  const source = (edge.sourceColumns || []).join(' + ');
  const target = (edge.targetColumns || []).join(' + ');
  return `${edge.source}${source ? '.' + source : ''} → ${edge.target}${target ? '.' + target : ''}`;
}
function nodeTitle(text) {
  let shortened = '',
    width = 0;
  for (const char of text) {
    width += char.codePointAt(0) > 255 ? 14 : 8.5;
    if (width > 164) {
      return shortened + '…';
    }
    shortened += char;
  }
  return shortened;
}

/** Fit is a viewport-dependent scale; natural diagram dimensions are 100%.
 * zoom remains relative to fit internally so existing view snapshots restore.
 */
export function graphViewport(layout, width, height, zoom = 1, actualSize = false) {
  const fitScale = Math.min(1, Math.max(1, width - 24) / layout.width, Math.max(1, height - 24) / layout.height);
  const scale = actualSize ? 1 : fitScale * zoom;
  const svgWidth = layout.width * scale,
    svgHeight = layout.height * scale;
  const stageWidth = Math.max(width, svgWidth + 24),
    stageHeight = Math.max(height, svgHeight + 24);
  return {
    fitScale,
    scale,
    zoom: scale / fitScale,
    svgWidth,
    svgHeight,
    stageWidth,
    stageHeight,
    left: (stageWidth - svgWidth) / 2,
    top: (stageHeight - svgHeight) / 2,
    viewportWidth: width,
    viewportHeight: height
  };
}

/** Browse real schema relationships without changing the generation selection.
 * onSelect may synchronously return false to keep the current graph focus.
 */
export function createSchemaGraph({
  schema,
  focus,
  mode = 'all',
  pathMode = 'complete',
  initialView,
  issues = [],
  checked = false,
  onSelect = () => true,
  onEdge = () => {},
  onExpand = () => {},
  onViewChange = () => {}
}) {
  function visibleGraph(visible, graph = data) {
    return {
      nodes: graph.nodes.filter(node => visible.has(node.id)),
      edges: graph.edges.filter(edge => visible.has(edge.source) && visible.has(edge.target))
    };
  }

  const data = {
    nodes: (schema.nodes || []).map(node => ({
      ...node
    })),
    edges: (schema.edges || []).map(edge => ({
      ...edge
    }))
  };
  const tableByName = new Map((schema.tables || []).map(table => [table.name, table]));
  const nodeIds = new Set(data.nodes.map(node => node.id));
  const restored = initialView && typeof initialView === 'object' ? initialView : {};
  const nonnegative = value => Number.isFinite(value) && value >= 0 ? value : 0;
  const requestedFocus = focus ?? restored.focus;
  let currentFocus = nodeIds.has(requestedFocus) ? requestedFocus : data.nodes[0]?.id;
  // Inspecting a node keeps the drawing stable; only an explicit path action
  // changes its anchor. Older snapshots used focus for both purposes.
  let pathFocus = nodeIds.has(restored.pathFocus) ? restored.pathFocus : currentFocus;
  let currentMode = restoredMode();
  let currentPath = restored.pathMode || pathMode;
  if (currentPath === 'paths') {
    currentPath = 'complete';
  }
  if (!['complete', 'upstream', 'downstream', 'neighbors'].includes(currentPath)) {
    currentPath = 'complete';
  }
  let labels = restored.labels === true,
    expanded = restored.expanded === true;
  let selectedEdge = data.edges.some(edge => edge.id === restored.edgeId) ? restored.edgeId : null;
  let relatedEdges = new Set();
  let zoom = 1,
    actualSize = false,
    layout = null,
    frame = null,
    svg = null,
    stage = null,
    destroyed = false;
  let pendingViewport = initialViewport();
  let measuredCanvas = null;
  const initialSearch = typeof restored.search === 'string' ? restored.search : '';
  let searchText = initialSearch.trim(),
    composing = false;
  let lastView = '';
  let drag = null;
  const markerId = `wb-schema-arrow-${++graphSequence}`;
  const listeners = [],
    drawingListeners = [];
  const listen = (el, type, callback, drawing = false, options) => {
    el.addEventListener(type, callback, options);
    (drawing ? drawingListeners : listeners).push(() => el.removeEventListener(type, callback, options));
  };
  const activate = (el, callback) => {
    listen(el, 'click', callback, true);
    listen(el, 'keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        callback(event);
      }
    }, true);
  };
  const el = html('section', {
    class: 'graph-visual wb-schema-graph',
    'aria-label': '数据库关系图'
  });
  const toolbar = html('div', {
    class: 'graph-controls'
  });
  const toolbarRow = html('div', {
      class: 'graph-toolbar sg-toolbar'
    }),
    scopes = html('div', {
      class: 'graph-filters sg-modes',
      role: 'group',
      'aria-label': '关系图范围'
    });
  const scopeIndicator = html('span', {
    class: 'graph-filter-indicator',
    'aria-hidden': 'true'
  });
  scopes.append(scopeIndicator);
  let scopeGeometry = null;
  const pathScopes = html('div', {
    class: 'path-modes graph-path-filters sg-modes',
    role: 'group',
    'aria-label': '依赖路径深度'
  });
  const controls = new Map();
  const control = (container, action, title, callback) => {
    const button = html('button', {
      type: 'button',
      'data-graph-action': action
    }, title);
    listen(button, 'click', callback);
    container.append(button);
    controls.set(action, button);
    return button;
  };
  for (const [value, title] of [['plan', '本次生成'], ['all', '整库'], ['paths', '依赖路径'], ['issues', issues.length ? `检查问题 · ${issues.length}` : '检查问题']]) {
    control(scopes, value, title, () => {
      currentMode = value;
      if (value === 'paths') {
        pathFocus = currentFocus;
      }
      draw(false, true);
    });
  }
  controls.get('issues').setAttribute('title', '查看当前生成来源与规则检查中的错误和提醒，不代表清空范围检查');
  for (const [value, title] of [['complete', '完整路径'], ['upstream', '全部上游'], ['downstream', '全部下游'], ['neighbors', '仅相邻']]) {
    control(pathScopes, value, title, () => {
      currentMode = 'paths';
      currentPath = value;
      pathFocus = currentFocus;
      draw();
    });
  }
  const search = html('div', {
    class: 'graph-search sg-search'
  });
  const searchIcon = svgElement('svg', {
    class: 'icon',
    viewBox: '0 0 24 24',
    'aria-hidden': 'true'
  });
  searchIcon.append(svgElement('circle', {
    cx: 10,
    cy: 10,
    r: 6
  }), svgElement('path', {
    d: 'm15 15 5 5'
  }));
  search.append(searchIcon);
  const searchInput = html('input', {
    type: 'search',
    'data-graph-search': '',
    'aria-label': '查找表或字段',
    placeholder: '查找表或字段',
    autocomplete: 'off'
  });
  searchInput.value = initialSearch;
  const updateSearch = () => {
    const value = searchInput.value.trim();
    if (value === searchText) {
      return;
    }
    searchText = value;
    draw();
  };
  listen(searchInput, 'compositionstart', () => {
    composing = true;
  });
  listen(searchInput, 'compositionend', () => {
    composing = false;
    updateSearch();
  });
  listen(searchInput, 'input', event => {
    if (!composing && !event.isComposing) {
      updateSearch();
    }
  });
  listen(searchInput, 'keydown', event => {
    if (event.key !== 'Enter' || composing || event.isComposing || !searchText) {
      return;
    }
    const matches = searchMatches();
    const exact = matches.find(node => node.id.toLocaleLowerCase() === searchText.toLocaleLowerCase());
    if (exact || matches.length === 1) {
      event.preventDefault();
      readDependencies((exact || matches[0]).id, true);
    } else if (matches.length) {
      event.preventDefault();
      searchMatchesList.querySelector('button')?.focus();
    }
  });
  search.append(searchInput);
  control(search, 'clear-search', '清空', () => {
    composing = false;
    searchInput.value = '';
    updateSearch();
    searchInput.focus();
  });
  toolbarRow.append(scopes, search);
  const scopeNote = html('p', {
      class: 'graph-scope-note sg-scope'
    }),
    tools = html('div', {
      class: 'graph-meta sg-tools'
    }),
    summary = html('span');
  const pathTitle = html('strong', {
      class: 'mono'
    }),
    pathHeading = html('div', {
      class: 'path-scope-heading'
    });
  const inspectedTable = html('span', {
    class: 'graph-inspected-table'
  });
  const pathScope = html('div', {
    class: 'path-scope'
  });
  pathHeading.append(pathTitle, inspectedTable, pathScopes);
  pathScope.append(pathHeading);
  const readingGuide = html('div', {
    class: 'graph-reading-guide'
  });
  readingGuide.append(scopeNote);
  control(readingGuide, 'focus-readable', '阅读当前表依赖', () => readDependencies(currentFocus));
  const searchResults = html('section', {
    class: 'graph-search-results',
    'aria-label': '匹配的表'
  });
  const searchCount = html('p', {
    class: 'graph-search-count',
    role: 'status',
    'aria-live': 'polite'
  });
  const searchMatchesList = html('ul', {
    class: 'graph-search-matches'
  });
  searchResults.append(searchCount, searchMatchesList);
  const zoomTools = html('div', {
    class: 'graph-tools sg-modes'
  });
  control(zoomTools, 'zoom-out', '−', () => changeZoom(zoom / 1.25)).setAttribute('aria-label', '缩小关系图');
  const zoomLabel = html('span', {
    class: 'graph-zoom-label sg-zoom',
    'data-graph-zoom': '',
    'aria-live': 'polite',
    title: '相对图中节点原始尺寸的实际比例；100% 为自然阅读尺寸'
  }, '100%');
  zoomTools.append(zoomLabel);
  control(zoomTools, 'zoom-in', '＋', () => changeZoom(zoom * 1.25)).setAttribute('aria-label', '放大关系图');
  control(zoomTools, 'fit', '适应画布', () => applyViewport(true)).setAttribute('title', '缩放当前范围，让全部表与关系进入画布');
  control(zoomTools, 'readable', '100% 阅读', () => {
    actualSize = true;
    applyViewport();
    centerFocus();
  }).setAttribute('title', '按自然尺寸阅读当前范围，并居中当前表；可拖动或滚动画布');
  control(zoomTools, 'expand', expanded ? '收起' : '展开', () => {
    expanded = !expanded;
    canvas.classList.toggle('expanded', expanded);
    controls.get('expand').textContent = expanded ? '收起' : '展开';
    controls.get('expand').setAttribute('aria-pressed', String(expanded));
    onExpand(expanded);
    applyViewport();
  }).setAttribute('aria-pressed', String(expanded));
  tools.append(summary, zoomTools);
  const legend = html('div', {
    class: 'graph-state-legend',
    'data-graph-legend': '',
    role: 'group',
    'aria-label': '关系图图例'
  });
  for (const [state, label] of [['chosen', '本次生成'], ['referenced', '仅引用'], ['unused', '其他表'], ['current', '当前查看']]) {
    const item = html('span', {
      class: 'graph-legend-item'
    });
    item.append(html('i', {
      class: `graph-legend-swatch ${state}`,
      'aria-hidden': 'true'
    }), html('span', {}, label));
    legend.append(item);
  }
  const canvas = html('div', {
    class: 'graph-canvas sg-canvas',
    'data-graph-canvas': '',
    tabindex: '0',
    'aria-label': '数据库关系画布，可用方向键平移',
    'aria-describedby': `${markerId}-help`
  });
  canvas.classList.toggle('expanded', expanded);
  const footer = html('div', {
    class: 'graph-footer sg-footer'
  });
  footer.append(html('span', {id: `${markerId}-help`}, `父表 → 子表 · 粗线突出当前表的关联路径，浅线为其他关系。${issues.length ? '橙色表示检查问题。' : ''}拖动画布平移，Ctrl／⌘＋滚轮以鼠标位置缩放，普通滚轮滚动画布；点连线查看列映射。`));
  const labelControl = html('label'),
    labelToggle = html('input', {
      type: 'checkbox',
      'data-graph-label-toggle': ''
    });
  labelToggle.checked = labels;
  labelControl.append(labelToggle, html('span', {}, '显示字段名'));
  footer.append(labelControl);
  listen(labelToggle, 'change', () => {
    const preserveViewport = actualSize || Math.abs(zoom - 1) >= .001;
    labels = labelToggle.checked;
    draw(preserveViewport);
  });
  toolbar.append(toolbarRow, pathScope, readingGuide, searchResults);
  el.append(tools, legend, canvas, footer);
  const problemTables = new Set(issues.flatMap(issue => [issue.table, ...(Array.isArray(issue.tables) ? issue.tables : [])]).filter(id => nodeIds.has(id)));
  function matchesIssue(edge, issue) {
    if (issue.edge_id === edge.id || Array.isArray(issue.edge_ids) && issue.edge_ids.includes(edge.id)) return true;
    if (issue.table !== edge.target || issue.source_table && issue.source_table !== edge.source) return false;
    // Structured column groups preserve identifiers containing commas. Older
    // responses joined a composite FK with commas; compare the complete set.
    const columns = Array.isArray(issue.columns) ? issue.columns
      : issue.column ? String(issue.column).split(',').map(column => column.trim()) : null;
    if (!columns) return true;
    const expected = new Set(columns), actual = new Set(edge.targetColumns || []);
    return expected.size === actual.size && [...expected].every(column => actual.has(column));
  }
  const problemEdges = new Set(data.edges.filter(edge => issues.some(issue => matchesIssue(edge, issue))).map(edge => edge.id));
  const unlocatedIssues = issues.filter(issue => ![issue.table, ...(Array.isArray(issue.tables) ? issue.tables : [])].some(id => nodeIds.has(id))
    && !data.edges.some(edge => matchesIssue(edge, issue)));
  function getView() {
    return {
      mode: currentMode,
      pathMode: currentPath,
      focus: currentFocus || null,
      pathFocus: pathFocus || null,
      search: searchInput.value,
      labels,
      zoom,
      actualSize,
      expanded,
      scrollLeft: nonnegative(canvas.scrollLeft),
      scrollTop: nonnegative(canvas.scrollTop),
      edgeId: selectedEdge
    };
  }
  function publishView() {
    if (destroyed || pendingViewport || composing) {
      return;
    }
    const view = getView(),
      serialized = JSON.stringify(view);
    if (serialized === lastView) {
      return;
    }
    lastView = serialized;
    onViewChange(view);
  }
  function searchMatches() {
    if (!searchText) {
      return [];
    }
    const query = searchText.toLocaleLowerCase();
    return searchData().nodes.filter(node => [node.id, node.name, node.label, ...(tableByName.get(node.id)?.columns || []).map(column => column.name)].some(value => typeof value === 'string' && value.toLocaleLowerCase().includes(query)));
  }
  function searchData() {
    return currentMode === 'plan' ? globalThis.SqlseedDependencyView.selectPlanGraph(data) : data;
  }
  function projection() {
    if (searchText) {
      const matches = searchMatches();
      const source = searchData();
      const visible = new Set();
      for (const match of matches) {
        const paths = globalThis.SqlseedDependencyView.selectGraph(source, match.id, 'paths');
        for (const node of paths.nodes) {
          visible.add(node.id);
        }
      }
      return visibleGraph(visible, source);
    }
    if (currentMode === 'all') {
      return data;
    }
    if (currentMode === 'plan') {
      return globalThis.SqlseedDependencyView.selectPlanGraph(data);
    }
    if (currentMode === 'paths') {
      return globalThis.SqlseedDependencyView.selectGraph(data, pathFocus, currentPath === 'complete' ? 'paths' : currentPath);
    }
    const visible = new Set(problemTables);
    // Global configuration errors need the selected context, not an empty graph
    // that could be mistaken for a successful check. Do not mark every FK bad.
    if (unlocatedIssues.length) {
      for (const node of globalThis.SqlseedDependencyView.selectPlanGraph(data).nodes) visible.add(node.id);
    }
    for (const edge of data.edges) {
      if (problemEdges.has(edge.id)) {
        visible.add(edge.source);
        visible.add(edge.target);
      }
    }
    return visibleGraph(visible);
  }
  function highlightFocus() {
    // Highlight the complete dependency closure within the existing projection.
    // This includes sources needed by child branches without moving any nodes.
    const paths = globalThis.SqlseedDependencyView.selectGraph(data, currentFocus, 'paths');
    const relatedNodes = new Set(paths.nodes.map(node => node.id));
    relatedEdges = new Set(paths.edges.map(edge => edge.id));
    for (const node of canvas.querySelectorAll('[data-graph-node]')) {
      const id = node.dataset.graphNode,
        selected = id === currentFocus;
      node.dataset.current = String(selected);
      node.setAttribute('aria-pressed', String(selected));
      node.classList.toggle('focused', selected);
      node.classList.toggle('path-related', relatedNodes.has(id));
      node.classList.toggle('path-unrelated', !relatedNodes.has(id));
    }
    highlightEdges();
    updateContext();
  }
  function highlightEdges() {
    for (const element of canvas.querySelectorAll('[data-graph-edge],[data-graph-label]')) {
      const id = element.dataset.graphEdge || element.dataset.graphLabel;
      const selected = id === selectedEdge,
        related = relatedEdges.has(id);
      element.classList.toggle('focused', selected);
      element.setAttribute('aria-pressed', String(selected));
      element.classList.toggle('path-related', related);
      element.classList.toggle('path-unrelated', !related);
      let marker;
      if (element.classList.contains('problem')) {
        marker = 'problem';
      } else if (selected) {
        marker = 'focused';
      } else if (related) {
        marker = 'related';
      } else {
        marker = 'normal';
      }
      element.querySelector('.edge-line')?.setAttribute('marker-end', `url(#${markerId}-${marker})`);
    }
  }
  function updateContext() {
    pathTitle.textContent = pathFocus ? `${pathFocus} 的依赖路径` : '未选择表';
    inspectedTable.textContent = currentFocus ? `当前查看：${currentFocus}` : '';
    inspectedTable.hidden = !currentFocus || currentFocus === pathFocus;
    const notes = {
      complete: '保留下游所需的全部上游来源。',
      upstream: '显示当前表及所有上游来源。',
      downstream: '显示当前表及所有下游影响。',
      neighbors: '仅显示直接相邻关系，不代表完整依赖路径。'
    };
    if (searchText) {
      scopeNote.textContent = currentMode === 'plan'
        ? `仅在本次生成及引用来源中搜索“${searchText}”。选择结果可阅读完整结构依赖。`
        : `搜索“${searchText}”匹配的表及完整依赖路径。选择结果可聚焦阅读。`;
    } else if (currentMode === 'plan') {
      scopeNote.textContent = '本次生成 · 仅显示已勾选的表及本次引用来源；查看完整结构请切换整库。';
    } else if (currentMode === 'paths') {
      scopeNote.textContent = `${pathFocus || '未选择表'} · ${notes[currentPath]}`;
    } else if (currentMode === 'issues') {
      scopeNote.textContent = !issues.length ? emptyIssuesHint() : unlocatedIssues.length
        ? '部分问题属于整个生成计划；显示所选上下文，请结合依赖检查详情处理。'
        : '显示当前生成来源与规则检查中的错误和提醒，以及涉及的表和引用关系；清空范围另行检查。';
    } else {
      scopeNote.textContent = '整库总览 · 总览用于看关系分布，阅读字段或路径请聚焦表。';
    }
    const read = controls.get('focus-readable');
    read.disabled = !nodeIds.has(currentFocus);
    read.setAttribute('aria-label', `以 100% 阅读 ${currentFocus || '当前表'} 的完整依赖`);
  }
  function emptyIssuesHint() {
    return checked
      ? '当前检查没有发现问题。这里只展示生成来源与规则检查结果，清空范围须在生成计划中另行核对。'
      : '运行依赖检查后，这里会显示生成来源与规则的错误和提醒。查看结构可切换整库；此处不会自动执行检查。';
  }
  function renderSearchResults() {
    searchResults.hidden = !searchText;
    searchMatchesList.replaceChildren();
    if (!searchText) {
      searchCount.textContent = '';
      return;
    }
    const matches = searchMatches(),
      query = searchText.toLocaleLowerCase();
    searchCount.textContent = `匹配 ${matches.length} 张表 · 选择后以 100% 阅读完整依赖`;
    for (const node of matches) {
      const item = html('li'),
        target = html('button', {
          type: 'button',
          class: 'graph-search-match',
          'data-graph-match': node.id,
          'aria-label': `定位 ${node.id} 并阅读完整依赖`
        });
      target.append(html('strong', {
        class: 'mono'
      }, node.id));
      const columns = (tableByName.get(node.id)?.columns || []).filter(column => column.name.toLocaleLowerCase().includes(query));
      if (columns.length) {
        target.append(html('small', {}, `匹配字段：${columns.map(column => column.name).join('、')}`));
      }
      listen(target, 'click', () => readDependencies(node.id, true), true);
      item.append(target);
      searchMatchesList.append(item);
    }
  }
  function readDependencies(id, select = false) {
    if (destroyed || !nodeIds.has(id)) {
      return;
    }
    if (select && (onSelect(id) === false || destroyed)) {
      return;
    }
    currentFocus = id;
    pathFocus = id;
    currentMode = 'paths';
    currentPath = 'complete';
    selectedEdge = null;
    searchText = '';
    searchInput.value = '';
    composing = false;
    draw();
    actualSize = true;
    applyViewport();
    centerFocus();
    const node = [...canvas.querySelectorAll('[data-graph-node]')].find(item => item.dataset.graphNode === id);
    node?.focus?.({
      preventScroll: true
    });
    publishView();
  }
  function highlightEdge(id) {
    selectedEdge = id;
    highlightEdges();
    const edge = data.edges.find(item => item.id === id);
    if (edge) {
      onEdge(edge);
    }
    publishView();
  }
  function positionScopeIndicator(animate = false, resized = false) {
    if (destroyed) return;
    const selected = controls.get(currentMode);
    const group = scopes.getBoundingClientRect();
    const target = selected.getBoundingClientRect();
    if (!scopes.isConnected || !Number.isFinite(target.width) || !Number.isFinite(target.height)
      || target.width <= 0 || target.height <= 0) {
      scopes.removeAttribute('data-indicator-ready');
      scopeGeometry = null;
      return;
    }
    const next = {
      mode: currentMode,
      x: target.left - group.left - (scopes.clientLeft || 0) + (scopes.scrollLeft || 0),
      y: target.top - group.top - (scopes.clientTop || 0) + (scopes.scrollTop || 0),
      width: target.width,
      height: target.height
    };
    if (!resized && scopeGeometry && Object.keys(next).every(key => next[key] === scopeGeometry[key])) return;
    // 只有用户切换已显示的范围时滑动；初载、字体变化与容器缩放直接对齐。
    scopes.setAttribute('data-indicator-slide', String(Boolean(animate && scopeGeometry && next.mode !== scopeGeometry.mode)));
    Object.assign(scopeIndicator.style, {
      transform: `translate(${next.x}px, ${next.y}px)`,
      width: `${next.width}px`,
      height: `${next.height}px`
    });
    scopes.setAttribute('data-indicator-ready', '');
    scopeGeometry = next;
  }
  function draw(preserveViewport = false, animateScope = false) {
    if (destroyed) {
      return;
    }
    const previousFrame = preserveViewport ? frame : null;
    drawingListeners.splice(0).forEach(remove => remove());
    const visible = projection();
    for (const value of GRAPH_MODES) {
      controls.get(value).setAttribute('aria-pressed', String(currentMode === value));
    }
    positionScopeIndicator(animateScope);
    pathScope.hidden = currentMode !== 'paths' || Boolean(searchText);
    for (const value of ['complete', 'upstream', 'downstream', 'neighbors']) {
      controls.get(value).setAttribute('aria-pressed', String(currentPath === value));
    }
    updateContext();
    renderSearchResults();
    controls.get('clear-search').disabled = !searchText;
    summary.textContent = `显示 ${visible.nodes.length} / ${data.nodes.length} 张表 · ${visible.edges.length} 条关系`;
    canvas.replaceChildren();
    frame = null;
    if (!visible.nodes.length) {
      svg = null;
      stage = null;
      layout = null;
      zoomLabel.textContent = '—';
      for (const action of ['zoom-in', 'zoom-out', 'fit', 'readable']) {
        controls.get(action).disabled = true;
      }
      const emptyGraphHint = () => {
        if (searchText) {
          return '没有匹配的表或字段，可清空搜索或换一个关键词。';
        } else if (currentMode === 'all') {
          return '当前数据库没有可展示的表。';
        } else if (currentMode === 'plan') {
          return '尚未选择生成表。请在左侧勾选，或切换整库浏览结构。';
        } else if (currentMode === 'issues') {
          return issues.length
            ? '检查发现问题，但当前结构中没有可定位的表。请查看依赖检查详情。'
            : emptyIssuesHint();
        } else {
          return '当前范围没有匹配的表，可切换整库查看。';
        }
      };
      const empty = html('div', {
        class: 'graph-empty sg-empty'
      }, emptyGraphHint());
      if (currentMode === 'plan' && !searchText) {
        const showAll = html('button', {type: 'button', class: 'wb-button graph-empty-action'}, '查看整库');
        listen(showAll, 'click', () => {
          currentMode = 'all';
          draw(false, true);
          controls.get('all').focus({preventScroll: true});
        }, true);
        empty.append(showAll);
      }
      canvas.append(empty);
      pendingViewport = null;
      publishView();
      return;
    }
    layout = globalThis.SqlseedGraphLayout.layoutGraph(visible.nodes, visible.edges);
    layout = globalThis.SqlseedGraphLayout.placeEdgeLabels(layout, labels ? visible.edges.map(edge => ({
      edgeId: edge.id,
      text: relationText(edge)
    })) : []);
    stage = html('div', {
      class: 'graph-stage sg-stage'
    });
    svg = svgElement('svg', {
      class: 'schema-graph',
      viewBox: `0 0 ${layout.width} ${layout.height}`,
      role: 'group',
      'aria-label': '当前范围内的表与外键关系'
    });
    const defs = svgElement('defs');
    for (const [state, color] of [['normal', 'var(--graph-edge-default, var(--graph-chosen-edge))'], ['related', 'var(--teal)'], ['focused', 'var(--graph-inspect)'], ['problem', 'var(--warning)']]) {
      const marker = svgElement('marker', {
        id: `${markerId}-${state}`,
        viewBox: '0 0 10 10',
        refX: 10,
        refY: 5,
        // A selected/thicker route must not also magnify its arrowhead.
        markerUnits: 'userSpaceOnUse',
        markerWidth: 8,
        markerHeight: 8,
        orient: 'auto'
      });
      marker.append(svgElement('path', {
        d: 'M0 0L10 5L0 10Z',
        fill: color
      }));
      defs.append(marker);
    }
    svg.append(defs);
    drawRelationships();
    for (const node of layout.nodes) {
      drawNode(node);
    }
    for (const label of layout.labels) {
      drawLabel(label);
    }
    stage.append(svg);
    canvas.append(stage);
    highlightFocus();
    if (previousFrame) {
      frame = previousFrame;
      const size = canvasSize();
      const fitted = graphViewport(layout, size.width, size.height);
      zoom = previousFrame.scale / fitted.fitScale;
      actualSize = false;
      applyViewport();
    } else {
      applyViewport(true);
    }
    function drawNode(node) {
      const table = tableByName.get(node.id),
        title = node.label || node.name || node.id;
      const selected = node.selected === true,
        referenced = !selected && node.referenced === true;
      const group = svgElement('g', {
        class: `graph-node sg-node${selected ? ' chosen' : ''}${referenced ? ' referenced' : ''}${problemTables.has(node.id) ? ' blocked' : ''}`,
        'data-graph-node': node.id,
        'data-selected': String(selected),
        'data-referenced': String(referenced),
        'data-issue': String(problemTables.has(node.id)),
        role: 'button',
        tabindex: 0,
        'aria-label': `查看 ${title} 的字段与关系`
      });
      const titleText = nodeTitle(title);
      const existing = table?.row_count != null ? `现有 ${table.row_count} 行` : '';
      const metadata = nodeMetadata();
      const state = node.readonly || selected || referenced ? metadata : `其他表，不参与本次生成；${metadata}`;
      group.setAttribute('aria-label', `查看 ${title} 的字段与关系；${state}`);
      group.append(svgElement('title', {}, title), svgElement('rect', {
        class: 'graph-node-body',
        'pointer-events': 'fill',
        x: node.x,
        y: node.y,
        width: node.width,
        height: node.height,
        rx: 8
      }), svgElement('rect', {
        class: 'graph-focus-ring',
        x: node.x - 4,
        y: node.y - 4,
        width: node.width + 8,
        height: node.height + 8,
        rx: 12,
        'aria-hidden': 'true'
      }), svgElement('text', {
        class: 'graph-table-name graph-node-title sg-node-title',
        'pointer-events': 'none',
        x: node.x + 16,
        y: node.y + 29
      }, titleText), svgElement('text', {
        class: 'graph-table-state graph-node-meta sg-node-meta',
        'pointer-events': 'none',
        x: node.x + 16,
        y: node.y + 53
      }, metadata));
      activate(group, () => {
        if (onSelect(node.id) === false || destroyed) {
          return;
        }
        currentFocus = node.id;
        selectedEdge = null;
        highlightFocus();
        publishView();
      });
      svg.append(group);
      function nodeMetadata() {
        let metadata;
        if (node.readonly) {
          metadata = '外部引用 · 只读';
        } else if (selected) {
          metadata = `本次生成${node.count != null ? " " + node.count + " 行" : ''}`;
        } else if (referenced) {
          metadata = `仅引用${existing ? " · " + existing : ''}`;
        } else {
          metadata = `${table?.columns?.length || 0} 个字段${existing ? " · " + existing : ''}`;
        }
        return metadata;
      }
    }
    function drawRelationships() {
      for (const edge of layout.edges) {
        const group = svgElement('g', {
          class: `graph-edge sg-edge${problemEdges.has(edge.id) ? ' problem' : ''}${selectedEdge === edge.id ? ' focused' : ''}`,
          'data-graph-edge': edge.id,
          'data-issue': String(problemEdges.has(edge.id)),
          role: 'button',
          tabindex: 0,
          'aria-label': relationText(edge)
        });
        group.append(svgElement('title', {}, relationText(edge)), svgElement('path', {
          class: 'edge-hit sg-hit',
          'vector-effect': 'non-scaling-stroke',
          d: edge.path
        }), svgElement('path', {
          class: 'edge-line sg-route',
          'vector-effect': 'non-scaling-stroke',
          'pointer-events': 'none',
          d: edge.path
        }));
        activate(group, () => highlightEdge(edge.id));
        svg.append(group);
      }
      const leaders = svgElement('g', {
        class: 'graph-label-leaders',
        'aria-hidden': 'true'
      });
      for (const label of layout.labels) {
        if (label.leaderPath) {
          leaders.append(svgElement('path', {
            class: 'sg-leader',
            d: label.leaderPath
          }));
        }
      }
      svg.append(leaders);
    }
    function drawLabel(label) {
      const group = svgElement('g', {
        class: `graph-label sg-label${problemEdges.has(label.edgeId) ? ' problem' : ''}${selectedEdge === label.edgeId ? ' focused' : ''}`,
        'data-graph-label': label.edgeId,
        role: 'button',
        tabindex: 0,
        'aria-label': label.text
      });
      group.append(svgElement('title', {}, label.text), svgElement('rect', {
        'pointer-events': 'fill',
        x: label.x,
        y: label.y,
        width: label.width,
        height: label.height,
        rx: 4
      }));
      const text = svgElement('text', {'pointer-events':'none'});
      label.lines.forEach((line, index) => text.append(svgElement('tspan', {
        x: label.textX,
        y: label.textY + index * label.lineHeight
      }, line)));
      group.append(text);
      activate(group, () => highlightEdge(label.edgeId));
      svg.append(group);
    }
  }
  function canvasSize() {
    return measuredCanvas || {
      width: canvas.clientWidth || 800,
      height: canvas.clientHeight || 420
    };
  }
  function applyViewport(reset = false, anchor = null) {
    if (destroyed || !layout || !svg || !stage) {
      return;
    }
    const {width, height} = canvasSize();
    const old = frame;
    const centerX = old ? ((canvas.scrollLeft || 0) + old.viewportWidth / 2 - old.left) / old.scale : layout.width / 2;
    const centerY = old ? ((canvas.scrollTop || 0) + old.viewportHeight / 2 - old.top) / old.scale : layout.height / 2;
    if (pendingViewport) {
      zoom = pendingViewport.zoom;
      actualSize = pendingViewport.actualSize;
    } else if (reset) {
      zoom = 1;
      actualSize = false;
    }
    frame = graphViewport(layout, width, height, zoom, actualSize);
    zoom = frame.zoom;
    // Scale naturally when fitting a large graph, but cap arrowheads at 10 CSS
    // pixels while zooming in. Marker size is independent of route emphasis.
    const arrowSize = Math.min(8, 10 / frame.scale);
    for (const marker of svg.querySelectorAll('marker')) {
      marker.setAttribute('markerWidth', arrowSize);
      marker.setAttribute('markerHeight', arrowSize);
    }
    Object.assign(stage.style, {
      width: frame.stageWidth + 'px',
      height: frame.stageHeight + 'px'
    });
    svg.setAttribute('width', frame.svgWidth);
    svg.setAttribute('height', frame.svgHeight);
    Object.assign(svg.style, {
      width: frame.svgWidth + 'px',
      height: frame.svgHeight + 'px',
      left: frame.left + 'px',
      top: frame.top + 'px'
    });
    zoomLabel.textContent = Math.round(frame.scale * 100) + '%';
    zoomLabel.setAttribute('aria-label', `图形实际缩放 ${zoomLabel.textContent}`);
    for (const action of ['zoom-in', 'zoom-out', 'fit']) {
      controls.get(action).disabled = false;
    }
    controls.get('fit').setAttribute('aria-pressed', String(!actualSize && Math.abs(zoom - 1) < .001));
    controls.get('readable').disabled = Math.abs(frame.scale - 1) < .001;
    if (pendingViewport) {
      canvas.scrollLeft = pendingViewport.scrollLeft;
    } else if (reset) {
      canvas.scrollLeft = 0;
    } else if (anchor) {
      canvas.scrollLeft = Math.max(0, Math.min(frame.stageWidth - width, frame.left + anchor.x * frame.scale - anchor.viewportX));
    } else {
      canvas.scrollLeft = Math.max(0, frame.left + centerX * frame.scale - width / 2);
    }
    if (pendingViewport) {
      canvas.scrollTop = pendingViewport.scrollTop;
    } else if (reset) {
      canvas.scrollTop = 0;
    } else if (anchor) {
      canvas.scrollTop = Math.max(0, Math.min(frame.stageHeight - height, frame.top + anchor.y * frame.scale - anchor.viewportY));
    } else {
      canvas.scrollTop = Math.max(0, frame.top + centerY * frame.scale - height / 2);
    } // A new graph may be built before its host is attached. Restore again on
    // the first measured resize instead of committing fallback dimensions.
    if (canvas.clientWidth > 0 && canvas.clientHeight > 0) {
      pendingViewport = null;
    }
    publishView();
  }
  function centerFocus() {
    const node = layout?.nodes.find(item => item.id === currentFocus);
    if (!node || !frame) {
      return;
    }
    canvas.scrollLeft = Math.max(0, frame.left + (node.x + node.width / 2) * frame.scale - frame.viewportWidth / 2);
    canvas.scrollTop = Math.max(0, frame.top + (node.y + node.height / 2) * frame.scale - frame.viewportHeight / 2);
    publishView();
  }
  function changeZoom(value, anchor = null) {
    zoom = Math.min(Math.max(8, 2 / (frame?.fitScale || 1)), Math.max(.25, value));
    actualSize = false;
    applyViewport(false, anchor);
  }
  listen(canvas, 'wheel', event => {
    if (!event.ctrlKey && !event.metaKey) return;
    // Cancel browser page zoom only on this canvas, including at zoom limits.
    // An ordinary wheel remains native scrolling and does not alter the view.
    event.preventDefault();
    if (!frame || drag || !Number.isFinite(event.deltaY) || !event.deltaY
      || !Number.isFinite(event.clientX) || !Number.isFinite(event.clientY)) return;
    const bounds = canvas.getBoundingClientRect();
    const viewportX = event.clientX - bounds.left - (canvas.clientLeft || 0);
    const viewportY = event.clientY - bounds.top - (canvas.clientTop || 0);
    const anchor = {
      x: (canvas.scrollLeft + viewportX - frame.left) / frame.scale,
      y: (canvas.scrollTop + viewportY - frame.top) / frame.scale,
      viewportX,
      viewportY
    };
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? frame.viewportHeight : 1;
    const delta = Math.max(-100, Math.min(100, event.deltaY * unit));
    pendingViewport = null;
    changeZoom(zoom * Math.exp(-delta * .002), anchor);
  }, false, {passive: false});
  listen(canvas, 'pointerdown', event => {
    if (event.button !== 0 || event.target.closest('[data-graph-node],[data-graph-edge],[data-graph-label]')) {
      return;
    }
    drag = {
      x: event.clientX,
      y: event.clientY,
      left: canvas.scrollLeft || 0,
      top: canvas.scrollTop || 0
    };
    canvas.setPointerCapture?.(event.pointerId);
    canvas.classList.add('dragging');
  });
  listen(canvas, 'pointermove', event => {
    if (drag) {
      canvas.scrollLeft = drag.left + drag.x - event.clientX;
      canvas.scrollTop = drag.top + drag.y - event.clientY;
      publishView();
    }
  });
  const stopDrag = () => {
    drag = null;
    canvas.classList.remove('dragging');
  };
  listen(canvas, 'pointerup', stopDrag);
  listen(canvas, 'pointercancel', stopDrag);
  listen(canvas, 'keydown', event => {
    if (event.target !== canvas) {
      return;
    }
    const delta = {
      ArrowLeft: [-60, 0],
      ArrowRight: [60, 0],
      ArrowUp: [0, -60],
      ArrowDown: [0, 60]
    }[event.key];
    if (delta) {
      event.preventDefault();
      canvas.scrollLeft += delta[0];
      canvas.scrollTop += delta[1];
      publishView();
    }
  });
  listen(canvas, 'scroll', publishView);
  if (expanded) {
    onExpand(true);
  }
  draw();
  const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(entries => {
    if (destroyed) return;
    const bounds = entries.find(entry => entry.target === canvas)?.contentRect;
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) return;
    if (measuredCanvas?.width === bounds.width && measuredCanvas?.height === bounds.height) return;
    // clientWidth/clientHeight 会取整；缩放后的不足 1px 溢出可能让两个滚动条
    // 交替出现。使用实际内容区尺寸，并在后续缩放/重绘中沿用同一精度。
    measuredCanvas = {width: bounds.width, height: bounds.height};
    applyViewport();
  });
  resizeObserver?.observe(canvas);
  const scopeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => positionScopeIndicator(false, true));
  scopeObserver?.observe(scopes);
  for (const mode of GRAPH_MODES) scopeObserver?.observe(controls.get(mode));
  function focusTable(id) {
    if (destroyed || !nodeIds.has(id)) {
      return false;
    }
    const visible = projection().nodes.some(node => node.id === id),
      hadSearch = Boolean(searchText);
    currentFocus = id;
    selectedEdge = null;
    searchText = '';
    searchInput.value = '';
    composing = false;
    if (!visible) {
      currentMode = 'paths';
      currentPath = 'complete';
      pathFocus = id;
    }
    if (!visible || hadSearch) {
      draw();
    } else {
      highlightFocus();
    }
    centerFocus();
    const node = [...canvas.querySelectorAll('[data-graph-node]')].find(item => item.dataset.graphNode === id);
    node?.focus?.({
      preventScroll: true
    });
    return true;
  }
  return {
    el,
    toolbar,
    getView,
    focusTable,
    destroy() {
      destroyed = true;
      resizeObserver?.disconnect();
      scopeObserver?.disconnect();
      drawingListeners.splice(0).forEach(remove => remove());
      listeners.splice(0).forEach(remove => remove());
    }
  };
  function restoredMode() {
    let currentMode;
    if (GRAPH_MODES.includes(restored.mode)) {
      currentMode = restored.mode;
    } else if (GRAPH_MODES.includes(mode)) {
      currentMode = mode;
    } else {
      currentMode = 'all';
    }
    return currentMode;
  }
  function initialViewport() {
    let pendingViewport;
    if (initialView) {
      pendingViewport = {
        zoom: Number.isFinite(restored.zoom) && restored.zoom > 0 ? restored.zoom : 1,
        actualSize: restored.actualSize === true,
        scrollLeft: nonnegative(restored.scrollLeft),
        scrollTop: nonnegative(restored.scrollTop)
      };
    } else {
      pendingViewport = null;
    }
    return pendingViewport;
  }
}
