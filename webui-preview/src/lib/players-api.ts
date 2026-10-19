/** Same-origin access to the VexBot administrator API. Tokens stay in caller memory. */
export type PlayerPresence = "online" | "offline" | "unknown";

export interface AdminIdentity {
  id: string;
  username: string;
  owner: boolean;
  permissions: string[];
}

export interface LoginResponse {
  access_token: string;
  expires_in: number;
  identity: AdminIdentity;
}

export interface SetupStatus {
  required: boolean;
}

export interface ServerOption {
  id: string;
  name: string;
  historical: boolean;
}

export interface PlayerBinding {
  server: string;
  server_name: string;
  qq: string;
  uuid: string;
  name: string;
  created: number;
}

export interface PlayerVisit {
  server: string;
  server_name: string;
  historical: boolean;
  status: PlayerPresence;
  manageable: boolean;
  uuid: string;
  name: string;
  first_seen: number;
  last_seen: number;
  ip: string;
  online?: boolean;
  op?: boolean;
  banned?: boolean;
  whitelisted?: boolean;
  world?: string;
  game_mode?: string;
  health?: number;
  ping?: number;
  last_played?: number;
}

export interface Profile {
  id: number;
  uuid: string;
  name: string;
  ip: string;
  region: string;
  notes: string;
  source: string;
  created: number;
  last_seen: number;
  revision: number;
  deleted: number;
  status: PlayerPresence;
  bound: boolean;
  bindings: PlayerBinding[];
  servers: PlayerVisit[];
}

export interface ProfilePage {
  items: Profile[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  servers: ServerOption[];
}

export type PlayerActionKind =
  | "kick"
  | "ban"
  | "unban"
  | "whitelist_add"
  | "whitelist_remove";
export type PlayerActionStatus =
  | "pending"
  | "success"
  | "failed"
  | "cancelled"
  | "expired";

export interface PlayerAction {
  id: string;
  server: string;
  uuid: string;
  player: string;
  action: PlayerActionKind;
  reason: string;
  status: PlayerActionStatus;
  detail: string;
  created: number;
  expires: number;
}

export interface PlayerServer {
  id: string;
  name: string;
  online: boolean;
  supported: boolean;
  truncated: boolean;
  whitelist_enabled: boolean | null;
  last_seen: number | null;
}

export interface PlayerRecord {
  name: string;
  uuid: string | null;
  online: boolean;
  banned?: boolean;
  whitelisted?: boolean;
  op?: boolean;
  world?: string;
  game_mode?: string;
  health?: number;
  ping?: number;
  last_played?: number;
  ip?: string;
}

export interface PlayerSnapshot extends PlayerRecord {
  server: string;
  server_name: string;
  qq: string | null;
  status: PlayerPresence;
  manageable: boolean;
}

export interface StatusServer {
  id: string;
  name: string;
  groups: string[];
  online: boolean;
  capabilities?: string[];
  last_seen?: number;
  players?: string[];
  player_records?: PlayerRecord[];
}

export interface PlayerStatus {
  servers: StatusServer[];
  player_servers: PlayerServer[];
  player_actions: PlayerAction[];
  players: PlayerSnapshot[];
  bindings: Omit<PlayerBinding, "server_name">[];
  onebot: boolean;
  uptime: number;
  qq_provider: string;
  qq_error: string;
}

export interface CreateProfileFields {
  name: string;
  uuid: string;
  ip?: string;
  region?: string;
  notes?: string;
}

export interface UpdateProfileFields {
  revision: number;
  region?: string;
  notes?: string;
}

export interface BindProfileFields {
  server: string;
  qq: string;
}

export interface BulkProfileFields {
  ids: number[];
  action: "delete" | "unbind";
  server?: string;
}

export interface BulkProfileResult {
  profiles: number;
  bindings_removed: number;
}

export interface PlayerActionFields {
  request_id: string;
  server: string;
  uuid: string;
  player: string;
  action: PlayerActionKind;
  reason?: string;
}

export class APIError extends Error {
  readonly status: number;

  constructor(status: number, message?: string) {
    super(message || statusMessage(status));
    this.name = "APIError";
    this.status = status;
  }
}

function statusMessage(status: number): string {
  if (status === 401) return "登录已失效，请重新登录。";
  if (status === 403) return "当前账号没有此操作的管理权限。";
  if (status === 404) return "数据不存在或已删除，请刷新后重试。";
  if (status === 409) return "数据状态已变化，请刷新后核对。";
  if (status === 429) return "请求过于频繁，请稍后重试。";
  if (status === 502 || status === 503 || status === 504)
    return "VexBot 后台暂时无法连接，请确认软件已启动。";
  if (status === 0) return "无法连接 VexBot 后台，请检查服务状态。";
  return "请求失败，请稍后重试。";
}

function responseMessage(data: unknown, text: string, status: number): string {
  if (
    data &&
    typeof data === "object" &&
    "error" in data &&
    typeof data.error === "string"
  ) {
    return data.error.slice(0, 500) || statusMessage(status);
  }
  const plain = text.trim();
  // A proxy error page is not a useful message to display in the console.
  if (plain && !plain.startsWith("<") && plain.length <= 500) return plain;
  return statusMessage(status);
}

async function request<T>(
  path: string,
  token = "",
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  if (signal?.aborted) throw new DOMException("请求已取消", "AbortError");
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 15_000);
  const headers = new Headers({ Accept: "application/json" });
  if (token.trim()) headers.set("Authorization", `Bearer ${token}`);
  if (body !== undefined) headers.set("Content-Type", "application/json");

  try {
    const response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
    });
    const text = await response.text();
    let data: unknown;
    try {
      data = JSON.parse(text);
    } catch {
      if (response.ok)
        throw new APIError(
          response.status,
          "后台返回的数据格式错误，请刷新后核对操作结果。",
        );
    }
    if (!response.ok)
      throw new APIError(
        response.status,
        responseMessage(data, text, response.status),
      );
    return data as T;
  } catch (error) {
    if (signal?.aborted) throw new DOMException("请求已取消", "AbortError");
    if (error instanceof APIError) throw error;
    const uncertain =
      method !== "GET"
        ? "请刷新后核对操作结果，避免重复提交。"
        : "请确认后台已启动后重试。";
    throw new APIError(
      0,
      `${timedOut ? "请求超时。" : "无法连接 VexBot 后台。"}${uncertain}`,
    );
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", cancel);
  }
}

export function checkSetup(signal?: AbortSignal): Promise<SetupStatus> {
  return request("/api/admin-auth/setup", "", "GET", undefined, signal);
}

export { request as apiRequest };

export function login(
  username: string,
  password: string,
  signal?: AbortSignal,
): Promise<LoginResponse> {
  return request(
    "/api/admin-auth/login",
    "",
    "POST",
    { username, password },
    signal,
  );
}

export function logout(
  token: string,
  signal?: AbortSignal,
): Promise<{ ok: boolean }> {
  return request("/api/admin-auth/logout", token, "POST", undefined, signal);
}

export function playerApi(token: string) {
  const profilePath = (id: number) =>
    `/api/player-profiles/${encodeURIComponent(String(id))}`;
  return {
    session: (signal?: AbortSignal): Promise<AdminIdentity> =>
      request("/api/session", token, "GET", undefined, signal),
    status: (signal?: AbortSignal): Promise<PlayerStatus> =>
      request("/api/status", token, "GET", undefined, signal),
    list: (
      params: Record<string, string | number> = {},
      signal?: AbortSignal,
    ): Promise<ProfilePage> => {
      const query = new URLSearchParams();
      for (const [key, value] of Object.entries(params))
        query.set(key, String(value));
      return request(
        `/api/player-profiles${query.size ? `?${query}` : ""}`,
        token,
        "GET",
        undefined,
        signal,
      );
    },
    detail: (id: number, signal?: AbortSignal): Promise<Profile> =>
      request(profilePath(id), token, "GET", undefined, signal),
    create: (
      fields: CreateProfileFields,
      signal?: AbortSignal,
    ): Promise<Profile> =>
      request("/api/player-profiles", token, "POST", fields, signal),
    update: (
      id: number,
      fields: UpdateProfileFields,
      signal?: AbortSignal,
    ): Promise<Profile> =>
      request(profilePath(id), token, "PATCH", fields, signal),
    bind: (
      id: number,
      fields: BindProfileFields,
      signal?: AbortSignal,
    ): Promise<Profile> =>
      request(`${profilePath(id)}/bind`, token, "POST", fields, signal),
    bulk: (
      fields: BulkProfileFields,
      signal?: AbortSignal,
    ): Promise<BulkProfileResult> =>
      request("/api/player-profiles/bulk", token, "POST", fields, signal),
    action: (
      fields: PlayerActionFields,
      signal?: AbortSignal,
    ): Promise<PlayerAction> =>
      request("/api/player-actions", token, "POST", fields, signal),
  };
}
