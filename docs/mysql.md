# MySQL 数据存储

从 v0.6.26 起，可在「系统 → 软件设置 → 数据存储」选择 SQLite 或 MySQL。SQLite 仍为默认选项，已有安装不会自动切换。MySQL 模式下，绑定、账号、密码散列、玩家档案、日志、插件业务数据等直接存入 MySQL；配置文件、插件配置及备份文件仍保存在本机。

## 连接

支持 **MySQL 8.0.17+ 和 8.4**，使用 InnoDB、utf8mb4 与区分大小写的排序规则。请为单个 Myrinbot 实例创建专用数据库和数据库用户。不要与其他应用共用数据表，也不要同时运行两个实例操作同一个库。本版不声明兼容 MariaDB。

在 MySQL 管理工具中创建数据库，并向专用用户直接授予该库的 SELECT、INSERT、UPDATE、DELETE、CREATE、ALTER、INDEX、TRIGGER 权限。TRIGGER 权限用于检查并拒绝已有触发器，程序不会创建触发器；仅通过角色授予此权限的账户需补充直接授权。生产环境请使用独立密码，并按实际 Bot 来源地址限制用户。程序不会创建 MySQL 服务、数据库或数据库用户。

面板填写主机、端口、数据库、用户名和密码后可「检测连接」。检测只验证连接和读取，不建表、不保存设置。启用 TLS 时会同时校验证书及主机名；自签名证书需填写 CA 文件路径，相对路径以 `config.toml` 的目录为基准。

配置文件也可添加：

```toml
[mysql]
enabled = false
host = "127.0.0.1"
port = 3306
database = "myrinbot"
user = "myrinbot"
password = "填写数据库密码"
connect_timeout = 5
read_timeout = 5
write_timeout = 5
tls = false
ssl_ca = ""
```

`enabled = false` 使用 `app.database` 的 SQLite 文件，`true` 使用 MySQL。保存连接设置后需重启。切换为空库会创建新数据表，**不会自动复制原数据库**。运行中的 MySQL 连接失败不会另建 SQLite 数据库；事务中断不会自动重放。面板重启应用新连接失败时，仍按原有机制恢复上一次运行设置，并显示失败提示。

## 迁移已有数据

先配置好 MySQL 连接信息，保留当前数据库模式，再完全停止 Myrinbot。以下命令在软件目录中运行，使用软件自带的 Python 环境：

```powershell
.\.venv\Scripts\python.exe scripts/migrate_database.py --config config.toml --to mysql
```

迁回 SQLite：

```powershell
.\.venv\Scripts\python.exe scripts/migrate_database.py --config config.toml --to sqlite
```

工具会先保存源数据快照，核对导入结果后再切换配置。目标已有数据时默认拒绝覆盖；如明确需要替换，添加 `--replace`，工具会额外保存目标安全副本。源 SQLite 文件或源 MySQL 数据会保留。安全副本和迁移记录位于配置目录的 `data/database-migrations/`，其中包含账号数据和配置凭据，应妥善保管。

迁移后，旧验证码、登录会话、待执行操作和密码找回授权失效；定时任务暂停，重新确认后启用。重新启动软件，通过原服主用户名和密码登录。迁移过程中如断电或被强制结束，请保留迁移记录和安全副本，核对目标数据后再启动软件。

## 备份、恢复与升级

面板继续使用现有 ZIP 备份格式：MySQL 数据导出为经过校验的 SQLite 便携快照，因此备份可在两种存储模式间恢复。备份中的数据库地址和密码不会覆盖当前本机 MySQL 连接设置。恢复 MySQL 时使用事务，失败时保留恢复记录及安全副本。

通过旧版本面板在线升级后，请先**完全退出并从启动脚本重新启动**，让 MySQL 备份升级支持生效。MySQL 模式下禁止回退到 v0.6.26 之前的版本；如确需回退，请先离线迁回 SQLite。

## 验证范围

本版使用独立的官方 MySQL 8.4.7 实例验证建表、业务读写、身份标识、事务、SQLite 双向迁移、备份与恢复。MySQL 8.0.17 是功能最低要求；其他版本请先在独立数据库测试。游戏端 AuthMe、LimboAuth、LibreLogin 各自使用的数据库不会随 Bot 存储模式改变。
