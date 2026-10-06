package cn.starbridge;

import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.logging.Logger;
import org.bukkit.*;
import org.bukkit.entity.Player;
import org.bukkit.event.*;
import org.bukkit.plugin.*;
import org.bukkit.scheduler.BukkitScheduler;
import com.google.gson.*;

/** Executes against real legacy API interfaces, with a simulated server (no game server). */
public final class BukkitCompatibilityCheck {
    @SuppressWarnings("unchecked")
    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return (T) Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, handler);
    }
    private static Object fallback(Method method) {
        Class<?> type = method.getReturnType();
        if (type == boolean.class) return false;
        if (type == int.class) return 0;
        if (type == long.class) return 0L;
        if (type == double.class) return 0D;
        if (type == float.class) return 0F;
        return null;
    }
    public static void main(String[] args) throws Exception {
        AtomicBoolean banned = new AtomicBoolean();
        UUID nativeId = UUID.fromString("069a79f4-44e9-4726-a5be-fca90e38aaf5");
        Player actor = proxy(Player.class, (self, method, values) -> {
            String name = method.getName();
            if (name.equals("getName")) return "Notch";
            if (name.equals("getUniqueId")) return nativeId;
            if (name.equals("getHealth")) { if (method.getReturnType() == int.class) return 20; return 20D; }
            if (name.equals("getPing")) return 35;
            if (name.equals("isOnline")) return true;
            if (name.equals("isBanned")) return banned.get();
            if (name.equals("setBanned")) { banned.set((Boolean) values[0]); return null; }
            if (name.equals("getServer")) return Bukkit.getServer();
            if (name.equals("hashCode")) return nativeId.hashCode();
            if (name.equals("equals")) return self == values[0];
            return fallback(method);
        });
        Map<String, EventExecutor> handlers = new HashMap<>();
        PluginManager manager = proxy(PluginManager.class, (self, method, values) -> {
            if (method.getName().equals("registerEvent")) handlers.put(((Class<?>) values[0]).getName(), (EventExecutor) values[3]);
            return fallback(method);
        });
        List<Runnable> tasks = new ArrayList<>();
        BukkitScheduler scheduler = proxy(BukkitScheduler.class, (self, method, values) -> {
            if (method.getName().equals("scheduleSyncDelayedTask") || method.getName().equals("scheduleSyncRepeatingTask")) { tasks.add((Runnable) values[1]); return 1; }
            return fallback(method);
        });
        Server server = proxy(Server.class, (self, method, values) -> {
            String name = method.getName();
            if (name.equals("getOnlinePlayers")) return method.getReturnType().isArray() ? new Player[]{actor} : Collections.singletonList(actor);
            if (name.equals("getPlayer") || name.equals("getOfflinePlayer")) return actor;
            if (name.equals("getPluginManager")) return manager;
            if (name.equals("getScheduler")) return scheduler;
            if (name.equals("getLogger")) return Logger.getLogger("StarBridge-compatibility");
            if (name.equals("getName") || name.equals("getVersion") || name.equals("getBukkitVersion")) return "isolated compatibility test";
            if (name.equals("getBanList")) {
                return proxy(method.getReturnType(), (list, action, arguments) -> {
                    if (action.getName().equals("addBan")) { banned.set(true); return proxy(action.getReturnType(), (entry, getter, ignored) -> fallback(getter)); }
                    if (action.getName().equals("pardon")) banned.set(false);
                    return fallback(action);
                });
            }
            return fallback(method);
        });
        Bukkit.setServer(server);
        Plugin plugin = proxy(Plugin.class, (self, method, values) -> {
            if (method.getName().equals("getLogger")) return Logger.getLogger("StarBridge-compatibility");
            if (method.getName().equals("getServer")) return server;
            if (method.getName().equals("isEnabled")) return true;
            return fallback(method);
        });
        UUID identity = BukkitCompatibility.identity(actor);
        assert identity.equals(BukkitCompatibility.nativeIdentities() ? nativeId : BukkitCompatibility.legacyIdentity("Notch"));
        assert BukkitCompatibility.players().size() == 1;
        assert BukkitCompatibility.player(identity) == actor;
        assert BukkitCompatibility.offline(identity, "Notch") == actor;
        assert BukkitCompatibility.health(actor) == 20D;
        assert BukkitCompatibility.ping(actor) == null : "Old APIs must omit unsupported ping";
        BukkitCompatibility.ban(actor, "test"); assert banned.get();
        BukkitCompatibility.unban(actor); assert !banned.get();
        assert BukkitCompatibility.verifiedProfile("notch", nativeId, "069a79f444e94726a5befca90e38aaf5", "Notch").identity.equals(nativeId);
        int mismatches = 0;
        try { BukkitCompatibility.verifiedProfile("Other", nativeId, "069a79f444e94726a5befca90e38aaf5", "Notch"); } catch (IllegalArgumentException expected) { mismatches++; }
        try { BukkitCompatibility.verifiedProfile("Notch", UUID.randomUUID(), "069a79f444e94726a5befca90e38aaf5", "Notch"); } catch (IllegalArgumentException expected) { mismatches++; }
        assert mismatches == 2;
        assert !BukkitCompatibility.optionalEvent(plugin, "org.bukkit.event.DoesNotExistEvent", event -> {});
        GameLogin login = new GameLogin(plugin, (route, body) -> { throw new IllegalStateException("offline"); });
        Class<?> pickup = Class.forName("org.bukkit.event.player.PlayerPickupItemEvent");
        Event event = (Event) pickup.getConstructor(Player.class, Class.forName("org.bukkit.entity.Item"), int.class).newInstance(actor, null, 0);
        handlers.get(pickup.getName()).execute(null, event);
        assert ((Cancellable) event).isCancelled() : "Unknown/offline policy must keep login gate closed";
        JsonObject data = new JsonObject(), policy = new JsonObject();
        policy.addProperty("required", false); policy.addProperty("revision", "disabled");
        policy.addProperty("password_login", false); policy.addProperty("qq_login", true); policy.addProperty("login_seconds", 120);
        data.add("authentication", policy);
        login.accept(data);
        Event released = (Event) pickup.getConstructor(Player.class, Class.forName("org.bukkit.entity.Item"), int.class).newInstance(actor, null, 0);
        handlers.get(pickup.getName()).execute(null, released);
        assert !((Cancellable) released).isCancelled() : "Explicitly disabled authentication should release the gate";
        assert !tasks.isEmpty(); login.close();
        System.out.println("Legacy API runtime checks passed: identities, online players, health, bans, optional events, login gate");
    }
}
