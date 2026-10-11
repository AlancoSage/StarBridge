# Windows 安装与运行

适用版本：Bot **0.6.13**。本页负责安装、启动和停止主程序；启动后按 [快速开始](quick-start.md) 接入游戏服务器与 QQ。

适用于 Windows 10 / 11 和具有桌面环境的 Windows Server。需要能访问 Python 官网和 Python 包索引的网络；Bot 不需要显卡。

Linux 用户请阅读 [Linux 安装与运行](linux-installation.md)。BAT 安装入口仅用于 Windows：源码检出推荐 `Myrinbot.bat`；部署 ZIP 为兼容已有升级器保留 `星桥.bat`。本页以 ZIP 中的文件名演示，该脚本可自行重命名为 `Myrinbot.bat` 后使用，功能相同。

## 准备

- 从 [公开 Release](https://github.com/AlancoSage/StarBridge/releases) 下载的完整 Bot 部署包和可写目录，例如 `D:\StarBridge`；无需仓库访问授权，不要在 ZIP 预览窗口中启动。也可克隆 [公开源码](https://github.com/AlancoSage/StarBridge) 后使用相同启动流程，游戏 JAR 另行下载或构建。
- 双击安装会寻找或准备 Python；手动安装先准备 Python **3.11+**。
- 保留已有 `config.toml` 和整个 `data/`。QQ 实现端和 Minecraft 游戏服务器分别安装，本页不需要先装游戏端的 Java。

可以选择双击自动部署，也可以按步骤手动安装：

| 方式 | 适用情况 | 教程 |
| --- | --- | --- |
| 双击安装 | 希望自动准备环境并后台运行 | [方式一：双击安装](#方式一-双击安装) |
| 手动安装 | 希望自己安装 Python、依赖并通过终端运行 | [方式二：Windows 手动安装](#方式二-windows-手动安装) |

## 方式一 双击安装

1. 下载 Myrinbot Windows 部署包，完整解压到可写目录，例如 `D:\StarBridge`。不要直接在 ZIP 预览窗口内运行脚本。
2. 双击部署目录中的 **星桥.bat**；从源码部署时可双击 **Myrinbot.bat**。自动寻找 Python 3.11+；未找到时下载并校验官方 Python 3.13.16 安装包，安装到项目的 `.runtime\python`。随后创建 `.venv`，按 `requirements.lock.txt` 安装依赖，生成随机令牌配置。安装与运行逻辑都内嵌在此 BAT 文件中，无需另一个 PowerShell 脚本。
3. 管理面板就绪后自动打开浏览器，使用用户名和密码登录。首次尚未创建服主账号时，点击「创建服主账号」，使用本地 `config.toml` 的 `app.admin_token` 完成首次授权并设置用户名、密码，再登录面板填写机器人连接、服务器和关联群。

Bot 在后台运行，关闭安装窗口不会停止它。无需修改系统 PATH，无需 Git、Java 或显卡。QQ 登录实现端与 Minecraft 服务器仍由用户单独接入。ARM64 使用 Python 官方 ARM64 安装包，依赖安装需要该架构可用的二进制包。

## 再次运行与停止

| 文件 | 用途 |
| --- | --- |
| `星桥.bat` / 源码中的 `Myrinbot.bat` | 自动安装并启动；窗口内选择打开面板、启动、停止、重启或关闭窗口 |
| `config.toml` | 本地运行配置，包含首次创建服主账号的授权令牌及各端连接令牌 |
| `data/server.log`、`data/server-error.log` | 启动输出与错误日志 |

重复启动会核对 PID、Python 路径和启动命令，只复用本项目的实例。端口被其他程序占用时提示错误，不关闭其他程序或擅自修改端口。重新安装不覆盖 `config.toml` 和 `data`。Windows 重启后再次双击 `星桥.bat`。

窗口中的 `0` 仅关闭窗口，后台 Bot 继续运行；`3` 停止 Bot；`4` 重启 Bot。关闭窗口后仍可再次双击同一个脚本进行操作。本脚本没有创建系统服务或开机计划任务。

请保留完整项目目录。虚拟环境与项目专用 Python 使用绝对路径，安装后移动目录可能需要将 `.venv` 改名后重新安装。不要删除配置和数据目录。

## 方式二 Windows 手动安装

以下步骤使用 **Windows PowerShell**，每一步成功后再执行下一步。可以直接选择此方式完成部署。

### 1. 安装并检查 Python

从 [Python 官方 Windows 下载页](https://www.python.org/downloads/windows/) 获取 Python **3.11+** 的 Windows installer；可以选用与自动安装一致的 Python 3.13。根据机器选择 64-bit 或 ARM64 安装程序。使用常规 EXE 安装程序时，保留 pip 组件，并勾选 **Add python.exe to PATH**。

安装完成后重新打开 PowerShell，检查版本和解释器位置：

```powershell
python --version
python -c "import sys; print(sys.executable); assert sys.version_info >= (3, 11), 'Python 3.11+ required'"
```

版本检查通过后继续。如果 `python` 打开 Microsoft Store 或提示找不到命令，先检查 Python 是否安装、重新打开终端，或使用实际的 Python 路径创建虚拟环境，见下方示例。

### 2. 解压项目并进入目录

完整解压取得的 Myrinbot 项目包，例如放到 `D:\StarBridge`。在 PowerShell 中进入该目录：

```powershell
Set-Location -LiteralPath 'D:\StarBridge'
Test-Path -LiteralPath 'requirements.lock.txt'
Test-Path -LiteralPath 'starbridge\__main__.py'
```

将示例路径替换为自己的项目目录。两个文件检查都应返回 `True`；若返回 `False`，先检查是否只解压了部分文件，或进入了外层目录。

### 3. 创建虚拟环境并安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip check
```

`pip check` 应显示 `No broken requirements found.`。每条命令执行完成后应无错误；不要在依赖安装失败时继续启动。

没有将 Python 加入 PATH 时，可以用完整路径替代上面的第一条命令；下面路径只是示例，需替换为自己的解释器位置：

```powershell
& 'C:\Python313\python.exe' -m venv .venv
```

之后仍使用 `.\.venv\Scripts\python.exe` 安装依赖和启动。无需激活虚拟环境，也无需调整 PowerShell 的执行策略；直接调用环境中的解释器即可，见 [Python venv 说明](https://docs.python.org/3/library/venv.html)。

### 4. 生成初始配置

仅在尚未存在 `config.toml` 时初始化：

```powershell
if (-not (Test-Path -LiteralPath config.toml)) {
    .\.venv\Scripts\python.exe -m starbridge init --config config.toml
}
```

该命令生成初始配置和随机令牌。已有配置时会跳过，保留 `config.toml` 与玩家数据，不需要手动复制示例配置或填入占位令牌。

### 5. 启动 Bot 并登录面板

在同一个项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m starbridge run --config config.toml
```

保持此终端打开，在浏览器访问 `http://127.0.0.1:5800/`，使用用户名和密码登录。首次没有服主账号时，点击「创建服主账号」，使用 `config.toml` 中 `[app]` 下的 `admin_token` 完成首次授权并设置自己的账号，再登录并设置 QQ 实现端、游戏服务器和关联群。手动启动不会自动打开浏览器。

### 6. 停止与下次启动

手动安装后的命令是前台运行，按 **Ctrl+C** 停止。下次启动只需进入项目目录并运行主程序：

```powershell
Set-Location -LiteralPath 'D:\StarBridge'
.\.venv\Scripts\python.exe -m starbridge run --config config.toml
```

不需要重复创建虚拟环境、安装依赖或初始化配置。需要更新依赖时，先停止 Bot，再按新版本的 `requirements.lock.txt` 安装。

BAT 的菜单只管理由它在本目录启动、记录并核验的后台 Bot；前台实例在其终端按 Ctrl+C 停止，避免同时启动两个实例。希望改用后台运行时，先停止前台实例，再双击 `星桥.bat`，它会检查并复用现有环境与配置。

## 预期结果

浏览器能打开 [本机管理面板](http://127.0.0.1:5800/) 并使用账号密码登录；首次创建服主账号的授权令牌不用于日常登录。此时总览中的 QQ 或游戏端可以仍未连接，按 [快速开始](quick-start.md) 继续配置；QQ 单独接入见 [OneBot 11 连接](onebot-connection.md)。

自动安装的 Bot 在后台运行，使用 `星桥.bat` 菜单管理；手动运行的 Bot 保持终端打开，按 Ctrl+C 停止。已修改监听端口时，按实际端口访问面板。

## 常见故障

| 提示或现象 | 处理方法 |
| --- | --- |
| `python` 找不到或打开商店 | 检查 Python 安装与 PATH，重新打开终端，或用解释器完整路径创建环境 |
| Python 版本低于 3.11 | 安装受支持的版本，使用该版本重新创建虚拟环境 |
| 找不到 `requirements.lock.txt` | 完整解压项目，并在包含该文件的根目录执行命令 |
| 依赖下载失败或缺少对应二进制包 | 检查网络、Python 版本与 CPU 架构，再重新安装依赖 |
| `No module named starbridge` | 在项目根目录执行，并使用本项目 `.venv` 中的 Python |
| 5800 端口被占用 | 检查是否已有 Bot 或其他程序运行；停止自己的旧实例后再启动 |
| 双击后 Bot 未就绪 | 查看安装窗口提示和 `data/server-error.log`；不要仅凭窗口已打开判断成功 |
| 面板账号或密码不正确 | 使用本实例的服主或团队账号密码，确认账号已启用；首次没有服主账号时先点击「创建服主账号」 |
| 首次创建服主账号授权失败 | 使用当前目录 `config.toml` 的 `app.admin_token`，不要使用 OneBot 或游戏服务器连接令牌 |
| 移动目录后环境不可用 | 将 `.venv` 改名保留后在新目录重新安装；保留 `config.toml` 和 `data/` |

Bot 已启动后的连接问题见 [故障排查](troubleshooting.md)。

## 可选命令行操作

```bat
rem 启动；默认操作，通常直接双击即可
call "星桥.bat" start
rem 停止，不先启动
call "星桥.bat" stop
rem 重启
call "星桥.bat" restart
rem 仅安装环境与配置，不启动
call "星桥.bat" install
rem 自动化调用：不打开浏览器，不显示菜单，不等待按键
call "星桥.bat" start quiet
call "星桥.bat" stop quiet
rem 可选：指定已安装的 Python，未指定时自动查找
set "STARBRIDGE_PYTHON=C:\Python313\python.exe"
call "星桥.bat" install quiet
```

双击入口只对本次 PowerShell 进程使用执行策略参数，不永久修改系统执行策略。组织策略禁止脚本运行时，需由管理员按组织规则处理。

SHA-256 固定值来自 [Python 3.13.16 官方发布页](https://www.python.org/downloads/release/python-31316/)，校验失败不会执行下载文件。静默安装参数遵循 [Python Windows 安装说明](https://docs.python.org/3.13/using/windows.html#installing-without-ui)。
