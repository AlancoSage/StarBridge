package cn.starbridge.fabric;

import cn.starbridge.mods.*;
import com.google.gson.*;
import com.mojang.brigadier.CommandDispatcher;
import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.brigadier.builder.LiteralArgumentBuilder;
import com.mojang.brigadier.builder.RequiredArgumentBuilder;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Paths;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.RejectedExecutionException;
import net.fabricmc.loader.api.FabricLoader;

/** Lifecycle, command routing and immutable identities shared with the packet gate. */
public final class FabricRuntime {
    static volatile FabricNative nativeApi;
    static volatile FabricHost host;
    static volatile BridgeEngine engine;
    static String version;
    static final Map<String,String> packetNames=new HashMap<String,String>();
    private static final Map<Object,Session> identities=new ConcurrentHashMap<Object,Session>();
    private static final Map<UUID,GameHost.Player> tracked=new LinkedHashMap<UUID,GameHost.Player>();
    private static boolean failed,stopping;
    private static Object server;

    static final class Session {
        final GameHost.Player player;
        final BridgeEngine bridge;
        Session(GameHost.Player player,BridgeEngine bridge){this.player=player;this.bridge=bridge;}
        boolean locked(){return engine!=bridge||bridge.locked(player.id());}
    }
    private FabricRuntime(){}

    public static void initialize() {
        if(nativeApi!=null)return;
        nativeApi=new FabricNative();
        try(InputStream stream=FabricRuntime.class.getResourceAsStream("/starbridge-fabric-mappings.json")) {
            if(stream==null)throw new IllegalStateException("Fabric mappings missing");
            JsonObject document=new JsonParser().parse(new InputStreamReader(stream,StandardCharsets.UTF_8)).getAsJsonObject();
            version=document.get("mcVersion").getAsString();
            for(Map.Entry<String,JsonElement> item:document.getAsJsonObject("packets").entrySet()) {
                String actual=nativeApi.runtimeClassName(item.getValue().getAsString());
                packetNames.put(actual,item.getKey());
            }
        } catch(IOException error){throw new IllegalStateException("Fabric mappings unreadable",error);}
    }

    public static void tick(Object gameServer) {
        if(stopping||failed)return;
        try {
            if(host==null) {
                initialize();
                if(!FabricHost.dedicated(gameServer)){failed=true;return;}
                server=gameServer;
                FabricHost adapter=new FabricHost(gameServer,version);host=adapter;
                BridgeEngine bridge=new BridgeEngine(adapter,BridgeConfig.load(Paths.get("config","starbridge-bridge.properties")));
                engine=bridge;
                for(GameHost.Player player:adapter.players())tracked.put(player.id(),player);
                bridge.start();
                adapter.log("Fabric "+version+" 游戏桥接已启动。",null);
            }
            if(server!=gameServer)return;
            host.drain();
            Map<UUID,GameHost.Player> current=new LinkedHashMap<UUID,GameHost.Player>();
            for(GameHost.Player player:host.players())current.put(player.id(),player);
            for(GameHost.Player prior:new ArrayList<GameHost.Player>(tracked.values())) {
                GameHost.Player now=current.get(prior.id());
                if(now==null||now.handle()!=prior.handle())engine.leave(prior);
            }
            for(GameHost.Player player:current.values()) {
                GameHost.Player prior=tracked.get(player.id());
                if(prior==null||prior.handle()!=player.handle())engine.join(player);
            }
            tracked.clear();tracked.putAll(current);
            engine.gameTick();
        } catch(Throwable error) {
            failed=true;
            report("Fabric 原生桥接失败，停止服务端以保持登录保护。",error);
            if(host!=null)host.stop();
            else if(nativeApi!=null)nativeApi.call(gameServer,"net.minecraft.server.MinecraftServer","stop",false);
        }
    }

    public static void shutdown(Object gameServer) {
        if(server!=gameServer||stopping)return;
        stopping=true;
        BridgeEngine prior=engine;engine=null;
        try {if(prior!=null)prior.close();}
        finally {identities.clear();tracked.clear();FabricPacketGate.clear();host=null;}
    }
    public static void join(Object player) {
        if(host==null||engine==null||failed||stopping)throw new IllegalStateException("Fabric login protection is not ready");
        GameHost.Player wrapped=host.wrap(player),prior=tracked.get(wrapped.id());
        if(prior!=null&&prior.handle()!=player)engine.leave(prior);
        if(prior==null||prior.handle()!=player){engine.join(wrapped);tracked.put(wrapped.id(),wrapped);}
    }
    public static void protect(GameHost.Player player,BridgeEngine bridge) {
        Session session=new Session(player,bridge);identities.put(player.handle(),session);
        FabricPacketGate.attach(host.connection(player),session);
    }
    public static void unprotect(GameHost.Player player) {
        Session prior=identities.get(player.handle());
        if(prior!=null&&prior.player.handle()==player.handle()) {
            identities.remove(player.handle(),prior);FabricPacketGate.detach(prior);
        }
    }
    public static boolean lockedEntity(Object entity) {
        Session session=identities.get(entity);
        return session!=null&&session.player.handle()==entity&&session.locked();
    }

    /** Vanilla reaches this hook after signature and acknowledgement validation. */
    public static boolean allowChat(Object player,Object message) {
        Session session=identities.get(player);
        if(session==null||session.player.handle()!=player||session.locked())return false;
        Object contents=nativeApi.call(message,"net.minecraft.network.message.SignedMessage","getSignedContent");
        String raw;
        if(contents instanceof String)raw=(String)contents;
        else raw=(String)nativeApi.call(contents,"net.minecraft.network.message.DecoratedContents","plain");
        queueChat(session,raw);return true;
    }
    static void queueChat(final Session session,final String text) {
        try { session.bridge.callback(()->{
            if(identities.get(session.player.handle())==session&&!session.locked())session.bridge.chat(session.player,text);
        }); } catch(RejectedExecutionException ignored){}
    }
    static void queueCommand(final Session session,final String command) {
        try { session.bridge.callback(()->{
            if(identities.get(session.player.handle())==session)session.bridge.command(session.player,command);
        }); } catch(RejectedExecutionException ignored){}
    }
    static boolean routed(String raw) {
        int space=raw.indexOf(' ');String root=space<0?raw:raw.substring(0,space);
        return BridgeEngine.authCommand(raw)||root.equals("qbind")||root.equals("logout");
    }
    static void report(String message,Throwable error) {
        FabricHost adapter=host;
        if(adapter!=null)adapter.log(message,error);
        else {
            System.err.println("[StarBridge] "+message+" "+error.getClass().getName());
            for(StackTraceElement frame:error.getStackTrace())System.err.println("    at "+frame);
        }
    }

    @SuppressWarnings("unchecked")
    public static void registerCommands(Object commandManager) {
        initialize();
        CommandDispatcher<Object> dispatcher=(CommandDispatcher<Object>)nativeApi.call(commandManager,"net.minecraft.server.command.CommandManager","getDispatcher");
        dispatcher.register(LiteralArgumentBuilder.<Object>literal("starbridge:session").executes(context->1));
        for(String name:Arrays.asList("login","l","ql","qqlogin","starbridge:login","starbridge:l","starbridge:ql","starbridge:qqlogin","qbind","logout")) {
            final String root=name;
            LiteralArgumentBuilder<Object> command=LiteralArgumentBuilder.<Object>literal(name)
                .requires(source->{Object entity=nativeApi.call(source,"net.minecraft.server.command.ServerCommandSource","getEntity");return entity!=null&&nativeApi.type("net.minecraft.server.network.ServerPlayerEntity").isInstance(entity);})
                .executes(context->run(context.getSource(),root));
            if(name.endsWith("login")&&!name.endsWith("qqlogin")||name.equals("l")||name.equals("starbridge:l"))
                command.then(RequiredArgumentBuilder.<Object,String>argument("password",StringArgumentType.greedyString())
                    .executes(context->run(context.getSource(),root+" "+StringArgumentType.getString(context,"password"))));
            dispatcher.register(command);
        }
    }
    private static int run(Object source,String command) {
        Object entity=nativeApi.call(source,"net.minecraft.server.command.ServerCommandSource","getEntity");
        Session session=identities.get(entity);
        if(session!=null&&session.player.handle()==entity)session.bridge.command(session.player,command);
        return 1;
    }
    public static boolean allowCommand(Object source) {
        Object entity=nativeApi.call(source,"net.minecraft.server.command.ServerCommandSource","getEntity");
        if(entity==null||!nativeApi.type("net.minecraft.server.network.ServerPlayerEntity").isInstance(entity))return true;
        Session session=identities.get(entity);
        return session!=null&&session.player.handle()==entity&&!session.locked();
    }
}
