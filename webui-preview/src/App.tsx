import { useMotionPreference } from "@/components/MotionPreference";
import { useConsoleAuth } from "@/components/ConsoleAuth";
import { useEffect, useState } from "react";
import type { ComponentType, ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  ArrowRight,
  ArrowUpRight,
  Bell,
  Check,
  CheckCheck,
  ChevronRight,
  CircleHelp,
  Clock3,
  Command,
  GitBranch,
  Image,
  LayoutDashboard,
  LogOut,
  MessageCircle,
  Moon,
  PlugZap,
  RotateCcw,
  Server,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  Terminal,
  Users,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { FloatingDock } from "@/components/ui/floating-dock";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import BackgroundSwitcher from "@/components/BackgroundSwitcher";
import ServersPage from "@/pages/ServersPage";
import CommandsPage from "@/pages/CommandsPage";
import PlayersPage from "@/pages/PlayersPage";
import WebsiteSettings from "@/components/WebsiteSettings";

type Page = "overview" | "servers" | "commands" | "players" | "settings";
type Icon = ComponentType<{ className?: string }>;
const pages: { id: Page; label: string; en: string; icon: Icon }[] = [
  { id: "overview", label: "运行总览", en: "OVERVIEW", icon: LayoutDashboard },
  { id: "servers", label: "服务器", en: "SERVERS", icon: Server },
  { id: "commands", label: "指令中心", en: "COMMANDS", icon: Terminal },
  { id: "players", label: "玩家管理", en: "PLAYERS", icon: Users },
  { id: "settings", label: "控制台设置", en: "SETTINGS", icon: Settings2 },
];

function currentPage(): Page {
  return (
    pages.find((page) => "#" + page.id === location.hash)?.id ?? "overview"
  );
}

export default function App() {
  const { identity, signOut } = useConsoleAuth();
  const { reduced, enabled, toggleMotion } = useMotionPreference();
  // A single-frame target interrupts an in-flight animation with the same endpoint.
  const pageMotion = {
    initial: { opacity: reduced ? 1 : 0, y: reduced ? 0 : 16 },
    animate: { opacity: reduced ? [1] : 1, y: reduced ? [0] : 0 },
    transition: { duration: reduced ? 0 : 0.42, ease: "easeOut" as const },
  };
  const [page, setPage] = useState<Page>(currentPage);
  const [playersVisited, setPlayersVisited] = useState(
    () => currentPage() === "players",
  );
  const [settingsVisited, setSettingsVisited] = useState(
    () => currentPage() === "settings",
  );
  useEffect(() => {
    if (page === "players") setPlayersVisited(true);
    if (page === "settings") setSettingsVisited(true);
  }, [page]);
  const realPage = page === "players" || page === "settings";
  const [dark, setDark] = useState(() => {
    try {
      return localStorage.getItem("vexbot.cdk.preview.theme") === "dark";
    } catch {
      return false;
    }
  });
  const [notice, setNotice] = useState("");
  const [replay, setReplay] = useState(0);
  const [notifications, setNotifications] = useState(false);
  const active = pages.find((item) => item.id === page)!;
  const go = (next: Page) => {
    location.hash = next;
    setPage(next);
    window.scrollTo({ top: 0 });
  };
  useEffect(() => {
    const handler = () => setPage(currentPage());
    addEventListener("hashchange", handler);
    return () => removeEventListener("hashchange", handler);
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
    try {
      localStorage.setItem("vexbot.cdk.preview.theme", dark ? "dark" : "light");
    } catch {
      /* Theme still works in memory. */
    }
  }, [dark]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 3500);
    return () => clearTimeout(timer);
  }, [notice]);
  const dockItems = pages.map(({ id, label, icon: NavIcon }) => ({
    title: label,
    icon: (
      <NavIcon
        className={
          "h-full w-full " +
          (id === page ? "text-foreground" : "text-muted-foreground")
        }
      />
    ),
    href: "#" + id,
    active: id === page,
    onClick: () => go(id),
  }));
  dockItems.splice(3, 0, {
    title: "divider",
    icon: <span />,
    href: "",
    active: false,
    onClick: () => {},
  });

  return (
    <>
      <a
        className="skip-link"
        href="#workspace"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("workspace")?.focus();
        }}
      >
        跳转到内容
      </a>
      <header className="app-header">
        <div className="header-inner">
          <a href="#overview" className="brand-link" aria-label="VexBot 首页">
            <img src="/mark.svg" alt="" width="32" height="32" />
            <strong className="max-[420px]:hidden">VexBot</strong>
          </a>
          <span className="header-divider" />
          <span className="header-breadcrumb">
            工作空间 <ChevronRight className="size-3" />
            <span>{active.label}</span>
          </span>
          <Badge variant="secondary" className="preview-badge">
            <span className="size-1.5 rounded-full bg-amber-500" />
            {realPage ? "后台管理" : "交互预览"}
          </Badge>
          <div className="header-actions">
            <BackgroundSwitcher />
            <Button
              variant="ghost"
              className="motion-toggle"
              aria-label="动画效果"
              aria-pressed={enabled}
              title={enabled ? "关闭动画" : "开启动画"}
              onClick={toggleMotion}
            >
              <Sparkles />
              <span className="motion-toggle-label">动画</span>
              <span className="motion-toggle-state" aria-hidden="true">
                {enabled ? "开" : "关"}
              </span>
            </Button>
            <a
              href="https://github.com/AlancoSage/StarBridge"
              target="_blank"
              rel="noreferrer"
              className="icon-link"
              aria-label="VexBot GitHub"
            >
              <GitBranch className="size-4" />
            </a>
            <Button
              variant="ghost"
              size="icon"
              aria-label={dark ? "切换浅色主题" : "切换深色主题"}
              onClick={() => setDark(!dark)}
            >
              {dark ? <Sun /> : <Moon />}
            </Button>
            <div className="relative">
              <Button
                variant="ghost"
                size="icon"
                aria-label="查看通知"
                aria-expanded={notifications}
                onClick={() => setNotifications(!notifications)}
              >
                <Bell />
                <span className="notification-dot" />
              </Button>
              <AnimatePresence>
                {notifications && (
                  <motion.section
                    className="notification-panel"
                    initial={{
                      opacity: 0,
                      y: reduced ? 0 : -8,
                      scale: reduced ? 1 : 0.97,
                    }}
                    animate={{
                      opacity: reduced ? [1] : 1,
                      y: reduced ? [0] : 0,
                      scale: reduced ? [1] : 1,
                    }}
                    exit={{ opacity: 0, y: reduced ? 0 : -6 }}
                    transition={{ duration: reduced ? 0 : 0.18 }}
                  >
                    <div className="flex items-center justify-between">
                      <strong>通知</strong>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="关闭通知"
                        onClick={() => setNotifications(false)}
                      >
                        <X />
                      </Button>
                    </div>
                    <p>
                      <CheckCheck className="size-4 text-emerald-600" />
                      已统一登录 VexBot 控制台
                    </p>
                    <small>
                      各页面共用此账号；玩家管理与网站设置连接真实后台，其他功能仍为交互预览。
                    </small>
                  </motion.section>
                )}
              </AnimatePresence>
            </div>
            <button
              className="user-avatar"
              aria-label={`当前账号 ${identity.username}，查看控制台设置`}
              title={`当前账号：${identity.username}`}
              onClick={() => go("settings")}
            >
              {identity.username.slice(0, 1).toUpperCase()}
            </button>
            <span
              className="hidden max-w-24 truncate text-xs text-muted-foreground xl:block"
              title={identity.username}
            >
              {identity.username}
            </span>
            <Button
              variant="ghost"
              size="icon"
              aria-label="退出登录"
              title="退出登录"
              onClick={() => void signOut()}
              className="xl:w-auto xl:px-3"
            >
              <LogOut />
              <span className="hidden text-xs xl:inline">退出登录</span>
            </Button>
          </div>
        </div>
      </header>

      <main
        id="workspace"
        className="workspace"
        tabIndex={-1}
        data-motion={reduced ? "reduced" : "full"}
      >
        <nav className="page-navigation" aria-label="页面导航">
          {pages.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => go(id)}
              aria-current={page === id ? "page" : undefined}
            >
              {page === id && (
                <motion.span
                  className="nav-active-indicator"
                  layoutId={reduced ? undefined : "page-nav-indicator"}
                  aria-hidden="true"
                  transition={{
                    type: "spring",
                    stiffness: 400,
                    damping: 32,
                    duration: reduced ? 0 : undefined,
                  }}
                />
              )}
              <span className="nav-label">{label}</span>
            </button>
          ))}
        </nav>
        <motion.div key={page} className="page-heading" {...pageMotion}>
          <div>
            <div className="section-eyebrow">VEXBOT / {active.en}</div>
            <h1>
              {page === "overview" ? "让社区的每一刻，都在线。" : active.label}
            </h1>
            <p>
              {page === "players"
                ? "管理真实玩家档案、账号绑定和游戏操作。"
                : page === "settings"
                  ? "配置网站接入和官网信息，调整控制台预览偏好。"
                  : page === "overview"
                    ? "服务器、玩家与消息，在一个地方井然有序。"
                    : "管理你的游戏社区，让连接更简单。"}
            </p>
          </div>
          <div className="heading-status">
            {!realPage && <span className="status-dot" />}
            <span>{realPage ? "本机 VexBot 后台" : "预览环境运行中"}</span>
            <span className="text-muted-foreground">/</span>
            <span>
              {page === "settings"
                ? "官网设置可保存"
                : page === "players"
                  ? "账号权限校验"
                  : "示例数据"}
            </span>
          </div>
        </motion.div>

        {page === "overview" && (
          <motion.div
            key={`overview-${replay}`}
            {...pageMotion}
            className="page-content"
            data-page="overview"
          >
            <Overview
              go={go}
              notify={setNotice}
              replay={() => setReplay((value) => value + 1)}
            />
          </motion.div>
        )}
        <motion.div
          hidden={page !== "servers"}
          className="page-content"
          data-page="servers"
          initial={false}
          animate={{
            opacity: page === "servers" ? (reduced ? [1] : 1) : 0,
            y: reduced ? [0] : page === "servers" ? 0 : 16,
          }}
          transition={pageMotion.transition}
        >
          <ServersPage notify={setNotice} />
        </motion.div>
        <motion.div
          hidden={page !== "commands"}
          className="page-content"
          data-page="commands"
          initial={false}
          animate={{
            opacity: page === "commands" ? (reduced ? [1] : 1) : 0,
            y: reduced ? [0] : page === "commands" ? 0 : 16,
          }}
          transition={pageMotion.transition}
        >
          <CommandsPage notify={setNotice} />
        </motion.div>
        <motion.div
          hidden={page !== "players"}
          initial={false}
          animate={{
            opacity: page === "players" ? (reduced ? [1] : 1) : 0,
            y: reduced ? [0] : page === "players" ? 0 : 16,
          }}
          transition={pageMotion.transition}
          className="page-content"
          data-page="players"
        >
          {(playersVisited || page === "players") && (
            <PlayersPage notify={setNotice} active={page === "players"} />
          )}
        </motion.div>
        <motion.div
          hidden={page !== "settings"}
          initial={false}
          animate={{
            opacity: page === "settings" ? (reduced ? [1] : 1) : 0,
            y: reduced ? [0] : page === "settings" ? 0 : 16,
          }}
          transition={pageMotion.transition}
          className="page-content"
          data-page="settings"
        >
          {(settingsVisited || page === "settings") && (
            <Settings
              notify={setNotice}
              dark={dark}
              toggleTheme={() => setDark(!dark)}
              active={page === "settings"}
            />
          )}
        </motion.div>

        <footer className="workspace-footer">
          <span>
            VexBot <span className="mx-2">·</span> 你的社区，连接在一起
          </span>
          <a
            href="https://github.com/linux-do/cdk"
            target="_blank"
            rel="noreferrer"
          >
            基于 LINUX DO CDK 组件 <ArrowUpRight className="size-3" />
          </a>
        </footer>
      </main>
      <nav className="dock-position" aria-label="快捷导航">
        <FloatingDock
          items={dockItems}
          desktopClassName="preview-dock"
          mobileClassName="mobile-dock"
          mobileButtonClassName="mobile-dock-button"
        />
      </nav>
      <AnimatePresence>
        {notice && (
          <motion.div
            className="preview-toast"
            role="status"
            initial={{ opacity: 0, y: reduced ? 0 : 14 }}
            animate={{ opacity: reduced ? [1] : 1, y: reduced ? [0] : 0 }}
            exit={{ opacity: 0, y: reduced ? 0 : 8 }}
            transition={{ duration: reduced ? 0 : 0.22 }}
          >
            <Check className="size-4 text-emerald-600" />
            <span>{notice}</span>
            <button aria-label="关闭提示" onClick={() => setNotice("")}>
              <X className="size-4" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

function Overview({
  go,
  notify,
  replay,
}: {
  go: (page: Page) => void;
  notify: (text: string) => void;
  replay: () => void;
}) {
  const [range, setRange] = useState(7);
  const [tab, setTab] = useState("activity");
  const { reduced } = useMotionPreference();
  const metrics = [
    {
      title: "在线玩家",
      value: "24",
      unit: "人",
      change: "+6",
      desc: "较昨日同时段",
      icon: Users,
      positive: true,
    },
    {
      title: "游戏服务器",
      value: "2",
      unit: "/ 3",
      change: "正常",
      desc: "1 台服务器离线",
      icon: Server,
      positive: false,
    },
    {
      title: "今日消息",
      value: "1,286",
      unit: "条",
      change: "+18.6%",
      desc: "群服消息双向同步",
      icon: MessageCircle,
      positive: true,
    },
    {
      title: "已绑定玩家",
      value: "168",
      unit: "人",
      change: "+12",
      desc: "本周新绑定",
      icon: ShieldCheck,
      positive: true,
    },
  ];
  const time = new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    timeZone: "Asia/Shanghai",
  }).format(new Date());
  return (
    <div className="space-y-6">
      <div className="overview-toolbar">
        <div className="pill-tabs" aria-label="总览内容">
          {[
            ["activity", "运行概况"],
            ["messages", "消息动态"],
            ["connections", "接入状态"],
          ].map(([value, label]) => (
            <button
              key={value}
              aria-pressed={tab === value}
              onClick={() => setTab(value)}
            >
              {tab === value && (
                <motion.span
                  className="pill-active-indicator"
                  layoutId={reduced ? undefined : "overview-tab-indicator"}
                  aria-hidden="true"
                  transition={{
                    type: "spring",
                    stiffness: 420,
                    damping: 34,
                    duration: reduced ? 0 : undefined,
                  }}
                />
              )}
              <span className="pill-label">{label}</span>
            </button>
          ))}
        </div>
        <div className="overview-time-actions">
          <span className="text-xs text-muted-foreground flex items-center gap-2">
            <Clock3 className="size-3.5" />
            {time} · 实时演示
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="replay-motion"
            onClick={replay}
            disabled={reduced}
          >
            <RotateCcw />
            重播动画
          </Button>
        </div>
      </div>
      <div className="metrics-grid">
        {metrics.map(
          (
            { title, value, unit, change, desc, icon: MetricIcon, positive },
            index,
          ) => (
            <motion.section
              key={title}
              className="metric-card"
              initial={{ opacity: reduced ? 1 : 0, y: reduced ? 0 : 22 }}
              animate={{ opacity: reduced ? [1] : 1, y: reduced ? [0] : 0 }}
              transition={{
                duration: reduced ? 0 : 0.48,
                delay: reduced ? 0 : 0.08 + index * 0.09,
                ease: "easeOut",
              }}
              whileHover={
                reduced ? undefined : { y: -4, transition: { duration: 0.18 } }
              }
            >
              <div className="flex items-center justify-between">
                <span>{title}</span>
                <div className="metric-icon">
                  <MetricIcon className="size-3.5" />
                </div>
              </div>
              <div className="metric-value">
                <AnimatedNumber value={Number(value.replaceAll(",", ""))} />
                <small>{unit}</small>
              </div>
              <div className="metric-description">
                <span>{desc}</span>
                <span
                  className={
                    positive ? "text-emerald-600 dark:text-emerald-400" : ""
                  }
                >
                  {positive && <ArrowUpRight className="size-3" />}
                  {change}
                </span>
              </div>
            </motion.section>
          ),
        )}
      </div>

      <motion.div
        key={tab}
        className="overview-tab-content"
        initial={{ opacity: reduced ? 1 : 0, y: reduced ? 0 : 12 }}
        animate={{ opacity: reduced ? [1] : 1, y: reduced ? [0] : 0 }}
        transition={{ duration: reduced ? 0 : 0.35 }}
      >
        {tab === "activity" ? (
          <div className="chart-grid">
            <section className="soft-panel chart-panel">
              <div className="panel-title">
                <div>
                  <h2>社区活跃趋势</h2>
                  <p>每一次互动，都是社区活力的回响。</p>
                </div>
                <div className="pill-tabs range-tabs" aria-label="趋势时间范围">
                  {[7, 15, 30].map((days) => (
                    <button
                      key={days}
                      aria-pressed={range === days}
                      onClick={() => setRange(days)}
                    >
                      {range === days && (
                        <motion.span
                          className="pill-active-indicator"
                          layoutId={reduced ? undefined : "range-tab-indicator"}
                          aria-hidden="true"
                          transition={{
                            type: "spring",
                            stiffness: 420,
                            damping: 34,
                            duration: reduced ? 0 : undefined,
                          }}
                        />
                      )}
                      <span className="pill-label">{days}天</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="chart-summary">
                <strong>
                  <AnimatedNumber
                    value={range === 7 ? 8432 : range === 15 ? 17926 : 36814}
                  />
                </strong>
                <span>条互动消息</span>
                <Badge variant="secondary" className="growth-badge">
                  <ArrowUpRight />
                  12.8%
                </Badge>
              </div>
              <ActivityChart range={range} />
              <div className="chart-legend">
                <span>
                  <i className="bg-foreground" />
                  群聊消息
                </span>
                <span>
                  <i className="bg-emerald-500" />
                  游戏消息
                </span>
                <span className="ml-auto">示例统计</span>
              </div>
            </section>
            <ConnectionCard go={go} />
          </div>
        ) : tab === "messages" ? (
          <section className="soft-panel">
            <div className="panel-title">
              <div>
                <h2>消息动态</h2>
                <p>最近的群服同步与指令回复示例。</p>
              </div>
              <MessageCircle className="size-4 text-muted-foreground" />
            </div>
            {[
              ["13:28:06", "群聊 → 生存服", "Alex：今天一起去探索新的地图吗？"],
              ["13:27:42", "生存服 → 群聊", "Steve 完成了进度「钻石！」"],
              ["13:26:18", "指令回复", "在线 · 已发送服务器在线列表图片"],
            ].map(([time, source, text]) => (
              <div className="message-row" key={time}>
                <span className="message-time">{time}</span>
                <div>
                  <small>{source}</small>
                  <p>{text}</p>
                </div>
                <CheckCheck className="size-4 text-muted-foreground" />
              </div>
            ))}
          </section>
        ) : (
          <section className="soft-panel">
            <div className="panel-title">
              <div>
                <h2>接入概况</h2>
                <p>所有连接状态均为演示数据。</p>
              </div>
              <PlugZap className="size-4" />
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              {[
                ["QQ 官方机器人", "已连接"],
                ["OneBot 11", "未启用"],
                ["社区官网", "未接入"],
              ].map(([name, status]) => (
                <div className="connection-tile" key={name}>
                  <PlugZap className="size-5 text-muted-foreground" />
                  <h3>{name}</h3>
                  <p>{status}</p>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => go("settings")}
                  >
                    接入设置
                    <ArrowRight />
                  </Button>
                </div>
              ))}
            </div>
          </section>
        )}
      </motion.div>

      <div className="bottom-grid">
        <section className="soft-panel server-overview">
          <div className="panel-title">
            <div className="flex items-center gap-2">
              <Server className="size-4" />
              <h2>服务器概况</h2>
              <Badge variant="secondary" className="rounded-full">
                3
              </Badge>
            </div>
            <button className="text-action" onClick={() => go("servers")}>
              管理服务器
              <ArrowRight className="size-3.5" />
            </button>
          </div>
          <div className="table-scroll">
            <table className="overview-table">
              <thead>
                <tr>
                  <th>服务器</th>
                  <th>状态</th>
                  <th>在线玩家</th>
                  <th>TPS</th>
                  <th className="text-right">延迟</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["生存服", "Paper · 1.21.1", "18", "20.0", "12 ms", true],
                  ["创造服", "Fabric · 1.21.1", "6", "19.9", "18 ms", true],
                  ["冒险服", "NeoForge · 1.21.1", "0", "—", "—", false],
                ].map(([name, version, count, tps, ping, online]) => (
                  <tr key={String(name)} onClick={() => go("servers")}>
                    <td>
                      <div className="server-table-name">
                        <span
                          className={
                            "server-glyph " + (online ? "" : "offline")
                          }
                        >
                          <Server className="size-4" />
                        </span>
                        <div>
                          <strong>VexBot {name}</strong>
                          <small>{version}</small>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span
                        className={"status-label " + (online ? "online" : "")}
                      >
                        <i />
                        {online ? "在线" : "离线"}
                      </span>
                    </td>
                    <td>
                      {count}
                      <span className="text-muted-foreground">
                        {" "}
                        /{" "}
                        {name === "生存服"
                          ? "60"
                          : name === "创造服"
                            ? "40"
                            : "30"}
                      </span>
                    </td>
                    <td>{tps}</td>
                    <td className="text-right text-muted-foreground">{ping}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="soft-panel quick-panel">
          <div className="panel-title">
            <div className="flex items-center gap-2">
              <Command className="size-4" />
              <h2>常用操作</h2>
            </div>
            <Sparkles className="size-4 text-muted-foreground" />
          </div>
          <QuickAction
            icon={Terminal}
            title="管理游戏指令"
            desc="让日常操作，一句话完成"
            onClick={() => go("commands")}
          />
          <QuickAction
            icon={Image}
            title="预览图片回复"
            desc="把服务器状态，变成一张好看的图"
            onClick={() => {
              go("commands");
              notify("点击指令的「预览」即可查看图片效果");
            }}
          />
          <QuickAction
            icon={Users}
            title="查看绑定玩家"
            desc="连接游戏身份与群聊账号"
            onClick={() => go("players")}
          />
        </section>
      </div>
      <div className="tip-line">
        <CircleHelp className="size-3.5" />
        <span>试试底部悬浮导航，快速前往你想去的地方。</span>
        <span className="ml-auto hidden sm:inline">
          所有操作仅在预览环境生效
        </span>
      </div>
    </div>
  );
}

function ActivityChart({ range }: { range: number }) {
  const [hover, setHover] = useState(false);
  const { reduced } = useMotionPreference();
  const main =
    range === 7
      ? "M0 148 C28 148 31 175 65 158 S108 72 143 94 S181 142 215 108 S258 105 288 70 S328 113 358 75 S408 94 438 41 S487 67 518 30 S552 62 580 25"
      : range === 15
        ? "M0 157 C35 150 52 100 85 120 S138 63 170 107 S233 69 265 90 S325 43 365 58 S431 22 462 56 S529 30 580 15"
        : "M0 165 C38 170 57 123 98 135 S155 83 200 106 S260 48 298 72 S354 28 391 50 S462 7 494 36 S550 12 580 9";
  const second =
    "M0 178 C38 178 47 165 82 170 S143 126 177 148 S231 133 265 140 S324 112 358 134 S414 99 449 111 S521 76 551 94 S568 88 580 82";
  return (
    <div
      className="activity-chart"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div className="chart-y">
        <span>1,500</span>
        <span>1,000</span>
        <span>500</span>
        <span>0</span>
      </div>
      <div className="chart-plot">
        <svg
          viewBox="0 0 580 206"
          preserveAspectRatio="none"
          role="img"
          aria-label={`最近${range}天群聊与游戏消息的演示趋势图`}
        >
          <defs>
            <linearGradient id="area-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="currentColor" stopOpacity=".13" />
              <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[15, 75, 135, 195].map((y) => (
            <line
              key={y}
              x1="0"
              x2="580"
              y1={y}
              y2={y}
              stroke="currentColor"
              strokeOpacity=".08"
              strokeDasharray="3 5"
            />
          ))}
          <motion.g key={range} data-chart-animation="lines">
            <motion.path
              d={main + " L580 206 L0 206 Z"}
              fill="url(#area-fill)"
              initial={{ opacity: reduced ? 1 : 0 }}
              animate={{ opacity: reduced ? [1] : 1 }}
              transition={{
                duration: reduced ? 0 : 0.8,
                delay: reduced ? 0 : 0.2,
              }}
            />
            <motion.path
              d={second}
              fill="none"
              stroke="#10b981"
              strokeWidth="2"
              initial={{ pathLength: reduced ? 1 : 0 }}
              animate={{ pathLength: reduced ? [1] : 1 }}
              transition={{
                duration: reduced ? 0 : 1.15,
                ease: "easeInOut",
                delay: reduced ? 0 : 0.12,
              }}
            />
            <motion.path
              d={main}
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              initial={{ pathLength: reduced ? 1 : 0 }}
              animate={{ pathLength: reduced ? [1] : 1 }}
              transition={{ duration: reduced ? 0 : 1.15, ease: "easeInOut" }}
            />
          </motion.g>
        </svg>
        {hover && (
          <div className="chart-tooltip">
            群聊 1,286 条 · 游戏 642 条<span>示例数据</span>
          </div>
        )}
        <div className="chart-x">
          {["周一", "周二", "周三", "周四", "周五", "周六", "周日"].map(
            (day) => (
              <span key={day}>{day}</span>
            ),
          )}
        </div>
      </div>
    </div>
  );
}

function ConnectionCard({ go }: { go: (page: Page) => void }) {
  return (
    <section className="soft-panel connection-panel">
      <div className="panel-title">
        <h2>机器人连接</h2>
        <span className="status-label online">
          <i />
          已连接
        </span>
      </div>
      <div className="bot-identity">
        <div className="bot-icon">
          <img src="/mark.svg" alt="VexBot" />
        </div>
        <strong>VexBot</strong>
        <p>你的游戏社区小助手</p>
        <Badge variant="outline" className="rounded-full">
          <ShieldCheck />
          QQ 官方机器人
        </Badge>
      </div>
      <div className="connection-details">
        <div>
          <span>连接方式</span>
          <strong>WebSocket</strong>
        </div>
        <div>
          <span>运行时长</span>
          <strong>2 天 8 小时</strong>
        </div>
        <div>
          <span>消息延迟</span>
          <strong className="text-emerald-600 dark:text-emerald-400">
            32 ms
          </strong>
        </div>
      </div>
      <Button
        variant="outline"
        className="w-full rounded-xl"
        onClick={() => go("settings")}
      >
        管理连接
        <ArrowUpRight />
      </Button>
    </section>
  );
}

function QuickAction({
  icon: ActionIcon,
  title,
  desc,
  onClick,
}: {
  icon: Icon;
  title: string;
  desc: string;
  onClick: () => void;
}) {
  return (
    <button className="quick-action" onClick={onClick}>
      <span>
        <ActionIcon className="size-4" />
      </span>
      <div>
        <strong>{title}</strong>
        <p>{desc}</p>
      </div>
      <ChevronRight className="size-4 text-muted-foreground" />
    </button>
  );
}

const initialSettings = {
  name: "VexBot",
  connection: "official",
  images: true,
  sync: true,
  alerts: false,
};
function Settings({
  notify,
  dark,
  toggleTheme,
  active,
}: {
  notify: (text: string) => void;
  dark: boolean;
  toggleTheme: () => void;
  active: boolean;
}) {
  const [saved, setSaved] = useState(() => {
    try {
      const value = JSON.parse(
        localStorage.getItem("vexbot.cdk.preview.settings") || "null",
      );
      return value &&
        typeof value.name === "string" &&
        ["official", "onebot"].includes(value.connection) &&
        ["images", "sync", "alerts"].every(
          (key) => typeof value[key] === "boolean",
        )
        ? (Object.fromEntries(
            Object.keys(initialSettings).map((key) => [key, value[key]]),
          ) as typeof initialSettings)
        : initialSettings;
    } catch {
      return initialSettings;
    }
  });
  const [draft, setDraft] = useState(saved);
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  const update = (key: keyof typeof initialSettings, value: string | boolean) =>
    setDraft((previous) => ({ ...previous, [key]: value }));
  return (
    <div className="grid gap-5">
      <WebsiteSettings notify={notify} active={active} />
      <form
        className="settings-grid"
        onSubmit={(event) => {
          event.preventDefault();
          if (!draft.name.trim()) return;
          try {
            localStorage.setItem(
              "vexbot.cdk.preview.settings",
              JSON.stringify(draft),
            );
          } catch {
            notify("浏览器存储不可用，本次预览设置仅在当前页面生效");
            setSaved(draft);
            return;
          }
          setSaved(draft);
          notify("预览设置已保存到此浏览器");
        }}
      >
        <section className="soft-panel">
          <div className="panel-title">
            <div>
              <h2>界面预览</h2>
              <p>本区域的接入与消息选项用于预览控制台效果。</p>
            </div>
            <Settings2 className="size-4 text-muted-foreground" />
          </div>
          <label className="field-label" htmlFor="preview-name">
            机器人显示名称
          </label>
          <Input
            id="preview-name"
            value={draft.name}
            onChange={(event) => update("name", event.target.value)}
            required
            maxLength={40}
          />
          <div className="field-label mt-6" id="connection-label">
            机器人接入方式
          </div>
          <div
            className="option-grid"
            role="group"
            aria-labelledby="connection-label"
          >
            {[
              ["official", "QQ 官方机器人", "官方接口 · WebSocket 接入"],
              ["onebot", "OneBot 11", "连接兼容的机器人客户端"],
            ].map(([value, title, desc]) => (
              <button
                type="button"
                key={value}
                className={
                  "option-tile " +
                  (draft.connection === value ? "selected" : "")
                }
                aria-pressed={draft.connection === value}
                onClick={() => update("connection", value)}
              >
                <PlugZap className="size-5" />
                <strong>{title}</strong>
                <small>{desc}</small>
                {draft.connection === value && (
                  <Check className="option-check size-4" />
                )}
              </button>
            ))}
          </div>
        </section>
        <section className="soft-panel">
          <div className="panel-title">
            <div>
              <h2>消息与外观</h2>
              <p>让每一次回复都恰到好处。</p>
            </div>
            <Sparkles className="size-4 text-muted-foreground" />
          </div>
          <SettingRow title="指令图片回复" desc="允许指定指令将回复渲染成图片">
            <Switch
              aria-label="指令图片回复"
              checked={draft.images}
              onCheckedChange={(value) => update("images", value)}
            />
          </SettingRow>
          <SettingRow title="群服消息同步" desc="在游戏服务器与群聊间同步消息">
            <Switch
              aria-label="群服消息同步"
              checked={draft.sync}
              onCheckedChange={(value) => update("sync", value)}
            />
          </SettingRow>
          <SettingRow title="离线提醒" desc="服务器连接中断时发送提醒">
            <Switch
              aria-label="离线提醒"
              checked={draft.alerts}
              onCheckedChange={(value) => update("alerts", value)}
            />
          </SettingRow>
          <SettingRow title="深色模式" desc="切换预览界面的明暗主题">
            <Switch
              aria-label="深色模式"
              checked={dark}
              onCheckedChange={toggleTheme}
            />
          </SettingRow>
          <div className="settings-note">
            <ShieldCheck className="size-4 shrink-0" />
            <span>
              本区域只保存预览偏好；上方的网站接入设置独立保存到后台。
            </span>
          </div>
        </section>
        <div className="settings-save">
          <span className="flex items-center gap-2 text-xs text-muted-foreground">
            {dirty ? (
              <>
                <span className="size-1.5 rounded-full bg-amber-500" />
                有尚未保存的预览设置
              </>
            ) : (
              <>
                <CheckCheck className="size-4" />
                预览设置已保存
              </>
            )}
          </span>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!dirty}
              onClick={() => setDraft(saved)}
            >
              撤销更改
            </Button>
            <Button type="submit" disabled={!dirty}>
              保存预览设置
              <ArrowRight />
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}

function SettingRow({
  title,
  desc,
  children,
}: {
  title: string;
  desc: string;
  children: ReactNode;
}) {
  return (
    <div className="setting-row">
      <div>
        <strong>{title}</strong>
        <p>{desc}</p>
      </div>
      {children}
    </div>
  );
}
