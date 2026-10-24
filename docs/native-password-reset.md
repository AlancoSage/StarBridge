# 原登录插件密码找回

适用于 Bot **0.6.28**。已绑定 QQ 的原生游戏密码找回默认关闭，调用原登录插件的接口修改密码，不执行包含密码的控制台命令，也不会修改 VexBot 网页密码。

| 登录插件 | 安装位置 | VexBot 配套端 |
| --- | --- | --- |
| AuthMe Reloaded | Bukkit / Spigot / Paper | `VexBot-0.5.6.jar` |
| LibreLogin | 普通 Paper | `VexBot-0.5.6.jar` |
| LimboAuth | Velocity 代理 | `VexBot-Velocity-0.1.1.jar` |
| LibreLogin | Velocity 代理 | `VexBot-Velocity-0.1.1.jar` |

接口验证使用 AuthMe 5.7.0、LibreLogin 0.24.0、LimboAuth 1.1.14 与 Velocity 3.3。其他版本需具备相同公共接口；不兼容时会拒绝提供重置。

Folia 的第三方登录 API、BungeeCord、多代理共享账号数据库和 EasyAuth 不在本次支持范围。同一认证入口只安装一套登录插件；API 不符合要求、身份不一致或有多个找回端实例时，找回端拒绝修改密码。

## 服主配置

1. 更新 Bot 和对应的配套游戏端，完整重启游戏服或代理。
2. 原登录插件由服主自行安装。AuthMe 需要关闭自身的 `settings.sessions.enabled`，然后完整重启游戏服，避免旧 IP 会话绕过新密码；其他登录、安全配置仍由原插件管理。首次安装 AuthMe 生成配置后，也需配置好再重启。
3. 在面板「成员 → 游戏登录 → 找回原登录插件密码」中，选择服务器实际使用的插件和安装位置，保存。此设置独立于 VexBot 的进服登录开关；无需启用两套登录来使用找回功能。
4. 玩家先完成原登录插件的认证，再执行 `/qbind`，使用自己的 QQ **私聊**机器人发送 `/验证绑定 服务器ID 验证码`。已经绑定的玩家也要用原 QQ 私聊确认，无需解绑。游戏内认证和本人 QQ 的私聊确认都完成后才获得改密码权限，旧绑定不会自动升级权限。验证码不要发群或转发；普通群绑定只用于聊天绑定，不授予改密码权限。

仅验证真实登录过的账号：服务端记录 UUID、玩家名与原账号创建信息，Bot 记录对应绑定的创建代次。原账号删除重建、解绑重绑、更换登录插件后，需要重新验证。请保留游戏端的 `password-reset-proofs.properties`；删除它不会泄露密码，但对应账号必须重新验证。

## Velocity 安装

把 `VexBot-Velocity-0.1.1.jar` 放进 **Velocity 的 `plugins/`**，不要放进后端服。需要 Java 17 或更高版本；LibreLogin 自身的 Java 要求另行满足。

首次运行后编辑 `plugins/myrinbot-velocity/config.properties`：

```properties
enabled=true
endpoint=http://127.0.0.1:5800
server-id=survival
token=填写面板中该服务器的桥接令牌
engine=limboauth
```

LibreLogin 使用 `engine=librelogin`。`server-id` 与绑定所在的后端服务器 ID 一致；面板中为该服务器选择对应 Velocity 选项。代理与后端的玩家 UUID 必须一致，不能靠同名关联。跨机器连接请使用可信网络或 HTTPS。

代理提供 `/qbind` 和 `/myrinbot:qbind`，请在原登录插件认证完成后执行。它只负责原生账号验证和密码找回；状态、聊天等功能仍由原有后端桥接负责。更改代理配置后完整重启代理。

同一服务器的认证由代理上的原登录插件负责，请关闭该服务器的 VexBot 内置进服登录，避免同时使用两套连接认证。后端桥接仍可正常上报状态与聊天。

## 玩家使用

先退出游戏，私聊 OneBot 机器人发送：

```text
/重置密码 survival
```

机器人返回所属服务器、玩家名和 120 秒有效的一次性确认指令。在**同一私聊**中将指令最后的“新密码”替换为自己的密码后发送：

```text
/确认重置 一次性标识 新密码
```

新密码为 8–64 位可见 ASCII 字符，不含空格；原插件也会校验自己的密码规则。成功以原插件确认结果为准，提交后不能仅凭“已提交”判断已修改。

在群里发送 `/重置密码` 只会得到私聊使用提示；密码及确认指令不会被机器人转发到游戏或群回复。不要把密码发到群里。

QQ 官机的群用户和单聊用户使用不同的 OpenID，无法凭群绑定安全确认私聊归属，因此此版本仅开放 OneBot 的此项找回。QQ 官机原有的其他功能继续使用；玩家可使用原登录插件自己的找回入口。

## 执行与结果

新密码只短暂保存在 Bot 内存中，最长等待下发 30 秒，不写入 SQLite、审计、普通任务队列或备份。游戏端执行前还需向 Bot 一次性认领，重新检查绑定、设置、桥接令牌和 QQ 接入身份。

任务只下发一次、认领一次；结果不明时不会自动重放。若提示无法确认结果，先检查新密码是否能登录，再决定是否重新申请。相同账号确认重置间隔为 5 分钟。

AuthMe 的改密接口为异步操作。若原插件在时限内没有确认，仍可能稍后完成；找回端会暂停继续提交，并阻止该玩家重新连接。请保持账号离线，联系服主完整重启游戏服，再核对新密码和找回状态。

游戏端只处理离线账号，修改过程中暂时拒绝该玩家的新连接。不注册不存在的账号，不强制登录，不删除 TOTP 密钥。LibreLogin 会清除该账号的原生记住登录状态。恢复备份后会撤销找回权限，玩家需要重新执行经过原生认证的 `/qbind`。

接口来源：[AuthMe 5.7.0 公共 API](https://github.com/AuthMe/AuthMeReloaded/tree/5.7.0/src/main/java/fr/xephi/authme/api/v3)、[LibreLogin 0.24.0 API](https://github.com/kyngs/LibreLogin/tree/0.24.0/API/src/main/java/xyz/kyngs/librelogin/api)、[LimboAuth 1.1.14](https://github.com/Elytrium/LimboAuth/tree/1.1.14)。适配与测试代码由本项目独立实现，原插件不随配套端分发。
