package xyz.kyngs.librelogin.api.database;

import java.util.UUID;

public interface User {
    UUID getUuid();
    String getLastNickname();
    boolean isRegistered();
    String getSecret();
    default java.sql.Timestamp getJoinDate() { return null; }
    default xyz.kyngs.librelogin.api.crypto.HashedPassword getHashedPassword() { return null; }
    default void setHashedPassword(xyz.kyngs.librelogin.api.crypto.HashedPassword password) { throw new UnsupportedOperationException(); }
    default void setIp(String ip) { throw new UnsupportedOperationException(); }
    default void setLastAuthentication(java.sql.Timestamp time) { throw new UnsupportedOperationException(); }
}
