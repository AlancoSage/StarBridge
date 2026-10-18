package cn.starbridge;

import com.google.gson.*;
import io.papermc.paper.threadedregions.scheduler.*;
import org.bukkit.*;
import org.bukkit.entity.Player;
import org.bukkit.event.player.*;
import org.bukkit.plugin.*;

import java.lang.reflect.*;
import java.net.InetSocketAddress;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.*;
import java.util.logging.Logger;

/** Runs production login handlers with two separately owned region queues. */
public final class GameLoginFoliaCheck {
    private static final ThreadLocal<FakePlayer> owner = new ThreadLocal<>();
    private static final List<FakePlayer> players = new CopyOnWriteArrayList<>();
    private static final List<Runnable> timers = new CopyOnWriteArrayList<>();
    private static final Queue<Runnable> globals = new ConcurrentLinkedQueue<>();
    private static final List<JsonObject> requests = new CopyOnWriteArrayList<>();
    private static final Logger logger = Logger.getLogger("VexBot-Folia-login-test");
    private static final AtomicInteger queued = new AtomicInteger(), checks = new AtomicInteger(), authMeAccess = new AtomicInteger();
    private static volatile boolean enabled = true;
    private static Plugin authMe;
    private static final Map<String, Plugin> otherLoginPlugins = new HashMap<>();
    private static volatile CompletableFuture<JsonObject> passwordAnswer;

    @SuppressWarnings("unchecked")
    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return (T) Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, handler);
    }
    private static Object fallback(Method method) {
        if (method.getReturnType() == boolean.class) return false;
        if (method.getReturnType() == int.class) return 0;
        if (method.getReturnType() == long.class) return 0L;
        return null;
    }
    private static void check(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
        checks.incrementAndGet();
    }
    private static ScheduledTask task() {
        return proxy(ScheduledTask.class, (self, method, args) -> ScheduledTask.CancelledState.CANCELLED_BY_CALLER);
    }
    private static final class FakePlayer {
        final UUID id;
        final String name;
        final Queue<Runnable> region = new ConcurrentLinkedQueue<>();
        final Queue<Runnable> retirements = new ConcurrentLinkedQueue<>();
        final List<String> messages = new CopyOnWriteArrayList<>();
        final Player player;
        volatile boolean online = true;
        volatile String kicked = "";
        volatile CountDownLatch beginStarted, resumeBegin;
        FakePlayer(UUID id, String name) {
            this.id = id; this.name = name;
            EntityScheduler scheduler = proxy(EntityScheduler.class, (self, method, args) -> {
                if (!online) return null;
                ScheduledTask scheduled = task();
                @SuppressWarnings("unchecked") Consumer<ScheduledTask> callback = (Consumer<ScheduledTask>) args[1];
                region.add(() -> callback.accept(scheduled)); retirements.add((Runnable) args[2]); queued.incrementAndGet();
                return scheduled;
            });
            player = proxy(Player.class, (self, method, args) -> {
                switch (method.getName()) {
                    case "getScheduler": return scheduler;
                    case "getUniqueId": return id;
                    case "hashCode": return System.identityHashCode(self);
                    case "equals": return self == args[0];
                    case "toString": return name;
                    case "getServer": return Bukkit.getServer();
                    case "getName":
                        requireOwner();
                        if (beginStarted != null) {
                            beginStarted.countDown();
                            try { if (!resumeBegin.await(5, TimeUnit.SECONDS)) throw new AssertionError("Shutdown race barrier timeout"); }
                            catch (InterruptedException ex) { throw new AssertionError(ex); }
                        }
                        return name;
                    case "getAddress": requireOwner(); return new InetSocketAddress("127.0.0.1", 25565);
                    case "isOnline": requireOwner(); return online;
                    case "sendMessage": requireOwner(); messages.add((String) args[0]); return null;
                    case "kickPlayer": requireOwner(); kicked = (String) args[0]; online = false; return null;
                    default: return fallback(method);
                }
            });
        }
        void requireOwner() {
            if (owner.get() != this) throw new AssertionError("Player access outside owning region: " + name);
        }
        void inRegion(Runnable action) {
            owner.set(this);
            try { action.run(); }
            finally { owner.remove(); }
        }
        void drain() {
            inRegion(() -> { Runnable next; while ((next = region.poll()) != null) next.run(); });
        }
    }
    private static void drain() {
        Runnable global; while ((global = globals.poll()) != null) global.run();
        for (FakePlayer player : players) player.drain();
    }
    private static void pump(BooleanSupplier ready) throws Exception {
        long until = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (!ready.getAsBoolean()) {
            drain();
            if (System.nanoTime() > until) throw new AssertionError("Folia login callback timeout");
            Thread.sleep(5);
        }
        drain();
    }
    private static JsonObject result(JsonObject request, String status, String revision) {
        JsonObject value = new JsonObject();
        value.add("uuid", request.get("uuid")); value.add("nonce", request.get("nonce"));
        value.addProperty("status", status); value.addProperty("revision", revision);
        value.addProperty("expires_in", 120); value.addProperty("message", "test status");
        return value;
    }
    private static JsonObject policy(boolean required, String revision, JsonObject... results) {
        JsonObject response = new JsonObject(), value = new JsonObject();
        value.addProperty("required", required); value.addProperty("available", true);
        value.addProperty("password_login", true); value.addProperty("qq_login", true);
        value.addProperty("login_seconds", 120); value.addProperty("revision", revision);
        response.add("authentication", value);
        JsonArray array = new JsonArray(); for (JsonObject result : results) array.add(result);
        response.add("authentication_results", array); return response;
    }
    private static JsonObject heartbeat(GameLogin login, FakePlayer player) {
        for (JsonElement element : login.snapshot()) {
            JsonObject record = element.getAsJsonObject();
            if (player.id.toString().equals(record.get("uuid").getAsString())) return record;
        }
        throw new AssertionError("Missing heartbeat for " + player.name);
    }
    private static JsonObject latest(String action, FakePlayer player) {
        for (int index = requests.size() - 1; index >= 0; index--) {
            JsonObject value = requests.get(index);
            if (action.equals(value.get("action").getAsString()) && player.id.toString().equals(value.get("uuid").getAsString())) return value;
        }
        return null;
    }
    private static void expire(GameLogin login, FakePlayer player) throws Exception {
        Field registry = GameLogin.class.getDeclaredField("connections"); registry.setAccessible(true);
        Object connection = ((Map<?, ?>) registry.get(login)).get(player.id);
        Field deadline = connection.getClass().getDeclaredField("deadline"); deadline.setAccessible(true);
        player.inRegion(() -> { try { deadline.setLong(connection, 0); } catch (IllegalAccessException ex) { throw new AssertionError(ex); } });
    }
    public static void main(String[] args) throws Exception {
        check(BridgeScheduler.isFolia(), "Folia marker must select entity scheduling");
        Bukkit.global = proxy(GlobalRegionScheduler.class, (self, method, values) -> {
            if (method.getName().equals("cancelTasks")) return null;
            ScheduledTask task = task();
            @SuppressWarnings("unchecked") Consumer<ScheduledTask> action = (Consumer<ScheduledTask>) values[1];
            if (method.getName().equals("runAtFixedRate")) timers.add(() -> action.accept(task));
            else globals.add(() -> action.accept(task));
            return task;
        });
        PluginManager manager = proxy(PluginManager.class, (self, method, values) -> switch (method.getName()) {
            case "getPlugin" -> "AuthMe".equals(values[0]) ? authMe : otherLoginPlugins.get(values[0]);
            case "isPluginEnabled" -> "AuthMe".equals(values[0]) ? authMe != null : otherLoginPlugins.containsKey(values[0]);
            default -> fallback(method);
        });
        Server server = proxy(Server.class, (self, method, values) -> switch (method.getName()) {
            case "getOnlinePlayers" -> players.stream().filter(player -> player.online).map(player -> player.player).toList();
            case "getPluginManager" -> manager;
            case "getLogger" -> logger;
            default -> fallback(method);
        });
        Bukkit.setServer(server);
        Plugin plugin = proxy(Plugin.class, (self, method, values) -> switch (method.getName()) {
            case "isEnabled" -> enabled;
            case "getLogger" -> logger;
            case "getServer" -> server;
            case "getName" -> "StarBridge";
            case "hashCode" -> System.identityHashCode(self);
            case "equals" -> self == values[0];
            default -> fallback(method);
        });
        FakePlayer first = new FakePlayer(UUID.randomUUID(), "First"), second = new FakePlayer(UUID.randomUUID(), "Second");
        players.add(first); players.add(second);
        GameLogin login = new GameLogin(plugin, (route, data) -> {
            requests.add(data.deepCopy());
            if ("password".equals(data.get("action").getAsString())) return passwordAnswer.get(5, TimeUnit.SECONDS);
            return result(data, "pending", "r1");
        });
        try {
            check(first.messages.isEmpty() && second.messages.isEmpty(), "Constructor must defer all player access");
            drain(); login.accept(policy(true, "r1"));
            // Capturing a request precedes scheduling its response. An empty
            // region queue cannot establish that the join has completed.
            pump(() -> first.messages.stream().anyMatch(text -> text.startsWith("请登录："))
                && second.messages.stream().anyMatch(text -> text.startsWith("请登录：")));
            check(login.snapshot().size() == 2, "Global heartbeat must use captured identities, with no live player lookup");
            check(login.locked(first.player) && login.locked(second.player), "Both region gates start closed");
            int beforeTimers = queued.get();
            timers.forEach(Runnable::run); timers.forEach(Runnable::run); timers.forEach(Runnable::run);
            check(queued.get() - beforeTimers == 2, "A delayed region must retain at most one pending timeout check per connection");
            drain(); timers.forEach(Runnable::run);
            check(queued.get() - beforeTimers == 4, "Completing a timeout check must permit the next timer check"); drain();
            passwordAnswer = new CompletableFuture<>();
            CyclicBarrier together = new CyclicBarrier(2);
            ExecutorService regions = Executors.newFixedThreadPool(2);
            try {
                Future<?> passwordRegion = regions.submit(() -> first.inRegion(() -> {
                    try { together.await(5, TimeUnit.SECONDS); } catch (Exception ex) { throw new AssertionError(ex); }
                    PlayerCommandPreprocessEvent event = new PlayerCommandPreprocessEvent(first.player, "/l Example Password 123");
                    login.onCommand(event);
                    check(event.isCancelled() && "/starbridge:login".equals(event.getMessage()), "Password alias must mask its command");
                }));
                Future<?> qqRegion = regions.submit(() -> second.inRegion(() -> {
                    try { together.await(5, TimeUnit.SECONDS); } catch (Exception ex) { throw new AssertionError(ex); }
                    PlayerCommandPreprocessEvent event = new PlayerCommandPreprocessEvent(second.player, "/ql");
                    login.onCommand(event);
                    check(event.isCancelled() && "/starbridge:qqlogin".equals(event.getMessage()), "Parallel QQ command must remain in its own region");
                }));
                passwordRegion.get(5, TimeUnit.SECONDS); qqRegion.get(5, TimeUnit.SECONDS);
            } finally { regions.shutdownNow(); }
            pump(() -> latest("password", first) != null && latest("qq", second) != null);
            JsonObject password = latest("password", first);
            check("Example Password 123".equals(password.get("password").getAsString()), "Password spaces must survive transport");
            passwordAnswer.complete(result(password, "authenticated", "r1"));
            long until = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (first.region.isEmpty()) { if (System.nanoTime() > until) throw new AssertionError("Missing entity callback"); Thread.sleep(5); }
            check(login.locked(first.player), "HTTP worker cannot release the gate before its entity callback");
            first.drain();
            check(!login.locked(first.player) && login.locked(second.player), "A proof releases only its own region");
            login.accept(policy(true, "r1", result(heartbeat(login, second), "authenticated", "r1")));
            check(login.locked(second.player), "Global QQ result must defer player state changes");
            second.drain(); check(!login.locked(second.player), "QQ result applies on the owning region");
            String oldNonce = heartbeat(login, first).get("nonce").getAsString();
            login.accept(policy(true, "r2"));
            check(login.locked(first.player) && login.locked(second.player), "Policy revision must close every region gate immediately");
            drain();
            check(!oldNonce.equals(heartbeat(login, first).get("nonce").getAsString()), "Policy change must replace the connection nonce");
            login.accept(policy(true, "r2", result(password, "authenticated", "r1"))); drain();
            check(login.locked(first.player), "Old revision and nonce cannot release a region after policy change");
            JsonObject beforeRestart = heartbeat(login, first);
            login.accept(policy(true, "r2", result(beforeRestart, "missing", "r2"))); drain();
            check(!beforeRestart.get("nonce").getAsString().equals(heartbeat(login, first).get("nonce").getAsString()), "Backend restart must fence delayed callbacks");
            FakePlayer replacement = new FakePlayer(first.id, "First"); players.add(replacement);
            replacement.inRegion(() -> login.onJoin(new PlayerJoinEvent(replacement.player, "")));
            first.inRegion(() -> login.onQuit(new PlayerQuitEvent(first.player, "")));
            first.online = false;
            check(heartbeat(login, replacement).get("nonce").getAsString().equals(login.nonce(replacement.player)), "Late old quit must not remove a reconnected player");
            Runnable retirement; while ((retirement = first.retirements.poll()) != null) retirement.run();
            check(heartbeat(login, replacement) != null, "Retirement of old tasks must preserve the new connection");
            expire(login, second); timers.forEach(Runnable::run);
            check(second.kicked.isEmpty(), "Global timeout must not kick directly");
            second.drain(); check(!second.kicked.isEmpty(), "Timeout kick must run on its own region");
            second.inRegion(() -> login.onQuit(new PlayerQuitEvent(second.player, "")));
            login.accept(policy(false, "r3"));
            check(!login.locked(replacement.player), "Explicitly disabled authentication must release the gate immediately"); drain();
            authMe = proxy(Plugin.class, (self, method, values) -> {
                if (method.getName().equals("isEnabled")) return true;
                if (method.getName().equals("getDataFolder") || method.getName().equals("getDescription")) { authMeAccess.incrementAndGet(); throw new AssertionError("Unsafe AuthMe API setup on Folia"); }
                return fallback(method);
            });
            login.accept(policy(true, "r4"));
            check(login.locked(replacement.player) && replacement.kicked.isEmpty(), "Unsupported AuthMe must fail closed before an entity-scheduled kick");
            replacement.drain();
            check(!replacement.kicked.isEmpty() && authMeAccess.get() == 0, "Folia must reject AuthMe without invoking its API");
            Plugin unsafeNative = authMe;
            authMe = null;
            for (String nativeName : List.of("nLogin", "LoginSecurity", "LibreLogin")) {
                otherLoginPlugins.put(nativeName, unsafeNative);
                FakePlayer refused = new FakePlayer(UUID.randomUUID(), "Refused"); players.add(refused);
                refused.inRegion(() -> login.onJoin(new PlayerJoinEvent(refused.player, "")));
                login.accept(policy(true, "r4-" + nativeName));
                check(login.locked(refused.player) && refused.kicked.isEmpty(), "Unsupported native API closes the gate before an entity-scheduled kick: " + nativeName);
                refused.drain();
                check(!refused.kicked.isEmpty() && authMeAccess.get() == 0, "Folia must reject external login without invoking player or native APIs: " + nativeName);
                refused.inRegion(() -> login.onQuit(new PlayerQuitEvent(refused.player, "")));
                otherLoginPlugins.clear();
            }
            FakePlayer after = new FakePlayer(UUID.randomUUID(), "After"); players.add(after);
            after.inRegion(() -> login.onJoin(new PlayerJoinEvent(after.player, "")));
            login.accept(policy(true, "r5"));
            FakePlayer racing = new FakePlayer(UUID.randomUUID(), "Racing");
            racing.beginStarted = new CountDownLatch(1); racing.resumeBegin = new CountDownLatch(1);
            ExecutorService joinRegion = Executors.newSingleThreadExecutor();
            int beforeClose;
            try {
                Future<?> joining = joinRegion.submit(() -> racing.inRegion(() -> login.onJoin(new PlayerJoinEvent(racing.player, ""))));
                check(racing.beginStarted.await(5, TimeUnit.SECONDS), "Join must reach the shutdown race barrier");
                beforeClose = queued.get(); enabled = false; login.close();
                racing.resumeBegin.countDown(); joining.get(5, TimeUnit.SECONDS);
            } finally { racing.resumeBegin.countDown(); joinRegion.shutdownNow(); }
            drain(); BridgeScheduler.cancel(plugin);
            check(queued.get() == beforeClose && after.kicked.isEmpty(), "Folia disable cannot schedule player tasks or kick from a global thread");
            check(login.snapshot().size() == 0 && login.nonce(racing.player).isEmpty() && org.spigotmc.SpigotConfig.logCommands,
                "A join racing shutdown cannot repopulate connections, and native command logging restores");
            System.out.println("Folia game login checks passed: " + checks.get() + " (region ownership, password masking/spaces, QQ, immutable heartbeat, immediate policy fencing, nonce/reconnect/retirement, timeout, AuthMe rejection, disabled-plugin shutdown)");
        } finally { login.close(); BridgeScheduler.cancel(plugin); }
    }
}
