package com.nickuc.login.api;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import com.nickuc.login.api.enums.ImplementationType;
import com.nickuc.login.api.types.AccountData;
import com.nickuc.login.api.types.Identity;

public final class MockNLogin {
    public static nLoginAPI api = new Core();
    public static boolean ready = true, complete, registerSuccess = true, requestThrows;
    public static ImplementationType mode = ImplementationType.NATIVE;
    public static int registrations, requests;
    public static UUID registrationId;
    public static String credential;
    public static final Map<String, UUID> accounts = new HashMap<>();
    public static final Set<String> authenticated = new HashSet<>();
    private static final class Core implements nLoginAPI {
        public boolean isAvailable() { return ready; }
        public ImplementationType getImplementationType() { return mode; }
        public Optional<AccountData> getAccount(Identity identity) {
            UUID uuid = accounts.get(identity.knownName());
            return uuid == null ? Optional.empty() : Optional.of(() -> Optional.of(uuid));
        }
        public boolean isAuthenticated(Identity identity) { return authenticated.contains(identity.knownName()); }
        public boolean performRegister(Identity identity, String password, String ip) {
            registrations++;
            if (!registerSuccess || accounts.containsKey(identity.knownName())) return false;
            credential = password;
            accounts.put(identity.knownName(), registrationId);
            return true;
        }
        public void requestLogin(Identity identity, Object plugin) {
            requests++;
            if (requestThrows) throw new IllegalStateException("Native login unavailable");
            if (complete) authenticated.add(identity.knownName());
        }
    }
}
