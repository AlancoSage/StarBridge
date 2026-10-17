package cn.starbridge.velocity;

import com.velocitypowered.api.proxy.Player;
import java.util.UUID;

/** No console command or database file access: all changes go through the owning plugin API. */
interface NativeAuth {
    interface Claim { boolean allowed() throws Exception; }
    String id();
    boolean authenticated(Player player) throws Exception;
    String account(Player player) throws Exception;
    String reset(UUID identity, String name, String account, String password, Claim claim) throws Exception;
    static String fingerprint(String engine, UUID identity, String born) throws Exception {
        if (born == null || born.isEmpty()) return "";
        byte[] digest = java.security.MessageDigest.getInstance("SHA-256")
            .digest((engine + "\n" + identity + "\n" + born).getBytes(java.nio.charset.StandardCharsets.UTF_8));
        return java.util.HexFormat.of().formatHex(digest);
    }
}
