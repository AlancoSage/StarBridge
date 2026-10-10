package cn.starbridge;
import com.lenis0012.bukkit.loginsecurity.*;
import com.lenis0012.bukkit.loginsecurity.session.*;
import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.logging.Logger;
import org.bukkit.*;
import org.bukkit.entity.Player;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.plugin.*;

public final class LoginSecurityLinkCheck {
    private static int count;
    private static boolean enabled = true;
    private static final Map<UUID, Player> live = new HashMap<>();
    private static Object fallback(Method method) {
        if (method.getReturnType() == boolean.class) return false;
        if (method.getReturnType() == int.class) return 0;
        if (method.getReturnType() == long.class) return 0L;
        return null;
    }
    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, handler));
    }
    private static Player player(UUID id, String name) {
        Player p = proxy(Player.class, (self, method, args) -> {
            switch (method.getName()) {
                case "getUniqueId": return id;
                case "getName": return name;
                case "isOnline": return live.get(id) == self;
                case "kickPlayer": live.remove(id, self); return null;
                case "equals": return self == args[0];
                case "hashCode": return System.identityHashCode(self);
                default: return fallback(method);
            }
        });
        live.put(id, p); return p;
    }
    private static void check(boolean result, String reason) { if (!result) throw new AssertionError(reason); count++; }
    private interface Test { void run() throws Exception; }
    private static void fails(Test test, String reason) throws Exception {
        try { test.run(); throw new AssertionError(reason); } catch (IOException expected) { count++; }
    }
    public static void main(String[] args) throws Exception {
        PluginManager manager = proxy(PluginManager.class, (self, method, values) -> fallback(method));
        Server server = proxy(Server.class, (self, method, values) -> {
            switch (method.getName()) {
                case "getPlayer": return live.get(values[0]);
                case "getPluginManager": return manager;
                case "getLogger": return Logger.getLogger("LoginSecurity-fixture");
                case "getName": case "getVersion": case "getBukkitVersion": return "LoginSecurity isolated test";
                default: return fallback(method);
            }
        });
        Bukkit.setServer(server);
        Path folder = Files.createTempDirectory("starbridge-loginsecurity-check");
        LoginSecurity plugin = proxy(LoginSecurity.class, (self, method, values) -> {
            switch (method.getName()) {
                case "isEnabled": return enabled;
                case "getServer": return server;
                case "getDataFolder": return folder.toFile();
                default: return fallback(method);
            }
        });
        LoginSecurityLink link = new LoginSecurityLink(plugin, plugin);
        UUID id = UUID.randomUUID(); Player fresh = player(id, "Fresh");
        PlayerSession session = new PlayerSession(fresh); LoginSecurity.MANAGER.sessions.put(fresh, session);
        check(link.start(fresh) && session.registrations == 1, "New account uses native async registration");
        check(!link.authenticated(fresh), "Pending registration stays locked");
        check(session.password.length() >= 24, "Random internal credential");
        session.registered = true; session.authorized = true;
        session.callbacks.remove().run();
        check(session.logins == 1 && !link.authenticated(fresh), "Registration authorization does not skip restoration");
        session.restored = true; session.callbacks.remove().run();
        check(link.authenticated(fresh) && session.restored, "Native login callback completes gate");
        String file = new String(Files.readAllBytes(folder.resolve("loginsecurity-links.properties")), "UTF-8");
        check(!file.contains(session.password), "Native credentials are never persisted");
        link.onQuit(new PlayerQuitEvent(fresh, "quit")); live.remove(id);
        Player reconnect = player(id, "Fresh"); PlayerSession returned = new PlayerSession(reconnect);
        returned.registered = true; LoginSecurity.MANAGER.sessions.put(reconnect, returned);
        check(link.start(reconnect) && returned.logins == 1 && returned.registrations == 0, "Linked account is not re-registered");
        check(!link.authenticated(reconnect), "Pending linked login is locked");
        returned.authorized = true; returned.callbacks.remove().run();
        check(link.authenticated(reconnect), "Linked native login observed");
        Player old = player(UUID.randomUUID(), "Existing"); PlayerSession original = new PlayerSession(old);
        original.registered = true; LoginSecurity.MANAGER.sessions.put(old, original);
        check(!link.start(old) && original.logins == 0 && original.registrations == 0, "Unknown original password cannot be bypassed");
        fails(() -> link.remember(old), "Unverified original account cannot become trusted");
        original.authorized = true; link.remember(old); original.authorized = false;
        check(link.start(old) && original.logins == 1, "Original native authentication can link account");
        Player replacement = player(BukkitCompatibility.identity(old), "Existing");
        original.authorized = true; original.callbacks.remove().run();
        check(!link.authenticated(old), "Late callback for old connection cannot release new player");
        Player captchaPlayer = player(UUID.randomUUID(), "Captcha");
        LoginSecurity.MANAGER.sessions.put(captchaPlayer, new PlayerSession(captchaPlayer));
        LoginSecurity.CONFIG.captcha = true;
        fails(() -> link.start(captchaPlayer), "Native registration captcha cannot be bypassed");
        LoginSecurity.CONFIG.captcha = false; LoginSecurity.CONFIG.enabled = false;
        fails(() -> link.start(captchaPlayer), "Closed native registrations respected");
        LoginSecurity.CONFIG.enabled = true;
        Player rejected = player(UUID.randomUUID(), "Rejected"); PlayerSession rejection = new PlayerSession(rejected);
        LoginSecurity.MANAGER.sessions.put(rejected, rejection);
        check(link.start(rejected), "Rejected async action submitted");
        rejection.failNext = true; rejection.registered = true; rejection.authorized = true;
        rejection.callbacks.remove().run();
        fails(() -> link.authenticated(rejected), "Rejected native action never releases gate even when mode is authorized");
        UUID lateId = UUID.randomUUID(); Player departing = player(lateId, "Departing");
        PlayerSession pendingCreation = new PlayerSession(departing); LoginSecurity.MANAGER.sessions.put(departing, pendingCreation);
        check(link.start(departing), "Pending creation submitted");
        link.onQuit(new PlayerQuitEvent(departing, "quit")); live.remove(lateId);
        pendingCreation.registered = true; pendingCreation.authorized = true; pendingCreation.callbacks.remove().run();
        check(pendingCreation.logins == 0 && !link.authenticated(departing), "Late creation receipt never releases or logs in departed connection");
        Player later = player(lateId, "Departing"); PlayerSession recovered = new PlayerSession(later);
        recovered.registered = true; LoginSecurity.MANAGER.sessions.put(later, recovered);
        check(link.start(later) && recovered.logins == 1 && recovered.registrations == 0, "Successfully created account remains usable after early disconnect");
        Player changed = player(UUID.randomUUID(), "Fresh"); PlayerSession changedSession = new PlayerSession(changed);
        changedSession.registered = true; LoginSecurity.MANAGER.sessions.put(changed, changedSession);
        check(!link.start(changed), "Changed UUID invalidates ownership");
        enabled = false; check(!link.authenticated(reconnect), "Disabled provider does not authenticate"); enabled = true;
        link.logout(reconnect); check(!live.containsKey(id), "Logout disconnects the native session");
        check(link.ownershipCommands().contains("loginsecurity:login") && !link.ownershipCommands().contains("loginsecurity:lac"), "Only fixed native login commands allowed");
        VerifiedLoginAccounts previous = new VerifiedLoginAccounts(plugin, "parallel");
        VerifiedLoginAccounts reopened = new VerifiedLoginAccounts(plugin, "parallel");
        Player beforeReload = player(UUID.randomUUID(), "BeforeReload");
        Player afterReload = player(UUID.randomUUID(), "AfterReload");
        reopened.remember(afterReload); previous.remember(beforeReload);
        check(reopened.matches(beforeReload) && previous.matches(afterReload), "Late receipts merge and become visible across reopened adapters");
        java.util.concurrent.ExecutorService writers = java.util.concurrent.Executors.newFixedThreadPool(2);
        List<java.util.concurrent.Future<?>> writes = new ArrayList<>();
        List<Player> simultaneous = new ArrayList<>();
        try {
            for (int i = 0; i < 20; i++) {
                final Player concurrent = player(UUID.randomUUID(), "Concurrent" + i); simultaneous.add(concurrent);
                final VerifiedLoginAccounts records = i % 2 == 0 ? previous : reopened;
                writes.add(writers.submit(() -> { try { records.remember(concurrent); } catch (IOException ex) { throw new RuntimeException(ex); } }));
            }
            for (java.util.concurrent.Future<?> write : writes) write.get(10, java.util.concurrent.TimeUnit.SECONDS);
        } finally { writers.shutdownNow(); }
        VerifiedLoginAccounts restored = new VerifiedLoginAccounts(plugin, "parallel");
        check(restored.matches(beforeReload) && restored.matches(afterReload), "Reopened ownership file preserves both adapter generations");
        for (Player concurrent : simultaneous) check(restored.matches(concurrent), "Simultaneous receipts survive atomic persistence");
        Properties stored = new Properties();
        try (Reader reader = Files.newBufferedReader(folder.resolve("parallel-links.properties"))) { stored.load(reader); }
        check(stored.size() == 22 && !Files.exists(folder.resolve("parallel-links.properties.tmp")), "Concurrent records leave a complete atomic ownership file");
        System.out.println("LoginSecurity adapter checks passed: " + count);
    }
}
