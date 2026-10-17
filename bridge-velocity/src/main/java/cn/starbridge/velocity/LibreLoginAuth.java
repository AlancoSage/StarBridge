package cn.starbridge.velocity;

import com.velocitypowered.api.proxy.Player;
import java.lang.reflect.Method;
import java.sql.Timestamp;
import java.util.UUID;

/** LibreLogin 0.24 public API; optional plugin classes are resolved in their own class loader. */
final class LibreLoginAuth implements NativeAuth {
    private final Object api, database, authorization, crypto;
    private final Method byUUID, byName, uuid, nickname, registered, hashed, secret, authorized,
        awaiting, playerForUUID, present, validPassword, createHash, matches, setHash, setIp,
        setAuthentication, update, joined;

    LibreLoginAuth(Object plugin) throws Exception {
        ClassLoader loader = plugin.getClass().getClassLoader();
        Class<?> provider = Class.forName("xyz.kyngs.librelogin.api.provider.LibreLoginProvider", false, loader);
        Class<?> main = Class.forName("xyz.kyngs.librelogin.api.LibreLoginPlugin", false, loader);
        Class<?> platform = Class.forName("xyz.kyngs.librelogin.api.PlatformHandle", false, loader);
        Class<?> read = Class.forName("xyz.kyngs.librelogin.api.database.ReadDatabaseProvider", false, loader);
        Class<?> write = Class.forName("xyz.kyngs.librelogin.api.database.WriteDatabaseProvider", false, loader);
        Class<?> user = Class.forName("xyz.kyngs.librelogin.api.database.User", false, loader);
        Class<?> auth = Class.forName("xyz.kyngs.librelogin.api.authorization.AuthorizationProvider", false, loader);
        Class<?> hash = Class.forName("xyz.kyngs.librelogin.api.crypto.HashedPassword", false, loader);
        Class<?> crypt = Class.forName("xyz.kyngs.librelogin.api.crypto.CryptoProvider", false, loader);
        if (!provider.isInstance(plugin)) throw new IllegalStateException("unsupported provider");
        api = provider.getMethod("getLibreLogin").invoke(plugin);
        Object handle = main.getMethod("getPlatformHandle").invoke(api);
        if (!"velocity".equals(platform.getMethod("getPlatformIdentifier").invoke(handle))
            || platform.getMethod("getPlayerClass").invoke(handle) != Player.class
            || !Boolean.FALSE.equals(main.getMethod("multiProxyEnabled").invoke(api)))
            throw new IllegalStateException("only a single Velocity proxy is supported");
        database = main.getMethod("getDatabaseProvider").invoke(api);
        authorization = main.getMethod("getAuthorizationProvider").invoke(api);
        crypto = main.getMethod("getDefaultCryptoProvider").invoke(api);
        byUUID = read.getMethod("getByUUID", UUID.class);
        byName = read.getMethod("getByName", String.class);
        uuid = user.getMethod("getUuid"); nickname = user.getMethod("getLastNickname");
        registered = user.getMethod("isRegistered"); hashed = user.getMethod("getHashedPassword");
        secret = user.getMethod("getSecret");
        joined = user.getMethod("getJoinDate");
        authorized = auth.getMethod("isAuthorized", Object.class);
        awaiting = auth.getMethod("isAwaiting2FA", Object.class);
        playerForUUID = main.getMethod("getPlayerForUUID", UUID.class);
        present = main.getMethod("isPresent", UUID.class);
        validPassword = main.getMethod("validPassword", String.class);
        createHash = crypt.getMethod("createHash", String.class);
        matches = crypt.getMethod("matches", String.class, hash);
        setHash = user.getMethod("setHashedPassword", hash);
        setIp = user.getMethod("setIp", String.class);
        setAuthentication = user.getMethod("setLastAuthentication", Timestamp.class);
        update = write.getMethod("updateUser", user);
    }

    public String id() { return "librelogin"; }

    private boolean same(Object user, UUID identity, String name) throws Exception {
        return user != null && identity.equals(uuid.invoke(user)) && name.equals(nickname.invoke(user))
            && Boolean.TRUE.equals(registered.invoke(user)) && hashed.invoke(user) != null;
    }

    public boolean authenticated(Player player) throws Exception {
        UUID identity = player.getUniqueId(); String name = player.getUsername();
        return player.isActive() && player.getCurrentServer().isPresent()
            && playerForUUID.invoke(api, identity) == player
            && Boolean.TRUE.equals(authorized.invoke(authorization, player))
            && Boolean.FALSE.equals(awaiting.invoke(authorization, player))
            && same(byUUID.invoke(database, identity), identity, name)
            && same(byName.invoke(database, name), identity, name);
    }

    private String fingerprint(Object user, UUID identity) throws Exception {
        Object born = joined.invoke(user);
        return born instanceof Timestamp ? NativeAuth.fingerprint(id(), identity, Long.toString(((Timestamp) born).getTime())) : "";
    }

    public String account(Player player) throws Exception {
        if (!authenticated(player)) return "";
        return fingerprint(byUUID.invoke(database, player.getUniqueId()), player.getUniqueId());
    }

    public String reset(UUID identity, String name, String account, String password, Claim claim) throws Exception {
        Object user = byUUID.invoke(database, identity), named = byName.invoke(database, name);
        if (user == null && named == null) return "not_found";
        if (!same(user, identity, name) || !same(named, identity, name)) return "identity_mismatch";
        if (account.isEmpty() || !account.equals(fingerprint(user, identity))) return "identity_mismatch";
        if (Boolean.TRUE.equals(present.invoke(api, identity))) return "online";
        if (!Boolean.TRUE.equals(validPassword.invoke(api, password))) return "failed";
        Object newHash = createHash.invoke(crypto, password);
        if (newHash == null || !Boolean.TRUE.equals(matches.invoke(crypto, password, newHash))) return "failed";
        // The coordinator rechecks the QQ binding and route immediately before any mutation.
        if (!claim.allowed()) return "expired";
        if (Boolean.TRUE.equals(present.invoke(api, identity))) return "online";
        Object current = byUUID.invoke(database, identity), currentName = byName.invoke(database, name);
        if (!same(current, identity, name) || !same(currentName, identity, name)
            || !account.equals(fingerprint(current, identity))) return "identity_mismatch";
        Object previousSecret = secret.invoke(current);
        setHash.invoke(current, newHash);
        // LibreLogin's normal session bypass checks these fields. Clear both without disabling TOTP.
        setIp.invoke(current, (Object) null);
        setAuthentication.invoke(current, (Object) null);
        update.invoke(database, current);
        Object saved = byUUID.invoke(database, identity);
        if (!same(saved, identity, name) || !java.util.Objects.equals(previousSecret, secret.invoke(saved))
            || !Boolean.TRUE.equals(matches.invoke(crypto, password, hashed.invoke(saved)))) return "failed";
        return "success";
    }
}
