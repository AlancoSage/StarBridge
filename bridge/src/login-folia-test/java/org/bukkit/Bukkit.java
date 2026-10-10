package org.bukkit;

import io.papermc.paper.threadedregions.scheduler.GlobalRegionScheduler;
import org.bukkit.entity.Player;
import org.bukkit.plugin.PluginManager;
import org.bukkit.scheduler.BukkitScheduler;
import java.util.Collection;
import java.util.UUID;

/** Test-only facade: traditional scheduling is forbidden in this isolated Folia process. */
public final class Bukkit {
    private static Server server;
    public static GlobalRegionScheduler global;
    public static void setServer(Server value) { server = value; }
    public static Server getServer() { return server; }
    public static PluginManager getPluginManager() { return server.getPluginManager(); }
    public static BukkitScheduler getScheduler() { throw new AssertionError("Traditional scheduling on Folia"); }
    public static GlobalRegionScheduler getGlobalRegionScheduler() { return global; }
    public static Collection<? extends Player> getOnlinePlayers() { return server.getOnlinePlayers(); }
    public static Player getPlayer(UUID identity) { throw new AssertionError("Live player lookup outside its region"); }
    public static OfflinePlayer getOfflinePlayer(String name) { throw new AssertionError("Unexpected offline profile lookup"); }
}
