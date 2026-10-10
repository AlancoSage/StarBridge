package com.nickuc.login.api.types;

public interface Identity {
    String knownName();
    static Identity ofKnownName(String name) { return () -> name; }
}
