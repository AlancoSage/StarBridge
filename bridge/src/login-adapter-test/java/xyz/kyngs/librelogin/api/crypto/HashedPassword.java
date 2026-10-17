package xyz.kyngs.librelogin.api.crypto;

/** Public API test signature; this fixture is never bundled with the bridge. */
public record HashedPassword(String hash, String salt, String algo) { }
