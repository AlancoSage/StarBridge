package cn.starbridge.mods;

import java.nio.file.Paths;
import static cn.starbridge.mods.NativeAccess.*;

/** Lifecycle glue shared by FML 1.x, FML 2.x and Forge 36; no client linkage. */
public final class LegacyBootstrap {
    private LegacyHost host;
    private BridgeEngine bridge;
    public void start(Object event,String version,String loader) {
        Object server=version.equals("1.16.5")?call(event,"getServer"):call(call(type(version.equals("1.7.10")?"cpw.mods.fml.common.FMLCommonHandler":"net.minecraftforge.fml.common.FMLCommonHandler"),"instance"),"getMinecraftServerInstance");
        if(!LegacyHost.dedicated(server))return;
        try {
            host=new LegacyHost(server,version,loader);bridge=new BridgeEngine(host,BridgeConfig.load(Paths.get("config/starbridge-bridge.properties")));
            host.listen();bridge.start();host.log("VexBot Forge "+version+" 游戏端已启动。",null);
        } catch(Exception error) {
            System.err.println("[VexBot] 游戏端初始化失败，已停止服务器。请检查 config/starbridge-bridge.properties；错误类型："+error.getClass().getSimpleName());
            if(host!=null)host.closeListeners();call(server,"initiateShutdown|func_71263_m");host=null;bridge=null;
        }
    }
    public void stop() { if(bridge!=null)bridge.close();if(host!=null)host.closeListeners();bridge=null;host=null; }
    public void tick(Object event) {
        if(bridge==null||!field(event,"phase").toString().equals("END"))return;
        try { host.drain();bridge.gameTick(); }
        catch(RuntimeException error) { host.log("游戏端原生接口异常，已停止服务器；错误类型："+error.getClass().getSimpleName(),null);for(GameHost.Player player:host.players())player.kick("游戏认证保护不可用，请联系管理员。");host.stop(); }
    }
    public void join(Object event) { if(bridge!=null) { Object player=LegacyHost.eventPlayer(event);if(host.isPlayer(player))bridge.join(host.wrap(player)); } }
    public void leave(Object event) { if(bridge!=null) { Object player=LegacyHost.eventPlayer(event);if(host.isPlayer(player))bridge.leave(host.wrap(player)); } }
    public boolean chatGate(Object event) { if(bridge==null)return false;GameHost.Player player=host.wrap(LegacyHost.eventPlayer(event));return bridge.locked(player.id()); }
    public void chat(Object event) { if(bridge!=null)bridge.chat(host.wrap(LegacyHost.eventPlayer(event)),LegacyHost.eventText(event)); }
    public boolean protectEntity(Object event) {
        if(bridge==null)return false;Object entity=property(event,"getEntity|getEntityLiving","entityLiving|entity");
        return host.isPlayer(entity)&&bridge.locked(host.wrap(entity).id());
    }
    public boolean protectAttack(Object event) {
        if(protectEntity(event))return true;if(bridge==null)return false;
        Object source=property(event,"getSource","source"),attacker=call(source,"getTrueSource|getEntity|func_76346_g");return host.isPlayer(attacker)&&bridge.locked(host.wrap(attacker).id());
    }
}
