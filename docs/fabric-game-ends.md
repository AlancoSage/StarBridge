# Fabric 游戏端

**当前版本：VexBot 0.6.28 · Fabric 游戏端模组 0.1.2。** Fabric 服务端使用独立 VexBot 模组，连接同一台 Bot 即可接入 QQ 聊天、玩家管理、白名单与游戏登录。Paper / Spigot、Forge 和 NeoForge 的 JAR 继续按各自文档安装。Bot 0.6.4 已提供前五个 Fabric 版本；新增版本从 0.6.5 起提供。

## 选择 Minecraft 与 Java

每个版本使用对应的 JAR，不能跨 Minecraft 版本替换。旧五版固定使用 **Fabric Loader 0.16.14**，新增五版固定使用 **0.19.5**；游戏服务端按表中要求选择 Java。

下表使用 v0.6.28 正式附件、当前源码构建和面板下载的文件名。历史 Release 附件及部署 ZIP 内的兼容文件名仍为 `StarBridge-*`，按实际下载文件安装同一游戏版本的 JAR；名称关系见 [项目名称与兼容说明](project-name.md)。

| Minecraft | Fabric Loader | 运行 Java | VexBot 文件 |
| --- | --- | --- | --- |
| 1.16.5 | 0.16.14 | 8 | `VexBot-Fabric-1.16.5-0.1.2.jar` |
| 1.18.2 | 0.16.14 | 17 | `VexBot-Fabric-1.18.2-0.1.2.jar` |
| 1.19.2 | 0.16.14 | 17 | `VexBot-Fabric-1.19.2-0.1.2.jar` |
| 1.20.1 | 0.16.14 | 17 | `VexBot-Fabric-1.20.1-0.1.2.jar` |
| 1.21.1 | 0.16.14 | 21 | `VexBot-Fabric-1.21.1-0.1.2.jar` |
| 1.21.8 | 0.19.5 | 21 | `VexBot-Fabric-1.21.8-0.1.2.jar` |
| 1.21.11 | 0.19.5 | 21 | `VexBot-Fabric-1.21.11-0.1.2.jar` |
| 26.1 | 0.19.5 | 25 | `VexBot-Fabric-26.1-0.1.2.jar` |
| 26.2 | 0.19.5 | 25 | `VexBot-Fabric-26.2-0.1.2.jar` |
| 26.3 | 0.19.5 | 25 | `VexBot-Fabric-26.3-0.1.2.jar` |

从 [Fabric 官方服务端下载页](https://fabricmc.net/use/server/) 安装相应 Minecraft 版本的服务端。VexBot 自身**不依赖 Fabric API**，无需为 VexBot 给玩家安装客户端模组；整合包其他模组要求的 Fabric API、客户端组件和 Java 版本仍按整合包说明安装。Loader 的依赖与版本信息来自 [Fabric 官方元数据 API](https://github.com/FabricMC/fabric-meta)。

## 安装与接入

1. 先启动 Bot，在管理面板 **接入空间 → 服务器** 新建服务器，设置服务器 ID、QQ群、专属连接令牌与允许的远程命令。
2. 展开服务器卡片的 **安装插件 · 下载连接配置**，填写游戏服务器能访问的 Bot 地址。
3. 在模组游戏端版本列表选择 **Fabric + 对应 Minecraft 版本**，下载所选模组 JAR 与连接配置。
4. 停止游戏服务器，备份世界。将 JAR 放在服务器的 `mods/`，配置放在 `config/starbridge-bridge.properties`，每台服务器仅保留一份 VexBot 模组。
5. 使用表中对应的 Java 启动 Fabric 服务端。在 Bot 面板确认桥接在线、游戏版本与加载器正确，再检查聊天联动、玩家档案与 `/qbind`。
6. 需要密码或 QQ 登录时，在 **成员 → 游戏登录** 勾选这台服务器，选择 **自动** 或 **VexBot 内置** 引擎，保存后验证 `/l`、`/ql` 和未登录限制。

模组放在 `mods/`，不要放进 `plugins/`。Fabric、Forge 与 NeoForge 的 VexBot JAR 不能混装；已部署其他核心的服务器不要仅通过替换 VexBot JAR 改换加载器。

### 连接配置

十个 Fabric 版本均使用 UTF-8 配置：`config/starbridge-bridge.properties`。

```properties
endpoint=http://127.0.0.1:5800
server-id=survival
token=替换为这台服务器的连接令牌
allowed-commands=list
```

`token` 来自服务器卡片，不能使用面板管理员令牌或官网 API 密钥。Bot 与游戏服位于不同机器时，填写游戏服能访问的 Bot 地址，通过 HTTPS 或可信加密隧道传输账号密码。

手动设置多个允许的完整命令时，以 `|` 分隔；连接成功后以 Bot 面板同步的命令白名单为准。配置缺失或无效时，VexBot 拒绝启动服务端，避免误以为登录保护已经生效。修改连接配置后需要重启游戏服。

## 功能与登录指令

| 功能 | 行为 |
| --- | --- |
| QQ 联动 | 游戏聊天、加入 / 退出通知、QQ 到游戏广播与预设控制台命令 |
| 服务器状态 | 在线人数、游戏 / 加载器 / Java 版本、白名单状态与玩家列表 |
| 玩家管理 | UUID、历史档案、IP 与原生白名单 / 封禁 / OP 状态；保留手动归属地 |
| 管理操作 | 踢出、封禁、解封、白名单增删与申请执行回执；解封核对处罚来源 |
| QQ 绑定 | `/qbind` 获取短期绑定码，在群内完成绑定 |
| 密码登录 | `/login <密码>` 或 `/l <密码>`，使用网页 / 群外注册的账号密码 |
| QQ 登录 | `/qqlogin` 或 `/ql`，向已绑定 QQ 私聊发送登录确认 |
| 退出登录 | `/logout`，立即恢复登录限制 |

游戏登录默认关闭，按服务器选择开启。Fabric 没有 Bukkit 的 AuthMe API，仅使用自动或 VexBot 内置引擎；选择 AuthMe 时拒绝放行，不绕过认证。其他独立登录模组尚未提供适配，不要与 VexBot 内置认证同时启用。

登录前限制移动、聊天、普通命令、背包、物品与模组交互，并保护玩家免受伤害。登录指令不会作为普通聊天发送；含空格密码保留空格。每次连接有独立 nonce，重连后不能沿用旧 QQ 确认或旧请求结果。玩法操作回到游戏主线程，HTTP 请求使用有界后台队列，无需显卡或客户端界面组件。

## 升级与排查

- **升级**：停止游戏服，替换相同 Minecraft 版本的 VexBot JAR，保留配置并删除旧副本。Bot 升级不会替换独立游戏服中的 JAR。
- **无法加载**：核对 Minecraft 版本、Fabric Loader、文件名与启动脚本实际调用的 `java -version`。不要使用 Forge / NeoForge 版 JAR。
- **桥接离线**：检查 Bot 是否已启动、地址与端口、服务器 ID、专属令牌和日志。连接不到策略时，启用认证的玩家不会被自动放行。
- **无法登录**：核对面板中已勾选服务器、内置 / 自动引擎与账号注册状态；QQ 登录还需绑定且机器人能够发送私聊。
- **命令被拒绝**：面板配置的是允许的完整命令，不能只填命令前缀来允许任意参数。
- **整合包冲突**：先用相同 Minecraft 与 Loader 的最小测试服复查，再逐步加入原模组；保留完整版本号与异常堆栈。

## 开发与构建

游戏端复用 Java 8 公共桥接引擎，以 Fabric Loader 的 `ModInitializer` 启动。1.x 使用精确的官方 Yarn 映射与 Loader `MappingResolver` 访问原生方法；26.x 的官方服务端不再混淆，直接使用实际类名、方法名和签名，并在构建时逐项校验对应版本的官方服务端字节码。Mixin 安装生命周期与认证拦截。每个 Minecraft 版本独立打包，不依赖 Loom，也不把 Minecraft、Fabric Loader 或 Fabric API 装入成品 JAR。

构建使用 **Python 3.11+ 与 JDK 17**，编译参数 `--release 8`；这只表示 VexBot 字节码最低 Java 8，不改变 Minecraft 自身的 Java 要求。固定编译依赖与 Yarn 映射从 Fabric 官方 Maven 获取并核对校验值；26.x 官方服务端包由 Mojang 版本清单定位并校验，仅在 Python 中读取类声明，无需用 JDK 17 启动 Java 25 游戏服。成品输出到 `bridge/target/`。

| Minecraft | 固定映射或声明来源 |
| --- | --- |
| 1.16.5 | `net.fabricmc:yarn:1.16.5+build.10:v2` |
| 1.18.2 | `net.fabricmc:yarn:1.18.2+build.4:v2` |
| 1.19.2 | `net.fabricmc:yarn:1.19.2+build.28:v2` |
| 1.20.1 | `net.fabricmc:yarn:1.20.1+build.10:v2` |
| 1.21.1 | `net.fabricmc:yarn:1.21.1+build.3:v2` |
| 1.21.8 | `net.fabricmc:yarn:1.21.8+build.1:v2` |
| 1.21.11 | `net.fabricmc:yarn:1.21.11+build.6:v2` |
| 26.1 / 26.2 / 26.3 | 各自官方服务端 JAR 的实际类与成员声明，`official` 命名空间 |

构建脚本固定 Loader 与 Mixin / ASM 编译依赖，并核对摘要；运行服务端安装表中对应的 Loader。这些是编译和加载器依赖，不需要管理员手动复制到 `mods/`。26.x 不依赖不存在的 Yarn 或 `server_mappings` 下载。

以下命令供维护者在完整源码检出中使用；保留 `bridge-fabric/build.py`、`bindings.py`、`classfile.py`、`bindings/26.1.json`、`26.2.json`、`26.3.json` 与 `bridge-mods/common/` 公共引擎。Bot 部署 ZIP 提供成品 JAR，不包含桥接构建源码和依赖缓存。

Windows，在项目根目录构建全部十个版本：

```powershell
python bridge-fabric/build.py --java-home 'C:\Program Files\Java\jdk-17'
```

也可使用 PowerShell 包装脚本并指定虚拟环境中的 Python：

```powershell
.\bridge-fabric\build.ps1 -JavaHome 'C:\Program Files\Java\jdk-17' -Python .\.venv\Scripts\python.exe
```

Linux：

```bash
python3 bridge-fabric/build.py --java-home /path/to/jdk17
```

加上 `--version 26.3` 可只构建对应版本；不指定时构建全部十版。依赖默认缓存到 `bridge-fabric/build/dependencies`，可用 `--cache /path/to/cache` 指定其他目录。使用 `bridge/target/` 的最终 JAR 部署，构建过程中不需要启动游戏服务器。

## 验证范围

已在 **Fabric Loader 0.16.14** 上分别启动 Minecraft **1.16.5 / Java 8**、**1.18.2 / Java 17**、**1.19.2 / Java 17**、**1.20.1 / Java 17** 与 **1.21.1 / Java 21** 专用测试服，五组均使用未安装 VexBot 的原版协议客户端完成以下流程：

- 心跳、玩家档案与在线信息，未登录时的移动、聊天、`/help` 与 `/msg` 限制。
- 错误密码、含空格密码的 `/l` 登录；测试密码未出现在服务端日志；获取绑定码。
- 游戏聊天、Bot 到游戏广播、绑定 QQ 的 `/ql` 确认、退出登录及后端会话重建后的重新认证。
- 白名单增删与申请审核执行回执，踢出、封禁、带来源标记的解封和保留独立处罚。
- 原生控制台命令白名单，以及关闭认证后正常游戏指令的执行。

新增 **1.21.8 / Java 21** 与 **1.21.11 / Java 21** 在 **Fabric Loader 0.19.5** 的真实专用测试服上，各通过 21 项离线协议客户端检查，包含上面的登录、联动与管理流程。两版还检查了 signed command 包的确认状态，1.21.11 验证了新版玩家档案、白名单及封禁记录结构；解封不会删除相同理由的原生独立处罚。

**26.1 / Java 25 / Fabric Loader 0.19.5** 的真实专用测试服也通过 21 项离线协议客户端检查，包括登录、聊天联动、玩家与白名单管理、原生封禁来源保护和允许的控制台命令；检查了原生 signed command 包的 ACK 与校验状态。

**26.2 / Java 25** 与 **26.3 / Java 25** 在 **Fabric Loader 0.19.5** 的真实专用测试服上，各通过 23 项检查。测试客户端分别使用对应版本官方服务端的 `ProtocolInfo` 与 `StreamCodec` 编解码，经本机 TCP 完成真实连接、配置阶段、密码与 QQ 登录、聊天、后台会话重建、白名单、踢出、封禁与命令执行；同时核对新版白名单身份结构，以及带签名命令包的 ACK 与校验状态。没有借用其他游戏版本的协议定义。

1.21.1、1.21.8、1.21.11、26.1、26.2 与 26.3 检查了离线会话中的原生 signed command 包和 ACK 状态；这不代表已验证正版账号的密码学签名链。测试使用隔离 Bot、离线模式与模拟 QQ 私聊，未验证真实正版会话、真实 QQ 服务、完整 GUI 客户端、全部整合包或其他 Loader 构建号。正式部署请在自己的模组组合中复查，不据此声明兼容所有历史或未来版本。

相关文档：[游戏登录](game-login.md)、[Forge / NeoForge 游戏端](mod-game-ends.md)、[Minecraft 版本兼容与 Java 选择](minecraft-compatibility.md)。
