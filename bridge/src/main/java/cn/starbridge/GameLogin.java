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
import org.bukkit.event.entity.ProjectileLaunchEvent;
import org.bukkit.event.inventory.InventoryClickEvent;
import org.bukkit.event.inventory.InventoryOpenEvent;
import org.bukkit.event.player.*;
import org.bukkit.event.vehicle.VehicleEnterEvent;
import org.bukkit.plugin.Plugin;

import java.lang.reflect.Field;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Player transitions run on their owning scheduler; HTTP uses two bounded workers. */
final class GameLogin implements Listener {
    interface Transport { JsonObject post(String route, JsonObject data) throws Exception; }
    private static final class Policy {
        final boolean known, required, passwordLogin, qqLogin;
        final String revision, engine;
        final int loginSeconds;
        final LoginLink external;
        final long generation;
        Policy(boolean known, boolean required, boolean passwordLogin, boolean qqLogin,
               String revision, String engine, int loginSeconds, LoginLink external, long generation) {
            this.known = known; this.required = required; this.passwordLogin = passwordLogin; this.qqLogin = qqLogin;
            this.revision = revision; this.engine = engine; this.loginSeconds = loginSeconds;
            this.external = external; this.generation = generation;
        }
        boolean sameSettings(Policy other) {
            return known == other.known && required == other.required && passwordLogin == other.passwordLogin
                && qqLogin == other.qqLogin && revision.equals(other.revision) && engine.equals(other.engine)
                && loginSeconds == other.loginSeconds && external == other.external;
        }
    }
    private static final class Authentication {
        final boolean authenticated;
        final long generation;
        Authentication(boolean authenticated, long generation) { this.authenticated = authenticated; this.generation = generation; }
    }
    private static final class Connection {
        // Capture these only on the entity thread. Heartbeats never read live player state.
        final Player player;
        final UUID uuid;
        final String nonce = UUID.randomUUID().toString(), name, ip;
        volatile Authentication authentication = new Authentication(false, -1);
        // Scheduling metadata is shared with the global timer, not player login state.
        final AtomicBoolean timeoutQueued = new AtomicBoolean();
        // Remaining fields are confined to this player's scheduler.
        boolean inFlight;
        boolean proof, awaitingExternal;
        long externalDeadline, proofGeneration = -1;
        long deadline = System.currentTimeMillis() + 120000, lastCommand;
        Connection(Player player) {
            this.player = player;
            uuid = BukkitCompatibility.identity(player); name = player.getName();
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
        new ArrayBlockingQueue<>(64), runnable -> { Thread thread = new Thread(runnable, "Myrinbot-Login"); thread.setDaemon(true); return thread; });
    private volatile Policy policy = new Policy(false, true, true, true, "", "auto", 120, null, 0);
    private volatile boolean closed;
    private final LoginLinks loginLinks;
    private Field commandLogField;
    private boolean originalCommandLogs, ownsCommandLogs, commandLogWarning;

    GameLogin(Plugin plugin, Transport transport) {
        this.plugin = plugin; this.transport = transport; this.loginLinks = new LoginLinks(plugin);
        protectCommandLogs();
        Bukkit.getPluginManager().registerEvents(this, plugin);
        for (String name : Arrays.asList("PlayerInteractAtEntityEvent", "PlayerSwapHandItemsEvent", "PlayerItemConsumeEvent", "PlayerPickupItemEvent", "PlayerEditBookEvent")) {
            BukkitCompatibility.optionalEvent(plugin, "org.bukkit.event.player." + name, event -> gateOptional(event, "getPlayer"));
        }
        BukkitCompatibility.optionalEvent(plugin, "org.bukkit.event.entity.EntityPickupItemEvent", event -> gateOptional(event, "getEntity"));
        BukkitCompatibility.optionalEvent(plugin, "org.bukkit.event.inventory.InventoryDragEvent", event -> gateOptional(event, "getWhoClicked"));
        BridgeScheduler.repeatGlobal(plugin, this::checkTimeouts, 20, 20);
        for (Player player : BukkitCompatibility.players()) {
            if (BridgeScheduler.isFolia()) BridgeScheduler.runPlayer(plugin, player, () -> begin(player), null);
            else begin(player);
        }
    }

    boolean locked(Player player) {
        Policy current = policy;
        if (current.known && !current.required) return false;
        Connection connection = connections.get(BukkitCompatibility.identity(player));
        if (!current.known || connection == null || connection.player != player) return true;
        Authentication authentication = connection.authentication;
        return !authentication.authenticated || authentication.generation != current.generation;
    }

    String nonce(Player player) {
        Connection connection = connections.get(BukkitCompatibility.identity(player));
        return connection == null ? "" : connection.nonce;
    }

    private synchronized boolean protectCommandLogs() {
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

    private synchronized void restoreCommandLogs() {
        if (!ownsCommandLogs) return;
        try { commandLogField.setBoolean(null, originalCommandLogs); }
        catch (IllegalAccessException ignored) { }
        ownsCommandLogs = false;
    }

    synchronized void accept(JsonObject response) {
        if (closed || !response.has("authentication")) {
            // An older backend has no authentication policy; never assume it means disabled.
            return;
        }
        JsonObject value = response.getAsJsonObject("authentication");
        Policy previous = policy;
        boolean required = value.get("required").getAsBoolean();
        boolean passwordLogin = value.get("password_login").getAsBoolean();
        boolean qqLogin = value.get("qq_login").getAsBoolean();
        int loginSeconds = Math.max(30, Math.min(600, value.get("login_seconds").getAsInt()));
        String revision = value.get("revision").getAsString();
        String engine = value.has("login_engine") ? value.get("login_engine").getAsString() : "auto";
        boolean ready = true;
        LoginLink link = null;
        if (required) {
            try { link = loginLinks.select(engine); }
            catch (IllegalStateException exception) { ready = false; }
            ready = ready && value.get("available").getAsBoolean() && (!passwordLogin || protectCommandLogs());
        } else loginLinks.close();
        Policy candidate = new Policy(ready, required, passwordLogin, qqLogin, revision, engine, loginSeconds, link, previous.generation);
        final Policy accepted = new Policy(ready, required, passwordLogin, qqLogin, revision, engine, loginSeconds, link,
            candidate.sameSettings(previous) ? previous.generation : previous.generation + 1);
        policy = accepted;
        if (!ready) {
            for (Connection connection : connections.values()) dispatch(connection, () -> {
                if (policy.generation == accepted.generation) kick(connection, "Myrinbot游戏认证尚未就绪，请联系管理员检查登录引擎、登录插件 API 与认证设置。");
            });
            return;
        }
        if (!required) {
            for (Connection connection : connections.values()) dispatch(connection, () -> {
                if (policy.generation == accepted.generation) connection.authentication = new Authentication(true, accepted.generation);
            });
            return;
        }
        if (previous.known && !candidate.sameSettings(previous)) {
            for (Connection connection : connections.values()) dispatch(connection, () -> {
                if (policy.generation == accepted.generation) begin(connection.player);
            });
        }
        if (response.has("authentication_results")) for (JsonElement element : response.getAsJsonArray("authentication_results")) {
            JsonObject result = element.getAsJsonObject();
            Connection connection = connections.get(UUID.fromString(result.get("uuid").getAsString()));
            if (connection == null || !connection.nonce.equals(result.get("nonce").getAsString())) continue;
            dispatch(connection, () -> {
                if (policy.generation != accepted.generation) return;
                // A backend restart gets a fresh nonce, fencing all delayed old callbacks.
                if ("missing".equals(result.get("status").getAsString())) begin(connection.player);
                else apply(connection, result, false, false);
            });
        }
    }

    JsonArray snapshot() {
        JsonArray records = new JsonArray();
        for (Connection connection : connections.values()) {
            records.add(connection.request("heartbeat"));
            if (records.size() >= 500) break;
        }
        return records;
    }

    private void begin(Player player) {
        if (closed || !plugin.isEnabled() || !player.isOnline()) return;
        Connection connection = new Connection(player);
        Policy current;
        synchronized (this) {
            // A region event can race onDisable while capturing the address.
            if (closed || !plugin.isEnabled()) return;
            current = policy;
            connection.deadline = System.currentTimeMillis() + current.loginSeconds * 1000L;
            connections.put(connection.uuid, connection);
        }
        if (current.known && !current.required) { connection.authentication = new Authentication(true, current.generation); return; }
        message(connection, "Myrinbot正在检查本次游戏登录，请稍候……");
        submit(connection, connection.request("join"), true);
    }

    private void submit(Connection connection, JsonObject payload, boolean joining) {
        if (!current(connection)) { payload.remove("password"); return; }
        if (connection.inFlight) { message(connection, "认证请求正在处理中，请稍候。"); return; }
        connection.inFlight = true;
        Policy submittedPolicy = policy;
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
                queue(connection, () -> {
                    connection.inFlight = false;
                    if (submittedPolicy.known && policy.generation != submittedPolicy.generation) return;
                    if (answer.has("error")) {
                        if (policy.known && !policy.required) return;
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
        Policy current = policy;
        if (current.known && result.has("revision") && !current.revision.equals(result.get("revision").getAsString())) return;
        String status = result.get("status").getAsString();
        if ("authenticated".equals(status)) {
            if (!current.known || !current.required) return;
            if (connection.proof && connection.proofGeneration != current.generation) { begin(connection.player); return; }
            if (!connection.proof) {
                connection.proof = true; connection.proofGeneration = current.generation;
                if (current.external == null) complete(connection, current);
                else {
                    Player player = connection.player;
                    if (player == null || !player.isOnline()) return;
                    connection.awaitingExternal = true; connection.externalDeadline = System.currentTimeMillis() + current.loginSeconds * 1000L;
                    try {
                        current.external.start(player);
                        finishExternal(connection, current);
                        if (connection.awaitingExternal) message(connection, current.external.ownershipPrompt());
                    } catch (ReflectiveOperationException | RuntimeException | java.io.IOException ex) {
                        kick(connection, externalFailure(current.external, ex, "登录同步失败，请联系管理员检查插件设置。"));
                    }
                }
            }
        } else if ("disabled".equals(status)) {
            // Only a synchronized disabled policy can release the movement/command gate.
            if (current.known && !current.required) connection.authentication = new Authentication(true, current.generation);
        } else if ("denied".equals(status)) {
            connection.authentication = new Authentication(false, current.generation); kick(connection, result.get("message").getAsString());
        } else if (joining && "pending".equals(status)) {
            connection.deadline = System.currentTimeMillis() + result.get("expires_in").getAsInt() * 1000L;
            message(connection, prompt());
        } else if (notify && result.has("message") && !connection.authentication.authenticated) message(connection, result.get("message").getAsString());
    }

    private void complete(Connection connection, Policy current) {
        if (!connection.authentication.authenticated || connection.authentication.generation != current.generation) {
            connection.authentication = new Authentication(true, current.generation); connection.awaitingExternal = false;
            message(connection, "登录成功，欢迎回来！");
        }
    }
    private void finishExternal(Connection connection, Policy current) throws ReflectiveOperationException, java.io.IOException {
        if (connection.proof && connection.awaitingExternal && current.external.authenticated(connection.player)) {
            current.external.remember(connection.player); complete(connection, current);
        }
    }

    private static String externalFailure(LoginLink link, Exception failure, String fallback) {
        // Adapter-owned explanations are safe to show. File errors and reflected native
        // exceptions may contain private paths or arguments, so keep their messages local.
        String detail = failure.getMessage();
        if (failure instanceof java.io.IOException && detail != null && detail.startsWith(link.displayName() + " ")
                && detail.length() <= 240 && detail.indexOf('\n') < 0 && detail.indexOf('\r') < 0) return detail;
        return link.displayName() + " " + fallback;
    }

    private String prompt() {
        Policy current = policy;
        String prefix = current.external != null && "nlogin".equals(current.external.id()) ? "/starbridge:" : "/";
        return "请登录：" + (current.passwordLogin ? prefix + "login <注册时的密码>（或 " + prefix + "l <密码>） " : "") + (current.qqLogin ? "或 " + prefix + "qqlogin（简写 " + prefix + "ql，绑定 QQ 私聊确认）" : "")
            + "。旧账号可在网页「设置登录密码」验证邮箱后设置密码。";
    }
    private boolean current(Connection connection) {
        return !closed && plugin.isEnabled() && connections.get(connection.uuid) == connection;
    }
    private void queue(Connection connection, Runnable task) {
        queue(connection, task, null);
    }
    private void queue(Connection connection, Runnable task, Runnable done) {
        if (!current(connection)) { if (done != null) done.run(); return; }
        BridgeScheduler.runPlayer(plugin, connection.player, () -> {
            try { if (current(connection) && connection.player.isOnline()) task.run(); }
            finally { if (done != null) done.run(); }
        }, () -> {
            connections.remove(connection.uuid, connection);
            if (done != null) done.run();
        });
    }
    private void dispatch(Connection connection, Runnable task) {
        if (BridgeScheduler.isFolia()) queue(connection, task);
        else if (current(connection) && connection.player.isOnline()) task.run();
    }
    // These two methods are called only by entity tasks or player events.
    private void message(Connection connection, String text) {
        if (current(connection) && connection.player.isOnline()) connection.player.sendMessage(text);
    }
    private void kick(Connection connection, String text) {
        if (current(connection) && connection.player.isOnline()) connection.player.kickPlayer(text);
    }
    private void checkTimeouts() {
        if (closed) return;
        protectCommandLogs();
        for (Connection connection : connections.values()) {
            if (BridgeScheduler.isFolia()) {
                if (connection.timeoutQueued.compareAndSet(false, true))
                    queue(connection, () -> checkTimeout(connection), () -> connection.timeoutQueued.set(false));
            } else dispatch(connection, () -> checkTimeout(connection));
        }
    }
    private void checkTimeout(Connection connection) {
        Policy current = policy;
        Player player = connection.player;
        if (current.known && current.required && connection.proof && connection.proofGeneration != current.generation) { begin(player); return; }
        if (current.known && current.required && current.external != null) {
            try {
                if (connection.awaitingExternal) {
                    finishExternal(connection, current);
                    if (connection.awaitingExternal && System.currentTimeMillis() >= connection.externalDeadline) kick(connection, current.external.displayName() + " 同步超时，请检查其注册限制与登录设置。");
                } else if (connection.authentication.authenticated && !current.external.authenticated(player)) { begin(player); return; }
            } catch (ReflectiveOperationException | RuntimeException | java.io.IOException ex) {
                kick(connection, externalFailure(current.external, ex, "登录状态不可用，请联系管理员。"));
            }
        }
        if (locked(player) && System.currentTimeMillis() >= connection.deadline) kick(connection, "登录超时，请重新进入服务器。");
    }
    static String commandName(String message) {
        String first = message.split("\\s", 2)[0].toLowerCase(Locale.ROOT);
        if (first.startsWith("/")) first = first.substring(1);
        if (first.startsWith("starbridge:")) first = first.substring(11);
        if (first.equals("l")) return "login";
        if (first.equals("ql")) return "qqlogin";
        return first;
    }
    private void login(Player player, String name, String arg) {
        Policy current = policy;
        if (!current.known) { player.sendMessage("正在同步认证设置，请稍后重试。"); return; }
        if (!current.required) { player.sendMessage("此服务器没有启用Myrinbot游戏登录。"); return; }
        Connection connection = connections.get(BukkitCompatibility.identity(player));
        if (connection == null || connection.player != player || connection.proof && connection.proofGeneration != current.generation) { begin(player); return; }
        if (!locked(player)) { player.sendMessage("你已经登录。"); return; }
        if (System.currentTimeMillis() - connection.lastCommand < 1000) return;
        connection.lastCommand = System.currentTimeMillis();
        boolean password = name.equals("login");
        if (password && !current.passwordLogin || !password && !current.qqLogin) { player.sendMessage("此登录方式没有开放。"); return; }
        if (password && (arg.length() < 8 || arg.length() > 128)) { player.sendMessage("正确格式：/login <8–128 字符密码> 或 /l <密码>，请勿在公共聊天中发送密码。"); return; }
        JsonObject data = connection.request(password ? "password" : "qq");
        if (password) data.addProperty("password", arg);
        submit(connection, data, false);
    }

    @EventHandler(priority=EventPriority.LOWEST)
    public void onCommand(PlayerCommandPreprocessEvent event) {
        Policy current = policy;
        String original = event.getMessage();
        String name = commandName(original);
        boolean explicitStarBridge = original.regionMatches(true, 0, "/starbridge:", 0, 12)
            || original.regionMatches(true, 0, "starbridge:", 0, 11);
        boolean own = name.equals("login") || name.equals("qqlogin");
        Connection connection = connections.get(BukkitCompatibility.identity(event.getPlayer()));
        if (name.equals("logout") && current.known && current.required) {
            event.setCancelled(true);
            try { if (current.external != null) current.external.logout(event.getPlayer()); }
            catch (ReflectiveOperationException | RuntimeException | java.io.IOException ex) {
                event.getPlayer().kickPlayer(externalFailure(current.external, ex, "退出登录失败，请重新连接。")); return;
            }
            begin(event.getPlayer());
        } else if (!explicitStarBridge && current.known && current.required && current.external != null && current.external.ownershipCommands().contains(name)
                && connection != null && connection.proof && connection.proofGeneration == current.generation && connection.awaitingExternal) {
            // Permit only the selected adapter's fixed authentication commands after
            // independent Myrinbot proof. Native handlers still verify all credentials.
            event.setCancelled(false);
            return;
        } else if (own && (!current.known || current.required || !LoginLinks.hasExternal())) {
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
        Connection connection = connections.get(BukkitCompatibility.identity(event.getPlayer()));
        if (connection == null || connection.player != event.getPlayer() || !connections.remove(connection.uuid, connection)) return;
        Policy current = policy;
        if (!closed && current.known && current.required) {
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
        Connection connection = connections.get(BukkitCompatibility.identity(event.getPlayer()));
        boolean synchronizing = connection != null && connection.proof && connection.proofGeneration == policy.generation && connection.awaitingExternal
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
    public void onDrop(PlayerDropItemEvent event) { if (locked(event.getPlayer())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onProjectile(ProjectileLaunchEvent event) { if (BukkitCompatibility.shooter(event.getEntity()) instanceof Player && locked((Player) BukkitCompatibility.shooter(event.getEntity()))) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onFish(PlayerFishEvent event) { if (locked(event.getPlayer())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onInventory(InventoryClickEvent event) { if (event.getWhoClicked() instanceof Player && locked((Player) event.getWhoClicked())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onInventoryOpen(InventoryOpenEvent event) { if (event.getPlayer() instanceof Player && locked((Player) event.getPlayer())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onVehicle(VehicleEnterEvent event) { if (event.getEntered() instanceof Player && locked((Player) event.getEntered())) event.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onDamage(EntityDamageEvent event) {
        if (event.getEntity() instanceof Player && locked((Player) event.getEntity())) event.setCancelled(true);
        if (event instanceof EntityDamageByEntityEvent) {
            EntityDamageByEntityEvent hit = (EntityDamageByEntityEvent) event;
            if (hit.getDamager() instanceof Player && locked((Player) hit.getDamager())) hit.setCancelled(true);
            if (hit.getDamager() instanceof Projectile) {
                Object shooter = BukkitCompatibility.shooter((Projectile) hit.getDamager());
                if (shooter instanceof Player && locked((Player) shooter)) hit.setCancelled(true);
            }
        }
    }
    private void gateOptional(Event event, String getter) {
        Object actor = BukkitCompatibility.eventValue(event, getter);
        if (actor instanceof Player && locked((Player) actor)) ((Cancellable) event).setCancelled(true);
    }

    synchronized void close() {
        closed = true;
        loginLinks.close();
        workers.shutdownNow();
        // Folia rejects tasks submitted by a disabled plugin, and onDisable does
        // not own player regions. Use a server restart when changing login plugins.
        Policy current = policy;
        if (!BridgeScheduler.isFolia() && (!current.known || current.required))
            for (Player player : BukkitCompatibility.players()) player.kickPlayer("游戏认证插件已停止，请稍后重新连接。");
        connections.clear(); restoreCommandLogs();
    }
}
