# 参与 VexBot 开发

欢迎提交问题、文档改进和 Pull Request。提交前请先搜索已有 [Issues](https://github.com/AlancoSage/StarBridge/issues)，说明使用的 Bot 版本、服务端类型、Minecraft 和 Java 版本，以及复现步骤。请删除日志中的令牌、邮箱、QQ、IP 和玩家数据。

安全漏洞请按 [SECURITY.md](SECURITY.md) 私下报告。

产品正式名称为 **VexBot**。更名保留原有 Python 模块、游戏端标识与更新协议，开发时按 [项目名称与兼容说明](docs/project-name.md) 区分展示名称和兼容标识。

## 准备开发环境

Bot 使用 Python 3.11 或更新版本；持续集成使用 Python 3.14。Minecraft 游戏端使用 Java，具体 Java 要求请参阅 [版本兼容文档](https://github.com/AlancoSage/StarBridge/blob/main/docs/minecraft-compatibility.md)。管理面板与独立官网使用 HTML、CSS 和 JavaScript。

```bash
git clone https://github.com/AlancoSage/StarBridge.git
cd StarBridge
python -m venv .venv
```

Windows 激活 `.venv\Scripts\Activate.ps1`；Linux 激活 `source .venv/bin/activate`，然后安装依赖：

```bash
python -m pip install -r requirements.lock.txt
python -m starbridge --help
```

首次运行生成的 `config.toml`、数据库、邮件凭据、备份和运行缓存应保留在本机，不要提交。开发时请使用单独的测试配置与端口。

## 修改与验证

从 `main` 创建分支，将一个问题的相关改动放在同一个 Pull Request 中。描述问题、改动后的行为，以及实际执行的验证。

```bash
python -m unittest discover -s tests -q
git diff --check
```

Python 行为改动应运行相关测试；管理面板改动请检查桌面与手机尺寸，以及键盘操作。游戏端改动应按对应桥接目录中的构建与验证脚本检查目标版本；未做真实服务端验证时，请在 Pull Request 中说明。文档与低影响样式改动不需要新增重复实现的测试。

独立官网可单独构建：

```bash
python starbridge-website/build.py --output website.zip
```

构建完整发布包请参阅 [版本发布说明](https://github.com/AlancoSage/StarBridge/blob/main/docs/updates.md)。已正式发布的附件不应覆盖，行为变更需在新版本中发布。

## 许可证

提交贡献表示你有权提供这些内容，并同意以项目的 **AGPL-3.0-or-later** 许可证发布。引入第三方代码时请保留其版权与许可声明，并更新 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
