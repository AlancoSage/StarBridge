# VexBot Velocity 认证兼容端

此插件安装在 **Velocity 3.3+ 代理的 plugins 目录**。它为 LimboAuth 1.1.14 和 LibreLogin 0.24.0 提供原生账号核验、QQ 绑定码及离线密码恢复，不接管 `/login`、注册或两步验证。Java 17+ 可加载本插件；LibreLogin 0.24.0 自身要求 Java 21。

1. 代理只安装一套认证插件，在子服保留原有 VexBot 游戏端连接和状态上报。
2. 首次运行生成 `plugins/myrinbot-velocity/config.properties`。填写机器人的地址、该子服的 `server-id` 与桥接令牌，选择 `engine=limboauth` 或 `engine=librelogin`，设置 `enabled=true` 后重启代理。
3. 在机器人面板为对应服务器开启原生密码恢复，平台选择 Velocity，选择相同认证系统。
4. 玩家先完成原生认证及启用的两步验证，再在代理连接中执行 `/qbind`；代理优先处理此命令。所有玩家均须按提示由自己的 QQ **私聊机器人**发送 `/验证绑定 <服务器ID> <绑定码>`。已绑定的玩家也需由原绑定 QQ 私聊提交新码完成核验，无需解绑；仅执行游戏内命令不会获得密码恢复资格。不要把验证码发到群内或转给别人。群内普通 `绑定 <码>` 仅建立聊天绑定，不授予密码恢复资格。
5. 密码恢复时玩家须离开整个代理。重置只改变当前已绑定且完成核验的原生账号密码，不创建账号、不关闭两步验证，也不修改 VexBot 网站密码。QQ 中的具体用法以机器人帮助为准。

`password-reset-proofs.properties` 只保存 UUID 与原生注册时间的摘要，不保存密码。删除、重新注册同名账号后必须重新完成原生登录、执行 `/qbind` 并由对应绑定 QQ 私聊提交新码。机器人的 QQ 恢复授权也携带同一注册时间摘要；旧授权无法恢复新注册的同名账号。原生数据库缺少账号 UUID、玩家改名、UUID 不符或认证 API 不兼容时会拒绝恢复。不要删除此证明文件或从其他认证系统复制它。

仅支持一个 Velocity 实例持有该认证数据库的部署。LibreLogin 多代理模式会被拒绝；LimboAuth 的共享数据库多代理部署不在支持范围内，无法从一个代理可靠判断其他代理的在线会话。非本机连接建议使用 HTTPS 或受保护的内网。令牌只写入配置，不要提交配置到 GitHub。

实现使用原生公开 API 生成哈希和更新数据库，不把密码拼入控制台指令。重置任务与原文密码只在内存中流转，每个任务仅执行一次，并在写入前向机器人重新核验绑定、配置和有效期；此时拒绝该账号新连接。LimboAuth 清除本代理会话缓存并更新令牌签发时间，LibreLogin 清除旧 IP 与认证时间，两者均保留 TOTP 密钥。

源码接口依据：

- [LimboAuth 1.1.14](https://github.com/Elytrium/LimboAuth/tree/1.1.14)：`LimboAuth`、`RegisteredPlayer`、ORMLite 公共 DAO 和原生强制改密实现。
- [LibreLogin 公共 API](https://github.com/kyngs/LibreLogin/tree/5cae5bd01fa37e45ee1d529bfa5c8eb1dcdc5c58/API)：平台、账号、认证、加密与读写数据库接口。
- [Velocity API](https://docs.papermc.io/velocity/dev/creating-your-first-plugin/)：注入、代理命令及登录事件。

构建与测试（固定依赖 SHA256，不打包第三方认证插件；构建使用 Java 17+，直接加载 LibreLogin 发行 JAR 的测试使用 Java 21+）：

```powershell
python bridge-velocity/build.py --java-home 'C:\Program Files\Java\jdk-21'
python bridge-velocity/test.py --java-home 'C:\Program Files\Java\jdk-21'
```

输出 `bridge/target/VexBot-Velocity-0.1.1.jar`，并生成兼容升级器的 `StarBridge-Velocity-0.1.1.jar` 同字节附件。

测试覆盖正式发行 JAR 的 API 契约、原生 BCrypt 验证、LimboAuth 的真实 ORMLite/H2 数据库更新及会话缓存撤销、LibreLogin 原生账号模型和哈希、账号注册时间证明，以及一次性任务领取、过期、重放、在线和握手连接拒绝、禁止 HTTP 重定向。测试不会启动 Minecraft 客户端；实际客户端端到端登录仍需在目标代理环境中验证。
