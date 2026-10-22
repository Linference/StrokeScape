绘序成境 · StrokeScape 首个 Windows 便携测试版。

### 下载与使用

下载 **StrokeScape-0.1.0-Windows-x64.zip**，完整解压后双击 **StrokeScape.exe**。
不需要安装 Python、Node.js、FFmpeg；请保留 `_internal` 文件夹。适用于 Windows 10 / 11 x64。

### 功能

- 上传图片，生成结构感知的四层笔触绘画动画。
- 速写 18,000 笔、标准 60,000 笔、精细 150,000 笔，自定义最高 200,000 笔。
- 交互播放、进度拖动、逐笔查看、历史任务、HTML 及 MP4 导出。
- 本机处理；原图、作品与历史保存在程序旁的 `UserData` 文件夹。
- CPU 后端可独立使用；视频导出自动检测可用硬件编码，并提供软件回退。

本包不包含 CuPy/CUDA 图像计算组件，需要该功能时请使用源码版配置。
当前为早期测试版，尚未代码签名。发布包附 SHA256 校验文件。
高分辨率长视频的逐帧导出可能明显慢于笔触生成；最终画质取决于图片、分辨率与预算。

### 验证与第三方组件

发布前从 ZIP 解压运行，在移除开发工具 PATH 的条件下验证 EXE 启动、笔触生成、串行时间轴、HTML 导出和真实 MP4 导出。

内含未修改的 BtbN LGPL shared FFmpeg。许可证、配置和版本信息位于 `ThirdParty/FFmpeg`。
同一发布页的 **FFmpeg-c8de997cb1-source.zip** 与 **FFmpeg-Builds-937868360a-source.zip** 提供匹配源码与构建脚本；普通用户无需下载这两项源码资产。
其余组件许可见包内 `THIRD_PARTY_NOTICES.md`、`ThirdParty/` 和 Chromium 授权资料。
