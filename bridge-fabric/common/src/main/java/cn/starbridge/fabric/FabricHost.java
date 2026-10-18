package cn.starbridge.fabric;

import cn.starbridge.mods.BridgeEngine;
import cn.starbridge.mods.GameHost;
import com.google.gson.JsonObject;
import java.lang.reflect.Proxy;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import net.fabricmc.loader.api.FabricLoader;

/** Fabric server adapter. All world state and administrative operations stay on the server thread. */
public final class FabricHost implements GameHost {
    private static final String SERVER="net.minecraft.server.MinecraftServer";
    private static final String MANAGER="net.minecraft.server.PlayerManager";
    private static final String STORAGE="net.minecraft.server.ServerConfigList";
    private static final String ENTITY="net.minecraft.entity.Entity";
    private static final String PLAYER="net.minecraft.entity.player.PlayerEntity";
    private static final String SERVER_PLAYER="net.minecraft.server.network.ServerPlayerEntity";
    private static final String PLAY_HANDLER="net.minecraft.server.network.ServerPlayNetworkHandler";
    private static final String COMMON_HANDLER="net.minecraft.server.network.ServerCommonNetworkHandler";
    private static final String PROFILE="com.mojang.authlib.GameProfile";
    private final FabricNative nativeApi;
    private final Object server,manager;
    private final String version;
    private final String profileIdGetter,profileNameGetter;
    private final Path catalog;
    private final ArrayBlockingQueue<Runnable> callbacks=new ArrayBlockingQueue<Runnable>(512);
    private final Map<UUID,FabricPlayer> wrappers=new HashMap<UUID,FabricPlayer>();

    public FabricHost(Object server,String mcVersion) {
        FabricRuntime.initialize();nativeApi=Objects.requireNonNull(FabricRuntime.nativeApi,"Fabric native mappings not initialized");
        this.server=server;version=mcVersion;
        // Authlib 7 replaced these getters with the GameProfile record accessors.
        profileIdGetter=nativeApi.hasExternalMethod(PROFILE,"id","()Ljava/util/UUID;")?"id":"getId";
        profileNameGetter=nativeApi.hasExternalMethod(PROFILE,"name","()Ljava/lang/String;")?"name":"getName";
        if(!mcVersion.equals(nativeApi.minecraftVersion()))throw new IllegalStateException("Fabric game version does not match native mappings");
        manager=nativeApi.call(server,SERVER,"getPlayerManager");
        Object root=nativeApi.field(null,"net.minecraft.util.WorldSavePath","ROOT");
        catalog=((Path)nativeApi.call(server,SERVER,"getSavePath",root)).resolve("starbridge-players.json");
        // Probe the native management surfaces before reporting the game end as ready.
        bans();whites();ops();onlineMode();status();players();
    }
    public FabricNative natives(){return nativeApi;}
    public boolean isPlayer(Object value){return value!=null&&nativeApi.type(SERVER_PLAYER).isInstance(value);}
    public FabricPlayer wrap(Object value) {
        if(!isPlayer(value))throw new IllegalArgumentException("Not a native server player");
        Object profile=nativeApi.call(value,PLAYER,"getGameProfile");
        UUID id=(UUID)nativeApi.direct(profile,PROFILE,profileIdGetter,"()Ljava/util/UUID;");
        FabricPlayer found=wrappers.get(id);
        if(found==null||found.handle()!=value){found=new FabricPlayer(value,profile,id);wrappers.put(id,found);}
        return found;
    }
    public List<GameHost.Player> players() {
        Collection<?> values=(Collection<?>)nativeApi.call(manager,MANAGER,"getPlayerList");
        List<GameHost.Player> result=new ArrayList<GameHost.Player>(values.size());
        for(Object value:values)result.add(wrap(value));return result;
    }
    public GameHost.Player player(UUID id) {
        Object value=nativeApi.call(manager,MANAGER,"getPlayer",id);return value==null?null:wrap(value);
    }
    public Object handler(GameHost.Player player){return nativeApi.field(player.handle(),SERVER_PLAYER,"networkHandler");}
    public Object connection(GameHost.Player player) {
        String owner=nativeApi.hasField(COMMON_HANDLER,"connection")?COMMON_HANDLER:PLAY_HANDLER;
        return nativeApi.field(handler(player),owner,"connection");
    }
    public void execute(Runnable action){if(!callbacks.offer(action))throw new RejectedExecutionException("Game callback queue full");}
    public void drain() {
        for(int count=0;count<256;count++){Runnable action=callbacks.poll();if(action==null)break;action.run();}
        for(FabricPlayer player:wrappers.values())player.refreshAnchor();
    }
    public void stop(){nativeApi.call(server,SERVER,"stop",false);}
    public Path catalogFile(){return catalog;}
    public boolean onlineMode(){return (Boolean)nativeApi.call(server,SERVER,"isOnlineMode");}
    public static boolean dedicated(Object server) {
        FabricRuntime.initialize();
        return (Boolean)Objects.requireNonNull(FabricRuntime.nativeApi,"Fabric native mappings not initialized").call(server,SERVER,"isDedicated");
    }
    public JsonObject status() {
        JsonObject status=new JsonObject();status.addProperty("version",version);
        String loader=FabricLoader.getInstance().getModContainer("fabricloader").get().getMetadata().getVersion().getFriendlyString();
        status.addProperty("server_software","Fabric "+loader);
        status.addProperty("max_players",((Number)nativeApi.call(manager,MANAGER,"getMaxPlayerCount")).intValue());
        status.addProperty("whitelist_enabled",(Boolean)nativeApi.call(manager,MANAGER,"isWhitelistEnabled"));return status;
    }
    private Object profile(UUID id,String name) {
        // From 1.21.11 the native ban, operator and whitelist files use NameAndId.
        String owner=nativeApi.hasClass("net.minecraft.server.PlayerConfigEntry")?"net.minecraft.server.PlayerConfigEntry":PROFILE;
        return nativeApi.create(owner,id,name);
    }
    private Object bans(){return nativeApi.call(manager,MANAGER,"getUserBanList");}
    private Object whites(){return nativeApi.call(manager,MANAGER,"getWhitelist");}
    private Object ops(){return nativeApi.call(manager,MANAGER,"getOpList");}
    private Object entry(Object storage,Object profile){return nativeApi.call(storage,STORAGE,"get",profile);}
    private void save(Object storage){nativeApi.call(storage,STORAGE,"save");}
    public JsonObject flags(UUID id,String name) {
        Object profile=profile(id,name);JsonObject value=new JsonObject();
        value.addProperty("banned",entry(bans(),profile)!=null);value.addProperty("whitelisted",entry(whites(),profile)!=null);
        value.addProperty("op",entry(ops(),profile)!=null);return value;
    }
    public void protect(GameHost.Player player,BridgeEngine bridge) {
        FabricPlayer actual=(FabricPlayer)player;actual.bridge=bridge;actual.refreshAnchor();FabricRuntime.protect(player,bridge);
    }
    public void unprotect(GameHost.Player player) {
        FabricRuntime.unprotect(player);FabricPlayer actual=(FabricPlayer)player;actual.bridge=null;wrappers.remove(actual.id(),actual);
    }
    public void manage(UUID id,String name,String action,String reason,String expectedReason,String kickReason) {
        Object profile=profile(id,name);GameHost.Player online=player(id);
        if(action.equals("kick")){if(online==null)throw new IllegalStateException("Player offline");online.kick(reason);}
        else if(action.equals("ban")) {
            Object ban=nativeApi.create("net.minecraft.server.BannedPlayerEntry",profile,new Date(),"StarBridge",null,reason);
            Object storage=bans();nativeApi.call(storage,STORAGE,"add",ban);save(storage);if(online!=null)online.kick(kickReason);
        } else if(action.equals("unban")) {
            Object storage=bans(),ban=entry(storage,profile);
            if(ban!=null&&expectedReason!=null) {
                Object actualReason=nativeApi.call(ban,"net.minecraft.server.BanEntry","getReason");
                Object source=nativeApi.call(ban,"net.minecraft.server.BanEntry","getSource");
                if(!expectedReason.equals(actualReason)||!"StarBridge".equals(source))throw new IllegalStateException("Independent punishment must be preserved");
            }
            nativeApi.call(storage,STORAGE,"remove",profile);save(storage);
        } else if(action.equals("whitelist_add"))whitelist(id,name);
        else if(action.equals("whitelist_remove")){Object storage=whites();nativeApi.call(storage,STORAGE,"remove",profile);save(storage);}
        else throw new IllegalArgumentException("Unsupported action");
    }
    public void whitelist(UUID id,String name) {
        Object item=nativeApi.create("net.minecraft.server.WhitelistEntry",profile(id,name));Object storage=whites();
        nativeApi.call(storage,STORAGE,"add",item);save(storage);
    }
    public String command(String command) {
        try{return executeCommand(command);}
        catch(RuntimeException error){log("Fabric 原生命令任务执行失败。",error);throw error;}
    }
    private String executeCommand(String command) {
        Object manager=nativeApi.call(server,SERVER,"getCommandManager");
        Object source=nativeApi.call(server,SERVER,"getCommandSource");
        int count;
        String managerOwner="net.minecraft.server.command.CommandManager",sourceOwner="net.minecraft.server.command.ServerCommandSource";
        String entry=nativeApi.hasMethod(managerOwner,"parseAndExecute")?"parseAndExecute":
            nativeApi.hasMethod(managerOwner,"executeWithPrefix")?"executeWithPrefix":"execute";
        if(nativeApi.hasClass("net.minecraft.command.ReturnValueConsumer")&&nativeApi.hasMethod(sourceOwner,"withReturnValueConsumer")) {
            String callbackOwner="net.minecraft.command.ReturnValueConsumer";
            Class<?> callbackType=nativeApi.type(callbackOwner);
            final String resultMethod=nativeApi.methodName(callbackOwner,"onResult","(ZI)V");
            final String successMethod=nativeApi.methodName(callbackOwner,"onSuccess","(I)V");
            final int[] result={0};
            Object callback=Proxy.newProxyInstance(callbackType.getClassLoader(),new Class<?>[]{callbackType},(proxy,method,arguments)->{
                if(method.getName().equals(resultMethod)&&Boolean.TRUE.equals(arguments[0]))
                    result[0]=(int)Math.min(Integer.MAX_VALUE,(long)result[0]+Math.max(0,((Number)arguments[1]).intValue()));
                else if(method.getName().equals(successMethod))
                    result[0]=(int)Math.min(Integer.MAX_VALUE,(long)result[0]+Math.max(0,((Number)arguments[0]).intValue()));
                else if(method.getDeclaringClass()==Object.class) {
                    if(method.getName().equals("equals"))return proxy==arguments[0];
                    if(method.getName().equals("hashCode"))return System.identityHashCode(proxy);
                    if(method.getName().equals("toString"))return "VexBot command result";
                }
                return null;
            });
            source=nativeApi.call(source,sourceOwner,"withReturnValueConsumer",callback);
            nativeApi.call(manager,managerOwner,entry,source,command);count=result[0];
        } else {
            count=((Number)nativeApi.call(manager,managerOwner,entry,source,command)).intValue();
        }
        if(count<=0)throw new IllegalStateException("Command failed");return "命令已执行（"+count+"）";
    }
    public void broadcast(String text){for(GameHost.Player player:players())player.message(text);}
    public void log(String message,Throwable error) {
        System.err.println("[VexBot] "+message);
        // Native error messages may contain command arguments; log types and frames only.
        Set<Throwable> seen=Collections.newSetFromMap(new IdentityHashMap<Throwable,Boolean>());
        for(Throwable cause=error;cause!=null&&seen.add(cause);cause=cause.getCause()) {
            System.err.println("[VexBot] "+cause.getClass().getName());
            StackTraceElement[] frames=cause.getStackTrace();String detail=cause.getMessage();
            if(frames.length>0&&frames[0].getClassName().startsWith("cn.starbridge.fabric.")&&detail!=null
                    &&(detail.startsWith("Native ")||detail.startsWith("External ")||detail.startsWith("Fabric ")))
                System.err.println("[VexBot] "+detail);
            for(StackTraceElement frame:cause.getStackTrace())System.err.println("    at "+frame);
        }
    }
    private Object text(String value) {
        String clipped=value.substring(0,Math.min(value.length(),600));
        if(nativeApi.hasClass("net.minecraft.text.LiteralText"))return nativeApi.create("net.minecraft.text.LiteralText",clipped);
        return nativeApi.call(null,"net.minecraft.text.Text","literal",clipped);
    }

    public final class FabricPlayer implements GameHost.Player {
        private final Object entity;
        private final UUID id;
        private final String name;
        private BridgeEngine bridge;
        private boolean wasLocked;
        private double anchorX,anchorY,anchorZ;
        FabricPlayer(Object entity,Object profile,UUID id) {
            this.entity=entity;this.id=id;name=(String)nativeApi.direct(profile,PROFILE,profileNameGetter,"()Ljava/lang/String;");captureAnchor();
        }
        public Object handle(){return entity;}public UUID id(){return id;}public String name(){return name;}
        public String ip(){return (String)nativeApi.call(entity,SERVER_PLAYER,"getIp");}
        private double coordinate(String axis){return ((Number)nativeApi.call(entity,ENTITY,"get"+axis)).doubleValue();}
        private void captureAnchor(){anchorX=coordinate("X");anchorY=coordinate("Y");anchorZ=coordinate("Z");}
        private void refreshAnchor(){boolean locked=bridge!=null&&bridge.locked(id);if(locked&&!wasLocked)captureAnchor();wasLocked=locked;}
        public void message(String value) {
            if(nativeApi.hasClass("net.minecraft.server.PlayerConfigEntry"))
                nativeApi.call(entity,SERVER_PLAYER,"sendMessage",text(value));
            else nativeApi.call(entity,PLAYER,"sendMessage",text(value),false);
        }
        public void kick(String value) {
            String owner=nativeApi.hasMethod(COMMON_HANDLER,"disconnect")?COMMON_HANDLER:PLAY_HANDLER;
            nativeApi.call(handler(this),owner,"disconnect",text(value));
        }
        public void freeze() {
            refreshAnchor();
            if(Math.abs(coordinate("X")-anchorX)+Math.abs(coordinate("Y")-anchorY)+Math.abs(coordinate("Z")-anchorZ)>0.001) {
                float yaw,pitch;
                if(version.equals("1.16.5")){yaw=((Number)nativeApi.call(entity,ENTITY,"getYaw",1F)).floatValue();pitch=((Number)nativeApi.call(entity,ENTITY,"getPitch",1F)).floatValue();}
                else {yaw=((Number)nativeApi.call(entity,ENTITY,"getYaw")).floatValue();pitch=((Number)nativeApi.call(entity,ENTITY,"getPitch")).floatValue();}
                nativeApi.call(handler(this),PLAY_HANDLER,"requestTeleport",anchorX,anchorY,anchorZ,yaw,pitch);
            }
            nativeApi.call(entity,ENTITY,"setVelocity",0D,0D,0D);nativeApi.setFloating(entity,ENTITY,"fallDistance",0D);
        }
        public JsonObject details() {
            JsonObject value=new JsonObject();value.addProperty("health",((Number)nativeApi.call(entity,"net.minecraft.entity.LivingEntity","getHealth")).doubleValue());
            int ping=nativeApi.hasMethod(COMMON_HANDLER,"getLatency")?((Number)nativeApi.call(handler(this),COMMON_HANDLER,"getLatency")).intValue():((Number)nativeApi.field(entity,SERVER_PLAYER,"pingMilliseconds")).intValue();
            value.addProperty("ping",ping);
            Object interactions=nativeApi.field(entity,SERVER_PLAYER,"interactionManager");
            Object mode=nativeApi.call(interactions,"net.minecraft.server.network.ServerPlayerInteractionManager","getGameMode");
            String modeOwner="net.minecraft.world.GameMode";
            String modeGetter=nativeApi.hasMethod(modeOwner,"getName","()Ljava/lang/String;")?"getName":"getId";
            if(!nativeApi.hasMethod(modeOwner,modeGetter,"()Ljava/lang/String;"))
                throw new IllegalStateException("Native game mode string identifier missing");
            value.addProperty("game_mode",((String)nativeApi.call(mode,modeOwner,modeGetter)).toUpperCase(Locale.ROOT));
            String getter=nativeApi.hasMethod(SERVER_PLAYER,"getServerWorld")?"getServerWorld":
                nativeApi.hasMethod(SERVER_PLAYER,"getEntityWorld")?"getEntityWorld":"getWorld";
            Object world=nativeApi.call(entity,SERVER_PLAYER,getter),key=nativeApi.call(world,"net.minecraft.world.World","getRegistryKey");
            String owner=nativeApi.hasClass("net.minecraft.registry.RegistryKey")?"net.minecraft.registry.RegistryKey":"net.minecraft.util.registry.RegistryKey";
            value.addProperty("world",nativeApi.call(key,owner,"getValue").toString());return value;
        }
    }
}
