package org.bukkit;
import io.papermc.paper.threadedregions.scheduler.GlobalRegionScheduler;
import org.bukkit.scheduler.BukkitScheduler;
public final class Bukkit {
    public static boolean folia;
    public static BukkitScheduler legacy;
    public static GlobalRegionScheduler global;
    public static BukkitScheduler getScheduler() {
        if (folia) throw new AssertionError("Folia must not fall back to Bukkit scheduler");
        return legacy;
    }
    public static GlobalRegionScheduler getGlobalRegionScheduler() {
        if (!folia) throw new AssertionError("Legacy servers must not use the Folia scheduler");
        return global;
    }
}
