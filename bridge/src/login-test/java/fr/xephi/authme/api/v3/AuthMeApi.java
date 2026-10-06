package fr.xephi.authme.api.v3;
import org.bukkit.entity.Player;
/** Test double for asynchronous AuthMe API, excluded from the production JAR. */
public final class AuthMeApi {
    public static final AuthMeApi INSTANCE = new AuthMeApi();
    public boolean registered, authenticated;
    public int registrations, logins, logouts;
    public static AuthMeApi getInstance() { return INSTANCE; }
    public boolean isAuthenticated(Player player) { return authenticated; }
    public boolean isRegistered(String name) { return registered; }
    public void forceLogin(Player player) { logins++; }
    public void forceRegister(Player player, String password, boolean autoLogin) {
        assert password.length() >= 24 && autoLogin; registrations++;
    }
    public void forceLogout(Player player) { logouts++; authenticated = false; }
}
