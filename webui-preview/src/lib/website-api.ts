import { APIError, apiRequest } from "@/lib/players-api";

export type WebsiteMode = "none" | "provided" | "custom";
export type WebsiteDownload = "config" | "guide" | "project" | "sdk";
export interface WebsiteSettingsData {
  title: string;
  subtitle: string;
  description: string;
  rules: string;
  join_address: string;
  group_url: string;
  public_players: boolean;
  public_servers: boolean;
  login_enabled: boolean;
  accent_color: string;
  secondary_color: string;
  theme_mode: "system" | "light" | "dark";
  grid_background: boolean;
  website_url: string;
  api_public_url: string;
  connection_enabled: boolean;
  website_mode: WebsiteMode;
}
export interface WebsiteConfig {
  settings: WebsiteSettingsData;
  revision: string;
  error: string;
  connection: { origin: string; enabled: boolean; mode: WebsiteMode };
}

async function timedRequest<T>(
  signal: AbortSignal | undefined,
  milliseconds: number,
  run: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) throw new DOMException("请求已取消", "AbortError");
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, milliseconds);
  try {
    return await run(controller.signal);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

async function downloadFile(
  token: string,
  kind: Exclude<WebsiteDownload, "config">,
  signal?: AbortSignal,
): Promise<Blob> {
  try {
    return await timedRequest(signal, 15000, async (requestSignal) => {
      const response = await fetch(
        kind === "sdk" ? "/api/registration/example" : `/api/website/${kind}`,
        {
          headers: { Authorization: `Bearer ${token}` },
          credentials: "omit",
          cache: "no-store",
          redirect: "error",
          signal: requestSignal,
        },
      );
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new APIError(
          response.status,
          typeof data?.error === "string"
            ? data.error.slice(0, 500)
            : undefined,
        );
      }
      return response.blob();
    });
  } catch (cause) {
    if (signal?.aborted) throw new DOMException("请求已取消", "AbortError");
    if (cause instanceof APIError) throw cause;
    throw new APIError(0, "接入文件下载中断或超时，请检查后台连接后重试。");
  }
}

export function websiteApi(token: string) {
  return {
    get: (signal?: AbortSignal): Promise<WebsiteConfig> =>
      apiRequest("/api/website/settings", token, "GET", undefined, signal),
    save: (
      settings: WebsiteSettingsData,
      revision: string,
      signal?: AbortSignal,
    ): Promise<WebsiteConfig> =>
      apiRequest(
        "/api/website/settings",
        token,
        "PUT",
        { settings, revision },
        signal,
      ),
    download: async (
      kind: WebsiteDownload,
      signal?: AbortSignal,
    ): Promise<Blob> => {
      if (kind !== "config") return downloadFile(token, kind, signal);
      const config = await apiRequest<{ apiBase: string }>(
        "/api/website/config",
        token,
        "POST",
        {},
        signal,
      );
      return new Blob([JSON.stringify(config, null, 2) + "\n"], {
        type: "application/json",
      });
    },
  };
}

/** Public connectivity probe. Management credentials never leave the local API. */
export async function checkWebsiteApi(
  address: string,
  signal?: AbortSignal,
): Promise<{ title: string }> {
  const input = address || "/api/v1";
  let url: URL;
  try {
    url = new URL(input, window.location.origin);
    if (
      (input !== "/api/v1" && !/^https?:\/\//i.test(input)) ||
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      url.pathname.replace(/\/$/, "") !== "/api/v1" ||
      /\s/.test(input) ||
      input.length > 500
    )
      throw new Error();
  } catch {
    throw new Error(
      "请填写有效的 Bot API 地址，例如 https://bot.example.com/api/v1。",
    );
  }
  try {
    return await timedRequest(signal, 8000, async (requestSignal) => {
      const response = await fetch(
        url.href.replace(/\/$/, "") + "/community/info",
        {
          headers: { Accept: "application/json" },
          credentials: "omit",
          cache: "no-store",
          referrerPolicy: "no-referrer",
          redirect: "error",
          signal: requestSignal,
        },
      );
      if (!response.ok)
        throw new Error(`公开 API 返回 HTTP ${response.status}。`);
      const data = await response.json().catch(() => null);
      if (
        typeof data?.title !== "string" ||
        typeof data?.registration_enabled !== "boolean" ||
        typeof data?.login_enabled !== "boolean"
      )
        throw new Error("该地址未返回 VexBot 官网 API 数据，请检查地址。");
      return { title: data.title };
    });
  } catch (cause) {
    if (signal?.aborted) throw new DOMException("请求已取消", "AbortError");
    if (
      cause instanceof Error &&
      cause.name !== "AbortError" &&
      !(cause instanceof TypeError)
    )
      throw cause;
    throw new Error(
      "当前浏览器无法访问公开 API，或连接已超时。请检查地址、HTTPS 和跨域来源设置。",
    );
  }
}
