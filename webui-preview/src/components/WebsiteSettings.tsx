import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  ArrowUpRight,
  Download,
  Globe,
  LoaderCircle,
  RefreshCw,
  Save,
  ShieldCheck,
} from "lucide-react";
import { useConsoleAuth } from "@/components/ConsoleAuth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SelectControl } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { APIError } from "@/lib/players-api";
import { checkWebsiteApi, websiteApi } from "@/lib/website-api";
import type {
  WebsiteConfig,
  WebsiteDownload,
  WebsiteSettingsData,
} from "@/lib/website-api";

const contentKeys = [
  "title",
  "subtitle",
  "description",
  "rules",
  "join_address",
  "group_url",
  "accent_color",
  "secondary_color",
  "theme_mode",
  "grid_background",
] as const;
const fileNames: Record<WebsiteDownload, string> = {
  config: "config.json",
  guide: "VexBot-website-guide.md",
  project: "VexBot-website.zip",
  sdk: "VexBot-website-sdk.js",
};
const textAreaClass =
  "min-h-24 w-full resize-y rounded-xl border border-input bg-background/60 px-3 py-2 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30 disabled:opacity-50";

function settingsToSave(
  draft: WebsiteSettingsData,
  saved: WebsiteSettingsData,
): WebsiteSettingsData {
  const next = { ...draft, connection_enabled: draft.website_mode !== "none" };
  if (next.website_mode !== "provided") {
    for (const key of contentKeys) Object.assign(next, { [key]: saved[key] });
  }
  if (next.website_mode === "none") {
    next.website_url = saved.website_url;
    next.api_public_url = saved.api_public_url;
  }
  return next;
}

function sameSettings(left: WebsiteSettingsData, right: WebsiteSettingsData) {
  return (Object.keys(left) as (keyof WebsiteSettingsData)[]).every(
    (key) => left[key] === right[key],
  );
}

function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="block min-w-0 space-y-2 text-sm">
      <span className="font-medium">{label}</span>
      {children}
      {hint && (
        <span className="block text-xs leading-5 text-muted-foreground">
          {hint}
        </span>
      )}
    </label>
  );
}

function Toggle({
  label,
  detail,
  value,
  disabled,
  onChange,
}: {
  label: string;
  detail: string;
  value: boolean;
  disabled: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-5 rounded-2xl border border-border/70 bg-background/20 p-4">
      <div className="min-w-0">
        <p className="text-sm font-medium">{label}</p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p>
      </div>
      <Switch
        aria-label={label}
        checked={value}
        disabled={disabled}
        onCheckedChange={onChange}
      />
    </div>
  );
}

export default function WebsiteSettings({
  notify,
  active = true,
}: {
  notify: (message: string) => void;
  active?: boolean;
}) {
  const { token, identity, invalidate } = useConsoleAuth();
  const [baseline, setBaseline] = useState<WebsiteConfig | null>(null);
  const [draft, setDraft] = useState<WebsiteSettingsData | null>(null);
  const [error, setError] = useState("");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState("");
  const [conflict, setConflict] = useState(false);
  const [denied, setDenied] = useState(false);
  const [discard, setDiscard] = useState<"undo" | "reload" | null>(null);
  const generation = useRef(0);
  const controllers = useRef(new Set<AbortController>());
  const lock = useRef("");
  const activeRef = useRef(active);
  const tokenRef = useRef(token);
  const ownerRef = useRef(identity.owner);
  const baselineRef = useRef(baseline);
  const draftRef = useRef(draft);
  activeRef.current = active;
  tokenRef.current = token;
  ownerRef.current = identity.owner;
  baselineRef.current = baseline;
  draftRef.current = draft;

  async function task<T>(
    operation: string,
    work: (signal: AbortSignal) => Promise<T>,
    done: (value: T) => void,
  ) {
    if (lock.current || !activeRef.current || !ownerRef.current || denied)
      return;
    const epoch = generation.current;
    const requestToken = token;
    const controller = new AbortController();
    const current = () =>
      !controller.signal.aborted &&
      generation.current === epoch &&
      activeRef.current &&
      ownerRef.current &&
      tokenRef.current === requestToken;
    lock.current = operation;
    controllers.current.add(controller);
    setBusy(operation);
    setError("");
    setResult("");
    try {
      const value = await work(controller.signal);
      if (current()) done(value);
    } catch (cause) {
      if (!current()) return;
      if (cause instanceof APIError && cause.status === 401) {
        invalidate();
        return;
      }
      if (cause instanceof APIError && cause.status === 403) {
        setDenied(true);
        setBaseline(null);
        setDraft(null);
        setConflict(false);
        setDiscard(null);
        setError("当前账号无法访问网站设置，仅服主账号可以管理。");
        return;
      }
      const message =
        cause instanceof Error
          ? cause.message
          : "操作失败，请检查后台连接后重试。";
      if (
        operation === "save" &&
        cause instanceof APIError &&
        cause.status === 409
      ) {
        setConflict(true);
        setError(
          "网站设置已被其他操作更新。你的草稿已保留，请载入最新版本后再保存。",
        );
      } else if (
        operation === "save" &&
        (!(cause instanceof APIError) ||
          cause.status === 0 ||
          (cause.status >= 200 && cause.status < 300) ||
          cause.status >= 500)
      ) {
        setConflict(true);
        setError(`${message} 保存结果尚未确认，请载入最新版本核对后再保存。`);
      } else setError(message);
    } finally {
      controllers.current.delete(controller);
      if (generation.current === epoch && lock.current === operation) {
        lock.current = "";
        setBusy("");
      }
    }
  }

  function load(preserve = false) {
    const old = baselineRef.current;
    const previousDraft = draftRef.current;
    void task(
      "load",
      (signal) => websiteApi(token).get(signal),
      (config) => {
        let next = { ...config.settings };
        if (preserve && old && previousDraft) {
          const previous = settingsToSave(previousDraft, old.settings);
          for (const key of Object.keys(
            previous,
          ) as (keyof WebsiteSettingsData)[]) {
            if (
              key !== "connection_enabled" &&
              previous[key] !== old.settings[key]
            )
              Object.assign(next, { [key]: previous[key] });
          }
          next.connection_enabled = next.website_mode !== "none";
        }
        setBaseline(config);
        setDraft(next);
        setConflict(false);
        if (preserve)
          setResult("已载入最新版本，并保留你修改过的字段。请核对后保存。");
      },
    );
  }

  useEffect(() => {
    if (active && identity.owner && !baselineRef.current && !denied) load();
    return () => {
      generation.current += 1;
      controllers.current.forEach((controller) => controller.abort());
      controllers.current.clear();
      if (lock.current === "save") {
        setConflict(true);
        setError(
          "保存请求已中断，结果尚未确认。请载入最新版本核对，草稿已保留。",
        );
      }
      lock.current = "";
      setBusy("");
    };
    // The draft survives tab changes; only the first active visit fetches settings.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, token, identity.owner]);

  function update<K extends keyof WebsiteSettingsData>(
    key: K,
    value: WebsiteSettingsData[K],
  ) {
    setDraft((previous) =>
      previous
        ? {
            ...previous,
            [key]: value,
            ...(key === "website_mode"
              ? { connection_enabled: value !== "none" }
              : {}),
          }
        : previous,
    );
    setResult("");
  }

  const effective =
    baseline && draft ? settingsToSave(draft, baseline.settings) : null;
  const dirty = Boolean(
    effective && baseline && !sameSettings(effective, baseline.settings),
  );
  const enabled = draft?.website_mode !== "none";
  const disabled = Boolean(busy);

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!baseline || !effective || !dirty || conflict) return;
    void task(
      "save",
      (signal) => websiteApi(token).save(effective, baseline.revision, signal),
      (config) => {
        setBaseline(config);
        setDraft({ ...config.settings });
        setConflict(false);
        setResult("网站设置已保存，公开 API 和授权来源已更新。");
        notify("网站设置已保存");
      },
    );
  }

  function download(kind: WebsiteDownload) {
    if (dirty || !baseline) return;
    void task(
      `download:${kind}`,
      (signal) => websiteApi(token).download(kind, signal),
      (blob) => {
        const href = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = href;
        link.download = fileNames[kind];
        document.body.append(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(href), 1000);
        setResult("接入文件已下载。");
      },
    );
  }

  function check() {
    if (!baseline || dirty || !baseline.connection.enabled) return;
    void task(
      "check",
      (signal) => checkWebsiteApi(baseline.settings.api_public_url, signal),
      (info) => setResult(`公开 API 连接正常：${info.title}`),
    );
  }

  if (!identity.owner || denied)
    return (
      <section className="soft-panel">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
          <div>
            <h2 className="text-base font-semibold">网站详细设置</h2>
            <p
              role="status"
              className="mt-2 text-sm leading-6 text-muted-foreground"
            >
              网站接入、公开权限和官网内容仅限服主账号管理。请使用服主账号登录。
            </p>
            {error && (
              <p role="alert" className="mt-2 text-sm text-destructive">
                {error}
              </p>
            )}
          </div>
        </div>
      </section>
    );

  if (!baseline || !draft)
    return (
      <section className="soft-panel">
        <h2 className="text-base font-semibold">网站详细设置</h2>
        {busy ? (
          <p
            role="status"
            className="mt-4 flex items-center gap-2 text-sm text-muted-foreground"
          >
            <LoaderCircle className="size-4 animate-spin" />
            正在读取后台网站设置…
          </p>
        ) : (
          <>
            <p role="alert" className="mt-3 text-sm text-destructive">
              {error || "网站设置尚未载入。"}
            </p>
            <Button
              type="button"
              variant="outline"
              className="mt-4"
              onClick={() => load()}
            >
              <RefreshCw />
              重新载入
            </Button>
          </>
        )}
      </section>
    );

  const mode = draft.website_mode;
  const configuredApi = baseline.settings.api_public_url.trim();
  let websiteHref = "";
  try {
    const url = new URL(baseline.settings.website_url);
    if (
      ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password
    )
      websiteHref = url.href;
  } catch {
    /* No saved website to open. */
  }

  return (
    <section className="soft-panel" aria-labelledby="website-settings-title">
      <form onSubmit={save} className="space-y-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <Globe className="size-4" />
              <h2
                id="website-settings-title"
                className="text-base font-semibold"
              >
                网站详细设置
              </h2>
              <span className="rounded-full border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                后台设置
              </span>
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              绑定官网、配置公开 API，并管理 VexBot 官网的内容与外观。
            </p>
          </div>
          {baseline.connection.enabled && websiteHref && (
            <Button asChild size="sm" variant="outline">
              <a href={websiteHref} target="_blank" rel="noopener noreferrer">
                打开已绑定网站
                <ArrowUpRight />
              </a>
            </Button>
          )}
        </div>

        <Field label="网站绑定方式">
          <SelectControl
            aria-label="网站绑定方式"
            value={mode}
            disabled={disabled}
            onValueChange={(value) =>
              update(
                "website_mode",
                value as WebsiteSettingsData["website_mode"],
              )
            }
            options={[
              { value: "none", label: "不接入官网" },
              { value: "provided", label: "VexBot 官网" },
              { value: "custom", label: "自定义网站" },
            ]}
          />
        </Field>

        {enabled ? (
          <div className="grid gap-5 sm:grid-cols-2">
            <Field
              label="网站地址"
              hint="填写实际官网地址，保存后授权该网站来源访问 Bot API。"
            >
              <Input
                aria-label="网站地址"
                value={draft.website_url}
                onChange={(event) => update("website_url", event.target.value)}
                disabled={disabled}
                maxLength={1000}
                type="url"
                placeholder="https://www.example.com"
              />
            </Field>
            <Field
              label="Bot API 地址"
              hint="独立部署官网时填写 Bot 的公开 API 地址；留空表示使用官网同源 /api/v1。"
            >
              <Input
                aria-label="Bot API 地址"
                value={draft.api_public_url}
                onChange={(event) =>
                  update("api_public_url", event.target.value)
                }
                disabled={disabled}
                maxLength={500}
                placeholder="https://bot.example.com/api/v1"
              />
            </Field>
          </div>
        ) : (
          <p className="rounded-2xl border border-border/70 bg-background/20 px-4 py-3 text-xs leading-6 text-muted-foreground">
            不接入官网时 Bot
            仍可正常使用，已保存的网站地址、内容和外观会保留。公开 API
            权限由下方开关单独控制。
          </p>
        )}

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl bg-background/25 px-4 py-3 text-xs leading-5 text-muted-foreground">
          <ShieldCheck className="size-4 shrink-0" />
          <span>
            已保存的接入状态：
            {baseline.connection.enabled ? "已启用" : "未接入官网"}
          </span>
          {baseline.connection.origin && (
            <span className="break-all">
              授权来源：{baseline.connection.origin}
            </span>
          )}
          {dirty && (
            <span className="text-amber-600 dark:text-amber-400">
              当前更改尚未生效
            </span>
          )}
        </div>
        {baseline.error && (
          <p role="alert" className="text-sm leading-6 text-destructive">
            后台设置提示：{baseline.error}
          </p>
        )}

        <div className="space-y-3">
          <h3 className="text-sm font-semibold">公开 API 权限</h3>
          <div className="grid gap-3 lg:grid-cols-3">
            <Toggle
              label="开放玩家信息 API"
              detail="允许官网读取玩家名、UUID 与在线状态。"
              value={draft.public_players}
              disabled={disabled}
              onChange={(value) => update("public_players", value)}
            />
            <Toggle
              label="公开服务器状态"
              detail="允许官网读取服务器名称和连接状态。"
              value={draft.public_servers}
              disabled={disabled}
              onChange={(value) => update("public_servers", value)}
            />
            <Toggle
              label="开放网站密码登录 API"
              detail="允许玩家在官网通过游戏账号登录。"
              value={draft.login_enabled}
              disabled={disabled}
              onChange={(value) => update("login_enabled", value)}
            />
          </div>
          <p className="text-xs leading-5 text-muted-foreground">
            邮箱与 QQ 仅向登录后的账号本人提供，IP 与管理备注不会公开。
          </p>
        </div>

        {mode === "provided" && (
          <>
            <div className="space-y-5 border-t border-border/70 pt-6">
              <div>
                <h3 className="text-sm font-semibold">官网内容</h3>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  以下内容用于随 VexBot 提供的官网项目。
                </p>
              </div>
              <div className="grid gap-5 sm:grid-cols-2">
                <Field label="网站标题">
                  <Input
                    aria-label="网站标题"
                    value={draft.title}
                    onChange={(event) => update("title", event.target.value)}
                    maxLength={60}
                    required
                    disabled={disabled}
                  />
                </Field>
                <Field label="副标题">
                  <Input
                    aria-label="副标题"
                    value={draft.subtitle}
                    onChange={(event) => update("subtitle", event.target.value)}
                    maxLength={160}
                    disabled={disabled}
                  />
                </Field>
              </div>
              <div className="grid gap-5 sm:grid-cols-2">
                <Field label="社区介绍">
                  <textarea
                    aria-label="社区介绍"
                    className={textAreaClass}
                    value={draft.description}
                    onChange={(event) =>
                      update("description", event.target.value)
                    }
                    maxLength={1000}
                    disabled={disabled}
                  />
                </Field>
                <Field label="社区规则">
                  <textarea
                    aria-label="社区规则"
                    className={textAreaClass}
                    value={draft.rules}
                    onChange={(event) => update("rules", event.target.value)}
                    maxLength={2000}
                    disabled={disabled}
                  />
                </Field>
              </div>
              <div className="grid gap-5 sm:grid-cols-2">
                <Field label="加入服务器地址">
                  <Input
                    aria-label="加入服务器地址"
                    value={draft.join_address}
                    onChange={(event) =>
                      update("join_address", event.target.value)
                    }
                    maxLength={160}
                    disabled={disabled}
                    placeholder="play.example.com"
                  />
                </Field>
                <Field label="群聊链接">
                  <Input
                    aria-label="群聊链接"
                    value={draft.group_url}
                    onChange={(event) =>
                      update("group_url", event.target.value)
                    }
                    maxLength={500}
                    disabled={disabled}
                    placeholder="https://…"
                  />
                </Field>
              </div>
            </div>
            <div className="space-y-5 border-t border-border/70 pt-6">
              <h3 className="text-sm font-semibold">官网外观</h3>
              <div className="grid gap-5 sm:grid-cols-3">
                <Field label="主色">
                  <div className="flex items-center gap-3">
                    <Input
                      type="color"
                      aria-label="主色选择器"
                      value={
                        /^#[0-9a-f]{6}$/i.test(draft.accent_color)
                          ? draft.accent_color
                          : "#54745d"
                      }
                      onChange={(event) =>
                        update("accent_color", event.target.value)
                      }
                      disabled={disabled}
                      className="h-10 w-14 shrink-0 p-1"
                    />
                    <Input
                      aria-label="主色"
                      value={draft.accent_color}
                      onChange={(event) =>
                        update("accent_color", event.target.value)
                      }
                      disabled={disabled}
                      maxLength={7}
                      pattern="#[0-9a-fA-F]{6}"
                      required
                    />
                  </div>
                </Field>
                <Field label="辅助色">
                  <div className="flex items-center gap-3">
                    <Input
                      type="color"
                      aria-label="辅助色选择器"
                      value={
                        /^#[0-9a-f]{6}$/i.test(draft.secondary_color)
                          ? draft.secondary_color
                          : "#b78758"
                      }
                      onChange={(event) =>
                        update("secondary_color", event.target.value)
                      }
                      disabled={disabled}
                      className="h-10 w-14 shrink-0 p-1"
                    />
                    <Input
                      aria-label="辅助色"
                      value={draft.secondary_color}
                      onChange={(event) =>
                        update("secondary_color", event.target.value)
                      }
                      disabled={disabled}
                      maxLength={7}
                      pattern="#[0-9a-fA-F]{6}"
                      required
                    />
                  </div>
                </Field>
                <Field label="官网主题">
                  <SelectControl
                    aria-label="官网主题"
                    value={draft.theme_mode}
                    disabled={disabled}
                    onValueChange={(value) =>
                      update(
                        "theme_mode",
                        value as WebsiteSettingsData["theme_mode"],
                      )
                    }
                    options={[
                      { value: "system", label: "跟随系统" },
                      { value: "light", label: "浅色" },
                      { value: "dark", label: "深色" },
                    ]}
                  />
                </Field>
              </div>
              <Toggle
                label="官网网格背景"
                detail="在 VexBot 官网显示装饰网格背景，不影响控制台背景。"
                value={draft.grid_background}
                disabled={disabled}
                onChange={(value) => update("grid_background", value)}
              />
            </div>
          </>
        )}
        {mode === "custom" && (
          <p className="rounded-2xl border border-border/70 bg-background/20 px-4 py-3 text-xs leading-6 text-muted-foreground">
            自定义网站通过 Bot API
            接入。页面内容与外观由你的网站项目控制，可下载接入指南和 SDK
            完成对接。
          </p>
        )}

        <div className="space-y-3 border-t border-border/70 pt-6">
          <h3 className="text-sm font-semibold">连接与接入文件</h3>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={disabled || dirty || !baseline.connection.enabled}
              onClick={check}
            >
              {busy === "check" ? (
                <LoaderCircle className="animate-spin" />
              ) : (
                <Globe />
              )}
              检查 API
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={disabled || dirty || !configuredApi}
              onClick={() => download("config")}
            >
              <Download />
              下载接入配置
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={disabled || dirty}
              onClick={() => download("guide")}
            >
              <Download />
              接入指南
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={disabled || dirty}
              onClick={() => download("sdk")}
            >
              <Download />
              下载 SDK
            </Button>
            {mode === "provided" && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={disabled || dirty}
                onClick={() => download("project")}
              >
                <Download />
                下载官网项目
              </Button>
            )}
          </div>
          <p className="text-xs leading-5 text-muted-foreground">
            {dirty
              ? "请先保存网站设置，再检查连接或下载对应配置。"
              : !configuredApi
                ? "填写并保存 Bot API 地址后可下载 config.json；接入指南和 SDK 可直接下载。"
                : "下载文件采用已保存的设置。检查 API 会从当前浏览器访问公开接口。"}
          </p>
        </div>

        {error && (
          <div
            role="alert"
            className="space-y-3 rounded-xl border border-destructive/25 bg-destructive/5 p-4 text-sm leading-6 text-destructive"
          >
            <p>{error}</p>
            {conflict && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={disabled}
                onClick={() => load(true)}
              >
                <RefreshCw />
                载入最新版本，保留草稿
              </Button>
            )}
          </div>
        )}
        {result && (
          <p
            role="status"
            className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-4 py-3 text-sm leading-6"
          >
            {result}
          </p>
        )}

        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-border/70 pt-5">
          <p className="text-xs text-muted-foreground">
            {dirty ? "有尚未保存的网站设置" : "网站设置已与后台同步"}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="ghost"
              disabled={disabled || !dirty}
              onClick={() => setDiscard("undo")}
            >
              撤销更改
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={disabled}
              onClick={() => (dirty ? setDiscard("reload") : load())}
            >
              <RefreshCw className={busy === "load" ? "animate-spin" : ""} />
              重新载入
            </Button>
            <Button type="submit" disabled={disabled || !dirty || conflict}>
              {busy === "save" ? (
                <LoaderCircle className="animate-spin" />
              ) : (
                <Save />
              )}
              保存网站设置
            </Button>
          </div>
        </div>
      </form>

      <Dialog
        open={discard !== null}
        onOpenChange={(open) => !open && setDiscard(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>放弃尚未保存的网站设置？</DialogTitle>
            <DialogDescription>
              当前草稿会被已保存的网站设置替换。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDiscard(null)}>
              保留草稿
            </Button>
            <Button
              onClick={() => {
                const action = discard;
                setDiscard(null);
                if (action === "reload") load();
                else {
                  setDraft({ ...baseline.settings });
                  setConflict(false);
                  setError("");
                  setResult("");
                }
              }}
            >
              确认放弃
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
