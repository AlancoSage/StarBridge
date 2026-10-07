package cn.starbridge.mods;
import cpw.mods.fml.common.Mod;
import cpw.mods.fml.common.eventhandler.SubscribeEvent;
import cpw.mods.fml.common.eventhandler.EventPriority;
import cpw.mods.fml.common.gameevent.PlayerEvent;
import cpw.mods.fml.common.gameevent.TickEvent;
import cpw.mods.fml.common.event.FMLServerStartedEvent;
import cpw.mods.fml.common.event.FMLServerStoppingEvent;
import net.minecraftforge.event.ServerChatEvent;
import net.minecraftforge.event.entity.living.LivingAttackEvent;
import net.minecraftforge.event.entity.player.EntityItemPickupEvent;
@Mod(modid="starbridge", name="星桥 · Forge 游戏桥接", version="0.1.0", acceptableRemoteVersions="*")
public final class LegacyMod {
    private final LegacyBootstrap bootstrap=new LegacyBootstrap();
    @Mod.EventHandler public void initialize(cpw.mods.fml.common.event.FMLInitializationEvent event) {
        net.minecraftforge.common.MinecraftForge.EVENT_BUS.register(this);
        cpw.mods.fml.common.FMLCommonHandler.instance().bus().register(this);
    }
    @Mod.EventHandler public void started(FMLServerStartedEvent event) { bootstrap.start(event,"1.7.10","10.13.4.1614"); }
    @Mod.EventHandler public void stopping(FMLServerStoppingEvent event) { bootstrap.stop(); }
    @SubscribeEvent public void tick(TickEvent.ServerTickEvent event) { bootstrap.tick(event); }
    @SubscribeEvent public void join(PlayerEvent.PlayerLoggedInEvent event) { bootstrap.join(event); }
    @SubscribeEvent public void leave(PlayerEvent.PlayerLoggedOutEvent event) { bootstrap.leave(event); }
    @SubscribeEvent(priority=EventPriority.HIGHEST) public void gate(ServerChatEvent event) { if(bootstrap.chatGate(event))event.setCanceled(true); }
    @SubscribeEvent(priority=EventPriority.LOWEST) public void chat(ServerChatEvent event) { bootstrap.chat(event); }
    @SubscribeEvent public void damage(LivingAttackEvent event) { if(bootstrap.protectAttack(event))event.setCanceled(true); }
    @SubscribeEvent public void pickup(EntityItemPickupEvent event) { if(bootstrap.protectEntity(event))event.setCanceled(true); }
}
