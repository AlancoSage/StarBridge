package cn.starbridge.velocity;

import com.velocitypowered.api.proxy.Player;
import java.lang.reflect.Method;
import java.lang.reflect.Field;
import java.util.Collection;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

/** LimboAuth 1.1.14 public model/DAO API, without bundling any LimboAuth implementation. */
final class LimboAuthAdapter implements NativeAuth {
    private final Object plugin, dao;
    private final Class<?> model;
    private final Class<?> settings;
    private final Field settingsMain, minimum, maximum, strength;
    private final Method query, uuid, nickname, hash, totp, genHash, needAuth, pending, authenticating,
        removeCache, builder, where, eq, and, column, update, registered, unsafePasswords;

    LimboAuthAdapter(Object plugin) throws Exception {
        this.plugin = plugin;
        ClassLoader loader = plugin.getClass().getClassLoader();
        Class<?> main = Class.forName("net.elytrium.limboauth.LimboAuth", false, loader);
        settings = Class.forName("net.elytrium.limboauth.Settings", false, loader);
        settingsMain = settings.getField("MAIN");
        Class<?> options = Class.forName("net.elytrium.limboauth.Settings$MAIN", false, loader);
        minimum = options.getField("MIN_PASSWORD_LENGTH"); maximum = options.getField("MAX_PASSWORD_LENGTH");
        strength = options.getField("CHECK_PASSWORD_STRENGTH");
        unsafePasswords = main.getMethod("getUnsafePasswords");
        model = Class.forName("net.elytrium.limboauth.model.RegisteredPlayer", false, loader);
        Method daoMethod = main.getMethod("getPlayerDao");
        Class<?> daoType = daoMethod.getReturnType();
        dao = daoMethod.invoke(plugin);
        if (dao == null) throw new IllegalStateException("DAO not initialized");
        query = daoType.getMethod("queryForEq", String.class, Object.class);
        uuid = model.getMethod("getUuid"); nickname = model.getMethod("getNickname");
        hash = model.getMethod("getHash"); totp = model.getMethod("getTotpToken");
        registered = model.getMethod("getRegDate");
        genHash = model.getMethod("genHash", String.class);
        needAuth = main.getMethod("needAuth", Player.class);
        pending = main.getMethod("getPendingLogins");
        Method authenticatingMethod;
        try { authenticatingMethod = main.getMethod("getAuthenticatingPlayer", String.class); }
        catch (NoSuchMethodException released114) { authenticatingMethod = null; }
        authenticating = authenticatingMethod;
        removeCache = main.getMethod("removePlayerFromCache", String.class);
        builder = daoType.getMethod("updateBuilder");
        Class<?> builderType = builder.getReturnType();
        where = builderType.getMethod("where");
        Class<?> whereType = where.getReturnType();
        eq = whereType.getMethod("eq", String.class, Object.class);
        and = whereType.getMethod("and");
        column = builderType.getMethod("updateColumnValue", String.class, Object.class);
        update = builderType.getMethod("update");
    }

    public String id() { return "limboauth"; }

    private Object find(String name) throws Exception {
        Object found = query.invoke(dao, "LOWERCASENICKNAME", name.toLowerCase(Locale.ROOT));
        if (!(found instanceof List<?>)) throw new IllegalStateException("unsupported query response");
        List<?> rows = (List<?>) found;
        if (rows.size() > 1) throw new IllegalStateException("ambiguous account");
        return rows.isEmpty() ? null : rows.get(0);
    }

    private boolean same(Object account, UUID identity, String name) throws Exception {
        return account != null && model.isInstance(account) && name.equals(nickname.invoke(account))
            && identity.toString().equals(uuid.invoke(account))
            && hash.invoke(account) instanceof String && !((String) hash.invoke(account)).isEmpty();
    }

    public boolean authenticated(Player player) throws Exception {
        String name = player.getUsername();
        Object waiting = pending.invoke(plugin);
        return player.isActive() && player.getCurrentServer().isPresent()
            && Boolean.FALSE.equals(needAuth.invoke(plugin, player))
            && (authenticating == null || authenticating.invoke(plugin, name) == null)
            && waiting instanceof Collection<?> && !((Collection<?>) waiting).contains(name)
            && !((Collection<?>) waiting).contains(name.toLowerCase(Locale.ROOT))
            && same(find(name), player.getUniqueId(), name);
    }

    private String fingerprint(Object account, UUID identity) throws Exception {
        Object born = registered.invoke(account);
        return born instanceof Long && ((Long) born) > 0 ? NativeAuth.fingerprint(id(), identity, born.toString()) : "";
    }

    public String account(Player player) throws Exception {
        if (!authenticated(player)) return "";
        return fingerprint(find(player.getUsername()), player.getUniqueId());
    }

    public String reset(UUID identity, String name, String accountId, String password, Claim claim) throws Exception {
        Object account = find(name);
        if (account == null) return "not_found";
        if (!same(account, identity, name)) return "identity_mismatch";
        if (accountId.isEmpty() || !accountId.equals(fingerprint(account, identity))) return "identity_mismatch";
        Object options = settingsMain.get(settings.getField("IMP").get(null));
        if (options == null || password.length() < minimum.getInt(options) || password.length() > maximum.getInt(options)) return "failed";
        if (strength.getBoolean(options)) {
            Object unsafe = unsafePasswords.invoke(plugin);
            if (!(unsafe instanceof Collection<?>) || ((Collection<?>) unsafe).contains(password)) return "failed";
        }
        String oldHash = (String) hash.invoke(account);
        Object oldTotp = totp.invoke(account);
        Object newHash = genHash.invoke(null, password);
        if (!(newHash instanceof String) || ((String) newHash).isEmpty()) return "failed";
        if (!claim.allowed()) return "expired";
        Object fresh = find(name);
        if (!same(fresh, identity, name) || !oldHash.equals(hash.invoke(fresh))
            || !accountId.equals(fingerprint(fresh, identity))) return "identity_mismatch";
        Object change = builder.invoke(dao), condition = where.invoke(change);
        eq.invoke(condition, "LOWERCASENICKNAME", name.toLowerCase(Locale.ROOT));
        and.invoke(condition); eq.invoke(condition, "NICKNAME", name);
        and.invoke(condition); eq.invoke(condition, "UUID", identity.toString());
        and.invoke(condition); eq.invoke(condition, "HASH", oldHash);
        and.invoke(condition); eq.invoke(condition, "REGDATE", registered.invoke(fresh));
        column.invoke(change, "HASH", newHash);
        column.invoke(change, "ISSUEDTIME", System.currentTimeMillis());
        if (!Integer.valueOf(1).equals(update.invoke(change))) return "identity_mismatch";
        removeCache.invoke(plugin, name);
        Object saved = find(name);
        if (!same(saved, identity, name) || !newHash.equals(hash.invoke(saved))
            || !java.util.Objects.equals(oldTotp, totp.invoke(saved))) return "failed";
        return "success";
    }
}
