# VexBot 文档

VexBot 把 QQ 群、Minecraft 服务器和社区账号连接起来。你可以在管理面板配置消息联动、玩家档案、账号注册与登录、插件、官网和备份。

当前说明对应 **Bot 0.6.41 / Bukkit 游戏插件 0.5.6 / 游戏端模组 0.1.2**。支持可选的 [魔方财务商品与付款机器人](mofang-billing.md)。控制台使用用户名和密码登录，首次通过独立流程创建服主账号。项目以 VexBot 名称分发，面板和官网采用黑白 V 机器人图标；新安装的默认面板端口为 5800。Forge、NeoForge、Fabric 按游戏版本使用各自的模组。首次部署请从 [快速开始](quick-start.md) 阅读；已经接好服务器，可以直接查看下面的功能指南。

项目原有配置和接入标识保持兼容，详细关系见 [项目名称与兼容说明](project-name.md)。

源码另提供默认 5801 的[新版 WebUI 控制台](webui-preview.md)，需要单独启动。玩家管理和网站详细设置已连接真实后台，其余页面和预览选项仍使用示例数据；玩家使用的[社区官网](website-deployment.md)是独立项目，默认本机预览端口为 8089。

## 第一次部署

| 顺序 | 操作 | 完成后应看到什么 |
| --- | --- | --- |
| 1 | [安装 Bot：Windows](windows-installation.md) 或 [Linux](linux-installation.md) | 浏览器能登录管理面板 |
| 2 | 安装 [Paper / Spigot / Folia 插件](minecraft-compatibility.md)、[Forge / NeoForge 模组](mod-game-ends.md) 或 [Fabric 模组](fabric-game-ends.md) | 面板中对应服务器收到心跳 |
| 3 | [连接 OneBot 11](onebot-connection.md) 或 [QQ 官机](qq-official.md)，并填写关联群 | 概览显示 QQ 已连接 |
| 4 | [测试消息同步](message-sync.md) 和 [群命令](group-commands.md) | 群聊和游戏能够互通，查询返回当前服务器信息 |

Bot、QQ 实现端和游戏服务端可以运行在同一台机器，也可以分开部署。连接地址需要由发起连接的那台机器访问；`127.0.0.1` 始终指那台机器自身。[快速开始](quick-start.md) 会说明三个组件分别配置什么。

## 按功能阅读

| 文档分区 | 常用入口 |
| --- | --- |
| 入门与部署 | [快速开始](quick-start.md)、[OneBot 连接](onebot-connection.md)、[官机接入](qq-official.md)、[内置面板](panel-guide.md)、[新版 WebUI 控制台](webui-preview.md)、[版本与 Java 选择](minecraft-compatibility.md) |
| 玩家与账号 | [QQ 绑定](account-binding.md)、[玩家管理](player-management.md)、[消息同步](message-sync.md)、[群命令](group-commands.md)、[游戏登录](game-login.md)、[原插件密码找回](native-password-reset.md)、[注册 API](account-api.md) |
| 插件与自动化 | [插件市场](plugin-market.md)、[插件开发与最小示例](plugin-development.md)、[定时任务及白名单申请](automation-and-whitelist.md)、[指定指令图片回复](image-replies.md) |
| 官网与 API | [独立官网部署及信息接口](website-deployment.md)、[注册与密码接口](account-api.md) |
| 服务商商品与支付 | [魔方财务账号绑定、商品与付款](mofang-billing.md) |
| 团队与权限 | [管理员授权及运行管理](team-and-operations.md)、[工单与跨服处罚](community-operations.md) |
| 运维与备份 | [实时运行日志](runtime-logs.md)、[连接诊断和配置模板](diagnostics-and-templates.md)、[备份恢复](backups.md)、[更新回退](updates.md)、[常见问题](troubleshooting.md) |

在线文档中心按分区提供教程：[打开文档中心](https://wiki.rainside.top/starbridge/)。

## 哪些组件需要安装

| 组件 | 用途 | 是否必须 |
| --- | --- | --- |
| VexBot | 连接 QQ 与游戏，保存账号和管理设置，提供面板及 API | 必须 |
| OneBot 11 实现端 | 登录 QQ，将 QQ 事件发送给 Bot | OneBot 模式需要；官机通过开放平台应用接入 |
| VexBot 游戏插件或模组 | 上报游戏状态，转发聊天，执行授权操作 | 使用 Minecraft 联动时必须 |
| 社区官网 | 提供网页注册、服务器状态和本人信息 | 可选，可使用 VexBot 官网或自己的网页 |
| 第三方登录插件 | 接管 Minecraft 原生认证 | 可选，按 [适配范围](game-login.md#可选登录插件) 选择 |

Bot 使用 Python 3.11+。Bukkit 通用插件最低 Java 8，实际 Java 版本仍按游戏核心要求选择；模组按对应版本下载。Folia 使用内置或自动登录引擎。具体核心、加载器和实服验证范围以 [兼容说明](minecraft-compatibility.md) 为准。

## 查配置还是查接口

服主按操作教程在面板保存设置；开发者先确认 API 的凭据类型和权限，再使用接口参考中的示例。网站 API 密钥、玩家短期令牌、服主管理令牌与游戏服务器令牌用途不同，不能相互替代。

部署包和版本说明位于 [公开 Release](https://github.com/AlancoSage/StarBridge/releases)，无需仓库访问授权。完整源码位于 [AlancoSage/StarBridge](https://github.com/AlancoSage/StarBridge)，采用 [AGPL-3.0-or-later](https://github.com/AlancoSage/StarBridge/blob/main/LICENSE)；开发与贡献见 [贡献指南](https://github.com/AlancoSage/StarBridge/blob/main/CONTRIBUTING.md)。原有文档地址继续可用，长篇接口和兼容资料也继续保留。
