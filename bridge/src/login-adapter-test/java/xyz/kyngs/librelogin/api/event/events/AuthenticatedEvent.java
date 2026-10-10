package xyz.kyngs.librelogin.api.event.events;

public interface AuthenticatedEvent<P, S> {
    enum AuthenticationReason { LOGIN, REGISTER, PREMIUM, SESSION }
}
