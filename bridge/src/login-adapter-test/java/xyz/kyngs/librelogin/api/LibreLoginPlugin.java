package xyz.kyngs.librelogin.api;

import java.util.UUID;
import xyz.kyngs.librelogin.api.authorization.AuthorizationProvider;
import xyz.kyngs.librelogin.api.database.ReadDatabaseProvider;

/** The public signatures actually used by the optional adapter. */
public interface LibreLoginPlugin<P, S> {
    AuthorizationProvider<P> getAuthorizationProvider();
    ReadDatabaseProvider getDatabaseProvider();
    PlatformHandle<P, S> getPlatformHandle();
    boolean multiProxyEnabled();
    P getPlayerForUUID(UUID identity);
    Object getTOTPProvider();
}
