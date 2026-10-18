# 项目名称与兼容说明

项目正式名称为 **VexBot**。从 **v0.6.28** 起，管理面板、官网、机器人回复、安装器窗口和新发布附件统一使用 VexBot，图标为黑白 V 形机器人。

本次配套 Bukkit 插件 **0.5.5**、Velocity 插件 **0.1.1**、Forge / NeoForge / Fabric 模组 **0.1.2**。现有账号、玩家档案、绑定、MySQL 连接、服务器名称和运行配置沿用原设置。新安装的面板默认端口为 **5800**。

## 安装入口和发布附件

- **Windows 源码部署**：双击 `VexBot.bat`。原 `Myrinbot.bat`、`星桥.bat` 和 `云墟.bat` 仍可启动，窗口标题与消息均使用 VexBot。
- **Windows 部署 ZIP**：正式附件为 `VexBot-Windows-0.6.28.zip`。包内启动脚本沿用旧升级器允许的 `星桥.bat`，窗口显示 VexBot；可将脚本重命名为 `VexBot.bat` 使用。
- **独立官网**：正式附件为 `VexBot-website.zip`，面板、官网和网站 SDK 的新接入示例统一使用 VexBot 名称。
- **游戏端**：构建输出 `VexBot-*.jar`，面板以该名称下载；同一 Release 提供内容相同的 `StarBridge-*.jar` 兼容附件。每台服务器只安装一份对应平台和游戏版本的 JAR。
- **历史版本**：旧版曾使用 Myrinbot、AetherBot 或 StarBridge 发布，已发布的名称和附件保留原记录，不覆盖旧版本。

## 升级兼容

旧安装的升级监督进程不会由 Web 更新替换，只接受固定路径。因此新部署包继续使用 `StarBridge/` 归档根、`update.json` 更新协议、`bridge/target/StarBridge-*.jar` 和 `dist/StarBridge-website.zip`。相同部署内容同时提供 `StarBridge-Windows-0.6.28.zip`，旧升级器仍可识别。

以下技术标识继续沿用，以保留已有配置、登录状态和插件接入：

| 标识 | 用途 |
| --- | --- |
| `python -m starbridge`、`starbridge/` | Python 模块和现有启动命令 |
| `config.toml`、`data/starbridge.db` | 现有配置与 SQLite 文件路径 |
| MySQL 配置中的数据库名、用户名 | 既有数据库连接目标，不随品牌自动修改 |
| Bukkit 插件身份 `StarBridge`、`plugins/StarBridge/` | 插件配置和已有数据 |
| `/starbridge:l`、`/starbridge:ql`、`starbridge.bind` | 命令命名空间和权限节点 |
| `starbridge` 模组 ID、`cn.starbridge` Java 包 | 游戏加载器与插件内部标识 |
| `myrinbot-velocity`、`MyrinbotVelocity` | 已安装 Velocity 插件的内部身份与入口类 |
| `starbridge-website/`、`sdk/starbridge.js` | 已有网站源码与 SDK 路径 |
| `AlancoSage/StarBridge`、在线文档 `/starbridge` 路径 | 原源码、升级来源和文档链接 |

新网站推荐使用 `createVexBotClient` 或 `createVexBotRegistration`。原有 `createMyrinbotClient`、`createMyrinbotRegistration`、`createAetherBotClient`、`createAetherBotRegistration`、`createStarBridgeClient` 和 `createStarBridgeRegistration` 导出继续可用。

安装与升级步骤见 [Windows](windows-installation.md)、[Linux](linux-installation.md) 和 [更新说明](updates.md)。
