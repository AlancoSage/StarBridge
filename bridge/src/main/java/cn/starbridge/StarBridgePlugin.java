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
import java.util.stream.Collectors;

public final class StarBridgePlugin extends JavaPlugin implements Listener {
    private final Gson gson = new Gson();
    private final LinkedBlockingDeque<JsonObject> events = new LinkedBlockingDeque<>(500);
    private final LinkedBlockingDeque<JsonObject> results = new LinkedBlockingDeque<>(500);
    private final Set<String> inFlight = ConcurrentHashMap.newKeySet();
    // Accessed only on the game thread; prevents retries from executing twice in this session.
    private final LinkedHashMap<String, JsonObject> completed = new LinkedHashMap<>();
    private final Map<UUID, Long> bindingCooldown = new HashMap<>();
    private final Map<UUID, OfflinePlayer> knownPlayers = new HashMap<>();
    private final Map<UUID, Long> lastPlayed = new HashMap<>();
    private final Map<UUID, String> lastAddresses = new HashMap<>();
    private List<OfflinePlayer> recentPlayers = Collections.emptyList();
    private long nextCatalogUpdate;
    private volatile Set<String> allowedCommands;
    private ScheduledExecutorService io;
    private ThreadPoolExecutor identities;
    private String base, token;
    private volatile JsonObject snapshot = new JsonObject();
    private long lastWarning;
    private GameLogin login;

    @Override public void onEnable() {
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
        allowedCommands = Collections.unmodifiableSet(new HashSet<>(getConfig().getStringList("allowed-commands")));
        io = Executors.newSingleThreadScheduledExecutor(r -> { Thread t = new Thread(r, "StarBridge-HTTP"); t.setDaemon(true); return t; });
        identities = new ThreadPoolExecutor(2, 2, 0, TimeUnit.SECONDS, new ArrayBlockingQueue<Runnable>(64),
            r -> { Thread t = new Thread(r, "StarBridge-Identity"); t.setDaemon(true); return t; });
        login = new GameLogin(this, this::post);
        Bukkit.getPluginManager().registerEvents(this, this);
        Objects.requireNonNull(getCommand("qbind")).setExecutor(this);
        for (OfflinePlayer p : Bukkit.getOfflinePlayers()) knownPlayers.put(BukkitCompatibility.identity(p), p);
        for (OfflinePlayer p : Bukkit.getWhitelistedPlayers()) knownPlayers.put(BukkitCompatibility.identity(p), p);
        for (OfflinePlayer p : knownPlayers.values()) lastPlayed.put(BukkitCompatibility.identity(p), BukkitCompatibility.lastPlayed(p));
        updateSnapshot();
        BukkitCompatibility.repeat(this, this::updateSnapshot, 20, 20);
        io.scheduleWithFixedDelay(this::tick, 0, 1, TimeUnit.SECONDS);
        getLogger().info("星桥已启动，将连接 " + endpoint + "，使用 /qbind 获取绑定码。");
    }

    @Override public void onDisable() {
        if (login != null) login.close();
        if (io != null) io.shutdownNow();
        if (identities != null) identities.shutdownNow();
        Bukkit.getScheduler().cancelTasks(this);
    }

    private void updateSnapshot() {
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

    private JsonObject post(String route, JsonObject data) throws Exception {
        BridgeHttp.Response response = BridgeHttp.request(base + route, token, gson.toJson(data), route.equals("/auth") ? 16000 : 6000);
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
                if (inFlight.add(id)) BukkitCompatibility.runTask(this, () -> execute(job));
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
        String id = job.get("id").getAsString();
        if (!completed.containsKey(id) && "whitelist_application".equals(job.get("kind").getAsString())
            && job.get("expires").getAsDouble() * 1000 >= System.currentTimeMillis()) {
            applyWhitelist(job);
            return; // Keep inFlight until the asynchronous identity lookup completes.
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

    private String managePlayer(JsonObject job) {
        UUID identity = UUID.fromString(job.get("uuid").getAsString());
        String name = job.get("player").getAsString();
        String action = job.get("action").getAsString();
        String reason = job.has("reason") ? job.get("reason").getAsString() : "";
        if (!name.matches("[A-Za-z0-9_]{1,16}") || reason.length() > 340
            || reason.chars().anyMatch(c -> c < 32 || c == 127)) throw new IllegalArgumentException("Invalid player action");
        OfflinePlayer target = knownPlayers.get(identity);
        if (target == null || !name.equals(target.getName())) throw new IllegalArgumentException("玩家身份已变化，请刷新后重试");
        Player online = BukkitCompatibility.player(identity);
        if (reason.trim().isEmpty()) reason = "服务器管理员通过星桥执行操作";
        switch (action) {
            case "kick":
                if (online == null || !online.isOnline()) throw new IllegalStateException("玩家已离线，请刷新后重试");
                online.kickPlayer(reason);
                return "已踢出 " + name;
            case "ban":
                BukkitCompatibility.ban(target, reason);
                if (online != null && online.isOnline()) online.kickPlayer(job.has("kick_reason") ? job.get("kick_reason").getAsString() : reason);
                return "已永久封禁 " + name;
            case "unban":
                if (job.has("expected_ban_reason") && target.isBanned()
                    && !job.get("expected_ban_reason").getAsString().equals(BukkitCompatibility.banReason(target)))
                    throw new IllegalStateException("当前封禁属于其他处罚，或核心无法校验封禁来源；未自动解除");
                BukkitCompatibility.unban(target);
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
        String id = job.get("id").getAsString();
        try {
            if (job.get("expires").getAsDouble() * 1000 < System.currentTimeMillis()) {
                finishWhitelist(id, false, "任务已过期，未加入白名单"); return;
            }
            OfflinePlayer target = BukkitCompatibility.offline(identity, name);
            if (target.isBanned()) { finishWhitelist(id, false, "玩家已被服务器封禁，未加入白名单"); return; }
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
        lastPlayed.put(BukkitCompatibility.identity(event.getPlayer()), System.currentTimeMillis());
        nextCatalogUpdate = 0;
        joined(event.getPlayer());
    }
    @EventHandler public void onQuit(PlayerQuitEvent event) {
        bindingCooldown.remove(BukkitCompatibility.identity(event.getPlayer()));
        knownPlayers.put(BukkitCompatibility.identity(event.getPlayer()), BukkitCompatibility.offline(BukkitCompatibility.identity(event.getPlayer()), event.getPlayer().getName()));
        lastPlayed.put(BukkitCompatibility.identity(event.getPlayer()), System.currentTimeMillis());
        nextCatalogUpdate = 0;
        event("quit", event.getPlayer().getName(), "");
    }

    @Override public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!(sender instanceof Player)) { sender.sendMessage("请在游戏内执行 /qbind。"); return true; }
        Player player = (Player) sender;
        if (!command.getName().equalsIgnoreCase("qbind")) {
            player.sendMessage("此服务器没有启用星桥游戏登录。"); return true;
        }
        if (login.locked(player)) { player.sendMessage("请先完成游戏登录，再获取绑定码。"); return true; }
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
                String code = post("/bind-code", data).get("code").getAsString();
                message = "请在服务器 QQ 群发送：绑定 " + code + "（5 分钟有效，请勿转发给他人）";
            } catch (Exception ex) { message = "获取验证码失败，请联系管理员检查星桥连接。"; }
            String result = message;
            if (isEnabled()) BukkitCompatibility.runTask(this, () -> {
                Player current = BukkitCompatibility.player(playerId);
                if (current != null && current.isOnline() && connectionNonce.equals(login.nonce(current)) && !login.locked(current)) current.sendMessage(result);
            });
        });
        return true;
    }
}
