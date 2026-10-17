package cn.starbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.lang.reflect.Method;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.Properties;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.LinkedBlockingDeque;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import org.bukkit.Bukkit;
import org.bukkit.configuration.file.YamlConfiguration;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.player.AsyncPlayerPreLoginEvent;
import org.bukkit.event.player.PlayerLoginEvent;
import org.bukkit.event.server.PluginDisableEvent;
import org.bukkit.event.server.PluginEnableEvent;
import org.bukkit.plugin.Plugin;

/** Native password changes use public APIs and a separate, memory-only one-shot protocol. */
final class PasswordReset implements Listener {
    private static final String[] PLUGINS = {"AuthMe", "nLogin", "LoginSecurity", "LibreLogin"};
    private final Plugin owner;
    private final GameLogin.Transport transport;
    private final String instance = UUID.randomUUID().toString();
    private final LoginLinks bindingGate;
    private final Ownership ownership;
    private final Startup startup;
    private final ThreadPoolExecutor worker = new ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS,
        new ArrayBlockingQueue<Runnable>(8), runnable -> {
            Thread thread = new Thread(runnable, "Myrinbot-PasswordReset"); thread.setDaemon(true); return thread;
        });
    private final LinkedBlockingDeque<JsonObject> results = new LinkedBlockingDeque<JsonObject>(64);
    private final ConcurrentHashMap<String, Long> seen = new ConcurrentHashMap<String, Long>();
    private final java.util.Set<String> reserved = ConcurrentHashMap.newKeySet();
    private volatile Adapter adapter;
    private volatile Plugin quarantined;
    private volatile boolean closed;

    PasswordReset(Plugin owner, GameLogin.Transport transport, Startup startup) throws IOException {
        this.owner = owner; this.transport = transport;
        this.startup = startup;
        bindingGate = new LoginLinks(owner);
        ownership = new Ownership(owner.getDataFolder().toPath().resolve("password-reset-proofs.properties"));
        owner.getServer().getPluginManager().registerEvents(this, owner);
        refresh();
    }

    /** Called only on the Bukkit thread. A plugin transition invalidates captured adapters. */
    void refresh() {
        if (closed || BridgeScheduler.isFolia()) { adapter = null; return; }
        List<Plugin> installed = new ArrayList<Plugin>();
        for (String name : PLUGINS) {
            Plugin found = Bukkit.getPluginManager().getPlugin(name);
            if (found != null && found.isEnabled()) installed.add(found);
        }
        if (installed.size() != 1) { adapter = null; return; }
        Plugin nativePlugin = installed.get(0);
        if (nativePlugin == quarantined) { adapter = null; return; }
        if ("AuthMe".equals(nativePlugin.getName()) && !startup.valid()) { adapter = null; return; }
        if (adapter != null && adapter.installed == nativePlugin) return;
        adapter = null;
        try {
            if ("AuthMe".equals(nativePlugin.getName())) adapter = new AuthMe(nativePlugin, startup);
            else if ("LibreLogin".equals(nativePlugin.getName())) adapter = new Libre(nativePlugin);
        } catch (ReflectiveOperationException | RuntimeException | LinkageError unavailable) {
            // No exception text: optional providers can include sensitive arguments in errors.
        }
    }

    /** Native authentication is required for qbind even when Myrinbot game login is disabled. */
    Proof bindingProof(Player player) throws Exception {
        refresh();
        Adapter captured = adapter;
        if (captured == null) {
            LoginLink link = bindingGate.select("auto");
            if (link != null && !link.authenticated(player)) throw new IOException("请先完成原登录插件的认证，再使用 /qbind。");
            return null;
        }
        if (!captured.authenticated(player)) throw new IOException("请先完成原登录插件的认证，再使用 /qbind。");
        return new Proof(captured, BukkitCompatibility.identity(player), player.getName());
    }

    final class Proof {
        private final Adapter captured;
        private final UUID identity;
        private final String name;
        private Proof(Adapter captured, UUID identity, String name) { this.captured = captured; this.identity = identity; this.name = name; }
        /** Database work is performed by the existing HTTP worker, never by the server thread. */
        void addTo(JsonObject request) throws Exception {
            if (!active(captured)) throw new IOException("Native authentication changed");
            String fingerprint = captured.proofFingerprint(identity, name);
            if (fingerprint == null || !active(captured)) throw new IOException("Native account changed");
            ownership.remember(captured.id, name, identity, fingerprint);
            request.addProperty("password_reset_engine", captured.id);
            request.addProperty("password_reset_platform", "bukkit");
            request.addProperty("password_reset_account", accountHash(captured.id, identity, fingerprint));
        }
    }

    private boolean active(Adapter captured) {
        return !closed && adapter == captured && captured.installed != quarantined && owner.isEnabled() && captured.installed.isEnabled();
    }

    /** Invoked by the bridge's single HTTP timer. Responses never enter normal persistent jobs. */
    void tick() throws Exception {
        if (closed) return;
        Adapter captured = adapter;
        JsonObject request = new JsonObject();
        request.addProperty("instance", instance); request.addProperty("platform", "bukkit");
        List<JsonObject> batch = new ArrayList<JsonObject>();
        results.stream().limit(32).forEach(batch::add);
        // Report an unconfirmed AuthMe request using its original engine once, then withdraw capability.
        boolean reportingUncertain = batch.stream().anyMatch(value -> "uncertain".equals(string(value, "status")));
        request.addProperty("engine", reportingUncertain ? "authme" : captured == null ? "" : captured.id);
        JsonArray acknowledgements = new JsonArray(); for (JsonObject result : batch) acknowledgements.add(result);
        request.add("results", acknowledgements);
        JsonObject response = transport.post("/password-reset/tick", request);
        for (JsonObject result : batch) results.removeFirstOccurrence(result);
        if (captured == null || !active(captured) || !response.has("enabled") || !response.get("enabled").getAsBoolean()
                || !instance.equals(string(response, "instance")) || !captured.id.equals(string(response, "engine"))) return;
        JsonArray jobs = response.getAsJsonArray("jobs");
        if (jobs == null || jobs.size() > 8) return;
        long now = System.currentTimeMillis(); seen.entrySet().removeIf(entry -> entry.getValue() < now);
        for (JsonElement item : jobs) {
            if (!item.isJsonObject()) continue;
            JsonObject job = item.getAsJsonObject();
            String id = string(job, "id");
            try { UUID.fromString(id); } catch (IllegalArgumentException invalid) { continue; }
            if (seen.size() >= 2048 || seen.putIfAbsent(id, now + 300000) != null) continue;
            // Do not retain the response/password on the HTTP timer after handing it to the worker.
            BukkitCompatibility.runTask(owner, () -> start(captured, job));
        }
    }

    private void start(Adapter captured, JsonObject job) {
        String id = string(job, "id"), name = string(job, "player");
        UUID identity;
        try {
            identity = UUID.fromString(string(job, "uuid"));
            if (!name.matches("[A-Za-z0-9_]{1,16}") || !instance.equals(string(job, "instance"))
                    || !captured.id.equals(string(job, "engine")) || !active(captured)) { finish(id, "unsupported"); return; }
            if (expired(job)) { finish(id, "expired"); return; }
            String password = string(job, "password");
            if (!password.matches("[!-~]{8,64}")) { finish(id, "failed"); return; }
            for (Player player : BukkitCompatibility.players()) {
                if (identity.equals(BukkitCompatibility.identity(player)) || name.equalsIgnoreCase(player.getName())) { finish(id, "online"); return; }
            }
            String key = name.toLowerCase(Locale.ROOT);
            if (!reserved.add(key)) { finish(id, "failed"); return; }
            try { worker.execute(() -> execute(captured, job, identity, name, key)); }
            catch (RuntimeException rejected) { reserved.remove(key); finish(id, "failed"); }
        } catch (RuntimeException invalid) { finish(id, "failed"); }
    }

    private void execute(Adapter captured, JsonObject job, UUID identity, String name, String key) {
        String id = string(job, "id"), status = "failed";
        try {
            if (!active(captured)) { status = "unsupported"; return; }
            if (expired(job)) { status = "expired"; return; }
            String fingerprint = captured.fingerprint(identity, name);
            if (fingerprint == null) { status = "not_found"; return; }
            if (!ownership.matches(captured.id, name, identity, fingerprint)
                    || !accountHash(captured.id, identity, fingerprint).equals(string(job, "account"))) { status = "identity_mismatch"; return; }
            String password = string(job, "password");
            // The claim rechecks QQ ownership, binding generation, settings and expiration immediately before mutation.
            JsonObject claim = new JsonObject(); claim.addProperty("id", id); claim.addProperty("instance", instance);
            claim.addProperty("platform", "bukkit"); claim.addProperty("engine", captured.id);
            JsonObject permission = transport.post("/password-reset/claim", claim);
            if (!permission.has("allowed") || !permission.get("allowed").getAsBoolean() || !active(captured) || expired(job)) { status = "expired"; return; }
            String currentFingerprint = captured.fingerprint(identity, name);
            if (!fingerprint.equals(currentFingerprint) || !ownership.matches(captured.id, name, identity, currentFingerprint)
                    || !accountHash(captured.id, identity, currentFingerprint).equals(string(job, "account"))) { status = "identity_mismatch"; return; }
            if (!active(captured) || expired(job)) { status = "expired"; return; }
            status = captured.reset(identity, name, password, System.currentTimeMillis() + 15000) ? "success" : "failed";
        } catch (Uncertain pendingNativeWork) {
            status = "uncertain"; quarantined = captured.installed; adapter = null;
        } catch (Exception | LinkageError failure) {
            // Never log passwords, native exception messages or reflected invocation arguments.
        } finally {
            job.remove("password");
            // A void native request cannot be cancelled. Keep the account offline until a full server restart.
            if (!"uncertain".equals(status)) reserved.remove(key);
            finish(id, status);
        }
    }

    private static boolean expired(JsonObject job) { return !job.has("expires") || job.get("expires").getAsDouble() * 1000 < System.currentTimeMillis(); }
    private static String string(JsonObject value, String key) {
        return value.has(key) && value.get(key).isJsonPrimitive() ? value.get(key).getAsString() : "";
    }
    static String accountHash(String engine, UUID identity, String fingerprint) {
        try {
            byte[] value = (engine + "\n" + identity.toString() + "\n" + fingerprint).getBytes(java.nio.charset.StandardCharsets.UTF_8);
            byte[] digest = java.security.MessageDigest.getInstance("SHA-256").digest(value);
            StringBuilder result = new StringBuilder();
            for (byte part : digest) result.append(String.format(Locale.ROOT, "%02x", part & 255));
            return result.toString();
        } catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException("SHA-256 unavailable"); }
    }
    private void finish(String id, String status) {
        JsonObject result = new JsonObject(); result.addProperty("id", id); result.addProperty("status", status);
        if (!results.offerLast(result)) { results.pollFirst(); results.offerLast(result); }
    }

    @EventHandler(priority = EventPriority.HIGHEST)
    public void onPreLogin(AsyncPlayerPreLoginEvent event) {
        if (reserved.contains(event.getName().toLowerCase(Locale.ROOT))) event.disallow(AsyncPlayerPreLoginEvent.Result.KICK_OTHER, "正在安全更新游戏密码，请稍后重新连接。");
    }
    @EventHandler(priority = EventPriority.HIGHEST)
    public void onLogin(PlayerLoginEvent event) {
        if (reserved.contains(event.getPlayer().getName().toLowerCase(Locale.ROOT))) event.disallow(PlayerLoginEvent.Result.KICK_OTHER, "正在安全更新游戏密码，请稍后重新连接。");
    }
    @EventHandler public void onEnable(PluginEnableEvent event) { refresh(); }
    @EventHandler public void onDisable(PluginDisableEvent event) { if (event.getPlugin() == owner) close(); else refresh(); }
    void close() { closed = true; adapter = null; worker.shutdownNow(); bindingGate.close(); reserved.clear(); results.clear(); }

    abstract static class Adapter {
        final Plugin installed;
        final String id;
        Adapter(Plugin installed, String id) { this.installed = installed; this.id = id; }
        abstract boolean authenticated(Player player) throws Exception;
        abstract String fingerprint(UUID identity, String name) throws Exception;
        String proofFingerprint(UUID identity, String name) throws Exception { return fingerprint(identity, name); }
        abstract boolean reset(UUID identity, String name, String password, long deadline) throws Exception;
    }
    static final class Uncertain extends Exception { private static final long serialVersionUID = 1L; }

    /** AuthMe's void changePassword is asynchronous; only a successful password comparison completes it. */
    static final class AuthMe extends Adapter {
        private final Object api;
        private final Startup startup;
        private final Method authenticated, registered, playerInfo, infoName, infoUUID, registrationDate, changePassword, checkPassword;
        AuthMe(Plugin installed, Startup startup) throws ReflectiveOperationException {
            super(installed, "authme");
            this.startup = startup;
            ClassLoader loader = installed.getClass().getClassLoader();
            Class<?> type = Class.forName("fr.xephi.authme.api.v3.AuthMeApi", false, loader);
            Class<?> info = Class.forName("fr.xephi.authme.api.v3.AuthMePlayer", false, loader);
            api = type.getMethod("getInstance").invoke(null);
            if (api == null) throw new IllegalStateException("AuthMe not ready");
            authenticated = type.getMethod("isAuthenticated", Player.class); registered = type.getMethod("isRegistered", String.class);
            playerInfo = type.getMethod("getPlayerInfo", String.class); infoName = info.getMethod("getName");
            infoUUID = info.getMethod("getUuid"); registrationDate = info.getMethod("getRegistrationDate");
            changePassword = type.getMethod("changePassword", String.class, String.class); checkPassword = type.getMethod("checkPassword", String.class, String.class);
        }
        boolean authenticated(Player player) throws Exception { return Boolean.TRUE.equals(authenticated.invoke(api, player)); }
        String fingerprint(UUID identity, String name) throws Exception {
            if (!startup.valid()) return null;
            if (!Boolean.TRUE.equals(registered.invoke(api, name))) return null;
            // AuthMe data sources index lowercase account keys; retain the canonical real name for identity checks.
            Optional<?> record = (Optional<?>) playerInfo.invoke(api, name.toLowerCase(Locale.ROOT));
            if (!record.isPresent()) return null;
            Object user = record.get();
            if (!name.equalsIgnoreCase((String) infoName.invoke(user))) return null;
            Optional<?> uuid = (Optional<?>) infoUUID.invoke(user);
            if (uuid.isPresent() && !identity.equals(uuid.get())) return null;
            Instant created = (Instant) registrationDate.invoke(user);
            return created == null ? null : created.toString();
        }
        boolean reset(UUID identity, String name, String password, long deadline) throws Exception {
            if (!startup.accepts(password)) return false;
            try {
                changePassword.invoke(api, name, password);
                do {
                    if (Boolean.TRUE.equals(checkPassword.invoke(api, name, password))) return true;
                    Thread.sleep(200);
                } while (installed.isEnabled() && System.currentTimeMillis() < deadline && !Thread.currentThread().isInterrupted());
            } catch (Exception | LinkageError unconfirmed) { throw new Uncertain(); }
            throw new Uncertain();
        }
    }

    /** Captured in onLoad before AuthMe enables. Any later configuration edit requires a full restart. */
    static final class Startup {
        private final Path path;
        private final byte[] bytes;
        private final int minimum, maximum;
        private final java.util.regex.Pattern pattern;
        private final java.util.Set<String> unsafe;
        private volatile boolean invalid;
        private Startup(Path path, byte[] bytes, int minimum, int maximum, java.util.regex.Pattern pattern, java.util.Set<String> unsafe) {
            this.path = path; this.bytes = bytes; this.minimum = minimum; this.maximum = maximum; this.pattern = pattern; this.unsafe = unsafe;
        }
        static Startup capture(Plugin owner) {
            Plugin installed = Bukkit.getPluginManager().getPlugin("AuthMe");
            // A hot-loaded bridge cannot infer what ConfigMe already holds in memory.
            if (installed != null && installed.isEnabled()) return disabled();
            Path path = installed == null ? owner.getDataFolder().toPath().getParent().resolve("AuthMe/config.yml")
                : installed.getDataFolder().toPath().resolve("config.yml");
            return read(path);
        }
        static Startup disabled() { return new Startup(null, null, 0, 0, null, java.util.Collections.emptySet()); }
        static Startup read(Path path) {
            try {
                if (!Files.isRegularFile(path) || Files.size(path) > 1024 * 1024) return disabled();
                byte[] data = Files.readAllBytes(path);
                YamlConfiguration config = new YamlConfiguration();
                config.loadFromString(new String(data, java.nio.charset.StandardCharsets.UTF_8));
                if (!Boolean.FALSE.equals(config.get("settings.sessions.enabled"))) return disabled();
                int minimum = config.getInt("settings.security.minPasswordLength", 5), maximum = config.getInt("settings.security.passwordMaxLength", 30);
                if (minimum < 1 || maximum < minimum || maximum > 1024) return disabled();
                java.util.regex.Pattern pattern = java.util.regex.Pattern.compile(config.getString("settings.restrictions.allowedPasswordCharacters", "[!-~]*"));
                java.util.Set<String> unsafe = new java.util.HashSet<String>();
                for (String value : config.getStringList("settings.security.unsafePasswords")) unsafe.add(value.toLowerCase(Locale.ROOT));
                return new Startup(path, data, minimum, maximum, pattern, unsafe);
            } catch (Exception | LinkageError unavailable) { return disabled(); }
        }
        boolean valid() {
            if (invalid || path == null) return false;
            try {
                if (Files.size(path) > 1024 * 1024 || !java.util.Arrays.equals(bytes, Files.readAllBytes(path))) invalid = true;
            } catch (IOException unavailable) { invalid = true; }
            return !invalid;
        }
        boolean accepts(String password) {
            return valid() && password.length() >= minimum && password.length() <= maximum
                && pattern.matcher(password).matches() && !unsafe.contains(password.toLowerCase(Locale.ROOT));
        }
    }

    /** The native crypto/database providers retain the existing UUID, registration and TOTP secret. */
    static final class Libre extends Adapter {
        private final Object api, database, authorization;
        private final Method authorized, awaiting, byUUID, byName, userUUID, userName, registered, joined, hash,
            setPassword, update, defaultCrypto, validPassword, present, getPlayer, getPassword, cryptoFor, hashAlgo, matches, setIp, setLastAuthentication, secret, totpProvider;
        Libre(Plugin installed) throws ReflectiveOperationException {
            super(installed, "librelogin");
            ClassLoader loader = installed.getClass().getClassLoader();
            Class<?> provider = Class.forName("xyz.kyngs.librelogin.api.provider.LibreLoginProvider", false, loader);
            Class<?> type = Class.forName("xyz.kyngs.librelogin.api.LibreLoginPlugin", false, loader);
            Class<?> platformType = Class.forName("xyz.kyngs.librelogin.api.PlatformHandle", false, loader);
            Class<?> auth = Class.forName("xyz.kyngs.librelogin.api.authorization.AuthorizationProvider", false, loader);
            Class<?> read = Class.forName("xyz.kyngs.librelogin.api.database.ReadDatabaseProvider", false, loader);
            Class<?> write = Class.forName("xyz.kyngs.librelogin.api.database.WriteDatabaseProvider", false, loader);
            Class<?> user = Class.forName("xyz.kyngs.librelogin.api.database.User", false, loader);
            Class<?> crypto = Class.forName("xyz.kyngs.librelogin.api.crypto.CryptoProvider", false, loader);
            Class<?> hashed = Class.forName("xyz.kyngs.librelogin.api.crypto.HashedPassword", false, loader);
            if (!provider.isInstance(installed)) throw new IllegalStateException("LibreLogin API unavailable");
            api = provider.getMethod("getLibreLogin").invoke(installed);
            Object platform = type.getMethod("getPlatformHandle").invoke(api);
            if (!"paper".equals(platformType.getMethod("getPlatformIdentifier").invoke(platform))
                    || platformType.getMethod("getPlayerClass").invoke(platform) != Player.class
                    || !Boolean.FALSE.equals(type.getMethod("multiProxyEnabled").invoke(api))) throw new IllegalStateException("Unsupported LibreLogin platform");
            database = type.getMethod("getDatabaseProvider").invoke(api); authorization = type.getMethod("getAuthorizationProvider").invoke(api);
            if (!read.isInstance(database) || !write.isInstance(database)) throw new IllegalStateException("LibreLogin database unavailable");
            authorized = auth.getMethod("isAuthorized", Object.class); awaiting = auth.getMethod("isAwaiting2FA", Object.class);
            byUUID = read.getMethod("getByUUID", UUID.class); byName = read.getMethod("getByName", String.class);
            userUUID = user.getMethod("getUuid"); userName = user.getMethod("getLastNickname"); registered = user.getMethod("isRegistered");
            joined = user.getMethod("getJoinDate"); setPassword = user.getMethod("setHashedPassword", hashed); getPassword = user.getMethod("getHashedPassword");
            setIp = user.getMethod("setIp", String.class); setLastAuthentication = user.getMethod("setLastAuthentication", Timestamp.class);
            secret = user.getMethod("getSecret"); totpProvider = type.getMethod("getTOTPProvider");
            update = write.getMethod("updateUser", user); defaultCrypto = type.getMethod("getDefaultCryptoProvider"); validPassword = type.getMethod("validPassword", String.class);
            present = type.getMethod("isPresent", UUID.class); getPlayer = type.getMethod("getPlayerForUUID", UUID.class);
            hash = crypto.getMethod("createHash", String.class); matches = crypto.getMethod("matches", String.class, hashed);
            cryptoFor = type.getMethod("getCryptoProvider", String.class); hashAlgo = hashed.getMethod("algo");
        }
        boolean authenticated(Player player) throws Exception {
            return getPlayer.invoke(api, BukkitCompatibility.identity(player)) == player && Boolean.TRUE.equals(authorized.invoke(authorization, player))
                && Boolean.FALSE.equals(awaiting.invoke(authorization, player));
        }
        private boolean same(Object user, UUID identity, String name) throws Exception {
            return user != null && identity.equals(userUUID.invoke(user)) && name.equals(userName.invoke(user)) && Boolean.TRUE.equals(registered.invoke(user));
        }
        String fingerprint(UUID identity, String name) throws Exception {
            Object user = byUUID.invoke(database, identity), named = byName.invoke(database, name);
            if (!same(user, identity, name) || !same(named, identity, name)) return null;
            Timestamp first = (Timestamp) joined.invoke(user), second = (Timestamp) joined.invoke(named);
            return first != null && first.equals(second) ? first.toInstant().toString() : null;
        }
        String proofFingerprint(UUID identity, String name) throws Exception {
            String fingerprint = fingerprint(identity, name);
            if (fingerprint == null) return null;
            Object user = byUUID.invoke(database, identity), named = byName.invoke(database, name);
            // Paper 0.24 lacks a TOTP verifier and can mark migrated TOTP accounts authorized using only a password.
            if ((secret.invoke(user) != null || secret.invoke(named) != null) && totpProvider.invoke(api) == null) return null;
            return fingerprint;
        }
        boolean reset(UUID identity, String name, String password, long deadline) throws Exception {
            if (Boolean.TRUE.equals(present.invoke(api, identity)) || getPlayer.invoke(api, identity) != null
                    || !Boolean.TRUE.equals(validPassword.invoke(api, password))) return false;
            Object user = byUUID.invoke(database, identity);
            if (!same(user, identity, name)) return false;
            String birth = fingerprint(identity, name);
            if (birth == null) return false;
            Object provider = defaultCrypto.invoke(api), passwordHash = hash.invoke(provider, password);
            if (passwordHash == null || System.currentTimeMillis() >= deadline || Boolean.TRUE.equals(present.invoke(api, identity))) return false;
            if (!birth.equals(fingerprint(identity, name))) return false;
            user = byUUID.invoke(database, identity);
            if (!same(user, identity, name) || !birth.equals(((Timestamp) joined.invoke(user)).toInstant().toString())) return false;
            setPassword.invoke(user, passwordHash);
            setIp.invoke(user, new Object[]{null}); setLastAuthentication.invoke(user, new Object[]{null});
            update.invoke(database, user);
            Object saved = byUUID.invoke(database, identity);
            if (!same(saved, identity, name)) return false;
            Object savedHash = getPassword.invoke(saved);
            if (savedHash == null) return false;
            Object savedProvider = cryptoFor.invoke(api, hashAlgo.invoke(savedHash));
            return savedProvider != null && Boolean.TRUE.equals(matches.invoke(savedProvider, password, savedHash));
        }
    }

    /** Records account creation as well as UUID so a deleted/recreated native account loses reset permission. */
    static final class Ownership {
        private final Path path;
        private final Properties records = new Properties();
        Ownership(Path path) throws IOException {
            this.path = path;
            if (Files.exists(path)) {
                if (Files.size(path) > 1024 * 1024) throw new IOException("Reset proof file too large");
                try (Reader reader = Files.newBufferedReader(path)) { records.load(reader); }
            }
        }
        synchronized boolean matches(String engine, String name, UUID identity, String fingerprint) {
            return (identity.toString() + "|" + fingerprint).equals(records.getProperty(engine + ":" + name.toLowerCase(Locale.ROOT)));
        }
        synchronized void remember(String engine, String name, UUID identity, String fingerprint) throws IOException {
            String key = engine + ":" + name.toLowerCase(Locale.ROOT), value = identity.toString() + "|" + fingerprint;
            if (value.equals(records.getProperty(key))) return;
            if (records.size() >= 10000 && !records.containsKey(key)) throw new IOException("Reset proof capacity reached");
            Properties next = new Properties(); next.putAll(records); next.setProperty(key, value);
            Files.createDirectories(path.getParent()); Path temporary = path.resolveSibling(path.getFileName() + ".tmp");
            try (Writer writer = Files.newBufferedWriter(temporary)) { next.store(writer, "Myrinbot native authenticated reset proofs; no passwords"); }
            try { Files.move(temporary, path, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
            catch (AtomicMoveNotSupportedException unsupported) { Files.move(temporary, path, StandardCopyOption.REPLACE_EXISTING); }
            records.clear(); records.putAll(next);
        }
    }
}
