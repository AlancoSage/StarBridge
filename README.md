# VexBot

项目名称为 **VexBot**。原有配置、数据和游戏端接入方式保持兼容；安装脚本与技术标识的关系见 [项目名称与兼容说明](docs/project-name.md)。

当前正式版本为 **v0.6.41**，配套 Bukkit 游戏插件 **0.5.6**、Velocity 密码找回插件 **0.1.1** 与 Forge / NeoForge / Fabric 模组 **0.1.2**。在线列表图片采用左侧汇总、右侧服务器详情的玻璃板布局。支持[可选 MySQL 数据存储](docs/mysql.md)，提供连接检测、SQLite 双向迁移与便携备份，默认仍使用 SQLite。支持[原登录插件密码找回](docs/native-password-reset.md)：支持 AuthMe、LimboAuth 和 LibreLogin，已验证绑定的 OneBot 玩家可私聊重置自己的原生游戏密码，默认关闭。支持[指定指令图片回复](docs/image-replies.md)、QQ 官方机器人 AppID / AppSecret 鉴权与官方 WebSocket Gateway，按应用与场景隔离身份；原有 OneBot 接入继续可用。登录统一使用用户名和密码，首次通过独立流程创建服主账号。项目以 VexBot 名称分发，面板和官网使用黑白 V 机器人图标；新安装的管理面板默认端口为 **5800**，已有配置仍使用原来的端口。

面向 Minecraft 社区的 QQ 联动与管理工具。Bot 主程序使用 Python，Minecraft 插件与模组使用 Java，内置管理面板和独立社区官网使用 HTML / CSS / JavaScript，可选新版控制台使用 React / TypeScript；可选择 OneBot 11 或 [QQ 官方机器人](docs/qq-official.md) 接入。

源码公开于 [AlancoSage/StarBridge](https://github.com/AlancoSage/StarBridge)，采用 **AGPL-3.0-or-later**，完整条款见 [LICENSE](https://github.com/AlancoSage/StarBridge/blob/main/LICENSE)。开发与贡献请阅读 [CONTRIBUTING.md](https://github.com/AlancoSage/StarBridge/blob/main/CONTRIBUTING.md)，安全问题见 [SECURITY.md](https://github.com/AlancoSage/StarBridge/blob/main/SECURITY.md)，第三方依赖与许可证见 [THIRD_PARTY_NOTICES.md](https://github.com/AlancoSage/StarBridge/blob/main/THIRD_PARTY_NOTICES.md)。从开源后的源码构建部署 ZIP 时，`docs/` 目录也会附带这些文件。

在线使用说明、插件开发和 API 文档：[VexBot 文档中心](https://wiki.rainside.top/starbridge)。

首次部署从 [快速开始](docs/quick-start.md) 按 Bot → 游戏端 → QQ 接入 → 联动验收完成配置；官机按 [官方接入步骤](docs/qq-official.md) 配置，已接入的服务器可直接查阅 [功能文档目录](docs/index.md)。

项目采用独立的 VexBot 桥接协议，游戏服务器需安装配套插件或对应加载器的服务端模组。

指令、文字问答与消息规则分别使用对应的编辑流程，具体设计约定见 [交互设计说明](docs/interaction-design.md)。

## 已实现

- 强制绑定准入：在「成员 → 账号绑定」按服务器要求先绑定 QQ 才能进服。默认关闭，Paper / Spigot / Folia 需更新至游戏插件 **0.5.6**；按本服 UUID 检查，解绑后下次连接拒绝，首次绑定可由管理员核实后在玩家管理添加。见[账号绑定](docs/account-binding.md#强制绑定未绑定禁止进服)。

- [魔方财务商品与付款机器人](docs/mofang-billing.md)：Python / OneBot 11 私聊绑定服务商 API 账号，浏览两级分组与商品详情，确认下单并返回付款二维码或链接，默认关闭。

- Folia 游戏端：与 Paper / Spigot 共用 `VexBot-0.5.6.jar`，自动选择全局与玩家实体调度，支持聊天、档案、绑定、白名单、处罚回执和内置密码 / QQ 登录；接入方式与验证范围见 [Minecraft 兼容说明](docs/minecraft-compatibility.md#folia-接入)。
- Forge / NeoForge 游戏端：Forge 1.7.10、1.12.2、1.16.5、1.18.2、1.19.2、1.20.1，以及 NeoForge 1.20.4、1.20.6、1.21.1、1.21.4、1.21.8、1.21.11、26.1.2、26.2，接入聊天、玩家管理、白名单、绑定与密码 / QQ 登录，详见 [模组安装说明](docs/mod-game-ends.md)。NeoForge 仅提供正式构建。
- Fabric 游戏端：1.16.5、1.18.2、1.19.2、1.20.1、1.21.1、1.21.8、1.21.11、26.1、26.2 与 26.3，按游戏版本提供独立 JAR，VexBot 无需 Fabric API 或客户端模组，详见 [Fabric 安装说明](docs/fabric-game-ends.md)。

- 连接诊断：检查 QQ、游戏桥接、Java、邮件、官网与磁盘，按需检测 SMTP 认证和公开 API，详见 [诊断与模板](docs/diagnostics-and-templates.md)。
- Bot 更新与回退：通过 GitHub 公开 Release、上传部署 ZIP 或自定义 HTTPS 更新源获取版本，隔离验证、升级前备份、失败恢复和代码与数据回退；版本号变更时自动打包发布，详见 [更新说明](docs/updates.md)。
- 玩家工单与处罚申诉：官网本人提交与查看，管理回复、内部备注和状态处理；跨服封禁/踢出按 UUID 匹配并逐服确认，保护独立处罚，详见 [社区管理](docs/community-operations.md)。
- 配置导入与部署模板：单服、多服、QQ 登录、聊天联动四种模板，导入 TOML/JSON 前先预览，保留本机令牌。

- OneBot 11 **通用反向 WebSocket**，令牌验证、请求响应关联、断线错误处理。
- QQ 官方机器人：AppID / AppSecret 鉴权、WebSocket Gateway、群 @消息及 C2C 单聊事件、文字回复；应用与场景分别管理 OpenID 身份，支持范围见 [官机接入](docs/qq-official.md)。
- QQ 群 ↔ Minecraft 双向**文本**聊天；群图片转为 `[图片]` 提示。
- 游戏玩家加入 / 离开群通知。
- `/qbind` 游戏内生成 5 分钟验证码，在群内 `绑定 验证码`，绑定持久化到所选数据库（默认 SQLite，可选 MySQL）。
- 查询绑定、主动解绑、可选退群解绑、可选绑定后改群名片。
- 查询在线玩家与服务器连接状态。
- 配置式关键词回复。
- [指定指令图片回复](docs/image-replies.md)：按名单选择基础指令、预设指令和扩展回复，其他消息保持文字；「在线」「状态」采用按参考图重建的整幅插画背景、粗体白色大标题与轻模糊、高透光毛玻璃卡片，按参考比例排列在线人数、三项统计和服务器卡片。「在线」只展示服务器名、在线人数与玩家标签，「状态」另外展示容量、版本和离线提示。数据只来自当前群关联服务器，离线不显示旧玩家；本地确定性像素头像不是真实游戏皮肤，不请求第三方服务。插画与字体随包内置，无须新增配置；其他指令使用同风格文字卡片。支持中文排版、最多四页且每页不超过 2 MiB 的预览；预览可选已保存服务器，不保存配置、不发送 QQ；渲染失败按既有规则回退文字。
- JSON 规则插件：在面板「扩展」导入、启用／停用、重新加载和修改设置；扩展群命令、文本模板与进退服通知，无需代码执行或新增依赖。
- 指定 QQ 管理员调用预设控制台命令；插件再次检查完整命令白名单，并回传文本输出。
- 多台服务器，每个群关联一台服务器；一台服务器可以关联多个群。
- 管理面板显示真实连接状态、绑定记录和最近活动，并支持所有现有主程序设置的可视化编辑、保存与应用。
- 玩家管理：持久化玩家档案，按 UUID 汇总 IP、手动归属地、QQ 绑定与到访服务器；支持筛选分页、新增、详情修改、绑定、解绑和批量删除，以及踢出、封禁 / 解封、白名单操作与插件执行结果。
- 邮箱验证注册：QQ群 `/申请 玩家名 QQ号` → `/注册 验证码`；轻量 `/register` 网页与公开网站 API，独立后端密钥用于只读账号查询。注册、SMTP、邮件额度和允许来源均可在面板调整。
- 社区官网：可选择不接入、使用 VexBot 提供的官网或接入自己的官网。独立项目 [starbridge-website](starbridge-website/README.md) 拥有自己的启动、打包与部署流程，支持网页注册、密码登录、找回密码、所有服务器在线情况和本人档案。Bot「接入空间 → 网站绑定」可选择接入方式、自动授权来源、下载配置并调整公开内容；自建网站使用同一套 API/SDK，详见 [部署与信息接口文档](docs/website-deployment.md)。
- 事件去重、频率限制、有过期时间的任务队列、任务确认与重试。
- 多管理员：独立账号登录，按玩家管理、白名单审核、插件、定时任务、备份和统计等范围授权；停用账号或修改权限立即撤销旧会话。
- 故障监控：连接中断、服务器心跳失联和实际邮件发送失败记录，支持知晓标记与恢复状态；可选 QQ 群提醒，默认关闭。
- 官网自助中心：本人查看绑定、提交与追踪白名单申请、查看自己的封禁记录；支持游戏验证码绑定与主动解绑，同一套接口供自建网站接入。
- 备份保留策略：空间占用、按数量与天数清理、保护手动备份和恢复前备份；恢复前展示当前数据与备份差异，自动清理默认关闭。
- 插件版本管理：导入同 ID 新版本、查看更新说明、保留最近五个版本并回退；更新与回退后均保持停用，确认权限和设置后再启用。
- [插件市场](docs/plugin-market.md)：搜索、分类浏览和安装随软件提供的 6 款精选规则，查看详情、已安装和可更新状态，与现有插件设置、权限与回退记录共用。
- 运行统计：多服在线趋势、每日活跃玩家与进退服记录；低频采样和 SVG 图表，支持采集开关及保留天数。操作说明见 [团队与运行管理](docs/team-and-operations.md)。

## 运行环境

- Python **3.11+**。本机已使用 Python 3.14 验证。
- Minecraft **Java 版 Paper / Spigot / Folia** 使用同一个通用兼容 JAR；插件最低要求 **Java 8**，实际启动 Java 版本仍按服务端要求选择。Folia 1.21.8 使用 Java 21。详见 [Minecraft 版本兼容与 Java 选择](docs/minecraft-compatibility.md)。
- QQ 接入二选一：已登录 QQ、支持 OneBot 11 反向 WebSocket 的实现端（例如 NapCat），或具备群聊 / 单聊权限的 QQ 开放平台机器人应用。

已通过 Bukkit 1.4.7 / 1.7.9、Spigot 1.8.8 / 1.12.2 / 1.16.5 / 1.20.4 / 1.21.11 / 26.3 及 Paper 26.3 的 API 引用检查，并完成 Java 8 运行与隔离登录测试；这些检查不等同于所有历史版本的实服验证。

Folia **1.21.8 正式 build 6 / Java 21** 完成 **35 项实服检查**，使用 4 个区域线程、两名相隔 8192 格的离线协议玩家，验证密码与 QQ 登录、双区域档案、广播、白名单、处罚和正常停服。QQ 流程通过隔离 OneBot 接口完成，未验证正版档案签名链或真实 QQ 发送；具体版本与范围见 [兼容说明](docs/minecraft-compatibility.md#已完成哪些验证)。

另提供 [Forge / NeoForge 模组](docs/mod-game-ends.md) 与 [Fabric 模组](docs/fabric-game-ends.md)：对应 1.16.5 及以前的游戏端使用 Java 8，1.18.2–1.20.4 使用 Java 17，NeoForge 1.20.6 与各加载器的 1.21.x 使用 Java 21，Fabric 26.1–26.3 与 NeoForge 26.1.2 / 26.2 使用 Java 25。当前不支持基岩版原生服务端。游戏登录默认关闭；模组服和 Folia 使用内置或自动引擎，普通 Paper / Spigot 可选 AuthMe、nLogin、LoginSecurity 兼容，LibreLogin 需要普通 Paper；详见 [登录插件接入范围](docs/game-login.md#可选登录插件)。

## 1. 启动主程序

从 [GitHub Releases](https://github.com/AlancoSage/StarBridge/releases) 下载完整 Bot 部署 ZIP 后解压即可安装，不需要仓库访问授权或 GitHub 令牌。v0.6.41 的完整部署包为 `VexBot-Windows-0.6.41.zip`，独立官网包为 `VexBot-website.zip`；同版提供内容相同的 `StarBridge-Windows-0.6.41.zip`，供旧升级器识别。游戏 JAR 也可单独下载，部署 ZIP 内部文件名仍兼容已有更新器；历史版本保留原附件名称，例如 `StarBridge-website.zip`。

希望从源码部署或参与开发时，安装 Git 后执行：

```sh
git clone https://github.com/AlancoSage/StarBridge.git
cd StarBridge
```

源码部署使用下面相同的 Python 环境与启动命令，Windows 推荐双击 `VexBot.bat`，原来的 `星桥.bat` 仍可使用。配套游戏 JAR 从对应版本的 Release 下载，或按 [测试与构建](#测试与构建) 和游戏端文档自行编译；需要复现已发布版本时，检出该版本的 `v版本号` 标签。

按部署系统选择安装方式：

| 系统 | 安装入口 | 启动与停止 |
| --- | --- | --- |
| [Windows](docs/windows-installation.md) | 源码双击 `VexBot.bat`，部署 ZIP 双击 `星桥.bat`；也可手动安装 | BAT 菜单管理后台实例；手动前台运行按 Ctrl+C 停止 |
| [Linux](docs/linux-installation.md) | 安装 Python 3.11+，创建虚拟环境并安装锁定依赖 | 前台命令运行，或可选使用 systemd 后台托管 |

### Windows

Windows 用户完整解压部署 ZIP 后，双击 **星桥.bat** 自动准备 Python、安装依赖、生成配置并后台启动 Bot；这个文件保留旧名以兼容已有升级器，可以自行重命名为 **VexBot.bat**。源码检出提供 `VexBot.bat` 入口。管理面板就绪后自动打开，后续停止、重启仍在同一个脚本菜单内操作。已有配置与数据会保留，详见 [Windows 安装与运行](docs/windows-installation.md)。

Windows 也支持 [完整手动安装教程](docs/windows-installation.md#方式二-windows-手动安装)，包含 Python 安装、目录检查、依赖、配置、面板登录与故障处理。已经准备好 Python 3.11+ 时，在项目根目录执行 Windows PowerShell 命令：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
if (-not (Test-Path -LiteralPath config.toml)) {
    .\.venv\Scripts\python.exe -m starbridge init
}
.\.venv\Scripts\python.exe -m starbridge run
```

如果已有 `config.toml`，跳过 `init`；它不会覆盖已有配置。也可以双击 `星桥.bat`，使用相同的自动部署流程。

### Linux

在已安装 Python 3.11+ 与 venv 的环境中，进入项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
if [ ! -f config.toml ]; then
    .venv/bin/python -m starbridge init
fi
.venv/bin/python -m starbridge run
```

前台运行按 Ctrl+C 停止。系统依赖、远程面板访问、后台运行和开机启动见 [Linux 安装与运行](docs/linux-installation.md)。

### 登录面板并接入

启动后使用用户名和密码登录面板。首次没有服主账号时，点击独立的「创建服主账号」，使用 `config.toml` 的 `app.admin_token` 完成首次授权，设置服主用户名和密码，再回到普通登录；已有团队账号可直接使用。管理令牌保留用于首次授权和兼容管理 API，不是日常登录密码。进入面板后，在「机器人连接」和「服务器列表」中设置账号、管理员和群号即可。配置文件中的对应字段如下，便于了解两端设置的关系：

```toml
[onebot]
token = "保留 init 生成的随机令牌，并填入 QQ 实现端"
self_id = "你的机器人QQ号"
admins = ["你的管理员QQ号"]

[[servers]]
id = "survival"
name = "生存服"
token = "保留 init 生成的另一枚随机令牌，并填入游戏插件"
groups = ["你的QQ群号"]
```

这段仅说明需要修改的字段，完整格式以生成的文件为准。请不要把示例中文文字直接作为令牌。每类令牌必须不同。

打开 [管理面板](http://127.0.0.1:5800)，输入自己的用户名和密码。服主账号拥有完整管理权限，团队账号按授权范围访问；会话最多 8 小时，访问令牌仅保存在当前页面内存中，刷新页面后需重新登录。运行概览每 5 秒刷新，自动刷新不会覆盖正在编辑的内容。完整流程见 [面板登录](docs/panel-guide.md#登录面板)。

### 面板中调整设置

面板使用左侧分组导航，按总览、接入空间、自动化、成员、扩展、活动与设置划分。运行概览显示真实的机器人连接、服务器、绑定与活动记录。顶部「查找功能」和 Ctrl+K 可以搜索并跳转，导航与结果按管理员权限显示。

页面会随窗口宽度自动调整：桌面可收起侧栏，手机从顶部菜单打开导航，表单按单列显示。窄屏表格在表格区域内滚动；保存条兼容底部安全区域。背景采用纯白或纯黑，可切换明暗主题；主题与侧栏偏好只保存在当前浏览器。

| 页面 | 可调整内容 |
| --- | --- |
| 总览 | 机器人状态、在线服务器、绑定玩家、关联群与快捷入口 |
| 机器人连接 | 机器人 QQ、管理员 QQ、OneBot 令牌；查看并复制反向 WebSocket 地址 |
| 服务器列表 | 添加 / 移除服务器、ID、显示名称、关联群、连接令牌；下载插件配置 |
| 账号绑定 | 按玩家名、QQ、服务器搜索和筛选绑定记录 |
| 玩家管理 | 按玩家名 / QQ、UUID、IP、归属地、绑定状态、服务器和游戏状态筛选；分页管理档案，单个 / 批量解绑及删除 |
| 注册账号 | 注册开关、SMTP、验证码与邮件额度、网站来源和 API 密钥；搜索账号，下载文档与接入示例 |
| 消息与事件 | 群到游戏、游戏到群、进退服通知、退群解绑、绑定后改名片 |
| 插件管理 | 导入插件、启用 / 停用；在内置关键词回复插件中创建、编辑、搜索和移除回复 |
| 远程命令 | 按服务器通过命令列表配置和搜索控制台命令 |
| 运行日志 | [实时终端式日志](docs/runtime-logs.md)：等级、来源与内容筛选，暂停、跟随、展开、复制和下载 |
| 软件设置 | 监听地址、端口、数据库路径、兼容管理 API 令牌；重启主程序 |
| 扩展 | 在[插件市场](docs/plugin-market.md)搜索、分类浏览和安装精选规则；管理 JSON 插件、启用／停用、设置与版本回退 |
| 管理员 | 创建团队账号、设置权限、修改密码与停用账号 |
| 故障监控 | 连接与邮件异常、知晓标记、启动宽限时间和可选群提醒 |
| 运行统计 | 按服务器和时间查看在线趋势、每日活跃与进退服记录，调整采集和保留天数 |
| 备份与恢复 | 空间占用、手动备份、恢复差异预览、保留策略和清理 |

点击「保存全部设置」统一保存；有未保存更改时，也可使用底部保存条。切换页面会保留配置草稿，保存时会提交各页的更改。业务设置立即生效；监听地址、端口和数据库路径将在「软件设置 → 重启主程序」后生效。更换数据库不会搬迁原数据，原文件保留；修改端口后面板会给出新访问链接。启动新设置失败时，进程会恢复原运行地址和数据库，并显示错误。

保存会校验重复群号、服务器 ID、令牌及字段格式，原子替换配置文件，并将上一版存为 `config.toml.bak`。多个页面编辑产生冲突时会拒绝覆盖，可点击「重新载入」。数据库文件、连接凭据、令牌和备份需妥善保管，请勿公开。

表单中的必填、格式和数值范围错误会在字段旁显示中文提示，并定位首个错误字段；修正后提示自动清除。有错误时不会提交设置。

修改 OneBot 令牌或机器人账号会断开旧连接，需要同步到 QQ 实现端。修改服务器 ID / 令牌也需要同步到游戏插件；可在「服务器列表 → 安装插件」中填写游戏服可访问的主程序地址并下载完整 `config.yml`。外部 QQ 登录仍在 NapCat 等实现端完成。

通过 `星桥.bat` 启动的 Bot 在后台运行，可在同一脚本菜单中停止或重启；手动前台运行时按 Ctrl+C 停止。重复双击会复用此目录的后台进程。

### 新版 WebUI 控制台（可选）

源码中的 `webui-preview/` 提供基于 React 和 LINUX DO CDK 样式的新版控制台，默认打开 `http://127.0.0.1:5801/`，通过代理连接上面的 5800 后台。先启动 Bot，再在另一个终端执行：

```powershell
cd webui-preview
npm ci
npm run dev
```

新版控制台统一使用现有管理员用户名和密码登录。**玩家管理和「控制台设置 → 网站详细设置」读写真实后台**；运行总览、服务器、指令中心及其余预览选项仍使用示例数据。网站详细设置仅服主可访问，可填写网站与 Bot API 地址、调整公开权限，并在「VexBot 官网」模式编辑内容和外观。动画、背景和主题偏好保存在当前浏览器。

此控制台需要 Node.js 与单独的前端进程，独立于 Bot 正式部署包；下载部署 ZIP 后仍通过 5800 使用内置面板。玩家访问的社区官网默认本机预览为 8089。完整启动、权限、保存与故障处理见[新版控制台使用指南](docs/webui-preview.md)。

## 2. 连接 QQ

在 NapCat 或其他 OneBot 11 实现端添加 **WebSocket 客户端 / 反向 WebSocket**：

| 配置 | 值 |
| --- | --- |
| URL | `ws://127.0.0.1:5800/onebot/ws` |
| Token | `config.toml` 的 `onebot.token` |
| 连接模式 | Universal / 通用，API 和事件使用同一条连接 |
| 消息格式 | 推荐消息段数组；也支持 CQ 码字符串 |
| 断线重连 | 在实现端启用，建议间隔 3–5 秒 |

握手需要 `Authorization: Bearer <token>` 和 `X-Self-ID: <机器人QQ号>`。当前主程序接一只 QQ 机器人；多个群通过 `servers.groups` 配置。

先在配置的群发送 `帮助`。如果收到命令列表，QQ 链路已接通。

## 3. 安装 Minecraft 插件

Bot 0.6.41 配套通用插件：当前源码构建输出 `bridge/target/VexBot-0.5.6.jar`，并保留内容相同的 `bridge/target/StarBridge-0.5.6.jar` 兼容副本；部署 ZIP 内使用后者。也可在面板「成员 → 游戏登录」或「玩家管理」点击「下载 Paper / Spigot / Folia 插件」。

1. 将 JAR 放入游戏服务器的 `plugins` 文件夹。
2. 启动一次服务器，生成 `plugins/StarBridge/config.yml`。未配置有效令牌时插件会自动停用。
3. 设置插件配置：

```yaml
endpoint: "http://127.0.0.1:5800"
server-id: "survival"
token: "主程序中 survival 对应的 servers.token"
allowed-commands:
  - "list"
  - "tps"
```

4. 重启游戏服务器。管理面板应显示游戏服务器在线。

Folia 使用相同的 `plugins/` 安装和 `config.yml`，不用另选模组版本或手动开启调度开关。游戏登录选择「VexBot 内置」或「自动」，不要安装第三方登录插件。安装、升级或移除登录插件时完整停止并重启游戏服，不使用插件热卸载；详见 [Folia 接入](docs/minecraft-compatibility.md#folia-接入)。

完整的档案记录需要 0.3.0 游戏插件。升级时替换旧 JAR，保留原 `plugins/StarBridge/config.yml`，然后重启游戏服务器。0.2.0 仍可执行游戏管理操作，但不会上报 IP 和带 UUID 的入服事件；更早版本会提示升级。

在「成员 → 玩家管理」筛选玩家后点击「详情」。可修改归属地与备注，按服务器添加 QQ 绑定，或解除单个服务器的绑定。列表中的解绑会解除该玩家全部服务器的绑定；支持本页选择和批量处理。管理员手动绑定前需确认双方账号身份。新增档案需要真实 UUID，不会创建游戏存档或改变权限。

档案按 UUID 去重，一位玩家可关联多个服务器。档案、IP 和到访记录保存在所选数据库（默认 SQLite，可选 MySQL），服务器断线或移除后仍保留。IP 来自游戏服务器观察到的连接地址，经代理转发时可能是代理地址；归属地仅手动填写，不调用第三方查询。IP 变化会清空原归属地，避免展示旧地址的地区信息。

删除只清理本地档案、到访记录和全部绑定，同时撤销尚未执行的玩家管理任务，不删除 Minecraft 存档或封禁玩家。普通心跳不会立即重建已删除档案；玩家再次入服（0.3.0 的新入服事件）或管理员重新新增同一 UUID 时，档案可以重新记录。

在详情中按服务器点击「游戏管理」查看操作影响后提交。管理操作直接使用玩家 UUID，通过游戏端 API 执行，属于面板管理员权限；与群聊的预设命令白名单分别管理。只接受服务器上报的玩家，不通过用户名猜测账号身份。

插件单次上报最近 500 位已知玩家，在线玩家优先，超过时页面会提示；主程序保留此前已记录的档案。绑定记录中尚未上报的玩家和断开连接的服务器会显示「状态未知」，游戏管理按钮不可用。白名单是否限制加入仍由游戏服务器的白名单开关决定。

操作提交后显示「等待执行」，收到游戏插件回执才显示成功或失败。重复发送同一请求编号不会生成第二项任务；60 秒未确认会提示「结果未确认」，应核对游戏端后再操作。服务器连接或权限配置变更会撤销待执行任务。玩家管理记录和执行日志保存到所选数据库（默认 SQLite，可选 MySQL）。
5. 在游戏内输入 `/qbind`，将收到的验证码用于群命令 `绑定 A1B2C3D4`。

群号和 QQ 号使用字符串；游戏账号使用 UUID 标识。每台服务器内，一个 QQ 对应一个游戏 UUID，一个游戏 UUID 只能绑定一个 QQ。验证码只能用一次，再次获取会使旧码失效。

## 常用命令

| 位置 | 命令 | 功能 |
| --- | --- | --- |
| 游戏内 | `/qbind` | 获取验证码 |
| QQ 群 | `帮助` | 命令列表 |
| QQ 群 | `绑定 验证码` | 绑定游戏账号 |
| QQ 群 | `我的绑定` | 查询当前账号 |
| QQ 群 | `解绑` | 解除自己的绑定 |
| QQ 群 | `状态` / `在线` | 查询服务器、玩家 |
| QQ 群 | `官网` / `规则` | 示例关键词回复 |
| QQ 群 | `执行 在线检查` | 仅配置中的管理员可调用预设 `list` |
| QQ 群 | `执行 性能检查` | 仅配置中的管理员可调用预设 `tps` |

群主或群管理员不会自动获得控制台执行权限；以 `onebot.admins` 为准。首版要求参数使用普通空格分隔。

添加命令只需打开「远程命令」，在对应服务器下新增命令名与完整、固定的控制台命令。新版插件每次心跳都会从主程序同步白名单；请使用新版 JAR。旧版插件仍需手动修改 `allowed-commands` 或更新插件。插件通常能捕获 `sendMessage` 文本输出；部分插件异步输出或自行写日志的内容不保证回传。`tps` 是否存在由游戏服务端决定。

## 功能开关与多服

`[features]` 支持 `qq_to_mc`、`mc_to_qq`、`join_quit`、`unbind_on_leave`、`set_group_card`。改群名片需要 QQ 机器人具备对应权限。

在面板点击「添加服务器」可以连接更多服务器，每台服使用独立 `id`、令牌和群列表。服务器列表可以清空并保存，之后随时重新添加。每个群只能属于一台服务器，保存时会检查重复群号。绑定按服务器隔离；同一台服配置多个群且打开退群解绑时，退出其中任意一个关联群会解除该服务器绑定。移除服务器不会删除已有绑定，更改 ID 不会迁移旧绑定。修改群路由、令牌或预设命令时会撤销该服务器尚未执行的任务。

主程序默认只监听 `127.0.0.1`。跨机器部署时修改监听地址，并把 QQ 实现端和插件里的地址改成主程序地址；在公网使用 HTTPS / WSS 反向代理保护令牌。不要将令牌放入 URL 或公开仓库。

## 测试与构建

邮箱注册与网站接入参见 [账号 API 文档](docs/account-api.md)，前端示例见 [网站接入示例](examples/website-registration.js)。在「成员 → 注册账号」设置并保存后开放。默认关闭，不自动发邮件。社区账号 ID 与 Minecraft UUID 分开。

### 游戏登录

「成员 → 游戏登录」可按服务器启用，选择注册密码与绑定 QQ 私聊确认，调整时限和尝试次数。没有第三方登录插件时提供内置限制；普通 Paper / Spigot 可选 AuthMe、nLogin、LoginSecurity，LibreLogin 仅普通 Paper。Folia 仅使用内置或自动引擎，不接入第三方登录 API。使用 0.5.6 游戏插件，进服 `/login <密码>`（简写 `/l <密码>`）或 `/qqlogin`（简写 `/ql`）；旧账号通过 `/account-password` 验证注册邮箱设置密码。默认不开启，未登录限制操作、超时断开，重连需重新验证。已有原账号首次关联核实原身份，不覆盖旧密码；nLogin 每连接仍需原生认证，使用 /starbridge:login 或 /starbridge:ql 避免命令冲突，LibreLogin 没有可用 TOTP 实现时拒绝带密钥账号。需要可信关联的插件各自保存记录。同一游戏服只启用一个认证插件；混合加载器部署选自动。具体原生命令与验证范围见 [游戏登录文档](docs/game-login.md#可选登录插件)。

接入、已有账号迁移、命令日志保护与 API 详见 [游戏登录文档](docs/game-login.md)，面板可直接下载。插件运行时关闭 Spigot 原生玩家命令回显，避免 `/login` 密码写入服务器日志，卸载恢复原值；第三方日志插件需配置登录指令脱敏。

关键词回复位于「扩展 → 关键词回复 → 管理回复」，支持添加、搜索、修改与删除，保存立即生效；可单独停用。升级后原 `[replies]` 自动迁移一次，原配置保留为备份，之后不会覆盖插件设置。插件设置保存在 `data/plugin-state.json`。

使用现成规则可先到[插件市场](docs/plugin-market.md)浏览并安装，目录随软件版本更新，安装后在插件管理配置和启用。插件开发参见 [插件开发文档](docs/plugin-development.md)，完整示例见 [社群小助手](examples/community_helper.json)。导入示例后默认停用，在面板启用后可发送「服讯」「问候 内容」。插件入服通知默认关闭，可在插件设置中打开。插件 JSON 不运行脚本，不支持自动查询归属地。

面板使用本地 HTML / CSS / JavaScript 和随包提供的思源黑体，字体通过 Bot 同源加载，加载失败时回退系统字体；许可见 [思源黑体授权说明](docs/source-han-sans-license.md)。界面采用浅色卡片和圆角，切换页面时标题与首批卡片短暂淡入、轻微上移：每次最多 6 块，单块 220–280 毫秒，相邻卡片间隔不超过 40 毫秒。弹窗、保存栏和按钮保留短时反馈，玩家表格不播放整体入场动画。

顶部与登录页均提供「动画」开关，偏好仅保存在当前浏览器。未手动选择时跟随系统的减少动态效果设置；手动开启后优先使用浏览器内的选择，关闭后立即停止正在播放的 CSS 与 Web Animations 动画和过渡。没有背景模糊、持续动画、Canvas 或 WebGL。实时数据每 5 秒刷新一次，不会重播入场动画；仅绘制当前页面且数据变化时才重建列表，隐藏页面暂停轮询并取消正在播放的短动画，返回前台立即刷新。玩家表格不会因心跳时间变化而重建，保留选择状态与键盘焦点。

浏览器检查使用关闭 GPU / GPU 合成、CPU 降速 6 倍的 Edge 环境验证导航、表格刷新和后台暂停，结果保存在 `data/panel-performance.json`。这是软件渲染模拟检查，实际体验仍取决于机器性能、浏览器版本和数据量。

下拉菜单通过 CSS 美化浏览器的原生选择器，包含圆角、选中勾、轻量入场和可滚动选项，保持鼠标、键盘及原有筛选逻辑。不支持可定制选择器的浏览器保留系统下拉。[浏览器选择器样式说明](https://developer.chrome.com/blog/a-customizable-select)。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\bridge\build.ps1 -JavaHome 'C:\Program Files\Java\jdk-17'
```

Python 测试会在本地启动临时 HTTP / WebSocket 服务，模拟 OneBot 和游戏插件，验证完整收发与绑定流程，不连接真实 QQ，也不更改 `config.toml` 或生产数据库。

`requirements.lock.txt` 记录了本次验证的完整依赖版本，复现环境时可用它替代 `requirements.txt` 安装。

Windows 构建脚本下载并校验 Spigot 编译 API、Gson 和 ASM 构建依赖，不打包整个服务器。安装了 Maven 时也可以在 `bridge` 中运行 `mvn package`。各加载器的构建命令见 [Forge / NeoForge](docs/mod-game-ends.md#开发与构建) 与 [Fabric](docs/fabric-game-ends.md) 文档。

Linux 上运行 Bot 测试：

```sh
.venv/bin/python -m unittest discover -s tests -v
```

独立官网无需前端编译，在仓库根目录执行以下命令生成部署 ZIP；更多预览和部署方法见 [官网项目说明](starbridge-website/README.md)。

```sh
python starbridge-website/build.py --api-base https://bridge.example.com/api/v1
```

## 定时任务、插件权限与白名单申请

- 「扩展 → 定时任务插件 → 管理任务」支持间隔、指定星期与北京时间执行，动作包括群 / 游戏公告、预设命令和备份。插件可统一启停，并按动作、服务器和群授权；停用后自动与立即执行均暂停，重新启用不补发错过的任务。已有任务和执行记录保留。
- 「扩展 → 插件 → 权限」控制群消息、群命令、游戏通知与模板读取能力，限制服务器、群、使用者和 QQ 允许 / 拒绝名单，保存立即生效。
- 「成员 → 白名单申请」开放 `/白名单 玩家名 [理由]` 和 `/白名单状态`，支持资格限制、面板人工审核、离线待下发和游戏端确认。Paper / Spigot / Folia 使用 0.5.6 游戏插件；默认关闭申请。

这些数据随备份保存，恢复后定时任务自动停用。操作说明和 API 见 [定时任务与白名单申请](docs/automation-and-whitelist.md)。

## 备份与恢复

在「设置 → 备份与恢复」创建并下载 ZIP，或上传后预览恢复。包括账号和密码哈希、玩家档案、绑定、插件、关键词回复与业务设置；不包含游戏世界、AuthMe 数据和 JAR。恢复前自动保存当前数据，失败或中断支持回滚；保留本机面板地址、管理令牌及数据库位置，撤销旧验证码、登录会话和待执行命令。

备份包含连接密钥和 SMTP 授权码，请妥善保管。完整范围、迁移步骤、大小限制与管理 API 见 [备份与恢复文档](docs/backups.md)。

## 可靠性与首版边界

- 游戏插件每秒上报心跳，主程序 15 秒未收到心跳即视为桥接离线。“在线”表示插件链路可达，不包含 TPS 检测。
- 断线重连由 QQ 实现端负责。QQ 离线时游戏消息会记录发送失败，恢复后不补发历史聊天。
- 游戏侧未送达聊天只保留 30 秒，主程序待执行任务 60 秒后过期；队列有上限。
- 游戏任务使用 15 秒租约重试，插件在本次运行期间防止同一任务重复执行。插件崩溃重启后，极端情况下已执行但未确认的命令可能再次执行，因此仅配置可安全重试的命令。聊天与事件不承诺持久、恰好一次送达。
- 绑定记录保存在所选数据库（默认 SQLite，可选 MySQL）。启用游戏登录后，绑定 QQ 可确认本次连接；未启用时绑定可靠性依赖服务器自身账号认证。绑定不自动修改白名单或游戏权限。
- 暂未实现 AI 对话、自定义图片模板、PAPI、背包预览和跨平台账号。
- 已验证主程序模拟集成测试与 JAR 编译。游戏端的隔离实服流程、具体版本和验证范围见 [模组安装说明](docs/mod-game-ends.md)、[Fabric 游戏端](docs/fabric-game-ends.md) 与 [Paper / Spigot / Folia 兼容说明](docs/minecraft-compatibility.md)；真实 QQ、正版账号、其他构建号与整合包组合仍需在你的环境联调。

## 目录

```text
starbridge/                 Python 主程序与管理面板
bridge/src/main/            Java Minecraft 插件源码与配置
bridge/target/              编译出的插件 JAR
bridge-*/                   Forge / NeoForge / Fabric Java 游戏端与构建工具
starbridge-website/         独立 HTML / CSS / JavaScript 官网与 SDK
webui-preview/             React 新版控制台源码（独立启动，不含在 Bot 部署包中）
tests/                      HTTP / WebSocket / SQLite 测试
config.example.toml         示例配置
config.toml                 本机配置与随机令牌（不提交）
data/starbridge.db           运行时数据库（不提交）
VexBot.bat                 源码部署的 Windows 一键安装与运行入口
星桥.bat                    旧入口兼容；部署 ZIP 仍使用此文件名
```

通信标准：[OneBot 11](https://github.com/botuniverse/onebot-11)。
