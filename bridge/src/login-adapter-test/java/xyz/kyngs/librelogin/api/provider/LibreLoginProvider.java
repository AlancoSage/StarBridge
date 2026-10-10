package xyz.kyngs.librelogin.api.provider;

import xyz.kyngs.librelogin.api.LibreLoginPlugin;

/** Minimal public API contract fixture, without any upstream implementation. */
public interface LibreLoginProvider<P, S> {
    LibreLoginPlugin<P, S> getLibreLogin();
}
