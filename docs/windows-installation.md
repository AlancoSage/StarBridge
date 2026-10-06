# Windows 双击部署

适用于 Windows 10 / 11 和具有桌面环境的 Windows Server。需要能访问 Python 官网和 Python 包索引的网络；Bot 不需要显卡。

Linux 用户请阅读 [Linux 安装与运行](linux-installation.md)。本指南中的 `星桥.bat` 仅用于 Windows。

## 三步开始

1. 下载星桥 Windows 部署包，完整解压到可写目录，例如 `D:\StarBridge`。不要直接在 ZIP 预览窗口内运行脚本。
2. 双击根目录唯一的 **星桥.bat**。自动寻找 Python 3.11+；未找到时下载并校验官方 Python 3.13.16 安装包，安装到项目的 `.runtime\python`。随后创建 `.venv`，按 `requirements.lock.txt` 安装依赖，生成随机令牌配置。安装与运行逻辑都内嵌在此 BAT 文件中，无需另一个 PowerShell 脚本。
3. 管理面板就绪后自动打开浏览器。首次登录使用本地 `config.toml` 的 `app.admin_token`；进入面板填写机器人连接、服务器和关联群。

Bot 在后台运行，关闭安装窗口不会停止它。无需修改系统 PATH，无需 Git、Java 或显卡。QQ 登录实现端与 Minecraft 服务器仍由用户单独接入。ARM64 使用 Python 官方 ARM64 安装包，依赖安装需要该架构可用的二进制包。

## 再次运行与停止

| 文件 | 用途 |
| --- | --- |
| `星桥.bat` | 自动安装并启动；窗口内选择打开面板、启动、停止、重启或关闭窗口 |
| `config.toml` | 本地运行配置，包含首次登录令牌 |
| `data/server.log`、`data/server-error.log` | 启动输出与错误日志 |

重复启动会核对 PID、Python 路径和启动命令，只复用本项目的实例。端口被其他程序占用时提示错误，不关闭其他程序或擅自修改端口。重新安装不覆盖 `config.toml` 和 `data`。Windows 重启后再次双击 `星桥.bat`。

窗口中的 `0` 仅关闭窗口，后台 Bot 继续运行；`3` 停止 Bot；`4` 重启 Bot。关闭窗口后仍可再次双击同一个脚本进行操作。本脚本没有创建系统服务或开机计划任务。

请保留完整项目目录。虚拟环境与项目专用 Python 使用绝对路径，安装后移动目录可能需要将 `.venv` 改名后重新安装。不要删除配置和数据目录。

## 可选：Windows 手动安装

已经安装 Python 3.11+、希望自己管理运行环境时，在项目根目录执行 PowerShell 命令。通常使用上面的 BAT 即可，无需再执行本节。

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip check
if (-not (Test-Path -LiteralPath config.toml)) {
    .\.venv\Scripts\python.exe -m starbridge init --config config.toml
}
.\.venv\Scripts\python.exe -m starbridge run --config config.toml
```

手动命令是前台运行，按 Ctrl+C 停止。BAT 的菜单只管理由它在本目录启动、记录并核验的后台 Bot；不要同时启动前台和后台实例。

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
