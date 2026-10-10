package xyz.kyngs.librelogin.api.database;

import java.util.UUID;

public interface User {
    UUID getUuid();
    String getLastNickname();
    boolean isRegistered();
    String getSecret();
}
