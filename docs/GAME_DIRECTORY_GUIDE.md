# 《明日方舟》PC 游戏目录结构与解包说明

本说明来自本机只读盘点及固定版本上游文档。观察时间为 **2026-10-19 18:38:55—18:42:48（Asia/Shanghai）**，输入为：

```text
D:\Games\Hypergryph Launcher\games\Arknights Game
```

“用途”分为文件／清单直接证实，以及依据目录名、文件类型和组件名称推断。此处整理的是结构和说明，没有搬移、修改或删除游戏文件。完整开发安排见 [主计划](../DEVELOPMENT_PLAN.md)。

## 1. 总览

```text
Arknights Game/
├─ Arknights.exe                 游戏入口
├─ UnityPlayer.dll               Unity运行库
├─ GameAssembly.dll              IL2CPP游戏代码库
├─ Arknights_Data/
│  ├─ StreamingAssets/
│  │  └─ AB/Windows/             初始资源层
│  │     ├─ hot_update_list.json 初始资源清单
│  │     ├─ 074c396967a291d157f01a3e40c79119.idx
│  │     ├─ anon/*.bin           匿名资源包（抽样为UnityFS）
│  │     ├─ arts/、chararts/、charpack/、skinpack/
│  │     ├─ audio/、avg/、battle/、building/
│  │     ├─ scenes/、spritepack/、ui/、refs/…
│  │     └─ raw/video/*.usm      原始视频
│  ├─ PersistentData/
│  │  ├─ Bundles/               已下载的持久资源层
│  │  │  ├─ hot_update_list.json 当前资源清单
│  │  │  ├─ persistent_res_list.json 已下载资源记录
│  │  │  ├─ 708f7cd343e8fc62bee0502f85551996.idx
│  │  │  ├─ anon/*.bin
│  │  │  └─ arts/、audio/、avg/、battle/等
│  │  ├─ HGDownload/            下载组件状态
│  │  └─ .preset_thumbnail/     预设缩略图缓存占位
│  ├─ Plugins/x86_64/           原生插件及部分诊断数据
│  ├─ Resources/                Unity内置资源
│  ├─ il2cpp_data/              IL2CPP元数据／运行数据
│  └─ globalgamemanagers*、*.assets*、level*、配置文件
├─ AntiCheatExpert/             反作弊组件
├─ BLPlatform64/、CefView/      平台／网页运行组件
├─ plugins/、resources/、translations/
├─ sdkdata/、sdkplugins/、sdkresources/、U8Data/
├─ CrashSightLog/、HGEventLog_Encrypted/
├─ mmkv/、WebviewConfig/        本地状态／配置
├─ launcher_tmp/               启动器临时目录
├─ game_files等                启动器安装／校验清单类文件
└─ ArkUnpackerConfig.json、ArkUnpackerLogs.log  已存在的用户工具文件
```

Unity 数据区与平台／SDK区分开处理。目录浏览可展示全部文件，用途分类和默认资源扫描聚焦 Unity 资源；不将 SDK 状态或崩溃日志变化解释为游戏内容更新。

## 2. 本次物理文件规模

字节数按普通文件逻辑大小求和，不是磁盘实际占用。目录统计不跟随 reparse point／符号链接；本次未遇权限错误或此类链接。

| 范围 | 文件数 | 字节数 | 约 GiB | mtime落入固定24h窗口的文件数 |
| --- | ---: | ---: | ---: | ---: |
| 全游戏目录 | 16,878 | 27,949,656,000 | 26.03 | 20 |
| `Arknights_Data` | 14,576 | 26,753,594,409 | 24.92 | 11 |
| 初始资源层 | 13,328 | 24,242,983,799 | 22.58 | 0 |
| 持久资源层 | 820 | 2,333,644,085 | 2.17 | 0 |

另有 **7,306 个子目录**。全树 `.ab` 共 **13,942** 个：初始层 13,163，持久层 779。

| 扩展名 | 初始层数量 | 持久层数量 | 含义 |
| --- | ---: | ---: | --- |
| `.ab` | 13,163 | 779 | Unity AssetBundle，按对象类型导出 |
| `.bin` | 150 | 38 | 本次匿名包样本为UnityFS；不可一律当普通二进制表 |
| `.usm` | 13 | 0 | CRI视频资源，独立提取流程 |
| `.idx` | 1 | 1 | 资源索引，非UnityFS；schema仍待实测 |
| `.json` | 1 | 2 | 资源清单，作为结构化JSON读取 |

时间窗口固定为 `2026-10-18 18:38:55` 至 `2026-10-19 18:38:55 +08:00`。全树20项最近写入均属于日志／SDK状态等，两层资源内为0。

最新AB样本为：

```text
Arknights_Data/PersistentData/Bundles/arts/ui/homebanners/gacha/banner_hub.ab
size = 2936 bytes
mtime = 2026-10-16 16:20:32.187524 +08:00
```

这只能说明该观测窗口内没有资源mtime写入记录，不能证明服务器没有更新或当前数据中没有新干员。底包与热更清单的差异也不能冒充最近24小时的变化。

## 3. 游戏根目录功能

下表覆盖本机所有一级目录。组件作用主要按名称与实际文件类型推断，没有运行组件或读取账户／日志内容。

| 目录 | 文件数 | 字节数 | 功能与程序默认策略 |
| --- | ---: | ---: | --- |
| `Arknights_Data` | 14,576 | 26,753,594,409 | Unity资源、元数据和持久资源；核心入口 |
| `AntiCheatExpert` | 10 | 81,582,592 | 反作弊组件；仅用途说明 |
| `BLPlatform64` | 72 | 189,380,724 | 平台／网页运行组件；不按游戏AB解包 |
| `CefView` | 122 | 327,100,184 | CEF网页运行组件 |
| `CrashSightLog` | 1,848 | 2,109,701 | 崩溃遥测日志，默认排除资源更新统计 |
| `HGEventLog_Encrypted` | 1 | 192 | 加密事件日志，默认排除 |
| `launcher_tmp` | 0 | 0 | 当前为空的启动器临时目录 |
| `mmkv` | 8 | 32,768 | 键值存储，默认不读取内容 |
| `plugins` | 19 | 3,791,528 | Qt／应用插件 |
| `resources` | 5 | 15,687,080 | 网页／应用PAK、DAT等运行资源 |
| `sdkdata` | 2 | 640 | SDK本地状态 |
| `sdkplugins` | 2 | 5,614,568 | SDK插件及诊断数据库 |
| `sdkresources` | 9 | 32,833,484 | 当前为WOFF2字体等SDK资源 |
| `translations` | 82 | 26,289,707 | Qt／网页组件QM、PAK翻译资源 |
| `U8Data` | 3 | 1,680 | U8 SDK本地数据 |
| `WebviewConfig` | 6 | 7,280 | 网页组件本地配置 |

根目录另有113个文件，共511,629,463字节。主要分组：

- `Arknights.exe`、`UnityPlayer.dll`、`GameAssembly.dll`：入口、Unity引擎与IL2CPP代码。
- Qt、CEF、VC运行库、下载／事件SDK等DLL：运行依赖，不是可直接导出干员资料的数据表。
- `game_files`、`package_files`、`verify_files*`、`new_game_files`等：按名称归为启动器安装／校验清单候选，本轮没有验证每一种格式。
- `ArkUnpackerConfig.json`、`ArkUnpackerLogs.log`：用户历史工具文件，保持原样；新程序使用自己的数据目录。

### Arknights_Data 的非AB区域

| 路径／文件组 | 作用与处理 |
| --- | --- |
| `PersistentData/HGDownload` | 下载状态，当前一个2字节文件 |
| `PersistentData/.preset_thumbnail` | 当前一个零字节占位文件，不是资料图来源 |
| `Plugins/x86_64` | 原生插件；其中 `wesight/crashsight_data` 为诊断区域 |
| `Resources` | Unity内置资源，2文件／5,486,984字节；需要Unity资源读取方式 |
| `il2cpp_data/Metadata`、`il2cpp_data/Resources` | IL2CPP运行数据；不将其当现成角色JSON |
| `globalgamemanagers*`、`resources.assets*`、`sharedassets*.assets*` | Unity主资源／共享资源及旁置数据；按明确支持的序列化资源格式处理 |
| `level*` | 场景资源，不按文件名直接推导关卡语义 |
| `app.info`、`boot.config` | 客户端运行配置 |
| `RuntimeInitializeOnLoads.json`、`ScriptingAssemblies.json` | 初始化／程序集描述 |

## 4. 两层资源的全部一级子目录

“初始／持久”均为该子目录的递归统计；0表示目录存在但为空，“—”表示该层没有此目录。统计的是物理文件，并未去重为当前生效资源。

| 相对目录 | 初始文件数 | 持久文件数 | 用途与推荐处理 |
| --- | ---: | ---: | --- |
| 根文件 | 5 | 4 | 清单、IDX、公共shader／lipsync包，按格式分别解析 |
| `activity` | 7 | 1 | 活动通用／专题资源，按Unity对象类型导出 |
| `akvt` | 4 | 2 | 已见prfb_fx/spn/trp类专用预制体；具体玩法待对象确认 |
| `anon` | 150 | 38 | 匿名资源包（抽样为UnityFS），需要索引／容器名建立逻辑映射 |
| `arkvent` | 1 | 0 | 同名专题玩法资源，详细语义待对象确认 |
| `arts` | 1,380 | 84 | 头像、肖像、图标、地图美术、动态角色与UI图片 |
| `audio` | 759 | 518 | 音效、环境声和语音，按实际AudioClip编码导出 |
| `avg` | 2,494 | 12 | 剧情角色、背景、插图、特效和时间线 |
| `battle` | 696 | 36 | 战斗、敌人、技能等预制体／效果，追踪共享依赖 |
| `building` | 589 | 10 | 基建场景、家具、房间和UI；后勤技能语义不固定在此 |
| `chararts` | 472 | 0 | 按char_id命名的干员美术包，图像／纹理导出 |
| `charpack` | 465 | 0 | 干员资源编排／引用候选，实际对象待确认；不是数值表判据 |
| `config` | 2 | 1 | `common.ab`、`buff_template_holder.ab`等配置对象 |
| `crisisv2longterm` | 5 | 0 | 危机合约专题资源 |
| `crisisv2seasons` | 0 | 0 | 当前为空的危机合约赛季目录 |
| `cutin` | 2 | — | 角色切入演出，当前 `characters/cutin_char*.ab` |
| `graphics` | 2 | 1 | 图形配置，例如抗锯齿／反射 |
| `npcpack` | 6 | — | NPC资源包 |
| `pkgrps` | 43 | 11 | 共享／分组预制体包，如战斗敌人效果 |
| `prefabs` | 6 | — | 招募、商店、术语、文本等界面预制体 |
| `raw` | 13 | 0 | `video/*.usm`，专用CRI视频提取 |
| `refs` | 71 | 17 | 共享引用、美术和效果依赖，按依赖闭包解析 |
| `retro` | 48 | 0 | 往期／常驻专题资源，详细语义结合对象确认 |
| `scenes` | 4,975 | 45 | 关卡场景和照明，保留场景／依赖结构 |
| `shaders` | 19 | 12 | Shader资源，可导原始／结构；不承诺跨引擎复现 |
| `skinpack` | 426 | 4 | 角色外观资源，Spine／贴图／预制体组合待样本验证 |
| `spritepack` | 352 | 17 | Sprite／图集，导出时保留裁切、名称和透明度 |
| `ui` | 336 | 7 | 功能页面和活动UI，图片与结构对象分别导出 |

适合在软件中显示更细用途标签的实际子目录：

| 子目录 | 推荐标签 |
| --- | --- |
| `arts/charavatars`、`arts/charportraits` | 干员头像／肖像 |
| `arts/dynchars` | 动态角色美术，具体动画资源仍需对象识别 |
| `arts/skills`、`arts/items`、`arts/enemies` | 技能图标／道具美术／敌人美术 |
| `arts/maps`、`arts/shop`、`arts/ui` | 地图美术／商店／界面图像 |
| `avg/characters` | 剧情角色图像 |
| `avg/backgrounds`、`avg/bg` | 剧情背景 |
| `avg/images`、`avg/imgs` | 剧情插图 |
| `avg/effects`、`avg/timeline` | 剧情效果／时间线 |
| `audio/custom_se`、`audio/sound_beta_2` | 音效／环境声／多语言语音，按具体子路径细分 |
| `building/blueprint`、`building/diy` | 基建蓝图／装修家具相关表现资源 |
| `building/ui`、`building/vault` | 基建UI／场景资源，后者具体语义待对象确认 |
| `scenes/activities`、`scenes/arkvent`、`scenes/obt` | 各内容体系的场景集合 |
| `scenes/lightingsettings` | 场景照明配置 |
| `ui/character*`、`ui/uniequip`、`ui/uniequiparchive` | 干员／模组界面，不能直接视为角色／模组数值表 |

用途规则采用路径与对象证据分级；新增陌生目录保留“未知用途”，不根据相似名称强行套用。GUI中可搜索标签，类型识别由包头和实际对象类型完成。

## 5. 文件头与实际格式证据

以下样本均为 `UnityFS` 格式8，版本字符串 `2021.3.39f1`；路径相对 `Arknights_Data`：

```text
StreamingAssets/AB/Windows/chararts/char_002_amiya.ab
StreamingAssets/AB/Windows/charpack/char_002_amiya.ab
StreamingAssets/AB/Windows/config/common.ab
StreamingAssets/AB/Windows/audio/sound_beta_2/ambience.ab
PersistentData/Bundles/arts/charavatars/avatar_hub.ab
PersistentData/Bundles/avg/characters/avg_4231_clemnt_1.ab
StreamingAssets/AB/Windows/anon/025c139fef056c0eedc6b1759613b42f.bin
PersistentData/Bundles/anon/016941f6189dd86e1ee0425436ec4b5e.bin
```

共同头部：

```text
55 6E 69 74 79 46 53 00 00 00 00 08
UnityFS\0 ... 5.x.x\0 ... 2021.3.39f1\0
```

另外，初始层 `raw/video/01.usm` 的头部为 `CRID`，含 `@UTF`／`CRIUSF_DIR_STREAM`，应由USM流程处理。

`UnityPlayer.dll` 与 `Arknights.exe` 的版本资源都显示 `FileVersion=2021.3.39.0`、`ProductVersion=2021.3.39f1 (0)`。此检查仅读取版本信息，没有加载执行文件。

**证据边界：** 包头与版本一致只证明文件类型与声明版本；并未证明压缩块、对象TypeTree、外部依赖和全部素材能被当前引擎正确导出。

## 6. 清单与当前生效资源

### 6.1 三份清单

| 字段 | 初始 `hot_update_list.json` | 持久 `hot_update_list.json` |
| --- | --- | --- |
| 文件字节数 | 2,390,484 | 3,254,060 |
| `versionId` | `26-09-13-15-28-10-30688348` | `26-10-14-13-44-12-52990322` |
| `manifestVersion` | V078 | V078 |
| `manifestName` | `074c396967a291d157f01a3e40c79119.idx` | `708f7cd343e8fc62bee0502f85551996.idx` |
| `abInfos`数量 | 13,327 | 15,384 |
| `packInfos` | null | 73条 |
| mtime，+08:00 | 2026-10-09 15:29:25.587043 | 2026-10-16 16:19:32.793776 |

顶层字段为 `versionId/abInfos/manifestName/manifestVersion/packInfos`。资源项公共字段为 `name/hash/md5/totalSize/abSize`，还存在 `cid/pid/cat/meta/type` 等可选字段；其精确含义需按源码与样本确认，不能只按缩写猜测。

持久层的 `persistent_res_list.json` 指向同一当前IDX，包含818条资源。818条文件都存在、`abSize`均与落盘大小相符，`md5`字段与当前清单对应字段相同。这是**文件存在、大小和清单字段一致性检查**，不是对818个文件全部做了内容哈希验证。持久层820个文件中的另两项为两份JSON清单。

### 6.2 当前清单15,384项的磁盘覆盖

| 分类 | 数量 | 正确处理 |
| --- | ---: | --- |
| 持久层存在 | 818 | 候选当前文件，按支持的完整摘要进一步验证 |
| 底包存在且初始／当前清单md5字段相同 | 13,035 | 可复用底包候选；不是已全部逐文件实测hash |
| 底包存在但当前清单摘要已变，持久层缺失 | 62 | 陈旧候选，不当作当前版本静默使用 |
| 两层均未安装 | 1,469 | 本次均为可选语言语音，显示“未安装” |

未安装语音分布：`voice_cn=487`、`voice_custom=68`、`voice_en=457`、`voice_kr=457`。这是本机状态，程序应依据当次清单类型判断，不能把所有未来缺文件也视为可选语音。

62个陈旧候选中43个无`type`、19个为`dyn_illust`。抽查以下三个小文件，实际MD5仍匹配底包清单，而不匹配当前清单：

```text
arts/items/optionalvoucheritembgdecs/pic_hub.ab
arts/ui/homecheckinprogressgpicon/home_check_in_gp_icon_hub.ab
arts/ui/specialoperator/targettypebackicon/target_type_back_icon_hub.ab
```

首项的实测／底包MD5为 `3aedd056df56186352b26eb0a6cfc41d`，当前清单为 `233772c5b120bad9aceaec1b509e3e32`。这证明“热更中找不到就直接用旧底包”会把陈旧资源作为当前资源。

两份完整清单对比：13,289个同名、254个md5字段变化、2,095个新名称、38个旧名称不再列入。这只是**当前资源清单相对初始客户端清单**的累计差异，不是一次更新的内容，也不是新增干员数量。

### 6.3 摘要与大小字段不能混用

当前清单151个匿名`.bin`条目的`hash/md5`均为4字符短值，并非完整MD5。例如：

```text
name       = anon/016941f6189dd86e1ee0425436ec4b5e.bin
hash/md5   = e236
actual MD5 = d5bbf75361d0ec561578ba0e9e7db72b
abSize     = 115472
totalSize  = 92940
```

不能因短值与真实MD5不等就报损坏。只有已确认摘要类型才做该算法校验；短值原样保存并标注未完成内容验证。

当前IDX也表明落盘大小应核对`abSize`：

```text
totalSize = 3653686
abSize    = 35160284
actual    = 35160284
MD5       = 7a093e77aeca015ebf15a0d6a6346125  （实测吻合）
```

另两项实际内容MD5与清单一致的样本：

- `arts/charavatars/avatar_hub.ab`：`05a740cf6fc1568d9343e9896bfd154e`。
- `avg/characters/avg_4231_clemnt_1.ab`：`355ef5d530a67bf0e0e729852f8523ae`。

## 7. 干员／模组数据实际定位线索

两份IDX中都可直接检出以下逻辑路径字符串：

```text
dyn/gamedata/excel/character_table9fc534.bytes
dyn/gamedata/excel/skill_tableafb859.bytes
dyn/gamedata/excel/building_data73949e.bytes
dyn/gamedata/excel/uniequip_table8b1bb5.bytes
dyn/gamedata/excel/battle_equip_table91e6b6.bytes
dyn/gamedata/excel/char_meta_table87141b.bytes
dyn/gamedata/excel/range_table.bytes
```

初始IDX还检出150个不同的`anon/<32hex>.bin`路径，当前IDX为151个，与对应清单匿名包数一致。IDX本身不是UnityFS，前128字节为高熵二进制，后续存在结构化数据和这些字符串；尚未实测解码其字段关系。

上游固定schema中存在 [ResourceManifest定义](https://github.com/isHarryh/Ark-FBS-Py/blob/161d5e229916d7193364983396076556fbeaa549/CN/resource_manifest.py)，包含`Bundles`、`AssetToBundleList`、`BundleIndex`和`AllDependencies`。这提供了可验证假设：显式按该schema解码IDX，再核对表路径和真实包，而不是仅靠字符串猜表所在文件。

最短替代定位路线为：匿名UnityFS包 → 对象`m_Name`／`container`路径 → 识别表TextAsset → 显式选择schema解码。实施时选择真实验证通过的路线，保留来源映射。

当前未完成的验证包括：IDX schema／偏移、逻辑表到物理包映射、表字节解码、本机表版本一致性、全部天赋／潜能／模组分支与文本占位符。不能从`chararts/charpack`新文件名直接声称发现新干员，也不能从`ui/uniequip`直接得到模组数值。

## 8. 取证方法与来源

本次方法：PowerShell只读列目录；Python内存脚本用`os.scandir`、`stat(follow_symlinks=False)`逐层统计并拒绝reparse／符号链接；JSON解析三份资源清单；代表文件读取头部；少量指定样本计算MD5；两份IDX定向检索资源路径字符串。没有运行DLL/EXE，也没有读取账号数据或日志正文。

三份清单的SHA-256绑定本次观察：

| 相对路径（Arknights_Data下） | SHA-256 |
| --- | --- |
| `StreamingAssets/AB/Windows/hot_update_list.json` | `d7bd8e1e7037d9148e47921a8210ad763d05398dfbfd28837ee0078fcbe442ee` |
| `PersistentData/Bundles/hot_update_list.json` | `8192044ddda732c49227990f50947726a1c0c333659e32dad99328cc3eb1b3b4` |
| `PersistentData/Bundles/persistent_res_list.json` | `6c8f9e3305d30e684b67379aa0dd411813885d463a4139896f81eae86afc3a7a` |

可复核上游入口：

- [Ark-Unpacker固定README：PC两层资源与模式](https://github.com/isHarryh/Ark-Unpacker/blob/4a4b9efc6be4690b68b70b4a16578950baa066d3/README.md)。
- [资源查找指南目录](https://github.com/isHarryh/Ark-Unpacker/tree/4a4b9efc6be4690b68b70b4a16578950baa066d3/docs/zh)，旧指南与本机冲突时以本机证据为准。
- [AB解析](https://github.com/isHarryh/Ark-Unpacker/blob/4a4b9efc6be4690b68b70b4a16578950baa066d3/src/ResolveAB.py)、[文本解码](https://github.com/isHarryh/Ark-Unpacker/blob/4a4b9efc6be4690b68b70b4a16578950baa066d3/src/DecodeTextAsset.py)。

后续游戏更新可能改变本说明中的数量、清单名和路径。软件应自动识别并展示当前事实；这些具体值用于验证本轮调研，不作为硬编码运行规则。
