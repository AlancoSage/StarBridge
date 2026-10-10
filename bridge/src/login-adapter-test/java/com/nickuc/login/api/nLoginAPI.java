package com.nickuc.login.api;

import java.util.Optional;
import com.nickuc.login.api.enums.ImplementationType;
import com.nickuc.login.api.types.AccountData;
import com.nickuc.login.api.types.Identity;

/** Independent mock of the documented signatures; contains no upstream implementation. */
public interface nLoginAPI {
    static nLoginAPI getApi() { return MockNLogin.api; }
    boolean isAvailable();
    ImplementationType getImplementationType();
    Optional<AccountData> getAccount(Identity identity);
    boolean isAuthenticated(Identity identity);
    boolean performRegister(Identity identity, String password, String ip);
    void requestLogin(Identity identity, Object plugin);
}
