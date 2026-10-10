package com.lenis0012.bukkit.loginsecurity;
public final class LoginSecurityConfig {
    public boolean captcha, enabled = true;
    public boolean isRegisterCaptcha() { return captcha; }
    public boolean isRegistrationEnabled() { return enabled; }
    public int getPasswordMinLength() { return 6; }
    public int getPasswordMaxLength() { return 32; }
}
