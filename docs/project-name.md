# 项目名称与兼容说明

项目正式名称为 **Myrinbot**。界面、用户消息和文档使用新名称；更名不迁移已有账号、玩家档案、绑定或运行配置。

**v0.6.10** 正式以 Myrinbot 名称分发，配套 Bukkit 插件 **0.5.3** 与 Forge / NeoForge / Fabric 模组 **0.1.1**。管理面板和独立官网使用同一枚黑白 M 机器人图标。新安装默认使用 **5800** 端口；升级时保留已有配置中的端口，不要求迁移连接地址。

## 安装入口和发布附件

- **Windows 源码部署**：推荐双击 `Myrinbot.bat`；已有的 `星桥.bat` 与 `云墟.bat` 作为兼容入口继续可用。
- **Windows 部署 ZIP**：包内仍提供 `星桥.bat`，可直接双击，也可自行重命名为 `Myrinbot.bat`。脚本根据自身所在目录运行，不要求固定文件名。
- **v0.6.10 正式附件**：使用 `Myrinbot-*` 名称，包括 `Myrinbot-Windows-0.6.10.zip`、`Myrinbot-website.zip` 与配套游戏 JAR。同版提供内容相同的 `StarBridge-Windows-0.6.10.zip` 兼容附件，供旧升级器识别；下载时以对应 Release 的实际附件为准。
- **游戏端源码构建**：`bridge/target/` 输出 `Myrinbot-*.jar`，并提供内容相同的 `StarBridge-*.jar` 兼容副本。部署 ZIP 内继续使用兼容文件名，面板下载使用新产品名；每台游戏服只安装其中一份。
- **已经发布的历史版本**：附件名称和版本说明保留原记录，安装旧版时按对应 Release 的实际文件名操作。

## 保留的技术标识

已有版本的稳定升级器不会随 Web 更新替换，只接受原有的受管理路径。因此部署 ZIP 内仍使用 `StarBridge/` 归档根、`update.json` 更新协议、`bridge/target/StarBridge-*.jar` 和 `dist/StarBridge-website.zip`。对外附件可以使用新名称，包内兼容路径不需要手动改动。

以下标识也继续保留：

| 标识 | 保留原因 |
| --- | --- |
| `python -m starbridge`、`starbridge/` | Python 模块和已有启动命令 |
| `config.toml`、`data/starbridge.db` | 运行配置与既有数据库默认路径 |
| Bukkit 插件标识 `StarBridge`、`plugins/StarBridge/` | 游戏服插件配置、原有数据与命令命名空间 |
| `/starbridge:l`、`/starbridge:ql`、`starbridge.bind` | 游戏命令和权限节点 |
| `starbridge` 模组 ID、`cn.starbridge` Java 包与配置文件名 | 游戏加载器、游戏端配置和构建兼容 |
| `starbridge-website/`、`sdk/starbridge.js`、`createStarBridgeClient` | 独立官网源码路径与已有网站 SDK 接入 |
| `AlancoSage/StarBridge` 与在线文档的 `/starbridge` 路径 | 已有源码、更新来源与文档链接 |

产品名称使用 **Myrinbot**，启动命令仍为 `python -m starbridge`。保留现有数据库、游戏插件目录与配置即可接入；独立网站的新 SDK 示例使用 `createMyrinbotClient`，旧导出继续兼容。

在线文档的既有路径仍可使用。相关安装步骤见 [Windows](windows-installation.md)、[Linux](linux-installation.md)，版本安装与回退见 [更新说明](updates.md)。
