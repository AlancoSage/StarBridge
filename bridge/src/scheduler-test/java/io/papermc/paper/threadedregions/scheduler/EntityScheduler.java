package io.papermc.paper.threadedregions.scheduler;
import java.util.function.Consumer;
import org.bukkit.plugin.Plugin;
public interface EntityScheduler { ScheduledTask run(Plugin plugin, Consumer<ScheduledTask> run, Runnable retired); }
