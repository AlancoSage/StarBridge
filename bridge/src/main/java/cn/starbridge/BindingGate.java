package cn.starbridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import org.bukkit.Bukkit;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.HandlerList;
import org.bukkit.event.Listener;
import org.bukkit.event.player.AsyncPlayerPreLoginEvent;
import org.bukkit.plugin.Plugin;

import java.lang.reflect.Method;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Future;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Admission runs before world entry, never grants game-login proof or caches player approvals. */
final class BindingGate implements Listener {
    interface Transport { JsonObject post(String route, JsonObject data) throws Exception; }
    private static final String UNAVAILABLE = "VexBot 暂时无法核验绑定，请稍后重试或联系管理员。";
    private static final Method NATIVE_UUID = BukkitCompatibility.method(AsyncPlayerPreLoginEvent.class, "getUniqueId");
    private static final class Policy {
        final boolean known, required, available;
        final String message, revision;
        final long generation;
        Policy(boolean known, boolean required, boolean available, String message, String revision, long generation) {
            this.known = known; this.required = required; this.available = available;
            this.message = message; this.revision = revision; this.generation = generation;
        }
        boolean same(Policy other) {
            return known == other.known && required == other.required && available == other.available
                && message.equals(other.message) && revision.equals(other.revision);
        }
    }
    private final Transport transport;
    private final Plugin plugin;
    private final Path policyMarker;
    private boolean explicitPolicySeen;
    private final ThreadPoolExecutor workers = new ThreadPoolExecutor(4, 4, 0, TimeUnit.SECONDS,
        new ArrayBlockingQueue<Runnable>(16), runnable -> {
            Thread thread = new Thread(runnable, "VexBot-BindingGate"); thread.setDaemon(true); return thread;
        });
    private volatile Policy policy = new Policy(false, true, false, UNAVAILABLE, "", 0);
    private volatile boolean closed;

    BindingGate(Plugin plugin, Transport transport) {
        this.plugin = plugin; this.transport = transport;
        policyMarker = plugin.getDataFolder().toPath().resolve("binding-gate-policy.seen");
        try { explicitPolicySeen = Files.exists(policyMarker, LinkOption.NOFOLLOW_LINKS); }
        catch (RuntimeException unavailable) { explicitPolicySeen = true; }
        Bukkit.getPluginManager().registerEvents(this, plugin);
    }

    static boolean supported() { return NATIVE_UUID != null; }

    /** A missing field only establishes compatibility before any explicit policy was received. */
    synchronized void accept(JsonObject response) {
        if (closed || response == null) return;
        if (!response.has("binding_policy")) {
            if (!explicitPolicySeen && !policy.known)
                policy = new Policy(true, false, true, "", "legacy", policy.generation + 1);
            return;
        }
        rememberProtocol();
        try {
            Policy candidate = parse(response.getAsJsonObject("binding_policy"));
            update(candidate);
        }
        catch (RuntimeException malformed) { /* Keep unknown/enabled policies closed. */ }
    }

    private void update(Policy candidate) {
        Policy current = policy;
        if (!candidate.same(current)) policy = new Policy(candidate.known, candidate.required, candidate.available,
            candidate.message, candidate.revision, current.generation + 1);
    }

    private void rememberProtocol() {
        if (explicitPolicySeen) return;
        // This marker remembers only the protocol version, never approvals or account data.
        // After a restart, an older/missing policy must not silently disable a gate used before.
        explicitPolicySeen = true;
        try {
            Files.createDirectories(policyMarker.getParent());
            if (!Files.exists(policyMarker, LinkOption.NOFOLLOW_LINKS))
                Files.write(policyMarker, new byte[]{'1', '\n'}, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
        } catch (IOException | RuntimeException unavailable) {
            plugin.getLogger().warning("VexBot 绑定准入政策标记无法保存，请检查插件数据目录的写入权限。");
        }
    }

    private static boolean bool(JsonObject value, String key) {
        JsonElement element = value.get(key);
        if (element == null || !element.isJsonPrimitive() || !element.getAsJsonPrimitive().isBoolean())
            throw new IllegalArgumentException("Invalid binding policy");
        return element.getAsBoolean();
    }

    private static String text(JsonObject value, String key, int limit) {
        JsonElement element = value.get(key);
        if (element == null || !element.isJsonPrimitive() || !element.getAsJsonPrimitive().isString())
            throw new IllegalArgumentException("Invalid binding policy");
        String result = element.getAsString();
        if (result.length() > limit) throw new IllegalArgumentException("Invalid binding policy");
        return result;
    }

    private static Policy parse(JsonObject value) {
        return new Policy(true, bool(value, "required"), bool(value, "available"),
            text(value, "message", 1000), text(value, "revision", 200), 0);
    }

    @EventHandler(priority = EventPriority.HIGHEST)
    public void onPreLogin(AsyncPlayerPreLoginEvent event) {
        // Never replace bans/whitelist or another admission plugin's rejection.
        if (event.getLoginResult() != AsyncPlayerPreLoginEvent.Result.ALLOWED) return;
        UUID identity = null;
        try {
            Object nativeIdentity = NATIVE_UUID == null ? null : NATIVE_UUID.invoke(event);
            if (nativeIdentity instanceof UUID) identity = (UUID) nativeIdentity;
        } catch (ReflectiveOperationException | RuntimeException unavailable) { }
        String message = check(identity, event.getName(), event.isAsynchronous());
        if (message != null && event.getLoginResult() == AsyncPlayerPreLoginEvent.Result.ALLOWED)
            event.disallow(AsyncPlayerPreLoginEvent.Result.KICK_OTHER, message);
    }

    /** Null means permitted. This method never reads Bukkit player state or derives UUIDs from names. */
    String check(UUID identity, String name, boolean asynchronous) {
        Policy before = policy;
        if (closed) return denial(UNAVAILABLE, identity);
        if (!asynchronous || !supported() || identity == null || name == null || !name.matches("[A-Za-z0-9_]{1,16}"))
            return fallback(identity);
        JsonObject request = new JsonObject();
        request.addProperty("uuid", identity.toString()); request.addProperty("player", name);
        Future<JsonObject> pending = null;
        try {
            pending = workers.submit(() -> transport.post("/binding-check", request));
            JsonObject response = pending.get(4500, TimeUnit.MILLISECONDS);
            Policy answer = parse(response);
            boolean allowed = bool(response, "allowed");
            synchronized (this) {
                if (closed) return denial(UNAVAILABLE, identity);
                Policy current = policy;
                // A late check cannot undo a newer tick policy or release an enabled gate.
                if (current.generation != before.generation && !answer.same(current)) return fallback(identity);
                rememberProtocol();
                update(answer);
                if (allowed && answer.available) return null;
                return denial(answer.available ? answer.message : UNAVAILABLE, identity);
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return fallback(identity);
        } catch (Exception unavailable) {
            return fallback(identity);
        } finally {
            if (pending != null && !pending.isDone()) {
                pending.cancel(true);
                if (pending instanceof Runnable) workers.remove((Runnable) pending);
            }
        }
    }

    private String fallback(UUID identity) {
        Policy current = policy;
        return !closed && current.known && !current.required ? null : denial(UNAVAILABLE, identity);
    }

    private static String denial(String configured, UUID identity) {
        String message = configured == null ? "" : configured.replaceAll("[\\p{Cntrl}\\u00a7]", " ").trim();
        if (message.isEmpty()) message = "请先完成 QQ 与游戏账号绑定，再连接服务器。";
        if (message.codePointCount(0, message.length()) > 300)
            message = message.substring(0, message.offsetByCodePoints(0, 300));
        return message + "\n请联系管理员核实绑定。" + (identity == null ? "" : "\n玩家 UUID：" + identity);
    }

    void close() {
        synchronized (this) { closed = true; }
        HandlerList.unregisterAll(this);
        workers.shutdownNow();
    }
}
