# Bot 更新与回退

当前文档对应 **Bot v0.6.20**；面板更新协议从 0.6.1 起可用。进入 **设置 → 更新与回退**，只允许服主操作。默认使用 GitHub 正式版本，也可上传 ZIP 或选择自定义 HTTPS 更新源。项目的公开源码和正式 Release 位于 [AlancoSage/StarBridge](https://github.com/AlancoSage/StarBridge)，采用 [AGPL-3.0-or-later](https://github.com/AlancoSage/StarBridge/blob/main/LICENSE)。

v0.6.10 正式采用 `Myrinbot-*` 附件名称，同时为旧升级器保留内容相同的 `StarBridge-Windows-0.6.10.zip`。本版统一面板和官网的黑白 M 机器人图标，新安装的默认端口为 5800；更新不修改已有 `config.toml` 或端口。部署包内部的 `StarBridge/` 根目录、`update.json` 和受管理文件名保持原协议；历史附件名称也保持原记录。具体关系见 [项目名称与兼容说明](project-name.md)。

升级到 v0.6.11 后，面板统一使用用户名和密码登录。已有团队账号可以继续使用；尚无服主账号时，在登录页点击「创建服主账号」，使用当前 `config.toml` 的 `app.admin_token` 完成首次授权并设置用户名、密码。旧管理令牌继续兼容管理 API，不作为日常登录密码，详见 [面板登录](panel-guide.md#登录面板)。本次沿用 Bukkit 插件 0.5.3 与游戏端模组 0.1.1。

## GitHub 正式版本更新

1. 更新来源选择「GitHub 正式版本」，仓库填写 `AlancoSage/StarBridge`，或自己发布 Myrinbot 部署包的仓库。
2. 官方公开仓库无需配置 GitHub 读取令牌即可检查和下载。GitHub 提示请求额度不足时，可为自己的账号配置读取令牌；如果使用自己维护的私有仓库，则需有该仓库访问权，并为 fine-grained personal access token 仅选择该仓库、授予 **Contents: Read-only**，在面板填写并保存。
3. 点击「检查更新」获取最新可升级正式版，或点击「读取 GitHub 版本」查看发布历史。
4. 点击「下载并校验」，通过大小、SHA256、清单及隔离启动检查后，再点击「备份并升级」。读取和下载不会自动安装。

GitHub 令牌只保存在 Bot 的数据库中，接口仅返回「是否已配置」，不会返回令牌。输入框留空表示保留，勾选清除可删除；更换仓库时不沿用原令牌。令牌不发送给 GitHub 附件存储的跳转地址。备份包含更新源设置和读取令牌，只有服主可下载恢复包，请按其他运行凭据保管。

源码、部署 ZIP 和版本说明均可在 [公开仓库](https://github.com/AlancoSage/StarBridge) 与 [Releases](https://github.com/AlancoSage/StarBridge/releases) 获取，无需申请仓库访问权限。已有读取令牌可在面板勾选清除。不要把个人管理令牌写入安装脚本或发给其他用户；无法使用 GitHub 更新时，也可下载部署 ZIP 后上传面板。

版本列表只展示正式发布，排除草稿和预发布，按数值版本号排序。0.5.0 为历史手动安装包，0.6.0 起具有面板更新协议。版本号相同或更旧不会被提示为新版本；历史版本仍可单独下载校验，安装前核对版本和发布说明。

## 首次启用

Windows 部署 ZIP 使用 `星桥.bat` 启动或重启，源码推荐 `Myrinbot.bat`；Linux 使用原有 `python -m starbridge run --config config.toml`。此命令现在通过稳定的监督进程运行 Bot。旧实例需要先正常停止并用新版本重新启动一次，面板才允许自动版本切换。

监督进程只负责管理一个服务子进程与版本切换，没有持续外部轮询。一个安装目录只运行一个 Bot 实例。保留 `.runtime/updates/`，它包含回退代码、副本和可能正在使用的独立 Python 环境。不要删除在用环境。

## 上传升级包

1. 上传完整 Bot 部署 ZIP，最大 64 MiB；例如历史 `StarBridge-Windows-0.6.0.zip` 或采用新名称的 `Myrinbot-Windows-<版本>.zip`。该 ZIP 同时可以用于 Linux Bot 更新。
2. 等待文件校验与隔离启动测试完成。部署包需有 `StarBridge/update.json`，文件 SHA256、版本和升级协议必须一致。
3. 依赖版本变化时，在独立环境安装锁定依赖，不修改正在运行的虚拟环境。这一步需要能访问 PyPI。
4. 点击「备份并升级」。Bot 先创建数据安全备份，再停止子进程、保存代码与数据副本、替换代码并重新启动。
5. 服务确认就绪后记录成功；新版本启动失败或切换中断时自动恢复升级前代码和数据。

部署包会替换受管理的 Bot 源码、面板文件、文档、示例、游戏 JAR 与官网部署 ZIP。不会替换本机 `config.toml`、业务数据库、插件 JSON 或稳定监督脚本。包中的代码需要来自可信发布者；SHA256 检测完整性，并不提供发布者签名。

更新 Bot 内附的游戏 JAR 后，还需把它安装到每台 Minecraft 服务器并重启该服。已独立部署的官网也需要单独更新，Bot 升级不会改写远程官网目录。

## 使用自己的更新源

更新源为无账号密码的 HTTPS JSON 地址，不接受重定向。以下示例中的 SHA256 必须替换为部署包实际值。

```json
{
  "version": "0.6.20",
  "url": "https://downloads.example.com/Myrinbot-Windows-0.6.20.zip",
  "sha256": "替换为部署包的64位小写SHA256",
  "notes": "本次更新说明"
}
```

保存地址后，点击「检查更新」，再点击「下载并校验」。未配置更新源时直接上传 ZIP。自定义 HTTPS 请求不携带 GitHub 令牌；需要 GitHub 仓库认证的自建更新源请选择 GitHub 来源，或先下载部署包再上传。

## 每个版本发布到 GitHub

源码仓库提供 `.github/workflows/release.yml`。在 `main` 修改 `starbridge/__init__.py` 的 Bot 版本号，添加相应 `releases/v版本号.md` 后推送，工作流会运行回归测试、构建 Java 8 插件和官网，并发布该版本。也支持匹配版本号的 `v*` 标签和手动运行；同一版本重复触发会跳过已发布版本，不能覆盖旧包。

发布脚本准备完整 `Myrinbot-Windows-<版本>.zip`、`Myrinbot-website.zip`、`Myrinbot-*.jar` 和 `SHA256SUMS.txt`，并附带内容相同的 `StarBridge-Windows-<版本>.zip` 供旧升级器识别。正式发布时先创建草稿，上传并核对附件，再正式发布；失败不会把不完整草稿当作可升级版本。Bot、官网和 Minecraft 插件共用本次发布说明，插件自身版本可以与 Bot 不同。包内 JAR 和官网 ZIP 保留原有受管理路径。

本机也可先按 [模组构建说明](mod-game-ends.md#开发与构建) 与 [Fabric 构建说明](fabric-game-ends.md) 构建该版本全部游戏端，再构建通用插件并发布；发布脚本会检查配套 JAR，并生成官网包、Bot 包及校验文件：

```powershell
.\bridge\build.ps1
python scripts/release.py --publish
```

需要先用 `gh auth login` 登录有写入权限的 GitHub 账号。创建或修改自动发布工作流需要额外的 `workflow` 权限。普通 Bot 用户可直接读取官方公开 Release；发布脚本支持公开仓库及自己维护的私有仓库，源码提交中的版本必须与部署包一致。

## 回退与保留

在成功记录中选择「恢复此次操作前状态」。回退会先另存当前数据安全备份，再恢复**该次操作前的代码、配置和数据库**。升级后新产生的数据不会出现在恢复后的业务库中，需要时从安全备份取回。回退失败时恢复回退前的状态。

「清理旧更新文件」保留最近五次操作、已准备的部署包和仍在使用的运行环境。升级前、回退前的数据安全备份按保护备份保留；可在备份页面下载和手动管理。

这不是 Minecraft 世界备份功能；游戏地图与游戏插件目录需另行备份。支持此协议的 0.6.x 更新可以面板回退，手动覆盖过的早期版本不自动生成回退记录。

相关文档：[备份与恢复](backups.md)、[Windows 安装](windows-installation.md)、[Linux 安装](linux-installation.md)。
