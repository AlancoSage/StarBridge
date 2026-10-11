package cn.starbridge.mods;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.io.*;
import java.util.*;

/** Properties keeps the Java 8 game ends independent of Forge's changing config APIs. */
public final class BridgeConfig {
    public final String endpoint, serverId, token;
    public final Set<String> commands;
    public BridgeConfig(String endpoint, String serverId, String token, Collection<String> commands) {
        this.endpoint=endpoint; this.serverId=serverId; this.token=token; this.commands=new HashSet<String>(commands);
        Protocol.base(endpoint,serverId,token);
    }
    public static BridgeConfig load(Path file) throws IOException {
        if (!Files.exists(file)) {
            Files.createDirectories(file.toAbsolutePath().getParent());
            Files.write(file, ("# Myrinbot: save connection settings, then restart the server.\nendpoint=http://127.0.0.1:5800\nserver-id=survival\ntoken=CHANGE-ME\nallowed-commands=list\n").getBytes(StandardCharsets.UTF_8));
        }
        Properties values=new Properties();
        try (Reader input=Files.newBufferedReader(file,StandardCharsets.UTF_8)) { values.load(input); }
        List<String> commands=new ArrayList<String>();
        for(String command:values.getProperty("allowed-commands","list").split("\\|")) if(!command.trim().isEmpty()) commands.add(command.trim());
        return new BridgeConfig(values.getProperty("endpoint",""),values.getProperty("server-id",""),values.getProperty("token",""),commands);
    }
}
