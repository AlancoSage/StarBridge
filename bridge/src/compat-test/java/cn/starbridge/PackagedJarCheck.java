package cn.starbridge;

/** Run with the final JAR and server API only; no external Gson on the classpath. */
public final class PackagedJarCheck {
    public static void main(String[] args) throws Exception {
        Class<?> gson = Class.forName("cn.starbridge.lib.gson.Gson");
        try (java.util.jar.JarFile jar = new java.util.jar.JarFile(new java.io.File(gson.getProtectionDomain().getCodeSource().getLocation().toURI()))) {
            java.util.Enumeration<java.util.jar.JarEntry> entries = jar.entries();
            while (entries.hasMoreElements()) {
                java.util.jar.JarEntry entry = entries.nextElement();
                if (!entry.getName().endsWith(".class")) continue;
                assert entry.getName().startsWith("cn/starbridge/") : "Unexpected bundled class: " + entry.getName();
                try (java.io.DataInputStream data = new java.io.DataInputStream(jar.getInputStream(entry))) {
                    assert data.readInt() == 0xcafebabe;
                    data.readUnsignedShort(); assert data.readUnsignedShort() <= 52 : "Non-Java-8 class: " + entry.getName();
                }
            }
            assert jar.getEntry("META-INF/licenses/Gson-LICENSE.txt") != null;
            assert jar.getEntry("META-INF/licenses/Myrinbot/LICENSE") != null;
            try (java.io.InputStream descriptor = jar.getInputStream(jar.getEntry("plugin.yml"))) {
                java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
                byte[] buffer = new byte[1024]; int length;
                while ((length = descriptor.read(buffer)) != -1) bytes.write(buffer, 0, length);
                String yaml = new String(bytes.toByteArray(), java.nio.charset.StandardCharsets.UTF_8).replace("\r\n", "\n");
                assert yaml.contains("version: 0.5.4") && yaml.contains("folia-supported: true");
                assert yaml.contains("name: StarBridge\n") : "Existing plugin identity and data folder must remain compatible";
                assert yaml.contains("prefix: Myrinbot") : "Logger prefix must display the new brand";
                assert yaml.contains("main: cn.starbridge.StarBridgePlugin") && yaml.contains("starbridge.bind");
            }
        }
        Object instance = gson.newInstance();
        assert "\"Myrinbot\"".equals(gson.getMethod("toJson", Object.class).invoke(instance, "Myrinbot"));
        // Resolving every declared signature catches hard dependencies on absent event classes.
        Class.forName("cn.starbridge.StarBridgePlugin", false, gson.getClassLoader()).getDeclaredMethods();
        Class.forName("cn.starbridge.GameLogin", false, gson.getClassLoader()).getDeclaredMethods();
        Class.forName("cn.starbridge.AuthMeLink", false, gson.getClassLoader()).getDeclaredMethods();
        Class.forName("cn.starbridge.BridgeScheduler", false, gson.getClassLoader()).getDeclaredMethods();
        System.out.println("Packaged Java 8 JAR checks passed: isolated Gson and production class signatures");
    }
}
