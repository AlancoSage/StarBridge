package cn.starbridge.fabric;

import net.fabricmc.api.ModInitializer;

/** Server-only entry point; lifecycle hooks use the loader's bundled Mixin. */
public final class StarBridgeFabric implements ModInitializer {
    @Override public void onInitialize() { FabricRuntime.initialize(); }
}
