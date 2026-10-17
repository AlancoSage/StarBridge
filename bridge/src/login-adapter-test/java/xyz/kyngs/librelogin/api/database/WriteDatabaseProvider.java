package xyz.kyngs.librelogin.api.database;

/** Only the official public API signature used by the reset adapter; excluded from deployment. */
public interface WriteDatabaseProvider { void updateUser(User user); }
