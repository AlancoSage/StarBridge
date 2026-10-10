package org.bukkit.entity;

import io.papermc.paper.threadedregions.scheduler.EntityScheduler;
import java.net.InetSocketAddress;

/** Isolated player contract, plus Folia's public entity scheduler; never shipped. */
public interface Player extends Entity, org.bukkit.OfflinePlayer {
    String getName();
    boolean isOnline();
    InetSocketAddress getAddress();
    void kickPlayer(String reason);
    EntityScheduler getScheduler();
}
