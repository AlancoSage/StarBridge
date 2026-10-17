package xyz.kyngs.librelogin.api.crypto;

/** Public API test signatures, not a redistributed authentication implementation. */
public interface CryptoProvider {
    HashedPassword createHash(String password);
    boolean matches(String input, HashedPassword password);
    String getIdentifier();
}
