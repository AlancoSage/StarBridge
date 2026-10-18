package cn.starbridge.velocity;

import com.google.gson.*;
import com.google.inject.Inject;
import com.velocitypowered.api.command.SimpleCommand;
import com.velocitypowered.api.event.Subscribe;
import com.velocitypowered.api.event.PostOrder;
import com.velocitypowered.api.event.ResultedEvent;
import com.velocitypowered.api.event.connection.DisconnectEvent;
import com.velocitypowered.api.event.connection.LoginEvent;
import com.velocitypowered.api.event.connection.PreLoginEvent;
import com.velocitypowered.api.event.proxy.ProxyInitializeEvent;
import com.velocitypowered.api.event.proxy.ProxyShutdownEvent;
import com.velocitypowered.api.plugin.PluginContainer;
import com.velocitypowered.api.plugin.annotation.DataDirectory;
import com.velocitypowered.api.proxy.Player;
import com.velocitypowered.api.proxy.InboundConnection;
import com.velocitypowered.api.proxy.ProxyServer;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;
import net.kyori.adventure.text.Component;
import org.slf4j.Logger;

/** Proxy-only QQ ownership proof and native password recovery; does not replace native login. */
public final class MyrinbotVelocity {
    private final ProxyServer server;
    private final Logger logger;
    private final Path directory;
    private final String instance = UUID.randomUUID().toString();
    private final ScheduledExecutorService worker = Executors.newSingleThreadScheduledExecutor(runnable -> {
        Thread thread = new Thread(runnable, "VexBot-Velocity"); thread.setDaemon(true); return thread;
    });
    private final Set<String> resetting = ConcurrentHashMap.newKeySet();
    private final Map<InboundConnection, String> connections = new ConcurrentHashMap<>();
    private final Map<UUID, Long> cooldown = new ConcurrentHashMap<>();
    private final Map<UUID, String> nonces = new ConcurrentHashMap<>();
    private final Map<String, Double> seen = new LinkedHashMap<>();
    private final List<JsonObject> results = new ArrayList<>();
    private BridgeConfig config;
    private NativeAuth nativeAuth;
    private Ownership ownership;
    private volatile boolean closed, remoteEnabled;
    private volatile long lastTick;
    private long lastWarning;

    @Inject
    public MyrinbotVelocity(ProxyServer server, Logger logger, @DataDirectory Path directory) {
        this.server = server; this.logger = logger; this.directory = directory;
    }

    @Subscribe
    public void initialize(ProxyInitializeEvent event) {
        try {
            config = new BridgeConfig(directory);
            if (!config.enabled) {
                logger.info("VexBot Velocity 密码恢复默认关闭；请配置 config.properties 并在面板启用。");
                worker.shutdownNow(); return;
            }
            boolean limbo = server.getPluginManager().getPlugin("limboauth").isPresent();
            boolean libre = server.getPluginManager().getPlugin("librelogin").isPresent();
            if (limbo == libre || config.engine.equals("limboauth") != limbo)
                throw new IllegalStateException("exactly one selected authentication plugin is required");
            PluginContainer container = server.getPluginManager().getPlugin(config.engine).orElseThrow();
            Object plugin = container.getInstance().orElseThrow();
            nativeAuth = config.engine.equals("limboauth") ? new LimboAuthAdapter(plugin) : new LibreLoginAuth(plugin);
            ownership = new Ownership(directory);
            server.getCommandManager().register(server.getCommandManager().metaBuilder("qbind")
                .aliases("myrinbot:qbind").plugin(this).build(), new SimpleCommand() {
                @Override public void execute(Invocation invocation) {
                    if (!(invocation.source() instanceof Player)) {
                        invocation.source().sendMessage(Component.text("请在游戏内完成原生登录后执行 /qbind。")); return;
                    }
                    if (invocation.arguments().length != 0) return;
                    bind((Player) invocation.source());
                }
            });
            worker.scheduleWithFixedDelay(this::tick, 0, 2, TimeUnit.SECONDS);
            logger.info("VexBot Velocity 已启用原生认证账号核验；密码恢复以面板设置为准。");
        } catch (Exception | LinkageError failure) {
            closed = true; worker.shutdownNow();
            logger.error("VexBot Velocity 初始化失败；请检查配置、插件版本及是否只启用一套认证插件。");
        }
    }

    @Subscribe(order = PostOrder.LAST)
    public void preLogin(PreLoginEvent event) {
        if (closed || nativeAuth == null) return;
        String key = event.getUsername().toLowerCase(Locale.ROOT);
        if (resetting.contains(key))
            event.setResult(PreLoginEvent.PreLoginComponentResult.denied(Component.text("密码正在更新，请稍后重连。")));
        else if (event.getResult().isAllowed()) connections.put(event.getConnection(), key);
    }

    @Subscribe(order = PostOrder.LAST)
    public void login(LoginEvent event) {
        if (resetting.contains(event.getPlayer().getUsername().toLowerCase(Locale.ROOT)))
            event.setResult(ResultedEvent.ComponentResult.denied(Component.text("密码正在更新，请稍后重连。")));
        else if (event.getResult().isAllowed() && nativeAuth != null && !closed)
            connections.put(event.getPlayer(), event.getPlayer().getUsername().toLowerCase(Locale.ROOT));
    }

    @Subscribe public void disconnect(DisconnectEvent event) {
        UUID identity = event.getPlayer().getUniqueId(); nonces.remove(identity); cooldown.remove(identity);
    }

    @Subscribe public void shutdown(ProxyShutdownEvent event) {
        closed = true; remoteEnabled = false; worker.shutdownNow();
    }

    private boolean live(Player player, String nonce) {
        return !closed && remoteEnabled && System.currentTimeMillis() - lastTick < 10000
            && player.isActive() && server.getPlayer(player.getUniqueId()).orElse(null) == player
            && Objects.equals(nonces.get(player.getUniqueId()), nonce)
            && !resetting.contains(player.getUsername().toLowerCase(Locale.ROOT));
    }

    private void bind(Player player) {
        if (closed || !remoteEnabled || System.currentTimeMillis() - lastTick >= 10000) {
            player.sendMessage(Component.text("密码恢复尚未接通，请联系管理员检查机器人面板设置。")); return;
        }
        UUID identity = player.getUniqueId(); long now = System.currentTimeMillis();
        Long previous = cooldown.putIfAbsent(identity, now);
        if (previous != null && now - previous < 20000) {
            player.sendMessage(Component.text("请等待 20 秒再获取绑定码。")); return;
        }
        cooldown.put(identity, now);
        String nonce = UUID.randomUUID().toString(); nonces.put(identity, nonce);
        try {
            worker.execute(() -> {
                String message = "无法确认原生账号登录状态，请先完成原插件登录和两步验证后重试。";
                try {
                    if (!live(player, nonce) || !nativeAuth.authenticated(player)) {
                        if (live(player, nonce)) player.sendMessage(Component.text(message)); return;
                    }
                    JsonObject data = new JsonObject();
                    data.addProperty("uuid", identity.toString()); data.addProperty("player", player.getUsername());
                    data.addProperty("nonce", nonce); data.addProperty("password_reset_platform", "velocity");
                    data.addProperty("password_reset_engine", nativeAuth.id());
                    String account = nativeAuth.account(player);
                    if (!account.matches("[a-f0-9]{64}")) throw new IllegalStateException("unverified account");
                    data.addProperty("password_reset_account", account);
                    ownership.record(nativeAuth.id(), identity, player.getUsername(), account);
                    if (!live(player, nonce) || !nativeAuth.authenticated(player)) return;
                    JsonObject response = post("/bind-code", data);
                    String code = text(response, "code");
                    if (!code.matches("[A-Za-z0-9]{4,16}")) throw new IllegalStateException("invalid binding code");
                    message = "请由自己的 QQ 私聊机器人发送：/验证绑定 " + config.server + " " + code
                        + "（5 分钟有效，请勿转发或发群）。已绑定请用原 QQ，无需解绑。仅做普通绑定（如 QQ 官机），可在服务器群发送：绑定 " + code + "；不会开放改密权限。";
                } catch (Exception | LinkageError failure) { message = "获取绑定码失败，请联系管理员检查原生认证和机器人连接。"; }
                if (live(player, nonce)) player.sendMessage(Component.text(message));
            });
        } catch (RejectedExecutionException stopped) { /* shutting down */ }
    }

    private JsonObject post(String path, JsonObject data) throws Exception {
        String raw = BridgeHttp.post(config.endpoint + "/bridge/" + config.server + path, config.token, data.toString());
        return JsonParser.parseString(raw).getAsJsonObject();
    }

    private void tick() {
        if (closed) return;
        try {
            connections.entrySet().removeIf(entry -> !entry.getKey().isActive());
            JsonObject data = new JsonObject(); data.addProperty("instance", instance);
            data.addProperty("platform", "velocity"); data.addProperty("engine", nativeAuth.id());
            JsonArray reporting = new JsonArray(); results.forEach(reporting::add); data.add("results", reporting);
            JsonObject response = post("/password-reset/tick", data);
            results.clear();
            remoteEnabled = response.has("enabled") && response.get("enabled").getAsBoolean()
                && instance.equals(text(response, "instance")) && nativeAuth.id().equals(text(response, "engine"));
            lastTick = System.currentTimeMillis();
            if (!remoteEnabled) return;
            JsonArray jobs = response.getAsJsonArray("jobs");
            if (jobs == null || jobs.size() > 16) throw new IllegalStateException("invalid jobs");
            for (JsonElement element : jobs) {
                if (closed) return;
                JsonObject job = element.getAsJsonObject();
                String id = text(job, "id"), status = execute(job);
                if (validUUID(id)) {
                    JsonObject result = new JsonObject(); result.addProperty("id", id); result.addProperty("status", status);
                    if (results.size() < 128) results.add(result);
                }
            }
        } catch (Exception | LinkageError failure) {
            remoteEnabled = false;
            if (System.currentTimeMillis() - lastWarning > 60000) {
                lastWarning = System.currentTimeMillis();
                logger.warn("VexBot Velocity 连接或认证接口暂不可用；密码恢复已暂停。");
            }
        }
    }

    String execute(JsonObject job) {
        String id = text(job, "id"), name = text(job, "player"), identity = text(job, "uuid");
        double now = System.currentTimeMillis() / 1000.0;
        try {
            if (!validUUID(id) || !validUUID(identity) || !name.matches("[A-Za-z0-9_]{1,16}")
                || !nativeAuth.id().equals(text(job, "engine")) || !instance.equals(text(job, "instance"))) return "unsupported";
            double expires = job.get("expires").getAsDouble();
            if (!Double.isFinite(expires) || expires <= now || expires > now + 35) return "expired";
            seen.entrySet().removeIf(entry -> entry.getValue() < now - 300);
            if (seen.containsKey(id) || seen.size() >= 1000) return "expired";
            seen.put(id, expires);
            String password = text(job, "password");
            if (!password.matches("[!-~]{8,64}")) return "failed";
            UUID uuid = UUID.fromString(identity);
            String key = name.toLowerCase(Locale.ROOT);
            if (!resetting.add(key)) return "online";
            try {
                if (online(uuid, name)) return "online";
                String account = text(job, "account");
                if (!account.matches("[a-f0-9]{64}") || !account.equals(ownership.account(nativeAuth.id(), uuid, name)))
                    return "identity_mismatch";
                return nativeAuth.reset(uuid, name, account, password, () -> {
                    if (closed || !remoteEnabled || System.currentTimeMillis() / 1000.0 >= expires || online(uuid, name)) return false;
                    JsonObject claim = new JsonObject(); claim.addProperty("id", id); claim.addProperty("instance", instance);
                    claim.addProperty("platform", "velocity"); claim.addProperty("engine", nativeAuth.id());
                    JsonObject granted = post("/password-reset/claim", claim);
                    return !closed && !online(uuid, name) && System.currentTimeMillis() / 1000.0 < expires
                        && granted.has("allowed") && granted.get("allowed").getAsBoolean();
                });
            } finally { resetting.remove(key); }
        } catch (Exception | LinkageError failure) { return "failed"; }
        finally { job.remove("password"); }
    }

    private boolean online(UUID identity, String name) {
        String key = name.toLowerCase(Locale.ROOT);
        return connections.entrySet().stream().anyMatch(entry -> entry.getValue().equals(key) && entry.getKey().isActive())
            || server.getPlayer(identity).isPresent() || server.getAllPlayers().stream()
            .anyMatch(player -> player.getUsername().equalsIgnoreCase(name));
    }

    static String text(JsonObject data, String key) {
        JsonElement value = data.get(key);
        return value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isString() ? value.getAsString() : "";
    }

    static boolean validUUID(String value) {
        try { return UUID.fromString(value).toString().equals(value); } catch (IllegalArgumentException invalid) { return false; }
    }
}
