package cn.starbridge.forge;

import com.google.gson.*;
import io.netty.channel.*;
import io.netty.util.ReferenceCountUtil;
import net.minecraft.network.Connection;
import net.minecraft.commands.arguments.ArgumentSignatures;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.*;
import net.minecraft.network.protocol.common.*;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.ServerGamePacketListenerImpl;
import net.minecraft.world.phys.Vec3;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.entity.living.LivingIncomingDamageEvent;
import net.neoforged.neoforge.event.entity.player.ItemEntityPickupEvent;
import net.neoforged.neoforge.event.entity.player.PlayerNegotiationEvent;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.util.ObfuscationReflectionHelper;

import java.util.*;
import java.util.concurrent.*;

/** Session fencing and a packet gate cover inventory clicks as well as movement/commands. */
final class GameLogin {
    private static final String HANDLER = "starbridge_login";
    private static final class Login {
        final UUID id;
        final ServerPlayer player;
        final String nonce = UUID.randomUUID().toString(), name, ip;
        final Vec3 anchor;
        Channel channel;
        volatile boolean authenticated;
        boolean inFlight;
        long deadline, lastCommand;
        volatile long lastCorrection;
        long lastIngress;
        Login(ServerPlayer player, int seconds) {
            this.player = player; id = player.getUUID(); name = player.getGameProfile().getName(); ip = player.getIpAddress();
            anchor = player.position(); deadline = System.currentTimeMillis() + seconds * 1000L;
        }
        JsonObject request(String action) {
            JsonObject request = new JsonObject(); request.addProperty("action", action); request.addProperty("uuid", id.toString());
            request.addProperty("nonce", nonce); request.addProperty("player", name); request.addProperty("ip", ip); return request;
        }
    }
    private final StarBridge.Session session;
    private final ConcurrentMap<UUID, Login> connections = new ConcurrentHashMap<>();
    private final ThreadPoolExecutor workers = new ThreadPoolExecutor(2, 2, 0, TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(64), runnable -> StarBridge.Session.daemon(runnable, "Myrinbot-Login"));
    private volatile boolean known, required = true;
    private boolean passwordLogin = true, qqLogin = true;
    private String revision = "";
    private int seconds = 120;

    GameLogin(StarBridge.Session session) { this.session = session; NeoForge.EVENT_BUS.register(this); }
    boolean locked(UUID id) {
        if (known && !required) return false;
        Login login = connections.get(id); return !known || login == null || !login.authenticated;
    }
    String nonce(UUID id) { Login login = connections.get(id); return login == null ? "" : login.nonce; }
    void negotiate(PlayerNegotiationEvent event) {
        CompletableFuture<Void> installed = new CompletableFuture<>(); event.enqueueWork(installed);
        try {
            Channel channel = ObfuscationReflectionHelper.getPrivateValue(Connection.class, event.getConnection(), "channel");
            if (channel == null) throw new IllegalStateException();
            channel.eventLoop().execute(() -> {
                try {
                    channel.pipeline().addBefore("packet_handler", HANDLER, new ChannelInboundHandlerAdapter() {
                        @Override public void channelRead(ChannelHandlerContext context, Object packet) throws Exception {
                            // Installed before login completes: no already-queued game action can bypass the join gate.
                            if (beforeJoinBlocked(packet, event.getConnection().getPacketListener() instanceof ServerGamePacketListenerImpl)) {
                                ReferenceCountUtil.release(packet); return;
                            }
                            super.channelRead(context, packet);
                        }
                    });
                } catch (RuntimeException error) { event.getConnection().disconnect(Component.literal("登录保护初始化失败，请联系管理员。")); }
                finally { installed.complete(null); }
            });
        } catch (RuntimeException error) {
            event.getConnection().disconnect(Component.literal("登录保护初始化失败，请联系管理员。")); installed.complete(null);
        }
    }
    void join(ServerPlayer player) {
        Login login = begin(player);
        try {
            Connection connection = player.connection.getConnection();
            Channel channel = ObfuscationReflectionHelper.getPrivateValue(Connection.class, connection, "channel");
            if (channel == null) throw new IllegalStateException();
            login.channel = channel;
            channel.eventLoop().execute(() -> {
                try {
                    if (channel.pipeline().get(HANDLER) != null) channel.pipeline().remove(HANDLER);
                    channel.pipeline().addBefore("packet_handler", HANDLER, new ChannelInboundHandlerAdapter() {
                        @Override public void channelRead(ChannelHandlerContext context, Object packet) throws Exception {
                            // Handle our auth commands before the command bus; raw passwords never reach command loggers.
                            if (packet instanceof ServerboundChatCommandPacket command && Protocol.loginCommand(command.command())) {
                                long now=System.currentTimeMillis();
                                if(now-login.lastIngress>=1000) {
                                    login.lastIngress=now; String value=command.command();int split=value.indexOf(' ');
                                    String root=split<0?value:value.substring(0,split),password=split<0?"":value.substring(split+1);
                                    String action=root.endsWith("ql")||root.endsWith("qqlogin")?"qq":"password";
                                    session.callback(() -> { if(currentPlayer(player)) command(player,action,password); });
                                }
                                ReferenceCountUtil.release(packet);return;
                            }
                            if (packet instanceof ServerboundChatCommandSignedPacket command && Protocol.loginCommand(command.command())) {
                                // Even rejected auth requests must update vanilla chat acknowledgements.
                                super.channelRead(context, scrub(command));
                                long now = System.currentTimeMillis();
                                if (now - login.lastIngress < 1000) { ReferenceCountUtil.release(packet); return; }
                                login.lastIngress = now;
                                String value = command.command(); int split = value.indexOf(' ');
                                String root = split < 0 ? value : value.substring(0, split);
                                String action = root.endsWith("qqlogin") || root.endsWith("ql") ? "qq" : "password";
                                String password = split < 0 ? "" : value.substring(split + 1);
                                session.callback(() -> { if (currentPlayer(player)) command(player, action, password); });
                                ReferenceCountUtil.release(packet); return;
                            }
                            if (packet instanceof ServerboundChatCommandSignedPacket || packet instanceof ServerboundChatCommandPacket) {
                                // Vanilla first consumes signed arguments/acks. CommandEvent then denies execution while locked.
                                super.channelRead(context, packet); return;
                            }
                            if (locked(player.getUUID()) && !hygiene(packet)) {
                                if (packet instanceof ServerboundMovePlayerPacket && System.currentTimeMillis() - login.lastCorrection > 1000) {
                                    login.lastCorrection = System.currentTimeMillis();
                                    session.callback(() -> correct(player));
                                }
                                ReferenceCountUtil.release(packet); return;
                            }
                            super.channelRead(context, packet);
                        }
                    });
                } catch (RuntimeException error) { session.callback(() -> player.connection.disconnect(Component.literal("登录保护初始化失败，请联系管理员检查 Forge 版本。"))); }
            });
        } catch (RuntimeException error) {
            player.connection.disconnect(Component.literal("登录保护初始化失败，请使用 NeoForge 1.21.1 服务端。"));
            StarBridge.LOG.error("Myrinbot数据包保护不可用；错误类型：{}", error.getClass().getSimpleName());
        }
    }
    static boolean hygiene(Object packet) {
        // No actions, inventory packets or custom mod payloads are processed before login.
        return packet instanceof ServerboundKeepAlivePacket || packet instanceof ServerboundPongPacket
                || packet instanceof ServerboundClientInformationPacket || packet instanceof ServerboundAcceptTeleportationPacket
                || packet instanceof ServerboundResourcePackPacket || packet instanceof ServerboundChatAckPacket
                || packet instanceof ServerboundChatSessionUpdatePacket || packet instanceof ServerboundChatPacket;
    }
    static boolean beforeJoinBlocked(Object packet, boolean playing) {
        // NeoForge negotiates common custom payloads in the configuration phase.
        // They cannot perform game actions there; block them once play begins.
        String protocol = packet.getClass().getPackageName();
        return (protocol.equals("net.minecraft.network.protocol.game")
                || playing && protocol.equals("net.minecraft.network.protocol.common")) && !hygiene(packet);
    }
    static ServerboundChatCommandSignedPacket scrub(ServerboundChatCommandSignedPacket packet) {
        return new ServerboundChatCommandSignedPacket("starbridge:session", packet.timeStamp(), packet.salt(), ArgumentSignatures.EMPTY, packet.lastSeenMessages());
    }
    private boolean currentPlayer(ServerPlayer player) { return session.server.getPlayerList().getPlayer(player.getUUID()) == player; }
    private Login begin(ServerPlayer player) {
        Login previous = connections.get(player.getUUID()); Login login = new Login(player, seconds);
        if (previous != null) login.channel = previous.channel;
        connections.put(login.id, login);
        if (known && !required) login.authenticated = true;
        else { player.sendSystemMessage(Component.literal("Myrinbot正在检查本次游戏登录……")); submit(login, login.request("join"), true); }
        return login;
    }
    void leave(ServerPlayer player) {
        Login login = connections.get(player.getUUID());
        if (login == null || login.player != player) return;
        connections.remove(login.id, login); session.bindCooldown.remove(login.id);
        if (login.channel != null) login.channel.eventLoop().execute(() -> {
            if (login.channel.pipeline().get(HANDLER) != null) login.channel.pipeline().remove(HANDLER);
        });
        if (known && required) try { workers.execute(() -> { try { session.post("/auth", login.request("leave")); } catch (Exception ignored) { } }); }
        catch (RejectedExecutionException ignored) { }
    }
    void command(ServerPlayer player, String action, String password) {
        if (!currentPlayer(player)) return;
        if (!known) { player.sendSystemMessage(Component.literal("正在同步认证设置，请稍后重试。")); return; }
        if (!required) { player.sendSystemMessage(Component.literal("此服务器没有启用Myrinbot游戏登录。")); return; }
        if (action.equals("logout")) { begin(player); return; }
        Login login = connections.get(player.getUUID());
        if (login == null) { join(player); return; }
        if (login.authenticated) { message(login, "你已经登录。"); return; }
        long now = System.currentTimeMillis(); if (now - login.lastCommand < 1000) return; login.lastCommand = now;
        boolean usingPassword = action.equals("password");
        if (usingPassword ? !passwordLogin : !qqLogin) { message(login, "此登录方式没有开放。"); return; }
        if (usingPassword && (password.length() < 8 || password.length() > 128)) {
            message(login, "正确格式：/login <8–128 字符密码> 或 /l <密码>；请勿在公共聊天中发送密码。"); return;
        }
        JsonObject request = login.request(usingPassword ? "password" : "qq");
        if (usingPassword) request.addProperty("password", password); submit(login, request, false);
    }
    private void submit(Login login, JsonObject payload, boolean joining) {
        if (login.inFlight) { payload.remove("password"); message(login, "认证请求正在处理中，请稍候。"); return; }
        login.inFlight = true;
        try { workers.execute(() -> {
            JsonObject answer;
            try { answer = session.post("/auth", payload); }
            catch (Exception error) { answer = new JsonObject(); answer.addProperty("error", "认证连接暂不可用，请稍后重试。"); }
            finally { payload.remove("password"); }
            JsonObject result = answer;
            session.callback(() -> {
                if (connections.get(login.id) != login || !currentPlayer(login.player)) return;
                login.inFlight = false;
                if (result.has("error")) {
                    message(login, result.get("error").getAsString());
                    if (joining) kick(login, "认证服务不可用，请稍后重新进入服务器。");
                } else apply(login, result, joining, true);
            });
        }); } catch (RejectedExecutionException error) {
            payload.remove("password"); login.inFlight = false; message(login, "认证请求繁忙，请稍后重试。");
            if (joining) kick(login, "认证请求繁忙，请稍后重新进入服务器。");
        }
    }
    void accept(JsonObject response) {
        if (!response.has("authentication")) return;
        JsonObject policy = response.getAsJsonObject("authentication");
        boolean oldKnown = known, oldRequired = required; String oldRevision = revision;
        required = policy.get("required").getAsBoolean(); passwordLogin = policy.get("password_login").getAsBoolean(); qqLogin = policy.get("qq_login").getAsBoolean();
        seconds = Math.max(30, Math.min(600, policy.get("login_seconds").getAsInt())); revision = policy.get("revision").getAsString(); known = true;
        String engine = Protocol.text(policy, "login_engine", "auto");
        if (required && (!policy.get("available").getAsBoolean() || !Set.of("auto", "builtin").contains(engine))) {
            known = false;
            for (Login login : connections.values()) kick(login, "Forge 请使用Myrinbot内置或自动登录引擎；请联系管理员检查认证设置。");
            return;
        }
        if (!required) { connections.values().forEach(login -> login.authenticated = true); return; }
        if (oldKnown && (!oldRequired || !oldRevision.equals(revision))) {
            for (ServerPlayer player : List.copyOf(session.server.getPlayerList().getPlayers())) begin(player);
        }
        if (response.has("authentication_results")) for (JsonElement value : response.getAsJsonArray("authentication_results")) {
            JsonObject result = value.getAsJsonObject(); Login login = connections.get(UUID.fromString(result.get("uuid").getAsString()));
            if (login == null || !login.nonce.equals(Protocol.text(result, "nonce", ""))) continue;
            if ("missing".equals(Protocol.text(result, "status", ""))) { if (!login.inFlight && currentPlayer(login.player)) begin(login.player); }
            else apply(login, result, false, false);
        }
    }
    private void apply(Login login, JsonObject result, boolean joining, boolean notify) {
        if (connections.get(login.id) != login || !currentPlayer(login.player) || !login.nonce.equals(Protocol.text(result, "nonce", ""))) return;
        if (!known || !revision.equals(Protocol.text(result, "revision", ""))) return;
        switch (Protocol.text(result, "status", "")) {
            case "authenticated" -> {
                if (!login.authenticated) { login.authenticated = true; message(login, "登录成功，欢迎回来！"); }
            }
            case "disabled" -> { if (!required) login.authenticated = true; }
            case "denied" -> { login.authenticated = false; kick(login, Protocol.text(result, "message", "登录被拒绝")); }
            case "pending" -> {
                if (joining) {
                    login.deadline = System.currentTimeMillis() + Math.max(0, Math.min(600, result.get("expires_in").getAsInt())) * 1000L;
                    message(login, prompt());
                } else if (notify) message(login, Protocol.text(result, "message", prompt()));
            }
            default -> { }
        }
    }
    JsonArray snapshot() {
        JsonArray records = new JsonArray();
        for (Login login : connections.values()) { records.add(login.request("heartbeat")); if (records.size() >= 500) break; }
        return records;
    }
    private String prompt() {
        return "请登录：" + (passwordLogin ? "/login <注册密码> 或 /l <密码>；" : "") + (qqLogin ? "/qqlogin 或 /ql，绑定 QQ 私聊确认。" : "");
    }
    private void message(Login login, String text) {
        if (currentPlayer(login.player) && connections.get(login.id) == login) login.player.sendSystemMessage(Component.literal(Protocol.clip(text, 600)));
    }
    private void kick(Login login, String text) {
        if (currentPlayer(login.player) && connections.get(login.id) == login) login.player.connection.disconnect(Component.literal(Protocol.clip(text, 600)));
    }
    private void correct(ServerPlayer player) {
        Login login = connections.get(player.getUUID());
        if (login != null && login.player == player && locked(login.id) && currentPlayer(player)) {
            Vec3 point = login.anchor; player.connection.teleport(point.x, point.y, point.z, player.getYRot(), player.getXRot());
            player.setDeltaMovement(Vec3.ZERO); player.fallDistance = 0;
        }
    }
    void gameTick() {
        for (Login login : connections.values()) if (locked(login.id) && currentPlayer(login.player)) {
            if (System.currentTimeMillis() >= login.deadline) { kick(login, "登录超时，请重新进入服务器。"); continue; }
            // Prevent server-driven gravity and pushes as well as client packet movement.
            if (login.player.position().distanceToSqr(login.anchor) > 0.0001) correct(login.player);
            login.player.setDeltaMovement(Vec3.ZERO); login.player.fallDistance = 0;
        }
    }
    @SubscribeEvent public void damage(LivingIncomingDamageEvent event) {
        if (event.getEntity() instanceof ServerPlayer player && connections.containsKey(player.getUUID()) && locked(player.getUUID())) event.setCanceled(true);
        if (event.getSource().getEntity() instanceof ServerPlayer player && connections.containsKey(player.getUUID()) && locked(player.getUUID())) event.setCanceled(true);
    }
    @SubscribeEvent public void pickup(ItemEntityPickupEvent.Pre event) {
        if (event.getPlayer() instanceof ServerPlayer player && connections.containsKey(player.getUUID()) && locked(player.getUUID())) event.setCanPickup(net.neoforged.neoforge.common.util.TriState.FALSE);
    }
    void close() {
        NeoForge.EVENT_BUS.unregister(this); workers.shutdownNow();
        for (Login login : connections.values()) {
            if (!known || required) kick(login, "游戏认证已停止，请稍后重新连接。");
            if (login.channel != null) login.channel.eventLoop().execute(() -> { if (login.channel.pipeline().get(HANDLER) != null) login.channel.pipeline().remove(HANDLER); });
        }
        connections.clear();
    }
}
