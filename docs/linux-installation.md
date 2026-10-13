# Linux 安装与运行

适用版本：Bot **0.6.15**。本页负责准备 Python 环境、启动主程序和可选后台托管；群服联动按 [快速开始](quick-start.md) 继续。

适用于具有 Python 3.11+ 的 Linux 环境。下面的系统依赖命令面向 Ubuntu 24.04 和 Debian 12；其他发行版需使用对应的包管理器。Bot 不需要图形桌面、Java 或显卡，QQ 实现端和 Minecraft 游戏服务器需另外接入。

Windows 用户请阅读 [Windows 双击部署](windows-installation.md)。`星桥.bat` 仅用于 Windows；Linux 使用虚拟环境中的 Python 启动。

## 准备

- 从 [公开 Release](https://github.com/AlancoSage/StarBridge/releases) 下载的完整 Bot 部署包，或完整源码检出；可读写的部署目录，以及能访问 Python 包索引的网络。
- Python **3.11+** 与对应的 venv 包；下面以 `/opt/starbridge` 为部署目录。
- 保留已有 `config.toml` 和整个 `data/`。可选 systemd 托管需要相应管理权限。

## 1. 准备 Python 与项目目录

在 Ubuntu 24.04 / Debian 12 中安装系统依赖：

```bash
sudo apt update
sudo apt install -y python3 python3-venv
python3 --version
python3 -c 'import sys; assert sys.version_info >= (3, 11), "需要 Python 3.11 或更新版本"'
```

如果版本检查失败，先安装发行版支持的 Python 3.11+ 及其对应的 venv 包，再继续。创建虚拟环境时使用该版本的解释器，例如 `python3.12 -m venv .venv`。

完整解压 Myrinbot Bot 部署包到部署目录，或从 [公开仓库](https://github.com/AlancoSage/StarBridge) 克隆源码；无需额外仓库授权。下文以 `/opt/starbridge` 为例，目录中应直接包含 `starbridge/`、`config.example.toml` 和 `requirements.lock.txt`。部署用户需要有该目录的读写权限。使用其他目录时，修改下文的 `cd` 和 systemd 中的绝对路径。

不要将 Windows 的 `.venv` 或 `.runtime` 复制到 Linux；应在 Linux 上创建运行环境。

## 2. 安装依赖与生成配置

以部署用户执行，确认每一步成功后再继续：

```bash
cd /opt/starbridge
python3 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: -r requirements.lock.txt
.venv/bin/python -m pip check
```

首次运行时生成随机令牌配置；已有配置则保留：

```bash
if [ ! -f config.toml ]; then
    .venv/bin/python -m starbridge init --config config.toml
fi
```

首次创建服主账号时，使用 `config.toml` 的 `[app]` 下的 `admin_token` 完成一次授权并设置用户名和密码；日常面板登录使用账号密码。该管理令牌还用于兼容管理 API。QQ 接入使用 `onebot.token`，每个游戏服务器使用自己的连接令牌。后续设置都可以在管理面板内调整。

虚拟环境使用 Python 官方的 [venv](https://docs.python.org/3/library/venv.html)；无需执行激活脚本，也无需向系统 Python 安装项目依赖。系统包说明见 [Ubuntu python3-venv](https://packages.ubuntu.com/noble/python3-venv) 与 [Debian python3-venv](https://packages.debian.org/bookworm/python3-venv)。

## 3. 启动与访问面板

在项目根目录前台启动：

```bash
cd /opt/starbridge
.venv/bin/python -m starbridge run --config config.toml
```

本机访问 `http://127.0.0.1:5800/`，使用用户名和密码登录。首次没有服主账号时，点击「创建服主账号」，使用本机 `config.toml` 的 `app.admin_token` 完成首次授权并设置自己的账号，再回到普通登录。前台运行时按 **Ctrl+C** 停止；关闭终端或断开 SSH 后，进程可能退出。需要持续后台运行时使用下一节的 systemd。

默认监听地址为 `127.0.0.1`。部署在远程 Linux 服务器时，可先在自己的电脑开启 SSH 隧道，再打开本机浏览器：

```bash
ssh -N -L 5800:127.0.0.1:5800 deploy@example.com
```

将 `deploy@example.com` 替换为实际 SSH 用户和服务器地址；保持隧道窗口运行，再访问自己电脑的 `http://127.0.0.1:5800/`。如果本机 5800 已被占用，可以将 `-L` 中第一个端口改为 15800，并访问 `http://127.0.0.1:15800/`。

QQ 实现端或游戏服务器分开部署时，在面板「设置 → 软件设置」中调整监听地址与端口，并使用各端可以访问的 Bot 地址。`0.0.0.0` 是监听配置，浏览器使用实际 IP 或域名。面板重启应用配置后，还需按部署网络配置防火墙、反向代理或私有网络的访问规则。

## 4. 可选：systemd 后台运行与开机启动

本节用于运行 systemd 的服务器。先按 Ctrl+C 停止前台 Bot，避免同一个端口运行两个实例。

创建 `/etc/systemd/system/starbridge.service`，写入以下模板。**先将 `User=starbridge` 替换为实际存在的普通部署用户**；该用户必须能读写项目目录、`config.toml` 和 `data/`。示例目录为 `/opt/starbridge`，按实际路径修改三个路径字段。

```ini
[Unit]
Description=Myrinbot
Wants=network-online.target
After=network-online.target

[Service]
Type=exec
User=starbridge
WorkingDirectory=/opt/starbridge
ExecStart=/opt/starbridge/.venv/bin/python -u -m starbridge run --config /opt/starbridge/config.toml
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

加载服务并选择是否开机启动：

```bash
sudo systemctl daemon-reload
sudo systemctl start starbridge
sudo systemctl status starbridge --no-pager
# 需要开机启动时再执行
sudo systemctl enable starbridge
```

日常操作：

```bash
# 查看最近日志；加 -f 可持续跟踪
sudo journalctl -u starbridge -n 100 --no-pager
# 停止
sudo systemctl stop starbridge
# 重启
sudo systemctl restart starbridge
# 取消开机启动（不会停止当前服务）
sudo systemctl disable starbridge
```

systemd 托管的日志通过 `journalctl` 查看，Windows BAT 的 `data/server.pid` 与启动日志文件不用于管理 Linux 服务。`Type=exec` 和自动重启行为参见 [systemd 服务配置说明](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)。

## 预期结果

前台终端或 `journalctl` 显示管理面板已启动；浏览器能打开面板，并使用账号密码登录。首次创建服主账号只使用 `app.admin_token` 授权一次。systemd 托管时，`systemctl status starbridge` 应显示服务正在运行。

此时 QQ 与游戏端可以仍未连接。按 [快速开始](quick-start.md) 配置服务器、安装游戏端，再按 [OneBot 11 连接](onebot-connection.md) 连接 QQ。使用 SSH 隧道登录面板时，游戏端与 QQ 实现端仍需各自能访问 Bot。

## 5. 升级与常见问题

升级前在面板创建备份，再停止 Bot，更新项目代码并保留 `config.toml` 与整个 `data/`。重新安装锁定依赖后启动服务，不要覆盖现有配置或重复初始化。

| 提示或现象 | 处理方法 |
| --- | --- |
| `No module named venv` 或 `ensurepip is not available` | 安装当前 Python 版本对应的 venv 包后重新创建环境 |
| Python 版本低于 3.11 | 安装受支持的 Python 版本，再用该解释器创建 `.venv` |
| `No matching distribution found` | 检查 Python 版本、CPU 架构及该平台的二进制包支持；同时确认包索引可访问 |
| `Permission denied` | 确认运行用户有项目、配置及数据目录的读写权限 |
| `Address already in use` | 检查是否已有 Bot 或其他服务使用该端口；不要重复启动 |
| 本机正常、远程浏览器打不开 | 检查监听地址、实际访问地址、SSH 隧道及防火墙规则 |
| systemd 显示用户或路径错误 | 检查 `User` 是否存在，以及 `WorkingDirectory`、`ExecStart` 和配置路径是否正确 |
| 面板账号或密码不正确 | 使用本实例的服主或团队账号密码，确认账号已启用；首次没有服主账号时先点击「创建服主账号」 |
| 首次创建服主账号授权失败 | 使用当前实例配置中的 `app.admin_token`，不要使用 OneBot 或游戏连接令牌 |

连接后的问题见 [故障排查](troubleshooting.md)；更新操作见 [更新与回退](updates.md)。
