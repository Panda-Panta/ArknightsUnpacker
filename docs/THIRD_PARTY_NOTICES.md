# 第三方来源与许可说明

本文件记录本地固定依赖和实际收集到的声明。完整安装包许可证由打包脚本从当前锁定 wheel 的 `dist-info` 中按清单收集，保留于 `_internal/licenses/`，包含实际版本、METADATA 及 LICENSE／NOTICE 原文。此清单不把 Python 包的许可自动推广到随包本地 DLL，也不替代尚未确立的上游许可。

## 固定上游源码

| 组件 | 固定来源 | 本项目使用与许可状态 |
| --- | --- | --- |
| Ark-Unpacker | [4a4b9efc6be4690b68b70b4a16578950baa066d3](https://github.com/isHarryh/Ark-Unpacker/tree/4a4b9efc6be4690b68b70b4a16578950baa066d3) | 参考 PC 文本／AES、AB 与对象处理；改编 `lz4ak`，仅将 Profiler 依赖替换为 `nullcontext`。BSD-3-Clause 原文为 `vendor/Ark-Unpacker-LICENSE`，随包保留。 |
| Ark-FBS-Py | [161d5e229916d7193364983396076556fbeaa549](https://github.com/isHarryh/Ark-FBS-Py/tree/161d5e229916d7193364983396076556fbeaa549) | 使用 CN 生成 schema，位于 `vendor/ark_fbs/CN`；本地适配器映射当前 PC building 根结构，五个新增根字段仅保留未知证据和原始来源，已知资料可解。已检查的固定源码未提供可确立这些 schema 再分发授权的 LICENSE；**许可未确立**，不能推定 Ark-Unpacker 的 BSD 自动覆盖 schema。当前为本机已授权研发／便携验收材料；对外发布前须解决该项。 |

游戏原始文件、商标、图片、文本和音频的权利不因本工具的许可而转移。程序包不附整包游戏数据；用户导出内容的来源由对应 manifest 记录。

## Python 与运行依赖

以下版本由当前 `uv.lock` 固定；若重建改变依赖，应以该包 `build-info.json` 与锁文件为准。

| 组件 | 版本／来源 | 当前发行材料中的声明 |
| --- | --- | --- |
| Python | 3.12 x64；[Python](https://www.python.org/) | PSF 等组合许可，构建时收集实际解释器 `LICENSE.txt`。 |
| PySide6 / Qt / shiboken6 | 6.8.3；[Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html) | wheel METADATA 声明 LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only；wheel 附 `LicenseRef-Qt-Commercial.txt`，并不证明本项目持有商业许可。只收集实际用到的 Qt Core／Gui／Widgets／Multimedia／MultimediaWidgets 与必要插件，动态 DLL 留在目录式包中，可替换；不包含 QtWebEngine。保留 Qt 许可补充原文与来源记录，不据此宣称已完成所有对外分发条件核查。 |
| UnityPy | 1.25.3；[上游](https://github.com/K0lb3/UnityPy) | MIT；包含其运行数据及动态类，完整 wheel LICENSE 随包。 |
| flatbuffers / numpy / lz4 | 25.12.19 / 2.2.6 / 4.4.5 | 分别保留 wheel 的 Apache／BSD 等完整声明；numpy LICENSE 包含其本地库的多项声明。 |
| Pillow / pycryptodome / bson | 11.3.0 / 3.23.0 / 0.5.10 | 保留各 wheel 的 LICENSE 原文，Pillow 含底层图像库声明，pycryptodome 含多来源声明。 |
| texture2ddecoder / etcpak / astc-encoder-py | 1.0.6 / 0.9.15 / 0.1.12 | 保留实际 wheel LICENSE；原生图像解码／编码库的条款以原文为准。 |
| fmod-toolkit / pyfmodex | 0.1.3 / 0.7.2 | Python 代码声明 MIT；FMOD DLL 另见下一节。 |
| archspec / brotli / fsspec / tpk-ar | 当前锁文件精确版本 | UnityPy 传递依赖；METADATA 和提供的许可原文随包。 |
| spine-asset / WannaCRI / ffmpeg-python | 1.1.1 / 0.3.3 / 0.2.0 | 工程锁定依赖，保留提供的许可与 METADATA。WannaCRI 已用于 USM 自动分流；可选外部 FFmpeg 通过进程调用封装，安装 `ffmpeg-python` 不等于附带 FFmpeg 二进制。具体样本验证见下节及验收记录。 |
| attrs / python-dateutil / six / future / typing-extensions / tqdm / python-json-logger / colorama / packaging | 当前锁文件精确版本 | 保留实际 wheel 提供的声明；按 bundle 文件清单确认实际交付内容。 |
| PyInstaller | 6.16.0；[上游](https://pyinstaller.org/) | 构建工具；GPL-2.0-or-later 含 bootloader exception，保留 wheel `COPYING.txt` 原文。构建工具及整个开发环境不随程序目录分发。 |

## FMOD 原生 DLL

UnityPy 音频转换依赖 `fmod_toolkit/libfmod/Windows/x64/fmod.dll`；该 DLL 来自固定 `fmod-toolkit==0.1.3` wheel，构建按原路径收集以支持上游查找。Python 代码的 MIT 声明**不能确立 FMOD DLL 的 MIT 许可**。wheel 的本地材料中只找到 Python 项目 MIT LICENSE，未见覆盖此 DLL 的独立 FMOD 授权原文。

FMOD 为 Firelight Technologies 产品；原生 DLL 条件应查 [FMOD 官方许可入口](https://www.fmod.com/licensing)。本记录不声称获得额外 FMOD 再分发授权或满足对外发布条件。当前本机便携验收可保留与来源绑定的 DLL；对外发布前须单独确认适用许可、署名与再分发条件，或调整音频实现及候选验收。

## FFmpeg 与可选视频处理

0.1.16起，Qt Multimedia播放器随包收集锁定PySide6 wheel自带的FFmpeg媒体插件及动态库；本机avutil-59／avcodec-61／avformat-61的license接口均返回“LGPL version 2.1 or later”，随包补入GNU官方LGPL 2.1原文及来源摘要，Addons的METADATA／所附声明也按清单保留。它们用于本地音视频播放。当前便携包**不分发 FFmpeg／FFprobe 可执行程序**。`ffmpeg-python` 是 Python 包，不是 FFmpeg 二进制。USM 自动模式已通过 WannaCRI 分离视频／音频流，本机样本为 IVF／SFA；原始模式才复制源 USM。程序在 `PATH` 找到用户自行安装的 FFmpeg 后，可复制视频流、将音频转换为 AAC 并封装 MKV；未找到时保留分离流并记录状态。可用的 FFprobe 会用于记录流信息。

本机 USM 样本已完成 FFprobe 音视频流核对及 FFmpeg 前一秒实际解码，证据覆盖该样本的分流、封装和短段解码，不等同于全部视频的完整播放验收。外部 FFmpeg 的许可随用户实际安装的构建选项及其来源而变化；本工具不把 Python 包的许可扩展至该外部程序。完整测试覆盖由项目 README 与 M9／引擎验收记录维护。

## 来源证据和再构建

构建不会联网获取或更改许可证。额外补充的 Qt 许可文本保存在 `packaging/licenses/`，附来源 URL 和 SHA-256；wheel 文件来自当前锁定环境，不凭网络上其他版本替换。`build-info.json`、文件清单、锁文件和本机预检记录共同说明本次来源及证据边界。未知或未附声明项应保留原状并记录，不造作者、日期或许可证。
