package cn.starbridge;

import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.Arrays;
import java.util.Collections;
import java.util.Set;
import java.util.TreeSet;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.HandlerList;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.server.PluginDisableEvent;
import org.bukkit.plugin.Plugin;

/** Optional LoginSecurity 3.x adapter. Database work uses the provider's asynchronous action API. */
final class LoginSecurityLink implements LoginLink, Listener {
    private static final Set<String> COMMANDS = Collections.unmodifiableSet(new TreeSet<String>(Arrays.asList(
        "loginsecurity:login", "loginsecurity:l")));
    private final Plugin installed, owner;
    private final Object manager, service;
    private final Method sessionFor, registered, authorized, sessionPlayer, actionAsync, success, configuration;
    private final Method captcha, registrationEnabled, minimum, maximum;
    private final Constructor<?> loginAction, registerAction;
    private final Class<?> callbackType;
    private final VerifiedLoginAccounts accounts;
    private final ConcurrentHashMap<UUID, Attempt> attempts = new ConcurrentHashMap<UUID, Attempt>();
    private volatile boolean closed;

    LoginSecurityLink(Plugin installed, Plugin owner) throws ReflectiveOperationException, IOException {
        if (BridgeScheduler.isFolia()) throw new IOException("LoginSecurity 接入不支持 Folia。");
        if (installed == null || owner == null || !installed.isEnabled() || !owner.isEnabled())
            throw new IOException("LoginSecurity 或VexBot尚未启用。");
        this.installed = installed; this.owner = owner;
        ClassLoader loader = installed.getClass().getClassLoader();
        Class<?> api = Class.forName("com.lenis0012.bukkit.loginsecurity.LoginSecurity", false, loader);
        Class<?> sessions = Class.forName("com.lenis0012.bukkit.loginsecurity.session.SessionManager", false, loader);
        Class<?> session = Class.forName("com.lenis0012.bukkit.loginsecurity.session.PlayerSession", false, loader);
        Class<?> authService = Class.forName("com.lenis0012.bukkit.loginsecurity.session.AuthService", false, loader);
        Class<?> action = Class.forName("com.lenis0012.bukkit.loginsecurity.session.AuthAction", false, loader);
        callbackType = Class.forName("com.lenis0012.bukkit.loginsecurity.session.action.ActionCallback", false, loader);
        Class<?> response = Class.forName("com.lenis0012.bukkit.loginsecurity.session.action.ActionResponse", false, loader);
        if (!api.isInstance(installed)) throw new IOException("LoginSecurity 公共 API 与已安装插件不匹配。");
        manager = api.getMethod("getSessionManager").invoke(null);
        if (manager == null || !sessions.isInstance(manager)) throw new IOException("LoginSecurity 会话尚未初始化。");
        sessionFor = sessions.getMethod("getPlayerSession", Player.class);
        registered = session.getMethod("isRegistered");
        authorized = session.getMethod("isAuthorized");
        sessionPlayer = session.getMethod("getPlayer");
        actionAsync = session.getMethod("performActionAsync", action, callbackType);
        callbackType.getMethod("call", response);
        success = response.getMethod("isSuccess");
        service = authService.getField("PLUGIN").get(null);
        loginAction = Class.forName("com.lenis0012.bukkit.loginsecurity.session.action.LoginAction", false, loader)
            .getConstructor(authService, Object.class);
        registerAction = Class.forName("com.lenis0012.bukkit.loginsecurity.session.action.RegisterAction", false, loader)
            .getConstructor(authService, Object.class, String.class);
        configuration = api.getMethod("getConfiguration");
        Class<?> config = configuration.getReturnType();
        captcha = config.getMethod("isRegisterCaptcha");
        registrationEnabled = config.getMethod("isRegistrationEnabled");
        minimum = config.getMethod("getPasswordMinLength");
        maximum = config.getMethod("getPasswordMaxLength");
        accounts = new VerifiedLoginAccounts(owner, id());
        owner.getServer().getPluginManager().registerEvents(this, owner);
    }

    public String id() { return "loginsecurity"; }
    public String displayName() { return "LoginSecurity"; }
    public Set<String> ownershipCommands() { return COMMANDS; }
    public String ownershipPrompt() {
        return "正在等待 LoginSecurity 同步。首次接入已有账号，请用 /loginsecurity:login <原插件密码> 验证账号归属。";
    }

    public boolean authenticated(Player player) throws ReflectiveOperationException, IOException {
        if (!live(player)) return false;
        Attempt attempt = attempts.get(BukkitCompatibility.identity(player));
        if (attempt != null && attempt.player == player) {
            if (attempt.failure != null) throw new IOException(attempt.failure);
            // RegisterAction marks authorized before restoring inventory/blindness. Wait for LoginAction too.
            if (!attempt.finished) return false;
        }
        Object session = sessionFor.invoke(manager, player);
        return session != null && sessionPlayer.invoke(session) == player
            && Boolean.TRUE.equals(registered.invoke(session)) && Boolean.TRUE.equals(authorized.invoke(session));
    }

    public boolean start(Player player) throws ReflectiveOperationException, IOException {
        if (!live(player)) return false;
        if (authenticated(player)) return true;
        UUID identity = BukkitCompatibility.identity(player);
        Attempt current = attempts.get(identity);
        if (current != null && current.player == player) {
            if (current.failure != null) throw new IOException(current.failure);
            return true;
        }
        Object session = sessionFor.invoke(manager, player);
        if (session == null || sessionPlayer.invoke(session) != player) throw new IOException("LoginSecurity 会话不可用，请重新连接。");
        boolean exists = Boolean.TRUE.equals(registered.invoke(session));
        if (exists && !accounts.matches(player)) return false;
        Object action;
        if (exists) action = loginAction.newInstance(service, owner);
        else {
            Object config = configuration.invoke(null);
            if (!Boolean.TRUE.equals(registrationEnabled.invoke(config))) throw new IOException("LoginSecurity 已关闭新账号注册。");
            if (Boolean.TRUE.equals(captcha.invoke(config)))
                throw new IOException("LoginSecurity 开启了注册验证码，请先完成原插件注册再启用VexBot登录。");
            String password = VerifiedLoginAccounts.credential(((Number) minimum.invoke(config)).intValue(), ((Number) maximum.invoke(config)).intValue());
            action = registerAction.newInstance(service, owner, password);
        }
        Attempt next = new Attempt(player, identity, player.getName(), session);
        attempts.put(identity, next);
        if (current != null) current.active = false;
        submit(next, action, !exists);
        return true;
    }

    private void submit(final Attempt attempt, Object action, final boolean registration) throws ReflectiveOperationException {
        Object callback = Proxy.newProxyInstance(callbackType.getClassLoader(), new Class<?>[] { callbackType }, (proxy, method, args) -> {
            if (method.getDeclaringClass() == Object.class) {
                if ("hashCode".equals(method.getName())) return System.identityHashCode(proxy);
                if ("equals".equals(method.getName())) return proxy == args[0];
                return "VexBot LoginSecurity callback";
            }
            if (!"call".equals(method.getName())) return null;
            // LoginSecurity schedules callbacks on Bukkit's main thread.
            try {
                boolean accepted = args != null && args.length == 1 && Boolean.TRUE.equals(success.invoke(args[0]));
                // Keep a creation receipt even if this connection left before the callback. This does not release a gate.
                // Otherwise a successfully created random-password account could become impossible to link on rejoin.
                if (registration && accepted && Boolean.TRUE.equals(registered.invoke(attempt.session)))
                    accounts.remember(attempt.identity, attempt.name);
                if (!live(attempt)) return null;
                if (!accepted) {
                    attempt.failure = "LoginSecurity 拒绝了本次登录，请检查其配置或重新连接。";
                    attempt.finished = true;
                } else if (registration) {
                    if (!Boolean.TRUE.equals(registered.invoke(attempt.session))) throw new IOException("LoginSecurity 尚未完成注册。");
                    // This account was just created after independent VexBot proof, never an existing native account.
                    submit(attempt, loginAction.newInstance(service, owner), false);
                } else attempt.finished = true;
            } catch (ReflectiveOperationException | RuntimeException | IOException error) {
                attempt.failure = "LoginSecurity 登录同步失败，请重新连接或联系管理员。";
                attempt.finished = true;
            }
            return null;
        });
        try { actionAsync.invoke(attempt.session, action, callback); }
        catch (ReflectiveOperationException | RuntimeException error) {
            attempt.failure = "LoginSecurity 无法提交登录请求，请重新连接。";
            attempt.finished = true;
            throw error;
        }
    }

    private boolean live(Player player) {
        return !closed && owner.isEnabled() && installed.isEnabled() && player.isOnline()
            && BukkitCompatibility.player(BukkitCompatibility.identity(player)) == player;
    }

    private boolean live(Attempt attempt) throws ReflectiveOperationException {
        return attempt.active && attempts.get(attempt.identity) == attempt && live(attempt.player)
            && sessionFor.invoke(manager, attempt.player) == attempt.session && sessionPlayer.invoke(attempt.session) == attempt.player;
    }

    public void remember(Player player) throws IOException {
        try {
            if (!authenticated(player)) throw new IOException("LoginSecurity 尚未完成原生认证。");
            accounts.remember(player);
        } catch (ReflectiveOperationException unavailable) { throw new IOException("LoginSecurity 无法确认原生认证。"); }
    }

    public void logout(Player player) {
        invalidate(player);
        // A disconnect avoids claiming completion before the provider's async logout action actually finishes.
        player.kickPlayer("已退出VexBot与 LoginSecurity 登录，请重新连接服务器。");
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onQuit(PlayerQuitEvent event) { invalidate(event.getPlayer()); }
    @EventHandler(priority = EventPriority.MONITOR)
    public void onDisable(PluginDisableEvent event) {
        if (event.getPlugin() != owner && event.getPlugin() != installed) return;
        close();
    }
    public void close() {
        closed = true;
        for (Attempt attempt : attempts.values()) attempt.active = false;
        attempts.clear();
        HandlerList.unregisterAll(this);
    }
    private void invalidate(Player player) {
        UUID identity = BukkitCompatibility.identity(player);
        Attempt attempt = attempts.get(identity);
        if (attempt != null && attempt.player == player && attempts.remove(identity, attempt)) attempt.active = false;
    }
    private static final class Attempt {
        final Player player;
        final UUID identity;
        final String name;
        final Object session;
        volatile boolean active = true, finished;
        volatile String failure;
        Attempt(Player player, UUID identity, String name, Object session) { this.player = player; this.identity = identity; this.name = name; this.session = session; }
    }
}
