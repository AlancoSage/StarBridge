package cn.starbridge;

import com.google.gson.*;
import org.bukkit.Bukkit;
import org.bukkit.OfflinePlayer;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.command.ConsoleCommandSender;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.player.AsyncPlayerChatEvent;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.plugin.java.JavaPlugin;

import java.lang.reflect.Proxy;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

public final class StarBridgePlugin extends JavaPlugin implements Listener {
    private final Gson gson = new Gson();
    private final LinkedBlockingDeque<JsonObject> events = new LinkedBlockingDeque<>(500);
    private final LinkedBlockingDeque<JsonObject> results = new LinkedBlockingDeque<>(500);
    private final Set<String> inFlight = ConcurrentHashMap.newKeySet();
    // Only the global scheduler owns completed jobs; entity callbacks return through it.
    private final LinkedHashMap<String, JsonObject> completed = new LinkedHashMap<>();
    private final Map<UUID, Long> bindingCooldown = new ConcurrentHashMap<>();
    private final Map<UUID, OfflinePlayer> knownPlayers = new ConcurrentHashMap<>();
    private final Map<UUID, Long> lastPlayed = new ConcurrentHashMap<>();
    private final Map<UUID, String> lastAddresses = new ConcurrentHashMap<>();
    private final Map<UUID, Player> livePlayers = new ConcurrentHashMap<>();
    private final Map<UUID, Player> pendingSnapshots = new ConcurrentHashMap<>();
    private final Map<UUID, PlayerState> playerStates = new ConcurrentHashMap<>();
    private final Object playerLifecycle = new Object();
    private volatile boolean stopping;
    private static final class PlayerState {
        final Player connection;
        final JsonObject record;
        PlayerState(Player connection, JsonObject record) { this.connection = connection; this.record = record; }
    }
    private List<OfflinePlayer> recentPlayers = Collections.emptyList();
    private long nextCatalogUpdate;
    private volatile Set<String> allowedCommands;
    private ScheduledExecutorService io;
    private ThreadPoolExecutor identities;
    private String base, token;
    private String serverId;
    private volatile JsonObject snapshot = new JsonObject();
    private long lastWarning;
    private GameLogin login;
    private PasswordReset passwordReset;
    private PasswordReset.Startup passwordResetStartup = PasswordReset.Startup.disabled();

    @Override public void onLoad() { passwordResetStartup = PasswordReset.Startup.capture(this); }

    @Override public void onEnable() {
        stopping = false;
        saveDefaultConfig();
        String endpoint = getConfig().getString("endpoint", "").replaceAll("/+$", "");
        String sid = getConfig().getString("server-id", "");
        token = getConfig().getString("token", "");
        try {
            URI uri = URI.create(endpoint);
            if (!("http".equals(uri.getScheme()) || "https".equals(uri.getScheme())) || uri.getHost() == null
                || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null
                || !sid.matches("[A-Za-z0-9_-]{1,40}") || token.length() < 24 || token.startsWith("CHANGE-ME")) {
                throw new IllegalArgumentException();
            }
        } catch (IllegalArgumentException ex) {
            getLogger().severe("请先设置 plugins/StarBridge/config.yml 的 endpoint、server-id 和 token，再重启服务器。");
            Bukkit.getPluginManager().disablePlugin(this);
            return;
        }
        base = endpoint + "/bridge/" + sid;
        serverId = sid;
        allowedCommands = Collections.unmodifiableSet(new HashSet<>(getConfig().getStringList("allowed-commands")));
        io = Executors.newSingleThreadScheduledExecutor(r -> { Thread t = new Thread(r, "Myrinbot-HTTP"); t.setDaemon(true); return t; });
        identities = new ThreadPoolExecutor(2, 2, 0, TimeUnit.SECONDS, new ArrayBlockingQueue<Runnable>(64),
            r -> { Thread t = new Thread(r, "Myrinbot-Identity"); t.setDaemon(true); return t; });
        login = new GameLogin(this, this::post);
        try { passwordReset = new PasswordReset(this, this::post, passwordResetStartup); }
        catch (java.io.IOException unavailable) { getLogger().warning("原生密码重置证明文件不可用，已停用密码重置与绑定。请检查游戏端数据目录。"); }
        Bukkit.getPluginManager().registerEvents(this, this);
        Objects.requireNonNull(getCommand("qbind")).setExecutor(this);
        for (OfflinePlayer p : Bukkit.getOfflinePlayers()) knownPlayers.put(BukkitCompatibility.identity(p), p);
        for (OfflinePlayer p : Bukkit.getWhitelistedPlayers()) knownPlayers.put(BukkitCompatibility.identity(p), p);
        for (OfflinePlayer p : knownPlayers.values()) lastPlayed.put(BukkitCompatibility.identity(p), BukkitCompatibility.lastPlayed(p));
        BukkitCompatibility.runTask(this, this::updateSnapshot);
        BukkitCompatibility.repeat(this, this::updateSnapshot, 20, 20);
        io.scheduleWithFixedDelay(this::tick, 0, 1, TimeUnit.SECONDS);
        getLogger().info("Myrinbot已启动，将连接 " + endpoint + "，使用 /qbind 获取绑定码。");
    }

    @Override public void onDisable() {
        synchronized (playerLifecycle) {
            stopping = true;
            livePlayers.clear(); pendingSnapshots.clear(); playerStates.clear(); knownPlayers.clear();
            recentPlayers = Collections.emptyList();
            inFlight.clear();
        }
        if (login != null) login.close();
        if (passwordReset != null) passwordReset.close();
        if (io != null) io.shutdownNow();
        if (identities != null) identities.shutdownNow();
        BridgeScheduler.cancel(this);
    }

    private void updateSnapshot() {
        if (passwordReset != null) passwordReset.refresh();
        if (BridgeScheduler.isFolia()) { updateFoliaSnapshot(); return; }
        JsonObject value = new JsonObject();
        JsonArray players = new JsonArray();
        List<Player> online = BukkitCompatibility.players();
        Map<UUID, Player> onlineByIdentity = new HashMap<>();
        for (Player p : online) {
            UUID identity = BukkitCompatibility.identity(p);
            players.add(new JsonPrimitive(p.getName()));
            knownPlayers.put(identity, p);
            onlineByIdentity.put(identity, p);
            if (p.getAddress() != null && p.getAddress().getAddress() != null)
                lastAddresses.put(identity, p.getAddress().getAddress().getHostAddress());
        }
        if (System.currentTimeMillis() >= nextCatalogUpdate) {
            List<OfflinePlayer> ordered = new ArrayList<>(knownPlayers.values());
            ordered.removeIf(p -> p.getName() == null || !p.getName().matches("[A-Za-z0-9_]{1,16}"));
            ordered.sort(Comparator.comparing((OfflinePlayer p) -> !p.isOnline())
                .thenComparing(Comparator.comparingLong((OfflinePlayer p) -> lastPlayed.getOrDefault(BukkitCompatibility.identity(p), 0L)).reversed()));
            recentPlayers = ordered;
            nextCatalogUpdate = System.currentTimeMillis() + 10000;
        }
        JsonArray records = new JsonArray();
        for (OfflinePlayer p : recentPlayers.subList(0, Math.min(500, recentPlayers.size()))) {
            JsonObject record = new JsonObject();
            UUID identity = BukkitCompatibility.identity(p);
            record.addProperty("uuid", identity.toString()); record.addProperty("name", p.getName());
            record.addProperty("online", p.isOnline()); record.addProperty("banned", p.isBanned());
            record.addProperty("whitelisted", p.isWhitelisted()); record.addProperty("op", p.isOp());
            record.addProperty("last_played", p.isOnline() ? System.currentTimeMillis() : lastPlayed.getOrDefault(identity, 0L));
            record.addProperty("ip", lastAddresses.getOrDefault(identity, ""));
            Player current = onlineByIdentity.get(identity);
            if (current != null && current.isOnline()) {
                record.addProperty("world", current.getWorld().getName());
                record.addProperty("game_mode", current.getGameMode().name());
                Double health = BukkitCompatibility.health(current);
                Integer ping = BukkitCompatibility.ping(current);
                if (health != null) record.addProperty("health", health);
                if (ping != null) record.addProperty("ping", ping);
            }
            records.add(record);
        }
        value.add("player_records", records);
        value.add("capabilities", gson.toJsonTree(Arrays.asList("player_management", "game_authentication", "whitelist_application", "managed_sanctions")));
        value.addProperty("java_version", System.getProperty("java.version", "unknown"));
        value.addProperty("server_software", Bukkit.getName());
        value.add("auth_sessions", login.snapshot());
        value.addProperty("players_truncated", recentPlayers.size() > 500);
        value.addProperty("whitelist_enabled", Bukkit.hasWhitelist());
        value.add("players", players);
        value.addProperty("max_players", Bukkit.getMaxPlayers());
        value.addProperty("version", Bukkit.getBukkitVersion());
        snapshot = value;
    }

    /** Player fields are copied on their owning region; the global region only assembles copies. */
    private void capturePlayer(Player player) {
        UUID identity = BukkitCompatibility.identity(player);
        if (stopping || livePlayers.get(identity) != player || !player.isOnline()) return;
        JsonObject record = new JsonObject();
        record.addProperty("op", player.isOp());
        record.addProperty("whitelisted", player.isWhitelisted());
        record.addProperty("world", player.getWorld().getName());
        record.addProperty("game_mode", player.getGameMode().name());
        Double health = BukkitCompatibility.health(player);
        Integer ping = BukkitCompatibility.ping(player);
        if (health != null) record.addProperty("health", health);
        if (ping != null) record.addProperty("ping", ping);
        String address = player.getAddress() != null && player.getAddress().getAddress() != null
            ? player.getAddress().getAddress().getHostAddress() : "";
        synchronized (playerLifecycle) {
            if (!stopping && livePlayers.get(identity) == player) {
                lastAddresses.put(identity, address);
                playerStates.put(identity, new PlayerState(player, record));
            }
        }
    }

    private void updateFoliaSnapshot() {
        if (stopping) return;
        Map<UUID, Player> online = new HashMap<>();
        JsonArray names = new JsonArray();
        for (Player player : BukkitCompatibility.players()) {
            UUID identity = BukkitCompatibility.identity(player);
            online.put(identity, player);
            synchronized (playerLifecycle) {
                if (stopping) return;
                if (livePlayers.putIfAbsent(identity, player) == null || !knownPlayers.containsKey(identity))
                    knownPlayers.put(identity, BukkitCompatibility.offline(identity, player.getName()));
            }
            names.add(new JsonPrimitive(player.getName()));
            if (pendingSnapshots.putIfAbsent(identity, player) == null) {
                BukkitCompatibility.runPlayer(this, player, () -> {
                    try { capturePlayer(player); }
                    finally { pendingSnapshots.remove(identity, player); }
                }, () -> pendingSnapshots.remove(identity, player));
            }
        }
        List<OfflinePlayer> ordered = new ArrayList<>(knownPlayers.values());
        ordered.removeIf(p -> p.getName() == null || !p.getName().matches("[A-Za-z0-9_]{1,16}"));
        ordered.sort(Comparator.comparing((OfflinePlayer p) -> !online.containsKey(BukkitCompatibility.identity(p)))
            .thenComparing(Comparator.comparingLong((OfflinePlayer p) -> lastPlayed.getOrDefault(BukkitCompatibility.identity(p), 0L)).reversed()));
        JsonArray records = new JsonArray();
        for (OfflinePlayer player : ordered.subList(0, Math.min(500, ordered.size()))) {
            UUID identity = BukkitCompatibility.identity(player);
            Player current = online.get(identity);
            PlayerState state = playerStates.get(identity);
            // The backend requires a complete record. A new entity's first capture may still
            // be queued; publish its name now and its details on the next complete snapshot.
            if (current != null && (state == null || state.connection != current)) continue;
            if (current == null && player instanceof Player) {
                OfflinePlayer offline = BukkitCompatibility.offline(identity, player.getName());
                if (offline instanceof Player) continue; // Player list is still completing a transition.
                knownPlayers.put(identity, offline);
                player = offline;
            }
            JsonObject record = new JsonObject();
            record.addProperty("uuid", identity.toString()); record.addProperty("name", player.getName());
            record.addProperty("online", current != null); record.addProperty("banned", BukkitCompatibility.foliaBanned(identity, player.getName()));
            if (current == null && !(player instanceof Player)) {
                record.addProperty("whitelisted", player.isWhitelisted()); record.addProperty("op", player.isOp());
            }
            record.addProperty("last_played", current != null ? System.currentTimeMillis() : lastPlayed.getOrDefault(identity, 0L));
            record.addProperty("ip", lastAddresses.getOrDefault(identity, ""));
            if (current != null && state != null && state.connection == current) {
                for (Map.Entry<String, JsonElement> field : state.record.entrySet()) record.add(field.getKey(), field.getValue().deepCopy());
            }
            records.add(record);
        }
        JsonObject value = new JsonObject();
        value.add("player_records", records);
        value.add("players", names);
        value.add("capabilities", gson.toJsonTree(Arrays.asList("player_management", "game_authentication", "whitelist_application", "managed_sanctions")));
        value.addProperty("java_version", System.getProperty("java.version", "unknown"));
        value.addProperty("server_software", Bukkit.getName());
        value.add("auth_sessions", login.snapshot());
        value.addProperty("players_truncated", ordered.size() > 500);
        value.addProperty("whitelist_enabled", Bukkit.hasWhitelist());
        value.addProperty("max_players", Bukkit.getMaxPlayers());
        value.addProperty("version", Bukkit.getBukkitVersion());
        synchronized (playerLifecycle) { if (!stopping) snapshot = value; }
    }

    private JsonObject post(String route, JsonObject data) throws Exception {
        BridgeHttp.Response response = BridgeHttp.request(base + route, token, gson.toJson(data),
            route.equals("/auth") ? 16000 : route.equals("/password-reset/claim") ? 3000 : 6000);
        if (response.status != 200) {
            if (route.equals("/auth")) {
                try {
                    JsonObject error = JsonParser.parseString(response.body).getAsJsonObject();
                    if (error.has("error")) return error;
                } catch (RuntimeException ignored) { }
            }
            throw new IllegalStateException("HTTP " + response.status);
        }
        return JsonParser.parseString(response.body).getAsJsonObject();
    }

    private List<JsonObject> batch(LinkedBlockingDeque<JsonObject> queue) {
        return queue.stream().limit(50).collect(Collectors.toList());
    }

    private void tick() {
        try {
            // Old chat is deliberately not replayed after a long outage.
            long now = System.currentTimeMillis();
            events.removeIf(e -> now - e.get("queued_at").getAsLong() > 30000);
            List<JsonObject> eventBatch = batch(events), resultBatch = batch(results);
            JsonObject payload = snapshot.deepCopy();
            payload.add("events", gson.toJsonTree(eventBatch));
            payload.add("results", gson.toJsonTree(resultBatch));
            JsonObject response = post("/tick", payload);
            if (isEnabled()) BukkitCompatibility.runTask(this, () -> login.accept(response));
            if (response.has("allowed_commands")) {
                Set<String> configured = new HashSet<>();
                for (JsonElement item : response.getAsJsonArray("allowed_commands")) configured.add(item.getAsString());
                allowedCommands = Collections.unmodifiableSet(configured);
            }
            eventBatch.forEach(events::removeFirstOccurrence);
            resultBatch.forEach(results::removeFirstOccurrence);
            for (JsonElement element : response.getAsJsonArray("jobs")) {
                JsonObject job = element.getAsJsonObject();
                String id = job.get("id").getAsString();
                if (inFlight.add(id)) {
                    try { BukkitCompatibility.runTask(this, () -> execute(job)); }
                    catch (RuntimeException exception) { inFlight.remove(id); throw exception; }
                }
            }
            if (passwordReset != null) {
                try { passwordReset.tick(); }
                catch (Exception unavailable) { /* Optional older bot endpoints fail closed; never log provider/password data. */ }
            }
        } catch (Exception ex) {
            if (System.currentTimeMillis() - lastWarning > 30000) {
                getLogger().warning("桥接暂不可用：" + ex.getClass().getSimpleName() + " " + ex.getMessage());
                lastWarning = System.currentTimeMillis();
            }
        }
    }

    private void addResult(JsonObject result) {
        if (!results.offerLast(result)) {
            results.pollFirst(); results.offerLast(result);
            getLogger().warning("执行结果队列已满，已移除最旧记录。");
        }
    }

    private void execute(JsonObject job) {
        synchronized (playerLifecycle) {
            if (stopping || !isEnabled()) { inFlight.remove(job.get("id").getAsString()); return; }
            executeActive(job);
        }
    }

    private void executeActive(JsonObject job) {
        String id = job.get("id").getAsString();
        if (!completed.containsKey(id) && "whitelist_application".equals(job.get("kind").getAsString())
            && job.get("expires").getAsDouble() * 1000 >= System.currentTimeMillis()) {
            applyWhitelist(job);
            return; // Keep inFlight until the asynchronous identity lookup completes.
        }
        if (BridgeScheduler.isFolia() && !completed.containsKey(id)
                && job.get("expires").getAsDouble() * 1000 >= System.currentTimeMillis()) {
            String kind = job.get("kind").getAsString();
            if ("broadcast".equals(kind)) { broadcastFolia(job); return; }
            if ("player_action".equals(kind) && ("kick".equals(job.get("action").getAsString()) || "ban".equals(job.get("action").getAsString()))) {
                manageFoliaKick(job); return;
            }
        }
        try {
            if (completed.containsKey(id)) { addResult(completed.get(id)); return; }
            boolean ok = true;
            String detail;
            if (job.get("expires").getAsDouble() * 1000 < System.currentTimeMillis()) {
                ok = false; detail = "任务已过期，未执行";
            } else if ("broadcast".equals(job.get("kind").getAsString())) {
                String text = job.get("text").getAsString();
                Bukkit.broadcastMessage(text.substring(0, Math.min(text.length(), 600)));
                detail = "消息已同步";
            } else if ("command".equals(job.get("kind").getAsString())) {
                String command = job.get("command").getAsString();
                if (!allowedCommands.contains(command) || command.contains("\n") || command.contains("\r")) {
                    ok = false; detail = "插件拒绝执行：命令不在 allowed-commands 中";
                } else {
                    StringBuilder output = new StringBuilder();
                    ConsoleCommandSender console = Bukkit.getConsoleSender();
                    CommandSender capture = (CommandSender) Proxy.newProxyInstance(getClass().getClassLoader(),
                        new Class<?>[]{ConsoleCommandSender.class}, (proxy, method, args) -> {
                            if (method.getName().equals("sendMessage") && args != null) {
                                Object last = args[args.length - 1];
                                if (last instanceof String) append(output, (String) last);
                                else if (last instanceof String[]) for (String line : (String[]) last) append(output, line);
                                return null;
                            }
                            return method.invoke(console, args);
                        });
                    ok = Bukkit.dispatchCommand(capture, command);
                    detail = output.length() == 0 ? (ok ? "命令已交由服务器执行；无文本输出。" : "服务器未找到该命令。") : output.toString();
                }
            } else if ("player_action".equals(job.get("kind").getAsString())) {
                detail = managePlayer(job);
                try { updateSnapshot(); } catch (Exception ex) { getLogger().warning("玩家操作完成，等待下一次状态更新。"); }
            } else { ok = false; detail = "未知任务类型"; }
            JsonObject result = new JsonObject();
            result.addProperty("id", id); result.addProperty("ok", ok); result.addProperty("detail", detail);
            completed.put(id, result);
            if (completed.size() > 2000) completed.remove(completed.keySet().iterator().next());
            addResult(result);
        } catch (Exception ex) {
            JsonObject result = new JsonObject();
            result.addProperty("id", id); result.addProperty("ok", false);
            result.addProperty("detail", "插件执行异常：" + ex.getClass().getSimpleName());
            completed.put(id, result); addResult(result);
            getLogger().warning("任务执行失败：" + ex.getClass().getSimpleName());
        } finally { inFlight.remove(id); }
    }

    private void finishJob(String id, boolean ok, String detail) {
        if (stopping) { inFlight.remove(id); return; }
        JsonObject result = new JsonObject();
        result.addProperty("id", id); result.addProperty("ok", ok); result.addProperty("detail", detail);
        completed.put(id, result);
        if (completed.size() > 2000) completed.remove(completed.keySet().iterator().next());
        addResult(result); inFlight.remove(id);
    }

    private void finishFromPlayer(String id, boolean ok, String detail) {
        if (!stopping && isEnabled()) BukkitCompatibility.runTask(this, () -> finishJob(id, ok, detail));
        else inFlight.remove(id);
    }

    private void broadcastFolia(JsonObject job) {
        String id = job.get("id").getAsString();
        String raw = job.get("text").getAsString();
        String text = raw.substring(0, Math.min(raw.length(), 600));
        List<Player> recipients = BukkitCompatibility.players();
        if (recipients.isEmpty()) { finishJob(id, true, "消息已同步（当前没有在线玩家）"); return; }
        AtomicInteger remaining = new AtomicInteger(recipients.size()), failures = new AtomicInteger();
        Runnable done = () -> {
            if (remaining.decrementAndGet() == 0)
                finishFromPlayer(id, failures.get() == 0, failures.get() == 0 ? "消息已同步" : "部分玩家消息未发送：任务过期或玩家线程不可用");
        };
        for (Player player : recipients) BukkitCompatibility.runPlayer(this, player, () -> {
            try {
              synchronized (playerLifecycle) {
                if (stopping || !isEnabled()) { failures.incrementAndGet(); return; }
                if (job.get("expires").getAsDouble() * 1000 < System.currentTimeMillis()) failures.incrementAndGet();
                else if (player.isOnline() && player.hasPermission("bukkit.broadcast.user")) player.sendMessage(text);
              }
            } catch (RuntimeException ex) { failures.incrementAndGet(); }
            finally { done.run(); }
        }, () -> { failures.incrementAndGet(); done.run(); });
    }

    private void manageFoliaKick(JsonObject job) {
        String id = job.get("id").getAsString();
        try {
            String detail = managePlayer(job, true);
            UUID identity = UUID.fromString(job.get("uuid").getAsString());
            Player player = BukkitCompatibility.player(identity);
            boolean ban = "ban".equals(job.get("action").getAsString());
            if (player == null) { finishJob(id, ban, ban ? detail : "玩家已离线，请刷新后重试"); return; }
            String configured = job.has("reason") ? job.get("reason").getAsString() : "";
            String reason = configured.trim().isEmpty() ? "服务器管理员通过Myrinbot执行操作" : configured;
            String kickReason = ban && job.has("kick_reason") ? job.get("kick_reason").getAsString() : reason;
            BukkitCompatibility.runPlayer(this, player, () -> {
                try {
                  synchronized (playerLifecycle) {
                    if (stopping || !isEnabled()) { inFlight.remove(id); return; }
                    if (!ban && job.get("expires").getAsDouble() * 1000 < System.currentTimeMillis()) {
                        finishFromPlayer(id, false, "任务已过期，未踢出玩家"); return;
                    }
                    if (!player.isOnline() || BukkitCompatibility.player(identity) != player) {
                        finishFromPlayer(id, ban, ban ? detail : "玩家已离线或连接已变化，请刷新后重试"); return;
                    }
                    player.kickPlayer(kickReason);
                    finishFromPlayer(id, true, detail);
                  }
                } catch (RuntimeException ex) { finishFromPlayer(id, ban, ban ? detail + "；断开连接失败，请检查游戏端" : "踢出失败，请检查游戏端"); }
            }, () -> finishFromPlayer(id, ban, ban ? detail : "玩家已离线，未执行踢出"));
        } catch (RuntimeException ex) { finishJob(id, false, "玩家操作失败：" + ex.getClass().getSimpleName()); }
    }

    private String managePlayer(JsonObject job) {
        return managePlayer(job, false);
    }

    private String managePlayer(JsonObject job, boolean deferKick) {
        UUID identity = UUID.fromString(job.get("uuid").getAsString());
        String name = job.get("player").getAsString();
        String action = job.get("action").getAsString();
        String reason = job.has("reason") ? job.get("reason").getAsString() : "";
        if (!name.matches("[A-Za-z0-9_]{1,16}") || reason.length() > 340
            || reason.chars().anyMatch(c -> c < 32 || c == 127)) throw new IllegalArgumentException("Invalid player action");
        OfflinePlayer target = knownPlayers.get(identity);
        if (target == null || !name.equals(target.getName())) throw new IllegalArgumentException("玩家身份已变化，请刷新后重试");
        Player online = BukkitCompatibility.player(identity);
        if (reason.trim().isEmpty()) reason = "服务器管理员通过Myrinbot执行操作";
        switch (action) {
            case "kick":
                if (online == null || !deferKick && !online.isOnline()) throw new IllegalStateException("玩家已离线，请刷新后重试");
                if (!deferKick) online.kickPlayer(reason);
                return "已踢出 " + name;
            case "ban":
                if (BridgeScheduler.isFolia()) BukkitCompatibility.foliaBan(identity, name, reason);
                else BukkitCompatibility.ban(target, reason);
                if (!deferKick && online != null && online.isOnline()) online.kickPlayer(job.has("kick_reason") ? job.get("kick_reason").getAsString() : reason);
                return "已永久封禁 " + name;
            case "unban":
                boolean banned = BridgeScheduler.isFolia() ? BukkitCompatibility.foliaBanned(identity, name) : target.isBanned();
                String banReason = BridgeScheduler.isFolia() ? BukkitCompatibility.foliaBanReason(identity, name) : BukkitCompatibility.banReason(target);
                String banSource = BridgeScheduler.isFolia() ? BukkitCompatibility.foliaBanSource(identity, name) : BukkitCompatibility.banSource(target);
                if (job.has("expected_ban_reason") && banned
                    && (!job.get("expected_ban_reason").getAsString().equals(banReason) || !"StarBridge".equals(banSource)))
                    throw new IllegalStateException("当前封禁属于其他处罚，或核心无法校验封禁来源；未自动解除");
                if (BridgeScheduler.isFolia()) BukkitCompatibility.foliaUnban(identity, name);
                else BukkitCompatibility.unban(target);
                return "已解除 " + name + " 的封禁";
            case "whitelist_add":
            case "whitelist_remove":
                boolean value = action.equals("whitelist_add");
                target.setWhitelisted(value);
                if (target.isWhitelisted() != value) throw new IllegalStateException("Whitelist update failed");
                return name + (value ? " 已加入白名单" : " 已移出白名单");
            default: throw new IllegalArgumentException("Unsupported player action");
        }
    }

    private void applyWhitelist(JsonObject job) {
        String id = job.get("id").getAsString();
        String name = job.get("player").getAsString();
        if (!name.matches("[A-Za-z0-9_]{1,16}")) {
            finishWhitelist(id, false, "玩家名格式错误"); return;
        }
        UUID supplied = null;
        try {
            if (job.has("uuid") && !job.get("uuid").getAsString().trim().isEmpty()) supplied = UUID.fromString(job.get("uuid").getAsString());
        } catch (IllegalArgumentException ex) { finishWhitelist(id, false, "玩家 UUID 格式错误"); return; }
        if (!Bukkit.getOnlineMode()) {
            UUID identity = supplied != null ? supplied : UUID.nameUUIDFromBytes(("OfflinePlayer:" + name).getBytes(StandardCharsets.UTF_8));
            completeWhitelist(job, identity, name);
            return;
        }
        // Official lookup stays on a bounded worker; no network access on the game thread.
        if (!BukkitCompatibility.nativeIdentities() && supplied != null && !supplied.equals(BukkitCompatibility.legacyIdentity(name))) {
            finishWhitelist(id, false, "旧版服务器的玩家名与标识不匹配"); return;
        }
        final UUID expected = BukkitCompatibility.nativeIdentities() ? supplied : null;
        try {
            identities.execute(() -> {
                BukkitCompatibility.Profile profile = null;
                Exception failure = null;
                try { profile = BukkitCompatibility.lookupProfile(name, expected); }
                catch (Exception exception) { failure = exception; }
                if (!isEnabled()) { inFlight.remove(id); return; }
                final BukkitCompatibility.Profile answer = profile;
                final Exception error = failure;
                BukkitCompatibility.runTask(this, () -> {
                    if (error != null || answer == null) finishWhitelist(id, false, "正版玩家身份查询失败、超时或不匹配，请核对玩家名后重试");
                    else completeWhitelist(job, answer.identity, answer.name);
                });
            });
        } catch (RejectedExecutionException ex) { finishWhitelist(id, false, "正版身份查询繁忙，请稍后重试"); }
    }

    private void completeWhitelist(JsonObject job, UUID identity, String name) {
        synchronized (playerLifecycle) {
            if (stopping || !isEnabled()) { inFlight.remove(job.get("id").getAsString()); return; }
            completeWhitelistActive(job, identity, name);
        }
    }

    private void completeWhitelistActive(JsonObject job, UUID identity, String name) {
        String id = job.get("id").getAsString();
        try {
            if (job.get("expires").getAsDouble() * 1000 < System.currentTimeMillis()) {
                finishWhitelist(id, false, "任务已过期，未加入白名单"); return;
            }
            OfflinePlayer target = BukkitCompatibility.offline(identity, name);
            if (BridgeScheduler.isFolia() ? BukkitCompatibility.foliaBanned(identity, name) : target.isBanned()) {
                finishWhitelist(id, false, "玩家已被服务器封禁，未加入白名单"); return;
            }
            target.setWhitelisted(true);
            if (!target.isWhitelisted()) throw new IllegalStateException("Whitelist write failed");
            UUID serverIdentity = BukkitCompatibility.identity(target);
            knownPlayers.put(serverIdentity, target); nextCatalogUpdate = 0;
            finishWhitelist(id, true, name + " 已加入白名单（" + serverIdentity + "）");
            try { updateSnapshot(); } catch (RuntimeException ex) { getLogger().warning("白名单更新成功，等待下一次状态上报。"); }
        } catch (RuntimeException ex) { finishWhitelist(id, false, "白名单更新失败，请检查游戏端日志"); }
    }

    private void finishWhitelist(String id, boolean ok, String detail) {
        JsonObject result = new JsonObject();
        result.addProperty("id", id); result.addProperty("ok", ok); result.addProperty("detail", detail);
        completed.put(id, result);
        if (completed.size() > 2000) completed.remove(completed.keySet().iterator().next());
        addResult(result); inFlight.remove(id);
    }

    private static void append(StringBuilder output, String text) {
        int remaining = 1500 - output.length();
        if (remaining > 0) output.append(text, 0, Math.min(text.length(), remaining)).append('\n');
    }

    private void event(String kind, String player, String text) {
        JsonObject data = new JsonObject();
        data.addProperty("id", UUID.randomUUID().toString());
        data.addProperty("kind", kind); data.addProperty("player", player);
        data.addProperty("text", text.substring(0, Math.min(text.length(), 500)));
        data.addProperty("queued_at", System.currentTimeMillis());
        if (!events.offerLast(data)) { events.pollFirst(); events.offerLast(data); }
    }

    private void joined(Player player) {
        JsonObject data = new JsonObject();
        data.addProperty("id", UUID.randomUUID().toString());
        data.addProperty("kind", "join"); data.addProperty("player", player.getName());
        data.addProperty("uuid", BukkitCompatibility.identity(player).toString()); data.addProperty("text", "");
        if (player.getAddress() != null && player.getAddress().getAddress() != null)
            data.addProperty("ip", player.getAddress().getAddress().getHostAddress());
        data.addProperty("queued_at", System.currentTimeMillis());
        if (!events.offerLast(data)) { events.pollFirst(); events.offerLast(data); }
    }

    @EventHandler(priority=EventPriority.MONITOR, ignoreCancelled=true)
    public void onChat(AsyncPlayerChatEvent event) { event("chat", event.getPlayer().getName(), event.getMessage()); }
    @EventHandler public void onJoin(PlayerJoinEvent event) {
        if (BridgeScheduler.isFolia()) {
            Player player = event.getPlayer();
            synchronized (playerLifecycle) {
                if (stopping) return;
                livePlayers.put(BukkitCompatibility.identity(player), player);
            }
            capturePlayer(player);
        }
        lastPlayed.put(BukkitCompatibility.identity(event.getPlayer()), System.currentTimeMillis());
        BukkitCompatibility.runTask(this, () -> nextCatalogUpdate = 0);
        joined(event.getPlayer());
    }
    @EventHandler public void onQuit(PlayerQuitEvent event) {
        Player player = event.getPlayer();
        UUID identity = BukkitCompatibility.identity(player);
        String name = player.getName();
        bindingCooldown.remove(identity);
        livePlayers.remove(identity, player);
        playerStates.computeIfPresent(identity, (uuid, state) -> state.connection == player ? null : state);
        pendingSnapshots.remove(identity, player);
        lastPlayed.put(identity, System.currentTimeMillis());
        BukkitCompatibility.runTask(this, () -> {
            knownPlayers.put(identity, BukkitCompatibility.offline(identity, name));
            nextCatalogUpdate = 0;
        });
        event("quit", name, "");
    }

    @Override public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!(sender instanceof Player)) { sender.sendMessage("请在游戏内执行 /qbind。"); return true; }
        Player player = (Player) sender;
        if (!command.getName().equalsIgnoreCase("qbind")) {
            player.sendMessage("此服务器没有启用Myrinbot游戏登录。"); return true;
        }
        if (login.locked(player)) { player.sendMessage("请先完成游戏登录，再获取绑定码。"); return true; }
        if (passwordReset == null) { player.sendMessage("绑定的原生账号核验不可用，请联系管理员检查游戏端数据目录。"); return true; }
        final PasswordReset.Proof resetProof;
        try { resetProof = passwordReset.bindingProof(player); }
        catch (Exception | LinkageError unavailable) { player.sendMessage("请先完成原登录插件的认证，再获取绑定码；若已登录，请联系管理员检查登录插件兼容性。"); return true; }
        UUID playerId = BukkitCompatibility.identity(player);
        String connectionNonce = login.nonce(player);
        long now = System.currentTimeMillis();
        if (now - bindingCooldown.getOrDefault(playerId, 0L) < 20000) { player.sendMessage("请等待 20 秒再获取验证码。"); return true; }
        bindingCooldown.put(playerId, now);
        String name = player.getName();
        player.sendMessage("正在获取绑定验证码……");
        io.execute(() -> {
            String message;
            try {
                JsonObject data = new JsonObject(); data.addProperty("uuid", playerId.toString()); data.addProperty("player", name); data.addProperty("nonce", connectionNonce);
                if (resetProof != null) resetProof.addTo(data);
                JsonObject binding = post("/bind-code", data);
                String code = binding.get("code").getAsString();
                if (resetProof != null)
                    message = "密码找回验证请私聊 QQ 机器人发送：/验证绑定 " + serverId + " " + code
                        + "（5 分钟有效，原绑定无需解绑，请勿转发）。仅做普通绑定（如 QQ 官机），可在服务器群发送：绑定 " + code + "；不会开放改密权限。";
                else message = "请在服务器 QQ 群发送：绑定 " + code + "（5 分钟有效，请勿转发给他人）";
            } catch (Exception ex) { message = "获取验证码失败，请联系管理员检查Myrinbot连接。"; }
            String result = message;
            if (isEnabled()) BukkitCompatibility.runPlayer(this, player, () -> {
                if (player.isOnline() && BukkitCompatibility.player(playerId) == player && connectionNonce.equals(login.nonce(player)) && !login.locked(player)) player.sendMessage(result);
            }, () -> { });
        });
        return true;
    }
}
