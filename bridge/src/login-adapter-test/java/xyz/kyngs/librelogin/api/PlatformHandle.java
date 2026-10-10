package xyz.kyngs.librelogin.api;

public interface PlatformHandle<P, S> {
    String getPlatformIdentifier();
    Class<P> getPlayerClass();
}
