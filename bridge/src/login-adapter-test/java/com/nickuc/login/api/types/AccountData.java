package com.nickuc.login.api.types;

import java.util.Optional;
import java.util.UUID;

public interface AccountData {
    Optional<UUID> getUniqueId();
}
