package com.lenis0012.bukkit.loginsecurity.session.action;
public final class ActionResponse {
    private final boolean success;
    public ActionResponse(boolean success) { this.success = success; }
    public boolean isSuccess() { return success; }
}
