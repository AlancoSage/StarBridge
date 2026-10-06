package cn.starbridge;

import com.google.gson.*;
import org.bukkit.Bukkit;
import org.bukkit.entity.Player;
import org.bukkit.entity.Projectile;
import org.bukkit.event.*;
import org.bukkit.event.block.BlockBreakEvent;
import org.bukkit.event.block.BlockPlaceEvent;
import org.bukkit.event.entity.EntityDamageEvent;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.entity.EntityPickupItemEvent;
import org.bukkit.event.entity.ProjectileLaunchEvent;
import org.bukkit.event.inventory.InventoryClickEvent;
import org.bukkit.event.inventory.InventoryDragEvent;
import org.bukkit.event.inventory.InventoryOpenEvent;
import org.bukkit.event.player.*;
import org.bukkit.event.vehicle.VehicleEnterEvent;
import org.bukkit.plugin.Plugin;

import java.lang.reflect.Field;
import java.util.*;
import java.util.concurrent.*;

/** All Bukkit access and connection transitions run on the game thread. HTTP uses two bounded workers. */
final class GameLogin implements Listener {
    interface Transport { JsonObject post(String route, JsonObject data) throws Exception; }
    private static final class Connection {
        final UUID uuid;
        final String nonce = UUID.randomUUID().toString(), name, ip;
        volatile boolean authenticated;
        boolean inFlight;
        boolean proof, awaitingAuthMe;
        long authMeDeadline;
        long deadline = System.currentTimeMillis() + 120000, lastCommand;
        Connection(Player player) {
            uuid = player.getUniqueId(); name = player.getName();
            ip = player.getAddress() != null && player.getAddress().getAddress() != null
                ? player.getAddress().getAddress().getHostAddress() : "";
        }
        JsonObject request(String action) {
            JsonObject data = new JsonObject();
            data.addProperty("action", action); data.addProperty("uuid", uuid.toString());
            data.addProperty("nonce", nonce); data.addProperty("player", name); data.addProperty("ip", ip);
            return data;
        }
    }
    private final Plugin plugin;
    private final Transport transport;
    private final Map<UUID, Connection> connections = new ConcurrentHashMap<>();
    private final ThreadPoolExecutor workers = new ThreadPoolExecutor(2, 2, 0, TimeUnit.SECONDS,
        new ArrayBlockingQueue<>(64), runnable -> { Thread thread = new Thread(runnable, "StarBridge-Login"); thread.setDaemon(true); return thread; });
    private volatile boolean policyKnown, required = true;
    private boolean passwordLogin = true, qqLogin = true;
    private String revision = "";
    private int loginSeconds = 120;
    private AuthMeLink authMe;
    private Plugin linkedPlugin;
    private String engine = "auto";
    private Field commandLogField;
    private boolean originalCommandLogs, ownsCommandLogs, commandLogWarning;

    GameLogin(Plugin plugin, Transport transport) {
        this.plugin = plugin; this.transport = transport;
        protectCommandLogs();
        Bukkit.getPluginManager().registerEvents(this, plugin);
        Bukkit.getScheduler().runTaskTimer(plugin, this::checkTimeouts, 20, 20);
        for (Player player : Bukkit.getOnlinePlayers()) begin(player);
    }

    boolean locked(Player player) {
        if (policyKnown && !required) return false;
        Connection connection = connections.get(player.getUniqueId());
        return !policyKnown || connection == null || !connection.authenticated;
    }

    String nonce(Player player) {
        Connection connection = connections.get(player.getUniqueId());
        return connection == null ? "" : connection.nonce;
    }

    private boolean protectCommandLogs() {
        try {
            if (ownsCommandLogs) { commandLogField.setBoolean(null, false); return true; }
            // Spigot logs command arguments before PlayerCommandPreprocessEvent.
            // Disable its native command echo before displaying the password-login prompt.
            commandLogField = Class.forName("org.spigotmc.SpigotConfig").getField("logCommands");
            originalCommandLogs = commandLogField.getBoolean(null);
            commandLogField.setBoolean(null, false); ownsCommandLogs = true;
            return true;
        } catch (ReflectiveOperationException ex) {
            if (!commandLogWarning) plugin.getLogger().severe("无法屏蔽服务器密码命令日志，游戏密码登录未启用；请使用兼容的 Spigot/Paper 服务端。");
            commandLogWarning = true;
            return false;
        }
    }

    private void restoreCommandLogs() {
        if (!ownsCommandLogs) return;
        try { commandLogField.setBoolean(null, originalCommandLogs); }
        catch (IllegalAccessException ignored) { }
        ownsCommandLogs = false;
    }

    void accept(JsonObject response) {
        if (!response.has("authentication")) {
            // An older backend has no authentication policy; never assume it means disabled.
            return;
        }
        JsonObject policy = response.getAsJsonObject("authentication");
        boolean previousKnown = policyKnown, previousRequired = required;
        String previousRevision = revision;
        required = policy.get("required").getAsBoolean();
        passwordLogin = policy.get("password_login").getAsBoolean();
        qqLogin = policy.get("qq_login").getAsBoolean();
        loginSeconds = Math.max(30, Math.min(600, policy.get("login_seconds").getAsInt()));
        revision = policy.get("revision").getAsString(); policyKnown = true;
        engine = policy.has("login_engine") ? policy.get("login_engine").getAsString() : "auto";
        if (required && (!policy.get("available").getAsBoolean()
                || !configureEngine()
                || passwordLogin && !protectCommandLogs())) {
            policyKnown = false;
            for (Player player : Bukkit.getOnlinePlayers()) player.kickPlayer("星桥游戏认证尚未就绪，请联系管理员检查登录引擎、AuthMe API 与认证设置。");
            return;
        }
        if (!required) {
            for (Connection connection : connections.values()) connection.authenticated = true;
            return;
        }
        if (previousKnown && (!previousRequired || !previousRevision.equals(revision))) {
            for (Player player : Bukkit.getOnlinePlayers()) begin(player);
        }
        if (response.has("authentication_results")) for (JsonElement element : response.getAsJsonArray("authentication_results")) {
            JsonObject result = element.getAsJsonObject();
            Connection connection = connections.get(UUID.fromString(result.get("uuid").getAsString()));
            if (connection == null || !connection.nonce.equals(result.get("nonce").getAsString())) continue;
            if ("missing".equals(result.get("status").getAsString())) {
                Player player = Bukkit.getPlayer(connection.uuid);
                // A backend restart gets a fresh nonce, fencing all delayed old callbacks.
                if (player != null && player.isOnline()) begin(player);
            } else apply(connection, result, false, false);
        }
    }

    private boolean configureEngine() {
        Plugin installed = Bukkit.getPluginManager().getPlugin("AuthMe");
        boolean enabled = installed != null && installed.isEnabled();
        if ("builtin".equals(engine) && enabled || "authme".equals(engine) && !enabled) return false;
        if (!enabled) { authMe = null; linkedPlugin = null; return !"authme".equals(engine); }
        if (authMe != null && linkedPlugin == installed) return true;
        try { authMe = new AuthMeLink(installed, plugin); linkedPlugin = installed; return true; }
        catch (ReflectiveOperationException | RuntimeException | java.io.IOException ex) {
            plugin.getLogger().severe("AuthMe API v3 无法接入，请检查版本与启动日志；星桥未放行游戏登录。");
            authMe = null; linkedPlugin = null; return false;
        }
    }

    JsonArray snapshot() {
        JsonArray records = new JsonArray();
        for (Player player : Bukkit.getOnlinePlayers()) {
            Connection connection = connections.get(player.getUniqueId());
            if (connection != null) records.add(connection.request("heartbeat"));
            if (records.size() >= 500) break;
        }
        return records;
    }

    private void begin(Player player) {
        Connection connection = new Connection(player);
        connection.deadline = System.currentTimeMillis() + loginSeconds * 1000L;
        connections.put(connection.uuid, connection);
        if (policyKnown && !required) { connection.authenticated = true; return; }
        player.sendMessage("星桥正在检查本次游戏登录，请稍候……");
        submit(connection, connection.request("join"), true);
    }

    private void submit(Connection connection, JsonObject payload, boolean joining) {
        if (connection.inFlight) { message(connection, "认证请求正在处理中，请稍候。"); return; }
        connection.inFlight = true;
        try {
            workers.execute(() -> {
                JsonObject result;
                try { result = transport.post("/auth", payload); }
                catch (Exception ex) {
                    result = new JsonObject(); result.addProperty("error", "认证连接暂不可用，请稍后重试或联系管理员。");
                } finally {
                    // Never retain a password in a queued payload after the request completes.
                    payload.remove("password");
                }
                JsonObject answer = result;
                if (plugin.isEnabled()) Bukkit.getScheduler().runTask(plugin, () -> {
                    if (connections.get(connection.uuid) != connection) return;
                    connection.inFlight = false;
                    if (answer.has("error")) {
                        message(connection, answer.get("error").getAsString());
                        if (joining) kick(connection, "认证服务不可用，请稍后重新进入服务器。");
                    } else apply(connection, answer, joining, true);
                });
            });
        } catch (RejectedExecutionException ex) {
            payload.remove("password"); connection.inFlight = false;
            message(connection, "认证请求繁忙，请稍后重试。");
            if (joining) kick(connection, "认证请求繁忙，请稍后重新进入服务器。");
        }
    }

    private void apply(Connection connection, JsonObject result, boolean joining, boolean notify) {
        if (connections.get(connection.uuid) != connection) return;
        if (!result.has("nonce") || !connection.nonce.equals(result.get("nonce").getAsString())) return;
        if (policyKnown && result.has("revision") && !revision.equals(result.get("revision").getAsString())) return;
        String status = result.get("status").getAsString();
        if ("authenticated".equals(status)) {
            if (!connection.proof) {
                connection.proof = true;
                if (authMe == null) complete(connection);
                else {
                    Player player = Bukkit.getPlayer(connection.uuid);
                    if (player == null || !player.isOnline()) return;
                    connection.awaitingAuthMe = true; connection.authMeDeadline = System.currentTimeMillis() + loginSeconds * 1000L;
                    try {
                        if (!authMe.start(player)) message(connection, "这是已有 AuthMe 账号，首次关联请再输入 /authme:login <原 AuthMe 密码> 验证所有权；以后可用星桥密码或 QQ 登录。");
                        finishAuthMe(connection, player);
                    } catch (ReflectiveOperationException | RuntimeException | java.io.IOException ex) { kick(connection, "AuthMe 登录同步失败，请联系管理员检查插件设置。"); }
                }
            }
        } else if ("disabled".equals(status)) {
            // Only a synchronized disabled policy can release the movement/command gate.
            if (policyKnown && !required) connection.authenticated = true;
        } else if ("denied".equals(status)) {
            connection.authenticated = false; kick(connection, result.get("message").getAsString());
        } else if (joining && "pending".equals(status)) {
            connection.deadline = System.currentTimeMillis() + result.get("expires_in").getAsInt() * 1000L;
            message(connection, prompt());
        } else if (notify && result.has("message") && !connection.authenticated) message(connection, result.get("message").getAsString());
    }

    private void complete(Connection connection) {
        if (!connection.authenticated) {
            connection.authenticated = true; connection.awaitingAuthMe = false;
            message(connection, "登录成功，欢迎回来！");
        }
    }
    private void finishAuthMe(Connection connection, Player player) throws ReflectiveOperationException, java.io.IOException {
        if (connection.proof && connection.awaitingAuthMe && authMe.authenticated(player)) {
            authMe.remember(player); complete(connection);
        }
    }

    private String prompt() {
        return "请登录：" + (passwordLogin ? "/login <注册时的密码>（或 /l <密码>） " : "") + (qqLogin ? "或 /qqlogin（简写 /ql，绑定 QQ 私聊确认）" : "")
            + "。旧账号可在网页「设置登录密码」验证邮箱后设置密码。";
    }
    private void message(Connection connection, String text) {
        Player player = Bukkit.getPlayer(connection.uuid);
        if (player != null && player.isOnline() && connections.get(connection.uuid) == connection) player.sendMessage(text);
    }
    private void kick(Connection connection, String text) {
        Player player = Bukkit.getPlayer(connection.uuid);
        if (player != null && player.isOnline() && connections.get(connection.uuid) == connection) player.kickPlayer(text);
    }
    private void checkTimeouts() {
        protectCommandLogs();
        for (Player player : Bukkit.getOnlinePlayers()) {
            Connection connection = connections.get(player.getUniqueId());
            if (policyKnown && required && authMe != null && connection != null) {
                try {
                    if (connection.awaitingAuthMe) {
                        finishAuthMe(connection, player);
                        if (connection.awaitingAuthMe && System.currentTimeMillis() >= connection.authMeDeadline) kick(connection, "AuthMe 同步超时，请检查其注册限制与登录设置。");
                    } else if (connection.authenticated && !authMe.authenticated(player)) { begin(player); continue; }
                } catch (ReflectiveOperationException | RuntimeException | java.io.IOException ex) { kick(connection, "AuthMe 登录状态不可用，请联系管理员。"); }
            }
            if (connection != null && locked(player) && System.currentTimeMillis() >= connection.deadline) kick(connection, "登录超时，请重新进入服务器。");
        }
    }
    static String commandName(String message) {
        String first = message.split("\\s", 2)[0].toLowerCase(Locale.ROOT);
        if (first.startsWith("/")) first = first.substring(1);
        if (first.startsWith("starbridge:")) first = first.substring(11);
        return switch (first) { case "l" -> "login"; case "ql" -> "qqlogin"; default -> first; };
    }
    private void login(Player player, String name, String arg) {
        if (!policyKnown) { player.sendMessage("正在同步认证设置，请稍后重试。"); return; }
        if (!required) { player.sendMessage("此服务器没有启用星桥游戏登录。"); return; }
        Connection connection = connections.get(player.getUniqueId());
        if (connection == null) { begin(player); return; }
        if (connection.authenticated) { player.sendMessage("你已经登录。"); return; }
        if (System.currentTimeMillis() - connection.lastCommand < 1000) return;
        connection.lastCommand = System.currentTimeMillis();
        boolean password = name.equals("login");
        if (password && !passwordLogin || !password && !qqLogin) { player.sendMessage("此登录方式没有开放。"); return; }
        if (password && (arg.length() < 8 || arg.length() > 128)) { player.sendMessage("正确格式：/login <8–128 字符密码> 或 /l <密码>，请勿在公共聊天中发送密码。"); return; }
        JsonObject data = connection.request(password ? "password" : "qq");
        if (password) data.addProperty("password", arg);
        submit(connection, data, false);
    }

    @EventHandler(priority=EventPriority.LOWEST)
    public void onCommand(PlayerCommandPreprocessEvent event) {
        String name = commandName(event.getMessage());
        boolean own = name.equals("login") || name.equals("qqlogin");
        Connection connection = connections.get(event.getPlayer().getUniqueId());
        if (name.equals("logout") && policyKnown && required) {
            event.setCancelled(true);
            try { if (authMe != null) authMe.logout(event.getPlayer()); }
            catch (ReflectiveOperationException ex) { event.getPlayer().kickPlayer("AuthMe 退出登录失败，请重新连接。"); return; }
            begin(event.getPlayer());
        } else if ((name.equals("authme:login") || name.equals("authme:l") || name.equals("authme:totp")
                || name.equals("authme:verification") || name.equals("authme:captcha")) && policyKnown && required && authMe != null
                && connection != null && connection.proof && connection.awaitingAuthMe) {
            // AuthMe's LOWEST listener blocks namespaced commands before login by default.
            // Permit only its fixed authentication commands after independent StarBridge proof;
            // AuthMe command handlers still verify credentials, permissions and additional codes.
            event.setCancelled(false);
            return;
        } else if (own && (!policyKnown || required || !Bukkit.getPluginManager().isPluginEnabled("AuthMe"))) {
            String original = event.getMessage();
            int split = original.indexOf(' ');
            String arg = split < 0 ? "" : original.substring(split + 1);
            event.setMessage("/starbridge:" + name); event.setCancelled(true);
            login(event.getPlayer(), name, arg);
        } else if (locked(event.getPlayer())) {
            event.setCancelled(true); event.getPlayer().sendMessage(prompt());
        }
    }
    @EventHandler public void onJoin(PlayerJoinEvent event) { begin(event.getPlayer()); }
    @EventHandler public void onQuit(PlayerQuitEvent event) {
        Connection connection = connections.remove(event.getPlayer().getUniqueId());
        if (connection != null && policyKnown && required) {
            try { workers.execute(() -> { try { transport.post("/auth", connection.request("leave")); } catch (Exception ignored) { } }); }
            catch (RejectedExecutionException ignored) { }
        }
    }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onMove(PlayerMoveEvent event) {
        if (locked(event.getPlayer()) && event.getTo() != null
                && (event.getFrom().getX() != event.getTo().getX() || event.getFrom().getY() != event.getTo().getY() || event.getFrom().getZ() != event.getTo().getZ())) event.setTo(event.getFrom());
    }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onTeleport(PlayerTeleportEvent event) {
        Connection connection = connections.get(event.getPlayer().getUniqueId());
        boolean synchronizing = connection != null && connection.proof && connection.awaitingAuthMe
            && event.getCause() == PlayerTeleportEvent.TeleportCause.PLUGIN;
        if (locked(event.getPlayer()) && !synchronizing) event.setCancelled(true);
    }
    @EventHandler(priority=EventPriority.LOWEST)
    public void onChat(AsyncPlayerChatEvent event) { if (locked(event.getPlayer())) { event.setCancelled(true); event.setMessage(""); } }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onBreak(BlockBreakEvent event) { if (locked(event.getPlayer())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onPlace(BlockPlaceEvent event) { if (locked(event.getPlayer())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST)
    public void onInteract(PlayerInteractEvent event) { if (locked(event.getPlayer())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onEntity(PlayerInteractEntityEvent event) { if (locked(event.getPlayer())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onEntityAt(PlayerInteractAtEntityEvent event) { if (locked(event.getPlayer())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onDrop(PlayerDropItemEvent event) { if (locked(event.getPlayer())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onSwap(PlayerSwapHandItemsEvent event) { if (locked(event.getPlayer())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onConsume(PlayerItemConsumeEvent event) { if (locked(event.getPlayer())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onPickup(EntityPickupItemEvent event) { if (event.getEntity() instanceof Player player && locked(player)) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onProjectile(ProjectileLaunchEvent event) { if (event.getEntity().getShooter() instanceof Player player && locked(player)) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onFish(PlayerFishEvent event) { if (locked(event.getPlayer())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onEditBook(PlayerEditBookEvent event) { if (locked(event.getPlayer())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onInventory(InventoryClickEvent event) { if (event.getWhoClicked() instanceof Player player && locked(player)) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onInventoryDrag(InventoryDragEvent event) { if (event.getWhoClicked() instanceof Player player && locked(player)) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onInventoryOpen(InventoryOpenEvent event) { if (event.getPlayer() instanceof Player player && locked(player)) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onVehicle(VehicleEnterEvent event) { if (event.getEntered() instanceof Player player && locked(player)) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onDamage(EntityDamageEvent event) {
        if (event.getEntity() instanceof Player player && locked(player)) event.setCancelled(true);
        if (event instanceof EntityDamageByEntityEvent hit) {
            if (hit.getDamager() instanceof Player player && locked(player)) hit.setCancelled(true);
            if (hit.getDamager() instanceof Projectile shot && shot.getShooter() instanceof Player player && locked(player)) hit.setCancelled(true);
        }
    }
    void close() {
        workers.shutdownNow();
        if (!policyKnown || required) for (Player player : Bukkit.getOnlinePlayers()) player.kickPlayer("游戏认证插件已停止，请稍后重新连接。");
        connections.clear(); restoreCommandLogs();
    }
}
