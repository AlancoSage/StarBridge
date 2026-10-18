package cn.starbridge.velocity;

import com.google.gson.JsonObject;
import com.sun.net.httpserver.HttpServer;
import com.velocitypowered.api.event.connection.LoginEvent;
import com.velocitypowered.api.event.connection.PreLoginEvent;
import com.velocitypowered.api.event.proxy.ProxyShutdownEvent;
import com.velocitypowered.api.proxy.Player;
import com.velocitypowered.api.proxy.ProxyServer;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.Timestamp;
import java.util.*;
import java.util.concurrent.atomic.*;
import java.util.function.BiFunction;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** Real released model/crypto/DAO classes, with isolated proxy connections and HTTP coordinator. */
public final class SecurityCheck {
    private static final UUID ID = UUID.fromString("b656a994-b8f5-4c40-9e32-b2c1ae6ae83e");
    private static final String NAME = "ProofPlayer";
    private static final String OLD = "Old-Verified-Password1!", NEW = "New-Verified-Password2!";
    private static final Logger LOG = LoggerFactory.getLogger("VexBot-Velocity-Check");
    private static int checks;

    static void check(boolean value, String label) {
        checks++; if (!value) throw new AssertionError(label);
    }
    static Class<?> type(String name) throws Exception { return Class.forName(name); }
    @SuppressWarnings("unchecked")
    static <T> T proxy(Class<T> type, BiFunction<String, Object[], Object> callback) {
        return (T) java.lang.reflect.Proxy.newProxyInstance(SecurityCheck.class.getClassLoader(), new Class<?>[]{type}, (object, method, args) -> {
            if (method.getName().equals("equals")) return object == args[0];
            if (method.getName().equals("hashCode")) return System.identityHashCode(object);
            if (method.getName().equals("toString")) return "isolated-test-proxy";
            Object result = callback.apply(method.getName(), args == null ? new Object[0] : args);
            if (result == null && method.getReturnType() == boolean.class) return false;
            if (result == null && method.getReturnType() == int.class) return 0;
            if (result == null && method.getReturnType() == long.class) return 0L;
            return result;
        });
    }
    static Object get(Object owner, String name) throws Exception {
        Field field = owner.getClass().getDeclaredField(name); field.setAccessible(true); return field.get(owner);
    }
    static void set(Object owner, String name, Object value) throws Exception {
        Field field = owner.getClass().getDeclaredField(name); field.setAccessible(true); field.set(owner, value);
    }
    static Player player(AtomicBoolean active, AtomicBoolean inServer) {
        return proxy(Player.class, (name, args) -> switch (name) {
            case "getUniqueId" -> ID;
            case "getUsername" -> NAME;
            case "isActive" -> active.get();
            case "getRemoteAddress" -> new InetSocketAddress("127.0.0.1", 25565);
            case "getCurrentServer" -> inServer.get() ? Optional.of(new Object()) : Optional.empty();
            default -> null;
        });
    }
    static ProxyServer server(List<Player> online) {
        return proxy(ProxyServer.class, (name, args) -> switch (name) {
            case "getAllPlayers" -> online;
            case "getPlayer" -> online.stream().filter(player -> args[0] instanceof UUID
                ? player.getUniqueId().equals(args[0]) : player.getUsername().equalsIgnoreCase((String) args[0])).findFirst();
            default -> null;
        });
    }
    static Object invoke(Object owner, String name, Class<?>[] types, Object... args) throws Exception {
        return owner.getClass().getMethod(name, types).invoke(owner, args);
    }

    static void proofs(Path root) throws Exception {
        Path folder = Files.createDirectory(root.resolve("ownership"));
        Ownership proofs = new Ownership(folder);
        String account = NativeAuth.fingerprint("limboauth", ID, "1234");
        proofs.record("limboauth", ID, NAME, account);
        check(new Ownership(folder).account("limboauth", ID, NAME).equals(account), "birth proof persists");
        check(proofs.account("librelogin", ID, NAME).isEmpty(), "engine isolation");
        check(proofs.account("limboauth", UUID.randomUUID(), NAME).isEmpty(), "UUID isolation");
        check(proofs.account("limboauth", ID, NAME.toLowerCase(Locale.ROOT)).isEmpty(), "exact name isolation");
        check(!Files.readString(folder.resolve("password-reset-proofs.properties")).contains(NEW), "no password in proof file");
        BridgeConfig defaults = new BridgeConfig(Files.createDirectory(root.resolve("defaults")));
        check(!defaults.enabled && defaults.endpoint.endsWith(":5800"), "disabled defaults on port 5800");
    }

    static void libre(Player player) throws Exception {
        String base = "xyz.kyngs.librelogin.";
        Class<?> userType = type(base + "api.database.User");
        Class<?> hashType = type(base + "api.crypto.HashedPassword");
        Object crypto = type(base + "common.crypto.BCrypt2ACryptoProvider").getConstructor().newInstance();
        Object oldHash = invoke(crypto, "createHash", new Class<?>[]{String.class}, OLD);
        Object user = type(base + "common.database.AuthenticUser").getConstructor(UUID.class, UUID.class, hashType,
            String.class, Timestamp.class, Timestamp.class, String.class, String.class, Timestamp.class, String.class, String.class)
            .newInstance(ID, null, oldHash, NAME, new Timestamp(1234000), new Timestamp(1235000), "KEEP-TOTP", "127.0.0.1",
                new Timestamp(1236000), "survival", null);
        AtomicReference<Object> record = new AtomicReference<>(user);
        AtomicBoolean authorized = new AtomicBoolean(true), twoFactorPending = new AtomicBoolean(false), online = new AtomicBoolean(false), multi = new AtomicBoolean(false);
        AtomicInteger updates = new AtomicInteger();
        Object database = proxy(type(base + "api.database.ReadWriteDatabaseProvider"), (name, args) -> {
            if (name.equals("getByUUID") || name.equals("getByName")) return record.get();
            if (name.equals("updateUser")) { updates.incrementAndGet(); record.set(args[0]); }
            return null;
        });
        Object authorization = proxy(type(base + "api.authorization.AuthorizationProvider"), (name, args) -> switch (name) {
            case "isAuthorized" -> authorized.get();
            case "isAwaiting2FA" -> twoFactorPending.get();
            default -> null;
        });
        Object platform = proxy(type(base + "api.PlatformHandle"), (name, args) -> switch (name) {
            case "getPlatformIdentifier" -> "velocity";
            case "getPlayerClass" -> Player.class;
            default -> null;
        });
        Object api = proxy(type(base + "api.LibreLoginPlugin"), (name, args) -> switch (name) {
            case "getPlatformHandle" -> platform;
            case "multiProxyEnabled" -> multi.get();
            case "getDatabaseProvider" -> database;
            case "getAuthorizationProvider" -> authorization;
            case "getDefaultCryptoProvider" -> crypto;
            case "isPresent" -> online.get();
            case "getPlayerForUUID" -> player;
            case "validPassword" -> true;
            default -> null;
        });
        Object provider = proxy(type(base + "api.provider.LibreLoginProvider"), (name, args) -> api);
        LibreLoginAuth adapter = new LibreLoginAuth(provider);
        check(adapter.authenticated(player), "LibreLogin real API authorized connection");
        String account = adapter.account(player);
        twoFactorPending.set(true);
        check(!adapter.authenticated(player), "LibreLogin pending TOTP denied");
        twoFactorPending.set(false); authorized.set(false);
        check(!adapter.authenticated(player), "LibreLogin native unauthenticated denied");
        authorized.set(true);
        check(adapter.reset(ID, NAME, account, NEW, () -> false).equals("expired") && updates.get() == 0, "LibreLogin denied claim never writes");
        online.set(true);
        check(adapter.reset(ID, NAME, account, NEW, () -> true).equals("online") && updates.get() == 0, "LibreLogin network online denied");
        online.set(false);
        check(adapter.reset(UUID.randomUUID(), NAME, account, NEW, () -> true).equals("identity_mismatch"), "LibreLogin UUID mismatch denied");
        check(adapter.reset(ID, NAME.toLowerCase(Locale.ROOT), account, NEW, () -> true).equals("identity_mismatch"), "LibreLogin wrong case denied");
        check(adapter.reset(ID, NAME, account, NEW, () -> true).equals("success"), "LibreLogin real crypto reset");
        Object savedHash = userType.getMethod("getHashedPassword").invoke(user);
        check(Boolean.TRUE.equals(invoke(crypto, "matches", new Class<?>[]{String.class, hashType}, NEW, savedHash)), "LibreLogin new password verifies natively");
        check(Boolean.FALSE.equals(invoke(crypto, "matches", new Class<?>[]{String.class, hashType}, OLD, savedHash)), "LibreLogin old password fails natively");
        check("KEEP-TOTP".equals(userType.getMethod("getSecret").invoke(user)), "LibreLogin TOTP preserved");
        check(userType.getMethod("getIp").invoke(user) == null && userType.getMethod("getLastAuthentication").invoke(user) == null, "LibreLogin prior session revoked");
        userType.getMethod("setJoinDate", Timestamp.class).invoke(user, new Timestamp(2234000));
        check(adapter.reset(ID, NAME, account, NEW, () -> true).equals("identity_mismatch"), "LibreLogin recreated account denied");
        multi.set(true);
        boolean rejected = false;
        try { new LibreLoginAuth(provider); } catch (IllegalStateException expected) { rejected = true; }
        check(rejected, "LibreLogin multi proxy denied");
        record.set(null);
        check(adapter.reset(ID, NAME, account, NEW, () -> true).equals("not_found"), "LibreLogin absent native account denied");
    }

    static void limbo(Path root, Player player) throws Exception {
        String base = "net.elytrium.limboauth.";
        Class<?> main = type(base + "LimboAuth"), model = type(base + "model.RegisteredPlayer");
        Class<?> unsafeType = type("sun.misc.Unsafe");
        Field unsafeField = unsafeType.getDeclaredField("theUnsafe"); unsafeField.setAccessible(true);
        Object plugin = unsafeType.getMethod("allocateInstance", Class.class).invoke(unsafeField.get(null), main);
        // Avoid starting proxy listeners/metrics; the plugin's real native methods still run unchanged.
        set(plugin, "cachedAuthChecks", new java.util.concurrent.ConcurrentHashMap<>());
        set(plugin, "premiumCache", new java.util.concurrent.ConcurrentHashMap<>());
        set(plugin, "pendingLogins", new HashSet<>());
        Set<String> unsafePasswords = new HashSet<>();
        set(plugin, "unsafePasswords", unsafePasswords);
        Object settings = type(base + "Settings").getField("IMP").get(null);
        Field settingsMain = settings.getClass().getField("MAIN");
        Object options = type(base + "Settings$MAIN").getConstructor().newInstance();
        settingsMain.set(settings, options);
        options.getClass().getField("BCRYPT_COST").set(options, 4); // Fast real BCrypt, isolated test policy.
        String ormlite = base + "thirdparty.com.j256.ormlite.";
        Class<?> sourceType = type(ormlite + "support.ConnectionSource");
        Object source = type(ormlite + "jdbc.JdbcConnectionSource").getConstructor(String.class)
            .newInstance("jdbc:h2:mem:myrinbot_velocity_check;DB_CLOSE_DELAY=-1");
        type(ormlite + "table.TableUtils").getMethod("createTable", sourceType, Class.class).invoke(null, source, model);
        Object dao = type(ormlite + "dao.DaoManager").getMethod("createDao", sourceType, Class.class).invoke(null, source, model);
        set(plugin, "playerDao", dao);
        Object account = model.getConstructor(String.class, String.class, String.class).newInstance(NAME, ID.toString(), "127.0.0.1");
        model.getMethod("setPassword", String.class).invoke(account, OLD);
        model.getMethod("setTotpToken", String.class).invoke(account, "KEEP-TOTP");
        model.getMethod("setRegDate", Long.class).invoke(account, Long.valueOf(1234000));
        Class<?> daoType = type(ormlite + "dao.Dao");
        daoType.getMethod("create", Object.class).invoke(dao, account);
        main.getMethod("cacheAuthUser", Player.class).invoke(plugin, player);
        LimboAuthAdapter adapter = new LimboAuthAdapter(plugin);
        check(adapter.authenticated(player), "LimboAuth released API authorized connection");
        String proof = adapter.account(player);
        main.getMethod("removePlayerFromCache", String.class).invoke(plugin, NAME);
        check(!adapter.authenticated(player), "LimboAuth unverified/TOTP pending denied");
        main.getMethod("cacheAuthUser", Player.class).invoke(plugin, player);
        check(adapter.reset(ID, NAME, proof, NEW, () -> false).equals("expired"), "LimboAuth denied claim never writes");
        int maximum = options.getClass().getField("MAX_PASSWORD_LENGTH").getInt(options);
        options.getClass().getField("MAX_PASSWORD_LENGTH").setInt(options, NEW.length() - 1);
        check(adapter.reset(ID, NAME, proof, NEW, () -> true).equals("failed"), "LimboAuth native maximum password policy");
        options.getClass().getField("MAX_PASSWORD_LENGTH").setInt(options, maximum);
        options.getClass().getField("CHECK_PASSWORD_STRENGTH").setBoolean(options, true);
        unsafePasswords.add(NEW);
        check(adapter.reset(ID, NAME, proof, NEW, () -> true).equals("failed"), "LimboAuth native unsafe password policy");
        unsafePasswords.clear();
        check(adapter.reset(UUID.randomUUID(), NAME, proof, NEW, () -> true).equals("identity_mismatch"), "LimboAuth UUID mismatch denied");
        check(adapter.reset(ID, NAME.toLowerCase(Locale.ROOT), proof, NEW, () -> true).equals("identity_mismatch"), "LimboAuth exact name check");
        check(adapter.reset(ID, NAME, proof, NEW, () -> true).equals("success"), "LimboAuth real ORMLite atomic password update");
        List<?> rows = (List<?>) daoType.getMethod("queryForEq", String.class, Object.class).invoke(dao, "LOWERCASENICKNAME", NAME.toLowerCase(Locale.ROOT));
        Object saved = rows.get(0);
        String savedHash = (String) model.getMethod("getHash").invoke(saved);
        Class<?> bcrypt = type(base + "thirdparty.at.favre.lib.crypto.bcrypt.BCrypt");
        Object verifier = bcrypt.getMethod("verifyer").invoke(null);
        Method verify = verifier.getClass().getMethod("verify", char[].class, CharSequence.class);
        Object good = verify.invoke(verifier, NEW.toCharArray(), savedHash);
        Object bad = verify.invoke(verifier, OLD.toCharArray(), savedHash);
        check(good.getClass().getField("verified").getBoolean(good), "LimboAuth new password verifies natively");
        check(!bad.getClass().getField("verified").getBoolean(bad), "LimboAuth old password fails natively");
        check("KEEP-TOTP".equals(model.getMethod("getTotpToken").invoke(saved)), "LimboAuth TOTP preserved");
        check(Boolean.TRUE.equals(main.getMethod("needAuth", Player.class).invoke(plugin, player)), "LimboAuth session cache invalidated");
        check(((Long) model.getMethod("getTokenIssuedAt").invoke(saved)) > 1234000L, "LimboAuth token issuance renewed");
        model.getMethod("setRegDate", Long.class).invoke(saved, Long.valueOf(2234000));
        daoType.getMethod("update", Object.class).invoke(dao, saved);
        check(adapter.reset(ID, NAME, proof, NEW, () -> true).equals("identity_mismatch"), "LimboAuth recreated account denied");
        sourceType.getMethod("close").invoke(source);
    }

    static JsonObject job(MyrinbotVelocity bridge) throws Exception {
        JsonObject job = new JsonObject();
        job.addProperty("id", UUID.randomUUID().toString()); job.addProperty("uuid", ID.toString()); job.addProperty("player", NAME);
        job.addProperty("engine", "limboauth"); job.addProperty("instance", (String) get(bridge, "instance"));
        job.addProperty("account", NativeAuth.fingerprint("limboauth", ID, "1234"));
        job.addProperty("expires", System.currentTimeMillis() / 1000.0 + 29); job.addProperty("password", NEW);
        return job;
    }

    static void protocol(Path root, Player player) throws Exception {
        List<Player> online = new ArrayList<>();
        ProxyServer proxy = server(online);
        AtomicBoolean allowed = new AtomicBoolean(true), redirect = new AtomicBoolean(false);
        AtomicInteger claims = new AtomicInteger(), mutations = new AtomicInteger(), leaks = new AtomicInteger();
        HttpServer http = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        http.createContext("/bridge/survival/password-reset/claim", request -> {
            claims.incrementAndGet(); request.getRequestBody().readAllBytes();
            if (redirect.get()) {
                request.getResponseHeaders().add("Location", "/leak"); request.sendResponseHeaders(302, -1);
            } else {
                byte[] body = ("{\"allowed\":" + allowed.get() + "}").getBytes(StandardCharsets.UTF_8);
                request.sendResponseHeaders(200, body.length); request.getResponseBody().write(body);
            }
            request.close();
        });
        http.createContext("/leak", request -> { leaks.incrementAndGet(); request.sendResponseHeaders(200, -1); request.close(); });
        http.start();
        Path directory = Files.createDirectory(root.resolve("protocol"));
        Files.writeString(directory.resolve("config.properties"), "enabled=true\nendpoint=http://127.0.0.1:" + http.getAddress().getPort()
            + "\nserver-id=survival\ntoken=isolated-test-token-123456\nengine=limboauth\n");
        MyrinbotVelocity bridge = new MyrinbotVelocity(proxy, LOG, directory);
        set(bridge, "config", new BridgeConfig(directory)); set(bridge, "remoteEnabled", true);
        Ownership ownership = new Ownership(directory);
        ownership.record("limboauth", ID, NAME, NativeAuth.fingerprint("limboauth", ID, "1234"));
        set(bridge, "ownership", ownership);
        set(bridge, "nativeAuth", new NativeAuth() {
            public String id() { return "limboauth"; }
            public boolean authenticated(Player current) { return true; }
            public String account(Player current) throws Exception { return NativeAuth.fingerprint(id(), ID, "1234"); }
            public String reset(UUID identity, String name, String account, String password, Claim claim) throws Exception {
                LoginEvent event = new LoginEvent(player); bridge.login(event);
                check(!event.getResult().isAllowed(), "login blocked throughout reset");
                if (!claim.allowed()) return "expired";
                mutations.incrementAndGet(); return "success";
            }
        });
        try {
            JsonObject once = job(bridge);
            check(bridge.execute(once).equals("success") && mutations.get() == 1, "claim before mutation");
            check(!once.has("password"), "plaintext job password reference removed");
            check(bridge.execute(once).equals("expired") && mutations.get() == 1, "replayed job denied");
            LoginEvent outside = new LoginEvent(player); bridge.login(outside);
            check(outside.getResult().isAllowed(), "login gate released after mutation");
            ((Map<?, ?>) get(bridge, "connections")).clear();
            allowed.set(false);
            check(bridge.execute(job(bridge)).equals("expired") && mutations.get() == 1, "revoked binding claim denied");
            allowed.set(true); redirect.set(true);
            check(bridge.execute(job(bridge)).equals("failed") && leaks.get() == 0 && mutations.get() == 1, "credential-bearing redirects refused");
            redirect.set(false);
            int before = claims.get();
            online.add(player);
            check(bridge.execute(job(bridge)).equals("online") && claims.get() == before, "online native account denied before claim");
            online.clear();
            AtomicBoolean connecting = new AtomicBoolean(true);
            Player handshake = player(connecting, new AtomicBoolean(false));
            bridge.preLogin(new PreLoginEvent(handshake, NAME));
            check(bridge.execute(job(bridge)).equals("online") && claims.get() == before, "in-flight handshake denied before claim");
            connecting.set(false);
            JsonObject wrong = job(bridge); wrong.addProperty("instance", UUID.randomUUID().toString());
            check(bridge.execute(wrong).equals("unsupported") && claims.get() == before, "wrong process instance denied");
            wrong = job(bridge); wrong.addProperty("engine", "librelogin");
            check(bridge.execute(wrong).equals("unsupported"), "wrong authentication owner denied");
            wrong = job(bridge); wrong.addProperty("expires", System.currentTimeMillis() / 1000.0 - 1);
            check(bridge.execute(wrong).equals("expired"), "expired jobs denied");
            wrong = job(bridge); wrong.addProperty("password", "new\nconsole command");
            check(bridge.execute(wrong).equals("failed"), "control characters denied");
            wrong = job(bridge); wrong.addProperty("player", "../other");
            check(bridge.execute(wrong).equals("unsupported"), "invalid native account name denied");
            wrong = job(bridge); wrong.remove("account");
            check(bridge.execute(wrong).equals("identity_mismatch") && claims.get() == before, "missing coordinator account proof denied");
            wrong = job(bridge); wrong.addProperty("account", NativeAuth.fingerprint("limboauth", ID, "old-registration"));
            check(bridge.execute(wrong).equals("identity_mismatch") && claims.get() == before, "stale QQ grant for recreated account denied");
            check(MyrinbotVelocity.validUUID(ID.toString()) && !MyrinbotVelocity.validUUID("1-1-1-1-1"), "canonical UUID enforced");
        } finally { bridge.shutdown(new ProxyShutdownEvent()); http.stop(0); }
    }

    public static void main(String[] args) throws Exception {
        Path root = Path.of(args[0]);
        AtomicBoolean active = new AtomicBoolean(true), inServer = new AtomicBoolean(true);
        Player player = player(active, inServer);
        proofs(root); libre(player); limbo(root, player); protocol(root, player);
        System.out.println("Velocity real released API, native hash, session and recovery security checks: " + checks + " PASS");
    }
}
