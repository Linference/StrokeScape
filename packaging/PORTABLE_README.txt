绘序成境 · StrokeScape 0.1.0（Windows 便携版）

一、启动
1. 将 ZIP 完整解压到普通可写文件夹，例如桌面或“文档”。
2. 双击 StrokeScape.exe。
3. 导入图片或使用内置原创示例，选择精度后开始绘制。

不需要安装 Python、Node.js 或 FFmpeg。请保留 _internal 文件夹，不要只复制 EXE。
优先使用 Windows WebView2 桌面窗口；该运行时不可用时，自动使用内置 Chromium 窗口。

二、作品与隐私
日常创作在本机完成。UserData 文件夹保存你的原图、历史任务和导出文件。
本发布包不包含开发者的图片、任务或浏览器资料。

三、功能
速写 18,000 笔；标准 60,000 笔；精细 150,000 笔。
“笔触与画布”可自定义至 200,000 笔，最长边上限为 2560 像素。
支持 HTML 交互作品和 MP4 视频导出。

四、加速
本包提供完整 CPU 绘制能力，不依赖 NVIDIA 显卡。
视频编码会检测可用硬件，无法使用时尝试软件编码。
本包不含庞大的 CuPy/CUDA 计算组件；需要 CUDA 图像计算时可使用源码版配置。

五、遇到问题
请先确认已完整解压，且所在文件夹可以写入。
首次运行生成和导出可能有初始化开销；视频导出耗时与分辨率、时长及帧率有关。
错误记录位于 UserData/StrokeScape.log。
当前为早期版本，尚未提供代码签名；请仅从官方仓库下载并核对 SHA256。

项目与更新：https://github.com/Linference/StrokeScape
问题反馈：https://github.com/Linference/StrokeScape/issues
第三方许可证见 THIRD_PARTY_NOTICES.md 和 ThirdParty 文件夹。
