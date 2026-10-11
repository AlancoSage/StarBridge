import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.jar.*;
import java.util.stream.Stream;
import org.objectweb.asm.*;
import org.objectweb.asm.commons.*;

/** Build-only equivalent of the Gson relocation configured in pom.xml. */
public final class ShadeJar {
    private static final String SOURCE = "com/google/gson";
    private static final String TARGET = "cn/starbridge/lib/gson";
    private static final Remapper MAPPER = new Remapper() {
        @Override public String map(String name) {
            return name.equals(SOURCE) || name.startsWith(SOURCE + "/") ? TARGET + name.substring(SOURCE.length()) : name;
        }
        @Override public Object mapValue(Object value) {
            if (value instanceof String && ((String) value).startsWith("com.google.gson."))
                return "cn.starbridge.lib.gson." + ((String) value).substring("com.google.gson.".length());
            return super.mapValue(value);
        }
    };
    private static byte[] relocate(byte[] bytes) {
        ClassReader reader = new ClassReader(bytes);
        ClassWriter writer = new ClassWriter(0);
        reader.accept(new ClassRemapper(writer, MAPPER), 0);
        return writer.toByteArray();
    }
    private static void entry(JarOutputStream output, Set<String> names, String name, byte[] bytes) throws IOException {
        if (!names.add(name)) throw new IOException("Duplicate plugin entry: " + name);
        output.putNextEntry(new JarEntry(name)); output.write(bytes); output.closeEntry();
    }
    private static void tree(JarOutputStream output, Set<String> names, Path root) throws IOException {
        try (Stream<Path> paths = Files.walk(root)) {
            for (Path path : (Iterable<Path>) paths.filter(Files::isRegularFile).sorted()::iterator) {
                if (Files.isSymbolicLink(path)) throw new IOException("Symlink in plugin input");
                String name = root.relativize(path).toString().replace('\\', '/');
                byte[] bytes = Files.readAllBytes(path);
                entry(output, names, name, name.endsWith(".class") ? relocate(bytes) : bytes);
            }
        }
    }
    public static void main(String[] args) throws IOException {
        Path destination = Paths.get(args[3]), temporary = Paths.get(args[3] + ".new");
        Set<String> names = new HashSet<>();
        try (JarOutputStream output = new JarOutputStream(Files.newOutputStream(temporary))) {
            tree(output, names, Paths.get(args[0]));
            tree(output, names, Paths.get(args[1]));
            if (args.length > 4) {
                Path root = Paths.get(args[4]);
                for (String name : new String[]{"LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"}) {
                    Path path = root.resolve(name);
                    if (Files.isRegularFile(path)) {
                        if (Files.isSymbolicLink(path)) throw new IOException("Symlink in license input");
                        entry(output, names, "META-INF/licenses/Myrinbot/" + name, Files.readAllBytes(path));
                    }
                }
            }
            try (JarFile library = new JarFile(args[2])) {
                Enumeration<JarEntry> entries = library.entries();
                while (entries.hasMoreElements()) {
                    JarEntry item = entries.nextElement();
                    if (!item.getName().startsWith(SOURCE + "/") || !item.getName().endsWith(".class")) continue;
                    try (InputStream input = library.getInputStream(item); ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                        byte[] buffer = new byte[4096]; int count;
                        while ((count = input.read(buffer)) != -1) bytes.write(buffer, 0, count);
                        entry(output, names, TARGET + item.getName().substring(SOURCE.length()), relocate(bytes.toByteArray()));
                    }
                }
            }
        }
        Files.move(temporary, destination, StandardCopyOption.REPLACE_EXISTING);
    }
}
