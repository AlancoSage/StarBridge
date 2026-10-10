package com.lenis0012.bukkit.loginsecurity.session.action;
import com.lenis0012.bukkit.loginsecurity.session.*;
public final class RegisterAction extends AuthAction {
    public final String password;
    public RegisterAction(AuthService service, Object provider, String password) { this.password = password; }
}
