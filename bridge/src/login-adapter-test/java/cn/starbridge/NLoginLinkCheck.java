package cn.starbridge;

import com.nickuc.login.api.MockNLogin;
import com.nickuc.login.api.enums.ImplementationType;
import java.io.File;
import java.io.IOException;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.util.UUID;
import java.util.logging.Logger;
import org.bukkit.Bukkit;
import org.bukkit.Server;
import org.bukkit.configuration.file.YamlConfiguration;
import org.bukkit.entity.Player;
import org.bukkit.plugin.Plugin;

/** Adapter contract checks: native proof, immutable identities, factors, failure paths. */
public final class NLoginLinkCheck {
    private static int count;
    private static boolean primary = true, enabled = true;
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
    private static void check(boolean result, String message) {
        if (!result) throw new AssertionError(message);
        count++;
    }
    private interface Attempt { void run() throws Exception; }
    private static void fails(Attempt attempt, String message) throws Exception {
        try { attempt.run(); throw new AssertionError(message); }
        catch (IOException | ReflectiveOperationException expected) { count++; }
    }
    public static void main(String[] arguments) throws Exception {
        Server server = proxy(Server.class, (self, method, values) -> {
            if (method.getName().equals("isPrimaryThread")) return primary;
            if (method.getName().equals("getLogger")) return Logger.getLogger("nLogin-adapter-test");
            if (method.getName().equals("getName") || method.getName().equals("getVersion")
                || method.getName().equals("getBukkitVersion")) return "nLogin isolated test";
            return fallback(method);
        });
        Bukkit.setServer(server);
        File folder = Files.createTempDirectory("starbridge-nlogin-check").toFile();
        YamlConfiguration config = new YamlConfiguration();
        config.set("security.passwords.small", 5);
        config.set("security.passwords.large", 32);
        Plugin plugin = proxy(Plugin.class, (self, method, values) -> {
            if (method.getName().equals("isEnabled")) return enabled;
            if (method.getName().equals("getDataFolder")) return folder;
            if (method.getName().equals("getConfig")) return config;
            return fallback(method);
        });
        UUID uuid = UUID.randomUUID();
        MockNLogin.registrationId = uuid;
        Player player = proxy(Player.class, (self, method, values) -> {
            if (method.getName().equals("getUniqueId")) return uuid;
            if (method.getName().equals("getName")) return "Steve";
            if (method.getName().equals("getAddress")) return new InetSocketAddress("127.0.0.1", 25565);
            return fallback(method);
        });
        NLoginLink adapter = new NLoginLink(plugin, plugin);
        check(adapter.id().equals("nlogin"), "Stable provider id");
        check(!adapter.authenticated(player), "Unregistered cannot authenticate");
        check(!adapter.start(player), "Native registration must be completed by the player");
        check(MockNLogin.registrations == 0 && MockNLogin.requests == 0, "Adapter never creates a credential or requests native authentication");
        fails(() -> adapter.remember(player), "Unregistered cannot establish native proof");
        MockNLogin.accounts.put("Steve", uuid);
        check(!adapter.start(player), "Existing native account requires its original proof");
        check(!adapter.authenticated(player), "Pending second factor stays locked");
        fails(() -> adapter.remember(player), "Pending factor cannot become native proof");
        check(!folder.toPath().resolve("nlogin-links.properties").toFile().exists(), "Adapter stores neither credentials nor cached bypass proof");
        MockNLogin.api.requestLogin(com.nickuc.login.api.types.Identity.ofKnownName("Steve"), plugin);
        check(!adapter.start(player), "A public native login request is not authentication proof");
        MockNLogin.authenticated.add("Steve");
        check(adapter.start(player) && adapter.authenticated(player), "Only completed native authentication opens the native gate");
        adapter.remember(player);
        count++;
        MockNLogin.authenticated.clear();
        check(!adapter.start(player), "Each connection needs native authentication again");
        check(!new NLoginLink(plugin, plugin).start(player), "Adapter restart never reuses previous native authentication");
        check(MockNLogin.registrations == 0 && MockNLogin.requests == 1, "Retries never change passwords or call native requestLogin");
        MockNLogin.authenticated.add("Steve");
        MockNLogin.accounts.put("Steve", UUID.randomUUID());
        fails(() -> adapter.start(player), "Recreated native identity cannot reuse old proof");
        fails(() -> adapter.authenticated(player), "Wrong native identity cannot authenticate");
        MockNLogin.accounts.put("Steve", uuid);
        MockNLogin.mode = ImplementationType.PROXY;
        fails(() -> adapter.start(player), "Proxy API unsupported");
        MockNLogin.mode = ImplementationType.NATIVE;
        MockNLogin.ready = false;
        fails(() -> adapter.authenticated(player), "API not ready fails closed");
        MockNLogin.ready = true;
        enabled = false;
        fails(() -> adapter.start(player), "Disabled plugin fails closed");
        enabled = true;
        primary = false;
        fails(() -> adapter.start(player), "Worker API use fails closed");
        primary = true;
        fails(() -> adapter.logout(player), "Missing public logout requires reconnect");
        check(adapter.ownershipCommands().contains("nlogin:login")
            && adapter.ownershipCommands().contains("nlogin:email")
            && adapter.ownershipCommands().contains("nlogin:register")
            && adapter.ownershipCommands().contains("login")
            && adapter.ownershipCommands().contains("register")
            && adapter.ownershipCommands().contains("email")
            && !adapter.ownershipCommands().contains("nlogin:changepassword")
            && !adapter.ownershipCommands().contains("changepassword"), "Native registration and factor commands have a fixed scope");
        check(adapter.ownershipPrompt().contains("/starbridge:login")
            && adapter.ownershipPrompt().contains("/starbridge:ql")
            && adapter.ownershipPrompt().contains("/register"), "Two-stage prompt distinguishes website proof from native proof");
        MockNLogin.accounts.clear();
        check(!adapter.authenticated(player), "Deleted native account grants no session");
        System.out.println("nLogin adapter: " + count + " checks passed");
    }
}
