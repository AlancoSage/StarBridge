import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { FormEvent, ReactNode } from "react";
import {
  ArrowUpRight,
  LoaderCircle,
  Moon,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Sun,
} from "lucide-react";
import BackgroundSwitcher from "@/components/BackgroundSwitcher";
import { useMotionPreference } from "@/components/MotionPreference";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  APIError,
  checkSetup,
  login,
  logout,
  playerApi,
} from "@/lib/players-api";
import type { AdminIdentity } from "@/lib/players-api";

type AuthenticatedSession = {
  token: string;
  identity: AdminIdentity;
  expiresAt: number;
};

type ConsoleAuth = {
  token: string;
  identity: AdminIdentity;
  signOut: () => Promise<void>;
  invalidate: (message?: string) => void;
  updateIdentity: (identity: AdminIdentity) => void;
};

const ConsoleAuthContext = createContext<ConsoleAuth | null>(null);
const themeKey = "vexbot.cdk.preview.theme";

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function LoginScreen({
  busy,
  error,
  onLogin,
}: {
  busy: boolean;
  error: string;
  onLogin: (username: string, password: string) => Promise<void>;
}) {
  const { enabled, toggleMotion } = useMotionPreference();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [setupRequired, setSetupRequired] = useState<boolean | null>(null);
  const [setupError, setSetupError] = useState("");
  const [setupRetry, setSetupRetry] = useState(0);
  const [dark, setDark] = useState(() => {
    try {
      return localStorage.getItem(themeKey) === "dark";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
    try {
      localStorage.setItem(themeKey, dark ? "dark" : "light");
    } catch {
      // The theme remains available when browser storage is disabled.
    }
  }, [dark]);

  useEffect(() => {
    const controller = new AbortController();
    setSetupRequired(null);
    setSetupError("");
    checkSetup(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setSetupRequired(result.required);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setSetupError(errorMessage(reason, "无法连接 VexBot 后台。"));
      });
    return () => controller.abort();
  }, [setupRetry]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || setupRequired !== false) return;
    const submittedPassword = password;
    setPassword("");
    void onLogin(username.trim(), submittedPassword);
  }

  return (
    <div className="min-h-dvh text-foreground">
      <header className="border-b border-border bg-background/85">
        <div className="mx-auto flex min-h-19 max-w-7xl items-center justify-between gap-3 px-4 sm:px-8">
          <div className="flex items-center gap-2.5">
            <img src="/mark.svg" alt="" width="32" height="32" />
            <strong className="text-xl tracking-tight">VexBot</strong>
          </div>
          <div className="flex items-center gap-1">
            <BackgroundSwitcher />
            <Button
              variant="ghost"
              size="icon"
              aria-label={enabled ? "关闭动画" : "开启动画"}
              aria-pressed={enabled}
              title={enabled ? "关闭动画" : "开启动画"}
              onClick={toggleMotion}
            >
              <Sparkles className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={dark ? "切换浅色主题" : "切换深色主题"}
              title={dark ? "切换浅色主题" : "切换深色主题"}
              onClick={() => setDark((previous) => !previous)}
            >
              {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto flex min-h-[calc(100dvh-76px)] max-w-7xl items-center justify-center px-4 py-10 sm:px-8">
        <section
          aria-labelledby="console-login-title"
          className="w-full max-w-md rounded-3xl border border-border bg-card/95 p-6 shadow-sm sm:p-9"
        >
          <div className="mb-6 flex size-12 items-center justify-center rounded-2xl bg-muted">
            <ShieldCheck className="size-6" aria-hidden="true" />
          </div>
          <p className="mb-2 text-[10px] tracking-[0.2em] text-muted-foreground">
            VEXBOT / CONSOLE
          </p>
          <h1
            id="console-login-title"
            className="text-2xl font-semibold tracking-tight"
          >
            登录 VexBot
          </h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            使用现有管理员账号登录，统一访问控制台。
          </p>

          {error && (
            <p
              role="alert"
              className="mt-5 rounded-xl border border-destructive/25 bg-destructive/5 px-4 py-3 text-sm leading-6 text-destructive"
            >
              {error}
            </p>
          )}

          {setupError ? (
            <div className="mt-6 space-y-3 rounded-xl border border-border bg-muted/30 p-4">
              <p role="alert" className="text-sm leading-6">
                {setupError}
              </p>
              <Button
                variant="outline"
                onClick={() => setSetupRetry((value) => value + 1)}
              >
                <RefreshCw />
                重新连接
              </Button>
            </div>
          ) : setupRequired === null ? (
            <p
              role="status"
              className="mt-6 flex items-center gap-2 text-sm text-muted-foreground"
            >
              <LoaderCircle className="size-4 animate-spin" />
              正在连接 VexBot 后台…
            </p>
          ) : setupRequired ? (
            <div className="mt-6 space-y-3 rounded-xl border border-border bg-muted/30 p-4">
              <p className="text-sm leading-6">
                后台尚未创建管理员账号，请先完成首次设置。
              </p>
              <Button asChild variant="outline">
                <a
                  href="http://127.0.0.1:5800/"
                  target="_blank"
                  rel="noreferrer"
                >
                  打开后台首次设置
                  <ArrowUpRight />
                </a>
              </Button>
              <Button
                variant="ghost"
                onClick={() => setSetupRetry((value) => value + 1)}
              >
                <RefreshCw />
                我已完成设置
              </Button>
            </div>
          ) : (
            <form className="mt-6 space-y-5" onSubmit={submit}>
              <label className="block space-y-2 text-sm">
                <span>用户名</span>
                <Input
                  name="username"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  maxLength={64}
                  required
                  disabled={busy}
                  className="h-11"
                />
              </label>
              <label className="block space-y-2 text-sm">
                <span>密码</span>
                <Input
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  maxLength={128}
                  required
                  disabled={busy}
                  className="h-11"
                />
              </label>
              <Button type="submit" disabled={busy} className="h-11 w-full">
                {busy && <LoaderCircle className="animate-spin" />}
                {busy ? "正在登录…" : "登录控制台"}
              </Button>
            </form>
          )}
          <p className="mt-6 text-xs leading-5 text-muted-foreground">
            登录后按账号权限开放管理功能。刷新页面后需要重新登录。
          </p>
        </section>
      </main>
    </div>
  );
}

export function ConsoleAuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthenticatedSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connectionWarning, setConnectionWarning] = useState("");
  const mounted = useRef(false);
  const sessionRef = useRef<AuthenticatedSession | null>(null);
  const epoch = useRef(0);
  const loginRequest = useRef<AbortController | null>(null);
  const validationRequest = useRef<AbortController | null>(null);
  const revokeRequests = useRef(new Set<AbortController>());

  const clearSession = useCallback(() => {
    epoch.current += 1;
    loginRequest.current?.abort();
    loginRequest.current = null;
    validationRequest.current?.abort();
    validationRequest.current = null;
    sessionRef.current = null;
    setSession(null);
    setBusy(false);
    setConnectionWarning("");
  }, []);

  const invalidate = useCallback(
    (message = "登录已失效，请重新登录。") => {
      clearSession();
      setError(message);
    },
    [clearSession],
  );

  const updateIdentity = useCallback((identity: AdminIdentity) => {
    const previous = sessionRef.current;
    if (!previous || previous.identity.id !== identity.id) return;
    const next = { ...previous, identity };
    sessionRef.current = next;
    setSession(next);
  }, []);

  const signOut = useCallback(async () => {
    const previous = sessionRef.current;
    clearSession();
    setError("");
    if (!previous) return;
    const generation = epoch.current;
    const controller = new AbortController();
    revokeRequests.current.add(controller);
    try {
      await logout(previous.token, controller.signal);
    } catch (reason) {
      if (
        mounted.current &&
        !controller.signal.aborted &&
        generation === epoch.current &&
        !sessionRef.current &&
        !(reason instanceof APIError && reason.status === 401)
      ) {
        setError(
          "已退出本页。后台会话撤销失败，请确认后台连接；原会话将在有效期结束后失效。",
        );
      }
    } finally {
      revokeRequests.current.delete(controller);
    }
  }, [clearSession]);

  const signIn = useCallback(async (username: string, password: string) => {
    if (loginRequest.current) return;
    const generation = ++epoch.current;
    const controller = new AbortController();
    loginRequest.current = controller;
    setError("");
    setBusy(true);
    try {
      const response = await login(username, password, controller.signal);
      if (
        !mounted.current ||
        controller.signal.aborted ||
        generation !== epoch.current
      )
        return;
      if (
        !response.access_token ||
        !response.identity ||
        !Number.isFinite(response.expires_in) ||
        response.expires_in <= 0
      )
        throw new APIError(0, "后台返回的登录信息不完整，请重新登录。");
      const next = {
        token: response.access_token,
        identity: response.identity,
        expiresAt: Date.now() + response.expires_in * 1000,
      };
      sessionRef.current = next;
      setSession(next);
      setConnectionWarning("");
    } catch (reason) {
      if (
        mounted.current &&
        !controller.signal.aborted &&
        generation === epoch.current
      )
        setError(errorMessage(reason, "登录失败，请稍后重试。"));
    } finally {
      if (loginRequest.current === controller) {
        loginRequest.current = null;
        if (mounted.current && generation === epoch.current) setBusy(false);
      }
    }
  }, []);

  const revalidate = useCallback(async () => {
    const current = sessionRef.current;
    if (!current || validationRequest.current) return;
    if (Date.now() >= current.expiresAt) {
      invalidate();
      return;
    }
    const generation = epoch.current;
    const controller = new AbortController();
    validationRequest.current = controller;
    const isCurrent = () =>
      mounted.current &&
      !controller.signal.aborted &&
      generation === epoch.current &&
      sessionRef.current?.token === current.token;
    try {
      const identity = await playerApi(current.token).session(
        controller.signal,
      );
      if (!isCurrent()) return;
      updateIdentity(identity);
      setConnectionWarning("");
    } catch (reason) {
      if (!isCurrent()) return;
      if (reason instanceof APIError && reason.status === 401) invalidate();
      else setConnectionWarning("暂时无法验证登录状态，连接恢复后将自动重试。");
    } finally {
      if (validationRequest.current === controller)
        validationRequest.current = null;
    }
  }, [invalidate, updateIdentity]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      epoch.current += 1;
      loginRequest.current?.abort();
      loginRequest.current = null;
      validationRequest.current?.abort();
      validationRequest.current = null;
      revokeRequests.current.forEach((controller) => controller.abort());
      revokeRequests.current.clear();
    };
  }, []);

  const token = session?.token;
  const expiresAt = session?.expiresAt;
  useEffect(() => {
    if (!token || !expiresAt) return;
    void revalidate();
    const timer = window.setInterval(() => void revalidate(), 60_000);
    const expiration = window.setTimeout(
      () => {
        if (sessionRef.current?.token === token) invalidate();
      },
      Math.max(0, expiresAt - Date.now()),
    );
    const onFocus = () => void revalidate();
    const onVisibility = () => {
      if (document.visibilityState === "visible") void revalidate();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(timer);
      window.clearTimeout(expiration);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
      validationRequest.current?.abort();
      validationRequest.current = null;
    };
  }, [token, expiresAt, invalidate, revalidate]);

  const value = useMemo<ConsoleAuth | null>(
    () =>
      session
        ? {
            token: session.token,
            identity: session.identity,
            signOut,
            invalidate,
            updateIdentity,
          }
        : null,
    [session, signOut, invalidate, updateIdentity],
  );

  if (!value) return <LoginScreen busy={busy} error={error} onLogin={signIn} />;

  return (
    <ConsoleAuthContext.Provider value={value}>
      {connectionWarning && (
        <div
          role="status"
          className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-border bg-muted px-4 py-2 text-sm text-foreground"
        >
          <span>{connectionWarning}</span>
          <Button size="sm" variant="ghost" onClick={() => void revalidate()}>
            <RefreshCw />
            重试验证
          </Button>
        </div>
      )}
      {children}
    </ConsoleAuthContext.Provider>
  );
}

export function useConsoleAuth(): ConsoleAuth {
  const context = useContext(ConsoleAuthContext);
  if (!context)
    throw new Error(
      "useConsoleAuth requires an authenticated ConsoleAuthProvider",
    );
  return context;
}
