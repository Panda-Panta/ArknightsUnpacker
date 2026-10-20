# 实际工程结构

更新：2026-10-20。唯一主计划为 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)，使用入口为 [README.md](README.md)。本文件描述已存在源码和依赖方向。

GitHub源码采用 `main`／`test`；Windows二进制放在对应版本 Release 附件，`data/`、`exports/`、`dist/` 和 `artifacts/` 不进入源码。可提交的验证摘要为 [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)，完整本机日志与样本仍留在忽略目录。

```text
ArknightsUnpacker/
├─ src/arknights_unpacker/
│  ├─ __main__.py, bootstrap.py    GUI／worker／验收入口分派
│  ├─ application.py              AppServices 用例集成，负责所选安装与输出保护
│  ├─ contracts.py                共享模型、模组PNG排版选项、取消标记与序列化契约
│  ├─ jobs.py                     隔离子进程、文件 IPC、取消与结果清单
│  ├─ paths.py                    程序旁 data／exports 默认路径、旧版迁移与原子写入
│  ├─ library/                    目录发现、分类、清单、生效候选、扫描、快照和 SQLite
│  ├─ extraction/                 Unity／PC 文本解码、IDX、核心表、图片、Spine、USM
│  ├─ gamedata/                   归一化、属性与描述、干员／模组资料、依赖与语义差异
│  ├─ reports/                    语义块、模组单张／分页PNG、独立HTML与批次清单
│  └─ ui/                         Qt 浅色六页工作台、启动恢复、更新批量导图、原图预览保存
├─ resources/                     文件夹规则、HTML 实际运行资产、ui/ 主题矢量图标
├─ data/                          默认本机配置、扫描／解析／变化历史及预览，不随源码或程序打包
├─ exports/                       启动自动创建的默认输出，不随源码或程序打包
├─ vendor/                        固定 CN FlatBuffers schemas、LZ4AK 和来源摘要
├─ tests/
│  ├─ app/                        worker IPC、写入边界、服务导出取消
│  ├─ library/                    来源选择、扫描差异与存储迁移
│  ├─ engine/                     数据解码、输入一致性与对象提取
│  ├─ gamedata/                   属性、描述、模块、快照语义回归
│  ├─ reports/                    同值导出、转义、分页、草稿与取消
│  ├─ gui/                        Qt 交互、身份保持、可读预览和队列
│  └─ integration/                显式启用的本机真实 Qt 全流程
├─ packaging/                     PyInstaller、来源／文件清单、许可证和预检入口
├─ scripts/                       dev.ps1、verify.ps1、build.ps1、verify-html.cjs
├─ docs/                          游戏目录、用户指南、第三方声明
├─ artifacts/                     里程碑样本、审查报告与 M9 验收，不随程序打包
├─ dist/<版本>/ArknightsUnpacker/ 最终目录式 Windows 便携包
├─ .work/                         独立任务／测试／构建中间文件，不随包分发
├─ .tools/, .venv/                仅本机开发依赖，不随包分发
├─ pyproject.toml, uv.lock         精确依赖和工程命令
└─ DEVELOPMENT_PLAN.md           完整主计划及最终事实记录
```

Qt 只调用 `AppServices`，不自行解释游戏表。`library` 提供资源观测和来源，`extraction` 产出带来源的 `TableSourceSet`，`gamedata` 构建资料与变化集，`reports` 共用语义块输出 PNG／HTML／TXT；JSON 保留完整资料和字段证据。Unity 解码运行在独立进程中，GUI 线程只处理界面与结果。

主要调用链：

```text
MainWindow → AppServices.restore → CatalogStore → 上次文件／资料及变化结果
MainWindow → AppServices.scan → library → CatalogStore
MainWindow → AppServices.load_data → WorkerRunner → extraction.tables
                                     ↓
                               gamedata.load_gamedata → compare_entities
MainWindow → AppServices.extract → WorkerRunner → extraction.engine
MainWindow → AppServices.export → build_operator/build_module → reports.export_report
```

`reports/html_render.py` 负责生成资料与选择结构，并读取 `resources/html/operator.html`、`report.css`、`report.js`，将模板、样式与脚本内联进导出 HTML。这三份文件是实际运行资产，模板版本为 2.0.0，修改会直接影响新报告。`reports/model.py` 的 entry_id／entry_title／stage 将模组简介与各级属性、天赋归为同一条目，PNG／TXT 继续共用资料。PNG 主题与排版实现位于 `reports/render.py`：`ReportOptions.module_image_layout` 为 `single`（默认）或 `paged`，只控制纯模组合集；`single` 按内容生成一张自适应高度图，超过 8,000 万像素时明确提示改用分页或减少选择。`ui/settings.py` 以 `report_module_image_layout` 保存“模组PNG排版”，模组页合并导出所选或本次新增；`modules.html` 仍同页容纳全部模组，干员独立报告分页不变。模组复选框由 `ui/entity_view.py` 内局部模型按稳定ID维护，排序／筛选保留勾选并提示隐藏数量；共享 `RecordsModel` 与干员列表选择不变。folder_rules.json 是目录用途分类的实际运行输入。

`scripts/verify-html.cjs` 是真实浏览器验收入口：`node scripts/verify-html.cjs --html <产物路径> --output <证据目录>`。开发环境需提供 Node.js 和 Playwright，可用 `NODE_PATH` 指向已有 Playwright 安装的 `node_modules`；这些工具不属于产品运行依赖。旧 HTML 为静态快照，需重新导出才使用新资产，不迁改已有报告。

构建只收集明确的源码依赖、资源、vendor、Qt 动态库与许可证；不收集游戏原文件、整个项目、测试夹具、应用历史数据库或用户配置。新增格式适配应修改对应 extraction 模块并更新真实样本证据；领域数值只在 gamedata 修改，界面与两个渲染器不得各自重算。
