package cn.starbridge;

import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.BooleanSupplier;
import java.util.logging.Logger;
import org.bukkit.Bukkit;
import org.bukkit.Server;
import org.bukkit.entity.Player;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.server.PluginDisableEvent;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.PluginManager;
import xyz.kyngs.librelogin.api.LibreLoginPlugin;
import xyz.kyngs.librelogin.api.PlatformHandle;
import xyz.kyngs.librelogin.api.authorization.AuthorizationProvider;
import xyz.kyngs.librelogin.api.database.ReadDatabaseProvider;
import xyz.kyngs.librelogin.api.database.User;
import xyz.kyngs.librelogin.api.event.events.AuthenticatedEvent.AuthenticationReason;
import xyz.kyngs.librelogin.api.provider.LibreLoginProvider;

/** Exercises account ownership, asynchronous I/O and old-connection fencing against public API mocks. */
public final class LibreLoginLinkCheck {
    private static final Thread main = Thread.currentThread();
    private static final UUID identity = UUID.randomUUID();
    private static final AtomicInteger authorizations = new AtomicInteger();
    private static final AtomicInteger databaseReads = new AtomicInteger();
    private static final Map<Player, Boolean> authorized = Collections.synchronizedMap(new IdentityHashMap<>());
    private static final Map<Player, Boolean> twoFactor = Collections.synchronizedMap(new IdentityHashMap<>());
    private static volatile boolean ownerEnabled = true;
    private static volatile boolean nativeEnabled = true;
    private static volatile boolean proxyMode;
    private static volatile String platform = "paper";
    private static volatile boolean hasTotpProvider = true;
    private static volatile FakePlayer current;
    private static volatile User user;
    private static volatile User namedUser;
    private static volatile RuntimeException databaseFailure;
    private static volatile CountDownLatch entered;
    private static volatile CountDownLatch release;
    private static Server server;
    private static Plugin owner;
    private static Plugin installed;
    private static Path data;
    private static int checks;

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

    private static Object common(Object self, Method method, Object[] args, String name) {
        return switch (method.getName()) {
            case "getName" -> name;
            case "getServer" -> server;
            case "getDataFolder" -> data.toFile();
            case "getLogger" -> Logger.getLogger("LibreLogin-test");
            case "hashCode" -> System.identityHashCode(self);
            case "equals" -> self == args[0];
            case "toString" -> name;
            default -> defaultValue(method);
        };
    }

    private static final class FakePlayer {
        final Player player;
        final UUID uuid;
        volatile boolean online = true;
        String kicked = "";
        FakePlayer(UUID uuid) {
            this.uuid = uuid;
            player = proxy(Player.class, (self, method, args) -> switch (method.getName()) {
                case "getName" -> "Steve";
                case "getUniqueId" -> uuid;
                case "isOnline" -> online;
                case "kickPlayer" -> { kicked = (String) args[0]; online = false; yield null; }
                default -> common(self, method, args, "TestPlayer");
            });
        }
    }

    private static User user(UUID uuid, String name, boolean registered, String secret) {
        return new User() {
            public UUID getUuid() { return uuid; }
            public String getLastNickname() { return name; }
            public boolean isRegistered() { return registered; }
            public String getSecret() { return secret; }
        };
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
        checks++;
    }

    private static void waitFor(BooleanSupplier condition) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
        while (!condition.getAsBoolean()) {
            if (System.nanoTime() > deadline) throw new AssertionError("Timed out waiting for public API worker");
            Thread.sleep(5);
        }
    }

    private static void finished(LibreLoginLink link) throws Exception {
        Field attempts = LibreLoginLink.class.getDeclaredField("attempts"); attempts.setAccessible(true);
        waitFor(() -> {
            try {
                Object attempt = ((Map<?, ?>) attempts.get(link)).get(current.uuid);
                if (attempt == null) return true;
                Field completed = attempt.getClass().getDeclaredField("finished"); completed.setAccessible(true);
                return completed.getBoolean(attempt);
            } catch (Exception exception) { throw new AssertionError(exception); }
        });
    }

    private static LibreLoginLink link() throws Exception {
        return new LibreLoginLink(installed, owner);
    }

    private static void nativeReady(LibreLoginLink link) throws Exception {
        waitFor(() -> {
            try { return link.authenticated(current.player); }
            catch (Exception failure) { throw new AssertionError(failure); }
        });
    }

    private static void nativeRefused(LibreLoginLink link) throws Exception {
        check(!link.authenticated(current.player), "Native authorized state cannot open gate while identity audit is pending");
        waitFor(() -> {
            try { link.authenticated(current.player); return false; }
            catch (IOException expected) { return true; }
            catch (Exception failure) { throw new AssertionError(failure); }
        });
    }

    private static void blockDatabase() {
        entered = new CountDownLatch(1); release = new CountDownLatch(1);
    }

    private static void releaseDatabase() { release.countDown(); }

    private static void stop(LibreLoginLink link) { link.onDisable(new PluginDisableEvent(owner)); }

    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        data = Files.createTempDirectory(Path.of(".tools/login-adapters"), "libre-proof-check-");
        PluginManager manager = proxy(PluginManager.class, (self, method, values) -> defaultValue(method));
        server = proxy(Server.class, (self, method, values) -> switch (method.getName()) {
            case "getPluginManager" -> manager;
            case "getLogger" -> Logger.getLogger("LibreLogin-test");
            case "getName" -> "Paper";
            case "getVersion", "getBukkitVersion" -> "test";
            default -> defaultValue(method);
        });
        Bukkit.setServer(server);
        owner = proxy(Plugin.class, (self, method, values) -> method.getName().equals("isEnabled")
            ? ownerEnabled : common(self, method, values, "StarBridge"));
        AuthorizationProvider<Player> authorization = new AuthorizationProvider<>() {
            public boolean isAuthorized(Player player) { return authorized.getOrDefault(player, false); }
            public boolean isAwaiting2FA(Player player) { return twoFactor.getOrDefault(player, false); }
            public void authorize(User account, Player player, AuthenticationReason reason) {
                if (Thread.currentThread() == main) throw new AssertionError("Native authorization performs I/O on main thread");
                if (account.getSecret() != null || isAwaiting2FA(player)) throw new AssertionError("TOTP bypass");
                if (current.player != player) throw new AssertionError("Stale connection was authorized");
                authorizations.incrementAndGet(); authorized.put(player, true);
            }
        };
        ReadDatabaseProvider database = new ReadDatabaseProvider() {
            public User getByUUID(UUID uuid) {
                if (Thread.currentThread() == main) throw new AssertionError("Database read on main thread");
                databaseReads.incrementAndGet();
                CountDownLatch block = release;
                if (block != null) {
                    entered.countDown();
                    try { block.await(3, TimeUnit.SECONDS); }
                    catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
                }
                if (databaseFailure != null) throw databaseFailure;
                return user;
            }
            public User getByName(String name) { return namedUser == null ? user : namedUser; }
        };
        PlatformHandle<Player, Object> handle = new PlatformHandle<>() {
            public String getPlatformIdentifier() { return platform; }
            public Class<Player> getPlayerClass() { return Player.class; }
        };
        LibreLoginPlugin<Player, Object> api = new LibreLoginPlugin<>() {
            public AuthorizationProvider<Player> getAuthorizationProvider() { return authorization; }
            public ReadDatabaseProvider getDatabaseProvider() { return database; }
            public PlatformHandle<Player, Object> getPlatformHandle() { return handle; }
            public boolean multiProxyEnabled() { return proxyMode; }
            public Player getPlayerForUUID(UUID uuid) { return current != null && current.online && current.uuid.equals(uuid) ? current.player : null; }
            public Object getTOTPProvider() { return hasTotpProvider ? Boolean.TRUE : null; }
        };
        installed = (Plugin) Proxy.newProxyInstance(Plugin.class.getClassLoader(), new Class<?>[]{Plugin.class, LibreLoginProvider.class},
            (self, method, values) -> switch (method.getName()) {
                case "getLibreLogin" -> api;
                case "isEnabled" -> nativeEnabled;
                default -> common(self, method, values, "LibreLogin");
            });
        current = new FakePlayer(identity); user = user(identity, "Steve", true, null);
        LibreLoginLink link = link();
        check(link.ownershipCommands().stream().allMatch(command -> command.startsWith("librelogin:")), "Only native namespaced commands allowed");
        check(!link.start(current.player) && authorizations.get() == 0 && databaseReads.get() == 0, "Unverified existing user requires native proof");
        try { link.remember(current.player); throw new AssertionError("Unauthenticated ownership proof accepted"); }
        catch (IOException expected) { check(true, "Unauthenticated proof denied"); }
        authorized.put(current.player, true);
        nativeReady(link);
        check(link.authenticated(current.player), "Native proof recognized");
        link.remember(current.player);
        check(Files.readString(data.resolve("librelogin-links.properties")).contains(identity.toString()), "Only verified identity persisted");
        authorized.put(current.player, false);
        blockDatabase();
        check(link.start(current.player), "Trusted external proof requests asynchronous login");
        check(entered.await(3, TimeUnit.SECONDS) && !link.authenticated(current.player), "Pending database I/O does not open gate");
        releaseDatabase(); finished(link); release = null;
        nativeReady(link);
        check(link.authenticated(current.player) && authorizations.get() == 1, "Trusted no-TOTP user authorized on worker");
        stop(link);

        authorized.put(current.player, false); user = user(identity, "Steve", true, "totp-secret"); link = link();
        link.start(current.player); finished(link);
        check(!link.start(current.player) && !link.authenticated(current.player) && authorizations.get() == 1, "Stored TOTP secret always requires native proof");
        authorized.put(current.player, true); twoFactor.put(current.player, true);
        check(!link.authenticated(current.player), "Incomplete native two-factor proof cannot finish");
        twoFactor.put(current.player, false);
        nativeReady(link);
        check(link.authenticated(current.player), "Completed native TOTP proof accepted"); stop(link);

        authorized.put(current.player, false); user = user(identity, "Steve", true, null); twoFactor.put(current.player, true); link = link();
        link.start(current.player); finished(link);
        check(!link.start(current.player) && authorizations.get() == 1, "Two-factor enrollment is never bypassed"); stop(link); twoFactor.put(current.player, false);

        namedUser = user(UUID.randomUUID(), "Steve", true, null); link = link(); link.start(current.player); finished(link);
        check(!link.start(current.player) && authorizations.get() == 1, "Database name and UUID must identify same user"); stop(link); namedUser = null;
        user = user(identity, "steve", true, null); link = link(); link.start(current.player); finished(link);
        check(!link.start(current.player) && authorizations.get() == 1, "Native canonical nickname is respected"); stop(link);
        user = user(identity, "Steve", false, null); link = link(); link.start(current.player); finished(link);
        check(!link.start(current.player) && authorizations.get() == 1, "Unregistered native record is never overwritten"); stop(link);

        user = user(identity, "Steve", true, null); blockDatabase(); link = link(); FakePlayer old = current;
        link.start(old.player); check(entered.await(3, TimeUnit.SECONDS), "Stale test worker entered database");
        current = new FakePlayer(identity); old.online = false; link.onQuit(new PlayerQuitEvent(old.player, ""));
        releaseDatabase(); release = null; Thread.sleep(40);
        check(authorizations.get() == 1 && !link.authenticated(current.player), "Quit invalidates old async connection without authorizing replacement");
        link.start(current.player); finished(link); link.onQuit(new PlayerQuitEvent(old.player, ""));
        nativeReady(link);
        check(link.authenticated(current.player) && authorizations.get() == 2, "Late old quit cannot invalidate current connection"); stop(link);

        authorized.put(current.player, false); blockDatabase(); link = link(); old = current;
        link.start(old.player); check(entered.await(3, TimeUnit.SECONDS), "Live lookup test entered database"); current = new FakePlayer(identity);
        releaseDatabase(); release = null; Thread.sleep(40);
        check(authorizations.get() == 2, "Native current-player identity alone fences old callbacks"); stop(link);

        blockDatabase(); link = link(); link.start(current.player); check(entered.await(3, TimeUnit.SECONDS), "Disable test entered database");
        ownerEnabled = false; stop(link); releaseDatabase(); release = null; Thread.sleep(40);
        check(authorizations.get() == 2 && !link.authenticated(current.player), "Owner disable invalidates pending work"); ownerEnabled = true;

        link = link(); databaseFailure = new IllegalStateException("Database offline"); link.start(current.player); finished(link);
        try { link.authenticated(current.player); throw new AssertionError("Database failure opened gate"); }
        catch (IOException expected) { check(!expected.getMessage().contains("Database offline"), "Failure closes gate without leaking upstream payloads"); }
        stop(link); databaseFailure = null;

        hasTotpProvider = false; user = user(identity, "Steve", true, "migrated-secret");
        authorized.put(current.player, true); link = link();
        check(!link.authenticated(current.player), "Previously authorized native state waits for identity and two-factor audit");
        final LibreLoginLink unavailableTotp = link;
        waitFor(() -> {
            try { unavailableTotp.authenticated(current.player); return false; }
            catch (IOException expected) { return expected.getMessage().contains("两步验证"); }
            catch (Exception failure) { throw new AssertionError(failure); }
        });
        check(true, "Native authorized flag with secret and missing TOTP provider cannot downgrade authentication");
        try { link.remember(current.player); throw new AssertionError("Downgraded native account remembered"); }
        catch (IOException expected) { check(true, "Downgraded native proof cannot persist ownership"); }
        stop(link); hasTotpProvider = true; user = user(identity, "Steve", true, null);

        user = user(UUID.randomUUID(), "Steve", true, null); link = link(); nativeRefused(link);
        check(true, "Already native-authorized UUID mismatch is denied"); stop(link);
        user = user(identity, "Steve", false, null); link = link(); nativeRefused(link);
        check(true, "Already native-authorized unregistered profile is denied"); stop(link);
        user = user(identity, "Steve", true, null);

        link = link(); link.logout(current.player);
        check(!current.online && current.kicked.contains("LibreLogin"), "Logout disconnects safely without private-state mutation"); stop(link);
        current = new FakePlayer(UUID.randomUUID()); link = link();
        check(!link.start(current.player), "UUID changes require fresh native proof"); stop(link);

        proxyMode = true;
        try { link(); throw new AssertionError("Proxy API accepted"); }
        catch (IOException expected) { check(true, "Proxy mode rejected"); } proxyMode = false;
        platform = "velocity";
        try { link(); throw new AssertionError("Proxy platform accepted"); }
        catch (IOException expected) { check(true, "Non-Paper native platform rejected"); } platform = "paper";
        nativeEnabled = false;
        try { link(); throw new AssertionError("Disabled plugin accepted"); }
        catch (IOException expected) { check(true, "Disabled native plugin rejected"); } nativeEnabled = true;
        System.out.println("LibreLogin public API checks passed: " + checks);
    }
}
