# 实际工程结构

更新：2026-10-20。唯一主计划为 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)，使用入口为 [README.md](README.md)。本文件描述已存在源码和依赖方向。

GitHub源码采用 `main`／`test`；Windows二进制放在对应版本 Release 附件，`data/`、`dist/` 和 `artifacts/` 不进入源码。可提交的验证摘要为 [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)，完整本机日志与样本仍留在忽略目录。

```text
ArknightsUnpacker/
├─ src/arknights_unpacker/
│  ├─ __main__.py, bootstrap.py    GUI／worker／验收入口分派
│  ├─ application.py              AppServices 用例集成，负责所选安装与输出保护
│  ├─ contracts.py                共享模型、取消标记、进度与序列化契约
│  ├─ jobs.py                     隔离子进程、文件 IPC、取消与结果清单
│  ├─ paths.py                    程序旁数据路径、旧版非破坏迁入和原子写入
│  ├─ library/                    目录发现、分类、清单、生效候选、扫描、快照和 SQLite
│  ├─ extraction/                 Unity／PC 文本解码、IDX、核心表、图片、Spine、USM
│  ├─ gamedata/                   归一化、属性与描述、干员／模组资料、依赖与语义差异
│  ├─ reports/                    语义块、PNG 排版、独立 HTML 与批次清单
│  └─ ui/                         Qt 浅色六页工作台、启动恢复、更新批量导图、原图预览保存
├─ resources/                     文件夹规则、HTML 模板资料、ui/ 主题矢量图标
├─ data/                          默认本机配置、扫描／解析／变化历史及预览，不随源码或程序打包
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
├─ scripts/                       dev.ps1、verify.ps1、build.ps1
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

运行时 HTML 样式／脚本的权威实现是 `reports/html_render.py`；`resources/html` 为随源码保留的模板资料，修改模板资料不会直接改变运行输出。PNG 主题实现位于 `reports/render.py`。folder_rules.json 是目录用途分类的实际运行输入。

构建只收集明确的源码依赖、资源、vendor、Qt 动态库与许可证；不收集游戏原文件、整个项目、测试夹具、应用历史数据库或用户配置。新增格式适配应修改对应 extraction 模块并更新真实样本证据；领域数值只在 gamedata 修改，界面与两个渲染器不得各自重算。
