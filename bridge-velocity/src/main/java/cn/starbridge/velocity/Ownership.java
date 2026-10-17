package cn.starbridge.velocity;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.Properties;
import java.util.UUID;

/** Authenticated account birth proofs. Contains no passwords, QQ ids, tokens or session credentials. */
final class Ownership {
    private final Path file;
    private final Properties records = new Properties();
    Ownership(Path directory) throws IOException {
        file = directory.resolve("password-reset-proofs.properties");
        if (Files.exists(file)) {
            if (!Files.isRegularFile(file) || Files.size(file) > 1024 * 1024) throw new IOException("native proof file too large");
            try (Reader input = Files.newBufferedReader(file, StandardCharsets.UTF_8)) { records.load(input); }
            if (records.size() > 10000) throw new IOException("too many native proofs");
        }
    }
    void record(String engine, UUID uuid, String name, String account) throws IOException {
        if (!account.matches("[a-f0-9]{64}")) throw new IOException("invalid native proof");
        String key = engine + ":" + name, value = uuid + "|" + account;
        if (!records.containsKey(key) && records.size() >= 10000) throw new IOException("native proof limit reached");
        Object old = records.setProperty(key, value);
        Path temporary = file.resolveSibling(file.getFileName() + ".new");
        try {
            try (Writer output = Files.newBufferedWriter(temporary, StandardCharsets.UTF_8)) {
                records.store(output, "Verified native account birth proofs; no secrets");
            }
            if (Files.size(temporary) > 1024 * 1024) throw new IOException("native proof file limit reached");
            try { Files.move(temporary, file, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
            catch (AtomicMoveNotSupportedException unsupported) { Files.move(temporary, file, StandardCopyOption.REPLACE_EXISTING); }
        } catch (IOException failure) {
            if (old == null) records.remove(key); else records.put(key, old);
            throw failure;
        }
    }
    String account(String engine, UUID uuid, String name) {
        String value = records.getProperty(engine + ":" + name, ""), prefix = uuid + "|";
        return value.startsWith(prefix) && value.substring(prefix.length()).matches("[a-f0-9]{64}")
            ? value.substring(prefix.length()) : "";
    }
}
