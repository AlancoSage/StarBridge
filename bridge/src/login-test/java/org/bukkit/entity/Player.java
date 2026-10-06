package org.bukkit.entity;

import java.net.InetSocketAddress;

/** Minimal Player test double; real Bukkit event classes and production handlers remain in use.
 *  Avoids bootstrapping Minecraft's potion/enchantment registries just to create an interface proxy.
 *  This source is compiled only into target/test-classes and is never packaged in the plugin JAR.
 */
public interface Player extends Entity, org.bukkit.OfflinePlayer {
    String getName();
    boolean isOnline();
    InetSocketAddress getAddress();
    void kickPlayer(String reason);
}
