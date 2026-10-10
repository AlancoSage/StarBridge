package org.bukkit.scheduler;
import org.bukkit.plugin.Plugin;
public interface BukkitScheduler {
    int scheduleSyncDelayedTask(Plugin plugin, Runnable run);
    int scheduleSyncRepeatingTask(Plugin plugin, Runnable run, long delay, long period);
    void cancelTask(int id);
    void cancelTasks(Plugin plugin);
}
