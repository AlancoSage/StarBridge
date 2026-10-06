# 星桥社区官网 · 独立项目

本目录可单独复制到自己的仓库、电脑或服务器开发、部署。网站由纯 HTML/CSS/JavaScript 构成，不导入 Bot 代码，不需要 Bot 数据库、Node.js 或运行时框架。账号、邮件验证和服务器状态通过 HTTP API 接入星桥。

## 本地启动

安装 Python 3.11 或更新版本，在本目录运行：

```sh
python serve.py --port 8089 --api-base http://127.0.0.1:8088/api/v1
```

Windows 也可运行 `./start.ps1 -ApiBase http://127.0.0.1:8088/api/v1`；不指定 `-ApiBase` 时读取项目 `config.json`。打开 `http://127.0.0.1:8089/`；终端按 Ctrl+C 停止。`serve.py` 只使用 Python 标准库，不依赖父目录；`--api-base` 只覆盖本次服务提供的配置，不修改文件。开发服务默认仅监听本机，正式部署使用静态 Web 服务器。

## 在 Bot 面板接入

1. 打开 Bot「接入空间 → 网站绑定」，选择「使用星桥提供的官网」。网站地址填 `http://127.0.0.1:8089/`，Bot 公开 API 地址填 `http://127.0.0.1:8088/api/v1`。
2. 保存后 Bot 自动允许网站的准确来源，不需要重复修改注册来源设置。已有自建网站可选「接入自己的官网」，按 API/SDK 文档接入。
3. 下载「接入配置」，将 `config.json` 放到本项目根目录。正式部署时换成访客能访问的域名和 API 地址。
4. 在 Bot 注册设置中配置 SMTP 并启用注册。已注册账号的密码登录不依赖新注册开关。

网站地址可包含子目录。不需要官网时选择「不接入官网」，停止允许此来源的跨域 API 请求并保留原设置；这是浏览器来源授权，不会关闭 API、撤销用户令牌或代替用户身份验证。Bot 可独立使用，选择星桥官网也需自行部署独立项目。

## 打包与部署

```sh
python build.py --api-base https://bridge.example.com/api/v1
```

生成 `dist/StarBridge-website.zip`，包含网页、启动和打包工具、SDK 与文档。也可用 `--output` 指定输出文件。打包只读取本项目固定文件，不读取 Bot 配置、数据库或密码；API 地址只写入压缩包内的 `config.json`。

解压到 Nginx、Apache 或静态托管目录；可部署在根目录或子目录，导航使用 hash，无需 SPA 重写。Nginx 示例见 `nginx.example.conf`。同域反向代理 `/api/v1/` 时可配置 `{"apiBase":"/api/v1"}`。静态托管不需要安装 Python；Python 仅用于本地预览和打包。

## 开发与功能

- `index.html`、`site.css`、`site.js`：独立界面与交互；`config.json`：唯一 API 地址配置。
- `sdk/starbridge.js`：已有网站可导入的浏览器 SDK。
- `docs/website-deployment.md`、`docs/account-api.md`：部署、注册及信息接口文档。
- 首页与服务器页展示全部配置服务器，含未连接项；状态每 30 秒刷新，后台暂停。
- 支持邮箱注册、密码登录、本人档案、找回密码、游戏验证码绑定和主动解绑、白名单申请与进度、本人封禁记录；没有公开玩家目录页面。
- 文案、主题、游戏地址、入群链接和公开范围由 Bot 面板调整，经公开 API 读取。

网站使用静态背景和短暂 CSS 动画，支持减少动态效果，没有 WebGL、模糊滤镜、背景视频或持续动画。短期用户令牌只保存在当前标签页 `sessionStorage`；前端配置不能放管理员令牌、SMTP 密码或网站后端密钥。
