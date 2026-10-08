package cn.starbridge.fabric;

import io.netty.channel.*;
import io.netty.util.ReferenceCountUtil;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** Decoded ingress filter installed before packet_handler, including the first play packet. */
public final class FabricPacketGate extends ChannelInboundHandlerAdapter {
    private static final String HANDLER="starbridge_auth";
    private static final String CONNECTION="net.minecraft.network.ClientConnection";
    private static final String CHAT="net.minecraft.network.packet.c2s.play.ChatMessageC2SPacket";
    private static final String COMMAND="net.minecraft.network.packet.c2s.play.CommandExecutionC2SPacket";
    private static final String SIGNED_COMMAND="net.minecraft.network.packet.c2s.play.ChatCommandSignedC2SPacket";
    private static final Map<Object,FabricPacketGate> gates=new ConcurrentHashMap<Object,FabricPacketGate>();
    private static final Set<String> SAFE=new HashSet<String>(Arrays.asList(
        "KeepAliveC2SPacket","PongC2SPacket","TeleportConfirmC2SPacket","ClientSettingsC2SPacket",
        "ResourcePackStatusC2SPacket","MessageAcknowledgmentC2SPacket","ChatSessionUpdateC2SPacket",
        "AcknowledgeReconfigurationC2SPacket","ClientOptionsC2SPacket","CommonPongC2SPacket",
        "PlayerSessionC2SPacket","AcknowledgeChunksC2SPacket","PlayerLoadedC2SPacket","ClientTickEndC2SPacket"));
    private final Object connection;
    private volatile FabricRuntime.Session session;
    private long lastLogin;
    private long lastAuxiliary;
    private FabricPacketGate(Object connection){this.connection=connection;}

    public static void install(Object connection,ChannelHandlerContext context) {
        FabricPacketGate gate=new FabricPacketGate(connection);
        if(gates.putIfAbsent(connection,gate)!=null)return;
        try {context.pipeline().addBefore("packet_handler",HANDLER,gate);}
        catch(Throwable error) {
            gates.remove(connection,gate);context.close();
            FabricRuntime.report("无法安装登录保护，已关闭连接。",error);
        }
    }
    public static void remove(Object connection,ChannelHandlerContext context){gates.remove(connection);}
    static void clear(){gates.clear();}
    static void attach(Object connection,FabricRuntime.Session session) {
        FabricPacketGate gate=gates.get(connection);
        if(gate==null)throw new IllegalStateException("Fabric player connection has no ingress guard");
        gate.session=session;
    }
    static void detach(FabricRuntime.Session prior) {
        for(FabricPacketGate gate:gates.values())if(gate.session==prior)gate.session=null;
    }
    private static String shortName(String name){return name.substring(name.lastIndexOf('.')+1);}
    private boolean commonIsPlay(FabricNative nativeApi) {
        Object listener=nativeApi.call(connection,CONNECTION,"getPacketListener");
        return listener!=null&&nativeApi.type("net.minecraft.server.network.ServerPlayNetworkHandler").isInstance(listener);
    }
    private boolean command(FabricRuntime.Session member,String raw) {
        if(member==null||raw.length()>512||!FabricRuntime.routed(raw))return false;
        if(cn.starbridge.mods.BridgeEngine.authCommand(raw)) {
            long now=System.nanoTime();if(now-lastLogin<1_000_000_000L)return true;lastLogin=now;
        } else {
            long now=System.nanoTime();if(now-lastAuxiliary<1_000_000_000L)return true;lastAuxiliary=now;
        }
        FabricRuntime.queueCommand(member,raw);return true;
    }
    /** The inert command retains the exact native timestamp/salt/ack bookkeeping. */
    private Object scrub(Object packet,String owner,FabricNative nativeApi) {
        if(!nativeApi.hasMethod(owner,"timestamp"))return null;
        Object timestamp=nativeApi.call(packet,owner,"timestamp"),salt=nativeApi.call(packet,owner,"salt");
        Object signatures=nativeApi.field(null,"net.minecraft.network.message.ArgumentSignatureDataMap","EMPTY");
        String getter=nativeApi.hasMethod(owner,"lastSeenMessages")?"lastSeenMessages":"acknowledgment";
        Object acknowledgment=nativeApi.call(packet,owner,getter);
        if(nativeApi.hasMethod(owner,"signedPreview"))
            return nativeApi.create(owner,"starbridge:session",timestamp,salt,signatures,false,acknowledgment);
        return nativeApi.create(owner,"starbridge:session",timestamp,salt,signatures,acknowledgment);
    }

    @Override public void channelRead(ChannelHandlerContext context,Object packet) throws Exception {
        boolean forwarded=false;
        String owner=null;
        try {
            owner=FabricRuntime.packetNames.get(packet.getClass().getName());
            FabricNative nativeApi=FabricRuntime.nativeApi;
            if(owner==null) {
                FabricRuntime.Session current=session;
                if((current==null||current.locked())&&commonIsPlay(nativeApi))return;
                forwarded=true;context.fireChannelRead(packet);return;
            }
            if(owner.contains(".c2s.common.")&&!commonIsPlay(nativeApi)) {
                forwarded=true;context.fireChannelRead(packet);return;
            }
            FabricRuntime.Session member=session;
            boolean locked=member==null||member.locked();
            if(owner.equals(COMMAND)||owner.equals(SIGNED_COMMAND)) {
                String raw=(String)nativeApi.call(packet,owner,"command");
                if(FabricRuntime.routed(raw)) {
                    command(member,raw);
                    Object safe=scrub(packet,owner,nativeApi);
                    if(safe!=null)context.fireChannelRead(safe);
                    return;
                }
                // Signed non-login commands must advance vanilla's signature chain first;
                // the CommandManager Mixin blocks execution after native validation.
                forwarded=true;context.fireChannelRead(packet);return;
            } else if(owner.equals(CHAT)&&nativeApi.hasMethod(CHAT,"getChatMessage")) {
                String raw=(String)nativeApi.call(packet,CHAT,"getChatMessage");
                if(raw.startsWith("/")) {
                    String value=raw.substring(1);
                    if(FabricRuntime.routed(value)||locked){command(member,value);return;}
                } else {
                    if(locked)return;
                    FabricRuntime.queueChat(member,raw);
                }
            }
            // Modern chat reaches the downstream broadcast Mixin after native ACK validation.
            if(locked&&!owner.equals(CHAT)&&!SAFE.contains(shortName(owner)))return;
            forwarded=true;context.fireChannelRead(packet);
        } catch(Throwable error) {
            context.close();FabricRuntime.report("登录保护无法解析原生数据包，已关闭连接。",error);
        } finally {
            if(!forwarded) {
                // 1.16–1.20 CustomPayload owns a separate PacketByteBuf. Vanilla normally
                // releases it in Packet.apply(); discarded packets never reach that method.
                if(owner!=null&&owner.endsWith(".CustomPayloadC2SPacket")
                        &&FabricRuntime.nativeApi.hasField(owner,"data"))
                    ReferenceCountUtil.release(FabricRuntime.nativeApi.field(packet,owner,"data"));
                ReferenceCountUtil.release(packet);
            }
        }
    }
}
