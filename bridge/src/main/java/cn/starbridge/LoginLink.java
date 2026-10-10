package cn.starbridge;

import java.io.IOException;
import java.util.Set;
import org.bukkit.entity.Player;

/** Public-API adapters only; player operations run on the player's owning scheduler. */
interface LoginLink {
    String id();
    String displayName();
    boolean authenticated(Player player) throws ReflectiveOperationException, IOException;
    /** False means an existing, unverified native account still needs its original proof. */
    boolean start(Player player) throws ReflectiveOperationException, IOException;
    void remember(Player player) throws IOException;
    void logout(Player player) throws ReflectiveOperationException, IOException;
    Set<String> ownershipCommands();
    String ownershipPrompt();
    default void close() { }
}
