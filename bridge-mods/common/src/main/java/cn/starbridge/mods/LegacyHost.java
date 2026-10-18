package cn.starbridge.mods;

import com.google.gson.*;
import io.netty.channel.*;
import io.netty.util.ReferenceCountUtil;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import static cn.starbridge.mods.NativeAccess.*;

/** Native legacy adapter. String SRG names remain stable in production and MCP dev servers. */
public final class LegacyHost implements GameHost {
    private final Object server,list;
    private final String version,loader;
    private final boolean ancient,v16;
    private final Map<UUID,LegacyPlayer> players=new HashMap<UUID,LegacyPlayer>();
    private final ArrayBlockingQueue<Runnable> callbacks=new ArrayBlockingQueue<Runnable>(512);
    private static final String HANDLER="starbridge_login";
    private final Path catalog;
    private final List<Channel> listeners=new ArrayList<Channel>();
    public LegacyHost(Object server,String version,String loader) {
        this.server=server;this.version=version;this.loader=loader;ancient=version.equals("1.7.10");v16=version.equals("1.16.5");
        list=call(server,"getPlayerList|getConfigurationManager|func_184103_al|func_71203_ab");
        if(v16)catalog=((Path)call(server,"getWorldPath|func_240776_a_",create("net.minecraft.world.storage.FolderName","."))).resolve("starbridge-players.json");
        else {
            Object world=call(server,"getWorld|worldServerForDimension|func_71218_a",0);
            Object save=call(world,"getSaveHandler|func_72860_G");
            Object directory=call(save,"getWorldDirectory|func_75765_b");catalog=((java.io.File)directory).toPath().resolve("starbridge-players.json");
        }
        // Probe management APIs up front: a missing native operation must never silently disable protection.
        bans();whites();players();onlineMode();
    }
    public LegacyPlayer wrap(Object player) {
        UUID id=(UUID)call(player,"getUniqueID|getUUID|func_110124_au");LegacyPlayer saved=players.get(id);
        if(saved==null||saved.handle()!=player) { saved=new LegacyPlayer(player);players.put(id,saved); }return saved;
    }
    public boolean isPlayer(Object entity) { if(entity==null)return false;String name=entity.getClass().getName();return name.equals("net.minecraft.entity.player.EntityPlayerMP")||name.equals("net.minecraft.entity.player.ServerPlayerEntity"); }
    public List<GameHost.Player> players() {
        Collection<?> actual=(Collection<?>)property(list,"getPlayers|func_181057_v","playerEntityList|players|field_72404_b");
        List<GameHost.Player> found=new ArrayList<GameHost.Player>();for(Object player:actual)found.add(wrap(player));return found;
    }
    public GameHost.Player player(UUID id) { for(GameHost.Player player:players())if(player.id().equals(id))return player;return null; }
    public void execute(Runnable callback) { if(!callbacks.offer(callback))throw new RejectedExecutionException("Game callback queue full"); }
    public void drain() { for(int i=0;i<256;i++) { Runnable action=callbacks.poll();if(action==null)break;action.run(); } }
    public void stop() { call(server,"initiateShutdown|func_71263_m"); }
    public Path catalogFile() { return catalog; }
    public boolean onlineMode() { return (Boolean)call(server,"isServerInOnlineMode|usesAuthentication|func_71266_T"); }
    public JsonObject status() {
        JsonObject value=new JsonObject();value.addProperty("version",version);value.addProperty("server_software","Forge "+loader);
        value.addProperty("max_players",((Number)call(list,"getMaxPlayers|func_72352_l")).intValue());value.addProperty("whitelist_enabled",(Boolean)call(list,"isWhiteListEnabled|isUsingWhitelist|func_72383_n"));return value;
    }
    private Object bans() { return call(list,"getBannedPlayers|getBans|func_152608_h"); }
    private Object whites() { return call(list,"getWhitelistedPlayers|getWhiteList|func_152599_k"); }
    private Object profile(UUID id,String name) { return create("com.mojang.authlib.GameProfile",id,name); }
    private Object entry(Object storage,Object profile) { return call(storage,"getEntry|get|func_152683_b",profile); }
    public JsonObject flags(UUID id,String name) {
        Object profile=profile(id,name);JsonObject value=new JsonObject();value.addProperty("banned",entry(bans(),profile)!=null);value.addProperty("whitelisted",entry(whites(),profile)!=null);
        Object ops=call(list,"getOppedPlayers|getOps|func_152603_m");value.addProperty("op",entry(ops,profile)!=null);return value;
    }
    private void save(Object storage) { call(storage,"writeChanges|save|func_152678_f"); }
    public void manage(UUID id,String name,String action,String reason,String expectedReason,String kickReason) throws Exception {
        Object profile=profile(id,name);GameHost.Player player=player(id);
        if(action.equals("kick")) { if(player==null)throw new IllegalStateException("Player offline");player.kick(reason); }
        else if(action.equals("ban")) {
            Object ban=create("net.minecraft.server.management.UserListBansEntry|net.minecraft.server.management.ProfileBanEntry",profile,new Date(),"StarBridge",null,reason);
            call(bans(),"addEntry|add|func_152687_a",ban);save(bans());if(player!=null)player.kick(kickReason);
        } else if(action.equals("unban")) {
            Object ban=entry(bans(),profile);if(ban!=null&&expectedReason!=null&&!expectedReason.equals(call(ban,"getBanReason|getReason|func_73686_f")))throw new IllegalStateException("Independent punishment must be preserved");
            call(bans(),"removeEntry|remove|func_152684_c",profile);save(bans());
        } else if(action.equals("whitelist_add"))whitelist(id,name);
        else if(action.equals("whitelist_remove")) { call(whites(),"removeEntry|remove|func_152684_c",profile);save(whites()); }
        else throw new IllegalArgumentException("Unsupported action");
    }
    public void whitelist(UUID id,String name) {
        Object entry=create("net.minecraft.server.management.UserListWhitelistEntry|net.minecraft.server.management.WhitelistEntry",profile(id,name));call(whites(),"addEntry|add|func_152687_a",entry);save(whites());
    }
    public void broadcast(String text) { for(GameHost.Player player:players())player.message(text); }
    public String command(String command) {
        Object manager=call(server,"getCommandManager|getCommands|func_71187_D|func_195571_aL");
        int count=((Number)(v16?call(manager,"handleCommand|func_197059_a",call(server,"getCommandSource|createCommandSourceStack|func_195573_aM"),command):call(manager,"executeCommand|handleCommand|func_71556_a",server,command))).intValue();
        if(count<=0)throw new IllegalStateException("Command failed");return "命令已执行（"+count+"）";
    }
    public void log(String message,Throwable error) { System.err.println("[VexBot] "+message); }
    private Channel channel(Object player) {
        Object handler=field(player,"playerNetServerHandler|connection|field_71135_a");Object manager=byType(handler,"net.minecraft.network.NetworkManager");return (Channel)byType(manager,"io.netty.channel.Channel");
    }
    public void protect(GameHost.Player player,BridgeEngine bridge) {
        final LegacyPlayer actual=(LegacyPlayer)player;
        try {
            final Channel channel=channel(player.handle());actual.channel=channel;
            channel.eventLoop().execute(()->{
                try {
                    if(channel.pipeline().get(HANDLER)!=null)channel.pipeline().remove(HANDLER);
                    channel.pipeline().addBefore("packet_handler",HANDLER,new ChannelInboundHandlerAdapter() {
                        private long ingress,auxiliary;
                        @Override public void channelRead(ChannelHandlerContext context,Object packet) throws Exception {
                            String type=packet.getClass().getSimpleName();
                            if(type.equals("C01PacketChatMessage")||type.equals("CPacketChatMessage")||type.equals("CChatMessagePacket")) {
                                String text=(String)call(packet,"getMessage|func_149439_c");
                                if(text.startsWith("/")) {
                                    String raw=text.substring(1),root=raw.split(" ",2)[0];
                                    if(BridgeEngine.authCommand(raw)||root.equals("logout")||root.equals("qbind")) {
                                        long now=System.currentTimeMillis();boolean authentication=BridgeEngine.authCommand(raw);
                                        if(now-(authentication?ingress:auxiliary)>=1000) {
                                            if(authentication)ingress=now;else auxiliary=now;bridge.callback(()->bridge.command(actual,raw));
                                        }
                                        ReferenceCountUtil.release(packet);return;
                                    }
                                }
                            }
                            if(bridge.locked(actual.id())&&!hygiene(type)) { ReferenceCountUtil.release(packet);return; }
                            super.channelRead(context,packet);
                        }
                    });
                } catch(RuntimeException error) { bridge.callback(()->actual.kick("登录保护初始化失败，请联系管理员检查 Forge 版本。")); }
            });
        } catch(RuntimeException error) { player.kick("登录保护初始化失败，请联系管理员。"); }
    }
    public static boolean hygiene(String name) { return Arrays.asList("C00PacketKeepAlive","CPacketKeepAlive","CKeepAlivePacket","C15PacketClientSettings","CPacketClientSettings","CClientSettingsPacket","CPacketConfirmTeleport","CConfirmTeleportPacket","CPacketResourcePackStatus","CResourcePackStatusPacket").contains(name); }
    public static void negotiate(Object manager) {
        final Channel channel=(Channel)byType(manager,"io.netty.channel.Channel");
        negotiateChannel(channel);
    }
    private static void negotiateChannel(final Channel channel) {
        channel.eventLoop().execute(()->{
            if(channel.pipeline().get(HANDLER)!=null)return;
            channel.pipeline().addBefore("packet_handler",HANDLER,new ChannelInboundHandlerAdapter() {
                @Override public void channelRead(ChannelHandlerContext context,Object packet) throws Exception {
                    String type=packet.getClass().getSimpleName();
                    boolean handshake=false;
                    if(type.equals("C17PacketCustomPayload")||type.equals("CPacketCustomPayload")) {
                        String name=(String)call(packet,"getChannelName|func_149559_c");
                        handshake=Arrays.asList("FML|HS","FML","REGISTER","MC|Brand").contains(name);
                    }
                    if(packet.getClass().getName().startsWith("net.minecraft.network.play.client.")&&!hygiene(type)&&!handshake) { ReferenceCountUtil.release(packet);return; }super.channelRead(context,packet);
                }
            });
        });
    }
    /** Install at channel activation, before any play packet can queue onto the game thread. */
    public void listen() {
        Object network=call(server,"getNetworkSystem|getConnection|func_147137_ag");
        Collection<?> endpoints=(Collection<?>)field(network,"endpoints|channels|field_151274_e");
        for(Object value:endpoints) {
            Channel channel=((ChannelFuture)value).channel();listeners.add(channel);
            channel.eventLoop().submit(()->{
                channel.pipeline().addFirst("starbridge_accept",new ChannelInboundHandlerAdapter() {
                    @Override public void channelRead(ChannelHandlerContext context,Object child) throws Exception {
                        if(child instanceof Channel) {
                            final Channel connection=(Channel)child;
                            connection.pipeline().addLast("starbridge_prepare",new ChannelInboundHandlerAdapter() {
                                @Override public void channelActive(ChannelHandlerContext context) throws Exception {
                                    negotiateChannel(connection);context.pipeline().remove(this);super.channelActive(context);
                                }
                            });
                        }
                        super.channelRead(context,child);
                    }
                });
            }).syncUninterruptibly();
        }
        if(listeners.isEmpty())throw new IllegalStateException("No dedicated server listener");
    }
    public void closeListeners() { for(Channel channel:listeners)channel.eventLoop().execute(()->{if(channel.pipeline().get("starbridge_accept")!=null)channel.pipeline().remove("starbridge_accept");});listeners.clear(); }
    public void unprotect(GameHost.Player player) { LegacyPlayer actual=(LegacyPlayer)player;if(actual.channel!=null)actual.channel.eventLoop().execute(()->{if(actual.channel.pipeline().get(HANDLER)!=null)actual.channel.pipeline().remove(HANDLER);});players.remove(actual.id(),actual); }
    public final class LegacyPlayer implements GameHost.Player {
        private final Object entity;private final UUID id;private final String name;private final double x,y,z;private Channel channel;
        LegacyPlayer(Object entity) { this.entity=entity;id=(UUID)call(entity,"getUniqueID|getUUID|func_110124_au");name=(String)call(call(entity,"getGameProfile|func_146103_bH"),"getName");x=coordinate("X");y=coordinate("Y");z=coordinate("Z"); }
        public Object handle() { return entity; } public UUID id(){return id;}public String name(){return name;}
        public String ip(){return (String)call(entity,"getPlayerIP|getIpAddress|func_71114_r");}
        private double coordinate(String axis) { String srg=axis.equals("X")?"field_70165_t":axis.equals("Y")?"field_70163_u":"field_70161_v";String getter=axis.equals("X")?"func_226277_ct_":axis.equals("Y")?"func_226278_cu_":"func_226281_cx_";return ((Number)property(entity,"getPos"+axis+"|get"+axis+"|"+getter,"pos"+axis+"|"+srg)).doubleValue(); }
        private Object text(String message) { return create("net.minecraft.util.ChatComponentText|net.minecraft.util.text.TextComponentString|net.minecraft.util.text.StringTextComponent",Protocol.clip(message,600)); }
        public void message(String message) { if(v16)call(entity,"sendMessage|func_145747_a",text(message),new UUID(0,0));else call(entity,"sendMessage|addChatMessage|func_145747_a",text(message)); }
        public void kick(String reason) { Object handler=field(entity,"playerNetServerHandler|connection|field_71135_a");if(ancient)call(handler,"kickPlayerFromServer|func_147360_c",Protocol.clip(reason,600));else call(handler,"disconnect|func_194028_b|func_147360_c",text(reason)); }
        public void freeze() {
            if(Math.abs(coordinate("X")-x)+Math.abs(coordinate("Y")-y)+Math.abs(coordinate("Z")-z)>0.001) {
                Object handler=field(entity,"playerNetServerHandler|connection|field_71135_a");
                float yaw=((Number)field(entity,"rotationYaw|yRot|field_70177_z")).floatValue(),pitch=((Number)field(entity,"rotationPitch|xRot|field_70125_A")).floatValue();
                call(handler,"setPlayerLocation|teleport|func_147364_a",x,y,z,yaw,pitch);
            }
            if(v16)call(entity,"setMotion|setDeltaMovement|func_213293_j",0D,0D,0D);
            else { set(entity,"motionX|field_70159_w",0D);set(entity,"motionY|field_70181_x",0D);set(entity,"motionZ|field_70179_y",0D); }
            set(entity,"fallDistance|field_70143_R",0F);
        }
        public JsonObject details() {
            JsonObject value=new JsonObject();value.addProperty("health",((Number)call(entity,"getHealth|func_110143_aJ")).doubleValue());value.addProperty("ping",((Number)field(entity,"ping|field_71138_i")).intValue());
            Object manager=field(entity,"theItemInWorldManager|interactionManager|gameMode|field_71134_c");Object mode=call(manager,"getGameType|getGameModeForPlayer|func_73081_b");value.addProperty("game_mode",((String)call(mode,"getName|func_77149_b")).toUpperCase(Locale.ROOT));
            if(!v16) { Object world=field(entity,"worldObj|world|field_70170_p");Object provider=field(world,"provider|field_73011_w");Object dimension=ancient?field(provider,"dimensionId|field_76574_g"):call(provider,"getDimension|func_186058_p");value.addProperty("world",dimension.toString()); }
            else { Object world=field(entity,"world|level|field_70170_p");value.addProperty("world",call(call(world,"getDimensionKey|dimension|func_234923_W_"),"getLocation|location|func_240901_a_").toString()); }
            return value;
        }
    }
    public static Object eventPlayer(Object event) { return property(event,"getPlayer|getEntity|getEntityLiving","player|entityPlayer|entityLiving|entity"); }
    public static String eventText(Object event) { return (String)property(event,"getMessage|getRawText","message"); }
    public static boolean dedicated(Object server) { return (Boolean)call(server,"isDedicatedServer|func_71262_S"); }
}
