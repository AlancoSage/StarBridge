package fr.xephi.authme.api.v3;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

/** Official AuthMe public API signatures used in security tests, excluded from deployment. */
public interface AuthMePlayer {
    String getName();
    Optional<UUID> getUuid();
    Instant getRegistrationDate();
}
