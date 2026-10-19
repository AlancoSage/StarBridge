import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  AlertCircle,
  Check,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
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
import { APIError, playerApi } from "@/lib/players-api";
import { useConsoleAuth } from "@/components/ConsoleAuth";
import type {
  AdminIdentity,
  PlayerAction,
  PlayerActionFields,
  PlayerActionKind,
  PlayerStatus,
  PlayerVisit,
  Profile,
  ProfilePage,
} from "@/lib/players-api";

const controlClass =
  "h-10 min-w-0 rounded-xl border border-border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
const fieldClass = "grid min-w-0 gap-2 text-sm";
const actionNames: Record<PlayerActionKind, string> = {
  kick: "踢出玩家",
  ban: "封禁玩家",
  unban: "解除封禁",
  whitelist_add: "加入白名单",
  whitelist_remove: "移出白名单",
};
const resultNames: Record<PlayerAction["status"], string> = {
  pending: "等待游戏插件确认",
  success: "执行成功",
  failed: "执行失败",
  expired: "已过期，执行结果未确认",
  cancelled: "已取消",
};
type Confirmation =
  | { kind: "delete" | "unbind"; profile: Profile; server?: string }
  | {
      kind: "game";
      visit: PlayerVisit;
      action: PlayerActionKind;
      reason: string;
      payload?: PlayerActionFields;
    };
type WatchedAction = {
  payload: PlayerActionFields;
  started: number;
  phase: "waiting" | "unknown" | "timeout";
};

function permission(identity: AdminIdentity) {
  return identity.owner || identity.permissions.includes("players.manage");
}
function aborted(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}
function errorText(error: unknown) {
  return error instanceof Error ? error.message : "请求失败，请重试。";
}
function dateText(value: number | null | undefined) {
  return value ? new Date(value * 1000).toLocaleString("zh-CN") : "暂无记录";
}
function Presence({ status }: { status: string }) {
  const label =
    status === "online" ? "在线" : status === "offline" ? "离线" : "状态未知";
  return (
    <span
      className={`inline-flex items-center gap-2 whitespace-nowrap text-xs ${status === "online" ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"}`}
    >
      <span
        className={`size-1.5 rounded-full ${status === "online" ? "bg-emerald-500" : "bg-muted-foreground"}`}
      />
      {label}
    </span>
  );
}
function Message({
  children,
  danger = false,
}: {
  children: ReactNode;
  danger?: boolean;
}) {
  return (
    <div
      role={danger ? "alert" : "status"}
      className={`flex items-start gap-2 rounded-xl border p-3 text-sm leading-relaxed ${danger ? "border-destructive/30 bg-destructive/5 text-destructive" : "border-border bg-muted/40 text-muted-foreground"}`}
    >
      <AlertCircle className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 break-words">{children}</div>
    </div>
  );
}

export default function PlayersPage({
  notify,
  active = true,
}: {
  notify: (message: string) => void;
  active?: boolean;
}) {
  const { token, identity, invalidate, updateIdentity } = useConsoleAuth();
  const [blocked, setDenied] = useState(false);
  const denied = blocked || !permission(identity);
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [data, setData] = useState<ProfilePage | null>(null);
  const [status, setStatus] = useState<PlayerStatus | null>(null);
  const [name, setName] = useState("");
  const [uuid, setUuid] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [server, setServer] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [refresh, setRefresh] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Profile | null>(null);
  const [region, setRegion] = useState("");
  const [notes, setNotes] = useState("");
  const [detailError, setDetailError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [bindingServer, setBindingServer] = useState("");
  const [qq, setQq] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [createFields, setCreateFields] = useState({
    name: "",
    uuid: "",
    ip: "",
    region: "",
    notes: "",
  });
  const [createError, setCreateError] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [confirmError, setConfirmError] = useState("");
  const [watched, setWatched] = useState<WatchedAction | null>(null);
  const [actionMessage, setActionMessage] = useState("");
  const tokenRef = useRef(token);
  const activeRef = useRef(active);
  const epoch = useRef(0);
  const lock = useRef(false);
  const controllers = useRef(new Set<AbortController>());
  const selectedRef = useRef<number | null>(null);
  const loadedProfile = useRef<number | null>(null);
  const profileRef = useRef<Profile | null>(null);
  const watchedRef = useRef<WatchedAction | null>(null);
  activeRef.current = active;
  selectedRef.current = selectedId;
  profileRef.current = selected;
  watchedRef.current = watched;

  const controller = useCallback(() => {
    const value = new AbortController();
    controllers.current.add(value);
    return value;
  }, []);
  const release = useCallback((value: AbortController) => {
    controllers.current.delete(value);
  }, []);
  const clearSensitive = useCallback(() => {
    epoch.current += 1;
    for (const item of controllers.current) item.abort();
    controllers.current.clear();
    tokenRef.current = "";
    loadedProfile.current = null;
    setDenied(false);
    setData(null);
    setStatus(null);
    setSelectedId(null);
    setSelected(null);
    setRegion("");
    setNotes("");
    setQq("");
    setBindingServer("");
    setConfirmation(null);
    setWatched(null);
    setCreateOpen(false);
    setCreateFields({ name: "", uuid: "", ip: "", region: "", notes: "" });
    setCreateError("");
    setDetailError("");
    setListError("");
    setConfirmError("");
    setActionMessage("");
    setConflict(false);
    lock.current = false;
    setBusy(false);
    setLoading(false);
    setDetailLoading(false);
  }, []);
  const handleError = useCallback(
    (cause: unknown) => {
      if (aborted(cause)) return;
      if (cause instanceof APIError && cause.status === 401) {
        clearSensitive();
        invalidate("登录已失效，请重新登录。");
      } else if (cause instanceof APIError && cause.status === 403) {
        epoch.current += 1;
        for (const item of controllers.current) item.abort();
        controllers.current.clear();
        lock.current = false;
        setBusy(false);
        setLoading(false);
        setDetailLoading(false);
        setDenied(true);
        setData(null);
        setStatus(null);
        setSelectedId(null);
        setSelected(null);
        setConfirmation(null);
        setWatched(null);
        setRegion("");
        setNotes("");
        setQq("");
        setCreateOpen(false);
        setActionMessage("");
        setCreateFields({ name: "", uuid: "", ip: "", region: "", notes: "" });
        setCreateError("");
        setDetailError("");
        setConfirmError("");
        setError("此账号没有玩家管理权限，请联系服主授权。");
      }
    },
    [clearSensitive, invalidate],
  );
  useEffect(() => {
    if (permission(identity)) setDenied(false);
    else handleError(new APIError(403));
  }, [identity, handleError]);
  const current = useCallback(
    (generation: number, value: string) =>
      epoch.current === generation &&
      tokenRef.current === value &&
      activeRef.current,
    [],
  );

  useEffect(() => {
    if (!active) {
      epoch.current += 1;
      for (const item of controllers.current) item.abort();
      controllers.current.clear();
      setBusy(false);
      lock.current = false;
      setWatched((previous) =>
        previous?.phase === "waiting"
          ? { ...previous, phase: "unknown" }
          : previous,
      );
      return;
    }
    return () => {
      for (const item of controllers.current) item.abort();
      controllers.current.clear();
    };
  }, [active]);
  useEffect(() => {
    tokenRef.current = token;
    return () => {
      epoch.current += 1;
      tokenRef.current = "";
      for (const item of controllers.current) item.abort();
    };
  }, [token]);

  useEffect(() => {
    if (!active || !token || denied) return;
    const request = controller(),
      generation = epoch.current;
    let alive = true;
    (async () => {
      const api = playerApi(token);
      const who = await api.session(request.signal);
      if (!alive || !current(generation, token)) return;
      updateIdentity(who);
      if (!permission(who)) {
        handleError(new APIError(403));
        return;
      }
      const result = await api.status(request.signal);
      if (!alive || !current(generation, token)) return;
      setStatus(result);
      const previous = watchedRef.current;
      const record =
        previous &&
        result.player_actions.find(
          (item) => item.id === previous.payload.request_id,
        );
      if (record && record.status !== "pending") {
        setActionMessage(
          `${actionNames[record.action]}：${resultNames[record.status]}${record.detail ? `。${record.detail}` : ""}`,
        );
        setWatched(null);
      }
    })()
      .catch((cause) => {
        if (alive && current(generation, token) && !aborted(cause)) {
          handleError(cause);
          setListError(`后台状态读取失败：${errorText(cause)}`);
        }
      })
      .finally(() => release(request));
    return () => {
      alive = false;
      request.abort();
    };
  }, [
    active,
    token,
    denied,
    refresh,
    controller,
    release,
    current,
    handleError,
    updateIdentity,
  ]);

  useEffect(() => {
    if (!active || !token || denied) return;
    const request = controller(),
      generation = epoch.current;
    let alive = true;
    setLoading(true);
    setListError("");
    const timer = window.setTimeout(() => {
      playerApi(token)
        .list(
          {
            name,
            uuid,
            status: filterStatus,
            server,
            page,
            page_size: pageSize,
          },
          request.signal,
        )
        .then((result) => {
          if (alive && current(generation, token)) {
            setData(result);
            if (result.page !== page) setPage(result.page);
          }
        })
        .catch((cause) => {
          if (alive && current(generation, token) && !aborted(cause)) {
            handleError(cause);
            setListError(errorText(cause));
            setData(null);
          }
        })
        .finally(() => {
          release(request);
          if (alive && current(generation, token)) setLoading(false);
        });
    }, 180);
    return () => {
      alive = false;
      window.clearTimeout(timer);
      request.abort();
      release(request);
    };
  }, [
    active,
    token,
    denied,
    name,
    uuid,
    filterStatus,
    server,
    page,
    pageSize,
    refresh,
    controller,
    release,
    current,
    handleError,
  ]);

  useEffect(() => {
    if (!active || !token || denied || selectedId === null) return;
    const request = controller(),
      generation = epoch.current;
    let alive = true;
    const preserveDraft = loadedProfile.current === selectedId;
    setDetailLoading(true);
    if (!preserveDraft) {
      setSelected(null);
      setDetailError("");
      setConflict(false);
      setRegion("");
      setNotes("");
      setQq("");
      setBindingServer("");
    }
    playerApi(token)
      .detail(selectedId, request.signal)
      .then((result) => {
        if (alive && current(generation, token)) {
          if (preserveDraft) {
            if (
              profileRef.current &&
              profileRef.current.revision !== result.revision
            ) {
              setConflict(true);
              setDetailError(
                "档案在离开页面期间已被更新。输入草稿已保留，请载入最新版本并核对。",
              );
            } else setSelected(result);
          } else {
            setSelected(result);
            setRegion(result.region);
            setNotes(result.notes);
            loadedProfile.current = result.id;
          }
        }
      })
      .catch((cause) => {
        if (alive && current(generation, token) && !aborted(cause)) {
          handleError(cause);
          setDetailError(errorText(cause));
        }
      })
      .finally(() => {
        release(request);
        if (alive && current(generation, token)) setDetailLoading(false);
      });
    return () => {
      alive = false;
      request.abort();
    };
  }, [
    active,
    token,
    denied,
    selectedId,
    controller,
    release,
    current,
    handleError,
  ]);

  useEffect(() => {
    if (!active || !token || denied || !watched || watched.phase !== "waiting")
      return;
    const request = controller(),
      generation = epoch.current;
    let alive = true,
      timer = 0;
    const deadline = window.setTimeout(
      () => {
        if (!alive || !current(generation, token)) return;
        setWatched((previous) =>
          previous?.payload.request_id === watched.payload.request_id
            ? { ...previous, phase: "timeout" }
            : previous,
        );
        setActionMessage(
          "等待确认已超过 60 秒，不能确定执行结果。请刷新最近操作记录；不要使用新的请求重复提交。",
        );
      },
      Math.max(0, 60000 - (Date.now() - watched.started)),
    );
    const poll = async () => {
      if (Date.now() - watched.started >= 60000) {
        setWatched((previous) =>
          previous?.payload.request_id === watched.payload.request_id
            ? { ...previous, phase: "timeout" }
            : previous,
        );
        setActionMessage(
          "等待确认已超过 60 秒，不能确定执行结果。请刷新最近操作记录；不要使用新的请求重复提交。",
        );
        return;
      }
      try {
        const result = await playerApi(token).status(request.signal);
        if (!alive || !current(generation, token)) return;
        setStatus(result);
        const record = result.player_actions.find(
          (item) => item.id === watched.payload.request_id,
        );
        if (record && record.status !== "pending") {
          setWatched(null);
          setActionMessage(
            `${actionNames[record.action]}：${resultNames[record.status]}${record.detail ? `。${record.detail}` : ""}`,
          );
          setRefresh((value) => value + 1);
          return;
        }
        timer = window.setTimeout(poll, 1800);
      } catch (cause) {
        if (!alive || !current(generation, token) || aborted(cause)) return;
        handleError(cause);
        setWatched((previous) =>
          previous?.payload.request_id === watched.payload.request_id
            ? { ...previous, phase: "unknown" }
            : previous,
        );
        setActionMessage(
          "无法读取确认记录，不能确定游戏操作是否执行。请先刷新最近操作记录；重试会复用同一请求编号。",
        );
      }
    };
    timer = window.setTimeout(poll, 1000);
    return () => {
      alive = false;
      window.clearTimeout(timer);
      window.clearTimeout(deadline);
      request.abort();
      release(request);
    };
  }, [
    active,
    token,
    denied,
    watched,
    controller,
    release,
    current,
    handleError,
  ]);

  async function mutate(
    operation: (signal: AbortSignal) => Promise<void>,
    onError: (message: string, cause: unknown) => void,
  ) {
    if (lock.current || denied || !tokenRef.current || !activeRef.current)
      return;
    const savedToken = tokenRef.current,
      generation = epoch.current,
      request = controller();
    lock.current = true;
    setBusy(true);
    try {
      await operation(request.signal);
    } catch (cause) {
      if (current(generation, savedToken) && !aborted(cause)) {
        handleError(cause);
        onError(errorText(cause), cause);
      }
    } finally {
      release(request);
      if (epoch.current === generation) {
        lock.current = false;
        setBusy(false);
      }
    }
  }
  function openProfile(profile: Profile) {
    loadedProfile.current = null;
    setSelectedId(profile.id);
  }
  function refreshAll() {
    setRefresh((value) => value + 1);
  }
  function saveAnnotations(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    const profile = selected,
      savedToken = token,
      generation = epoch.current;
    setDetailError("");
    void mutate(
      async (signal) => {
        const result = await playerApi(savedToken).update(
          profile.id,
          { revision: profile.revision, region, notes },
          signal,
        );
        if (
          !current(generation, savedToken) ||
          selectedRef.current !== profile.id
        )
          return;
        setSelected(result);
        setRegion(result.region);
        setNotes(result.notes);
        setConflict(false);
        refreshAll();
        notify("归属地与备注已保存。");
      },
      (message, cause) => {
        setDetailError(message);
        if (cause instanceof APIError && cause.status === 409)
          setConflict(true);
      },
    );
  }
  function loadLatest() {
    if (!selected) return;
    const pid = selected.id,
      savedToken = token,
      generation = epoch.current;
    void mutate(
      async (signal) => {
        const result = await playerApi(savedToken).detail(pid, signal);
        if (!current(generation, savedToken) || selectedRef.current !== pid)
          return;
        setSelected(result);
        setConflict(false);
        setDetailError(
          "已载入最新档案版本，输入框中的草稿仍保留。核对后可重新保存。",
        );
      },
      (message) => setDetailError(message),
    );
  }
  function createProfile(event: FormEvent) {
    event.preventDefault();
    const savedToken = token,
      generation = epoch.current;
    setCreateError("");
    void mutate(
      async (signal) => {
        const result = await playerApi(savedToken).create(
          {
            ...createFields,
            name: createFields.name.trim(),
            uuid: createFields.uuid.trim(),
          },
          signal,
        );
        if (!current(generation, savedToken)) return;
        setCreateOpen(false);
        setCreateFields({ name: "", uuid: "", ip: "", region: "", notes: "" });
        setPage(1);
        refreshAll();
        setSelectedId(result.id);
        notify("玩家档案已创建。");
      },
      (message) => setCreateError(message),
    );
  }
  function reconcileBindingProfile(result: Profile) {
    const baseline = profileRef.current;
    if (!baseline || baseline.id !== result.id) return;
    const sameAnnotations =
      baseline.ip === result.ip &&
      baseline.region === result.region &&
      baseline.notes === result.notes;
    if (
      baseline.revision !== result.revision &&
      (!sameAnnotations || result.revision < baseline.revision)
    ) {
      // Updating a binding must not silently accept a new annotation revision.
      setSelected({
        ...baseline,
        bindings: result.bindings,
        servers: result.servers,
        status: result.status,
        bound: result.bound,
        last_seen: result.last_seen,
      });
      setConflict(true);
      setDetailError(
        "绑定已更新，但档案信息同时发生了变化。归属地与备注草稿已保留，请载入最新版本并核对后再保存。",
      );
      return;
    }
    setSelected(result);
  }
  function bindProfile(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    const pid = selected.id,
      savedToken = token,
      generation = epoch.current;
    setDetailError("");
    void mutate(
      async (signal) => {
        const result = await playerApi(savedToken).bind(
          pid,
          { server: bindingServer, qq: qq.trim() },
          signal,
        );
        if (!current(generation, savedToken) || selectedRef.current !== pid)
          return;
        reconcileBindingProfile(result);
        setQq("");
        refreshAll();
        notify("玩家绑定已保存。");
      },
      (message) => setDetailError(message),
    );
  }
  function openGame(visit: PlayerVisit, action: PlayerActionKind) {
    if (
      !visit.manageable ||
      !visit.uuid ||
      !visit.name ||
      (action === "kick" && visit.status !== "online") ||
      watched
    )
      return;
    setConfirmation({ kind: "game", visit, action, reason: "" });
    setConfirmError("");
  }
  async function submitGame(
    payload: PlayerActionFields,
    signal: AbortSignal,
    generation: number,
    savedToken: string,
  ) {
    const result = await playerApi(savedToken).action(payload, signal);
    if (!current(generation, savedToken)) return;
    if (
      !result ||
      result.id !== payload.request_id ||
      result.server !== payload.server ||
      result.uuid !== payload.uuid ||
      result.player !== payload.player ||
      result.action !== payload.action ||
      !["pending", "success", "failed", "expired", "cancelled"].includes(
        result.status,
      )
    ) {
      throw new APIError(
        202,
        "后台已响应，但未返回可核对的操作记录。请刷新记录确认执行结果，避免重复提交。",
      );
    }
    setConfirmation(null);
    setConfirmError("");
    setStatus((previous) =>
      previous
        ? {
            ...previous,
            player_actions: [
              result,
              ...previous.player_actions.filter(
                (item) => item.id !== result.id,
              ),
            ],
          }
        : previous,
    );
    if (result.status === "pending") {
      setWatched({ payload, started: Date.now(), phase: "waiting" });
      setActionMessage(
        "操作已提交，正在等待游戏插件确认。提交不代表执行成功。",
      );
    } else {
      setWatched(null);
      setActionMessage(
        `${actionNames[result.action]}：${resultNames[result.status]}${result.detail ? `。${result.detail}` : ""}`,
      );
      refreshAll();
    }
  }
  function confirmAction() {
    if (
      !confirmation ||
      lock.current ||
      denied ||
      !tokenRef.current ||
      !activeRef.current
    )
      return;
    const item = confirmation,
      savedToken = token,
      generation = epoch.current;
    setConfirmError("");
    if (item.kind === "game") {
      if (item.reason.length > 120 || /[\x00-\x1f\x7f]/.test(item.reason)) {
        setConfirmError("原因必须是 120 字以内的单行文字。");
        return;
      }
      const payload = item.payload ?? {
        request_id: crypto.randomUUID(),
        server: item.visit.server,
        uuid: item.visit.uuid,
        player: item.visit.name,
        action: item.action,
        reason: item.reason,
      };
      setConfirmation({ ...item, payload });
      setWatched({ payload, started: Date.now(), phase: "unknown" });
      void mutate(
        async (signal) => {
          await submitGame(payload, signal, generation, savedToken);
        },
        (message, cause) => {
          if (
            cause instanceof APIError &&
            (cause.status === 0 ||
              (cause.status >= 200 && cause.status < 300) ||
              cause.status >= 500)
          ) {
            setWatched({ payload, started: Date.now(), phase: "unknown" });
            setActionMessage(
              "提交连接中断，不能确定操作是否已受理。请先刷新最近操作记录；重试将复用同一请求编号。",
            );
            setConfirmError(
              "连接中断，执行结果尚未确认。请先关闭此窗口刷新操作记录；如需重试，请复用此请求。",
            );
          } else {
            setWatched(null);
            setConfirmError(message);
          }
        },
      );
    } else {
      void mutate(
        async (signal) => {
          await playerApi(savedToken).bulk(
            {
              ids: [item.profile.id],
              action: item.kind,
              ...(item.server ? { server: item.server } : {}),
            },
            signal,
          );
          if (!current(generation, savedToken)) return;
          setConfirmation(null);
          refreshAll();
          if (item.kind === "delete") {
            setSelectedId(null);
            setSelected(null);
            notify("玩家档案已删除，游戏存档未删除。");
          } else {
            const updated = await playerApi(savedToken).detail(
              item.profile.id,
              signal,
            );
            if (
              current(generation, savedToken) &&
              selectedRef.current === item.profile.id
            )
              reconcileBindingProfile(updated);
            notify("绑定已解除。");
          }
        },
        (message) => setConfirmError(message),
      );
    }
  }
  function retryWatched() {
    if (!watched || watched.phase === "waiting") return;
    const payload = watched.payload,
      savedToken = token,
      generation = epoch.current;
    void mutate(
      async (signal) => {
        await submitGame(payload, signal, generation, savedToken);
      },
      (message) =>
        setActionMessage(
          `仍无法确认：${message}。请刷新操作记录；请求编号保持不变。`,
        ),
    );
  }

  return (
    <div className="grid min-w-0 gap-5">
      {denied ? (
        <section className="soft-panel !rounded-[20px]">
          <Message danger>
            {error || "此账号没有玩家管理权限，请联系服主授权。"}
          </Message>
          <p className="mt-4 text-sm text-muted-foreground">
            需要「玩家与绑定管理」权限。获得授权后请重新登录。
          </p>
        </section>
      ) : (
        <>
          <section className="soft-panel min-w-0 !rounded-[20px]">
            <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="font-semibold">
                  玩家档案{" "}
                  <span className="ml-2 text-sm font-normal text-muted-foreground">
                    {data ? `共 ${data.total} 位` : ""}
                  </span>
                </h2>
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  来自实际游戏上报、已保存绑定与手动创建的档案。
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={refreshAll}
                  disabled={busy || loading}
                >
                  <RefreshCw
                    className={`size-4 ${loading ? "animate-spin" : ""}`}
                  />
                  刷新
                </Button>
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() => {
                    setCreateError("");
                    setCreateOpen(true);
                  }}
                >
                  <Plus className="size-4" />
                  添加玩家
                </Button>
              </div>
            </div>
            <div className="mb-4 grid gap-3 md:grid-cols-2 xl:grid-cols-[1.3fr_1.5fr_1fr_1fr]">
              <label className="relative">
                <span className="sr-only">搜索玩家名或 QQ 身份</span>
                <Search className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" />
                <Input
                  className="pl-9"
                  value={name}
                  maxLength={120}
                  placeholder="搜索玩家名或 QQ 身份"
                  onChange={(event) => {
                    setName(event.target.value);
                    setPage(1);
                  }}
                />
              </label>
              <Input
                aria-label="搜索 UUID"
                value={uuid}
                maxLength={120}
                placeholder="UUID 筛选"
                onChange={(event) => {
                  setUuid(event.target.value);
                  setPage(1);
                }}
              />
              <select
                aria-label="玩家状态"
                className={controlClass}
                value={filterStatus}
                onChange={(event) => {
                  setFilterStatus(event.target.value);
                  setPage(1);
                }}
              >
                <option value="">全部状态</option>
                <option value="online">在线</option>
                <option value="offline">离线</option>
                <option value="unknown">状态未知</option>
                <option value="banned">已封禁</option>
                <option value="whitelisted">在白名单中</option>
              </select>
              <select
                aria-label="筛选服务器"
                className={controlClass}
                value={server}
                onChange={(event) => {
                  setServer(event.target.value);
                  setPage(1);
                }}
              >
                <option value="">全部服务器</option>
                {data?.servers.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                    {item.historical ? "（历史）" : ""}
                  </option>
                ))}
              </select>
            </div>
            <div className="mb-4 flex items-center justify-between gap-3">
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <Switch
                  checked={filterStatus === "online"}
                  onCheckedChange={(value) => {
                    setFilterStatus(value ? "online" : "");
                    setPage(1);
                  }}
                />
                只看在线
              </label>
              {loading && (
                <span role="status" className="text-xs text-muted-foreground">
                  正在读取真实档案…
                </span>
              )}
            </div>
            {listError && (
              <div className="mb-4">
                <Message danger>
                  {listError}{" "}
                  <button
                    type="button"
                    className="ml-2 underline"
                    onClick={refreshAll}
                  >
                    重新读取
                  </button>
                </Message>
              </div>
            )}
            <div className="max-w-full overflow-x-auto" aria-busy={loading}>
              <table className="overview-table !min-w-[760px]">
                <thead>
                  <tr>
                    <th>玩家 / UUID</th>
                    <th>状态</th>
                    <th>绑定身份</th>
                    <th>到访服务器</th>
                    <th className="!text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.items.map((profile) => (
                    <tr key={profile.id}>
                      <td>
                        <div className="flex items-center gap-3">
                          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-background text-sm font-semibold">
                            {profile.name.slice(0, 1).toUpperCase()}
                          </span>
                          <div>
                            <strong className="text-sm font-medium">
                              {profile.name}
                            </strong>
                            <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                              {profile.uuid}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td>
                        <Presence status={profile.status} />
                      </td>
                      <td>
                        <span className="text-xs">
                          {profile.bindings.length
                            ? profile.bindings
                                .map((binding) => binding.qq)
                                .join("、")
                            : "未绑定"}
                        </span>
                      </td>
                      <td>
                        <span className="text-xs text-muted-foreground">
                          {profile.servers.length
                            ? profile.servers
                                .map((visit) => visit.server_name)
                                .join("、")
                            : "暂无到访记录"}
                        </span>
                      </td>
                      <td className="!text-right">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          onClick={() => openProfile(profile)}
                        >
                          管理
                          <ChevronRight className="size-3.5" />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!loading && data?.items.length === 0 && (
              <div className="grid justify-items-center gap-3 py-12 text-center">
                <Users className="size-8 text-muted-foreground/60" />
                <p className="text-sm font-medium">
                  {data.total === 0 &&
                  !name &&
                  !uuid &&
                  !filterStatus &&
                  !server
                    ? "还没有真实玩家档案"
                    : "没有符合筛选条件的玩家"}
                </p>
                <p className="max-w-md text-xs leading-relaxed text-muted-foreground">
                  连接游戏端插件并等待玩家上报，或点击「添加玩家」创建实际档案。
                </p>
              </div>
            )}
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4 text-xs text-muted-foreground">
              <label className="flex items-center gap-2">
                每页
                <select
                  aria-label="每页数量"
                  className={`${controlClass} !h-8`}
                  value={pageSize}
                  onChange={(event) => {
                    setPageSize(Number(event.target.value));
                    setPage(1);
                  }}
                >
                  {[10, 25, 50, 100].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
                位
              </label>
              <div className="flex items-center gap-3">
                <Button
                  aria-label="上一页"
                  variant="outline"
                  size="icon"
                  disabled={loading || !data || data.page <= 1}
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                >
                  <ChevronLeft className="size-4" />
                </Button>
                <span>
                  {data?.page ?? page} / {data?.pages ?? 1}
                </span>
                <Button
                  aria-label="下一页"
                  variant="outline"
                  size="icon"
                  disabled={loading || !data || data.page >= data.pages}
                  onClick={() => setPage((value) => value + 1)}
                >
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          </section>
          <section className="soft-panel min-w-0 !rounded-[20px]">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold">最近游戏操作</h2>
                <p className="mt-2 text-xs text-muted-foreground">
                  以游戏插件回执为准；服务器断开或回执缺失时不会显示执行成功。
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={refreshAll}
                disabled={busy}
              >
                <RefreshCw className="size-4" />
                刷新记录
              </Button>
            </div>
            {actionMessage && (
              <div className="mb-4">
                <Message>{actionMessage}</Message>
              </div>
            )}
            {watched && (
              <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl bg-muted/50 p-3 text-xs">
                <span className="break-all font-mono">
                  请求：{watched.payload.request_id}
                </span>
                {watched.phase === "waiting" ? (
                  <span className="flex items-center gap-2">
                    <LoaderCircle className="size-3.5 animate-spin" />
                    等待确认
                  </span>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={retryWatched}
                  >
                    使用同一请求重试
                  </Button>
                )}
              </div>
            )}
            <div className="max-w-full overflow-x-auto">
              <table className="overview-table !min-w-[680px]">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>玩家 / 服务器</th>
                    <th>操作</th>
                    <th>执行记录</th>
                  </tr>
                </thead>
                <tbody>
                  {status?.player_actions.slice(0, 15).map((record) => (
                    <tr key={record.id}>
                      <td className="whitespace-nowrap text-xs">
                        {dateText(record.created)}
                      </td>
                      <td>
                        <div className="text-sm">{record.player}</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {status.player_servers.find(
                            (item) => item.id === record.server,
                          )?.name ?? record.server}
                        </div>
                      </td>
                      <td className="text-xs">{actionNames[record.action]}</td>
                      <td>
                        <div
                          className={`text-xs ${record.status === "success" ? "text-emerald-600 dark:text-emerald-400" : record.status === "failed" ? "text-destructive" : "text-muted-foreground"}`}
                        >
                          {resultNames[record.status]}
                        </div>
                        {record.detail && (
                          <p className="mt-1 max-w-xs text-xs text-muted-foreground">
                            {record.detail}
                          </p>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!status?.player_actions.length && (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {status ? "暂无游戏操作记录" : "正在读取后台操作记录…"}
              </p>
            )}
          </section>
        </>
      )}

      <Dialog
        open={selectedId !== null && !denied && active}
        onOpenChange={(open) => {
          if (!open && !busy) {
            setSelectedId(null);
            setSelected(null);
          }
        }}
      >
        <DialogContent
          className="!max-h-[90dvh] !overflow-y-auto sm:!max-w-3xl"
          showCloseButton={!busy}
        >
          <DialogHeader>
            <DialogTitle>
              {selected ? `${selected.name} · 玩家档案` : "玩家档案"}
            </DialogTitle>
            <DialogDescription>
              档案信息与游戏端操作使用真实后台数据。
            </DialogDescription>
          </DialogHeader>
          <div className="grid min-w-0 gap-5 p-6">
            {detailLoading && (
              <p role="status" className="text-sm text-muted-foreground">
                正在读取档案…
              </p>
            )}
            {detailError && (
              <Message danger={!conflict && !detailError.startsWith("已载入")}>
                {detailError}
              </Message>
            )}
            {selected && (
              <>
                <dl className="grid gap-3 rounded-2xl bg-muted/40 p-4 text-sm sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <dt className="text-xs text-muted-foreground">UUID</dt>
                    <dd className="mt-1 break-all font-mono text-xs">
                      {selected.uuid}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">IP 地址</dt>
                    <dd className="mt-1 break-all">
                      {selected.ip || "暂无上报"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">状态</dt>
                    <dd className="mt-1">
                      <Presence status={selected.status} />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">最近活跃</dt>
                    <dd className="mt-1 text-xs">
                      {dateText(selected.last_seen)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">档案版本</dt>
                    <dd className="mt-1 text-xs">{selected.revision}</dd>
                  </div>
                </dl>
                <form onSubmit={saveAnnotations} className="grid gap-4">
                  <label className={fieldClass}>
                    归属地
                    <Input
                      value={region}
                      maxLength={120}
                      disabled={busy}
                      onChange={(event) => setRegion(event.target.value)}
                      placeholder="为当前 IP 添加归属地备注"
                    />
                  </label>
                  <label className={fieldClass}>
                    档案备注
                    <textarea
                      aria-label="档案备注"
                      className={`${controlClass} !h-24 py-3`}
                      value={notes}
                      maxLength={1000}
                      disabled={busy}
                      onChange={(event) => setNotes(event.target.value)}
                      placeholder="最多 1000 字"
                    />
                  </label>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      size="sm"
                      type="submit"
                      disabled={
                        busy ||
                        conflict ||
                        (region === selected.region && notes === selected.notes)
                      }
                    >
                      <Check className="size-4" />
                      保存归属地与备注
                    </Button>
                    {conflict && (
                      <Button
                        size="sm"
                        type="button"
                        variant="outline"
                        disabled={busy}
                        onClick={loadLatest}
                      >
                        载入最新版本，保留草稿
                      </Button>
                    )}
                  </div>
                </form>
                <div className="border-t border-border pt-5">
                  <h3 className="mb-3 text-sm font-semibold">绑定身份</h3>
                  <div className="grid gap-2">
                    {selected.bindings.map((binding) => (
                      <div
                        key={`${binding.server}:${binding.qq}`}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-muted/40 p-3"
                      >
                        <div>
                          <p className="text-sm">{binding.server_name}</p>
                          <p className="mt-1 break-all text-xs text-muted-foreground">
                            QQ / 官机身份：{binding.qq}
                          </p>
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          onClick={() => {
                            setConfirmation({
                              kind: "unbind",
                              profile: selected,
                              server: binding.server,
                            });
                            setConfirmError("");
                          }}
                        >
                          解绑
                        </Button>
                      </div>
                    ))}
                    {!selected.bindings.length && (
                      <p className="text-xs text-muted-foreground">
                        当前未绑定身份。
                      </p>
                    )}
                  </div>
                  <form
                    onSubmit={bindProfile}
                    className="mt-4 grid items-end gap-3 sm:grid-cols-[1fr_1.2fr_auto]"
                  >
                    <label className={fieldClass}>
                      服务器
                      <select
                        aria-label="服务器"
                        required
                        className={controlClass}
                        value={bindingServer}
                        disabled={busy}
                        onChange={(event) =>
                          setBindingServer(event.target.value)
                        }
                      >
                        <option value="">选择服务器</option>
                        {data?.servers
                          .filter((item) => !item.historical)
                          .map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.name}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label className={fieldClass}>
                      QQ / 官机用户身份
                      <Input
                        required
                        value={qq}
                        maxLength={153}
                        disabled={busy}
                        onChange={(event) => setQq(event.target.value)}
                        placeholder="QQ 号或官机身份"
                      />
                    </label>
                    <Button
                      type="submit"
                      disabled={busy || !bindingServer || !qq.trim()}
                    >
                      添加绑定
                    </Button>
                  </form>
                </div>
                <div className="border-t border-border pt-5">
                  <h3 className="mb-3 text-sm font-semibold">
                    到访服务器与游戏管理
                  </h3>
                  <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
                    每项操作仅作用于卡片中指定的服务器和玩家。需游戏服务器在线并上报玩家管理能力。
                  </p>
                  <div className="grid gap-3">
                    {selected.servers.map((visit) => (
                      <div
                        key={visit.server}
                        className="rounded-2xl border border-border p-4"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <h4 className="text-sm font-medium">
                              {visit.server_name}
                              {visit.historical ? "（历史服务器）" : ""}
                            </h4>
                            <p className="mt-1 break-all text-xs text-muted-foreground">
                              游戏身份：{visit.name} · {visit.server}
                            </p>
                          </div>
                          <Presence status={visit.status} />
                        </div>
                        <p className="mt-2 text-xs text-muted-foreground">
                          最近到访：{dateText(visit.last_seen)}
                          {visit.banned === true ? " · 已封禁" : ""}
                          {visit.whitelisted === true ? " · 在白名单中" : ""}
                        </p>
                        {!visit.manageable ? (
                          <p className="mt-3 rounded-lg bg-muted/50 p-2 text-xs leading-relaxed text-muted-foreground">
                            {visit.historical
                              ? "此服务器已移除，保留到访记录。"
                              : !status?.player_servers.find(
                                    (item) => item.id === visit.server,
                                  )?.online
                                ? "服务器未连接，无法进行游戏操作。"
                                : !status.player_servers.find(
                                      (item) => item.id === visit.server,
                                    )?.supported
                                  ? "当前游戏端未上报玩家管理能力，请安装支持的新版插件。"
                                  : "插件尚未上报此玩家的完整身份，刷新后再试。"}
                          </p>
                        ) : (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {(
                              [
                                "kick",
                                visit.banned ? "unban" : "ban",
                                visit.whitelisted
                                  ? "whitelist_remove"
                                  : "whitelist_add",
                              ] as PlayerActionKind[]
                            ).map((action) => (
                              <Button
                                type="button"
                                key={action}
                                size="sm"
                                variant="outline"
                                disabled={
                                  busy ||
                                  !!watched ||
                                  !visit.uuid ||
                                  !visit.name ||
                                  (action === "kick" &&
                                    visit.status !== "online")
                                }
                                onClick={() => openGame(visit, action)}
                              >
                                {actionNames[action]}
                              </Button>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                    {!selected.servers.length && (
                      <p className="text-xs text-muted-foreground">
                        尚无到访记录，不能指定游戏端操作。玩家连接并上报后会自动显示。
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-5">
                  <p className="text-xs text-muted-foreground">
                    删除档案只影响后台资料和绑定。
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="text-destructive"
                    disabled={busy}
                    onClick={() => {
                      setConfirmation({ kind: "delete", profile: selected });
                      setConfirmError("");
                    }}
                  >
                    删除玩家档案
                  </Button>
                </div>
              </>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                setSelectedId(null);
                setSelected(null);
              }}
            >
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={createOpen && active && !denied}
        onOpenChange={(open) => {
          if (!busy) setCreateOpen(open);
        }}
      >
        <DialogContent
          className="!max-h-[90dvh] !overflow-y-auto"
          showCloseButton={!busy}
        >
          <DialogHeader>
            <DialogTitle>添加真实玩家档案</DialogTitle>
            <DialogDescription>
              手动建档不创建游戏账号，也不自动加入服务器白名单。
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={createProfile}>
            <div className="grid gap-4 p-6">
              {createError && <Message danger>{createError}</Message>}
              <label className={fieldClass}>
                游戏玩家名
                <Input
                  required
                  pattern="[A-Za-z0-9_]{1,16}"
                  maxLength={16}
                  value={createFields.name}
                  disabled={busy}
                  onChange={(event) =>
                    setCreateFields((value) => ({
                      ...value,
                      name: event.target.value,
                    }))
                  }
                  placeholder="1–16 位字母、数字或下划线"
                />
              </label>
              <label className={fieldClass}>
                玩家 UUID
                <Input
                  aria-label="玩家 UUID"
                  aria-describedby="player-create-uuid-help"
                  required
                  value={createFields.uuid}
                  disabled={busy}
                  onChange={(event) =>
                    setCreateFields((value) => ({
                      ...value,
                      uuid: event.target.value,
                    }))
                  }
                  placeholder="填写真实游戏身份 UUID"
                />
                <span
                  id="player-create-uuid-help"
                  className="text-xs leading-relaxed text-muted-foreground"
                >
                  UUID 为必填，用于准确关联玩家，请从服务器查询。
                </span>
              </label>
              <label className={fieldClass}>
                IP 地址（选填）
                <Input
                  value={createFields.ip}
                  disabled={busy}
                  onChange={(event) =>
                    setCreateFields((value) => ({
                      ...value,
                      ip: event.target.value,
                    }))
                  }
                />
              </label>
              <label className={fieldClass}>
                归属地（选填）
                <Input
                  maxLength={120}
                  value={createFields.region}
                  disabled={busy}
                  onChange={(event) =>
                    setCreateFields((value) => ({
                      ...value,
                      region: event.target.value,
                    }))
                  }
                />
              </label>
              <label className={fieldClass}>
                备注（选填）
                <textarea
                  aria-label="备注（选填）"
                  className={`${controlClass} !h-24 py-3`}
                  maxLength={1000}
                  value={createFields.notes}
                  disabled={busy}
                  onChange={(event) =>
                    setCreateFields((value) => ({
                      ...value,
                      notes: event.target.value,
                    }))
                  }
                />
              </label>
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => setCreateOpen(false)}
              >
                取消
              </Button>
              <Button type="submit" disabled={busy}>
                {busy && <LoaderCircle className="size-4 animate-spin" />}
                创建档案
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={confirmation !== null && active && !denied}
        onOpenChange={(open) => {
          if (!open && !busy) {
            setConfirmation(null);
            setConfirmError("");
          }
        }}
      >
        <DialogContent
          className="!max-h-[90dvh] !overflow-y-auto"
          showCloseButton={!busy}
        >
          <DialogHeader>
            <DialogTitle>
              {confirmation?.kind === "game"
                ? `确认${actionNames[confirmation.action]}`
                : confirmation?.kind === "delete"
                  ? "确认删除玩家档案"
                  : "确认解除绑定"}
            </DialogTitle>
            <DialogDescription>
              {confirmation?.kind === "game"
                ? "提交后将等待指定游戏服务器的插件回执。"
                : "此操作不会删除 Minecraft 游戏存档。"}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 p-6">
            {confirmError && <Message danger>{confirmError}</Message>}
            {confirmation?.kind === "game" ? (
              <>
                <div className="rounded-xl bg-muted/50 p-4 text-sm leading-relaxed">
                  <p>
                    服务器：{confirmation.visit.server_name}（
                    {confirmation.visit.server}）
                  </p>
                  <p>玩家：{confirmation.visit.name}</p>
                  <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                    {confirmation.visit.uuid}
                  </p>
                </div>
                <label className={fieldClass}>
                  操作原因（选填，最多 120 字）
                  <Input
                    maxLength={120}
                    value={confirmation.reason}
                    disabled={busy || !!confirmation.payload}
                    onChange={(event) =>
                      setConfirmation({
                        ...confirmation,
                        reason: event.target.value,
                      })
                    }
                  />
                </label>
                {confirmation.payload && (
                  <p className="break-all text-xs text-muted-foreground">
                    重试复用请求：{confirmation.payload.request_id}
                  </p>
                )}
              </>
            ) : (
              confirmation && (
                <p className="text-sm leading-relaxed">
                  {confirmation.kind === "delete"
                    ? `将删除 ${confirmation.profile.name} 的后台档案、到访记录和绑定，并撤销尚待执行的玩家操作。游戏端再次上报时可能重新出现档案。`
                    : `将解除 ${confirmation.profile.name} 在 ${confirmation.profile.bindings.find((item) => item.server === confirmation.server)?.server_name ?? confirmation.server} 的身份绑定，保留玩家档案。`}
                </p>
              )
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                setConfirmation(null);
                setConfirmError("");
              }}
            >
              取消
            </Button>
            <Button disabled={busy} onClick={confirmAction}>
              {busy && <LoaderCircle className="size-4 animate-spin" />}
              {confirmation?.kind === "game"
                ? confirmation.payload
                  ? "使用同一请求重试"
                  : "确认提交"
                : "确认操作"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
