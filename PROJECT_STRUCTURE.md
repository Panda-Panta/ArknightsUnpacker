# 实际工程结构

更新：2026-11-09。唯一主计划为 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)，使用入口为 [README.md](README.md)。本文件描述已存在源码和依赖方向。

关卡目录、地图预制体和出怪回放由独立的 [ArknightsMapViewer](https://github.com/Panda-Panta/ArknightsMapViewer) 维护。本仓库的玩法资料仍提供卫戍协议关卡摘要，资源浏览仍可预览和保存原始图像。

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
│  │  ├─ gameplay.py            生效资源索引读取、玩法识别和按需详情
│  │  └─ autochess.py           PC 卫戍协议的赛季结构及策略、盟约、调度解码
│  ├─ gamedata/                   归一化、属性与描述、干员／模组资料、依赖与语义差异
│  │  ├─ build.py                共用培养条件校验与来源信息，不依赖具体资料构建器
│  │  └─ module_comparison.py    同培养条件的模组各级属性、原效果与前一级对照
│  ├─ reports/                    语义块、模组单张／分页PNG、独立HTML与批次清单
│  │  ├─ style.py                共用亮色／暗色调色板、字体与资料分区顺序
│  │  ├─ fonts.py                字体只读加载、TTC字形提取、PNG与HTML离线内嵌
│  │  ├─ font_catalog.py         系统／用户Fonts名称、样式及集合字形索引，进程内缓存
│  │  └─ exporters.py            JSON／TXT／HTML／PNG 有序适配器，所选格式延迟加载
│  └─ ui/                         Qt 浅色工作台、启动恢复、更新批量导图、原图预览保存
│     ├─ pages.py                稳定ID页面清单、各页控制器与状态／刷新装配
│     ├─ gameplay_page.py        玩法子页、赛季选择和关卡详情
│     ├─ profile_navigation.py   干员右侧详情的当前章节目录与锚点跳转
│     ├─ resource_preview.py     对象窗口右侧图片／音视频／文本及二进制预览
│     ├─ preview_smoke.py        显式原生预览验收入口，走实际窗口／队列／worker
│     ├─ font_picker.py          设置和资料预览复用的系统字体／文件选择器
│     ├─ report_font_smoke.py     显式原生同窗换字形、正式导出与回收验收
│     └─ preview_cache.py        临时预览归属、窗口／生产任务释放、旧缓存回收
├─ resources/                     文件夹规则、HTML 实际运行资产、ui/ 主图标PNG／ICO及主题矢量图标
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

Qt 只调用 `AppServices`，不自行解释游戏表。`library` 提供资源观测和来源，`extraction` 产出带来源的 `TableSourceSet`，`gamedata` 构建资料与变化集，`reports` 共用语义块输出 PNG／HTML／TXT；JSON 保留完整当前资料和字段证据。`compose_report`及`export_report`不附带跨版本变化集，干员与模组详情统一只渲染当前资料，共享语义层不再生成任何跨版本更新段落；当前后勤阶段和模组未装备／各等级对照不受影响。历史差分仍用于新增／变化筛选。Unity 解码运行在独立进程中，GUI 线程只处理界面与结果。

玩法识别在文件扫描完成后读取本次生效 IDX，并将目录写入扫描快照的 `manifest_versions.gameplay`，恢复历史时直接用保存的目录。卫戍协议的关卡摘要复用表来源定位、版本校验和独立 worker，打开详情时才读取源包。没有适配器的玩法展示资源入口及状态。

`gamedata/operators.py` 从同快照 `uniequip_table.subProfDict` 补齐分支本地化名称，原分支ID保留；后勤遍历全部槽位与解锁阶段，`building_skills` 保留 `slot`、名称、设施、说明及条件。该列表不随面板培养条件裁剪，战斗技能和属性仍按原培养规则计算。共用报告层显示全部阶段及替换关系，JSON保留完整结构；无需迁移已保存游戏表。

`ui/explorer.py`和`ui/updates.py`共享`library.classifications.category_labels()`的用途标签，并补入扫描／资源目录观测到的类别。资源浏览选择具体类型后在当前来源全库匹配，关键词与AB条件继续叠加；暂时禁用目录导航／递归且保留原值，切回全部类型恢复原目录范围。`ExplorerPage`以`file_type`标签保存状态，旧状态缺字段默认全部类型；不会改变分类规则或实际解包器。

`library/preview_types.py`是独立媒体候选类型的单一映射，供源提取与浏览入口共享。`ui/resource_preview.py`只负责右侧呈现及播放器；`ObjectsDialog`负责对象选择、防抖、代次和预览租约，`MainWindow`合并同窗口的在途／最新请求并调用真实worker，避免旧结果覆盖新选择。普通预览独立使用auto解码，不改正式导出配置。QtMultimedia／Widgets及媒体插件随目录包收集，外部FFmpeg可执行程序仍为USM可选封装能力。`--smoke-test`配合隐藏的`--preview-source/--preview-kind`显式验收实际右侧面板、静音播放、暂停拖动与关闭释放；不在普通启动中执行。

0.1.18 的 `jobs.py` 通过 `__main__.py --worker-server` 为对象列表和临时资源预览按需复用单个隔离解码进程，保留逐任务请求、结果、取消和事件；每次重新读取源文件，不缓存 Unity 环境，闲置约60秒／退出回收。正式解包和核心表继续一次性进程。`main_window.py` 提供三种检查方式，默认资料检查结束后再提交全文件扫描，取消不启动后续阶段；核心表缺失保留失败任务并继续默认文件扫描。`application.load_data` 只刷新资料，保留既有文件扫描与 catalog，没有扫描时创建明确空 catalog。`library.scan` 用目录栈携带相对路径和 DirEntry 元数据；`resolver` 每层预计算相对前缀、同次 live 观测共享父目录元数据，snapshot 恢复不访问游戏文件。`ui.explorer` 按 catalog/root 缓存当前资源基础行，在更换数据或目录根时失效，搜索及用途筛选复用这些行。

`ui/profile_navigation.py`给干员右侧现有QTextBrowser添加紧凑目录，目录与profile_html共用同一最终semantic_blocks，按序号创建内部锚点；EntityView负责换角色／空状态时重置导航，PNG预览窗口不增加目录。干员与模组的only_changes均为隐藏兼容属性，不参与筛选或状态保存，旧状态恢复时忽略；后勤额外通用提示Block已移除，真实阶段条目及JSON原始字段保留。

0.1.21的天赋`term_definitions`由`render_description`按游戏术语标签收集；模组原天赋定义位于`comparison.original_term_definitions`，不混入模组业务变化。共用`Block.notes`将定义附在对应表格后，HTML／Qt以小字号段落显示，PNG以较小字体显示，不增加目录或章节；TXT保留完整文字，JSON保留结构。潜能描述证据位于各增量的metadata，官方注解可完整还原基础说明时去重，标准属性未说明的变化继续提示。`diff._without_text`将术语定义视为文字，保留文字勘误分类。

字体选项`ReportOptions.font_path`由设置页的`report_font_path`传入，旧配置默认空路径。`reports/fonts.py`按已选文件bytes统一构造PNG字体与HTML的内嵌font-face，PNG分页和绘制共用同一布局／字形；批次目录也内嵌字体。JSON／TXT不加载字体，未选时保持既有自动字体。显式`--smoke-test --profile-export-test`在隔离状态恢复当前干员后点击真实导出按钮、等待既有队列，并记录产物；普通启动不执行。

0.1.22通过fonttools4.68.0读取Fonts目录的名称表和TTC索引，`font_index`与路径一起保存在设置／ReportOptions／任务请求中，旧值默认0。`fonts.py`将TTC的所选face提取为独立字体bytes，PNG与HTML使用同一face。资料预览通过`ReportArtifactsDialog.font_preview_requested`、主窗独立报告generation/pending状态和既有queue／PreviewLease异步更新；旧代结果不覆盖新选择、关闭只取消本窗口任务，成功选项传给正式导出。默认按钮不会响应字体文本控件的Return／Enter。显式`--smoke-test --profile-font-preview-test`验证实际系统字体选择、同窗切换、正式四格式和关闭回收；普通启动不执行。

底部「任务记录…」在独立窗口呈现任务表。`Job.show_in_tasks` 为可选持久字段，内部资料、启动恢复和对象列表读取标为 False，`JobQueue.visible_jobs` 为任务表提供可见记录。旧记录按稳定内部标题兼容，其他默认可见。可见与内部成功记录分别保留最近 20 条。表格动作按稳定 job_id 查回原任务。后台串行调度、状态栏和错误信号继续处理内部读取。

0.1.24的`RecordsModel`列定义可追加原始排序getter，大小／时间保留字节／纳秒精度，未知值双向置后，`replace`沿用当前有效排序；持久索引在排序后按原行身份映射。`FileRecord.created_ns`为可空文件系统birth time，扫描及摘要后的最终stat记录该值，旧JSON默认未知、不迁移数据库。`ExplorerView`按快照绝对物理路径关联生效资源的修改／创建／首次观测值，离线不补读源文件；更新表同样按原值排序。`extraction.engine.list_bundle_objects`从Unity对象`byte_size`元数据返回可空`size`，独立媒体为源文件字节；`ObjectsDialog`的大小列可排序，自动预览选中以排序后的记录为准。显式`--smoke-test --resource-sort-test --game-root <隔离夹具>`通过真实扫描和表头点击验收文件排序／时间；既有资源预览smoke同时核对worker返回的对象大小、排序与预览身份，普通启动不执行。

主要调用链：

0.1.25新增`extraction/character_config.py`归一两种AVG角色配置，`images.py`将配置Alpha显式引用接入普通Sprite／Texture并保持裁片；`extraction/characters.py`提供JSON目录、逻辑画布恢复及自动／手动共用合成。`ExtractionRequest.character_options`为可空兼容字段，`kinds=['expression']`经现有extract worker导出；内部`character_catalog`读取复用隔离worker，不进入可见任务。`ui/character_workbench.py`只管理组／底图／表情、位置尺寸、成功预览与lease，不解释Unity表。Explorer按钮／菜单→MainWindow→AppServices→worker接通；预览最新请求保留显式类型及合成参数，关闭仅取消本窗口所属读取／预览，正式批量不受影响。`--smoke-test --character-source`显式验证真实配置→手选预览→正式导出／批量与回收，普通启动不执行。

```text
MainWindow → AppServices.restore → CatalogStore → 上次文件／资料及变化结果
MainWindow → AppServices.scan → library → CatalogStore
MainWindow → AppServices.load_data → WorkerRunner → extraction.tables
                                     ↓
                               gamedata.load_gamedata → compare_entities
MainWindow → AppServices.extract → WorkerRunner → extraction.engine
MainWindow → AppServices.export → build_operator/build_module → reports.export_report
```

`reports/html_render.py` 负责生成资料、连续条目与锚点目录结构，并读取 `resources/html/operator.html`、`report.css`、`report.js`，将模板、样式与脚本内联进导出 HTML。这三份文件是实际运行资产，模板版本为 2.3.0，修改会直接影响新报告。`reports/style.py` 读取 `resources/report_styles.json`，提供两种格式共用的调色板、字体层级及 `ordered_groups(document)` 资料分区顺序。HTML 通过 `theme_css(theme)` 内联主题变量，PNG 使用 `theme_colors(theme)` 和 `typography()`；批次目录同样接收 `ReportOptions.theme`。JSON 是正式构建要求的运行资产，纯 JSON／TXT 导出仍不依赖这些样式。

`reports/model.py` 的 entry_id／entry_title 将模组简介与分类横表归为同一条目；Block.kind 标明模组简介、属性、效果、潜能、召唤物与条件，stage 保留兼容字段、新横表统一为空。列为项目／未装备／1级／2级／3级，属性直接读取领域比较结果，文本引用首次相同原文，JSON保留原数据。PNG／HTML／TXT与GUI预览共用这些语义块。PNG 排版实现位于 `reports/render.py`：`ReportOptions.module_image_layout` 为 `single`（默认）或 `paged`，只控制纯模组合集；`single` 按内容生成一张自适应高度图，超过 8,000 万像素时明确提示改用分页或减少选择。`ui/settings.py` 以 `report_module_image_layout` 保存“模组PNG排版”，以 `report_theme` 保存“资料导出主题（PNG / HTML）”，原有 dark/light 值兼容保留。`modules.html` 仍同页容纳全部模组，干员独立报告分页不变。模组复选框由 `ui/entity_view.py` 内局部模型按稳定ID维护，排序／筛选保留勾选并提示隐藏数量；共享 `RecordsModel` 与干员列表选择不变。folder_rules.json 是目录用途分类的实际运行输入。

`scripts/verify-html.cjs` 是真实浏览器验收入口：`node scripts/verify-html.cjs --html <产物路径> --output <证据目录>`。开发环境需提供 Node.js 和 Playwright，可用 `NODE_PATH` 指向已有 Playwright 安装的 `node_modules`；这些工具不属于产品运行依赖。旧 HTML 为静态快照，需重新导出才使用新资产，不迁改已有报告。

主图标权威图稿为`resources/ui/app-icon.png`，`app-icon.ico`保存Windows多尺寸透明版本；bootstrap通过resource_root设置Qt默认应用图标，主窗口及其对话框继承，PyInstaller的EXE.icon嵌入ICO。原生smoke另外记录实际应用／窗口图标及缩略图，构建清单要求两份资产。图稿无需游戏扫描／解码。

构建只收集明确的源码依赖、资源、vendor、Qt 动态库与许可证；不收集游戏原文件、整个项目、测试夹具、应用历史数据库或用户配置。新增格式适配应修改对应 extraction 模块并更新真实样本证据；领域数值只在 gamedata 修改，界面与两个渲染器不得各自重算。

0.1.19更新记录页的`UpdatesView`按实际双击行校验存在状态、资源类型和根目录后发出`objects_requested`，`UpdatesPage`连接既有`MainWindow.objects`；对象窗口、右侧预览及解码流程共用。显式预览验收可加`--preview-updates`从更新记录表真实鼠标双击开始，常规启动不执行。

页面增删入口为 `ui/pages.py` 的 `PAGE_DEFINITIONS`：控制器负责创建视图、信号连接、状态保存／恢复和刷新。新增页面使用唯一且稳定的 `page_id`；移除资源浏览、更新记录、干员或模组的清单项后，其余功能仍可使用。四个可选页缺失具体模块时跳过该页，其内部依赖错误正常报出。`jobs` 和 `settings` 是必要基础设施。主窗口通过 `PageComposition` 调度，任务标签按实际控件定位，不依赖页签下标；新保存状态按 ID，旧数字状态按原六页顺序兼容。PyInstaller 显式收集 UI 子模块以支持延迟导入。

报告公共入口仍为 `compose_report`／`export_report`。`reports/export.py` 负责任务目录、来源路径保护、取消与失败清单；`reports/exporters.py` 的有序格式表负责对应输出，HTML／PNG 渲染器在被选择时才导入。纯资料组合和 JSON／TXT 不要求 HTML 资产。`gamedata/module_comparison.py` 用已有 `panel()` 算法对照同一培养条件，保留未解析值，不混入召唤物或条件战斗效果；派生 `comparison` 不参与业务差分。`reports/model.py` 将对照转为统一语义块，供 GUI 预览、PNG、HTML、TXT 共用；JSON 保留原字段及新对照。旧资料缺少新字段时仍可展示。

显式 `--headless-verify` 在一次真实扫描／解析后分别以 dark/light 导出同一组选定干员和模组，`verification.json` 的 `report_runs` 记录两种结果；该入口不代表浏览器检查。浏览器脚本另从实际导出 HTML 检查主题颜色、离线交互、窄屏和打印状态；打印媒体使用共享亮色变量，结束后恢复屏幕主题。`--smoke-test` 原生窗口收据包含当前主题与可选值，用于冻结／安装设置保留验证。

HTML 所有技能与模组连续显示，移除技能／模组页签和等级控件；每个模组只用一个 details 折叠，分类为带行表头的横表。原生锚点用于跳转，JS仅处理搜索、清除、折叠、打印与锚点展开。共享正文行高为1.4，PNG按实测首列宽度为四状态列留等宽空间，窄图保留带标签回退。旧静态HTML不受影响，需重新导出。

`ui/jobs.py` 在启动及每个任务终结后，将成功历史限制为最近20条；`ui/job_history.py` 仅移除对应任务JSON／事件，保留非成功与恢复祖先，不删除正式产物。`settled(job)` 在工作线程释放后通知主窗口结束预览生产占用。`ui/preview_cache.py` 为data/preview与previews分配带标记和QLockFile的独占目录，lease须同时结束生产并释放窗口后才删除；外部HTML延至程序退出。主窗口在队列修剪前扫描旧缓存归属，未知／链接／其他在用实例保留；对话框只释放显式绑定的lease，正式任务重复预览仍可打开。AppServices.extract/export的remember_output默认为True，临时预览传False，不改变正式输出设置。

0.1.10界面更新：main_window.py管理可折叠的扫描选项／历史对照、当前页说明及可省略路径；settings.py自行拥有可滚动表单与固定保存栏，SettingsPage直接装配该视图。entity_view.py、explorer.py、updates.py各自拥有表格／空状态切换和就近清除筛选，不改变服务层数据或稳定ID。jobs.py仅改善空队列及进度呈现，未更改调度器。HTML模板2.3.0添加正文跳转、滚动目录位置及局部横表键盘访问，仍使用style.py和report_styles.json的2.2.0共享调色板；PNG排版器未改，PNG／HTML／TXT的正文由model.py统一精简为玩家资料，exporters.py的JSON仍直接保存完整ReportDocument，内部导航键不删除。新增界面回归在tests/gui/test_*_usability.py与tests/reports/test_html_usability.py；截图／真实快照验收在.work/ui-refresh-20261023/，不随包发布。
