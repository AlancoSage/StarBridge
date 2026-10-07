package cn.starbridge;

import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;
import org.bukkit.Bukkit;
import org.bukkit.OfflinePlayer;
import org.bukkit.entity.Player;
import org.bukkit.entity.Projectile;
import org.bukkit.event.*;
import org.bukkit.plugin.Plugin;

/** Detect capabilities instead of hard-linking to version-specific Bukkit classes. */
final class BukkitCompatibility {
    private static final Map<String, Optional<Method>> METHODS = new ConcurrentHashMap<>();

    static final class Profile {
        final UUID identity;
        final String name;
        Profile(UUID identity, String name) { this.identity = identity; this.name = name; }
    }

    static Profile lookupProfile(String name, UUID expected) throws java.io.IOException {
        if (!name.matches("[A-Za-z0-9_]{1,16}")) throw new IllegalArgumentException("Invalid profile name");
        BridgeHttp.Response response = BridgeHttp.request("https://api.minecraftservices.com/minecraft/profile/lookup/name/" + name, null, null, 6000);
        if (response.status != 200) throw new java.io.IOException("Official profile lookup failed");
        com.google.gson.JsonObject value = com.google.gson.JsonParser.parseString(response.body).getAsJsonObject();
        return verifiedProfile(name, expected, value.get("id").getAsString(), value.get("name").getAsString());
    }

    static Profile verifiedProfile(String requested, UUID expected, String raw, String canonical) {
        if (!raw.matches("[A-Fa-f0-9]{32}") || !canonical.matches("[A-Za-z0-9_]{1,16}") || !requested.equalsIgnoreCase(canonical))
            throw new IllegalArgumentException("Official profile mismatch");
        UUID identity = UUID.fromString(raw.substring(0, 8) + "-" + raw.substring(8, 12) + "-" + raw.substring(12, 16) + "-" + raw.substring(16, 20) + "-" + raw.substring(20));
        if (expected != null && !expected.equals(identity)) throw new IllegalArgumentException("UUID mismatch");
        return new Profile(identity, canonical);
    }

    static Method method(Class<?> owner, String name, Class<?>... parameters) {
        String key = owner.getName() + ":" + name + Arrays.toString(parameters);
        return METHODS.computeIfAbsent(key, ignored -> {
            try { return Optional.of(owner.getMethod(name, parameters)); }
            catch (NoSuchMethodException exception) { return Optional.empty(); }
        }).orElse(null);
    }

    private static Object call(Method method, Object target, Object... values) {
        if (method == null) throw new IllegalStateException("Server API is unavailable");
        try { return method.invoke(target, values); }
        catch (ReflectiveOperationException exception) { throw new IllegalStateException("Server API call failed", exception); }
    }

    static UUID identity(OfflinePlayer player) {
        Method method = method(OfflinePlayer.class, "getUniqueId");
        if (method != null) return (UUID) call(method, player);
        return UUID.nameUUIDFromBytes(("OfflinePlayer:" + player.getName()).getBytes(StandardCharsets.UTF_8));
    }

    static boolean nativeIdentities() {
        return method(OfflinePlayer.class, "getUniqueId") != null;
    }

    static UUID legacyIdentity(String name) {
        return UUID.nameUUIDFromBytes(("OfflinePlayer:" + name).getBytes(StandardCharsets.UTF_8));
    }

    static List<Player> players() {
        Object value = call(method(Bukkit.class, "getOnlinePlayers"), null);
        List<Player> players = new ArrayList<>();
        if (value instanceof Iterable<?>) {
            for (Object player : (Iterable<?>) value) players.add((Player) player);
        } else if (value != null && value.getClass().isArray()) {
            for (int index = 0; index < Array.getLength(value); index++) players.add((Player) Array.get(value, index));
        } else throw new IllegalStateException("Unsupported online player API");
        return players;
    }

    static Player player(UUID identity) {
        Method method = method(Bukkit.class, "getPlayer", UUID.class);
        if (method != null) return (Player) call(method, null, identity);
        for (Player player : players()) if (identity.equals(identity(player))) return player;
        return null;
    }

    static OfflinePlayer offline(UUID identity, String name) {
        Method method = method(Bukkit.class, "getOfflinePlayer", UUID.class);
        if (method != null) return (OfflinePlayer) call(method, null, identity);
        return Bukkit.getOfflinePlayer(name);
    }

    static long lastPlayed(OfflinePlayer player) {
        Method method = method(OfflinePlayer.class, "getLastPlayed");
        return method == null ? 0 : ((Number) call(method, player)).longValue();
    }

    static Double health(Player player) {
        Method method = method(Player.class, "getHealth");
        return method == null ? null : ((Number) call(method, player)).doubleValue();
    }

    static Integer ping(Player player) {
        Method method = method(Player.class, "getPing");
        return method == null ? null : Math.max(0, ((Number) call(method, player)).intValue());
    }

    static Object shooter(Projectile projectile) {
        return call(method(Projectile.class, "getShooter"), projectile);
    }

    static void runTask(Plugin plugin, Runnable task) {
        Bukkit.getScheduler().scheduleSyncDelayedTask(plugin, task);
    }

    static void repeat(Plugin plugin, Runnable task, long delay, long period) {
        Bukkit.getScheduler().scheduleSyncRepeatingTask(plugin, task, delay, period);
    }

    static boolean optionalEvent(Plugin plugin, String name, Consumer<Event> handler) {
        try {
            Class<? extends Event> type = Class.forName(name, false, plugin.getClass().getClassLoader()).asSubclass(Event.class);
            Bukkit.getPluginManager().registerEvent(type, new Listener() {}, EventPriority.HIGHEST,
                (listener, event) -> { if (type.isInstance(event)) handler.accept(event); }, plugin, true);
            return true;
        } catch (ClassNotFoundException ignored) { return false; }
    }

    static Object eventValue(Event event, String getter) {
        return call(method(event.getClass(), getter), event);
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private static Object bans(String name) {
        try {
            Class type = Class.forName("org.bukkit.BanList$Type");
            Object value = Enum.valueOf(type, name);
            Method accessor = method(Bukkit.class, "getBanList", type);
            return accessor == null ? null : call(accessor, null, value);
        } catch (ClassNotFoundException | IllegalArgumentException ignored) { return null; }
    }

    private static Object banCall(Object list, String name, Object... args) {
        // Interfaces avoid invoking inaccessible implementation classes on newer Java runtimes.
        for (Class<?> implementation = list.getClass(); implementation != null; implementation = implementation.getSuperclass()) {
          for (Class<?> type : implementation.getInterfaces()) {
            for (Method method : type.getMethods()) {
                if (!method.getName().equals(name) || method.getParameterTypes().length != args.length) continue;
                boolean compatible = true;
                for (int index = 0; index < args.length; index++) {
                    Class<?> parameter = method.getParameterTypes()[index];
                    if (args[index] != null && !parameter.isInstance(args[index])) compatible = false;
                    if (args[index] == null && name.equals("addBan") && index == 2 && parameter != Date.class) compatible = false;
                }
                if (compatible) return call(method, list, args);
            }
          }
        }
        throw new IllegalStateException("Unsupported ban API");
    }

    static void ban(OfflinePlayer player, String reason) {
        Method modern = method(OfflinePlayer.class, "ban", String.class, Date.class, String.class);
        if (modern != null) {
            if (call(modern, player, reason, null, "StarBridge") == null) throw new IllegalStateException("Ban failed");
        } else {
            Object list = bans("NAME");
            if (list != null) {
                if (banCall(list, "addBan", player.getName(), reason, null, "StarBridge") == null) throw new IllegalStateException("Ban failed");
            } else call(method(OfflinePlayer.class, "setBanned", boolean.class), player, true);
        }
        if (!player.isBanned()) throw new IllegalStateException("Ban not confirmed");
    }

    static void unban(OfflinePlayer player) {
        Object profiles = bans("PROFILE");
        Method profile = method(OfflinePlayer.class, "getPlayerProfile");
        if (profiles != null && profile != null) banCall(profiles, "pardon", call(profile, player));
        Object names = bans("NAME");
        if (names != null) banCall(names, "pardon", player.getName());
        else if (profiles == null) call(method(OfflinePlayer.class, "setBanned", boolean.class), player, false);
        if (player.isBanned()) throw new IllegalStateException("Unban not confirmed");
    }

    static String banReason(OfflinePlayer player) {
        Object entry = null;
        Object profiles = bans("PROFILE");
        Method profile = method(OfflinePlayer.class, "getPlayerProfile");
        if (profiles != null && profile != null) entry = banCall(profiles, "getBanEntry", call(profile, player));
        Object names = bans("NAME");
        if (entry == null && names != null) entry = banCall(names, "getBanEntry", player.getName());
        if (entry == null) return null;
        try { return (String) call(method(Class.forName("org.bukkit.BanEntry"), "getReason"), entry); }
        catch (ClassNotFoundException ignored) { return null; }
    }
}
