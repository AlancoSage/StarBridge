package cn.starbridge;

import java.io.IOException;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.bukkit.Bukkit;
import org.bukkit.entity.Player;
import org.bukkit.plugin.Plugin;

/** Reflects the public nLogin Identity API. Native authentication retains its own extra factors. */
final class NLoginLink implements LoginLink {
    private final Plugin installed, owner;
    private final Object api;
    private final Class<?> identityType, accountType;
    private final Method available, implementation, identity, account, authenticated, uniqueId;

    NLoginLink(Plugin installed, Plugin owner) throws ReflectiveOperationException, IOException {
        this.installed = installed;
        this.owner = owner;
        if (BridgeScheduler.isFolia()) throw new IOException("nLogin API region-thread contract has not been verified");
        ClassLoader loader = installed.getClass().getClassLoader();
        Class<?> apiType = Class.forName("com.nickuc.login.api.nLoginAPI", true, loader);
        identityType = Class.forName("com.nickuc.login.api.types.Identity", true, loader);
        accountType = Class.forName("com.nickuc.login.api.types.AccountData", true, loader);
        api = apiType.getMethod("getApi").invoke(null);
        if (api == null || !apiType.isInstance(api)) throw new IOException("nLogin API is not ready");
        available = apiType.getMethod("isAvailable");
        implementation = apiType.getMethod("getImplementationType");
        identity = identityType.getMethod("ofKnownName", String.class);
        account = apiType.getMethod("getAccount", identityType);
        authenticated = apiType.getMethod("isAuthenticated", identityType);
        uniqueId = accountType.getMethod("getUniqueId");
        check();
    }

    public String id() { return "nlogin"; }
    public String displayName() { return "nLogin"; }
    public Set<String> ownershipCommands() {
        return Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
            "login", "l", "log", "register", "reg", "r", "email", "discord",
            "nlogin:login", "nlogin:l", "nlogin:log", "nlogin:register", "nlogin:reg", "nlogin:r",
            "nlogin:email", "nlogin:discord")));
    }
    public String ownershipPrompt() {
        return "nLogin 需要两步验证：先使用 /starbridge:login <网站密码> 或 /starbridge:ql 完成Myrinbot登录，再使用 /login <nLogin 密码>；新账号使用 /register <密码> <确认密码>，并完成 nLogin 要求的二次验证。";
    }

    private void check() throws ReflectiveOperationException, IOException {
        if (BridgeScheduler.isFolia() || !Bukkit.isPrimaryThread())
            throw new IOException("nLogin adapter requires the Bukkit server thread");
        if (!installed.isEnabled() || !owner.isEnabled() || !Boolean.TRUE.equals(available.invoke(api)))
            throw new IOException("nLogin API is not ready");
        Object mode = implementation.invoke(api);
        if (!(mode instanceof Enum) || !"NATIVE".equals(((Enum<?>) mode).name()))
            throw new IOException("nLogin must run on the same backend server");
    }

    private Object identity(Player player) throws ReflectiveOperationException, IOException {
        check();
        Object value = identity.invoke(null, player.getName());
        if (value == null || !identityType.isInstance(value)) throw new IOException("nLogin identity is unavailable");
        return value;
    }

    private Object account(Player player, Object identity) throws ReflectiveOperationException, IOException {
        Object value = account.invoke(api, identity);
        if (!(value instanceof Optional)) throw new IOException("Invalid nLogin account response");
        Optional<?> record = (Optional<?>) value;
        if (!record.isPresent()) return null;
        Object data = record.get();
        if (!accountType.isInstance(data)) throw new IOException("Invalid nLogin account response");
        Object stored = uniqueId.invoke(data);
        if (!(stored instanceof Optional)) throw new IOException("Invalid nLogin account identity");
        Optional<?> uuid = (Optional<?>) stored;
        if (!uuid.isPresent() || !(uuid.get() instanceof UUID)
            || !BukkitCompatibility.identity(player).equals(uuid.get()))
            throw new IOException("nLogin account identity does not match this connection");
        return data;
    }

    public boolean authenticated(Player player) throws ReflectiveOperationException, IOException {
        Object identity = identity(player);
        return account(player, identity) != null && Boolean.TRUE.equals(authenticated.invoke(api, identity));
    }

    public boolean start(Player player) throws ReflectiveOperationException, IOException {
        // A public requestLogin request is not a confirmed native authentication result.
        // Observe native proof every connection; never create an unknown password or force a login.
        return authenticated(player);
    }

    public void remember(Player player) throws IOException {
        try {
            if (!authenticated(player)) throw new IOException("nLogin has not completed authentication");
        } catch (ReflectiveOperationException ex) {
            throw new IOException("Cannot confirm nLogin account ownership", ex);
        }
    }

    public void logout(Player player) throws IOException {
        // nLogin exposes no public logout API; its official AuthMe compatibility method is also a no-op.
        throw new IOException("nLogin requires disconnecting and reconnecting to end the native session");
    }
}
