package cn.starbridge.mods;

import com.google.gson.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Pure validation shared by the worker and the server thread. */
final class Protocol {
    static String base(String endpoint, String sid, String token) {
        URI uri = URI.create(endpoint);
        if (!("http".equals(uri.getScheme()) || "https".equals(uri.getScheme())) || uri.getHost() == null
                || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null
                || !sid.matches("[A-Za-z0-9_-]{1,40}") || token.length() < 24 || token.startsWith("CHANGE-ME")
                || token.chars().anyMatch(c -> c < 32 || c == 127)) throw new IllegalArgumentException("Invalid bridge configuration");
        return endpoint.replaceAll("/+$", "") + "/bridge/" + sid;
    }
    static String text(JsonObject value, String key, String fallback) {
        return value.has(key) && !value.get(key).isJsonNull() ? value.get(key).getAsString() : fallback;
    }
    static String clip(String text, int maximum) { return text.substring(0, Math.min(text.length(), maximum)); }
    static boolean expired(JsonObject job) { return job.get("expires").getAsDouble() * 1000 < System.currentTimeMillis(); }
    static void player(String name) {
        if (!name.matches("[A-Za-z0-9_]{1,16}")) throw new IllegalArgumentException("Invalid player name");
    }
    static String reason(JsonObject job) {
        String reason = text(job, "reason", "服务器管理员通过Myrinbot执行操作");
        if (reason.length() > 340 || reason.chars().anyMatch(c -> c < 32 || c == 127))
            throw new IllegalArgumentException("Invalid reason");
        return reason.trim().isEmpty() ? "服务器管理员通过Myrinbot执行操作" : reason;
    }
    static UUID offlineId(String name) { return UUID.nameUUIDFromBytes(("OfflinePlayer:" + name).getBytes(StandardCharsets.UTF_8)); }
    static boolean loginCommand(String command) {
        // Match complete command roots only; namespace tricks and lookalike names stay blocked.
        String root = command.split("\\s", 2)[0];
        return new HashSet<String>(Arrays.asList("login", "l", "qqlogin", "ql", "starbridge:login", "starbridge:l", "starbridge:qqlogin", "starbridge:ql")).contains(root);
    }
    static JsonObject result(String id, boolean ok, String detail) {
        JsonObject result = new JsonObject(); result.addProperty("id", id);
        result.addProperty("ok", ok); result.addProperty("detail", clip(detail, 1500)); return result;
    }
}
