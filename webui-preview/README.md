# VexBot WebUI 交互预览

基于 [linux-do/cdk](https://github.com/linux-do/cdk) 的前端组件和设计样式制作的 VexBot 管理界面预览。页面使用本地示例数据，可查看仪表盘、切换导航与主题、筛选服务器，并体验表单、开关和弹窗。

此预览尚未连接 VexBot 的生产 API，页面操作只影响预览状态，不会改变现有机器人配置、服务器或数据库。原有 `5800` 端口的 VexBot 服务保持独立。

## 本地运行

在本目录执行：

```powershell
npm ci
npm run dev
```

打开 <http://127.0.0.1:5801/>。已在 Node.js 24 验证；安装前端依赖需要联网。

构建并查看构建后的页面：

```powershell
npm run build
npm run preview
```

构建预览同样使用 `5801` 端口；请先停止开发服务器，再运行 `npm run preview`。

本示例只运行前端，不需要 CDK 的 Go 后端、Redis、OAuth 或第三方账号。

## 效果与验证

支持运行总览、服务器、指令中心、玩家管理和控制台设置。服务器和指令修改在本次页面会话内保留；主题与预览设置保存在当前浏览器。预览不会请求生产 API。

已通过 TypeScript 检查、生产构建及 Edge 浏览器交互检查，覆盖搜索、筛选、新建与重复标识验证、回复图片、设置保存和撤销、手机悬浮导航。1440px 桌面与 390px 手机均无页面异常或横向溢出。

![浅色总览](screenshots/overview-light.png)

[深色总览](screenshots/overview-dark.png) · [手机效果](screenshots/overview-mobile.png)

## 复用范围与许可

参考版本：[linux-do/cdk @ 6fb394a3d2d53796ef5d27b85994dd7b3b78fe2b](https://github.com/linux-do/cdk/tree/6fb394a3d2d53796ef5d27b85994dd7b3b78fe2b)。复用了该版本的 `frontend/components/ui/` 基础组件（包括 `floating-dock.tsx`）、`frontend/lib/utils.ts` 工具，以及 `frontend/app/globals.css` 中的主题变量和基础样式；具体保留的组件见本示例 `src/` 目录。

适配包括：将 Next.js 应用环境换为独立前端预览，使用 VexBot 品牌与机器人管理示例数据，替换业务导航与事件，调整导入路径，并补充适合预览的响应式布局和交互。没有接入 CDK 的兑换、支付、用户认证或其他后端业务。

这些复用部分保持原 MIT 许可，完整版权和许可声明位于 [third-party/linux-do-cdk-LICENSE.txt](third-party/linux-do-cdk-LICENSE.txt)。本项目新编写的 VexBot 页面和适配代码遵循仓库根目录的 [GNU AGPL-3.0 许可](../LICENSE)。各 npm 依赖遵循各自的许可。

本目录独立于正式 Bot 与官网部署包。构建输出包含原始许可和 npm 依赖许可清单。
