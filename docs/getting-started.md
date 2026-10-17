# 部署与快速入门

第一次部署请使用 [完整快速开始](quick-start.md)。该教程按 Bot、Minecraft、OneBot、联动验收说明每一步的设置和成功标志，适用于 Bot 0.6.25 / Bukkit 游戏插件 0.5.4。

## 选择安装方式

| 你的环境 | 阅读入口 |
| --- | --- |
| Windows，双击自动部署 | [Windows 一键安装](windows-installation.md) |
| Windows，自己安装 Python | [Windows 手动安装](windows-installation.md#方式二-windows-手动安装) |
| Linux，终端或 systemd | [Linux 安装](linux-installation.md) |

## 接好三个组件

先启动 Bot 并登录面板，再配置服务器和关联群、安装游戏端，最后连接 OneBot 11。游戏服和 QQ 实现端分别向 Bot 发起连接；不要把游戏端 HTTP 地址与 QQ 反向 WebSocket 地址混用。

- 游戏端：[Paper / Spigot / Folia](minecraft-compatibility.md)、[Forge / NeoForge](mod-game-ends.md)、[Fabric](fabric-game-ends.md)。
- QQ 端：[OneBot 11 连接及参数](onebot-connection.md)。
- 验收：[快速开始](quick-start.md)、[消息同步](message-sync.md)、[QQ群命令](group-commands.md)。

## 接入成功以后

按需继续配置 [玩家绑定](account-binding.md)、[游戏登录](game-login.md)、[社区官网](website-deployment.md) 与 [插件](plugin-development.md)。这些功能不是基本文本联动的必装依赖。

页面或连接异常时，先查看 [面板使用指南](panel-guide.md) 和 [常见问题](troubleshooting.md)。完整篇章入口见 [文档目录](index.md)。
