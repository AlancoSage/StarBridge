import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import {
  ArrowUpRight,
  Check,
  ChevronRight,
  Command,
  Image,
  MessageSquare,
  Plus,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type BotCommand = {
  id: string;
  trigger: string;
  description: string;
  enabled: boolean;
  image: boolean;
  kind: "builtin" | "custom";
  reply: string;
};

const initialCommands: BotCommand[] = [
  {
    id: "online",
    trigger: "在线",
    description: "查看所有服务器的在线玩家",
    enabled: true,
    image: true,
    kind: "builtin",
    reply:
      "目前有 24 位玩家在线。\nVexBot 生存服：18 / 60\nVexBot 创造服：6 / 40\nVexBot 冒险服：离线",
  },
  {
    id: "status",
    trigger: "服务器状态",
    description: "获取运行状态、延迟和玩家数量",
    enabled: true,
    image: false,
    kind: "builtin",
    reply:
      "服务器运行正常。\n已接入 3 个世界，2 个运行中。\n平均连接延迟 15 ms，当前在线 24 人。",
  },
  {
    id: "bind",
    trigger: "绑定",
    description: "将聊天账号与游戏身份关联",
    enabled: true,
    image: false,
    kind: "builtin",
    reply:
      "在游戏中获取绑定码，然后发送：\n绑定 你的绑定码\n\n这是绑定流程演示，不会修改真实账号。",
  },
  {
    id: "help",
    trigger: "帮助",
    description: "展示可用指令和快速使用说明",
    enabled: true,
    image: false,
    kind: "builtin",
    reply:
      "欢迎使用 VexBot。\n在线 — 查看在线玩家\n服务器状态 — 查看各世界状态\n绑定 — 关联你的游戏身份\n帮助 — 查看此使用说明",
  },
];

const MotionButton = motion.create(Button);

function GlassReply() {
  const reduceMotion = useReducedMotion();
  const worlds = [
    {
      name: "VexBot 生存服",
      count: 18,
      total: 60,
      players: ["Alex", "Cloud", "Momo", "Luna"],
      color: "from-emerald-400 to-teal-600",
    },
    {
      name: "VexBot 创造服",
      count: 6,
      total: 40,
      players: ["Steve", "Nori", "River"],
      color: "from-sky-400 to-indigo-600",
    },
    {
      name: "VexBot 冒险服",
      count: 0,
      total: 30,
      players: [],
      color: "from-violet-400 to-purple-600",
    },
  ];
  return (
    <div
      className="relative isolate overflow-hidden rounded-[24px] bg-[#131d35] p-5 text-white sm:p-7"
      aria-label="在线指令的玻璃风格图片预览，内容为演示数据"
    >
      <div className="pointer-events-none absolute -left-16 -top-24 -z-10 size-80 rounded-full bg-indigo-400/40 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-32 -right-24 -z-10 size-96 rounded-full bg-teal-300/25 blur-3xl" />
      <div className="pointer-events-none absolute right-12 top-16 -z-10 h-72 w-32 rotate-45 rounded-full bg-violet-400/20 blur-2xl" />
      <div className="mb-6 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <img src="/mark.svg" alt="" className="size-8 rounded-lg" />
          <span className="text-sm font-semibold tracking-wide">VexBot</span>
        </div>
        <span className="rounded-full border border-white/15 bg-white/5 px-2.5 py-1 text-[10px] tracking-widest text-white/60">
          LIVE / DEMO
        </span>
      </div>
      <div className="grid gap-4 sm:grid-cols-[0.8fr_1.5fr]">
        <motion.div
          initial={reduceMotion ? false : { opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: reduceMotion ? 0 : 0.5 }}
          className="flex flex-col justify-between rounded-[20px] border border-white/20 bg-white/[0.08] p-5 backdrop-blur-xl"
        >
          <div>
            <p className="text-xs tracking-[0.18em] text-white/50">
              OUR WORLDS, TOGETHER
            </p>
            <h3 className="mt-4 text-2xl font-semibold leading-tight tracking-tight">
              此刻，
              <br />
              世界正热闹。
            </h3>
            <p className="mt-3 text-xs leading-5 text-white/60">
              服务器在线列表
            </p>
            <div className="mt-8 flex items-baseline gap-2">
              <strong className="text-6xl font-semibold tracking-tighter">
                <AnimatedNumber value={24} />
              </strong>
              <span className="text-xs text-white/60">位玩家在线</span>
            </div>
            <div className="mt-5 h-px bg-white/15" />
            <div className="mt-5 grid grid-cols-2 gap-3">
              <div>
                <p className="text-xl font-medium">3</p>
                <p className="mt-1 text-[10px] text-white/50">接入世界</p>
              </div>
              <div>
                <p className="text-xl font-medium">2</p>
                <p className="mt-1 text-[10px] text-white/50">正在运行</p>
              </div>
            </div>
          </div>
          <div className="mt-8 text-[10px] leading-5 text-white/45">
            <span className="mr-1 inline-block size-1.5 rounded-full bg-emerald-300" />
            刚刚更新 · 本地演示数据
            <br />
            VEXBOT / SERVER ACTIVITY
          </div>
        </motion.div>
        <div className="space-y-3">
          {worlds.map((world, index) => (
            <motion.div
              key={world.name}
              initial={reduceMotion ? false : { opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{
                duration: reduceMotion ? 0 : 0.45,
                delay: reduceMotion ? 0 : 0.1 + index * 0.075,
              }}
              className="rounded-[20px] border border-white/20 bg-white/[0.09] p-4 backdrop-blur-xl"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`size-1.5 rounded-full ${index === 2 ? "bg-white/30" : "bg-emerald-300"}`}
                  />
                  <h4 className="text-sm font-semibold">{world.name}</h4>
                </div>
                <span className="rounded-lg border border-white/15 bg-black/10 px-2 py-1 text-[10px] text-white/70">
                  {index === 2
                    ? "暂时离线"
                    : `${world.count} / ${world.total} 在线`}
                </span>
              </div>
              {world.players.length > 0 ? (
                <div className="mt-4 flex flex-wrap gap-2">
                  {world.players.map((player, playerIndex) => (
                    <span
                      key={player}
                      className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/10 py-1 pr-2 pl-1"
                    >
                      <span
                        className={`flex size-6 items-center justify-center rounded bg-gradient-to-br ${world.color} text-[10px] font-bold`}
                        style={{ filter: `hue-rotate(${playerIndex * 24}deg)` }}
                      >
                        {player.slice(0, 1)}
                      </span>
                      <span className="text-[10px]">{player}</span>
                    </span>
                  ))}
                  <span className="flex items-center px-1 text-[10px] text-white/50">
                    + {world.count - world.players.length} 人
                  </span>
                </div>
              ) : (
                <p className="mt-4 text-xs text-white/40">
                  世界正在休息，期待下次相见。
                </p>
              )}
            </motion.div>
          ))}
        </div>
      </div>
      <p className="mt-5 text-right text-[9px] tracking-wide text-white/35">
        PREVIEW ONLY · 玩家名称与在线数量均为演示
      </p>
    </div>
  );
}

function GenericImageReply({ command }: { command: BotCommand }) {
  return (
    <div className="relative overflow-hidden rounded-[24px] bg-[#182437] p-6 text-white sm:p-8">
      <div className="pointer-events-none absolute -right-8 -top-16 size-64 rounded-full bg-teal-400/20 blur-3xl" />
      <div className="relative rounded-[20px] border border-white/20 bg-white/10 p-5 backdrop-blur-xl">
        <div className="flex items-center gap-2">
          <img src="/mark.svg" className="size-7 rounded-lg" alt="" />
          <span className="text-xs text-white/60">VexBot · 指令回复</span>
        </div>
        <h3 className="mt-6 break-words text-2xl font-semibold">
          {command.trigger}
        </h3>
        <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-7 text-white/85">
          {command.reply}
        </p>
        <p className="mt-8 border-t border-white/15 pt-4 text-[10px] text-white/40">
          VEXBOT / REPLY · 演示内容
        </p>
      </div>
    </div>
  );
}

export default function CommandsPage({
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
      y: reduceMotion ? 0 : -8,
      transition: { duration: reduceMotion ? 0 : 0.18, delay: 0 },
    },
    transition: {
      duration: reduceMotion ? 0 : 0.42,
      delay: reduceMotion ? 0 : Math.min(index, 5) * 0.065,
      ease: [0.22, 1, 0.36, 1] as const,
    },
  });
  const [commands, setCommands] = useState(initialCommands);
  const [query, setQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [trigger, setTrigger] = useState("");
  const [description, setDescription] = useState("");
  const [reply, setReply] = useState("");
  const [image, setImage] = useState(false);
  const [error, setError] = useState("");
  const filtered = useMemo(
    () =>
      commands.filter((command) =>
        `${command.trigger} ${command.description}`
          .toLowerCase()
          .includes(query.trim().toLowerCase()),
      ),
    [commands, query],
  );
  const preview = commands.find((command) => command.id === previewId);
  const enabledCount = commands.filter((command) => command.enabled).length;
  const imageCount = commands.filter((command) => command.image).length;

  function updateCommand(
    id: string,
    field: "enabled" | "image",
    checked: boolean,
  ) {
    setCommands((current) =>
      current.map((command) =>
        command.id === id ? { ...command, [field]: checked } : command,
      ),
    );
    const command = commands.find((entry) => entry.id === id);
    if (command)
      notify(
        field === "enabled"
          ? `「${command.trigger}」已${checked ? "启用" : "停用"}（演示）`
          : `「${command.trigger}」已切换为${checked ? "图片" : "文字"}回复（演示）`,
      );
  }

  function openAdd() {
    setTrigger("");
    setDescription("");
    setReply("");
    setImage(false);
    setError("");
    setAddOpen(true);
  }

  function addCommand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanTrigger = trigger.trim();
    if (!cleanTrigger || !reply.trim()) {
      setError("请填写触发指令和回复内容。");
      return;
    }
    if (
      commands.some(
        (command) =>
          command.trigger.toLowerCase() === cleanTrigger.toLowerCase(),
      )
    ) {
      setError("这个触发指令已经存在，请换一个。");
      return;
    }
    setCommands((current) => [
      ...current,
      {
        id: `custom-${Date.now()}`,
        trigger: cleanTrigger,
        description: description.trim() || "自定义指令回复",
        reply: reply.trim(),
        enabled: true,
        image,
        kind: "custom",
      },
    ]);
    setAddOpen(false);
    notify(`已创建演示指令「${cleanTrigger}」，刷新页面后恢复。`);
  }

  return (
    <div className="min-w-0 space-y-7">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          让每一次对话，都有恰到好处的回应。
        </p>
        <MotionButton
          onClick={openAdd}
          className="gap-2 rounded-xl"
          whileHover={reduceMotion ? undefined : { y: -2 }}
          whileTap={reduceMotion ? undefined : { scale: 0.96 }}
        >
          <Plus className="size-4" />
          新建指令
        </MotionButton>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {[
          {
            label: "可用指令",
            value: commands.length,
            icon: Command,
            note: "把常用操作交给对话",
          },
          {
            label: "已启用",
            value: enabledCount,
            icon: MessageSquare,
            note: "随时准备回应",
          },
          {
            label: "图片回复",
            value: imageCount,
            icon: Image,
            note: "更直观地呈现信息",
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
              <CardContent className="p-5">
                <div className="flex items-center justify-between">
                  <p className="text-sm text-muted-foreground">{stat.label}</p>
                  <stat.icon className="size-4 text-muted-foreground" />
                </div>
                <p className="mt-3 text-3xl font-semibold tracking-tight">
                  <AnimatedNumber value={stat.value} />
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  {stat.note}
                </p>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative w-full sm:w-80">
          <Search className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索指令或功能…"
            aria-label="搜索指令"
            className="h-10 rounded-xl pl-9 pr-9"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="清空指令搜索"
              className="absolute right-2 top-2 rounded p-1 text-muted-foreground hover:bg-muted"
            >
              <X className="size-4" />
            </button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          共 {filtered.length} 条指令
        </p>
      </div>

      <div className="max-w-full overflow-x-auto rounded-[20px] border">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="bg-muted/60 text-xs text-muted-foreground">
            <tr>
              <th className="px-5 py-4 font-medium">触发指令</th>
              <th className="px-4 py-4 font-medium">功能说明</th>
              <th className="px-4 py-4 font-medium">状态</th>
              <th className="px-4 py-4 font-medium">图片回复</th>
              <th className="px-5 py-4 text-right font-medium">预览</th>
            </tr>
          </thead>
          <tbody>
            <AnimatePresence>
              {filtered.map((command, index) => (
                <motion.tr
                  key={command.id}
                  layout={reduceMotion ? false : "position"}
                  {...enter(index)}
                  className="border-t transition-colors hover:bg-muted/20"
                >
                  <td className="px-5 py-5">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{command.trigger}</span>
                      {command.kind === "custom" && (
                        <Badge variant="outline" className="text-[10px]">
                          自定义
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
                      {command.id.startsWith("custom")
                        ? "CUSTOM REPLY"
                        : `BUILT-IN / ${command.id}`}
                    </p>
                  </td>
                  <td className="px-4 py-5 text-muted-foreground">
                    {command.description}
                  </td>
                  <td className="px-4 py-5">
                    <div className="flex items-center gap-2">
                      <Switch
                        checked={command.enabled}
                        onCheckedChange={(checked) =>
                          updateCommand(command.id, "enabled", checked)
                        }
                        aria-label={`${command.enabled ? "停用" : "启用"}${command.trigger}指令`}
                      />
                      <span className="whitespace-nowrap text-xs text-muted-foreground">
                        {command.enabled ? "已启用" : "已停用"}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-5">
                    <Switch
                      checked={command.image}
                      onCheckedChange={(checked) =>
                        updateCommand(command.id, "image", checked)
                      }
                      aria-label={`${command.trigger}图片回复`}
                    />
                  </td>
                  <td className="px-5 py-5 text-right">
                    <MotionButton
                      variant="ghost"
                      size="sm"
                      className="gap-1.5 rounded-lg"
                      onClick={() => setPreviewId(command.id)}
                      whileHover={reduceMotion ? undefined : { x: 2 }}
                      whileTap={reduceMotion ? undefined : { scale: 0.94 }}
                    >
                      预览
                      <ArrowUpRight className="size-3.5" />
                    </MotionButton>
                  </td>
                </motion.tr>
              ))}
              {filtered.length === 0 && (
                <motion.tr key="empty" {...enter()}>
                  <td colSpan={5} className="px-5 py-14 text-center">
                    <Search className="mx-auto mb-3 size-6 text-muted-foreground" />
                    <p className="font-medium">没有找到相关指令</p>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setQuery("")}
                      className="mt-3"
                    >
                      清空搜索
                      <ChevronRight className="ml-1 size-3.5" />
                    </Button>
                  </td>
                </motion.tr>
              )}
            </AnimatePresence>
          </tbody>
        </table>
      </div>

      <div className="flex flex-col gap-4 rounded-[20px] bg-muted/50 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="rounded-xl border bg-background p-2.5">
            <Sparkles className="size-4" />
          </span>
          <div>
            <h2 className="text-sm font-medium">给信息，换一种表达。</h2>
            <p className="mt-1 max-w-xl text-xs leading-5 text-muted-foreground">
              为指定指令开启图片回复，以玻璃卡片呈现在线名单和服务器状态。点击预览，看看发送后的样子。
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          className="shrink-0 gap-2 rounded-xl bg-background"
          onClick={() => setPreviewId("online")}
        >
          查看在线回复
          <Image className="size-3.5" />
        </Button>
      </div>
      <p className="flex items-start gap-2 text-xs leading-5 text-muted-foreground">
        <Check className="mt-0.5 size-3.5 shrink-0" />
        当前为交互演示。指令、开关和回复内容仅保存在本页，不会发送消息或更改生产配置。
      </p>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-[20px] p-6 gap-5 sm:max-w-lg">
          <DialogHeader className="p-0">
            <DialogTitle>新建指令</DialogTitle>
            <DialogDescription>
              设置触发词和回复内容，在预览中体验一条自己的指令。
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={addCommand} className="space-y-5">
            <div className="grid gap-2 text-sm">
              <label htmlFor="command-trigger" className="font-medium">
                触发指令
              </label>
              <Input
                id="command-trigger"
                value={trigger}
                onChange={(event) => setTrigger(event.target.value)}
                maxLength={30}
                placeholder="例如：群公告"
                required
                autoComplete="off"
              />
            </div>
            <div className="grid gap-2 text-sm">
              <label htmlFor="command-description" className="font-medium">
                功能说明
                <span className="ml-2 font-normal text-muted-foreground">
                  选填
                </span>
              </label>
              <Input
                id="command-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                maxLength={100}
                placeholder="这条指令可以做什么？"
              />
            </div>
            <div className="grid gap-2 text-sm">
              <label htmlFor="command-reply" className="font-medium">
                回复内容
              </label>
              <textarea
                id="command-reply"
                value={reply}
                onChange={(event) => setReply(event.target.value)}
                maxLength={2000}
                rows={4}
                placeholder="输入收到指令时的回复…"
                required
                className="flex w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </div>
            <div className="flex items-center justify-between gap-4 rounded-xl bg-muted/60 p-4">
              <label htmlFor="command-image" className="cursor-pointer text-sm">
                <span className="block font-medium">图片回复</span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  将文字呈现在玻璃风格卡片中
                </span>
              </label>
              <Switch
                id="command-image"
                checked={image}
                onCheckedChange={setImage}
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
              <Button type="submit">创建指令</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(preview)}
        onOpenChange={(open) => {
          if (!open) setPreviewId(null);
        }}
      >
        <DialogContent className="max-h-[92dvh] overflow-y-auto rounded-[20px] p-6 gap-5 sm:max-w-3xl">
          <DialogHeader className="p-0">
            <DialogTitle className="break-words pr-5">
              回复预览 · {preview?.trigger}
            </DialogTitle>
            <DialogDescription>
              {preview?.image ? "图片回复 · 玻璃卡片样式" : "文字回复"}
              。以下内容均为演示，不会发送到聊天群。
            </DialogDescription>
          </DialogHeader>
          {preview && (
            <>
              <div className="flex items-center justify-between gap-3 rounded-xl border p-3">
                <label
                  htmlFor="preview-image-switch"
                  className="flex items-center gap-2 text-sm"
                >
                  <Image className="size-4 text-muted-foreground" />
                  使用图片回复
                </label>
                <Switch
                  id="preview-image-switch"
                  checked={preview.image}
                  onCheckedChange={(checked) =>
                    updateCommand(preview.id, "image", checked)
                  }
                />
              </div>
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={`${preview.id}-${preview.image ? "image" : "text"}`}
                  initial={reduceMotion ? false : { opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: reduceMotion ? 0 : -8 }}
                  transition={{ duration: reduceMotion ? 0 : 0.24 }}
                >
                  {preview.image ? (
                    preview.id === "online" ? (
                      <GlassReply />
                    ) : (
                      <GenericImageReply command={preview} />
                    )
                  ) : (
                    <div className="rounded-[20px] bg-muted/60 p-5">
                      <div className="mb-4 flex items-center gap-2">
                        <img
                          src="/mark.svg"
                          alt=""
                          className="size-8 rounded-lg"
                        />
                        <span className="text-sm font-medium">VexBot</span>
                        <Badge
                          variant="outline"
                          className="ml-auto text-[10px]"
                        >
                          演示
                        </Badge>
                      </div>
                      <div className="whitespace-pre-wrap break-words rounded-xl border bg-background p-4 text-sm leading-7">
                        {preview.reply}
                      </div>
                    </div>
                  )}
                </motion.div>
              </AnimatePresence>
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs text-muted-foreground">
                  {preview.enabled
                    ? "该指令已启用"
                    : "该指令已停用，仍可预览样式"}
                </span>
                <Button
                  onClick={() => setPreviewId(null)}
                  className="rounded-xl"
                >
                  完成
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
