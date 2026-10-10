package com.lenis0012.bukkit.loginsecurity.session;
import java.util.IdentityHashMap;
import org.bukkit.entity.Player;
public final class SessionManager {
    public final IdentityHashMap<Player, PlayerSession> sessions = new IdentityHashMap<>();
    public PlayerSession getPlayerSession(Player player) { return sessions.get(player); }
}
