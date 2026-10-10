package xyz.kyngs.librelogin.api.authorization;

import xyz.kyngs.librelogin.api.database.User;
import xyz.kyngs.librelogin.api.event.events.AuthenticatedEvent.AuthenticationReason;

public interface AuthorizationProvider<P> {
    boolean isAuthorized(P player);
    boolean isAwaiting2FA(P player);
    void authorize(User user, P player, AuthenticationReason reason);
}
