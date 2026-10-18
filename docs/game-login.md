# VexBot 游戏登录

原登录插件的“忘记密码”请使用独立的[QQ 密码找回](native-password-reset.md)，支持 AuthMe、LimboAuth 和 LibreLogin，默认关闭。它与本页的进服登录开关分别配置。

适用：**VexBot 0.6.28 · 游戏插件 0.5.5 通用兼容构建**。Spigot / Paper / Folia 使用同一个 JAR，插件最低 Java 8，服务端及第三方插件按自身要求使用 Java。具体检查范围与差异见 [Minecraft 版本兼容](minecraft-compatibility.md)。Paper / Spigot 可选择下面列出的登录插件，LibreLogin 使用普通 Paper；Folia 使用 VexBot 内置登录。

**Forge / NeoForge** 按 Minecraft 版本下载独立 JAR，放在 `mods/`，连接配置放在 `config/`。只支持内置或自动引擎；密码、QQ 确认与 `/l`、`/ql` 使用方式相同。支持版本、Java 要求和安装步骤见 [Forge 与 NeoForge 游戏端](mod-game-ends.md)。

**Fabric** 同样按 Minecraft 版本选择独立服务端 JAR，统一使用 `config/starbridge-bridge.properties`，无需 Fabric API 或 VexBot 客户端模组。密码、QQ 确认与未登录限制采用相同流程；只支持内置或自动引擎，安装与 Java 要求见 [Fabric 游戏端](fabric-game-ends.md)。

## 这篇文档解决什么

游戏登录用于在玩家进服后确认账号所有权：验证成功前限制游戏操作，验证成功后才放行。社区注册、QQ 绑定和白名单分别管理账号、身份对应关系和入服资格；开启其中一项不会自动开启其他项。首次接入先完成 [快速开始](quick-start.md)，注册流程见 [账号注册](account-api.md)，QQ 绑定见 [账号绑定](account-binding.md)。

新服没有其他登录插件时，先按下面的内置流程验证一个测试账号；已有 AuthMe、nLogin、LoginSecurity 或 LibreLogin 的服，先阅读 [可选登录插件](#可选登录插件) 中对应的首次关联步骤，再启用登录。

## 开启前准备

- Bot 已启动，目标服务器已出现在面板中，游戏桥接显示在线。插件首次同步策略前会限制操作，不能只启动游戏服。
- 准备一个已注册的测试玩家名和可收信的邮箱。网页注册时设置密码；群注册的账号先在 `/account-password` 设置密码。
- 使用 QQ 登录时，先完成该服务器的实际 QQ 绑定，并确认 [OneBot 已连接且可以私聊](onebot-connection.md)。密码登录本身不要求 OneBot 在线。
- 备份 Bot 数据及游戏服目录；已有第三方登录插件时保留它的账号库和 VexBot 可信关联文件。备份范围见 [备份与恢复](backups.md)。

## 配置与开启

1. 从面板「成员 → 游戏登录」下载新版 JAR，替换游戏服务器旧的 VexBot JAR，保留原连接配置并重启服务器。
2. 在「成员 → 注册账号」配置 SMTP，开放注册。网页 `/register` 验证邮箱时同时设置游戏密码。群里注册的旧账号在 `/account-password` 验证注册邮箱后设置密码。
3. 在「成员 → 游戏登录」勾选需要登录的服务器，选择登录引擎与密码 / QQ 登录方式，保存。默认不勾选任何服务器。没有第三方登录插件的单服可先选择「VexBot 内置」并启用密码登录；已有登录插件或混合加载器部署按下表选择。

只开放 QQ 登录时，先核对已有绑定；未绑定玩家无法在待登录状态执行 `/qbind`，应先允许密码登录或由管理员核实身份后绑定。社区账号 ID 与 Minecraft UUID 分开。第一次验证成功建立该账号在该服务器的 UUID 关联，后续不同 UUID 不能冒用同名账号。

| 登录引擎 | 行为 |
| --- | --- |
| 自动 | 没有已适配的登录插件时使用内置限制；只有一个已启用插件时自动选择；两个及以上拒绝放行 |
| VexBot 内置 | 用于没有第三方登录插件的服务器；检测到下面任一个已启用插件时拒绝放行 |
| AuthMe 兼容 | 仅 Paper / Spigot；需要自行安装支持 API v3 的 AuthMe，缺失或 API 不可用时拒绝放行 |
| nLogin 兼容 | 仅 Paper / Spigot 后端服；需要支持 Identity API 的 nLogin，不能把代理端 nLogin 当作本服登录插件 |
| LoginSecurity 兼容 | 仅 Paper / Spigot；需要 LoginSecurity 3.x 公开会话与异步 Action API |
| LibreLogin 兼容 | 仅普通 Paper / Java 21，首次完成原插件注册登录；0.24.0 Paper 拒绝带 TOTP 密钥的账号 |

同一游戏服只启用一个登录插件。即使明确选择某个引擎，同时检测到两个已启用的已适配插件也会拒绝登录；指定插件缺失、API 不匹配或选择未知引擎时不会自动放行。未列出的登录插件和独立登录模组尚未适配，不要与 VexBot 内置认证同时启用。登录引擎是 Bot 的统一设置；同时接入 Bukkit 和模组服时选择「自动」，Bukkit 自动识别本服插件，模组服使用内置引擎。

服务器、登录方式、时限、尝试次数、QQ 确认有效期与请求间隔均在面板调整。保存会使现有游戏会话失效，在线玩家需要重新验证；无需手改登录设置文件。插件首次启动需成功同步 VexBot 策略才能知道某服务器未启用认证，同步前暂时限制操作；应先启动主程序并保持桥接可达。

### Folia 服务器

从面板下载 **Paper / Spigot / Folia 插件**，放入 `plugins/`，保留 `plugins/StarBridge/config.yml`，使用 Folia 自身要求的 Java；1.21.8 正式 build 6 使用 Java 21。选择「VexBot 内置」或「自动」，不要安装第三方登录插件。Folia 上启用 AuthMe、nLogin、LoginSecurity 或 LibreLogin，或明确选择第三方兼容引擎时，VexBot 拒绝放行并在游戏日志说明原因；插件自身声明支持 Folia 不表示其登录 API 已具备 VexBot 需要的区域线程契约。

Folia 的登录回复、策略变更与超时检查在玩家所属实体线程处理，跨区域移动、退出重连和晚到的确认结果不会沿用旧连接。安装、升级或移除认证插件时完整停止并重启服务器，不使用热卸载或运行中强制停用。面板登录设置可以正常保存应用。具体实测版本与操作范围见 [Folia 接入](minecraft-compatibility.md#folia-接入)。

## 玩家操作

```text
/login <网页注册或邮箱重置时设置的密码>
/l <同一密码>
/qqlogin
/ql
/logout
```

`/l` 是 `/login` 的简写，`/ql` 是 `/qqlogin` 的简写，两者分别使用相同的验证与限流流程。也支持 `/starbridge:l` 和 `/starbridge:ql`。密码 8–128 字符，保留空格，禁止控制字符。未登录时限制移动、传送、聊天、其他命令、方块与物品操作、背包操作和伤害；超时断开连接。每次重连需重新登录，旧连接的异步结果不会放行新连接。

`/qqlogin` 把服务器名、玩家名、本次 IP 和一次性确认指令私聊给**实际绑定**的 QQ。收件人可私聊回复 `/确认登录 <确认串>` 或 `/拒绝登录 <确认串>`。群内回复不会确认；确认串有时限、一次有效，重连和绑定变化后失效。必须连接 OneBot，且机器人能私聊该 QQ；私聊失败不会改成群发，也不会自动登录。不需要 QQ 邮箱与网页密码账号一致来确认旧绑定；有身份冲突时由管理员核对，不能以新注册的同名账号覆盖旧绑定。

旧账号或忘记密码：打开 `/account-password`，填写已注册玩家名与原邮箱，收到验证码后设置新密码。修改成功撤销旧游戏会话和社区短期令牌，不删除游戏 UUID 关联。关闭新用户注册后，已配置的密码重置邮件仍可用。

## 第一次成功登录与验收

下面以没有第三方登录插件、已启用密码登录的测试服为例：

1. 用注册时的玩家名进服，确认出现登录提示，暂时不能移动、聊天或操作物品。
2. 在游戏命令栏输入 `/l <注册时设置的密码>`，例如测试密码为 `Example Password 123` 时输入 `/l Example Password 123`。密码中的空格保留，不加引号。
3. 确认游戏提示登录成功，移动、聊天与背包操作恢复；面板「成员 → 注册账号」出现该服务器关联。
4. 退出再进服，确认仍需重新验证。测试账号第一次验证建立服务器 UUID 关联，以后同名但不同 UUID 的连接不能直接沿用。
5. 若同时启用 QQ 登录，重新进服输入 `/ql`，在绑定 QQ 的机器人私聊中回复收到的 `/确认登录 <确认串>`，确认放行；再测试一次拒绝或过期确认不会放行。

第三方引擎需要同时完成 VexBot 证明和对应原插件认证；只收到 VexBot 验证成功的提示，不代表原插件已经完成登录。nLogin 必须用 `/starbridge:l` 或 `/starbridge:ql` 完成 VexBot 步骤，再按原插件提示登录。详细命令见下一节。

## 常见问题

| 现象 | 检查与处理 |
| --- | --- |
| 进服一直受限，提示认证服务不可用 | 先确认 Bot 正在运行、桥接地址与本服 Bearer 密钥一致、桥接心跳在线；再查看游戏日志中的引擎或策略同步错误 |
| 提示账号不存在、没有密码或密码错误 | 确认使用注册玩家名；群注册账号先通过原邮箱在 `/account-password` 设置密码，密码保留空格 |
| VexBot 验证通过，仍不能操作 | 查看原登录插件提示；已有账号首次关联仍需原密码或有效原生会话，二次验证也必须完成，不要删除关联文件来尝试放行 |
| `/login` 进入了 nLogin 的流程 | 使用 `/starbridge:login` 或 `/starbridge:l` 完成 VexBot 验证，并合并本页 nLogin 命令白名单 |
| `/ql` 没有私聊或确认无效 | 检查本服绑定、OneBot 私聊能力、确认时限和当前连接；确认只在机器人私聊有效，重连后重新请求 |
| 只开放 QQ 登录，新玩家无法绑定 | 待登录状态不能执行 `/qbind`；先允许密码登录完成绑定，或由管理员核实身份后绑定 |
| 更换正版 / 离线模式后提示身份不符 | 先核实玩家所有权与 UUID 变化，再按 [账号关联管理](#账号关联管理) 重置 VexBot 关联；原登录插件的身份校验独立处理 |
| 保存设置后在线玩家重新需要登录 | 保存会撤销旧游戏会话；等待桥接心跳收到新策略后按新设置验证 |
| Folia 提示第三方登录引擎不支持 | 使用「VexBot 内置」或「自动」，移除第三方登录插件后完整重启，按 [Folia 服务器](#folia-服务器) 检查 |

登录成功后继续配置 [消息互通](message-sync.md)、[玩家管理](player-management.md) 和 [群命令](group-commands.md)。这些功能是否可用还取决于各自开关、绑定和权限。

## 可选登录插件

本节只用于普通 Paper / Spigot，LibreLogin 需要 Paper。登录插件由服主自行安装，不打包进 VexBot；游戏版本可加载 VexBot JAR，不代表任意版本的第三方登录插件都能接入。

所有适配器均要求本次 VexBot 密码或绑定 QQ 的证明和原插件认证状态同时成立才解除 VexBot 限制。原插件可能先于 VexBot 处理自己的登录或注册，原生成功本身不能解除 VexBot 门禁。已有原账号且未保存可信关联时，仍需原插件密码或其有效认证会话；网页注册一个同名账号不能覆盖原密码或直接接管原账号。AuthMe、LoginSecurity、LibreLogin 分别使用 `authme-links.properties`、`loginsecurity-links.properties`、`librelogin-links.properties`，保存在 `plugins/StarBridge/`，只记录原插件验证过的玩家名与 UUID，不保存密码，各插件的信任不能互相替代。nLogin 每次采用原生认证，不创建可跳过它的可信关联。保留关联文件并单独备份游戏服目录。

### AuthMe

通过 [AuthMe 官方 API v3](https://github.com/AuthMe/AuthMeReloaded/blob/5.7.0/src/main/java/fr/xephi/authme/api/v3/AuthMeApi.java) 接入；不打包 AuthMe、本节的登录流程不读取或改写其已有密码；单独启用的原生密码找回按本人私聊确认执行。VexBot 确认密码或 QQ 后请求登录，并等待 `isAuthenticated` 变为真才放行，不能把异步调用已提交当成登录完成。

没有 AuthMe 账号的玩家，API 创建一个带随机内部凭证的 AuthMe 账号，再登录。用户日常输入的仍是 VexBot 密码，密码哈希保存在 VexBot 数据库；不会把 VexBot 密码复制到 AuthMe。

**安装 AuthMe 前已存在的账号**首次关联需要两份证明：先完成 VexBot 密码或 QQ 确认，再使用 `/authme:login <原 AuthMe 密码>`，或由 AuthMe 自身恢复有效会话。核实后在游戏插件目录 `authme-links.properties` 保存玩家名和 UUID，后续可直接用 VexBot 密码 / QQ 登录。它不保存密码。这样网页抢注同名账号无法接管既有 AuthMe 账号。新服务器没有这一额外步骤。

已有账号首次关联时若 AuthMe 要求二次验证，原密码后仍须完成其 TOTP / verification / captcha，使用对应的 `/authme:totp`、`/authme:verification`、`/authme:captcha` 命令；VexBot 保持操作限制直到 AuthMe 报告认证完成。仅在本次 VexBot 验证通过且正在关联时允许这些固定命令。完成关联后的 AuthMe 接入保留公开 `forceLogin` 行为，不把它描述为每次重新执行 AuthMe 的全部原生验证步骤。

保留这份关联文件。若关闭 VexBot 认证，AuthMe 将恢复使用自己的登录方式；自动创建账号的内部随机密码不是网页密码。关闭前应通过 AuthMe 自己的账号管理为玩家建立可用凭证，不能假定两个密码库已同步。

AuthMe 仍可能因注册限制、账号封禁或其登录超时拒绝请求，应检查其配置。AuthMe 组合当前验证包含编译与隔离 API / Bukkit 事件测试，未完成所有 AuthMe 插件组合的实服验证；这与 [Folia 内置登录验证](minecraft-compatibility.md#已完成哪些验证) 分开记录。

### nLogin

使用 [nLogin 官方公开 API](https://docs.nickuc.com/nlogin/development/usage/)，本次适配目标为 **nLogin 2.0.24 / Identity API 2.0** 的 Bukkit 后端原生模式。网站说明中的其他 API 版本不自动视为已验证；实际缺少所需方法时拒绝接入，不猜测旧接口。

每次连接先用 `/starbridge:login <网站密码>` 或 `/starbridge:ql` 完成 VexBot 证明，再按 nLogin 提示使用原生 `/login <nLogin 密码>`；新账号使用 `/register <密码> <确认密码>`。nLogin 已恢复有效会话时可以复用其认证结果，仍须本次 VexBot 证明。需要邮箱或 Discord 确认时继续完成原插件流程。普通 `/login` 和 `/l` 会被 nLogin 接管，第一步必须明确使用保留的 `starbridge:` 命名空间；默认 nLogin 不提供 `/nlogin:login` 或 `/nlogin:register`，不要依赖这些指令。

当前适配采用原生认证观察，VexBot 不自动注册或修改 nLogin 密码，不调用 `requestLogin` 或 `forceLogin` 代替原生证明，也不把 API 请求提交当作认证完成。原账号 UUID 必须与这次游戏连接一致，缺失或不符时拒绝认证，不按同名合并。

先完成 nLogin 自己的首次初始化向导，再参考 [官方配置模板](https://docs.nickuc.com/nlogin/config/template/) 在 `plugins/nLogin/config.yml` 的现有配置中合并以下值，完整重启游戏服。下面字段按本次实测的 2.0.24 生成配置，旧官网模板的层级可能不同；保留已有白名单，不要直接替换整份配置：

```yaml
commands:
  allowed-commands:
    - /login
    - /l
    - /qqlogin
    - /ql
    - /starbridge:login
    - /starbridge:l
    - /starbridge:qqlogin
    - /starbridge:ql
ui:
  remove-chat-messages: false
```

这些白名单只让 VexBot 验证指令和提示能够到达，未验证玩家仍受 VexBot 限制。实服客户端使用 `ui.show-dialogs: NONE` 关闭原生登录对话框，方便使用命令；是否关闭由服主选择。原生账号可能在 VexBot 验证前注册或登录，VexBot 只有看到两端证明都成立才放行，不保证拦截 nLogin 自己的账号创建。

原 API 没有可用的公开退出接口，执行 `/logout` 会断开连接，重新进服再验证；不会假装原插件会话已经退出。代理模式不在此适配范围内。

### LoginSecurity

按 [LoginSecurity 官方 3.x 会话 API](https://github.com/lenis0012/LoginSecurity) 接入。新账号用随机内部凭据调用异步注册 Action，注册成功后继续 Login Action，待原插件恢复登录状态及背包后才放行。已存在且未关联账号需先完成 VexBot 证明，再用 `/loginsecurity:login <原插件密码>` 验证原身份。

原插件关闭新账号注册或启用注册验证码时，VexBot 不会绕过限制；先在启用 VexBot 游戏认证前完成原插件注册，或按原插件自己的设置调整注册流程。注册或登录失败会保留操作限制并说明原因。`/logout` 会断开连接，让原插件按退出流程结束本次会话。

### LibreLogin

使用 [LibreLogin 0.24.0 官方发行版](https://github.com/kyngs/LibreLogin/releases/tag/0.24.0) 的公开 API，仅接入安装在本游戏服的 Paper 插件，不接入代理端或 Folia。本次实服组合为 Paper 1.21.4 正式 build 232 / Java 21；LibreLogin 自带组件对其他 Minecraft 版本的兼容不能由 VexBot JAR 推断。

首次使用先完成 VexBot 密码或 QQ，再按原插件提示用 `/librelogin:register` 注册新原生账号，或用 `/librelogin:login` 登录已有账号。本节的登录流程不设置或覆盖 LibreLogin 密码；单独启用的原生密码找回按本人私聊确认执行；原插件认证成功后建立可信关联。后续同一 UUID 且未启用 TOTP 的已关联账号，可以使用 VexBot 密码或 QQ 请求原插件授权。

启用 TOTP 的账号每次仍需 LibreLogin 原生密码及二次验证流程，VexBot 不会自动授权绕过它。本次检查的 LibreLogin 0.24.0 Paper 端没有可用 TOTP 校验器，带动态验证码密钥的账号会被拒绝；不能把原生授权标记当成已完成二次验证。待关联状态只允许原插件固定登录、注册与二次验证命令，不能借此执行管理指令。执行 `/logout` 会断开连接，重新进服后开始新的认证。

### 接入与检查范围

| 插件 / 接口 | 核心 | 首次验证 | 当前验证范围 |
| --- | --- | --- | --- |
| AuthMe API v3 | Paper / Spigot | 已有账号原密码或有效原生会话 | 公开 API 反射、隔离事件与异步认证回归 |
| nLogin 2.0.24 / Identity API 2.0 | Paper / Spigot 后端 | 每连接原生验证或有效原生会话，再核对 VexBot 证明 | 25 项隔离检查，free 版 / Paper 1.21.8 build 60 实服 16 项；Premium 二次验证未实服检查 |
| LoginSecurity 3.3.1 会话 / Action API | Paper / Spigot | 已有账号原密码或有效原生会话 | 47 项隔离检查，Paper 1.21.8 build 60 实服 23 项 |
| LibreLogin 0.24.0 / Java 21 | 普通 Paper | 首次原生注册或登录；本版 Paper 拒绝带 TOTP 密钥的账号 | 35 项隔离检查，Paper 1.21.4 build 232 实服 26 项 |

第三方登录插件可能有自己的用户名策略、超时、注册限制、IP 限制及会话恢复方式，仍以原插件配置为准。以上不会扩展为全部历史版本、代理平台或所有插件组合的实服保证。Folia 仅支持 VexBot 内置登录；Forge / NeoForge / Fabric 仍仅使用自动或内置引擎。

## 账号关联管理

「成员 → 注册账号」显示是否设置密码和关联服务器。管理员核实 UUID 变化后可点「重置关联」，撤销当前游戏会话，允许下次验证重新关联。该操作不改 QQ 绑定、存档、封禁或白名单，也不重置原登录插件的可信关联；已有原账号的首次所有权校验仍独立生效。

## 接口与性能

游戏端使用服务器专属 Bearer 密钥调用 `POST /bridge/{sid}/auth`。正文包含 `action`（join / password / qq / leave）、`uuid`、每次连接随机 UUID `nonce`、`player`、`ip`；password 操作额外包含 `password`。返回 nonce、设置 revision、status、message、expires_in。每秒心跳携带 `auth_sessions`，返回认证策略与本次连接结果。服务器密钥只授予可信游戏服务端，网站 API 密钥与用户短期令牌不能调用此接口。

管理员接口：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET / PUT | `/api/authentication/settings` | 读取或提交完整 settings 与 revision |
| DELETE | `/api/authentication/account-links/{account_id}` | 重置账号的游戏 UUID 关联 |
| GET | `/api/authentication/guide` | 下载本文档 |

`settings` 包含 enabled_servers（服务器 ID 列表）、login_engine（auto / builtin / authme / nlogin / loginsecurity / librelogin）、password_login、qq_login、login_seconds（30–600）、qq_seconds（30–300）、max_attempts（1–10）、qq_cooldown（15–300）。保存采用版本检查，旧页面冲突返回 409，未知引擎返回 400 且不改变现有设置与会话。成功保存登录引擎会撤销旧游戏会话，并在桥接心跳中下发所选值；各游戏端再按自身平台与插件 API 拒绝不兼容配置。读取失败时拒绝认证而非自动关闭。

密码使用随机盐与 PBKDF2-HMAC-SHA256 600,000 次，参考 [OWASP 密码存储指南](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)。哈希在两个受限后台线程执行，忙时拒绝额外工作；游戏 HTTP 也用两个线程与固定队列，不阻塞游戏主线程。默认同服务器玩家五分钟最多五次密码尝试，重连不重置；确认串和邮件验证码只保存摘要。待登录会话有容量和过期清理。

游戏端到 VexBot 的连接包含密码，跨机器部署应使用 HTTPS 或可信本地加密隧道；不要通过公网明文 HTTP 传输。游戏认证不可用时新的登录不会放行，已验证连接不会因一次网络抖动立即掉线；管理设置传播依赖正常心跳。

Spigot 会在命令事件之前记录原命令参数。因此 VexBot 运行期间关闭其原生玩家命令回显（包括其他玩家命令），卸载时恢复原值；命令事件中也将 VexBot 登录密码替换成无参数形式。第三方命令日志插件不受这个开关控制，管理员需要检查它们的登录指令脱敏。此保护不依赖显卡。

面板仍使用普通 HTML/CSS、短时过渡与后台暂停轮询；没有新增动画库、图片渲染或 GPU 特效。自动化验证只使用模拟邮件和 QQ，不向真实玩家发送测试消息。
