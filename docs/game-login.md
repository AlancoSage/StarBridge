# 星桥游戏登录

游戏插件版本：**0.5.0 通用兼容构建**。面向跨版本 Spigot / Paper，插件最低 Java 8，服务端按自身要求使用 Java。具体检查范围与差异见 [Minecraft 版本兼容](minecraft-compatibility.md)。AuthMe 为可选依赖；服务器没有安装时使用星桥内置登录。

## 开启

1. 从面板「成员 → 游戏登录」下载新版 JAR，替换游戏服务器旧的 StarBridge JAR，保留原连接配置并重启服务器。
2. 在「成员 → 注册账号」配置 SMTP，开放注册。网页 `/register` 验证邮箱时同时设置游戏密码。群里注册的旧账号在 `/account-password` 验证注册邮箱后设置密码。
3. 在「成员 → 游戏登录」勾选需要登录的服务器，选择登录引擎与密码 / QQ 登录方式，保存。默认不勾选任何服务器。

只开放 QQ 登录时，先核对已有绑定；未绑定玩家无法在待登录状态执行 `/qbind`，应先允许密码登录或由管理员核实身份后绑定。社区账号 ID 与 Minecraft UUID 分开。第一次验证成功建立该账号在该服务器的 UUID 关联，后续不同 UUID 不能冒用同名账号。

| 登录引擎 | 行为 |
| --- | --- |
| 自动 | 没有 AuthMe 时使用内置限制；安装并启用 AuthMe 后使用 API 兼容 |
| 星桥内置 | 用于未安装 AuthMe 的服务器；检测到 AuthMe 时拒绝放行，提示修改引擎 |
| AuthMe 兼容 | 需要自行安装支持 API v3 的 AuthMe；缺失或 API 不可用时拒绝放行 |

服务器、登录方式、时限、尝试次数、QQ 确认有效期与请求间隔均在面板调整。保存会使现有游戏会话失效，在线玩家需要重新验证；无需手改登录设置文件。插件首次启动需成功同步星桥策略才能知道某服务器未启用认证，同步前暂时限制操作；应先启动主程序并保持桥接可达。其他登录插件尚未提供适配，不要与内置登录同时启用。

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

## 可选 AuthMe

通过 [AuthMe 官方 API v3](https://github.com/AuthMe/AuthMeReloaded/blob/master/authme-core/src/main/java/fr/xephi/authme/api/v3/AuthMeApi.java) 接入；不打包 AuthMe、不读取或改写其已有密码。星桥确认密码或 QQ 后请求登录，并等待 `isAuthenticated` 变为真才放行，不能把异步调用已提交当成登录完成。

没有 AuthMe 账号的玩家，API 创建一个带随机内部凭证的 AuthMe 账号，再登录。用户日常输入的仍是星桥密码，密码哈希保存在星桥数据库；不会把星桥密码复制到 AuthMe。

**安装 AuthMe 前已存在的账号**首次关联需要两份证明：先完成星桥密码或 QQ 确认，再使用 `/authme:login <原 AuthMe 密码>`，或由 AuthMe 自身恢复有效会话。核实后在游戏插件目录 `authme-links.properties` 保存玩家名和 UUID，后续可直接用星桥密码 / QQ 登录。它不保存密码。这样网页抢注同名账号无法接管既有 AuthMe 账号。新服务器没有这一额外步骤。

已有账号启用 AuthMe 二次验证时，原密码后仍须完成其 TOTP / verification / captcha，使用对应的 `/authme:totp`、`/authme:verification`、`/authme:captcha` 命令；星桥保持操作限制直到 AuthMe 报告认证完成。仅在本次星桥验证通过且正在关联时允许这些固定命令。

保留这份关联文件。若关闭星桥认证，AuthMe 将恢复使用自己的登录方式；自动创建账号的内部随机密码不是网页密码。关闭前应通过 AuthMe 自己的账号管理为玩家建立可用凭证，不能假定两个密码库已同步。

AuthMe 仍可能因注册限制、账号封禁或其登录超时拒绝请求，应检查其配置。真实服务器上的插件组合需要联调，当前验证包含编译与隔离 API / Bukkit 事件测试，没有宣称已完成实服测试。

## 账号关联管理

「成员 → 注册账号」显示是否设置密码和关联服务器。管理员核实 UUID 变化后可点「重置关联」，撤销当前游戏会话，允许下次验证重新关联。该操作不改 QQ 绑定、存档、封禁或白名单。AuthMe 已有账号的首次所有权校验仍独立生效。

## 接口与性能

游戏端使用服务器专属 Bearer 密钥调用 `POST /bridge/{sid}/auth`。正文包含 `action`（join / password / qq / leave）、`uuid`、每次连接随机 UUID `nonce`、`player`、`ip`；password 操作额外包含 `password`。返回 nonce、设置 revision、status、message、expires_in。每秒心跳携带 `auth_sessions`，返回认证策略与本次连接结果。服务器密钥只授予可信游戏服务端，网站 API 密钥与用户短期令牌不能调用此接口。

管理员接口：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET / PUT | `/api/authentication/settings` | 读取或提交完整 settings 与 revision |
| DELETE | `/api/authentication/account-links/{account_id}` | 重置账号的游戏 UUID 关联 |
| GET | `/api/authentication/guide` | 下载本文档 |

`settings` 包含 enabled_servers（服务器 ID 列表）、login_engine（auto / builtin / authme）、password_login、qq_login、login_seconds（30–600）、qq_seconds（30–300）、max_attempts（1–10）、qq_cooldown（15–300）。保存采用版本检查，旧页面冲突返回 409。读取失败时拒绝认证而非自动关闭。

密码使用随机盐与 PBKDF2-HMAC-SHA256 600,000 次，参考 [OWASP 密码存储指南](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)。哈希在两个受限后台线程执行，忙时拒绝额外工作；游戏 HTTP 也用两个线程与固定队列，不阻塞游戏主线程。默认同服务器玩家五分钟最多五次密码尝试，重连不重置；确认串和邮件验证码只保存摘要。待登录会话有容量和过期清理。

游戏端到星桥的连接包含密码，跨机器部署应使用 HTTPS 或可信本地加密隧道；不要通过公网明文 HTTP 传输。游戏认证不可用时新的登录不会放行，已验证连接不会因一次网络抖动立即掉线；管理设置传播依赖正常心跳。

Spigot 会在命令事件之前记录原命令参数。因此 StarBridge 运行期间关闭其原生玩家命令回显（包括其他玩家命令），卸载时恢复原值；命令事件中也将星桥登录密码替换成无参数形式。第三方命令日志插件不受这个开关控制，管理员需要检查它们的登录指令脱敏。此保护不依赖显卡。

面板仍使用普通 HTML/CSS、短时过渡与后台暂停轮询；没有新增动画库、图片渲染或 GPU 特效。自动化验证只使用模拟邮件和 QQ，不向真实玩家发送测试消息。
