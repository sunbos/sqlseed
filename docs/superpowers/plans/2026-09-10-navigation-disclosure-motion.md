# 导航、折叠与页面过渡实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在已确认的单一主题中完成紧凑顶部导航、圆头折叠指示和短暂页面过渡，保持操作响应与可访问性。

**Architecture:** 保留原生 ES modules、hash router、details/summary 和既有生命周期。导航与内容动效仅为呈现层增强，不等待动画后再执行路由；折叠优先 CSS 渐进增强，不引入运行库。

**Tech Stack:** 原生 JavaScript、CSS、Node 内置测试、Playwright、现有 FastAPI 静态资源服务。

---

## 设计约定与授权

用户已选择圆头 Chevron 作为默认折叠方式，并授权参考导航与页面过渡设计。本次直接落实这部分；保留配色、字体用途、现有四项导航与正式任务边界。参考页面的中性导航、轻描边和圆润控件用于节奏判断，不复制内容网站的大标题、卡片布局或品牌资产。

当前工作区存在大量既有未提交内容，本轮在当前目录定点修改并记录验证；不重置、提交或推送既有改动。组件安装卸载和预览布局重构属于之前研究的独立功能，不混入本次动效实现。

视觉约定：桌面顶部品牌在左、导航在中、连接在右；导航文字保持稳定尺寸与字重，选中项通过浅底色、文字和圆润指示线表达。窄屏四个入口保持直接可达。配色继续使用 `--paper`、`--wash`、`--ink`、`--muted`、`--line`、`--teal`、`--soft`。

动效约定：交互状态约 160ms，页面淡入约 180ms，折叠约 200ms，统一平缓结束的 easing；不做弹跳、页面大幅平移或逐卡片入场。设置减少动态效果时立即切换。

## Task 1：顶部导航与页面过渡

**Files:**
- Create: `plugins/sqlseed-web/src/sqlseed_web/static/navigation.css`
- Modify: `plugins/sqlseed-web/src/sqlseed_web/static/js/app.js`
- Test: `plugins/sqlseed-web/tests/test_navigation_motion.cjs`

- [x] 使用 `#nav` 和产品 header 的明确选择器提供紧凑导航；与基础样式不同的作用范围必须明确，避免全局 button 覆盖。活动状态保留 `aria-current="page"`。
- [x] 新路由根节点仅在不同顶层页面之间添加 `page-enter`；初载、连接重挂载、同页参数改变不播放。实现顺序如下，不延迟 import 或 mount：

```js
const root = module.render();
if (renderedPage && renderedPage !== page) root.classList.add('page-enter');
main.replaceChildren(root);
renderedPage = page;
await module.mount?.();
```

沿用当前 `routeVersion` 检查。只有已成功提交的页面才更新 `renderedPage`。页面渐入仅涉及 opacity，不使用 transform；动画结束后不保留额外动画层。

- [x] CSS 定义可被系统偏好关闭的一次动画，默认完成后不保留额外动画层：

```css
@keyframes page-enter { from { opacity: .65; } to { opacity: 1; } }
#app > .page-enter { animation: page-enter 180ms ease-out; }
@media (prefers-reduced-motion: reduce) {
  #app > .page-enter { animation: none; }
}
```

- [x] 编写真实 router 行为测试：A→B→C 迟到 import 不替换 C；不同顶层页才加类；同页和连接事件不加类；mount 无需等待动画，生命周期调用次数正确。
- [x] 执行 `node --test plugins/sqlseed-web/tests/test_app_shell.cjs plugins/sqlseed-web/tests/test_navigation_motion.cjs`，预期全部通过。

## Task 2：原生折叠与一致 Chevron

**Files:**
- Create: `plugins/sqlseed-web/src/sqlseed_web/static/disclosure.css`
- Modify when necessary: `plugins/sqlseed-web/src/sqlseed_web/static/js/workbench/ui.js`
- Test: `plugins/sqlseed-web/tests/test_disclosure_focus.cjs`

- [x] 正式页面和弹窗的 summary 隐藏浏览器默认 marker，用同一圆头、圆转角 SVG mask 表达向下/向上状态；保持整行热点和 focus-visible。保留标题文字作为可访问名称，不给每行新增翻译字符串。
- [x] 清除数据库结构操作的旧字符 Chevron 视觉冲突，并让下拉触发器使用同一家族形态，仍保留其 combobox 语义与既有键盘行为。
- [x] 折叠动画以 `::details-content`、`interpolate-size`、离散 content-visibility 过渡与 `interactivity: inert` 做 feature-gated 渐进增强；关闭期间立即隔离交互。默认不开启全局高度插值；缺特性时原生开合正常可用。支持减少动态效果，不添加点击拦截或延迟隐藏的可聚焦内容。
- [x] 窄修弹窗 focus trap：把 summary 纳入候选；折叠 details 后代中只有首个 summary 子树可进入焦点候选。保留 disabled、hidden、既有 tabindex 判断，不重写弹窗生命周期。
- [x] 用真实 modal 代码验证关闭内容中的按钮被排除、summary 可进入循环、展开后内部操作恢复可达；执行 `node --test plugins/sqlseed-web/tests/test_disclosure_focus.cjs plugins/sqlseed-web/tests/test_connection.cjs`。

## Task 3：集成与浏览器验收

**Files:**
- Modify: `plugins/sqlseed-web/src/sqlseed_web/static/style.css`（仅共享样式导入）
- Update: 本计划与 `plugins/sqlseed-web/src/sqlseed_web/static/AGENTS.md` 中当前视觉约定
- Create: `docs/design-review/2026-09-10-navigation-motion/README.md` 及截图

- [x] 主样式导入两个新增 stylesheet，不增加另一套 tokens、CDN 或构建步骤。
- [x] 审阅实现范围与代码质量，再运行 `node --test plugins/sqlseed-web/tests/test_*.cjs`；测试失败按实际原因处理，不能为过关删除生命周期保护。
- [x] 仅在独立浏览器 tab 检查实际服务，不改数据库、配置、插件或模型；静态文件无缓存可直接取得，无须重启正式后端。
- [x] 验证 1144×872、1440×900、390×844 和短屏：导航没有遮挡/换行挤压；四页切换无空白闪烁和旧结果覆盖；快速点击与浏览器后退正常；设置、字段 CHECK、高级选项的开合正常；减少动态效果时无页面/折叠动画；键盘焦点正确。
- [x] 保存可 review 的截图和验证说明，明确本轮没有重新验证真实 LLM、PostgreSQL 或新增环境管理能力。

## 完成记录

本轮 578 项前端回归通过，并在实际 Chromium 页面检查跨页、原生折叠、键盘、窄屏与系统偏好。浏览器实测发现的关闭过渡焦点问题已通过特性检测与即时交互隔离修正。截图、测量与未验证范围见 [验收记录](../../design-review/2026-09-10-navigation-motion/README.md)。
