package io.papermc.paper.threadedregions.scheduler;
import java.util.function.Consumer;
import org.bukkit.plugin.Plugin;
public interface GlobalRegionScheduler {
    ScheduledTask run(Plugin plugin, Consumer<ScheduledTask> run);
    ScheduledTask runAtFixedRate(Plugin plugin, Consumer<ScheduledTask> run, long delay, long period);
    void cancelTasks(Plugin plugin);
}
