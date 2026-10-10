package xyz.kyngs.librelogin.api.database;

import java.util.UUID;

public interface ReadDatabaseProvider {
    User getByUUID(UUID identity);
    User getByName(String name);
}
