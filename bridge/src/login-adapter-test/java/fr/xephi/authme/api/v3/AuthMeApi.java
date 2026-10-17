package fr.xephi.authme.api.v3;

import java.util.Optional;
import org.bukkit.entity.Player;

/** Asynchronous API test double; credentials exist only in this test process. */
public final class AuthMeApi {
    public static final AuthMeApi INSTANCE = new AuthMeApi();
    public boolean authenticated;
    public volatile AuthMePlayer account;
    public volatile boolean mutate = true;
    public volatile String password = "Original-Password";
    public volatile int changes;
    public static AuthMeApi getInstance() { return INSTANCE; }
    public boolean isAuthenticated(Player player) { return authenticated; }
    public boolean isRegistered(String name) { return account != null && account.getName().equalsIgnoreCase(name); }
    public Optional<AuthMePlayer> getPlayerInfo(String name) {
        // Native AuthMe data sources use lowercase lookup keys while preserving a separate real name.
        return isRegistered(name) && name.equals(name.toLowerCase(java.util.Locale.ROOT)) ? Optional.ofNullable(account) : Optional.empty();
    }
    public boolean checkPassword(String name, String input) { return input.equals(password); }
    public void changePassword(String name, String next) {
        changes++;
        if (mutate) {
            Thread worker = new Thread(() -> { try { Thread.sleep(80); password = next; } catch (InterruptedException ignored) { } });
            worker.setDaemon(true); worker.start();
        }
    }
    public void forceLogin(Player player) { }
    public void forceRegister(Player player, String password, boolean autoLogin) { }
    public void forceLogout(Player player) { authenticated = false; }
}
