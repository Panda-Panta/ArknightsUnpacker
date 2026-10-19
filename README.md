# ArknightsUnpacker · 明日方舟资源与资料工作台

Windows 原生 GUI：浏览《明日方舟》PC 资源、扫描最近更新、解包选中文件，并生成干员／模组 PNG 长图与 PRTS 风格离线 HTML。

**版本 0.1.0。** 已实现本地资源、核心数据、资料计算和导出链路；验收使用的本机数据为 **78.2.0**，资源版本 `26-10-14-13-44-12-52990322`。128 项自动回归、源码真实 Qt 流程、正式 EXE 原生启动及生产服务链分别通过，覆盖与缺口见 [验收摘要](docs/ACCEPTANCE.md)。

## 直接运行

Release 入口：[v0.1.0](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.0) · [Windows x64 ZIP](https://github.com/Panda-Panta/ArknightsUnpacker/releases/download/v0.1.0/ArknightsUnpacker-0.1.0-win64.zip) · [ZIP SHA-256](https://github.com/Panda-Panta/ArknightsUnpacker/releases/download/v0.1.0/ArknightsUnpacker-0.1.0-win64.zip.sha256)。分发目标为私有仓库，访问需要对应仓库权限。

解压完整 ZIP 后，双击其中的 `ArknightsUnpacker.exe`。无需安装 Python，保留同目录的 `_internal` 文件夹。本机已交付目录中的程序也可直接运行；源码仓库不保存 `dist/` 构建产物。

1. 选择游戏目录，在设置中选择独立输出目录。
2. 扫描后浏览目录、查看用途，按需启用“仅 .ab”。最近时间默认 24 小时，可修改。
3. 选中文件解包；双击包可浏览内部对象并选择提取。
4. 在“干员资料”／“模组更新”点击“解析核心数据”，选择资料，预览或导出 PNG、HTML。JSON 和 TXT 同步保存，完整字段来源保留于 JSON。

程序允许选择其他安装位置，游戏文件只读访问，不整理移动游戏原文件。应用设置、快照与缓存默认位于 `%LOCALAPPDATA%\ArknightsUnpacker`。

## 已实现

- 初始／热更双层资源发现、清单和 IDX 解析、来源选择及用途注释；可显示物理文件或当前资源候选。
- 最近写入时间筛选、扫描快照差异、可取消的严格摘要校验；重启后保留历史。
- Unity 图片与显式 Alpha 配对、TextAsset 原始／解码输出、音频、完整 Spine 组、USM 流提取。USM 的可选 MKV 封装需要 PATH 中的 FFmpeg，程序包不附 FFmpeg。
- 满级、满潜、满信赖属性，标明基础／信赖／潜能／单个模组的数值；天赋潜能差额、专三技能、后勤、三级模组资料与语义变化比较。
- 新干员／新模组由完整前后数据快照确定，可一键导出新增资料。首次没有历史基线时显示“历史未知”，不会把所有角色认定为新增。
- PNG 分页、缩放、滚动预览；每名干员独立 HTML，模组合集及批次索引。HTML 的 CSS、脚本、图片均内嵌，正文无 JavaScript 也保留；提供目录、搜索、折叠和打印入口。
- 后台队列、独立解包进程、进度、取消、失败诊断与重试；导出不覆盖旧批次，禁止输出到游戏目录内。

文件修改时间仅表示本机写入时间。快速扫描不会反复读取全部普通 AB 内容；无完整摘要时明确保留元数据证据等级。真实新增识别需要更新前的完整同服基线，不能由 mtime 或干员编号倒推。默认区服未知；同一安装的两次观测可带提示比较，跨来源需明确区服。

## 文档与证据

- [使用指南](docs/USER_GUIDE.md)：界面操作、数据保留、迁移和故障诊断。
- [实际游戏目录说明](docs/GAME_DIRECTORY_GUIDE.md)：各文件夹功能与解包策略。
- [完整开发计划与实施记录](DEVELOPMENT_PLAN.md)：F01–F11、M0–M9、设计与完成状态。
- [源码结构索引](PROJECT_STRUCTURE.md)：模块职责与实际入口。
- [第三方来源及许可](docs/THIRD_PARTY_NOTICES.md)：固定上游提交、依赖和未确立的再分发条件。
- [验收摘要](docs/ACCEPTANCE.md)：测试、真实 Qt 流程、冻结包运行、制品摘要和已知验证边界。原始本机日志与解包样本不随源码上传。

当前已知边界：PC building 表的 5 个新增根字段没有可信语义名，保留其未知证据；已知后勤字段可解析。未覆盖未来游戏格式、未安装资源或全部游戏内运行效果。HTML 文件的静态完整性与脚本语法已检查；本轮浏览器工具拒绝 `file://` 访问，实际浏览器离线交互、窄屏与打印效果尚未自动验收。

## 源码运行与构建

需要 Python 3.12 x64、uv 和 PowerShell 7，精确依赖在 `uv.lock`：

```powershell
uv sync --locked
pwsh -File scripts/dev.ps1
pwsh -File scripts/verify.ps1
pwsh -File scripts/build.ps1
```

构建到 `dist/<版本>/ArknightsUnpacker`，已存在时拒绝覆盖。`build-info.json` 绑定源码摘要和依赖，`file-manifest.json`／`SHA256SUMS.txt` 记录程序包文件摘要。本次已验收的 v0.1.0 制品在 Git 初始化前构建，来源按工作区输入文件摘要记录；上传仓库不会追溯改写该制品的构建来源。

真实游戏 GUI 验证需显式设置本机路径，输出只写测试工作目录或指定证据目录：

```powershell
$env:ARKNIGHTS_GAME_ROOT = 'D:\你的游戏目录\Arknights Game'
$env:ARKNIGHTS_LIVE_EVIDENCE = Join-Path (Get-Location) 'artifacts/local-gui'
uv run --locked --no-sync python -X utf8 -m pytest tests/integration/test_live_workbench.py --basetemp .work/pytest-live-gui
```

已知许可证材料随包保留；Ark-FBS schema 和 FMOD DLL 的再分发授权尚未确立。私有仓库和私有 Release 不表示这些许可问题已解决，不能据此推定公开发布授权。详见 [第三方来源及许可](docs/THIRD_PARTY_NOTICES.md)。
