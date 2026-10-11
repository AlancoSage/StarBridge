package cn.starbridge.forge;

import net.minecraftforge.common.ForgeConfigSpec;
import java.util.List;

final class Config {
    static final ForgeConfigSpec SPEC;
    static final ForgeConfigSpec.ConfigValue<String> ENDPOINT, SERVER_ID, TOKEN;
    static final ForgeConfigSpec.ConfigValue<List<? extends String>> COMMANDS;
    static {
        ForgeConfigSpec.Builder builder = new ForgeConfigSpec.Builder();
        ENDPOINT = builder.comment("Bot 地址；远程部署请使用 HTTPS。修改连接参数后重启服务器。")
                .define("endpoint", "http://127.0.0.1:5800");
        SERVER_ID = builder.comment("与 Bot 面板配置的服务器 ID 一致。") .define("server-id", "survival");
        TOKEN = builder.comment("该服务器的桥接令牌，不是管理面板令牌。") .define("token", "CHANGE-ME");
        COMMANDS = builder.comment("首次连接前的命令白名单；连接后使用 Bot 面板中的完整命令列表。")
                .defineListAllowEmpty("allowed-commands", List.of("list"), value -> value instanceof String);
        SPEC = builder.build();
    }
}
