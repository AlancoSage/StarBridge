package com.lenis0012.bukkit.loginsecurity.session;
import java.util.ArrayDeque;
import org.bukkit.entity.Player;
import com.lenis0012.bukkit.loginsecurity.session.action.*;
public final class PlayerSession {
    public final Player player;
    public boolean registered, authorized, restored, failNext;
    public int registrations, logins;
    public String password;
    public final ArrayDeque<Runnable> callbacks = new ArrayDeque<>();
    public PlayerSession(Player player) { this.player = player; }
    public Player getPlayer() { return player; }
    public boolean isRegistered() { return registered; }
    public boolean isAuthorized() { return authorized; }
    public void performActionAsync(AuthAction action, ActionCallback callback) {
        if (action instanceof RegisterAction) { registrations++; password = ((RegisterAction)action).password; }
        else logins++;
        callbacks.add(() -> callback.call(new ActionResponse(!failNext)));
    }
}
