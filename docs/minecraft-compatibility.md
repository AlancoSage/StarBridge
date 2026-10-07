# Minecraft 版本兼容与 Java 选择

星桥 0.5.0 游戏桥接插件采用**通用兼容构建**：旧版与新版 Paper / Spigot 使用同一个 `StarBridge-0.5.0.jar`，无需按游戏版本下载不同的插件。插件最低 Java 8，游戏服务端仍使用自身要求的 Java。

## 安装与升级

1. 从 Bot 面板的玩家管理或游戏登录页面下载配套 JAR。
2. 停止游戏服务器，在 `plugins/` 中替换旧 StarBridge JAR，确保只保留一份。
3. 保留 `plugins/StarBridge/config.yml` 的地址、服务器 ID 和令牌，重新启动游戏服务器。
4. 在 Bot 面板确认桥接在线，检查聊天、`/qbind` 和玩家管理；开启游戏认证的服务器还需检查 `/l`、`/ql` 和未登录时的操作限制。

无需修改 Bot 的 Python 环境，也不需要安装显卡驱动。升级前的 JAR 虽然也叫 0.5.0，但仍可能是原 Java 17 构建，旧服应重新下载此次通用兼容构建。

## Java 怎么选

“插件最低 Java 8”只说明插件字节码能在 Java 8 或更新的 JVM 上加载，不能让要求 Java 21 的服务端改用 Java 8。下面是 [Paper 官方推荐表](https://docs.papermc.io/paper/getting-started/#requirements)，查阅日期为 2026-10-06：

| Paper 游戏版本 | 官方推荐 Java |
| --- | --- |
| 1.7.10–1.11 | 8 |
| 1.12–1.16.4 | 11 |
| 1.16.5 | 16 |
| 1.17–1.19 | 17 |
| 1.20–1.21.11 | 21 |
| 26.1 及更新版本 | 25 |

Spigot 和历史第三方构建请按对应发行说明选择运行环境；上表是 Paper 的推荐值，不是每种核心的最低要求。使用游戏启动脚本中的 `java -version` 确认实际运行版本，注意电脑可能同时装有多个 Java。

## 已完成哪些验证

| API 版本 | 验证方式 | 结果 |
| --- | --- | --- |
| Bukkit 1.4.7-R1.0、1.7.9-R0.2 | 从 Bukkit 官方标签源码重建 API；检查插件引用；Java 8 下运行接口代理测试 | 通过 |
| Spigot 1.8.8 | 官方 API 引用检查；Java 8 下运行兼容适配、网络与最终 JAR 测试 | 通过 |
| Spigot 1.12.2、1.16.5 | 官方 API 引用检查 | 通过 |
| Spigot 1.20.4 | 官方 API 引用检查；Java 17 下运行隔离的登录与 AuthMe 测试 | 通过 |
| Spigot 1.21.11、26.3 | 官方 API 引用检查 | 通过 |
| Paper 26.3 build 157-beta | 官方 API 引用检查 | 通过 |

API 检查验证插件直接调用的类和方法签名是否存在；接口代理测试使用真实 API 和模拟服务端，不运行 Minecraft 世界。**目前没有完成全部历史版本、每个构建号及所有插件组合的实服验证，也不能保证未来版本永远不变。**通用构建以跨版本适配为目标，正式部署前应在自己的核心与插件组合上验证。

## 跨版本行为

| 项目 | 处理方式 |
| --- | --- |
| 玩家在线列表 | 自动适配旧版数组和新版集合返回值 |
| 玩家生命值 | 自动适配旧版整数与新版浮点返回值 |
| 玩家延迟 | 核心有可用 API 时上报；旧版没有时省略，不填虚假数值 |
| UUID | 有原生 UUID API 时使用原值；更早的核心按玩家名生成稳定的旧版标识 |
| 封禁与解封 | 按能力使用档案封禁、名字封禁或旧版接口，并核对执行结果 |
| 登录事件 | 按核心能力注册拾取、编辑书本、副手切换、背包拖动等事件，避免引用旧核心没有的事件类 |
| 正版白名单 | 在后台查询官方身份，校验玩家名及可用的 UUID；任务过期、查询失败或身份不符时不会写入 |
| JSON 库 | 插件独立打包并隔离 Gson，避免依赖服务端自带的版本 |

旧版按名字生成的标识不等于 Mojang 正版 UUID；改名或升级到支持原生 UUID 的核心可能改变标识。迁移时由管理员核实玩家档案、QQ 绑定和游戏账号关联，不能按同名自动合并身份。旧核心可能无法恢复历史最后登录时间，面板以现有上报记录为准。

为了让旧核心加载同一份 JAR，插件不指定只在较新核心上可用的 `api-version`。新版核心可能输出 legacy plugin / 未声明 API 版本提示；这是所用兼容加载方式的提示，应结合插件启用结果与桥接状态判断是否成功。字段含义见 [Spigot plugin.yml 说明](https://www.spigotmc.org/wiki/plugin-yml/)。

未登录限制不会因缺少新版事件而直接放行。密码登录还需要能够关闭核心原生密码命令回显；该能力不可用时拒绝启用密码登录，可检查核心版本或仅启用 QQ 登录。AuthMe 兼容模式额外要求该 AuthMe 版本支持 API v3，游戏版本兼容不代表所有 AuthMe 版本都可用。

另外提供 Forge **1.7.10 / 1.12.2 / 1.16.5 / 1.18.2 / 1.19.2 / 1.20.1** 和 NeoForge **1.21.1** 服务端模组，各自使用独立 JAR，安装与 Java 选择见 [Forge 与 NeoForge 游戏端](mod-game-ends.md)。Fabric 提供 **1.16.5 / 1.18.2 / 1.19.2 / 1.20.1 / 1.21.1** 独立 JAR，详见 [Fabric 游戏端](fabric-game-ends.md)。模组放在 `mods/`，使用内置或自动登录引擎，不同加载器不能混装。当前不包含 Folia 或基岩版原生核心。

## 构建与重复验证

构建环境使用 **JDK 17+**，输出为 Java 8 字节码。运行旧服只需要 Java 8，不需要 JDK 17；Bot 仍使用 Python 3.11+。

Windows 构建：

```powershell
.\bridge\build.ps1 -JavaHome 'C:\Program Files\Java\jdk-17'
```

也可在 `bridge/` 内使用 Maven 执行 `mvn package`。两种方式均隔离打包 Gson，并且不把 Bukkit API 或测试类装入最终 JAR。

隔离测试不属于 Maven 单元测试。维护者可以在项目根目录运行：

```powershell
.\bridge\test.ps1
.\bridge\test-compatibility.ps1 -RuntimeJavaHome 'C:\Java\jdk8'
```

`RuntimeJavaHome` 指向已有的 Java 8 环境；不传时使用构建 JDK。兼容测试默认检查 Spigot 1.8.8，可通过 `-ApiJars` 传入其他官方 API JAR 路径。历史 API 的来源和新版下载校验值记录在 `bridge/compatibility-matrix.json`。网络测试只连接本机临时 HTTP 服务，不发送邮件或 QQ 测试消息。

出现 `UnsupportedClassVersionError` 时先确认实际加载的是通用构建，并核对启动 Java；出现 `NoSuchMethodError` 或 `NoClassDefFoundError` 时保留核心完整版本、Java 版本和堆栈，再定位未覆盖的 API 差异。
