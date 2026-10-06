package cn.starbridge;

import java.lang.reflect.Method;
import java.security.SecureRandom;
import java.util.Base64;
import org.bukkit.entity.Player;
import org.bukkit.plugin.Plugin;
import java.nio.file.*;
import java.io.*;
import java.util.*;

/** Optional public API v3 integration. No AuthMe classes or user passwords are bundled. */
final class AuthMeLink {
    private final Object api;
    private final Method authenticated, registered, login, register, logout;
    private final Properties managed = new Properties();
    private final Path path;
    AuthMeLink(Plugin authMe, Plugin owner) throws ReflectiveOperationException, IOException {
        path = owner.getDataFolder().toPath().resolve("authme-links.properties");
        if (Files.exists(path)) {
            if (Files.size(path) > 1024 * 1024) throw new IOException("AuthMe links file too large");
            try (Reader reader = Files.newBufferedReader(path)) { managed.load(reader); }
        }
        Class<?> type = Class.forName("fr.xephi.authme.api.v3.AuthMeApi", true, authMe.getClass().getClassLoader());
        api = type.getMethod("getInstance").invoke(null);
        if (api == null) throw new IllegalStateException("AuthMe API is not ready");
        authenticated = type.getMethod("isAuthenticated", Player.class);
        registered = type.getMethod("isRegistered", String.class);
        login = type.getMethod("forceLogin", Player.class);
        register = type.getMethod("forceRegister", Player.class, String.class, boolean.class);
        logout = type.getMethod("forceLogout", Player.class);
    }
    boolean authenticated(Player player) throws ReflectiveOperationException {
        return Boolean.TRUE.equals(authenticated.invoke(api, player));
    }
    boolean start(Player player) throws ReflectiveOperationException {
        if (authenticated(player)) return true;
        if (Boolean.TRUE.equals(registered.invoke(api, player.getName()))) {
            // A public website name claim is not proof of ownership of an older AuthMe account.
            if (!player.getUniqueId().toString().equals(managed.getProperty(player.getName().toLowerCase(Locale.ROOT)))) return false;
            login.invoke(api, player);
        }
        else {
            byte[] bytes = new byte[18]; new SecureRandom().nextBytes(bytes);
            // AuthMe owns this internal credential. The user's password stays in StarBridge.
            register.invoke(api, player, Base64.getUrlEncoder().withoutPadding().encodeToString(bytes), true);
        }
        return true;
    }
    void remember(Player player) throws IOException {
        String name = player.getName().toLowerCase(Locale.ROOT), identity = player.getUniqueId().toString();
        if (identity.equals(managed.getProperty(name))) return;
        if (managed.size() >= 10000 && !managed.containsKey(name)) throw new IOException("AuthMe link capacity reached");
        Properties next = new Properties(); next.putAll(managed); next.setProperty(name, identity);
        Files.createDirectories(path.getParent());
        Path temporary = path.resolveSibling(path.getFileName() + ".tmp");
        try (Writer writer = Files.newBufferedWriter(temporary)) { next.store(writer, "StarBridge verified AuthMe identities; no passwords"); }
        try { Files.move(temporary, path, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
        catch (AtomicMoveNotSupportedException ex) { Files.move(temporary, path, StandardCopyOption.REPLACE_EXISTING); }
        managed.clear(); managed.putAll(next);
    }
    void logout(Player player) throws ReflectiveOperationException { logout.invoke(api, player); }
}
