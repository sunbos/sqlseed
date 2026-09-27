sqlseed README 品牌资源
=====================

sqlseed-wordmark-light.svg 和 sqlseed-wordmark-dark.svg 供根 README.md / README.zh-CN.md
的 <picture> 使用。默认使用浅色版本，深色版本按 prefers-color-scheme 选择。
两者背景透明，具有 title/desc；README 的 img 保留 alt="sqlseed" 和固定宽高。

来源
----
- 叶芽表格图标：plugins/sqlseed-web/src/sqlseed_web/static/index.html 的 .brand-mark。
  rect/path 的几何、线宽和透明度逐项原样保留，没有另外设计图标。
- 字标：项目已有 ChillRoundGothic-Medium.woff2 的 sqlseed. 字形轮廓。
  路径：plugins/sqlseed-web/src/sqlseed_web/static/fonts/chill-round-gothic/
  字体 SHA-256：2f59b5d4ca9e1e1f0ce8ce03935635b2cec6257919e4b486647b638df8f7a9de
  来源和 OFL-1.1 许可证见该目录的 README.md 与 License.txt。
- 配色：Web style.css 的 --ink、--teal 及 .brand::after。
  浅色 ink #293b3e / teal #24634f；深色 ink #e3eeec / teal #9bd4bf；句点 #648d79。

生成与维护
----------
SVG 不含字体文件、文字渲染节点、脚本或外部资源。字标已转为矢量路径，因此 GitHub
与离线查看均不需要加载字体，也不依赖本机字体替换。

使用 fonttools 4.66.0 的 TTFont、SVGPathPen 与 TransformPen，从上述本地 Medium
字体的 cmap 获取字形并逐字绘制。字体 unitsPerEm=1000；采用 Web 的 23px 字号、
-1px 字距，缩放为 (0.023, -0.023)。首字横坐标 40，基线 26.5；每字推进
glyph.width * 0.023 - 1；句点在最后推进位置额外加 1（对应 Web 的 gap 和负 margin）。
路径数值保留三位小数。图标外层 translate(3 6.5) scale(.84375)，对应 27px 图标。
画布 viewBox="0 0 128 40"，README 显示尺寸 256×80。

今后品牌图标、字形或配色变化时，应同时更新两份 SVG；两个 README 共用同一组资源。
请保留字标轮廓与相对比例，不把系统字体或 CDN 字体重新写入 SVG。
