package cn.starbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import fr.xephi.authme.api.v3.AuthMeApi;
import fr.xephi.authme.api.v3.AuthMePlayer;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.logging.Logger;
import org.bukkit.Bukkit;
import org.bukkit.Server;
import org.bukkit.entity.Player;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.PluginManager;
import org.bukkit.scheduler.BukkitScheduler;
import xyz.kyngs.librelogin.api.LibreLoginPlugin;
import xyz.kyngs.librelogin.api.PlatformHandle;
import xyz.kyngs.librelogin.api.authorization.AuthorizationProvider;
import xyz.kyngs.librelogin.api.crypto.CryptoProvider;
import xyz.kyngs.librelogin.api.crypto.HashedPassword;
import xyz.kyngs.librelogin.api.database.ReadDatabaseProvider;
import xyz.kyngs.librelogin.api.database.User;
import xyz.kyngs.librelogin.api.database.WriteDatabaseProvider;
import xyz.kyngs.librelogin.api.provider.LibreLoginProvider;

/** Security assertions exercise one-shot claims, native identity proofs and actual asynchronous workers. */
public final class PasswordResetCheck {
    private static int checks;
    private static Path directory;
    private static Server server;
    private static final UUID identity = UUID.randomUUID();
    private static final Map<String, Plugin> plugins = new HashMap<>();
    private static final List<Player> online = new ArrayList<>();
    private static boolean authorized = true, twoFactor, present, proxyMode, totpProvider = true;
    private static Player current;
    private static MutableUser user, named;
    private static int writes;
    private static String hashInput;
    private static boolean invalidHash;
    private static Runnable duringHash = () -> { };

    @SuppressWarnings("unchecked") private static <T> T proxy(Class<T> type, InvocationHandler handler, Class<?>... additional) {
        Class<?>[] types = new Class<?>[additional.length + 1]; types[0] = type;
        System.arraycopy(additional, 0, types, 1, additional.length);
        return (T) Proxy.newProxyInstance(type.getClassLoader(), types, handler);
    }
    private static Object zero(Method method) {
        if (method.getReturnType() == boolean.class) return false;
        if (method.getReturnType() == int.class) return 0;
        if (method.getReturnType() == long.class) return 0L;
        return null;
    }
    private static Object common(Object self, Method method, Object[] values, String name) {
        return switch (method.getName()) {
            case "getName" -> name;
            case "getServer" -> server;
            case "getDataFolder" -> directory.resolve(name).toFile();
            case "getLogger" -> Logger.getLogger("PasswordReset-test");
            case "isEnabled" -> true;
            case "hashCode" -> System.identityHashCode(self);
            case "equals" -> self == values[0];
            case "toString" -> name;
            default -> zero(method);
        };
    }
    private static Plugin plugin(String name) { return proxy(Plugin.class, (self, method, values) -> common(self, method, values, name)); }
    private static void check(boolean condition, String message) { if (!condition) throw new AssertionError(message); checks++; }
    private static void rejected(PasswordReset service) throws Exception {
        try { service.bindingProof(current); throw new AssertionError("Unauthenticated/conflicting provider must not issue proof"); }
        catch (java.io.IOException | IllegalStateException expected) { checks++; }
    }
    private static final class MutableUser implements User {
        UUID uuid = identity;
        String name = "Steve", secret = "TOTP-REMUST-STAY", ip = "198.51.100.8";
        Timestamp joined = Timestamp.from(Instant.parse("2025-01-01T00:00:00Z"));
        Timestamp authenticated = Timestamp.from(Instant.now());
        HashedPassword password = new HashedPassword("original", null, "test");
        public UUID getUuid() { return uuid; }
        public String getLastNickname() { return name; }
        public boolean isRegistered() { return true; }
        public String getSecret() { return secret; }
        public Timestamp getJoinDate() { return joined; }
        public HashedPassword getHashedPassword() { return password; }
        public void setHashedPassword(HashedPassword value) { password = value; }
        public void setIp(String value) { ip = value; }
        public void setLastAuthentication(Timestamp value) { authenticated = value; }
    }
    private static final CryptoProvider crypto = new CryptoProvider() {
        public HashedPassword createHash(String password) { hashInput = password; duringHash.run(); return invalidHash ? null : new HashedPassword("hashed:" + password, "salt", "test"); }
        public boolean matches(String password, HashedPassword encoded) { return encoded != null && encoded.hash().equals("hashed:" + password); }
        public String getIdentifier() { return "test"; }
    };
    @SuppressWarnings("unchecked") private static Plugin libre() {
        Object database = proxy(ReadDatabaseProvider.class, (self, method, values) -> switch (method.getName()) {
            case "getByUUID" -> user;
            case "getByName" -> named;
            case "updateUser" -> { user = (MutableUser) values[0]; named = user; writes++; yield null; }
            default -> zero(method);
        }, WriteDatabaseProvider.class);
        Object authorization = proxy(AuthorizationProvider.class, (self, method, values) -> switch (method.getName()) {
            case "isAuthorized" -> authorized;
            case "isAwaiting2FA" -> twoFactor;
            default -> zero(method);
        });
        Object platform = proxy(PlatformHandle.class, (self, method, values) -> switch (method.getName()) {
            case "getPlatformIdentifier" -> "paper";
            case "getPlayerClass" -> Player.class;
            default -> zero(method);
        });
        Object api = proxy(LibreLoginPlugin.class, (self, method, values) -> switch (method.getName()) {
            case "getDatabaseProvider" -> database;
            case "getAuthorizationProvider" -> authorization;
            case "getPlatformHandle" -> platform;
            case "getDefaultCryptoProvider", "getCryptoProvider" -> crypto;
            case "getPlayerForUUID" -> current;
            case "isPresent" -> present;
            case "multiProxyEnabled" -> proxyMode;
            case "validPassword" -> !values[0].equals("Rejected-Pass");
            case "getTOTPProvider" -> totpProvider ? new Object() : null;
            default -> zero(method);
        });
        return proxy(Plugin.class, (self, method, values) -> method.getName().equals("getLibreLogin") ? api : common(self, method, values, "LibreLogin"), LibreLoginProvider.class);
    }
    private static final class Transport implements GameLogin.Transport {
        JsonObject pending;
        JsonObject advertised;
        final List<JsonObject> results = new ArrayList<>();
        boolean allowed = true;
        Runnable beforeClaim = () -> { };
        int claims;
        String account;
        public synchronized JsonObject post(String route, JsonObject request) {
            JsonObject response = new JsonObject();
            if (route.equals("/password-reset/claim")) {
                claims++; beforeClaim.run(); response.addProperty("allowed", allowed); return response;
            }
            advertised = request.deepCopy();
            for (var result : request.getAsJsonArray("results")) results.add(result.getAsJsonObject());
            response.addProperty("enabled", true); response.addProperty("engine", request.get("engine").getAsString());
            response.addProperty("instance", request.get("instance").getAsString());
            JsonArray jobs = new JsonArray(); if (pending != null) { jobs.add(pending); pending = null; }
            response.add("jobs", jobs); return response;
        }
    }
    private static JsonObject job(Transport transport, String engine) {
        JsonObject job = new JsonObject(); job.addProperty("id", UUID.randomUUID().toString());
        job.addProperty("uuid", identity.toString()); job.addProperty("player", "Steve"); job.addProperty("password", "New-Safe-Password");
        job.addProperty("engine", engine); job.addProperty("instance", transport.advertised.get("instance").getAsString());
        job.addProperty("account", transport.account);
        job.addProperty("expires", System.currentTimeMillis() / 1000.0 + 30); return job;
    }
    private static String submit(PasswordReset service, Transport transport, JsonObject job) throws Exception {
        String id = job.get("id").getAsString(); transport.pending = job;
        long deadline = System.currentTimeMillis() + 4000;
        do {
            service.tick();
            for (JsonObject result : transport.results) if (id.equals(result.get("id").getAsString())) {
                check(result.size() == 2 && !result.toString().contains("Password"), "Result contains no credentials or provider messages");
                return result.get("status").getAsString();
            }
            Thread.sleep(5);
        } while (System.currentTimeMillis() < deadline);
        throw new AssertionError("Timed out waiting for isolated reset worker");
    }
    private static AuthMePlayer authAccount(UUID uuid, String name, Instant registered) {
        return new AuthMePlayer() {
            public String getName() { return name; }
            public Optional<UUID> getUuid() { return Optional.ofNullable(uuid); }
            public Instant getRegistrationDate() { return registered; }
        };
    }
    public static void main(String[] arguments) throws Exception {
        directory = Files.createTempDirectory(Path.of(".tools/login-adapters"), "password-reset-");
        PluginManager manager = proxy(PluginManager.class, (self, method, values) -> method.getName().equals("getPlugin") ? plugins.get(values[0]) : zero(method));
        BukkitScheduler scheduler = proxy(BukkitScheduler.class, (self, method, values) -> {
            if (method.getName().equals("scheduleSyncDelayedTask")) { ((Runnable) values[1]).run(); return 1; }
            return zero(method);
        });
        server = proxy(Server.class, (self, method, values) -> switch (method.getName()) {
            case "getPluginManager" -> manager;
            case "getScheduler" -> scheduler;
            case "getOnlinePlayers" -> online;
            case "getLogger" -> Logger.getLogger("PasswordReset-test");
            case "getName" -> "Paper";
            case "getVersion", "getBukkitVersion" -> "test";
            default -> zero(method);
        });
        Bukkit.setServer(server);
        current = proxy(Player.class, (self, method, values) -> switch (method.getName()) {
            case "getName" -> "Steve";
            case "getUniqueId" -> identity;
            case "isOnline" -> true;
            case "hashCode" -> System.identityHashCode(self);
            case "equals" -> self == values[0];
            default -> zero(method);
        });
        Player connection = current;
        Plugin owner = plugin("StarBridge");
        Path authConfig = directory.resolve("AuthMe/config.yml"); Files.createDirectories(authConfig.getParent());
        Files.writeString(authConfig, "settings:\n  sessions:\n    enabled: false\n");
        plugins.put("AuthMe", plugin("AuthMe"));
        AuthMeApi nativeAuth = AuthMeApi.INSTANCE;
        nativeAuth.account = authAccount(identity, "steve", Instant.parse("2025-01-01T00:00:00Z"));
        Transport transport = new Transport(); PasswordReset service = new PasswordReset(owner, transport, PasswordReset.Startup.read(authConfig));
        rejected(service);
        nativeAuth.authenticated = true;
        JsonObject proof = new JsonObject(); service.bindingProof(current).addTo(proof);
        transport.account = proof.get("password_reset_account").getAsString();
        check(transport.account.equals(PasswordReset.accountHash("authme", identity, "2025-01-01T00:00:00Z")), "Binding proof includes an engine/UUID/native-creation SHA-256 fingerprint");
        check(proof.get("password_reset_engine").getAsString().equals("authme"), "Only completed native authentication grants reset proof");
        check(proof.get("password_reset_platform").getAsString().equals("bukkit"), "Proof is platform scoped");
        service.tick(); current = null;
        JsonObject reset = job(transport, "authme");
        long before = System.currentTimeMillis();
        check(submit(service, transport, reset).equals("success"), "Asynchronous AuthMe reset is verified, not assumed");
        check(System.currentTimeMillis() - before >= 80 && nativeAuth.changes == 1, "Void AuthMe request waits for confirmed password");
        check(!reset.has("password"), "Secret is removed from consumed job");
        JsonObject duplicate = reset.deepCopy(); duplicate.addProperty("password", "Never-Replay-This"); transport.pending = duplicate; service.tick(); Thread.sleep(25);
        check(nativeAuth.changes == 1 && transport.claims == 1, "A duplicated delivery cannot reset or claim twice");
        transport.allowed = false;
        check(submit(service, transport, job(transport, "authme")).equals("expired") && nativeAuth.changes == 1, "Revoked binding/settings claim cannot mutate password");
        transport.allowed = true;
        JsonObject missingAccount = job(transport, "authme"); missingAccount.remove("account");
        check(submit(service, transport, missingAccount).equals("identity_mismatch") && nativeAuth.changes == 1, "A legacy grant without native account generation cannot reset passwords");
        JsonObject mismatchedAccount = job(transport, "authme"); mismatchedAccount.addProperty("account", "0".repeat(64));
        check(submit(service, transport, mismatchedAccount).equals("identity_mismatch") && nativeAuth.changes == 1, "A different account generation cannot reuse QQ ownership");
        nativeAuth.account = authAccount(UUID.randomUUID(), "steve", Instant.parse("2025-01-01T00:00:00Z"));
        check(submit(service, transport, job(transport, "authme")).equals("not_found"), "Native UUID mismatch is rejected");
        nativeAuth.account = authAccount(null, "steve", Instant.parse("2026-01-01T00:00:00Z"));
        check(submit(service, transport, job(transport, "authme")).equals("identity_mismatch"), "Recreated name without stored UUID cannot reuse old native proof");
        nativeAuth.account = authAccount(null, "steve", Instant.parse("2025-01-01T00:00:00Z"));
        check(submit(service, transport, job(transport, "authme")).equals("success"), "Older AuthMe account without stored UUID uses native-authenticated local UUID proof");
        online.add(connection);
        check(submit(service, transport, job(transport, "authme")).equals("online"), "Connected native accounts are never changed"); online.clear();
        JsonObject wrongInstance = job(transport, "authme"); wrongInstance.addProperty("instance", UUID.randomUUID().toString());
        check(submit(service, transport, wrongInstance).equals("unsupported"), "Jobs cannot cross game-end boot instances");
        JsonObject expired = job(transport, "authme"); expired.addProperty("expires", 1);
        check(submit(service, transport, expired).equals("expired"), "Expired work does not claim");
        Files.writeString(authConfig, "settings:\n  sessions:\n    enabled: true\n");
        check(!PasswordReset.Startup.read(authConfig).valid(), "Remembered-IP AuthMe sessions disable reset capability");
        Files.writeString(authConfig, "settings:\n  sessions:\n    enabled: 'false'\n");
        check(!PasswordReset.Startup.read(authConfig).valid(), "Nonboolean YAML must fail closed");
        Files.writeString(authConfig, "settings:\n  sessions:\n    enabled: false\n");
        PasswordReset.Startup pinned = PasswordReset.Startup.read(authConfig);
        Files.writeString(authConfig, "settings:\n  sessions:\n    enabled: true\n");
        check(!pinned.valid(), "A native configuration edit invalidates the loaded startup policy");
        Files.writeString(authConfig, "settings:\n  sessions:\n    enabled: false\n");
        check(!pinned.valid(), "Restoring YAML cannot bypass the full-restart requirement");
        check(!PasswordReset.Startup.capture(owner).valid(), "Hot-loading while AuthMe is already active cannot claim runtime policy knowledge");
        Files.writeString(authConfig, "settings:\n  sessions:\n    enabled: false\n  security:\n    minPasswordLength: 10\n    passwordMaxLength: 20\n    unsafePasswords: [unsafevalue]\n  restrictions:\n    allowedPasswordCharacters: '[a-z]*'\n");
        PasswordReset.Startup constraints = PasswordReset.Startup.read(authConfig);
        check(constraints.accepts("sufficientlowercase") && !constraints.accepts("Short") && !constraints.accepts("waytoolonglowercasepassword"), "Native configured min/max lengths are enforced before the admin API");
        check(!constraints.accepts("invalidUPPERcase") && !constraints.accepts("unsafevalue"), "Native allowed-character regex and unsafe-password list remain enforced");
        Files.writeString(authConfig, "settings:\n  sessions:\n    enabled: false\n");
        current = connection; plugins.put("nLogin", plugin("nLogin")); rejected(service); plugins.remove("nLogin");
        Files.writeString(authConfig, "settings:\n  sessions:\n    enabled: true\n");
        check(service.bindingProof(current) == null, "Unsafe recovery configuration preserves native-authenticated ordinary qbind without granting reset proof");
        service.tick();
        check(transport.advertised.get("engine").getAsString().isEmpty(), "Unsafe AuthMe recovery policy advertises no reset capability");
        Files.writeString(authConfig, "settings:\n  sessions:\n    enabled: false\n");
        service.close(); plugins.clear();
        nativeAuth.mutate = false;
        PasswordReset.AuthMe unconfirmed = new PasswordReset.AuthMe(plugin("AuthMe"), PasswordReset.Startup.read(authConfig));
        try { unconfirmed.reset(identity, "Steve", "Unconfirmed-New-Pass", System.currentTimeMillis() - 1); throw new AssertionError("Void native request cannot imply completion"); }
        catch (PasswordReset.Uncertain expected) { checks++; }
        check(!nativeAuth.password.equals("Unconfirmed-New-Pass"), "A void AuthMe request with no matching persisted password is never acknowledged as success");
        nativeAuth.mutate = true;

        // Model the native void API whose queued operation cannot be cancelled on timeout.
        Plugin asyncNative = plugin("AuthMe"); plugins.put("AuthMe", asyncNative);
        Transport uncertainTransport = new Transport();
        PasswordReset uncertainService = new PasswordReset(owner, uncertainTransport, PasswordReset.Startup.read(authConfig));
        PasswordReset.Adapter pending = new PasswordReset.Adapter(asyncNative, "authme") {
            boolean authenticated(Player player) { return true; }
            String fingerprint(UUID uuid, String name) { return "native-account-creation"; }
            boolean reset(UUID uuid, String name, String password, long deadline) throws Exception { throw new PasswordReset.Uncertain(); }
        };
        var adapterField = PasswordReset.class.getDeclaredField("adapter"); adapterField.setAccessible(true); adapterField.set(uncertainService, pending);
        JsonObject uncertainProof = new JsonObject(); uncertainService.bindingProof(current).addTo(uncertainProof);
        uncertainTransport.account = uncertainProof.get("password_reset_account").getAsString(); uncertainService.tick(); current = null;
        check(submit(uncertainService, uncertainTransport, job(uncertainTransport, "authme")).equals("uncertain"), "Unconfirmed native void operations report uncertainty rather than false failure/success");
        uncertainService.tick();
        check(uncertainTransport.advertised.get("engine").getAsString().isEmpty(), "Quarantined provider withdraws capability after reporting the original result");
        var preLogin = new org.bukkit.event.player.AsyncPlayerPreLoginEvent("Steve", java.net.InetAddress.getLoopbackAddress(), identity);
        uncertainService.onPreLogin(preLogin);
        check(preLogin.getLoginResult() != org.bukkit.event.player.AsyncPlayerPreLoginEvent.Result.ALLOWED, "Unconfirmed native work keeps the account offline until full restart");
        uncertainService.close(); plugins.clear(); current = connection;

        user = new MutableUser(); named = user; plugins.put("LibreLogin", libre());
        transport = new Transport(); service = new PasswordReset(owner, transport, PasswordReset.Startup.disabled());
        twoFactor = true; rejected(service); twoFactor = false;
        totpProvider = false;
        try { service.bindingProof(current).addTo(new JsonObject()); throw new AssertionError("Unsupported migrated TOTP must not issue proof"); }
        catch (java.io.IOException expected) { checks++; }
        totpProvider = true;
        proof = new JsonObject(); service.bindingProof(current).addTo(proof);
        check(proof.get("password_reset_engine").getAsString().equals("librelogin"), "LibreLogin requires finished native two-factor authorization before proof");
        service.tick(); current = null;
        transport.account = proof.get("password_reset_account").getAsString();
        check(submit(service, transport, job(transport, "librelogin")).equals("success"), "LibreLogin delegates native hashing and update to the public API");
        check(writes == 1 && "TOTP-REMUST-STAY".equals(user.secret), "Reset preserves native TOTP secret");
        check(user.ip == null && user.authenticated == null, "Password reset invalidates remembered-IP native session");
        check("New-Safe-Password".equals(hashInput), "Native crypto receives only the private supplied password");
        user.joined = Timestamp.from(Instant.now());
        check(submit(service, transport, job(transport, "librelogin")).equals("identity_mismatch") && writes == 1, "Recreated LibreLogin registration loses local proof");
        user.joined = Timestamp.from(Instant.parse("2025-01-01T00:00:00Z"));
        named = new MutableUser(); named.uuid = UUID.randomUUID();
        check(submit(service, transport, job(transport, "librelogin")).equals("not_found") && writes == 1, "Name and UUID must resolve to the same native record"); named = user;
        present = true;
        check(submit(service, transport, job(transport, "librelogin")).equals("failed") && writes == 1, "Native network-presence check fences cached connected accounts"); present = false;
        invalidHash = true;
        check(submit(service, transport, job(transport, "librelogin")).equals("failed") && writes == 1, "Native hash failure leaves existing password intact"); invalidHash = false;
        JsonObject badPassword = job(transport, "librelogin"); badPassword.addProperty("password", "Rejected-Pass");
        check(submit(service, transport, badPassword).equals("failed") && writes == 1, "Native password rules cannot be bypassed");
        MutableUser original = user;
        duringHash = () -> { user = new MutableUser(); user.joined = Timestamp.from(Instant.now()); named = user; };
        check(submit(service, transport, job(transport, "librelogin")).equals("failed") && writes == 1, "A native account replaced while hashing cannot be overwritten by the old user object");
        duringHash = () -> { }; user = original; named = user;
        transport.beforeClaim = () -> user.uuid = UUID.randomUUID();
        check(submit(service, transport, job(transport, "librelogin")).equals("identity_mismatch") && writes == 1, "Native identity is checked again after network claim");
        service.close();
        String stored = Files.readString(directory.resolve("StarBridge/password-reset-proofs.properties"));
        check(!stored.contains("Password") && !stored.contains("TOTP") && !stored.contains("198.51"), "Persisted proof contains identity/creation only, never credentials");
        System.out.println("PasswordReset security checks: " + checks + " passed");
    }
}
