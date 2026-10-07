# Forge 与 NeoForge 游戏端

**适用：星桥 Bot 0.6.3+ · 游戏端模组 0.1.0。** 在管理面板选择 Minecraft 版本，下载对应 JAR 和连接配置，即可将模组服接入星桥。Paper / Spigot 继续使用原来的 Bukkit 插件；多个不同版本服务器可以连接同一台 Bot。

## 选择版本

每个 Minecraft 版本使用独立构建，不能跨版本替换，也不能混用 Forge 与 NeoForge。

| Minecraft | 加载器与验证构建 | 运行 Java | 配置文件 |
| --- | --- | --- | --- |
| 1.7.10 | Forge 10.13.4.1614 | 8 | `config/starbridge-bridge.properties` |
| 1.12.2 | Forge 14.23.5.2859 | 8 | `config/starbridge-bridge.properties` |
| 1.16.5 | Forge 36.2.34 | 8 | `config/starbridge-bridge.properties` |
| 1.18.2 | Forge 40.3.0 | 17 | `config/starbridge-common.toml` |
| 1.19.2 | Forge 43.5.0 | 17 | `config/starbridge-common.toml` |
| 1.20.1 | Forge 47.4.10 | 17 | `config/starbridge-common.toml` |
| 1.21.1 | NeoForge 21.1.256 | 21 | `config/starbridge-common.toml` |

这些是已验证的具体组合；整合包的其他模组可能有额外 Java 或加载器要求。安装器可从 [Forge 官方下载页](https://files.minecraftforge.net/) 或 [NeoForge 官方下载页](https://neoforged.net/) 获取。Java 环境说明见 [Forge 文档](https://docs.minecraftforge.net/en/1.20.1/gettingstarted/) 与 [NeoForge 1.21.1 文档](https://docs.neoforged.net/docs/1.21.1/gettingstarted/)。

## 安装：先接 Bot，再启动游戏服

1. 在 Bot 面板 **接入空间 → 服务器** 创建服务器，保存 ID、群号、连接令牌和允许的远程命令。
2. 展开服务器卡片的 **安装插件 · 下载连接配置**，填写游戏服务器能访问的主程序地址。
3. 在 **Forge / NeoForge 游戏版本** 选择对应版本，点击 **下载所选模组 JAR** 和 **下载模组连接配置**。
4. 停止游戏服务器，备份世界。将 JAR 放到服务器根目录的 `mods/`，连接配置放到 `config/`，保留下载文件名；每台服务器只装一份星桥模组。
5. 启动游戏服务器，在 Bot 面板确认桥接在线、版本正确，再检查聊天联动与 `/qbind`。
6. 需要注册密码或 QQ 登录时，在 **成员 → 游戏登录** 勾选这台服务器，使用 **自动** 或 **星桥内置** 引擎，保存后检查 `/l`、`/ql` 和未登录限制。

**不要把模组放到 `plugins/`，也不要把 Bukkit 插件放到 `mods/`。** 不需要给玩家安装星桥客户端模组。Forge 1.7.10 的原生网络握手要求客户端支持 Forge；整合包自身要求的客户端模组仍按整合包说明安装。

### 旧版配置：1.7.10 / 1.12.2 / 1.16.5

文件使用 UTF-8：`config/starbridge-bridge.properties`。

```properties
endpoint=http://127.0.0.1:8088
server-id=survival
token=替换为这台服务器的连接令牌
allowed-commands=list
```

若手动配置多个完整命令，以 `|` 分隔。连接成功后以 Bot 面板的命令白名单为准，不开放任意控制台命令。

### 新版配置：1.18.2 / 1.19.2 / 1.20.1 / NeoForge 1.21.1

文件使用 UTF-8：`config/starbridge-common.toml`。

```toml
endpoint = "http://127.0.0.1:8088"
server-id = "survival"
token = "替换为这台服务器的连接令牌"
allowed-commands = ["list"]
```

这里的令牌来自 **服务器卡片**，不是面板管理员令牌或网站 API 密钥。Bot 与游戏服在不同机器时，地址不能填 `127.0.0.1`；填写游戏服能访问的地址，并通过 HTTPS 或可信加密隧道传输账号密码。配置缺失或无效时模组拒绝启动服务端，避免误以为登录保护已经生效。

## 功能与指令

| 功能 | 各版本共同支持 |
| --- | --- |
| QQ 联动 | 游戏聊天、加入和退出、QQ 到游戏广播、预设命令 |
| 服务器状态 | 在线人数、版本、Java、白名单状态与玩家列表 |
| 玩家管理 | UUID、历史档案、IP、原生白名单 / 封禁 / OP 状态；不自动查询 IP 归属地 |
| 管理操作 | 踢出、封禁、解封、白名单增删；执行后回执，解封核对处罚来源 |
| QQ 绑定 | `/qbind` 获取短期绑定码，群内完成绑定 |
| 密码登录 | `/login <密码>` 或 `/l <密码>`，使用网页 / 群外注册时的账号密码 |
| QQ 登录 | `/qqlogin` 或 `/ql`，向已绑定 QQ 发送私聊确认，确认后放行 |
| 退出登录 | `/logout`，立即恢复登录限制 |

游戏登录默认关闭，按服务器启用。纯 Forge / NeoForge 不使用 Bukkit 的 AuthMe API；选择 AuthMe 兼容引擎时不会绕过认证。混合核心、Fabric、Folia 和基岩版原生核心不在此构建范围内。

登录前拦截移动、聊天、普通命令、背包及模组交互，登录指令不会作为聊天发送。每次连接有独立 nonce，重连后不能沿用上次 QQ 确认。网络请求在有界后台队列中执行，世界修改回到游戏线程；无需显卡或客户端界面组件。

## 升级与排查

- **升级**：停止游戏服，替换对应版本 JAR，保留配置；确认 `mods/` 中没有旧星桥副本。Bot 升级不会自动替换独立游戏服的 JAR。
- **版本不符 / 无法加载**：核对 Minecraft、加载器、JAR 名称和启动脚本实际使用的 `java -version`。
- **桥接离线**：检查 Bot 地址、服务器 ID、专属令牌、端口和游戏服日志。配置修改后重启游戏服。
- **无法登录**：确认已勾选该服务器、选择内置或自动引擎、玩家已注册；QQ 登录需先绑定并保证机器人能发私聊。
- **命令被拒绝**：面板允许的是完整命令，不能仅配置命令前缀来放行所有参数。
- **整合包冲突**：先在相同版本的最小测试服确认，再逐步加入原整合包，保留加载器完整版本与异常堆栈。

## 开发与构建

源码目录按原生 API 分开，最终成品均输出到 `bridge/target/`。旧版构建使用 JDK 17 的 `--release 8`，无需安装过时的 ForgeGradle；编译依赖从官方仓库下载并核对固定 SHA-256，不打包 Minecraft 或加载器本体。

| 目标 | 源码目录 | 构建 JDK |
| --- | --- | --- |
| Forge 1.7.10 / 1.12.2 / 1.16.5 | `bridge-mods/` | 17，输出 Java 8 |
| Forge 1.18.2 | `bridge-forge-1.18.2/` | 17 |
| Forge 1.19.2 | `bridge-forge-1.19.2/` | 17 |
| Forge 1.20.1 | `bridge-forge/` | 17 |
| NeoForge 1.21.1 | `bridge-neoforge/` | 21 |

Windows，在项目根目录运行：

```powershell
python bridge-mods/build.py --java-home 'C:\Java\jdk-17'
.\bridge-forge-1.18.2\build.ps1 -JavaHome 'C:\Java\jdk-17'
.\bridge-forge-1.19.2\build.ps1 -JavaHome 'C:\Java\jdk-17'
.\bridge-forge\build.ps1 -JavaHome 'C:\Java\jdk-17'
.\bridge-neoforge\build.ps1 -JavaHome 'C:\Java\jdk-21'
```

Linux，旧版使用 `python3 bridge-mods/build.py --java-home /path/to/jdk17`；新版在对应源码目录设置正确的 `JAVA_HOME` 并运行 `sh ./gradlew copyBridge`。Forge 成品经过生产映射转换，NeoForge 使用该版本的原生映射；不要使用开发目录的中间 JAR。

GitHub 私有发布流程构建全部游戏端、运行单元测试，并附带独立 JAR 与 `SHA256SUMS.txt`。Bot 部署包同时携带这些游戏端，面板即可按版本下载。

## 验证范围

在表中所列加载器和 Java 上启动专用服务端，用未安装星桥的协议客户端验证心跳、玩家档案、登录前移动 / 聊天 / 命令限制、错误密码、含空格密码的 `/l`、绑定码、聊天 / 广播、QQ `/ql` 确认、退出、后端会话重建、白名单增删与申请回执、踢出、封禁 / 解封来源核对，以及关闭认证后的正常命令。

验证使用隔离 Bot、离线模式和模拟 QQ 私聊，不代表已测试所有构建号、正版账号登录、真实 QQ 服务或全部整合包组合。正式部署请在自己的整合包中复查登录和管理流程。
