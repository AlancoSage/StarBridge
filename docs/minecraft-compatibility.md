# Minecraft 版本兼容与 Java 选择

Myrinbot Bot **0.6.17** 配套游戏桥接插件 **0.5.3** 采用**通用兼容构建**：Paper / Spigot / Folia 使用同一个 `Myrinbot-0.5.3.jar`，无需为 Folia 单独下载模组。插件最低 Java 8，游戏服务端仍使用自身要求的 Java。

## 安装与升级

1. 从 Bot 面板的玩家管理或游戏登录页面下载配套 JAR。
2. 停止游戏服务器，在 `plugins/` 中替换旧 Myrinbot JAR，确保只保留一份。
3. 保留 `plugins/StarBridge/config.yml` 的地址、服务器 ID 和令牌，重新启动游戏服务器。
4. 在 Bot 面板确认桥接在线，检查聊天、`/qbind` 和玩家管理；开启游戏认证的服务器还需检查 `/l`、`/ql` 和未登录时的操作限制。

无需修改 Bot 的 Python 环境，也不需要安装显卡驱动。Folia 至少使用 0.5.2 兼容构建，推荐当前 0.5.3；此前的 0.5.0 未提供 Folia 调度适配。

## Folia 接入

1. 在 Bot 面板「接入空间 → 服务器」保存服务器 ID、连接令牌和关联群，下载 `Myrinbot-0.5.3.jar` 与这台服务器的 `config.yml`。
2. 完整停止 Folia，把 JAR 放入 `plugins/`，配置放入 `plugins/StarBridge/config.yml`。只保留一份 Myrinbot 插件。
3. 用该 Folia 构建要求的 Java 启动游戏服；本次实服验证为 **Folia 1.21.8 正式 build 6 / Java 21**。Java 8 字节码不表示 Folia 服务端能用 Java 8 启动。
4. 在 Bot 面板确认桥接在线，检查玩家档案、双向聊天、`/qbind` 与管理回执。
5. 需要游戏登录时，在「成员 → 游戏登录」勾选这台服务器，选择「Myrinbot 内置」或「自动」，按需启用密码与 QQ 确认，再检查 `/l`、`/ql`、`/logout` 和未登录限制。

无需额外调度插件或客户端组件。Myrinbot 自动识别 Folia：全局任务用于组装状态与控制台操作，玩家状态、消息、登录结果及踢出回到各自实体调度器。玩家跨区域移动后仍由其实体调度器处理；已离线连接的回调不会操作新连接。实现方式遵循 [Paper / Folia 调度说明](https://docs.papermc.io/paper/dev/folia-support/)。

**Folia 游戏登录只使用 Myrinbot 内置模式。** 使用内置或自动引擎并移除第三方登录插件；已启用 AuthMe、nLogin、LoginSecurity 或 LibreLogin，或明确选择第三方兼容引擎时 Myrinbot 拒绝放行。登录插件能加载 Folia 不表示其公开 API 已具备安全的区域线程契约，Myrinbot 不会调用未经验证的接口。普通 Paper / Spigot 可以使用下列兼容引擎。

## 第三方登录插件兼容

| 引擎 | 核心与接口要求 | 首次关联与限制 |
| --- | --- | --- |
| AuthMe | 普通 Paper / Spigot；公开 API v3 | 已有账号需原身份验证，不覆盖原密码；新账号可创建随机内部凭据 |
| nLogin | 普通 Paper / Spigot 本服原生后端；Identity API，本次检查 2.0.24 / API 2.0 | 每连接原生注册或密码及额外验证；账号 UUID 必须匹配；不接代理模式 |
| LoginSecurity | 普通 Paper / Spigot；3.x 会话与异步 Action API | 已有账号需原身份；注册验证码和关闭注册不能绕过 |
| LibreLogin | 普通 Paper；0.24.0 公开 API，Java 21 | 首次原生注册 / 登录后关联；本版 Paper 拒绝带 TOTP 密钥的账号；不接代理或 Folia |
| Myrinbot 内置 | Paper / Spigot / Folia；Forge / NeoForge / Fabric 对应模组 | 不同时启用第三方认证；模组服与 Folia 可选自动 |

每台游戏服只启用一个已适配的登录插件，Myrinbot 在调用 API 前拒绝多个认证所有者。显式引擎缺失、公开 API 不匹配及未知引擎不会回退放行；同一 Bot 接入不同加载器时选择「自动」。各适配器可信关联文件互相隔离，既有 `authme-links.properties` 保留可用，其他插件不能继承它的信任。安装步骤、原生命令、API 来源及验证范围见 [可选登录插件](game-login.md#可选登录插件)。

安装、升级、移除登录插件时完整停止并重启游戏服，不使用热卸载或强制插件停用。正常关服会取消待执行的全局与实体任务并清理回调；插件停用时不在非玩家线程逐个踢人，不能把热停用当成继续在线运行的认证保护方式。面板中的认证开关与业务设置仍可正常保存应用，不需要为了改这些设置重启游戏服。

## Java 怎么选

“插件最低 Java 8”只说明插件字节码能在 Java 8 或更新的 JVM 上加载，不能让要求 Java 21 的服务端改用 Java 8。下面是 [Paper 官方推荐表](https://docs.papermc.io/paper/getting-started/#requirements)，查阅日期为 2026-10-10：

| Paper 游戏版本 | 官方推荐 Java |
| --- | --- |
| 1.7.10–1.11 | 8 |
| 1.12–1.16.4 | 11 |
| 1.16.5 | 16 |
| 1.17–1.19 | 17 |
| 1.20–1.21.11 | 21 |
| 26.1 及更新版本 | 25 |

Folia、Spigot 和历史第三方构建请按对应发行说明选择运行环境；上表是 Paper 的推荐值，不是每种核心的最低要求。使用游戏启动脚本中的 `java -version` 确认实际运行版本，注意电脑可能同时装有多个 Java。

## 已完成哪些验证

| 目标 / 版本 | 验证方式 | 结果 |
| --- | --- | --- |
| Bukkit 1.4.7-R1.0、1.7.9-R0.2 | 从 Bukkit 官方标签源码重建 API；检查插件引用；Java 8 下运行接口代理测试 | 通过 |
| Spigot 1.8.8 | 官方 API 引用检查；Java 8 下运行兼容适配、网络与最终 JAR 测试 | 通过 |
| Spigot 1.12.2、1.16.5 | 官方 API 引用检查 | 通过 |
| Spigot 1.20.4 | 官方 API 引用检查；Java 17 下运行隔离的登录与 AuthMe 测试 | 通过 |
| Spigot 1.21.11、26.3 | 官方 API 引用检查 | 通过 |
| Paper 26.3 build 157-beta | 官方 API 引用检查 | 通过 |
| 传统 Bukkit / Folia 调度接口 | Java 8 字节码的隔离调度测试；覆盖线程归属、退休、任务取消和关闭竞态，共 50 项 | 通过 |
| Folia 内置登录 | 隔离的双区域登录测试，覆盖密码、QQ、策略与 nonce、超时、退休、四种外部登录插件拒绝和停用竞态，共 33 项 | 通过 |
| Folia 1.21.8 正式 build 6 | Java 21 实服，4 个区域线程，两名相隔 8192 格的协议玩家；密码 / QQ 登录、限制、档案、广播、白名单、处罚和停服，共 35 项 | 通过 |
| 新增原生登录适配器 | nLogin 25 项、LoginSecurity 47 项、LibreLogin 35 项隔离公共 API 契约检查，覆盖原账号归属、异步等待、身份变化、失败、重载与并发记录持久化 | 通过 |
| LoginSecurity 3.3.1 + Paper 1.21.8 正式 build 60 | Java 21 实服，新账号异步注册及状态恢复、已有原账号双证明、原生会话恢复仍需 Myrinbot 证明、网站 /login 与 /l、QQ /ql、限制与退出，共 23 项 | 通过 |
| nLogin free 2.0.24 + Paper 1.21.8 正式 build 60 | Java 21 实服，原生或 Myrinbot 单端成功仍限制、网站与 QQ 命名空间指令、普通原生注册与密码登录、UUID 核对、重连及命令冲突，共 16 项 | 通过 |
| LibreLogin 0.24.0 + Paper 1.21.4 正式 build 232 | Java 21 实服，首次原生注册及登录、网站 /l、绑定 QQ /ql、原密码不变、身份核对、拒绝带 TOTP 密钥的账号与正常停服，共 26 项 | 通过 |

Folia 实服检查确认两名玩家分别属于两个独立区域，玩家操作在各自所属实体线程执行。进服、退出登录、重连、踢出与封禁转换期间心跳均被接受，客户端解码错误为 0，并在仍有玩家在线时完成正常停服（退出码 0）。管理处罚自动解封同时核对来源与原因，管理员独立封禁得到保留。

本次使用离线 Minecraft 协议客户端，QQ 流程由隔离 OneBot 接口完成；未验证正版在线档案的密码学签名链或真实 QQ 私聊发送。上述实服结果只对应 **Folia 1.21.8 正式 build 6**，不扩展为其他 Folia 构建号或插件组合的验证结果。

API 检查验证插件直接调用的类和方法签名是否存在；接口代理测试使用真实 API 和模拟服务端，不运行 Minecraft 世界。**目前没有完成全部历史版本、每个构建号及所有插件组合的实服验证，也不能保证未来版本永远不变。**通用构建以跨版本适配为目标，正式部署前应在自己的核心与插件组合上验证。

LoginSecurity 实服检查使用真实 Paper、原登录插件和游戏协议客户端，Myrinbot HTTP 返回由隔离测试后端提供；nLogin 和 LibreLogin 使用真实 Myrinbot 账号后端。QQ 发送与确认在测试中模拟，不向真实 QQ 发送消息。nLogin Premium 专属二次验证未做实服检查；隔离公共 API 测试检查原生未认证时不会放行。AuthMe 当前完成公开 API 与事件回归，未完成这些实服组合的验证。

## 跨版本行为

| 项目 | 处理方式 |
| --- | --- |
| 玩家在线列表 | 自动适配旧版数组和新版集合返回值 |
| 玩家生命值 | 自动适配旧版整数与新版浮点返回值 |
| 玩家延迟 | 核心有可用 API 时上报；旧版没有时省略，不填虚假数值 |
| UUID | 有原生 UUID API 时使用原值；更早的核心按玩家名生成稳定的旧版标识 |
| 封禁与解封 | 按能力使用档案封禁、名字封禁或旧版接口，并核对执行结果；管理处罚自动解封须同时匹配封禁来源 `StarBridge` 与原处罚原因，校验失败保留封禁 |
| 登录事件 | 按核心能力注册拾取、编辑书本、副手切换、背包拖动等事件，避免引用旧核心没有的事件类 |
| 正版白名单 | 在后台查询官方身份，校验玩家名及可用的 UUID；任务过期、查询失败或身份不符时不会写入 |
| JSON 库 | 插件独立打包并隔离 Gson，避免依赖服务端自带的版本 |
| Folia 调度 | 全局与实体任务分别调度；停止时取消待执行任务，玩家离线与调度失败不误报执行成功 |

旧版按名字生成的标识不等于 Mojang 正版 UUID；改名或升级到支持原生 UUID 的核心可能改变标识。迁移时由管理员核实玩家档案、QQ 绑定和游戏账号关联，不能按同名自动合并身份。旧核心可能无法恢复历史最后登录时间，面板以现有上报记录为准。

为了让旧核心加载同一份 JAR，插件不指定只在较新核心上可用的 `api-version`。新版核心可能输出 legacy plugin / 未声明 API 版本提示；这是所用兼容加载方式的提示，应结合插件启用结果与桥接状态判断是否成功。字段含义见 [Spigot plugin.yml 说明](https://www.spigotmc.org/wiki/plugin-yml/)。

未登录限制不会因缺少新版事件而直接放行。密码登录还需要能够关闭核心原生密码命令回显；该能力不可用时拒绝启用密码登录，可检查核心版本或仅启用 QQ 登录。第三方兼容模式还要求原插件具有所需公开 API，游戏版本兼容不代表所有登录插件版本都可用。

另外提供 Forge **1.7.10 / 1.12.2 / 1.16.5 / 1.18.2 / 1.19.2 / 1.20.1** 和 NeoForge **1.20.4 / 1.20.6 / 1.21.1 / 1.21.4 / 1.21.8 / 1.21.11 / 26.1.2 / 26.2** 服务端模组，各自使用独立 JAR，安装与 Java 选择见 [Forge 与 NeoForge 游戏端](mod-game-ends.md)。NeoForge 1.20.4 使用 Java 17，1.20.6 与 1.21.x 使用 Java 21，26.1.2 / 26.2 使用 Java 25；仅提供正式构建。Fabric 提供 **1.16.5 / 1.18.2 / 1.19.2 / 1.20.1 / 1.21.1 / 1.21.8 / 1.21.11 / 26.1 / 26.2 / 26.3** 独立 JAR，详见 [Fabric 游戏端](fabric-game-ends.md)；1.21.x 使用 Java 21，26.x 使用 Java 25。模组放在 `mods/`，使用内置或自动登录引擎，不同加载器不能混装。Folia 使用本文的 Bukkit 插件；基岩版原生核心不在支持范围内。

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
.\bridge\test-scheduler.ps1
.\bridge\test-game-login-folia.ps1
.\bridge\test-login-adapters.ps1
.\bridge\test-compatibility.ps1 -RuntimeJavaHome 'C:\Java\jdk8'
```

`RuntimeJavaHome` 指向已有的 Java 8 环境；不传时使用构建 JDK。兼容测试默认检查 Spigot 1.8.8，可通过 `-ApiJars` 传入其他官方 API JAR 路径。历史 API 的来源和新版下载校验值记录在 `bridge/compatibility-matrix.json`。网络测试只连接本机临时 HTTP 服务，不发送邮件或 QQ 测试消息。

出现 `UnsupportedClassVersionError` 时先确认实际加载的是通用构建，并核对启动 Java；出现 `NoSuchMethodError` 或 `NoClassDefFoundError` 时保留核心完整版本、Java 版本和堆栈，再定位未覆盖的 API 差异。
