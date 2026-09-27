# 寒蝉圆黑体本地网页字体

本目录随 `sqlseed-web` 的 wheel 一起分发，页面从同源 `/static/fonts/chill-round-gothic/` 加载，不访问 CDN，也不要求在操作系统安装字体。字体保留上游完整字符集，没有根据当前页面文字裁字。

## 来源与授权

- 官方仓库：[Warren2060/ChillRoundGothic](https://github.com/Warren2060/ChillRoundGothic)。
- 固定提交：[`53505f0818983d2fcdda00dc66e051ad13e81ffb`](https://github.com/Warren2060/ChillRoundGothic/tree/53505f0818983d2fcdda00dc66e051ad13e81ffb)。
- 原始文件：[Regular WOFF](https://raw.githubusercontent.com/Warren2060/ChillRoundGothic/53505f0818983d2fcdda00dc66e051ad13e81ffb/woff/ChillRoundGothic_Regular.woff)、[Medium WOFF](https://raw.githubusercontent.com/Warren2060/ChillRoundGothic/53505f0818983d2fcdda00dc66e051ad13e81ffb/woff/ChillRoundGothic_Medium.woff)。两条路径均已与该提交的官方 `woff` 目录核对。
- 字体授权为 **SIL Open Font License 1.1（OFL-1.1）**，不是应用代码的 AGPL 授权。原始 [License.txt](License.txt) 随字体原样保留；[上游许可证](https://raw.githubusercontent.com/Warren2060/ChillRoundGothic/53505f0818983d2fcdda00dc66e051ad13e81ffb/License.txt) 的版权人为 `The ChillRoundGothic Project Authors`。
- 上游许可证文件的版权头未列出保留字体名；但字体内嵌版权元数据声明了 Adobe 的保留名 `Source` 和 ChillType 的保留名 `ChillRounded`，因此不能将本字体描述成“没有保留字体名”。本次格式转换保留了原始版权和命名元数据；实际字体族名为 `Chill Round Gothic` / `Chill Round Gothic Medium`，没有使用这两个保留名。新增 CSS 字体族别名也不应使用上述保留名。
- 本地修改仅为 WOFF → WOFF2 格式转换。未修改字形、字宽、字重、字符映射、排版或许可证。字体单独及转换版本仍按 OFL-1.1 分发，不以字体作者名义为应用背书。
- 网页字体转换与命名规则参考 [OFL 官方 FAQ 第 2 节](https://openfontlicense.org/ofl-faq/#2-using-ofl-fonts-for-web-pages-and-online-web-font-services)，后续若裁字或修改字体应重新核对授权与命名条件。

## 字重与文件

| 本地文件 | CSS `font-weight` | WOFF 原文件 | WOFF2 文件 | Unicode 码点 | 字形 |
| --- | --- | ---: | ---: | ---: | ---: |
| `ChillRoundGothic-Regular.woff2` | `400` | 7,613,220 字节 | 6,139,480 字节 | 27,183 | 27,319 |
| `ChillRoundGothic-Medium.woff2` | `500` | 7,770,248 字节 | 6,326,040 字节 | 27,183 | 27,319 |

`400` / `500` 与源字体 `OS/2.usWeightClass` 一致；两份文件都是独立静态字重，不是可变字体。各覆盖 21,269 个 Unicode 统一汉字、128 个兼容汉字。该覆盖不等于全部 Unicode 汉字；应用仍应提供系统字体回退。

## 浏览器行盒度量

字体每 em 为 1000 units，hhea ascent/descent 为 1160/-288，Win ascent/descent 为 1160/288；typo 度量则为 880/-120。Windows Chromium 原生单行输入内部使用 `line-height: normal`，按较短 typo 度量形成约 13px 行盒时，`g` 的 -250 units 下伸部分会被裁切，即使输入外框仍有 40px 高。

共享 `@font-face` 显式使用 `ascent-override: 116%`、`descent-override: 28.8%`、`line-gap-override: 0%`，对齐原字体已有的 hhea/Win 度量，不改变字体文件、字形或字宽。正式设置页模型名内部文字区域从约 12.67px 恢复到 19.33px，外框保持 40px；交互样板“材质与文字”提供下伸字母、重音与中文的可输入/只读对照。不支持这些描述符的浏览器仍使用原字体度量，跨浏览器验收需单独确认。

定义依据：[CSS Fonts 的字体度量覆盖](https://www.w3.org/TR/css-fonts-5/#font-metrics-override-desc)。

两份 WOFF2 合计 12,465,520 字节，选择保留全量字库以支持用户自己的表名、字段名和数据。文件采用 Brotli 的字体模式压缩，未通过删除字符或排版表减小文件。

## 可复现转换

使用独立临时虚拟环境，未在运行 Web 的环境中安装转换依赖：

- Python 3.12.14
- fonttools 4.66.0
- Brotli 1.2.0
- zopfli 0.4.3（`fonttools[woff]` 的附带依赖，本次 WOFF2 使用 Brotli）

在独立环境中安装 `fonttools[woff]==4.66.0`、`brotli==1.2.0`、`zopfli==0.4.3`，从上述固定 URL 下载两份源文件后执行：

```text
python -m fontTools.ttLib.woff2 compress --hmtx-transform ChillRoundGothic_Regular.woff -o ChillRoundGothic-Regular.woff2
python -m fontTools.ttLib.woff2 compress --hmtx-transform ChillRoundGothic_Medium.woff -o ChillRoundGothic-Medium.woff2
```

fontTools 的此转换入口设置 `recalcBBoxes=False` 和 `recalcTimestamp=False`，保留源字体的尺寸与时间元数据。`--hmtx-transform` 启用 WOFF2 标准的可选字宽表压缩，不改变还原后的字宽。没有运行 `pyftsubset` 或其他字符裁剪步骤。

## SHA-256

| 文件 | SHA-256 |
| --- | --- |
| 源 `ChillRoundGothic_Regular.woff` | `db8b3fafb3ecc1e43c5d3da52351c0c90804e268d8ce311700457465be661603` |
| 本地 `ChillRoundGothic-Regular.woff2` | `aec0b819c2552412082a4cbc99d266e1b00fba3350eb774913ed807c447cb199` |
| 源 `ChillRoundGothic_Medium.woff` | `49dce08c6415786238eb3253418b8732a814b387fa09d5d0fac898f537ec08ac` |
| 本地 `ChillRoundGothic-Medium.woff2` | `2f59b5d4ca9e1e1f0ce8ce03935635b2cec6257919e4b486647b638df8f7a9de` |
| 源及本地 `License.txt` | `bdefa7c6496762298804550255762c4532124282910e976db960b24d04665ad4` |

## 内容核验

转换后重新打开两份 WOFF2，逐项核对源文件与输出的 Unicode `cmap`、完整字形顺序、`hmtx` 字宽及 `name` 元数据，均一致。以下样板包含 101 个不同汉字，两字重均全部覆盖：

> 工作台配置管理运行记录设置数据库数据表字段规则取值预览关系图保存打开编辑生成检查依赖连接服务地址默认模型密码安装组件修复取消应用返回命令格式复制清透玻璃圆角字体用户订单产品姓名年龄邮箱日期时间数量中文汉字简体繁體測試設定讀取

本次还扫描正式静态目录下 `.js` / `.html` 文件包含的 868 个不同统一汉字，两字重均未缺字。这是当前源码文字的覆盖核验，不是跨操作系统视觉验收或任意用户文本都不缺字的承诺。

完整字体表也已核对：除 `head` 表的 WOFF2 压缩标记位和校验和之外，其余表的解压数据逐字节一致，包含 CFF 字形、字符映射、字宽与排版数据；源和输出均未携带独立 WOFF XML 元数据。本次实际构建 wheel 并检查 ZIP 内容，确认两份字体、许可证和本 README 均被打包，字体及许可证内容与本地文件一致。
