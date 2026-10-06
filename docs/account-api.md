# 星桥账号注册与网站 API

版本：`v1`。星桥负责邮件验证与社区账号创建，QQ 和网站共享账号库。群内用文字反馈，无需图片渲染或显卡。

## 配置注册

管理面板「成员 → 注册账号」中填写 SMTP 主机、端口、加密方式、发件邮箱、登录账号和授权码，打开注册开关并单独保存。默认关闭，保存不会发信，用户申请后才发送验证码。配置保存在配置目录下 `data/registration-settings.json`，立即生效。

支持 SSL / TLS 和 STARTTLS，校验证书，不使用明文 SMTP。[Python SMTP 接口说明](https://docs.python.org/3/library/smtplib.html)。请按邮件服务商要求填写端口与授权码。

默认验证码有效 5 分钟、错误最多 5 次、重发间隔 60 秒、每小时最多 60 封，可在面板调整时间和邮件额度。每个来源 IP／QQ 用户 10 分钟最多申请 5 次。限流与验证码摘要保存在 SQLite，重启不清空。保存注册设置会使旧验证码失效。

## 群命令

```text
/申请 Steve 123456789
/注册 012345
```

QQ 号必须与申请人一致，验证码发到 `QQ号@qq.com`。只支持已关联的群；必须由原申请人，在原服务器关联的原群确认验证码。参数缺失、验证码错误／过期、邮件失败会显示具体文字提示。验证码、访问令牌和 SMTP 授权码不发到群里。

注册创建的是社区账号。游戏绑定仍使用游戏 `/qbind` 和群 `绑定 验证码`，不根据玩家名猜测 UUID。游戏登录默认关闭；启用后可使用注册密码或绑定 QQ 确认，参见 [游戏登录接入](game-login.md)。注册本身不修改存档或白名单。

## 注册网页与网站接入

内置页面为 `/register`，例如 `http://127.0.0.1:8088/register`。填写玩家名、邮箱后验证，网页自动保存本次申请编号。页面关闭后，可从验证码邮件中复制申请编号继续验证。

API 根地址：`https://你的星桥域名/api/v1`。浏览器跨站接入需在面板「允许接入的网站来源」填写精确来源，例如 `https://community.example.com`，只包含协议、域名、可选端口。不能使用路径或通配符；同源页面默认可用。支持 CORS 预检；CORS 不替代邮件验证，也不能阻止非浏览器客户端调用公开注册接口。

上线使用 HTTPS。反向代理下默认按实际连接来源 IP 限流，不信任客户端自填的 X-Forwarded-For，需按部署规模调整邮件总额度。网站后端 API 密钥不要放在浏览器代码中。

完整浏览器示例：`examples/website-registration.js`，可从面板下载。

## 公开接口

请求使用 `Content-Type: application/json`。所有响应禁止缓存，下面路径相对 `/api/v1`。

### 查看状态

`GET /registration/info` 返回：

```json
{"enabled":true,"site_name":"星桥社区","code_minutes":5,"website_url":"https://community.example.com/register"}
```

不返回邮件配置或密钥。

### 申请验证码

`POST /registration/request`

```json
{"player":"Steve","email":"123456789@qq.com"}
```

玩家名为 3–16 位 ASCII 字母、数字、下划线，忽略大小写去重；邮箱是有效 ASCII 邮箱地址，忽略大小写去重。数字 QQ 邮箱自动记录对应 QQ 号，其他邮箱的 QQ 字段为 null，不接受额外的 QQ 字段。

SMTP 接受邮件后返回 HTTP 202：

```json
{"challenge_id":"随机申请编号","player":"Steve","email":"123456789@qq.com","expires_in":298,"message":"验证码已发送，请检查邮箱"}
```

保存 `challenge_id` 用于验证。验证码不在 API 或日志中返回，只通过邮件发送。有效申请预留玩家名和邮箱，避免并发重复注册。SMTP 接受不保证收件箱立即收到，请检查垃圾邮件。

### 重发

`POST /registration/resend`

```json
{"challenge_id":"上一次的申请编号"}
```

仅接受网页申请编号，受到重发冷却与邮件额度限制。返回新申请编号，请更新表单；旧编号与验证码失效。群申请在原群重新发送 `/申请`。

### 验证并注册

`POST /registration/verify`

```json
{"challenge_id":"申请编号","code":"012345","password":"Example Password 123"}
```

验证码必须为 6 位数字字符串，保留前导零。password 为 8–128 字符，禁止控制字符，保留空格；内置注册网页要求设置密码。API 为兼容旧网站可省略 password，此时用户应通过邮箱设置密码或用实际绑定 QQ 登录。网页只能确认网页申请。成功返回 HTTP 201：

```json
{
  "account":{"id":"社区账号 UUID","player":"Steve","email":"123456789@qq.com","qq":"123456789","created":1790000000.0,"has_password":true},
  "access_token":"随机用户短期令牌",
  "token_type":"Bearer",
  "expires_in":3600
}
```

创建账号、消费验证码和生成令牌在同一事务完成。验证码只用一次。`account.id` 是社区账号 ID，不是 Minecraft UUID。

用户令牌只用于读取本人信息，有效一小时，数据库仅保存摘要。它不授予游戏登录权限；网站后端可验证短期令牌后建立自己的会话，不要直接相信浏览器提交的账号 ID／邮箱。当前没有网站密码登录或令牌续期接口；游戏密码验证由可信游戏插件调用。群注册不会把令牌发到群中。所有公开账号响应只显示 has_password，不返回密码或其哈希。

### 设置 / 重置游戏密码

内置网页 `/account-password`。以下路径相对 `/api/v1`，使用和注册相同的精确 CORS 来源配置，POST 需要 application/json。

| 方法 | 路径 | 正文 / 返回 |
| --- | --- | --- |
| GET | `/account/password/info` | available、min_length、max_length |
| POST | `/account/password/request` | `{ "player":"Steve", "email":"123456789@qq.com" }` → HTTP 202、challenge_id、expires_in、message |
| POST | `/account/password/verify` | `{ "challenge_id":"编号", "code":"012345", "password":"Example New Password 123" }` → message |

玩家名与原注册邮箱匹配时才发送邮件；不匹配也返回通用申请响应，防止直接查询账号邮箱。使用注册 SMTP 配置，关闭新用户注册后仍支持老账号设置密码。验证码最多五次错误、一次有效；修改成功撤销账号短期令牌和现有游戏会话，不改变游戏 UUID 关联。密码哈希在受限线程计算，不阻塞网站事件循环。

### 本人账号

`GET /account`，请求头 `Authorization: Bearer <access_token>`，返回 `{ "account": { ... } }`。

## 网站后端只读接口

面板生成独立的「网站后端 API 密钥」并保存；留空则关闭查询。

`GET /accounts/<account_id>`，请求头 `Authorization: Bearer <网站后端 API 密钥>`，返回 `{ "account": { ... } }`。

密钥只能按 ID 查询账号，不能管理玩家、修改主程序或读取 SMTP 设置。轮换后旧密钥立即失效。它不是用户令牌，不可交给普通网页用户。

## 管理接口

需要 `Authorization: Bearer <面板管理令牌>`，路径相对主程序根地址：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/registration/settings` | 读取完整设置及 revision |
| PUT | `/api/registration/settings` | 提交 `{ "settings": { ...完整配置... }, "revision": "..." }` |
| GET | `/api/registration/accounts?q=Steve&page=1` | 搜索玩家名、邮箱、QQ，每页 25 条 |
| GET | `/api/registration/guide` | 下载本文档 |
| GET | `/api/registration/example` | 下载网站接入示例 |

revision 防止旧页面覆盖新设置。只有管理员配置接口返回 SMTP 授权码，不应公开。

## 错误

公开 API 失败正文为 `{ "error": "可读说明", "code": "错误类型" }`。

| HTTP | 常见 code | 处理 |
| --- | --- | --- |
| 400 | invalid_request、code_invalid | 检查参数或验证码 |
| 401 | token_invalid、api_token_invalid | 凭证错误或过期 |
| 403 | origin_forbidden | 添加正确网站来源 |
| 404 | application_missing、account_missing | 申请／账号不存在或不属于当前渠道 |
| 409 | account_exists、application_pending、code_used、settings_changed | 检查已有申请，勿循环重复创建 |
| 410 | code_expired | 重新申请／重发 |
| 415 | content_type_invalid | 使用 JSON 请求头 |
| 429 | rate_limited、code_locked | 等待冷却或申请过期 |
| 502 | mail_failed | 检查 SMTP，未创建账号 |
| 503 | registration_disabled | 注册未开放 |

邮件超过 30 秒未完成时申请失败；即使稍后收到邮件，该次验证码也不生效。API 客户端可使用 45 秒请求超时。关闭注册不删除已有账号，网站后端查询与未过期的本人访问令牌仍有效。

## 验证与性能

自动测试使用模拟 SMTP、模拟 OneBot，不向真实用户发邮件或群消息。真实验证需要填写自己的 SMTP 配置，QQ 流程还需要已连接的 OneBot 与已关联群。

注册使用现有 aiohttp、SQLite 和 Python 标准库，无新增依赖。发信在后台线程执行，同一实例最多同时发两封，避免阻塞网页事件循环。网页没有持续动画或 GPU 渲染。
# 社区官网与玩家信息

星桥社区官网是独立的纯静态项目，支持密码登录、所有服务器状态和本人档案，另提供公开玩家信息 API。面板「接入空间 → 网站绑定」可接入网站、自动授权准确来源、下载独立项目与接入配置，并调整内容及公开范围。新增接口包括 `/api/v1/community/info`、`/api/v1/servers`、`/api/v1/players`、`/api/v1/players/{uuid}`、`/api/v1/account/login`、`/api/v1/account/logout`、`/api/v1/me/profile` 与网站后端专用 `/api/v1/accounts/{account_id}/profile`。详细字段及部署方式见 [官网部署与信息接口](website-deployment.md)。现有注册接口保持兼容。
