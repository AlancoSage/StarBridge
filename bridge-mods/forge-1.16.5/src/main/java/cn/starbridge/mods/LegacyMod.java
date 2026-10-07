package cn.starbridge.mods;
import net.minecraftforge.fml.common.Mod;
import net.minecraftforge.eventbus.api.SubscribeEvent;
import net.minecraftforge.eventbus.api.EventPriority;
import net.minecraftforge.event.entity.player.PlayerEvent;
import net.minecraftforge.event.TickEvent;
import net.minecraftforge.fml.event.server.FMLServerStartedEvent;
import net.minecraftforge.fml.event.server.FMLServerStoppingEvent;
import net.minecraftforge.event.ServerChatEvent;
import net.minecraftforge.event.entity.living.LivingAttackEvent;
import net.minecraftforge.event.entity.player.EntityItemPickupEvent;
@Mod("starbridge")
public final class LegacyMod {
    private final LegacyBootstrap bootstrap=new LegacyBootstrap();
    public LegacyMod() { net.minecraftforge.common.MinecraftForge.EVENT_BUS.register(this); }
    @SubscribeEvent public void started(FMLServerStartedEvent event) { bootstrap.start(event,"1.16.5","36.2.34"); }
    @SubscribeEvent public void stopping(FMLServerStoppingEvent event) { bootstrap.stop(); }
    @SubscribeEvent public void tick(TickEvent.ServerTickEvent event) { bootstrap.tick(event); }
    @SubscribeEvent public void join(PlayerEvent.PlayerLoggedInEvent event) { bootstrap.join(event); }
    @SubscribeEvent public void leave(PlayerEvent.PlayerLoggedOutEvent event) { bootstrap.leave(event); }
    @SubscribeEvent(priority=EventPriority.HIGHEST) public void gate(ServerChatEvent event) { if(bootstrap.chatGate(event))event.setCanceled(true); }
    @SubscribeEvent(priority=EventPriority.LOWEST) public void chat(ServerChatEvent event) { bootstrap.chat(event); }
    @SubscribeEvent public void damage(LivingAttackEvent event) { if(bootstrap.protectAttack(event))event.setCanceled(true); }
    @SubscribeEvent public void pickup(EntityItemPickupEvent event) { if(bootstrap.protectEntity(event))event.setCanceled(true); }
}
