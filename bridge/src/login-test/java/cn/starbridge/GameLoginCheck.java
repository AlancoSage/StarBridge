package cn.starbridge;

import com.google.gson.*;
import org.bukkit.*;
import org.bukkit.entity.Player;
import org.bukkit.event.block.BlockBreakEvent;
import org.bukkit.event.entity.EntityDamageEvent;
import org.bukkit.event.player.*;
import org.bukkit.plugin.*;
import org.bukkit.scheduler.*;

import java.lang.reflect.*;
import java.net.InetSocketAddress;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.BooleanSupplier;
import java.util.logging.Logger;

/** Runs real event handlers against an isolated Bukkit API stub, without a Minecraft server. */
public final class GameLoginCheck {
    private static final Queue<Runnable> callbacks = new ConcurrentLinkedQueue<>();
    private static final List<Runnable> timers = new ArrayList<>();
    private static final Logger logger = Logger.getLogger("StarBridge-test");
    private static FakePlayer actor;
    private static boolean authMe;
    private static Plugin installedAuthMe;
    private static final List<JsonObject> requests = Collections.synchronizedList(new ArrayList<>());
    private static volatile CompletableFuture<JsonObject> passwordAnswer;
    private static final AtomicBoolean offline = new AtomicBoolean();

    @SuppressWarnings("unchecked")
    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return (T) Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, handler);
    }
    private static Object defaultValue(Method method) {
        if (method.getReturnType() == boolean.class) return false;
        if (method.getReturnType() == int.class) return 0;
        if (method.getReturnType() == long.class) return 0L;
        return null;
    }
    private static final class FakePlayer {
        final UUID id;
        final List<String> messages = new ArrayList<>();
        boolean online = true;
        String kicked = "";
        final Player player;
        FakePlayer(UUID id) {
            this.id = id;
            player = proxy(Player.class, (self, method, args) -> switch (method.getName()) {
                case "getUniqueId" -> id;
                case "getName" -> "Steve";
                case "getServer" -> Bukkit.getServer();
                case "isOnline" -> online;
                case "getAddress" -> new InetSocketAddress("127.0.0.1", 25565);
                case "sendMessage" -> { if (args[0] instanceof String text) messages.add(text); yield null; }
                case "kickPlayer" -> { kicked = (String) args[0]; online = false; yield null; }
                case "hashCode" -> id.hashCode();
                case "equals" -> self == args[0];
                case "toString" -> "TestPlayer";
                default -> defaultValue(method);
            });
        }
    }
    private static void pump(BooleanSupplier condition) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
        while (!condition.getAsBoolean()) {
            Runnable callback;
            while ((callback = callbacks.poll()) != null) callback.run();
            if (System.nanoTime() > deadline) throw new AssertionError("Timed out waiting for an isolated login callback");
            Thread.sleep(5);
        }
        Runnable callback;
        while ((callback = callbacks.poll()) != null) callback.run();
    }
    private static JsonObject status(JsonObject request, String state, String revision) {
        JsonObject result = new JsonObject();
        result.add("uuid", request.get("uuid")); result.add("nonce", request.get("nonce"));
        result.addProperty("status", state); result.addProperty("revision", revision);
        result.addProperty("message", "status"); result.addProperty("expires_in", 120);
        return result;
    }
    private static JsonObject policy(boolean required, String revision, JsonObject... results) {
        JsonObject data = new JsonObject(), policy = new JsonObject();
        policy.addProperty("required", required); policy.addProperty("available", true); policy.addProperty("revision", revision);
        policy.addProperty("password_login", true); policy.addProperty("qq_login", true); policy.addProperty("login_seconds", 120);
        data.add("authentication", policy);
        JsonArray array = new JsonArray(); for (JsonObject result : results) array.add(result);
        data.add("authentication_results", array); return data;
    }
    private static JsonObject latest(String action) {
        synchronized (requests) {
            for (int index = requests.size() - 1; index >= 0; index--) {
                if (action.equals(requests.get(index).get("action").getAsString())) return requests.get(index);
            }
        }
        return null;
    }
    private static JsonObject snapshotFor(GameLogin login, FakePlayer player) {
        for (JsonElement element : login.snapshot()) {
            JsonObject record = element.getAsJsonObject();
            if (record.get("uuid").getAsString().equals(player.id.toString())) return record;
        }
        throw new AssertionError("Missing current connection heartbeat");
    }
    public static void main(String[] args) throws Exception {
        assert GameLogin.commandName("/l Password 123").equals("login");
        assert GameLogin.commandName("/ql").equals("qqlogin");
        assert GameLogin.commandName("/StarBridge:QL").equals("qqlogin");
        assert GameLogin.commandName("/authme:l Password 123").equals("authme:l");
        BukkitTask task = proxy(BukkitTask.class, (self, method, values) -> defaultValue(method));
        BukkitScheduler scheduler = proxy(BukkitScheduler.class, (self, method, values) -> {
            if (method.getName().equals("runTask")) { callbacks.add((Runnable) values[1]); return task; }
            if (method.getName().equals("runTaskTimer")) { timers.add((Runnable) values[1]); return task; }
            if (method.getName().equals("scheduleSyncDelayedTask")) { callbacks.add((Runnable) values[1]); return 1; }
            if (method.getName().equals("scheduleSyncRepeatingTask")) { timers.add((Runnable) values[1]); return 1; }
            return defaultValue(method);
        });
        PluginManager manager = proxy(PluginManager.class, (self, method, values) -> {
            if (method.getName().equals("isPluginEnabled")) return authMe;
            if (method.getName().equals("getPlugin")) return authMe ? installedAuthMe : null;
            return defaultValue(method);
        });
        Server server = proxy(Server.class, (self, method, values) -> switch (method.getName()) {
            case "getOnlinePlayers" -> actor.online ? List.of(actor.player) : List.of();
            case "getPlayer" -> actor.online && actor.id.equals(values[0]) ? actor.player : null;
            case "getPluginManager" -> manager;
            case "getScheduler" -> scheduler;
            case "getLogger" -> logger;
            case "getName", "getVersion", "getBukkitVersion" -> "StarBridge isolated test";
            default -> defaultValue(method);
        });
        Bukkit.setServer(server);
        actor = new FakePlayer(UUID.randomUUID());
        Plugin plugin = proxy(Plugin.class, (self, method, values) -> switch (method.getName()) {
            case "getLogger" -> logger;
            case "isEnabled" -> true;
            case "getName" -> "StarBridge";
            case "getDataFolder" -> java.nio.file.Files.createTempDirectory("starbridge-game-test").toFile();
            case "getServer" -> server;
            default -> defaultValue(method);
        });
        GameLogin login = new GameLogin(plugin, (route, request) -> {
            if (offline.get()) throw new IllegalStateException("offline");
            JsonObject captured = request.deepCopy(); requests.add(captured);
            if ("password".equals(request.get("action").getAsString())) return passwordAnswer.get(3, TimeUnit.SECONDS);
            return status(request, "pending", "r1");
        });
        try {
            assert !org.spigotmc.SpigotConfig.logCommands : "Native password command echo must be disabled";
            assert login.locked(actor.player) : "Unknown policy cannot allow login";
            login.accept(policy(true, "r1"));
            pump(() -> latest("join") != null && !callbacks.isEmpty());
            assert login.locked(actor.player);
            UUID worldId = UUID.randomUUID();
            World world = proxy(World.class, (self, method, values) -> switch(method.getName()) {
                case "getUID" -> worldId;
                case "getName" -> "TestWorld";
                case "equals" -> self == values[0];
                case "hashCode" -> worldId.hashCode();
                default -> defaultValue(method);
            });
            Location from = new Location(world, 0, 80, 0), to = new Location(world, 1, 80, 0);
            PlayerMoveEvent move = new PlayerMoveEvent(actor.player, from, to); login.onMove(move);
            assert move.getTo().equals(from) : "Pending player movement must be blocked";
            PlayerTeleportEvent teleport = new PlayerTeleportEvent(actor.player, from, to); login.onTeleport(teleport);
            assert teleport.isCancelled();
            AsyncPlayerChatEvent chat = new AsyncPlayerChatEvent(true, actor.player, "Do not relay this", new HashSet<>()); login.onChat(chat);
            assert chat.isCancelled() && chat.getMessage().isEmpty();
            PlayerCommandPreprocessEvent adminCommand = new PlayerCommandPreprocessEvent(actor.player, "/minecraft:op Steve"); login.onCommand(adminCommand);
            assert adminCommand.isCancelled();
            BlockBreakEvent block = new BlockBreakEvent(null, actor.player); login.onBreak(block); assert block.isCancelled();
            EntityDamageEvent damage = new EntityDamageEvent(actor.player, EntityDamageEvent.DamageCause.FALL, null, 10); login.onDamage(damage); assert damage.isCancelled();
            int before = actor.messages.size();
            login.accept(policy(true, "r1", status(latest("join"), "pending", "r1")));
            login.accept(policy(true, "r1", status(latest("join"), "pending", "r1")));
            assert actor.messages.size() == before : "Heartbeats must not repeat login prompts";
            passwordAnswer = new CompletableFuture<>();
            PlayerCommandPreprocessEvent password = new PlayerCommandPreprocessEvent(actor.player, "/starbridge:l Example Password 123"); login.onCommand(password);
            assert password.isCancelled() && password.getMessage().equals("/starbridge:login");
            pump(() -> latest("password") != null);
            JsonObject oldPasswordRequest = latest("password");
            FakePlayer oldActor = actor;
            login.onQuit(new PlayerQuitEvent(oldActor.player, ""));
            actor = new FakePlayer(oldActor.id); login.onJoin(new PlayerJoinEvent(actor.player, ""));
            String freshNonce = login.nonce(actor.player);
            assert !freshNonce.equals(oldPasswordRequest.get("nonce").getAsString());
            passwordAnswer.complete(status(oldPasswordRequest, "authenticated", "r1"));
            pump(() -> latest("join") != null && freshNonce.equals(latest("join").get("nonce").getAsString()) && !callbacks.isEmpty());
            assert login.locked(actor.player) : "Old password callbacks cannot authorize a reconnected player";
            pump(() -> actor.messages.stream().anyMatch(text -> text.startsWith("请登录：")));
            PlayerCommandPreprocessEvent qqAlias = new PlayerCommandPreprocessEvent(actor.player, "/ql"); login.onCommand(qqAlias);
            assert qqAlias.isCancelled() && qqAlias.getMessage().equals("/starbridge:qqlogin");
            pump(() -> latest("qq") != null);
            assert freshNonce.equals(latest("qq").get("nonce").getAsString()) && login.locked(actor.player);
            JsonObject freshRequest = latest("join");
            login.accept(policy(true, "r1", status(freshRequest, "authenticated", "r1")));
            assert !login.locked(actor.player) : "Matching QQ/password confirmation releases this connection";
            PlayerMoveEvent freeMove = new PlayerMoveEvent(actor.player, from, to); login.onMove(freeMove); assert freeMove.getTo().equals(to);
            login.accept(policy(true, "r1", status(freshRequest, "missing", "r1")));
            assert login.locked(actor.player);
            assert !freshNonce.equals(login.nonce(actor.player));
            login.accept(policy(true, "r1", status(freshRequest, "authenticated", "r1")));
            assert login.locked(actor.player) : "A backend restart fences old nonce results";
            login.accept(policy(false, "r2")); assert !login.locked(actor.player);
            login.accept(policy(true, "r3")); assert login.locked(actor.player);
            installedAuthMe = plugin; authMe = true;
            login.accept(policy(true, "r4"));
            var api = fr.xephi.authme.api.v3.AuthMeApi.INSTANCE;
            JsonObject current = snapshotFor(login, actor);
            login.accept(policy(true, "r4", status(current, "authenticated", "r4")));
            assert login.locked(actor.player) : "A requested AuthMe login is not a completed login";
            assert api.registrations == 1;
            login.accept(policy(true, "r4", status(current, "authenticated", "r4")));
            assert api.registrations == 1 : "Heartbeat cannot repeat account creation";
            api.registered = true; api.authenticated = true; timers.forEach(Runnable::run);
            assert !login.locked(actor.player);
            PlayerCommandPreprocessEvent logout = new PlayerCommandPreprocessEvent(actor.player, "/logout"); login.onCommand(logout);
            assert logout.isCancelled() && login.locked(actor.player) && api.logouts == 1;
            current = snapshotFor(login, actor);
            login.accept(policy(true, "r4", status(current, "authenticated", "r4")));
            assert api.logins == 1 && api.registrations == 1 && login.locked(actor.player);
            api.authenticated = true; timers.forEach(Runnable::run); assert !login.locked(actor.player);
            api.authenticated = false; timers.forEach(Runnable::run); assert login.locked(actor.player);
            login.onQuit(new PlayerQuitEvent(actor.player, ""));
            actor = new FakePlayer(UUID.randomUUID()); login.onJoin(new PlayerJoinEvent(actor.player, ""));
            current = snapshotFor(login, actor);
            login.accept(policy(true, "r4", status(current, "authenticated", "r4")));
            assert api.logins == 1 && login.locked(actor.player) : "An unlinked existing AuthMe account needs its own proof";
            PlayerCommandPreprocessEvent originalLogin = new PlayerCommandPreprocessEvent(actor.player, "/authme:login Original AuthMe Password");
            originalLogin.setCancelled(true); login.onCommand(originalLogin); assert !originalLogin.isCancelled();
            api.authenticated = true; timers.forEach(Runnable::run); assert !login.locked(actor.player);
            JsonObject invalid = policy(true, "r5"); invalid.getAsJsonObject("authentication").addProperty("login_engine", "builtin");
            login.accept(invalid); assert !actor.kicked.isEmpty();
            login.onQuit(new PlayerQuitEvent(actor.player, ""));
            actor = new FakePlayer(UUID.randomUUID()); login.onJoin(new PlayerJoinEvent(actor.player, "")); authMe = false;
            JsonObject absent = policy(true, "r6"); absent.getAsJsonObject("authentication").addProperty("login_engine", "authme");
            login.accept(absent); assert !actor.kicked.isEmpty() : "An explicit AuthMe policy cannot fall back without AuthMe";
            System.out.println("Game login checks passed: pending event gate, command masking, native log protection, silent heartbeat, reconnect fencing, backend restart, policy changes; optional AuthMe API, asynchronous registration/login, logout, conflict denial.");
        } finally {
            login.close();
            assert org.spigotmc.SpigotConfig.logCommands : "Native logging restores its previous value when unloaded";
        }
    }
}
