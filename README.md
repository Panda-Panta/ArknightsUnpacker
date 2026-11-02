# ArknightsUnpacker · 明日方舟资源与资料工作台

Windows 原生 GUI：浏览《明日方舟》PC 资源、扫描最近更新、解包选中文件，并生成干员／模组 PNG 长图与 PRTS 风格离线 HTML。

**版本 0.1.25（源码与本机已更新）。** AVG角色图片按配置引用补齐Alpha，新增表情差分制作：按组批量导出，或手选底图／表情、调整位置尺寸、预览后导出。文件／对象大小排序、时间对照、系统字体及当前页保持继续保留。使用方式见[用户指南](docs/USER_GUIDE.md)，验证见[验收摘要](docs/ACCEPTANCE.md)。当前公开发行下载仍为0.1.20。

## 直接运行

Release 入口：[v0.1.20](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.20) · [Windows x64 ZIP](https://github.com/Panda-Panta/ArknightsUnpacker/releases/download/v0.1.20/ArknightsUnpacker-0.1.20-win64.zip) · [ZIP SHA-256](https://github.com/Panda-Panta/ArknightsUnpacker/releases/download/v0.1.20/ArknightsUnpacker-0.1.20-win64.zip.sha256)。仓库与发行附件均已公开，无需登录即可下载。旧 [v0.1.15](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.15)／[v0.1.14](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.14)／[v0.1.13](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.13)／[v0.1.12](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.12)／[v0.1.11](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.11)／[v0.1.10](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.10)／[v0.1.9](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.9)／[v0.1.8](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.8)／[v0.1.7](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.7)／[v0.1.6](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.6)／[v0.1.4](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.4)／[v0.1.3](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.3)／[v0.1.2](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.2)／[v0.1.1](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.1)／[v0.1.0](https://github.com/Panda-Panta/ArknightsUnpacker/releases/tag/v0.1.0) 保留；本机 0.1.5 制品也保留。

解压完整 ZIP 后，双击其中的 `ArknightsUnpacker.exe`。无需安装 Python，保留同目录的 `_internal` 文件夹。本机已交付目录中的程序也可直接运行；源码仓库不保存 `dist/` 构建产物。

1. 选择游戏目录。默认输出为程序旁的 `exports/`，启动时自动创建；也可在设置中自定义输出目录。
2. 顶部默认“干员 / 模组优先”，先检查资料再扫描资源；主要查看新增资料时可选“仅检查干员 / 模组”。扫描后浏览目录、查看用途，按需启用“仅 .ab”。最近时间默认 24 小时，可修改。
3. 选中文件解包；双击包可浏览内部对象并选择提取。
4. 资料检查后，在“干员资料”／“模组更新”选择资料，预览或导出 PNG、HTML；“解析核心数据”也可单独刷新资料。模组页可勾选或全选当前筛选结果后合并导出，也可合并导出本次新增模组。JSON 和 TXT 同步保存，完整字段来源保留于 JSON。

再次启动直接读取保存结果，无需重新解析。设置、快照、变化记录与查看状态位于程序旁 `data/`；输出默认位于同级 `exports/`，源码运行时位于项目根。两者不随启动工作目录改变，显式 `--data-dir` 只改变数据目录。旧版 `Documents/ArknightsExports` 默认配置自动改用新默认，其他自定义输出路径保留，旧导出文件不搬动。升级时保留 `data/` 与已有输出。首次升级可非覆盖迁入旧 `%LOCALAPPDATA%\ArknightsUnpacker` 数据，原文件保留。游戏文件始终只读。

## 已实现

- 初始／热更双层资源发现、清单和 IDX 解析、来源选择及用途注释；可显示物理文件或当前资源候选。
- 最近写入时间筛选、扫描快照差异、可取消的严格摘要校验；启动恢复准确的扫描、资料与变化结果，再次扫描比较完整基线。
- 更新记录按文件用途下拉筛选、默认排除删除文件，可叠加搜索／AB 筛选／多选批量导图；图片保持原始像素，预览缩放不改变保存内容；单图平铺、多图分包目录。
- Unity 图片与显式 Alpha 配对、TextAsset 原始／解码输出、音频、完整 Spine 组、USM 流提取。USM 的可选 MKV 封装需要 PATH 中的 FFmpeg，程序包不附 FFmpeg。
- 满级、满潜、满信赖属性，标明基础／信赖／潜能／单个模组的数值；天赋潜能差额、专三技能、后勤、三级模组资料与语义变化比较。
- 新干员／新模组由完整前后数据快照确定，可一键导出新增资料。首次没有历史基线时显示“历史未知”，不会把所有角色认定为新增。
- 干员 PNG 保持独立报告分页；模组页合集 PNG 默认合为一张长图，在“模组PNG排版”可选分页。单图超过 8,000 万像素时明确提示改用分页或减少选择，不静默裁切或分张；预览缩放不改变输出像素。每名干员独立 HTML，模组合集保存为一个 `modules.html`。PNG／HTML 共用黑色顶栏、青色分区、资料卡片及亮色／暗色主题。HTML 全部技能和模组直接展示，提供右侧目录、就近锚点、搜索高亮／清除、折叠和完整打印；打印统一为适合纸张的亮色。CSS、脚本、图片均内嵌，无 JavaScript 时展示全部正文。
- 后台队列、独立解包进程、进度、取消、失败诊断与重试；导出不覆盖旧批次，禁止输出到游戏目录内。 成功记录保留最近20条；临时预览按实际窗口和生产任务生命周期回收，正式产物保留。

文件修改时间仅表示本机写入时间。快速扫描不会反复读取全部普通 AB 内容；无完整摘要时明确保留元数据证据等级。真实新增识别需要更新前的完整同服基线，不能由 mtime 或干员编号倒推。默认区服未知；同一安装的两次观测可带提示比较，跨来源需明确区服。

## 文档与证据

- [使用指南](docs/USER_GUIDE.md)：界面操作、数据保留、迁移和故障诊断。
- [实际游戏目录说明](docs/GAME_DIRECTORY_GUIDE.md)：各文件夹功能与解包策略。
- [完整开发计划与实施记录](DEVELOPMENT_PLAN.md)：F01–F11、M0–M9、设计与完成状态。
- [源码结构索引](PROJECT_STRUCTURE.md)：模块职责与实际入口。
- [第三方来源及许可](docs/THIRD_PARTY_NOTICES.md)：固定上游提交、依赖和未确立的再分发条件。
- [验收摘要](docs/ACCEPTANCE.md)：测试、真实 Qt 流程、冻结包运行、制品摘要和已知验证边界。原始本机日志与解包样本不随源码上传。

当前已知边界：PC building 表的 5 个新增根字段没有可信语义名，保留其未知证据；已知后勤字段可解析。未覆盖未来游戏格式、未安装资源或全部游戏内运行效果。HTML 浏览器交互、窄屏与打印的实际验证范围按版本记录，见验收摘要。HTML 模板为 2.3.0；旧 HTML 是静态快照，需要重新导出才能获得新布局和主题，程序不覆盖旧报告。

## 源码运行与构建

需要 Python 3.12 x64、uv 和 PowerShell 7，精确依赖在 `uv.lock`：

```powershell
uv sync --locked
pwsh -File scripts/dev.ps1
pwsh -File scripts/verify.ps1
pwsh -File scripts/build.ps1
```

构建到 `dist/<版本>/ArknightsUnpacker`，已存在时拒绝覆盖。`build-info.json` 绑定源码摘要、依赖和实际 Git 提交／工作区状态，`file-manifest.json`／`SHA256SUMS.txt` 记录程序文件摘要。旧 v0.1.0 构建时尚无 Git，保留当时的工作区来源记录，不追溯改写。

真实游戏 GUI 验证需显式设置本机路径，输出只写测试工作目录或指定证据目录：

```powershell
$env:ARKNIGHTS_GAME_ROOT = 'D:\你的游戏目录\Arknights Game'
$env:ARKNIGHTS_LIVE_EVIDENCE = Join-Path (Get-Location) 'artifacts/local-gui'
uv run --locked --no-sync python -X utf8 -m pytest tests/integration/test_live_workbench.py --basetemp .work/pytest-live-gui
```

已知许可证材料随包保留；Ark-FBS schema 和 FMOD DLL 的再分发授权尚未确立。私有仓库和私有 Release 不表示这些许可问题已解决，不能据此推定公开发布授权。详见 [第三方来源及许可](docs/THIRD_PARTY_NOTICES.md)。
