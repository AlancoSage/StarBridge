package cn.starbridge;

import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Locale;
import java.util.Properties;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import org.bukkit.entity.Player;
import org.bukkit.plugin.Plugin;

/** Per-provider ownership proofs. Never stores credentials or mixes plugin trust. */
final class VerifiedLoginAccounts {
    private static final class SharedRecords { Properties records = new Properties(); }
    private static final ConcurrentMap<Path, SharedRecords> RECORDS = new ConcurrentHashMap<Path, SharedRecords>();
    private final Path path;
    private final SharedRecords shared;

    VerifiedLoginAccounts(Plugin owner, String provider) throws IOException {
        if (!provider.matches("[a-z]{3,32}")) throw new IllegalArgumentException("Invalid login provider");
        path = owner.getDataFolder().toPath().resolve(provider + "-links.properties").toAbsolutePath().normalize();
        SharedRecords existing = RECORDS.putIfAbsent(path, new SharedRecords());
        shared = existing == null ? RECORDS.get(path) : existing;
        synchronized (shared) { shared.records = read(); }
    }

    private Properties read() throws IOException {
        Properties records = new Properties();
        if (Files.exists(path)) {
            if (Files.size(path) > 1024 * 1024) throw new IOException("Login ownership file too large");
            try (Reader reader = Files.newBufferedReader(path)) { records.load(reader); }
        }
        return records;
    }

    boolean matches(Player player) throws IOException {
        synchronized (shared) {
            return BukkitCompatibility.identity(player).toString().equals(
                shared.records.getProperty(player.getName().toLowerCase(Locale.ROOT)));
        }
    }

    void remember(Player player) throws IOException {
        remember(BukkitCompatibility.identity(player), player.getName());
    }

    void remember(UUID playerIdentity, String playerName) throws IOException {
        synchronized (shared) {
            String name = playerName.toLowerCase(Locale.ROOT);
            String identity = playerIdentity.toString();
            // A closed adapter's callback can still record completed native registration.
            // Merge the latest file without overwriting a reopened adapter's records.
            Properties records = read();
            if (identity.equals(records.getProperty(name))) { shared.records = records; return; }
            if (records.size() >= 10000 && !records.containsKey(name)) throw new IOException("Login ownership capacity reached");
            Properties next = new Properties(); next.putAll(records); next.setProperty(name, identity);
            Files.createDirectories(path.getParent());
            Path temporary = path.resolveSibling(path.getFileName() + ".tmp");
            try (Writer writer = Files.newBufferedWriter(temporary)) { next.store(writer, "Myrinbot verified identities; no passwords"); }
            try { Files.move(temporary, path, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
            catch (AtomicMoveNotSupportedException ex) { Files.move(temporary, path, StandardCopyOption.REPLACE_EXISTING); }
            shared.records = next;
        }
    }

    static String credential(int min, int max) {
        if (min < 1 || max < min || min > 128) throw new IllegalStateException("Unsupported internal credential length");
        int length = Math.min(max, Math.max(24, min));
        byte[] bytes = new byte[(length * 3 + 3) / 4 + 3]; new SecureRandom().nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes).substring(0, length);
    }
}
