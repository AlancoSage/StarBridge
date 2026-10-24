# 社区官网部署与玩家信息 API

官网接入是可选功能。这篇文档用于选择接入方式、部署独立官网，或在已有网页中调用服务器与账号 API。Bot 首次安装见 [快速开始](quick-start.md)；只需要邮件注册时可直接使用 Bot 的 `/register` 页面，见 [账号注册](account-api.md)。

本文对应 **Bot v0.6.39** 及随包分发的 `VexBot-website.zip`，官网与面板使用同一枚黑白 V 机器人图标。新安装的 Bot 默认内置面板与 API 端口为 **5800**，官网本机预览使用 **8089**；源码中可单独启动的[新版 WebUI 控制台](webui-preview.md)使用 **5801**。已有 Bot 配置保留原端口，接入时使用实际 API 地址。

## 先选择接入方式

| 面板选择 | 适用情况 | 需要完成的事 |
| --- | --- | --- |
| 不接入官网 | 只使用 Bot、游戏服及群功能；新安装默认 | 保持此模式即可，Bot 可独立运行 |
| 使用 VexBot 提供的官网 | 需要现成的首页、服务器状态和玩家账号页 | 下载独立项目、自行部署、填写网站与 API 地址并替换 `config.json` |
| 接入自己的官网 | 已有自己的页面和内容 | 填写网站地址，用本页 API 或 SDK 接入所需功能 |

两种接入方式均需网站地址，使用同一套 HTTP API 和来源授权。选择提供的官网不会自动部署网站；选择自有官网后，页面设计与内容由自己的项目管理，Bot 显示 API 公开范围设置及接口文档。

「不接入官网」保留已保存的网站地址和官网设置，停止允许该网站来源的跨域请求，旧官网入口不再跳转；不会启动、停止或部署外部网站服务。不关闭公共 API、注册功能或撤销用户令牌；其他手动授权来源仍可使用。

### 在新版控制台中设置

服主登录 5801 新版控制台后，进入 **控制台设置 → 网站详细设置**。这里与 5800 内置面板的「接入空间 → 网站绑定」管理同一份后台设置；团队账号不能读取或修改网站管理设置。

| 新版选项 | 显示的详细设置 |
| --- | --- |
| 不接入官网 | 保留已保存的地址、内容和外观；公开 API 三个开关仍可独立调整 |
| 自定义网站 | 网站地址、Bot API 地址、玩家信息 API、公开服务器状态、网站密码登录 API |
| VexBot 官网 | 上述接入配置，以及标题、副标题、社区介绍、规则、游戏地址、群聊链接、主色、辅助色、主题、网格背景 |

修改后点击「保存网站设置」，等待同步成功；下方「保存预览设置」只保存浏览器内的演示偏好。保存成功后可下载接入配置、指南和 SDK；官网项目包仅在「VexBot 官网」模式提供。下载配置前须明确填写并保存 API 地址，修改尚未保存时检查和下载暂时停用。

建议明确填写访客可访问的 `https://bot.example.com/api/v1`，本机测试填写 `http://127.0.0.1:5800/api/v1`。新版控制台允许 API 地址留空并保持空值，公开检查会通过当前控制台的 `/api/v1` 代理发起；检查成功不能证明 8089 官网或外网玩家能访问。需要官网同源反向代理时填写 `/api/v1` 并在官网服务器配置相应路由，勿把控制台的 5801 地址当作公开 Bot 地址。

切页会保留未保存草稿。版本冲突或保存结果未确认时，可点击「载入最新版本，保留草稿」，核对重新合并的内容后再保存。接入操作不要求把管理令牌或网站后端密钥填写到网页；网站服务端查询私人账号资料仍使用下文独立的凭据规则。

## 官网项目与部署内容

VexBot 提供完整的社区官网：首页、全部服务器状态、邮箱注册、密码登录、本人档案与邮件找回密码。所有页面为本地 HTML/CSS/JavaScript，无运行时框架、外部字体、图片服务、WebGL 或持续动画；导航只播放一次 160 毫秒淡入，并遵守减少动态效果设置。服务器状态页展示全部已配置服务器，包含未连接项，提供已连接数量及在线人数合计；每 30 秒刷新，后台暂停，回到页面立即刷新，也支持手动刷新。官网不展示公开玩家目录，已有网站仍可通过下述玩家信息 API 接入。

- **独立项目**：`starbridge-website/` 可以单独复制到自己的仓库和服务器，包含独立启动、打包工具、SDK 与文档。Bot 不承载官网静态文件，也不需要网站源目录才能启动。
- **独立部署**：在「接入空间 → 网站绑定」下载独立项目和 `config.json`，解压项目并替换接入配置，然后部署到自己选择的静态服务器或托管目录。面板下载的是预先生成的项目包；源码修改后运行独立项目的 `build.py` 重新打包。
- **已有网站**：使用本页接口和部署包中的 `sdk/starbridge.js`，可以自定义界面。

独立项目不含 VexBot 数据库、Bot 配置、密码或任何管理/网站后端密钥。首页介绍、规则、游戏地址、入群链接及公开开关都在 VexBot 面板调整，无需重新打包；网站只通过 HTTP API 读取这些数据。API 地址持久保存在 Bot 接入设置中，下载接入配置后需替换网站根目录的 `config.json`；保存 Bot 设置不会直接修改远端网站文件。

官网采用静态网格、方块装饰和紧凑导航。面板支持 `accent_color`、`secondary_color`（`#RRGGBB` 格式）、`theme_mode`（`system/light/dark`）及 `grid_background`。访客可通过「外观」选择配色和明暗模式，偏好保存在本浏览器 `localStorage`，不修改全站设置；「恢复官网默认外观」清除此偏好。窄屏导航自动放到页底。没有背景视频、加载遮罩、持续动画或模糊滤镜。

## 开始前准备

- Bot 已运行，服主可以打开内置面板「接入空间 → 网站绑定」，或已单独启动的新版控制台「控制台设置 → 网站详细设置」。
- 准备独立网页的部署目录或静态托管，以及访客能访问的 Bot 公开 API 地址。网页地址和 API 地址可以使用不同域名。
- 官网要开放新注册或密码找回时，先按 [账号注册](account-api.md) 配置 SMTP；只展示服务器状态时不要求 SMTP 或 OneBot。
- 本机预览使用 Python 3.11+，正式部署静态文件不需要 Python。不要双击 HTML 以 `file://` 方式测试跨域接入。

## 配置步骤

1. 在「网站绑定」选择「使用 VexBot 提供的官网」或「接入自己的官网」，填写网站地址、Bot 公开 API 地址并保存。网站地址支持子目录，例如 `https://www.example.com/community/`；Bot 会自动允许其准确来源 `https://www.example.com`。
2. 需要注册或密码找回时，在「成员 → 注册账号」配置 SMTP 和发件人；需要开放新用户注册时再启用注册。只展示公开信息可以跳过。官网登录不依赖注册开关，已注册用户可在停止新注册后继续登录。
3. 使用 VexBot 提供的官网时，设置官网名称、首页内容、游戏地址、入群链接及外观；两种接入方式都检查公开范围与官网登录开关。接入网站无需重复填写注册来源白名单；其他第三方网站可继续在注册设置中加入精确来源，不支持 `*` 或 `file://`。
4. API 地址填写 `https://bridge.example.com/api/v1`，保存后下载接入配置；同来源反向代理 `/api/v1/` 时可填写 `/api/v1`。
5. 使用 VexBot 提供的官网时，解压下载的独立项目，用新下载的 `config.json` 替换根目录配置，上传所有网页文件。站点可位于子目录，资源使用相对地址，导航使用 hash，不需要 SPA 重写规则。自有官网按下方 SDK 示例修改自己的项目。
6. 按实际启用的功能测试服务器状态、注册、登录、本人档案和找回密码，再向玩家提供官网地址。

### 最小本机预览

先在「网站绑定」选择「使用 VexBot 提供的官网」，网站地址填 `http://127.0.0.1:8089/`，API 地址填 `http://127.0.0.1:5800/api/v1`，保存并允许公开服务器。下载并解压项目，在独立项目目录执行：

```powershell
python serve.py --port 8089 --api-base http://127.0.0.1:5800/api/v1
```

Windows 也可执行：

```powershell
.\start.ps1 -ApiBase http://127.0.0.1:5800/api/v1
```

Bot 使用其他端口时同步替换 API 地址。打开 `http://127.0.0.1:8089/`，应看到面板配置的社区名称；服务器页包含所有已配置服务器，未连接服务器也会显示。此时只需完成公开信息读取，再按 [验收](#上线前验收) 测试注册与登录。

启动工具只依赖 Python 3.11+ 标准库，不依赖 Bot 或父目录；`--api-base` 覆盖本次服务的配置，不修改磁盘，不指定时读取项目 `config.json`。正式静态部署不需要 Python。API 的 `127.0.0.1` 对外网玩家指向玩家自己的机器，正式部署须使用玩家可访问的地址。

独立打包：`python build.py --api-base https://bridge.example.com/api/v1`，生成 `dist/VexBot-website.zip`；`--output` 可指定输出位置。只读取项目固定文件，API 地址写入压缩包，原始配置保持不变。Bot 的发布脚本会将同一官网包放到内部兼容路径 `dist/StarBridge-website.zip`，面板以新品牌文件名提供下载；源码手动部署时，将独立构建的 ZIP 复制到该兼容路径即可。

选择「不接入官网」后，即使该来源同时存在于手动白名单，Bot 也拒绝该网站来源的跨域 API 请求；其他手动授权网站不受影响。CORS 不代替身份验证，不阻止非浏览器客户端，关闭接入不会撤销用户令牌或关闭公共 API。旧 `/community/` 地址在接入时跳转到网站，未接入时返回 404，静态资源不再从 Bot 提供。接入方式保存在 `website_mode`（`none/provided/custom`）；旧版启用的接入设置迁移为 `custom`，关闭的设置迁移为 `none`，不会擅自更换地址。

公网官网和 API 使用 HTTPS，避免浏览器混合内容拦截。独立项目内提供 `nginx.example.conf`，自行填写目录、域名和证书；反向代理应只公开需要的 `/api/v1/` 与官网资源，管理面板可保留在内网。VexBot 当前以实际 socket 地址限流，不信任任意 `X-Forwarded-For`，经代理的用户可能共用额度。

## 上线前验收

1. 从实际官网域名打开首页，确认名称、规则、地址及服务器列表与面板设置一致；在手机上确认导航和表单可以使用。
2. 使用测试邮箱完成注册，退出再用注册玩家名和密码登录；群注册旧账号先通过邮件设置密码。关闭新注册后，已有账号仍应可以登录。
3. 查看本人档案。尚未游戏登录或绑定时为空；完成 [账号绑定](account-binding.md) 或 [游戏登录](game-login.md) 后刷新，确认只显示本人的身份。
4. 测试找回密码，确认旧会话失效；重新登录后测试退出，确认前端清理令牌。
5. 核对公开服务器和公开玩家开关。未授权的数据接口应返回 403；官网模板不提供公开玩家目录页。
6. 从实际玩家设备访问，确认 API 没有 `127.0.0.1`、内网地址、HTTPS 混合内容或 CORS 错误。面板「检查 API」只证明当前管理浏览器可读公开 API。

## 常见问题

| 现象 | 检查与处理 |
| --- | --- |
| 面板已绑定，网站打不开 | 绑定只保存地址和来源授权；先确认静态站点已上传并由网站服务提供，再核对域名、端口和部署目录 |
| 首页正常，但信息一直加载失败 | 打开网站的 `config.json` 确认 `apiBase`；Bot 保存设置不会修改远端文件，需要重新下载并替换配置 |
| 本机正常，外网玩家失败 | 将 `127.0.0.1` 或内网 API 换成玩家可访问的 HTTPS 地址；检查代理是否公开 `/api/v1/` |
| 浏览器显示跨域错误 | 保存与当前网页协议、域名、端口相同的网站地址；`localhost` 与 `127.0.0.1` 是不同来源，子目录不属于来源 |
| 选择“不接入官网”后旧网站不能调用 | 该网站来源的跨域请求会被拒绝，即使同时在手动白名单中；重新接入并保存后再测试 |
| 服务器显示未连接或玩家为 unknown | 先检查 [游戏桥接](quick-start.md) 心跳；未连接不能用来断定游戏服已经关闭，公开 API 也不会按同名猜测本人 UUID |
| 注册或找回密码邮件失败 | 按 [账号注册常见问题](account-api.md#常见问题) 核对 SMTP、限流和当前验证码 |
| 登录返回 401 或 503 | 401 检查注册玩家名和密码；503 检查官网登录开关或验证繁忙，群注册账号先设置密码 |
| 下载官网包返回 project_missing | 发布包应包含预先生成的项目 ZIP；源码部署按独立项目 `build.py` 打包，再放入 Bot 的 `dist/StarBridge-website.zip` |

## 访问权限与数据范围

在内置面板「接入空间 → 网站绑定」选择官网类型，填写网站地址和 Bot 公开 API 地址，保存绑定。该面板会把留空的 API 地址补为当前内置面板来源的 `/api/v1`；新版控制台的空值行为见[上方说明](#在新版控制台中设置)。正式部署应明确填写官网访客能访问的地址。已绑定时可「检查 API」或打开网站。检查只验证当前浏览器能读取公开 API，不代表网站已部署或网站访客一定能访问；不会向目标地址发送管理令牌。解除绑定会停止授权网站来源，并保留原地址、内容及账号，后续可重新绑定。

| 接口范围 | 凭据 | 数据 |
| --- | --- | --- |
| 官网配置、公开服务器/玩家 | 无 | 面板明确设置的公开资料 |
| 本人账号及关联档案 | 用户短期 Bearer 令牌 | 本人邮箱、QQ、注册时间、已验证的游戏身份和到访时间 |
| 自有网站后端查询账号档案 | 注册设置中的网站 API 密钥 | 指定账号的上述本人资料 |

公开玩家对象只有 `name`、`uuid`、`status` 三个字段，不含 QQ、邮箱、IP、归属地、管理备注、封禁或 OP 信息。本人档案也不返回 IP、管理备注、密码哈希或 OP 信息。游戏身份来自 `account_game_links` 中已验证的 UUID 或注册 QQ 对应的实际绑定，**不凭玩家名推测 UUID**。一个账号可关联多个服务器身份，每次最多返回 100 个。

关闭「公开玩家」后，列表和单个玩家信息接口返回 403；本人档案仍可查询。关闭「官网登录」停止新的密码登录，已有短期会话到期/退出/重置密码后失效。新注册成功仍会获得一次短期用户令牌。网站后端密钥与用户令牌不可互换，也不接受管理员或游戏桥接令牌。

## 公共接口

下列路径都相对于 VexBot 地址，GET 不需要凭据。所有 JSON 接口禁止缓存；跨域来源受网站接入及注册来源设置约束，CORS 不代替用户身份验证。

### `GET /api/v1/community/info`

返回 `title, subtitle, description, rules, join_address, group_url, public_players, public_servers, login_enabled, registration_enabled, password_reset_enabled, code_minutes, accent_color, secondary_color, theme_mode, grid_background`。这些均为允许公开的官网内容或功能开关，不返回邮件配置及来源白名单。

### `GET /api/v1/servers`

返回 `{"servers":[{"id":"survival","name":"生存服","connected":true,"online_count":2,"max_players":20}]}`。关闭公开服务器时返回 403。`connected` 表示游戏桥接心跳在 15 秒内，断开时人数与人数上限为 `null`；未连接不等于确认游戏服务器关机。不会返回服务器令牌、群号或远程命令。

### `GET /api/v1/players?q=Steve&page=1&page_size=24`

`q` 为玩家名/UUID 模糊搜索（最多 64 字符）；`page` 范围 1–10000，`page_size` 范围 1–50，默认 24。结果：

```json
{"players":[{"name":"Steve","uuid":"12345678-1234-1234-1234-123456789abc","status":"online"}],"page":1,"page_size":24,"total":1}
```

列表来自 VexBot 记录的未删除玩家档案，注册账号尚未到访或关联游戏身份时不会凭空生成游戏 UUID。状态为 `online`、`offline` 或 `unknown`。仅用当前有效心跳确认在线/离线，断连或缺少足够数据时为 `unknown`。

### `GET /api/v1/players/{uuid}`

返回 `{"player":{"name":"Steve","uuid":"...","status":"unknown"}}`。不存在返回 404；UUID 格式错误返回 400；公开开关与列表一致。

## 用户登录和本人信息

### `POST /api/v1/account/login`

`Content-Type: application/json`，请求 `{"player":"Steve","password":"注册时设置的密码"}`。

成功返回 `{account, access_token, token_type:"Bearer", expires_in:3600}`。账号包含 `id,player,email,qq,created,has_password`。密码使用既有 PBKDF2 验证，账号不存在/无密码/密码错误统一返回 401 `credentials_invalid`。有持久限流和密码计算并发上限；429 表示额度用完，503 可表示登录关闭或验证繁忙。密码不会写入日志。

### `GET /api/v1/me/profile`

请求头 `Authorization: Bearer <用户 access_token>`。返回：

```json
{
  "account":{"id":"c0ff3cb2-5c57-4b12-a9a5-7e88d8ab239f","player":"Steve","email":"123456789@qq.com","qq":"123456789","created":1780000000,"has_password":true},
  "game_profiles":[{"name":"Steve","uuid":"12345678-1234-1234-1234-123456789abc","server":"survival","server_name":"生存服","status":"online","first_seen":1780000000,"last_seen":1780001000}],
  "truncated":false
}
```

时间为 Unix 秒。不会把同名的陌生玩家作为本人身份。游戏档案尚未关联时 `game_profiles` 为空；普通注册与游戏登录/QQ 绑定流程仍独立。

### `POST /api/v1/account/logout`

带当前用户 Bearer 令牌，返回 `{"logged_out":true}`，只撤销该会话。前端同时清理本地令牌；不存在或过期的令牌返回 401。

官网示例将短期令牌保存在当前标签页 `sessionStorage`，不保存密码，不在 URL 中放令牌。关闭标签页后浏览器会清理该会话存储；服务端令牌最多有效一小时，找回/修改密码会撤销该账号所有已有令牌。自有网站可验证用户令牌后创建自己的会话，但必须自行处理到期与撤销。

## 官网自助中心

登录后的账号页面新增本人绑定管理、白名单申请进度和处罚记录。已有网站可以使用：

- `GET /api/v1/me/services`：返回可申请的服务器、本人绑定、最近 50 个申请、最近 50 条成功执行的踢出/封禁/解封记录及 `whitelist_enabled`。
- `POST /api/v1/me/bind`：`{server, code}`；绑定码来自游戏内 `/qbind`，只绑定到当前账号已验证的 QQ，消费后不可重用。
- `POST /api/v1/me/unbind`：`{server}`；只解除本人 QQ 在此服的绑定及对应本人游戏身份关联，撤销该 UUID 的当前游戏认证会话。
- `POST /api/v1/me/whitelist`：`{server, reason}`；玩家名和 QQ 由当前注册账号决定，复用 Bot 申请开关、注册/绑定要求、冷却和人工审核流程。

所有接口需要 `Authorization: Bearer <用户短期令牌>`，不接受网站后端密钥、游戏密钥或管理员登录令牌。不能传入其他 QQ、玩家名或账号 ID。不会返回管理审核备注、IP、处罚执行输出或其他账号资料。身份已有其他账号关联时不允许抢占，需管理员核实。申请进度与处罚页面只显示本人记录，取消绑定后对应的身份记录不会继续作为本人身份展示。

SDK 增加 `services(token)`、`bind(token,server,code)`、`unbind(token,server)` 和 `applyWhitelist(token,server,reason)`；这些同样只接受用户令牌。

## 注册与找回密码接口

复用已有接口：

- `POST /api/v1/registration/request`：`{player,email}`，发送验证邮件，返回 `challenge_id`。
- `POST /api/v1/registration/resend`：`{challenge_id}`，受重发冷却限制，返回新的挑战信息。
- `POST /api/v1/registration/verify`：`{challenge_id,code,password}`，完成注册并得到一小时用户令牌。官网要求设置 8–128 位密码。
- `GET /api/v1/account/password/info`：密码邮件功能状态。
- `POST /api/v1/account/password/request`：`{player,email}`，发送密码设置验证码。
- `POST /api/v1/account/password/verify`：`{challenge_id,code,password}`，验证后更新密码并撤销旧用户和游戏登录会话。

详细字段、邮件配置和群命令见 [账号 API 文档](account-api.md)。邮件验证码只能成功消费一次，不要在生产环境绕过验证。

## 已有网站接入示例

### 先运行一次公开读取

在「网站绑定」选择「接入自己的官网」，网站地址填写 `http://127.0.0.1:8089/`，API 地址填写 `http://127.0.0.1:5800/api/v1`，保存并允许公开服务器。下载面板中的 SDK，保留文件名 `website-registration.js`，与下面保存为 `index.html` 的文件放在同一测试目录：

```html
<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<title>VexBot API 接入示例</title>
<h1 id="community-name">正在读取社区信息…</h1>
<pre id="servers"></pre>
<script type="module">
  import {createVexBotClient} from './website-registration.js';
  const bridge = createVexBotClient('http://127.0.0.1:5800/api/v1');
  const name = document.getElementById('community-name');
  const output = document.getElementById('servers');
  try {
    const info = await bridge.communityInfo();
    name.textContent = info.title;
    const data = await bridge.servers();
    output.textContent = data.servers.map(server =>
      `${server.name}：${server.connected ? `已连接，在线 ${server.online_count} 人` : '未连接'}`
    ).join('\n') || '尚未配置服务器';
  } catch (error) {
    output.textContent = `读取失败：${error.message}`;
  }
</script>
</html>
```

在该测试目录运行 `python -m http.server 8089 --bind 127.0.0.1`，打开 `http://127.0.0.1:8089/`。如果正在运行前面的官网预览，先停止它以释放 8089 端口。确认社区名称和服务器状态读取成功，再接入下面的账号功能；公开读取不需要任何密钥。正式部署替换 API 地址和绑定的网站地址，并使用 HTTPS。

### 按需加入账号与玩家查询

独立项目内 SDK 路径为 `sdk/starbridge.js`；内置面板下载为 `website-registration.js`，新版控制台下载为 `VexBot-website-sdk.js`，按自己保存的位置调整 import。下例中的 `playerInput`、`passwordInput` 分别取自账号表单的玩家名和密码输入，玩家查询需启用公开玩家：

```js
import {createVexBotClient} from './sdk/starbridge.js';
const bridge = createVexBotClient('https://bridge.example.com');
const info = await bridge.communityInfo();
const directory = await bridge.players({q:'Steve',page:1,pageSize:24});
const result = await bridge.login(playerInput, passwordInput);
const profile = await bridge.profile(result.access_token);
await bridge.logout(result.access_token);
```

新接入推荐使用 `createVexBotClient` 或注册专用的 `createVexBotRegistration`。SDK 继续提供 `createMyrinbotClient`、`createMyrinbotRegistration`、`createStarBridgeClient`、`createStarBridgeRegistration`、`createAetherBotClient` 与 `createAetherBotRegistration` 兼容别名，已有网站无需改动。客户端提供 `info/apply/resend/verify/account/requestPassword/setPassword`，以及 `communityInfo/servers/players/player/login/logout/profile`。可传后端来源或包含 `/api/v1` 的完整地址。使用 DOM `textContent` 展示 API 文本，避免把用户或管理员输入当 HTML 执行。

### 网站服务端查询

`GET /api/v1/accounts/{account_id}/profile`，请求头 `Authorization: Bearer <网站后端 API 密钥>`，返回与本人接口相同的结构。原 `GET /api/v1/accounts/{account_id}` 继续只返回账号资料。

自有网站必须先校验本网站用户身份，再确定其允许查询的账号 ID；不可把这个接口代理成任意访客可按 ID 读取私人资料的接口。网站密钥只存服务端环境变量，不写入前端包：

```python
import json, os, uuid
from urllib.request import Request, urlopen

def starbridge_profile(verified_account_id):
    # verified_account_id 必须来自本网站已验证的用户会话。
    base = os.environ['STARBRIDGE_API_BASE'].rstrip('/')
    account_id = str(uuid.UUID(verified_account_id))
    req = Request(f'{base}/accounts/{account_id}/profile', headers={
        'Authorization': 'Bearer ' + os.environ['STARBRIDGE_WEBSITE_KEY']
    })
    with urlopen(req, timeout=10) as response:
        return json.load(response)
```

`STARBRIDGE_API_BASE` 例如 `https://bridge.example.com/api/v1`。后端查询每实际来源地址最多 100 次/10 分钟，公共读取最多 300 次/分钟。建议复用结果减少请求，私人数据不进入公开 CDN 缓存。

## 备份与恢复

官网内容及接入设置 `data/website-settings.json` 加入 VexBot 备份；账号、绑定、实际 UUID 关联位于数据库内。恢复会撤销所有临时用户令牌。独立网站源码和部署文件由网站项目单独备份；Bot 数据备份不包含它们。旧版无接入字段的备份默认不启用网站接入，恢复后检查网站地址、公开范围与文案。
