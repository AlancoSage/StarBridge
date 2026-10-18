import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import {
  Check,
  ChevronRight,
  Circle,
  LayoutGrid,
  List,
  Plus,
  Search,
  Server,
  Users,
  Wifi,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type GameServer = {
  id: string;
  name: string;
  identifier: string;
  version: string;
  online: boolean;
  players: number;
  capacity: number;
  latency: number;
  software: string;
  description: string;
};

const initialServers: GameServer[] = [
  {
    id: "survival",
    name: "VexBot 生存服",
    identifier: "survival",
    version: "1.21.1",
    online: true,
    players: 18,
    capacity: 60,
    latency: 12,
    software: "Paper",
    description: "一起建造、探索，留下属于大家的世界。",
  },
  {
    id: "creative",
    name: "VexBot 创造服",
    identifier: "creative",
    version: "1.21.1",
    online: true,
    players: 6,
    capacity: 40,
    latency: 18,
    software: "Fabric",
    description: "让每一个天马行空的想法都有地方落地。",
  },
  {
    id: "adventure",
    name: "VexBot 冒险服",
    identifier: "adventure",
    version: "1.21.1",
    online: false,
    players: 0,
    capacity: 30,
    latency: 0,
    software: "NeoForge",
    description: "一个新的旅程，正在准备中。",
  },
];

const fieldClass = "grid gap-2 text-sm";
const MotionButton = motion.create(Button);

function StatusBadge({ online }: { online: boolean }) {
  return (
    <Badge
      variant="outline"
      className={
        online
          ? "gap-1.5 border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-400"
          : "gap-1.5 border-border bg-muted text-muted-foreground"
      }
    >
      <span
        className={`size-1.5 rounded-full ${online ? "bg-emerald-500" : "bg-muted-foreground"}`}
      />
      {online ? "运行中" : "已离线"}
    </Badge>
  );
}

export default function ServersPage({
  notify,
}: {
  notify: (message: string) => void;
}) {
  const reduceMotion = useReducedMotion();
  const enter = (index = 0) => ({
    initial: reduceMotion ? (false as const) : { opacity: 0, y: 18 },
    whileInView: { opacity: 1, y: 0 },
    viewport: { once: true, amount: 0.1 },
    exit: {
      opacity: 0,
      y: reduceMotion ? 0 : -10,
      transition: { duration: reduceMotion ? 0 : 0.18, delay: 0 },
    },
    transition: {
      duration: reduceMotion ? 0 : 0.42,
      delay: reduceMotion ? 0 : Math.min(index, 5) * 0.065,
      ease: [0.22, 1, 0.36, 1] as const,
    },
  });
  const [servers, setServers] = useState(initialServers);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "online" | "offline">("all");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [addOpen, setAddOpen] = useState(false);
  const [selected, setSelected] = useState<GameServer | null>(null);
  const [name, setName] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [version, setVersion] = useState("1.21.1");
  const [error, setError] = useState("");
  const onlineCount = servers.filter((server) => server.online).length;
  const playerCount = servers.reduce(
    (total, server) => total + server.players,
    0,
  );
  const visibleServers = useMemo(
    () =>
      servers.filter((server) => {
        const matchesQuery =
          `${server.name} ${server.identifier} ${server.version}`
            .toLowerCase()
            .includes(query.trim().toLowerCase());
        return (
          matchesQuery &&
          (filter === "all" || server.online === (filter === "online"))
        );
      }),
    [servers, query, filter],
  );

  function openAdd() {
    setName("");
    setIdentifier("");
    setVersion("1.21.1");
    setError("");
    setAddOpen(true);
  }

  function addServer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanName = name.trim();
    const cleanIdentifier = identifier.trim().toLowerCase();
    const cleanVersion = version.trim();
    if (!cleanName || !cleanIdentifier || !cleanVersion) {
      setError("请填写服务器名称、标识和游戏版本。");
      return;
    }
    if (!/^[a-z0-9][a-z0-9_-]{1,31}$/.test(cleanIdentifier)) {
      setError(
        "标识需为 2–32 位小写字母、数字、短横线或下划线，以字母或数字开头。",
      );
      return;
    }
    if (servers.some((server) => server.identifier === cleanIdentifier)) {
      setError("这个服务器标识已经存在，请换一个。");
      return;
    }
    setServers((current) => [
      ...current,
      {
        id: cleanIdentifier,
        name: cleanName,
        identifier: cleanIdentifier,
        version: cleanVersion,
        online: false,
        players: 0,
        capacity: 40,
        latency: 0,
        software: "待连接",
        description: "新添加的演示服务器，等待游戏端连接。",
      },
    ]);
    setAddOpen(false);
    notify(`已添加演示服务器「${cleanName}」，刷新页面后恢复。`);
  }

  return (
    <div className="min-w-0 space-y-7">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          把每个世界的状态，放在一个地方。
        </p>
        <MotionButton
          onClick={openAdd}
          className="gap-2 rounded-xl"
          whileHover={reduceMotion ? undefined : { y: -2 }}
          whileTap={reduceMotion ? undefined : { scale: 0.96 }}
        >
          <Plus className="size-4" />
          添加服务器
        </MotionButton>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {[
          {
            label: "已接入服务器",
            value: servers.length,
            suffix: "个世界",
            icon: Server,
          },
          {
            label: "正在运行",
            value: onlineCount,
            suffix: `${servers.length - onlineCount} 个离线`,
            icon: Wifi,
          },
          {
            label: "在线玩家",
            value: playerCount,
            suffix: "此刻正在探索",
            icon: Users,
          },
        ].map((stat, index) => (
          <motion.div
            key={stat.label}
            {...enter(index)}
            whileHover={
              reduceMotion
                ? undefined
                : { y: -4, transition: { duration: 0.18, delay: 0 } }
            }
          >
            <Card className="h-full rounded-[20px] border-0 py-0 bg-muted/60 shadow-none">
              <CardContent className="flex items-start justify-between p-5">
                <div>
                  <p className="text-sm text-muted-foreground">{stat.label}</p>
                  <p className="mt-3 flex items-baseline gap-2 text-3xl font-semibold tracking-tight">
                    <AnimatedNumber value={stat.value} />
                    <span className="text-xs font-normal tracking-normal text-muted-foreground">
                      {stat.suffix}
                    </span>
                  </p>
                </div>
                <span className="rounded-xl bg-background p-2.5">
                  <stat.icon className="size-4 text-muted-foreground" />
                </span>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          className="flex max-w-full gap-1 rounded-xl bg-muted/70 p-1"
          aria-label="服务器状态筛选"
        >
          {(
            [
              { value: "all", label: "全部", count: servers.length },
              { value: "online", label: "在线", count: onlineCount },
              {
                value: "offline",
                label: "离线",
                count: servers.length - onlineCount,
              },
            ] as const
          ).map((tab) => (
            <MotionButton
              key={tab.value}
              size="sm"
              variant={filter === tab.value ? "secondary" : "ghost"}
              aria-pressed={filter === tab.value}
              onClick={() => setFilter(tab.value)}
              className={`gap-2 rounded-lg ${filter === tab.value ? "bg-background shadow-sm" : "text-muted-foreground"}`}
              whileHover={reduceMotion ? undefined : { y: -1 }}
              whileTap={reduceMotion ? undefined : { scale: 0.94 }}
            >
              {tab.label}
              <span className="text-xs opacity-60">{tab.count}</span>
            </MotionButton>
          ))}
        </div>
        <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto">
          <div className="relative min-w-0 flex-1 sm:w-60">
            <Search className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" />
            <Input
              aria-label="搜索服务器"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索服务器…"
              className="h-10 rounded-xl pl-9 pr-9"
            />
            {query && (
              <button
                type="button"
                aria-label="清空搜索"
                onClick={() => setQuery("")}
                className="absolute right-2 top-2 rounded p-1 text-muted-foreground hover:bg-muted"
              >
                <X className="size-4" />
              </button>
            )}
          </div>
          <div className="flex shrink-0 rounded-xl border p-1">
            <Button
              size="icon"
              variant={view === "grid" ? "secondary" : "ghost"}
              aria-label="卡片视图"
              aria-pressed={view === "grid"}
              className="size-8 rounded-lg"
              onClick={() => setView("grid")}
            >
              <LayoutGrid className="size-4" />
            </Button>
            <Button
              size="icon"
              variant={view === "list" ? "secondary" : "ghost"}
              aria-label="列表视图"
              aria-pressed={view === "list"}
              className="size-8 rounded-lg"
              onClick={() => setView("list")}
            >
              <List className="size-4" />
            </Button>
          </div>
        </div>
      </div>

      <AnimatePresence mode="wait">
        {visibleServers.length === 0 ? (
          <motion.div
            key="empty"
            {...enter()}
            className="rounded-[20px] border border-dashed p-12 text-center"
          >
            <Search className="mx-auto mb-3 size-7 text-muted-foreground" />
            <h2 className="font-medium">没有找到服务器</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              换个关键词，或者查看全部服务器。
            </p>
            <Button
              variant="outline"
              className="mt-5 rounded-xl"
              onClick={() => {
                setQuery("");
                setFilter("all");
              }}
            >
              重置筛选
            </Button>
          </motion.div>
        ) : view === "grid" ? (
          <motion.div
            key="grid"
            {...enter()}
            className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3"
          >
            <AnimatePresence mode="popLayout">
              {visibleServers.map((server, index) => (
                <motion.div
                  key={server.id}
                  layout={reduceMotion ? false : "position"}
                  {...enter(index)}
                  whileHover={
                    reduceMotion
                      ? undefined
                      : { y: -5, transition: { duration: 0.18, delay: 0 } }
                  }
                  className="min-w-0"
                >
                  <Card className="h-full min-w-0 rounded-[20px] py-0 border bg-background shadow-none transition-shadow hover:shadow-sm">
                    <CardContent className="p-5">
                      <div className="mb-6 flex items-start justify-between gap-3">
                        <span className="rounded-2xl bg-muted p-3">
                          <Server className="size-5" />
                        </span>
                        <StatusBadge online={server.online} />
                      </div>
                      <h2 className="break-words text-lg font-semibold tracking-tight">
                        {server.name}
                      </h2>
                      <p className="mt-1 break-words font-mono text-xs text-muted-foreground">
                        {server.identifier} · {server.software} {server.version}
                      </p>
                      <p className="mt-4 min-h-10 text-sm leading-6 text-muted-foreground">
                        {server.description}
                      </p>
                      <div className="mt-5 flex items-center justify-between gap-3 border-t pt-4">
                        <div>
                          <span className="text-xl font-semibold">
                            {server.players}
                          </span>
                          <span className="text-sm text-muted-foreground">
                            {" "}
                            / {server.capacity} 玩家
                          </span>
                        </div>
                        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                          <Circle
                            className={`size-2 fill-current ${server.online ? "text-emerald-500" : "text-muted-foreground"}`}
                          />
                          {server.online ? `${server.latency} ms` : "暂无连接"}
                        </span>
                      </div>
                      <div className="mt-3 h-1 overflow-hidden rounded-full bg-muted">
                        <motion.div
                          className={`h-full rounded-full ${server.online ? "bg-foreground" : "bg-muted-foreground"}`}
                          initial={reduceMotion ? false : { width: 0 }}
                          whileInView={{
                            width: `${(server.players / server.capacity) * 100}%`,
                          }}
                          viewport={{ once: true }}
                          style={{
                            width: `${(server.players / server.capacity) * 100}%`,
                          }}
                          transition={{
                            duration: reduceMotion ? 0 : 0.75,
                            delay: reduceMotion ? 0 : 0.18 + index * 0.065,
                          }}
                        />
                      </div>
                      <Button
                        variant="ghost"
                        className="mt-4 w-full justify-between rounded-xl bg-muted/50 text-xs"
                        onClick={() => setSelected(server)}
                      >
                        查看服务器
                        <ChevronRight className="size-3.5" />
                      </Button>
                    </CardContent>
                  </Card>
                </motion.div>
              ))}
            </AnimatePresence>
          </motion.div>
        ) : (
          <motion.div
            key="list"
            {...enter()}
            className="max-w-full overflow-x-auto rounded-[20px] border"
          >
            <table className="w-full min-w-[650px] text-left text-sm">
              <thead className="bg-muted/60 text-xs text-muted-foreground">
                <tr>
                  <th className="px-5 py-4 font-medium">服务器</th>
                  <th className="px-4 py-4 font-medium">状态</th>
                  <th className="px-4 py-4 font-medium">在线玩家</th>
                  <th className="px-4 py-4 font-medium">延迟</th>
                  <th className="px-5 py-4 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                <AnimatePresence>
                  {visibleServers.map((server, index) => (
                    <motion.tr
                      key={server.id}
                      layout={reduceMotion ? false : "position"}
                      {...enter(index)}
                      className="border-t"
                    >
                      <td className="px-5 py-5">
                        <div className="font-medium">{server.name}</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {server.identifier} · {server.version}
                        </div>
                      </td>
                      <td className="px-4 py-5">
                        <StatusBadge online={server.online} />
                      </td>
                      <td className="px-4 py-5">
                        {server.players}
                        <span className="text-muted-foreground">
                          {" "}
                          / {server.capacity}
                        </span>
                      </td>
                      <td className="px-4 py-5 text-muted-foreground">
                        {server.online ? `${server.latency} ms` : "—"}
                      </td>
                      <td className="px-5 py-5 text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="rounded-lg"
                          onClick={() => setSelected(server)}
                        >
                          查看详情
                          <ChevronRight className="ml-1 size-3.5" />
                        </Button>
                      </td>
                    </motion.tr>
                  ))}
                </AnimatePresence>
              </tbody>
            </table>
          </motion.div>
        )}
      </AnimatePresence>

      <p className="flex items-start gap-2 text-xs leading-5 text-muted-foreground">
        <Check className="mt-0.5 size-3.5 shrink-0" />
        以上为演示数据。添加服务器仅影响本次预览，不会连接或修改真实服务器。
      </p>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-[20px] p-6 gap-5 sm:max-w-md">
          <DialogHeader className="p-0">
            <DialogTitle>添加服务器</DialogTitle>
            <DialogDescription>
              创建一张演示服务器卡片，体验接入后的管理方式。
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={addServer} className="space-y-5">
            <div className={fieldClass}>
              <label htmlFor="server-name" className="font-medium">
                服务器名称
              </label>
              <Input
                id="server-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={60}
                placeholder="例如：VexBot 建筑服"
                autoComplete="off"
                required
              />
            </div>
            <div className={fieldClass}>
              <label htmlFor="server-identifier" className="font-medium">
                唯一标识
              </label>
              <Input
                id="server-identifier"
                value={identifier}
                onChange={(event) => setIdentifier(event.target.value)}
                maxLength={32}
                placeholder="例如：building"
                autoComplete="off"
                spellCheck={false}
                aria-describedby="server-identifier-help"
                required
              />
              <p
                id="server-identifier-help"
                className="text-xs leading-5 text-muted-foreground"
              >
                2–32 位字母、数字、短横线或下划线。
              </p>
            </div>
            <div className={fieldClass}>
              <label htmlFor="server-version" className="font-medium">
                游戏版本
              </label>
              <Input
                id="server-version"
                value={version}
                onChange={(event) => setVersion(event.target.value)}
                maxLength={30}
                placeholder="1.21.1"
                required
              />
            </div>
            {error && (
              <p
                role="alert"
                className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive"
              >
                {error}
              </p>
            )}
            <DialogFooter className="p-0">
              <Button
                variant="outline"
                type="button"
                onClick={() => setAddOpen(false)}
              >
                取消
              </Button>
              <Button type="submit">添加到预览</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-[20px] p-6 gap-5 sm:max-w-lg">
          <DialogHeader className="p-0">
            <DialogTitle className="break-words pr-5">
              {selected?.name}
            </DialogTitle>
            <DialogDescription>服务器概览 · 演示数据</DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="space-y-5">
              <div className="flex items-center justify-between rounded-2xl bg-muted/60 p-5">
                <div className="flex items-center gap-3">
                  <Server className="size-6" />
                  <span className="font-medium">连接状态</span>
                </div>
                <StatusBadge online={selected.online} />
              </div>
              <dl className="grid grid-cols-2 gap-5 text-sm">
                {[
                  ["服务器标识", selected.identifier],
                  ["游戏版本", selected.version],
                  ["服务端", selected.software],
                  ["在线玩家", `${selected.players} / ${selected.capacity}`],
                  [
                    "连接延迟",
                    selected.online ? `${selected.latency} ms` : "暂无连接",
                  ],
                  ["数据来源", "本地演示数据"],
                ].map(([label, value]) => (
                  <div key={label} className="min-w-0">
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd className="mt-1.5 break-words font-medium">{value}</dd>
                  </div>
                ))}
              </dl>
              <p className="rounded-xl border p-4 text-sm leading-6 text-muted-foreground">
                {selected.description}
              </p>
              <Button
                className="w-full rounded-xl"
                onClick={() => setSelected(null)}
              >
                完成
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
