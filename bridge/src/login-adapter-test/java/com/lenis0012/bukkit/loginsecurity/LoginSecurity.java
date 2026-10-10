package com.lenis0012.bukkit.loginsecurity;
import org.bukkit.plugin.Plugin;
import com.lenis0012.bukkit.loginsecurity.session.SessionManager;
/** Public API fixture, not a copy of the native implementation. */
public interface LoginSecurity extends Plugin {
    SessionManager MANAGER = new SessionManager();
    LoginSecurityConfig CONFIG = new LoginSecurityConfig();
    static SessionManager getSessionManager() { return MANAGER; }
    static LoginSecurityConfig getConfiguration() { return CONFIG; }
}
