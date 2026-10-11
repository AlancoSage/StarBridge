package cn.starbridge;

import java.io.IOException;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.Collections;
import java.util.Set;
import java.util.TreeSet;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.HandlerList;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.server.PluginDisableEvent;
import org.bukkit.plugin.Plugin;

/** Optional LibreLogin Paper adapter, using its public API without linking its Java 21 classes. */
final class LibreLoginLink implements LoginLink, Listener {
    private static final Set<String> COMMANDS = Collections.unmodifiableSet(new TreeSet<String>(Arrays.asList(
        "librelogin:login", "librelogin:l", "librelogin:log", "librelogin:register", "librelogin:reg",
        "librelogin:2fa", "librelogin:2faconfirm")));

    private final Plugin installed;
    private final Plugin owner;
    private final Object api;
    private final Object authorization;
    private final Object database;
    private final Method authorized;
    private final Method awaitingTwoFactor;
    private final Method authorize;
    private final Method playerForUUID;
    private final Method userForUUID;
    private final Method userForName;
    private final Method userUUID;
    private final Method userName;
    private final Method registered;
    private final Method secret;
    private final Object loginReason;
    private final boolean nativeTwoFactorAvailable;
    private final VerifiedLoginAccounts accounts;
    private final ConcurrentHashMap<UUID, Attempt> attempts = new ConcurrentHashMap<UUID, Attempt>();
    private final ExecutorService worker = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "Myrinbot-LibreLogin");
        thread.setDaemon(true);
        return thread;
    });
    private volatile boolean closed;

    LibreLoginLink(Plugin installed, Plugin owner) throws ReflectiveOperationException, IOException {
        if (BridgeScheduler.isFolia()) throw new IOException("LibreLogin 接入目前仅支持普通 Paper，不能用于 Folia。");
        if (installed == null || owner == null || !installed.isEnabled() || !owner.isEnabled())
            throw new IOException("LibreLogin 或Myrinbot尚未启用。");
        this.installed = installed;
        this.owner = owner;
        ClassLoader loader = installed.getClass().getClassLoader();
        Class<?> providerType = Class.forName("xyz.kyngs.librelogin.api.provider.LibreLoginProvider", false, loader);
        Class<?> apiType = Class.forName("xyz.kyngs.librelogin.api.LibreLoginPlugin", false, loader);
        Class<?> authorizationType = Class.forName("xyz.kyngs.librelogin.api.authorization.AuthorizationProvider", false, loader);
        Class<?> platformType = Class.forName("xyz.kyngs.librelogin.api.PlatformHandle", false, loader);
        Class<?> readType = Class.forName("xyz.kyngs.librelogin.api.database.ReadDatabaseProvider", false, loader);
        Class<?> userType = Class.forName("xyz.kyngs.librelogin.api.database.User", false, loader);
        Class<?> reasonType = Class.forName("xyz.kyngs.librelogin.api.event.events.AuthenticatedEvent$AuthenticationReason", false, loader);
        if (!providerType.isInstance(installed)) throw new IOException("LibreLogin 未提供受支持的公共 API。");
        api = providerType.getMethod("getLibreLogin").invoke(installed);
        if (api == null || !apiType.isInstance(api)) throw new IOException("LibreLogin 公共 API 尚未初始化。");
        Object platform = apiType.getMethod("getPlatformHandle").invoke(api);
        if (platform == null || !platformType.isInstance(platform)
                || !"paper".equals(platformType.getMethod("getPlatformIdentifier").invoke(platform))
                || platformType.getMethod("getPlayerClass").invoke(platform) != Player.class
                || !Boolean.FALSE.equals(apiType.getMethod("multiProxyEnabled").invoke(api)))
            throw new IOException("仅支持安装在本 Paper 服务器的 LibreLogin；代理端登录需要单独接入。");
        authorization = apiType.getMethod("getAuthorizationProvider").invoke(api);
        database = apiType.getMethod("getDatabaseProvider").invoke(api);
        if (!authorizationType.isInstance(authorization) || !readType.isInstance(database))
            throw new IOException("LibreLogin 授权或数据库 API 不可用。");
        authorized = authorizationType.getMethod("isAuthorized", Object.class);
        awaitingTwoFactor = authorizationType.getMethod("isAwaiting2FA", Object.class);
        authorize = authorizationType.getMethod("authorize", userType, Object.class, reasonType);
        playerForUUID = apiType.getMethod("getPlayerForUUID", UUID.class);
        userForUUID = readType.getMethod("getByUUID", UUID.class);
        userForName = readType.getMethod("getByName", String.class);
        userUUID = userType.getMethod("getUuid");
        userName = userType.getMethod("getLastNickname");
        registered = userType.getMethod("isRegistered");
        secret = userType.getMethod("getSecret");
        loginReason = reasonType.getField("LOGIN").get(null);
        nativeTwoFactorAvailable = apiType.getMethod("getTOTPProvider").invoke(api) != null;
        accounts = new VerifiedLoginAccounts(owner, id());
        owner.getServer().getPluginManager().registerEvents(this, owner);
    }

    public String id() { return "librelogin"; }
    public String displayName() { return "LibreLogin"; }
    public Set<String> ownershipCommands() { return COMMANDS; }
    public String ownershipPrompt() {
        return "首次接入请先完成 LibreLogin 原生注册或登录；已有账号使用 /librelogin:login <原密码> [动态验证码]，"
            + "新账号使用 /librelogin:register <密码> <重复密码>。"
            + (nativeTwoFactorAvailable ? "启用两步验证的账号每次仍需完成原生验证。" : "当前 Paper 端无法验证带有 TOTP 密钥的账号，Myrinbot会拒绝接入此类账号。");
    }

    public boolean authenticated(Player player) throws ReflectiveOperationException, IOException {
        if (!live(player)) return false;
        Attempt attempt = attempts.get(BukkitCompatibility.identity(player));
        if (attempt != null && attempt.player == player) {
            if (attempt.failure != null) throw new IOException(attempt.failure);
            if (!attempt.finished) return false;
        }
        if (!Boolean.TRUE.equals(authorized.invoke(authorization, player))
                || !Boolean.FALSE.equals(awaitingTwoFactor.invoke(authorization, player))) {
            if (attempt != null && attempt.player == player) { attempt.nativeChecked = false; attempt.nativeValid = false; }
            return false;
        }
        return validateNative(player, attempt);
    }

    public boolean start(Player player) throws ReflectiveOperationException, IOException {
        if (!live(player)) return false;
        if (authenticated(player)) return true;
        // LibreLogin has no atomic public registration API. Never replace an existing native password.
        if (!accounts.matches(player)) return false;
        UUID identity = BukkitCompatibility.identity(player);
        Attempt current = attempts.get(identity);
        if (current != null && current.player == player && current.started) {
            if (current.failure != null) throw new IOException(current.failure);
            return !current.requiresNative;
        }
        Attempt next = new Attempt(player, identity, player.getName());
        next.started = true;
        attempts.put(identity, next);
        if (current != null) current.active = false;
        try { worker.execute(() -> complete(next)); }
        catch (RejectedExecutionException rejected) {
            next.failure = "LibreLogin 接入已停止，请重新连接服务器。";
            next.finished = true;
            throw new IOException(next.failure);
        }
        return true;
    }

    private void complete(Attempt attempt) {
        try {
            if (!live(attempt)) return;
            Object user = userForUUID.invoke(database, attempt.identity);
            Object named = userForName.invoke(database, attempt.name);
            if (!sameUser(user, attempt) || !sameUser(named, attempt)
                    || !Boolean.TRUE.equals(registered.invoke(user)) || !Boolean.TRUE.equals(registered.invoke(named))) {
                attempt.requiresNative = true;
                return;
            }
            boolean hasSecret = secret.invoke(user) != null || secret.invoke(named) != null;
            if (hasSecret && !nativeTwoFactorAvailable) {
                attempt.failure = missingTwoFactor();
                return;
            }
            if (hasSecret || !Boolean.FALSE.equals(awaitingTwoFactor.invoke(authorization, attempt.player))) {
                attempt.requiresNative = true;
                return;
            }
            if (!live(attempt)) return;
            // The provider's normal authorize API performs synchronous database I/O, as its native commands do.
            // Its API does not validate TOTP, so the checks above deliberately exclude all two-factor accounts.
            if (!Boolean.TRUE.equals(authorized.invoke(authorization, attempt.player))) {
                authorize.invoke(authorization, user, attempt.player, loginReason);
            }
        } catch (ReflectiveOperationException | RuntimeException | LinkageError failure) {
            if (attempt.active) attempt.failure = "LibreLogin 公共 API 登录失败；请使用原插件登录或重新连接。";
        } finally {
            attempt.finished = true;
        }
    }

    private boolean validateNative(Player player, Attempt attempt) throws IOException {
        if (attempt == null || attempt.player != player) {
            Attempt next = new Attempt(player, BukkitCompatibility.identity(player), player.getName());
            next.finished = true;
            Attempt previous = attempts.put(next.identity, next);
            if (previous != null) previous.active = false;
            attempt = next;
        }
        if (attempt.nativeFailure != null) throw new IOException(attempt.nativeFailure);
        if (attempt.nativeChecked) return attempt.nativeValid;
        synchronized (attempt) {
            if (!attempt.nativePending) {
                attempt.nativePending = true;
                final Attempt captured = attempt;
                try { worker.execute(() -> inspectNative(captured)); }
                catch (RejectedExecutionException rejected) {
                    throw new IOException("LibreLogin 接入已停止，请重新连接服务器。");
                }
            }
        }
        return false;
    }

    private void inspectNative(Attempt attempt) {
        try {
            if (!live(attempt)) return;
            Object user = userForUUID.invoke(database, attempt.identity);
            Object named = userForName.invoke(database, attempt.name);
            if (!sameUser(user, attempt) || !sameUser(named, attempt)
                    || !Boolean.TRUE.equals(registered.invoke(user)) || !Boolean.TRUE.equals(registered.invoke(named))) {
                attempt.nativeFailure = "LibreLogin 无法确认此已认证连接的原生账号身份，请重新连接或联系管理员。";
                return;
            }
            if ((secret.invoke(user) != null || secret.invoke(named) != null) && !nativeTwoFactorAvailable) {
                attempt.nativeFailure = missingTwoFactor();
                return;
            }
            if (!live(attempt) || !Boolean.TRUE.equals(authorized.invoke(authorization, attempt.player))
                    || !Boolean.FALSE.equals(awaitingTwoFactor.invoke(authorization, attempt.player))) return;
            attempt.nativeValid = true;
            attempt.nativeChecked = true;
        } catch (ReflectiveOperationException | RuntimeException | LinkageError failure) {
            if (attempt.active) attempt.nativeFailure = "LibreLogin 无法核验原生账号状态，登录已拒绝，请联系管理员。";
        } finally {
            attempt.nativePending = false;
        }
    }

    private static String missingTwoFactor() {
        return "LibreLogin 当前 Paper 实现无法验证此账号已启用的两步验证，登录已拒绝；请将账号迁移至能完整验证两步验证的受支持登录端。";
    }

    private boolean sameUser(Object user, Attempt attempt) throws ReflectiveOperationException {
        return user != null && attempt.identity.equals(userUUID.invoke(user))
            && attempt.name.equals(userName.invoke(user));
    }

    private boolean live(Player player) throws ReflectiveOperationException {
        return !closed && owner.isEnabled() && installed.isEnabled() && player.isOnline()
            && playerForUUID.invoke(api, BukkitCompatibility.identity(player)) == player;
    }

    private boolean live(Attempt attempt) throws ReflectiveOperationException {
        // Only immutable UUID and the captured connection object are used on this worker.
        return attempt.active && attempts.get(attempt.identity) == attempt && !closed
            && owner.isEnabled() && installed.isEnabled()
            && playerForUUID.invoke(api, attempt.identity) == attempt.player;
    }

    public void remember(Player player) throws IOException {
        try {
            if (!authenticated(player)) throw new IOException("LibreLogin 尚未完成原生认证。");
            accounts.remember(player);
        } catch (ReflectiveOperationException unavailable) {
            throw new IOException("LibreLogin 公共 API 无法确认原生认证。");
        }
    }

    public void logout(Player player) {
        invalidate(player);
        // There is no public deauthorize/logout API. Disconnecting ends the native connection safely.
        player.kickPlayer("已退出Myrinbot与 LibreLogin 登录，请重新连接服务器。");
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
        worker.shutdownNow();
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
        volatile boolean active = true;
        volatile boolean started;
        volatile boolean finished;
        volatile boolean requiresNative;
        volatile String failure;
        volatile boolean nativePending;
        volatile boolean nativeChecked;
        volatile boolean nativeValid;
        volatile String nativeFailure;
        Attempt(Player player, UUID identity, String name) {
            this.player = player; this.identity = identity; this.name = name;
        }
    }
}
