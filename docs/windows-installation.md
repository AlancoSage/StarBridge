# Windows 双击部署

适用于 Windows 10 / 11 和具有桌面环境的 Windows Server。需要能访问 Python 官网和 Python 包索引的网络；Bot 不需要显卡。

## 三步开始

1. 下载星桥 Windows 部署包，完整解压到可写目录，例如 `D:\StarBridge`。不要直接在 ZIP 预览窗口内运行脚本。
2. 双击根目录的 **install.cmd**。自动寻找 Python 3.11+；未找到时下载并校验官方 Python 3.13.16 安装包，安装到项目的 `.runtime\python`。随后创建 `.venv`，按 `requirements.lock.txt` 安装依赖，生成随机令牌配置。
3. 管理面板就绪后自动打开浏览器。首次登录使用本地 `config.toml` 的 `app.admin_token`；进入面板填写机器人连接、服务器和关联群。

Bot 在后台运行，关闭安装窗口不会停止它。无需修改系统 PATH，无需 Git、Java 或显卡。QQ 登录实现端与 Minecraft 服务器仍由用户单独接入。ARM64 使用 Python 官方 ARM64 安装包，依赖安装需要该架构可用的二进制包。

## 再次运行与停止

| 文件 | 用途 |
| --- | --- |
| `install.cmd` | 首次部署；失败后可重新双击继续 |
| `start.cmd` | 后续启动；环境就绪时跳过重复安装 |
| `stop.cmd` | 停止此目录内的后台 Bot |
| `config.toml` | 本地运行配置，包含首次登录令牌 |
| `data/server.log`、`data/server-error.log` | 启动输出与错误日志 |

重复启动会核对 PID、Python 路径和启动命令，只复用本项目的实例。端口被其他程序占用时提示错误，不关闭其他程序或擅自修改端口。重新安装不覆盖 `config.toml` 和 `data`。Windows 重启后双击 `start.cmd`；本脚本没有创建系统服务或开机计划任务。

请保留完整项目目录。虚拟环境与项目专用 Python 使用绝对路径，安装后移动目录可能需要将 `.venv` 改名后重新安装。不要删除配置和数据目录。

## 可选命令行参数

```powershell
# 指定已安装的 Python
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -PythonPath 'C:\Python313\python.exe'

# 仅准备环境与配置，不启动
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -NoStart

# 启动，但不打开浏览器
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -NoBrowser
```

双击入口只对本次 PowerShell 进程使用执行策略参数，不永久修改系统执行策略。组织策略禁止脚本运行时，需由管理员按组织规则处理。

SHA-256 固定值来自 [Python 3.13.16 官方发布页](https://www.python.org/downloads/release/python-31316/)，校验失败不会执行下载文件。静默安装参数遵循 [Python Windows 安装说明](https://docs.python.org/3.13/using/windows.html#installing-without-ui)。
