package cn.starbridge.mods;

import com.google.gson.JsonObject;
import java.nio.file.Path;
import java.util.*;

/** Native operations are confined to the game thread; HTTP never enters an adapter. */
public interface GameHost {
    interface Player {
        Object handle(); UUID id(); String name(); String ip();
        void message(String text); void kick(String text); void freeze();
        JsonObject details();
    }
    List<Player> players(); Player player(UUID id);
    void execute(Runnable callback); void stop();
    Path catalogFile(); boolean onlineMode();
    JsonObject status(); JsonObject flags(UUID id, String name);
    void protect(Player player, BridgeEngine bridge);
    void unprotect(Player player);
    String command(String command) throws Exception;
    void manage(UUID id, String name, String action, String reason, String expectedReason, String kickReason) throws Exception;
    void whitelist(UUID id, String name) throws Exception;
    void broadcast(String message);
    void log(String message, Throwable error);
}
