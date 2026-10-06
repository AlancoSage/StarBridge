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
        }
        Object instance = gson.newInstance();
        assert "\"星桥\"".equals(gson.getMethod("toJson", Object.class).invoke(instance, "星桥"));
        // Resolving every declared signature catches hard dependencies on absent event classes.
        Class.forName("cn.starbridge.StarBridgePlugin", false, gson.getClassLoader()).getDeclaredMethods();
        Class.forName("cn.starbridge.GameLogin", false, gson.getClassLoader()).getDeclaredMethods();
        Class.forName("cn.starbridge.AuthMeLink", false, gson.getClassLoader()).getDeclaredMethods();
        System.out.println("Packaged Java 8 JAR checks passed: isolated Gson and production class signatures");
    }
}
