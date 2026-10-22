# 项目流程与系统架构图

图表对照当前源码绘制：`backend/engine.py`、`api.py`、`storage.py`、`projects.py`、`recorder.py`、`exporter.py`，以及 `public/renderer.js` 和 React 工作台。

| 图表 | GitHub 展示 | 图片 | 交互版 | 可编辑结构 |
| --- | --- | --- | --- | --- |
| 从图片到绘画过程 | [SVG](workflow.svg) | [PNG](workflow.png) | [HTML](workflow.html) | [JSON](workflow.workflow.json) |
| 核心技术架构 | [SVG](architecture.svg) | [PNG](architecture.png) | [HTML](architecture.html) | [JSON](architecture.architecture.json) |

GitHub README 使用自包含静态 SVG，支持系统深浅主题并保持矢量清晰度；PNG 为浅色展示备份。下载 HTML 后用浏览器打开，可切换主题、查看连线动效与导出图片。图表文件不参与软件运行。

## 编辑与重新生成

图表使用 `dynamic-archify` 技能的 workflow / architecture JSON 渲染器生成。先修改对应 JSON，再运行该工具的渲染器生成同名 HTML；`export_static.py` 从 HTML 提取静态 SVG，保留主题变量并移除动效：

```powershell
node <dynamic-archify>/renderers/workflow/render-workflow.mjs docs/diagrams/workflow.workflow.json docs/diagrams/workflow.html
node <dynamic-archify>/renderers/architecture/render-architecture.mjs docs/diagrams/architecture.architecture.json docs/diagrams/architecture.html
python docs/diagrams/export_static.py
```

没有该工具时，也可使用普通文本或矢量编辑器直接编辑 SVG。本次图表经过 JSON Schema 校验、渲染器布局检查和浏览器视觉检查。SVG 的节点、箭头与文字可单独编辑。

渲染模板由 Archify / dynamic-archify 提供，遵循 MIT 许可；原始许可见 [ARCHIFY-LICENSE.txt](ARCHIFY-LICENSE.txt)。HTML 保留工具署名。图表内容与布局根据 StrokeScape 当前实现整理。

## 图中边界

- 进程池用于笔触生成，线程池用于视频导出调度；没有引入 Redis、Celery 或云端服务。
- CuPy 仅可选加速密集结构分析，笔触选择、反馈与时间编排仍在 CPU 执行。
- Canvas 是应用、HTML 与视频共用的正式渲染器；OpenCV 用于近似反馈与生成中缩略图。
- 文件与 SQLite 通过作品编号关联；图中只展示主要调用和交付关系，不表示所有 API 请求或返回路径。
