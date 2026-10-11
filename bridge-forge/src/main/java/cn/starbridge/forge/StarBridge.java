package cn.starbridge.forge;

import com.google.gson.*;
import com.mojang.authlib.GameProfile;
import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.logging.LogUtils;
import net.minecraft.commands.*;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.players.*;
import net.minecraft.world.level.storage.LevelResource;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.event.*;
import net.minecraftforge.event.entity.player.PlayerEvent;
import net.minecraftforge.event.entity.player.PlayerNegotiationEvent;
import net.minecraftforge.event.server.*;
import net.minecraftforge.eventbus.api.SubscribeEvent;
import net.minecraftforge.eventbus.api.EventPriority;
import net.minecraftforge.fml.ModLoadingContext;
import net.minecraftforge.fml.common.Mod;
import net.minecraftforge.fml.config.ModConfig;
import net.minecraftforge.fml.util.ObfuscationReflectionHelper;
import org.slf4j.Logger;

import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

/** No client classes, registries or custom network channel: dedicated-server bridge. */
@Mod("starbridge")
public final class StarBridge {
    static final Logger LOG = LogUtils.getLogger();
    private static final Gson JSON = new Gson();
    private volatile Session active;

    public StarBridge() {
        ModLoadingContext.get().registerConfig(ModConfig.Type.COMMON, Config.SPEC, "starbridge-common.toml");
        MinecraftForge.EVENT_BUS.register(this);
    }
    @SubscribeEvent public void started(ServerStartedEvent event) {
        MinecraftServer server = event.getServer();
        if (!server.isDedicatedServer()) return;
        try {
            Session session = new Session(server);
            active = session; session.start();
            LOG.info("Myrinbot Forge 1.20.1 游戏端已启动。");
        } catch (RuntimeException error) {
            // A configured login service must not silently become unprotected after a bad config.
            LOG.error("Myrinbot连接配置无效，已停止服务器。请设置 config/starbridge-common.toml 的 endpoint、server-id、token。错误类型：{}", error.getClass().getSimpleName());
            server.halt(false);
        }
    }
    @SubscribeEvent public void stopping(ServerStoppingEvent event) {
        Session session = active; active = null;
        if (session != null) session.close();
    }
    @SubscribeEvent public void serverTick(TickEvent.ServerTickEvent event) {
        Session session = active;
        if (session != null && event.phase == TickEvent.Phase.END) session.gameTick();
    }
    @SubscribeEvent public void joined(PlayerEvent.PlayerLoggedInEvent event) {
        Session session = active;
        if (session != null && event.getEntity() instanceof ServerPlayer player) {
            session.remember(player); session.event("join", player, ""); session.login.join(player);
        }
    }
    @SubscribeEvent public void negotiating(PlayerNegotiationEvent event) {
        Session session = active;
        if (session != null) session.login.negotiate(event);
    }
    @SubscribeEvent public void left(PlayerEvent.PlayerLoggedOutEvent event) {
        Session session = active;
        if (session != null && event.getEntity() instanceof ServerPlayer player) {
            session.remember(player); session.event("quit", player, ""); session.login.leave(player); session.saveCatalog();
        }
    }
    @SubscribeEvent(priority = EventPriority.HIGHEST) public void chatGate(ServerChatEvent event) {
        Session session = active;
        if (session != null && session.login.locked(event.getPlayer().getUUID())) event.setCanceled(true);
    }
    @SubscribeEvent(priority = EventPriority.LOWEST) public void chat(ServerChatEvent event) {
        Session session = active;
        if (session != null && !session.login.locked(event.getPlayer().getUUID())) session.event("chat", event.getPlayer(), event.getRawText());
    }
    @SubscribeEvent(priority = EventPriority.HIGHEST) public void commandGate(CommandEvent event) {
        Session session = active;
        if (session != null && event.getParseResults().getContext().getSource().getEntity() instanceof ServerPlayer player
                && session.login.locked(player.getUUID())
                && !event.getParseResults().getReader().getString().equals("starbridge:session")) event.setCanceled(true);
    }
    @SubscribeEvent public void commands(RegisterCommandsEvent event) {
        // Internal no-op consumes chat acknowledgements without exposing password arguments to the command bus.
        event.getDispatcher().register(Commands.literal("starbridge:session").executes(context -> 1));
        for (String root : List.of("login", "l", "starbridge:login", "starbridge:l")) {
            event.getDispatcher().register(Commands.literal(root).requires(source -> source.getEntity() instanceof ServerPlayer)
                    .executes(context -> login(context.getSource(), "password", ""))
                    .then(Commands.argument("password", StringArgumentType.greedyString())
                            .executes(context -> login(context.getSource(), "password", StringArgumentType.getString(context, "password")))));
        }
        for (String root : List.of("qqlogin", "ql", "starbridge:qqlogin", "starbridge:ql"))
            event.getDispatcher().register(Commands.literal(root).requires(source -> source.getEntity() instanceof ServerPlayer)
                    .executes(context -> login(context.getSource(), "qq", "")));
        event.getDispatcher().register(Commands.literal("logout").requires(source -> source.getEntity() instanceof ServerPlayer)
                .executes(context -> login(context.getSource(), "logout", "")));
        event.getDispatcher().register(Commands.literal("qbind").requires(source -> source.getEntity() instanceof ServerPlayer)
                .executes(context -> {
                    Session session = active;
                    if (session != null) session.bind((ServerPlayer) context.getSource().getEntity());
                    return 1;
                }));
    }
    private int login(CommandSourceStack source, String action, String password) {
        Session session = active;
        if (session != null) session.login.command((ServerPlayer) source.getEntity(), action, password);
        else source.sendFailure(Component.literal("Myrinbot尚未启动，请联系管理员。"));
        return 1;
    }

    static final class Session {
        final MinecraftServer server;
        final GameLogin login;
        final String base, token;
        final ScheduledExecutorService io = Executors.newSingleThreadScheduledExecutor(r -> daemon(r, "Myrinbot-Tick"));
        final ThreadPoolExecutor workers = new ThreadPoolExecutor(2, 2, 0, TimeUnit.SECONDS,
                new ArrayBlockingQueue<>(64), r -> daemon(r, "Myrinbot-Job"));
        final LinkedBlockingDeque<JsonObject> events = new LinkedBlockingDeque<>(500), results = new LinkedBlockingDeque<>(500);
        final Set<String> inFlight = ConcurrentHashMap.newKeySet();
        final LinkedHashMap<String, JsonObject> completed = new LinkedHashMap<>();
        final LinkedHashMap<UUID, JsonObject> catalog = new LinkedHashMap<>();
        final Map<UUID, Long> bindCooldown = new HashMap<>();
        final Path catalogFile;
        volatile JsonObject snapshot = new JsonObject();
        Set<String> commands;
        volatile boolean running = true;
        int ticks;
        long lastWarning;

        Session(MinecraftServer server) {
            this.server = server; token = Config.TOKEN.get();
            base = Protocol.base(Config.ENDPOINT.get(), Config.SERVER_ID.get(), token);
            commands = Set.copyOf(Config.COMMANDS.get());
            catalogFile = server.getWorldPath(LevelResource.ROOT).resolve("starbridge-players.json");
            loadCatalog();
            login = new GameLogin(this);
        }
        void start() {
            for (ServerPlayer player : server.getPlayerList().getPlayers()) { remember(player); login.join(player); }
            updateSnapshot(); io.scheduleWithFixedDelay(this::tick, 0, 1, TimeUnit.SECONDS);
        }
        static Thread daemon(Runnable runnable, String name) { Thread thread = new Thread(runnable, name); thread.setDaemon(true); return thread; }
        void callback(Runnable runnable) { if (running) server.execute(() -> { if (running) runnable.run(); }); }
        JsonObject post(String route, JsonObject payload) throws Exception {
            BridgeHttp.Response response = BridgeHttp.request(base + route, token, JSON.toJson(payload), route.equals("/auth") ? 16000 : 6000);
            if (response.status == 200) return JsonParser.parseString(response.body).getAsJsonObject();
            if (route.equals("/auth")) {
                JsonObject error = JsonParser.parseString(response.body).getAsJsonObject();
                if (error.has("error")) return error;
            }
            throw new IllegalStateException("HTTP " + response.status);
        }
        void gameTick() {
            login.gameTick();
            if (++ticks % 20 == 0) { updateSnapshot(); if (ticks % 1200 == 0) saveCatalog(); }
        }
        void remember(ServerPlayer player) {
            JsonObject record = new JsonObject();
            record.addProperty("uuid", player.getUUID().toString()); record.addProperty("name", player.getGameProfile().getName());
            record.addProperty("last_played", System.currentTimeMillis()); record.addProperty("ip", player.getIpAddress());
            catalog.remove(player.getUUID()); catalog.put(player.getUUID(), record);
            // Bound memory and local persistence. Bot retains its own historic player database.
            while (catalog.size() > 10000) catalog.remove(catalog.keySet().iterator().next());
        }
        void loadCatalog() {
            try {
                if (!Files.exists(catalogFile)) return;
                if (Files.size(catalogFile) > 8 * 1024 * 1024) throw new IllegalArgumentException();
                for (JsonElement value : JsonParser.parseString(Files.readString(catalogFile)).getAsJsonArray()) {
                    if (catalog.size() >= 10000) break;
                    JsonObject record = value.getAsJsonObject();
                    UUID id = UUID.fromString(record.get("uuid").getAsString()); Protocol.player(record.get("name").getAsString());
                    catalog.put(id, record);
                }
            } catch (Exception error) { LOG.warn("Myrinbot玩家档案读取失败；错误类型：{}", error.getClass().getSimpleName()); }
        }
        void saveCatalog() {
            // Snapshot on the server thread; write disk on the worker with atomic replacement.
            String content = JSON.toJson(catalog.values());
            try { io.execute(() -> {
                try {
                    Path temporary = catalogFile.resolveSibling("starbridge-players.json.tmp");
                    Files.writeString(temporary, content);
                    try { Files.move(temporary, catalogFile, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
                    catch (AtomicMoveNotSupportedException ignored) { Files.move(temporary, catalogFile, StandardCopyOption.REPLACE_EXISTING); }
                } catch (Exception error) { LOG.warn("Myrinbot玩家档案保存失败；错误类型：{}", error.getClass().getSimpleName()); }
            }); } catch (RejectedExecutionException ignored) { }
        }
        void updateSnapshot() {
            PlayerList list = server.getPlayerList();
            Map<UUID, ServerPlayer> online = new LinkedHashMap<>(); JsonArray names = new JsonArray();
            for (ServerPlayer player : list.getPlayers()) { remember(player); online.put(player.getUUID(), player); names.add(player.getGameProfile().getName()); }
            {
                // Existing offline whitelist profiles are available via list entries, without HTTP.
                for (UserWhiteListEntry entry : list.getWhiteList().getEntries()) {
                    GameProfile profile = ObfuscationReflectionHelper.getPrivateValue(StoredUserEntry.class, entry, "f_11369_");
                    if (profile != null && !catalog.containsKey(profile.getId())) {
                        JsonObject record = new JsonObject(); record.addProperty("uuid", profile.getId().toString());
                        record.addProperty("name", profile.getName()); record.addProperty("last_played", 0L); record.addProperty("ip", "");
                        catalog.put(profile.getId(), record);
                    }
                }
            }
            List<UUID> ids = new ArrayList<>(online.keySet());
            List<UUID> recent = new ArrayList<>(catalog.keySet()); Collections.reverse(recent);
            for (UUID id : recent) if (!online.containsKey(id)) ids.add(id);
            JsonArray records = new JsonArray();
            for (UUID id : ids.subList(0, Math.min(500, ids.size()))) {
                JsonObject record = catalog.get(id).deepCopy();
                GameProfile profile = new GameProfile(id, record.get("name").getAsString());
                ServerPlayer player = online.get(id);
                record.addProperty("online", player != null); record.addProperty("banned", list.getBans().isBanned(profile));
                record.addProperty("whitelisted", list.getWhiteList().isWhiteListed(profile)); record.addProperty("op", list.isOp(profile));
                if (player != null) {
                    record.addProperty("world", player.serverLevel().dimension().location().toString());
                    record.addProperty("game_mode", player.gameMode.getGameModeForPlayer().getName().toUpperCase(Locale.ROOT));
                    record.addProperty("health", player.getHealth()); record.addProperty("ping", player.latency);
                }
                records.add(record);
            }
            JsonObject value = new JsonObject(); value.add("players", names); value.add("player_records", records);
            value.addProperty("players_truncated", ids.size() > 500); value.addProperty("max_players", list.getMaxPlayers());
            value.addProperty("version", "1.20.1"); value.addProperty("server_software", "Forge " + net.minecraftforge.versions.forge.ForgeVersion.getVersion());
            value.addProperty("java_version", System.getProperty("java.version")); value.addProperty("whitelist_enabled", list.isUsingWhitelist());
            value.add("capabilities", JSON.toJsonTree(List.of("player_management", "game_authentication", "whitelist_application", "managed_sanctions")));
            value.add("auth_sessions", login.snapshot()); snapshot = value;
        }
        void tick() {
            if (!running) return;
            try {
                events.removeIf(item -> System.currentTimeMillis() - item.get("queued_at").getAsLong() > 30000);
                List<JsonObject> eventBatch = events.stream().limit(50).toList(), resultBatch = results.stream().limit(50).toList();
                JsonObject value = snapshot.deepCopy(); value.add("events", JSON.toJsonTree(eventBatch)); value.add("results", JSON.toJsonTree(resultBatch));
                JsonObject answer = post("/tick", value);
                eventBatch.forEach(events::removeFirstOccurrence); resultBatch.forEach(results::removeFirstOccurrence);
                callback(() -> {
                    login.accept(answer);
                    if (answer.has("allowed_commands")) {
                        Set<String> updated = new HashSet<>();
                        for (JsonElement item : answer.getAsJsonArray("allowed_commands")) updated.add(item.getAsString());
                        commands = Set.copyOf(updated);
                    }
                    if (answer.has("jobs")) for (JsonElement item : answer.getAsJsonArray("jobs")) {
                        JsonObject job = item.getAsJsonObject(); String id = job.get("id").getAsString();
                        if (inFlight.add(id)) execute(job);
                    }
                });
            } catch (Exception error) {
                if (System.currentTimeMillis() - lastWarning > 30000) {
                    LOG.warn("Myrinbot桥接暂不可用；错误类型：{}", error.getClass().getSimpleName()); lastWarning = System.currentTimeMillis();
                }
            }
        }
        static void enqueue(LinkedBlockingDeque<JsonObject> queue, JsonObject item) {
            if (!queue.offerLast(item)) { queue.pollFirst(); queue.offerLast(item); }
        }
        void event(String kind, ServerPlayer player, String text) {
            JsonObject event = new JsonObject(); event.addProperty("id", UUID.randomUUID().toString());
            event.addProperty("kind", kind); event.addProperty("player", player.getGameProfile().getName());
            event.addProperty("text", Protocol.clip(text, 500)); event.addProperty("queued_at", System.currentTimeMillis());
            if (kind.equals("join")) { event.addProperty("uuid", player.getUUID().toString()); event.addProperty("ip", player.getIpAddress()); }
            enqueue(events, event);
        }
        void finish(String id, boolean ok, String detail) {
            JsonObject result = Protocol.result(id, ok, detail); completed.put(id, result);
            if (completed.size() > 2000) completed.remove(completed.keySet().iterator().next());
            enqueue(results, result); inFlight.remove(id);
        }
        void execute(JsonObject job) {
            String id = job.get("id").getAsString();
            try {
                if (completed.containsKey(id)) { enqueue(results, completed.get(id)); inFlight.remove(id); return; }
                if (Protocol.expired(job)) { finish(id, false, "任务已过期，未执行"); return; }
                switch (job.get("kind").getAsString()) {
                    case "broadcast" -> {
                        server.getPlayerList().broadcastSystemMessage(Component.literal(Protocol.clip(job.get("text").getAsString(), 600)), false);
                        finish(id, true, "消息已同步");
                    }
                    case "command" -> {
                        String command = job.get("command").getAsString();
                        if (!commands.contains(command) || command.contains("\n") || command.contains("\r")) {
                            finish(id, false, "命令不在 Bot 面板的完整命令白名单中"); return;
                        }
                        StringBuilder output = new StringBuilder();
                        CommandSource capture = new CommandSource() {
                            public void sendSystemMessage(Component text) {
                                if (output.length() < 1500) output.append(Protocol.clip(text.getString(), 1500 - output.length())).append('\n');
                            }
                            public boolean acceptsSuccess() { return true; }
                            public boolean acceptsFailure() { return true; }
                            public boolean shouldInformAdmins() { return false; }
                        };
                        CommandSourceStack source = server.createCommandSourceStack().withSource(capture);
                        // Parse first: vanilla performPrefixedCommand returns void and swallows failures.
                        int count = server.getCommands().getDispatcher().execute(command, source);
                        finish(id, count > 0, output.isEmpty() ? (count > 0 ? "命令已执行" : "命令执行失败") : output.toString());
                    }
                    case "player_action" -> { finish(id, true, manage(job)); updateSnapshot(); }
                    case "whitelist_application" -> whitelist(job);
                    default -> finish(id, false, "未知任务类型");
                }
            } catch (Exception error) { finish(id, false, "游戏端执行失败：" + error.getClass().getSimpleName()); }
        }
        String manage(JsonObject job) throws Exception {
            UUID id = UUID.fromString(job.get("uuid").getAsString()); String name = job.get("player").getAsString();
            Protocol.player(name); String reason = Protocol.reason(job);
            JsonObject record = catalog.get(id);
            if (record == null || !name.equals(record.get("name").getAsString())) throw new IllegalArgumentException("Player changed");
            GameProfile profile = new GameProfile(id, name); PlayerList list = server.getPlayerList(); ServerPlayer online = list.getPlayer(id);
            switch (job.get("action").getAsString()) {
                case "kick" -> { if (online == null) throw new IllegalStateException("Player offline"); online.connection.disconnect(Component.literal(reason)); }
                case "ban" -> {
                    list.getBans().add(new UserBanListEntry(profile, new Date(), "StarBridge", null, reason)); list.getBans().save();
                    if (online != null) online.connection.disconnect(Component.literal(Protocol.clip(Protocol.text(job, "kick_reason", reason), 340)));
                }
                case "unban" -> {
                    UserBanListEntry entry = list.getBans().get(profile);
                    if (entry != null && job.has("expected_ban_reason") && !job.get("expected_ban_reason").getAsString().equals(entry.getReason()))
                        throw new IllegalStateException("Independent punishment must be preserved");
                    list.getBans().remove(profile); list.getBans().save();
                }
                case "whitelist_add" -> { list.getWhiteList().add(new UserWhiteListEntry(profile)); list.getWhiteList().save(); }
                case "whitelist_remove" -> { list.getWhiteList().remove(profile); list.getWhiteList().save(); }
                default -> throw new IllegalArgumentException("Unsupported action");
            }
            return name + " 操作已完成";
        }
        void whitelist(JsonObject job) {
            String id = job.get("id").getAsString(), name = job.get("player").getAsString(); Protocol.player(name);
            String supplied = Protocol.text(job, "uuid", ""); UUID expected = supplied.isBlank() ? null : UUID.fromString(supplied);
            if (!server.usesAuthentication()) {
                completeWhitelist(job, new GameProfile(expected == null ? Protocol.offlineId(name) : expected, name)); return;
            }
            try { workers.execute(() -> {
                GameProfile profile;
                try {
                    BridgeHttp.Response response = BridgeHttp.request("https://api.mojang.com/users/profiles/minecraft/" + name, null, null, 5000);
                    if (response.status != 200) throw new IllegalStateException();
                    JsonObject value = JsonParser.parseString(response.body).getAsJsonObject();
                    String raw = value.get("id").getAsString();
                    if (!raw.matches("[0-9a-fA-F]{32}")) throw new IllegalArgumentException();
                    UUID uuid = UUID.fromString(raw.replaceFirst("(.{8})(.{4})(.{4})(.{4})(.{12})", "$1-$2-$3-$4-$5"));
                    String canonical = value.get("name").getAsString(); Protocol.player(canonical);
                    if (!canonical.equalsIgnoreCase(name) || expected != null && !expected.equals(uuid)) throw new IllegalArgumentException();
                    profile = new GameProfile(uuid, canonical);
                } catch (Exception error) { callback(() -> finish(id, false, "正版身份查询失败、超时或 UUID 不匹配")); return; }
                GameProfile answer = profile; callback(() -> completeWhitelist(job, answer));
            }); } catch (RejectedExecutionException error) { finish(id, false, "身份查询繁忙，请稍后重试"); }
        }
        void completeWhitelist(JsonObject job, GameProfile profile) {
            String id = job.get("id").getAsString();
            try {
                if (Protocol.expired(job)) { finish(id, false, "任务已过期"); return; }
                if (server.getPlayerList().getBans().isBanned(profile)) { finish(id, false, "玩家已被封禁，未加入白名单"); return; }
                server.getPlayerList().getWhiteList().add(new UserWhiteListEntry(profile)); server.getPlayerList().getWhiteList().save();
                JsonObject record = new JsonObject(); record.addProperty("uuid", profile.getId().toString()); record.addProperty("name", profile.getName());
                record.addProperty("last_played", 0L); record.addProperty("ip", ""); catalog.putIfAbsent(profile.getId(), record);
                finish(id, true, profile.getName() + " 已加入白名单（" + profile.getId() + "）"); updateSnapshot(); saveCatalog();
            } catch (Exception error) { finish(id, false, "白名单保存失败"); }
        }
        void bind(ServerPlayer player) {
            if (login.locked(player.getUUID())) { player.sendSystemMessage(Component.literal("请先完成游戏登录。")); return; }
            UUID id = player.getUUID(); String nonce = login.nonce(id), name = player.getGameProfile().getName(); long now = System.currentTimeMillis();
            if (now - bindCooldown.getOrDefault(id, 0L) < 20000) { player.sendSystemMessage(Component.literal("请等待 20 秒再获取绑定码。")); return; }
            bindCooldown.put(id, now); player.sendSystemMessage(Component.literal("正在获取绑定验证码……"));
            try { workers.execute(() -> {
                String message;
                try {
                    JsonObject request = new JsonObject(); request.addProperty("uuid", id.toString()); request.addProperty("player", name); request.addProperty("nonce", nonce);
                    message = "请在服务器 QQ 群发送：绑定 " + post("/bind-code", request).get("code").getAsString() + "（5 分钟有效，请勿转发）";
                } catch (Exception error) { message = "获取验证码失败，请联系管理员检查Myrinbot连接。"; }
                String answer = message; callback(() -> {
                    ServerPlayer current = server.getPlayerList().getPlayer(id);
                    if (current == player && nonce.equals(login.nonce(id)) && !login.locked(id)) current.sendSystemMessage(Component.literal(answer));
                });
            }); } catch (RejectedExecutionException error) { player.sendSystemMessage(Component.literal("请求繁忙，请稍后重试。")); }
        }
        void close() {
            login.close(); saveCatalog(); running = false; workers.shutdownNow(); io.shutdown();
            try { if (!io.awaitTermination(7, TimeUnit.SECONDS)) io.shutdownNow(); }
            catch (InterruptedException error) { io.shutdownNow(); Thread.currentThread().interrupt(); }
        }
    }
}
