package cn.starbridge.velocity;

import java.io.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.Properties;

final class BridgeConfig {
    final boolean enabled;
    final String endpoint, server, token, engine;
    BridgeConfig(Path directory) throws IOException {
        Files.createDirectories(directory);
        Path file = directory.resolve("config.properties");
        if (!Files.exists(file)) {
            try (InputStream input = BridgeConfig.class.getResourceAsStream("/config.properties")) {
                if (input == null) throw new IOException("missing default configuration");
                Files.copy(input, file);
            }
        }
        Properties values = new Properties();
        try (Reader input = Files.newBufferedReader(file, StandardCharsets.UTF_8)) { values.load(input); }
        String toggle = values.getProperty("enabled", "false").trim();
        if (!toggle.equals("false") && !toggle.equals("true")) throw new IOException("invalid enabled option");
        enabled = toggle.equals("true");
        endpoint = values.getProperty("endpoint", "http://127.0.0.1:5800").trim().replaceAll("/+$", "");
        server = values.getProperty("server-id", "survival").trim();
        token = values.getProperty("token", "").trim();
        engine = values.getProperty("engine", "limboauth").trim();
        try {
            URI address = URI.create(endpoint);
            if (!("http".equals(address.getScheme()) || "https".equals(address.getScheme()))
                || address.getHost() == null || address.getRawUserInfo() != null
                || address.getRawQuery() != null || address.getRawFragment() != null
                || !(address.getRawPath() == null || address.getRawPath().isEmpty()))
                throw new IllegalArgumentException();
        } catch (IllegalArgumentException invalid) { throw new IOException("invalid bridge endpoint"); }
        if (!server.matches("[A-Za-z0-9_-]{1,40}") || !(engine.equals("limboauth") || engine.equals("librelogin"))
            || enabled && (token.length() < 16 || token.length() > 512 || token.matches(".*[\\r\\n].*")))
            throw new IOException("invalid bridge configuration");
    }
}
