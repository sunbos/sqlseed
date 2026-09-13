# 工作台首次使用引导实施清单

> 按本轮用户已批准的“可收起、随状态变化的下一步提示”执行，不增加强制 AI 步骤。

**目标：** 让初次使用者看懂选择范围、检查规则、可选 AI、预览和写入确认之间的关系。

**实现：** 原生 ES modules。`workbench/guidance.js` 只计算提示状态；`pages/workbench.js` 复用既有入口和异步门禁，预览状态使用当前 model/epoch 的真实结果。收起偏好保存在浏览器，不改生成文档。AI 仅 GET 脱敏配置状态，不自动分析或检测连接。

- [x] 在 `tests/test_workbench_guidance.cjs` 验证无选择、规则修改后的旧预览、部分预览、完整预览、输入错误及 AI 缺失/配置状态。
- [x] 在 `static/js/workbench/guidance.js` 实现状态计算；在工作台配置上下文之后渲染紧凑提示。AI 快捷入口打开同一助手并默认已选范围；手动入口只导航；预览入口只读；生成计划入口保留原确认。
- [x] AI 状态加载和助手关闭后刷新不接受已离开页面的响应。新增入口沿用共享在途门禁。收起/展开后保留键盘焦点。
- [x] 运行 `node --test plugins/sqlseed-web/tests/test_*.cjs`、`pytest plugins/sqlseed-web/tests/ -q`，在真实浏览器检查 1144×872 和窄屏、折叠、规则编辑及 AI 跳转。
- [x] 同步 `docs/web-workbench.md`，记录下一轮 AI 对照实验的边界。

本轮不改变 core 去重、数据库约束或已有数据。下一轮先探测现有 Ollama 服务，再在相同数据库副本上对比原规则与 AI 建议；避免重复追加上一轮已成功的 users/orders。AI 保护 PK/FK，不把偶然成功当作已有复合键冲突已修复。

## 本轮验证（2026-09-08）

- Node 前端回归：440 passed（新增 8 项）；日志 `/tmp/sqlseed-guidance-node-20260908.log`。
- Web Python 回归：271 passed；日志 `/tmp/sqlseed-guidance-pytest-20260908.log`。
- 真实浏览器：仅修改隔离浏览器中的未保存配置，勾选 order_items/orders/users，AI 快捷入口默认 selected 范围；数量 0 的“检查输入”正确聚焦数量框，恢复为 100；三表只读预览完成后提示已预览 3 张表。未执行 AI 分析、配置保存或数据库写入。
- 1144、800、700 像素宽检查没有新增页面横向溢出，AI 操作可见。收起后高度 42.59px，焦点保留，刷新后仍收起。
- 独立审查发现错误数量与表搜索过滤后的焦点问题，均已修正并加入回归。
- 效果图：`.playwright-mcp/20260908-next-step-empty.png`、`20260908-next-step-previewed.png`、`20260908-next-step-narrow.png`。
- Ollama 配置状态公开读取为 available/ready，实际模型连通、建议质量及原失败对照留待下一轮真实 AI 测试。
