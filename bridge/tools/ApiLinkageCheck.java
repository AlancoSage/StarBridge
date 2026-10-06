import java.io.*;
import java.util.*;
import java.util.jar.*;
import org.objectweb.asm.*;

/** Static Bukkit linkage check; does not start a server or claim runtime compatibility. */
public final class ApiLinkageCheck {
    private static final class Symbol {
        String parent;
        String[] interfaces;
        Set<String> methods = new HashSet<>(), fields = new HashSet<>();
    }
    private static byte[] read(InputStream input) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192]; int count;
        while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
        return output.toByteArray();
    }
    private static boolean exists(Map<String, Symbol> api, String owner, String key, boolean field, Set<String> seen) {
        if (owner == null || !seen.add(owner)) return false;
        Symbol symbol = api.get(owner);
        if (symbol == null) return false;
        if ((field ? symbol.fields : symbol.methods).contains(key)) return true;
        if (key.startsWith("<init>")) return false;
        if (exists(api, symbol.parent, key, field, seen)) return true;
        for (String type : symbol.interfaces) if (exists(api, type, key, field, seen)) return true;
        return false;
    }
    private static Map<String, Symbol> symbols(String path) throws IOException {
        Map<String, Symbol> symbols = new HashMap<>();
        try (JarFile jar = new JarFile(path)) {
            Enumeration<JarEntry> entries = jar.entries();
            while (entries.hasMoreElements()) {
                JarEntry entry = entries.nextElement();
                if (!entry.getName().endsWith(".class")) continue;
                try (InputStream input = jar.getInputStream(entry)) {
                    ClassReader reader = new ClassReader(read(input));
                    Symbol symbol = new Symbol(); symbols.put(reader.getClassName(), symbol);
                    reader.accept(new ClassVisitor(Opcodes.ASM9) {
                        @Override public void visit(int version, int access, String name, String signature, String parent, String[] interfaces) {
                            symbol.parent = parent; symbol.interfaces = interfaces;
                        }
                        @Override public MethodVisitor visitMethod(int access, String name, String descriptor, String signature, String[] exceptions) {
                            symbol.methods.add(name + descriptor); return null;
                        }
                        @Override public FieldVisitor visitField(int access, String name, String descriptor, String signature, Object value) {
                            symbol.fields.add(name + descriptor); return null;
                        }
                    }, ClassReader.SKIP_CODE | ClassReader.SKIP_DEBUG | ClassReader.SKIP_FRAMES);
                }
            }
        }
        // Members inherited from java.lang.Object are stable on all supported JVMs.
        Symbol object = new Symbol(); object.interfaces = new String[0];
        for (java.lang.reflect.Method method : Object.class.getMethods()) object.methods.add(method.getName() + Type.getMethodDescriptor(method));
        symbols.put("java/lang/Object", object);
        Symbol enumeration = new Symbol(); enumeration.parent = "java/lang/Object"; enumeration.interfaces = new String[0];
        for (java.lang.reflect.Method method : Enum.class.getMethods()) enumeration.methods.add(method.getName() + Type.getMethodDescriptor(method));
        symbols.put("java/lang/Enum", enumeration);
        return symbols;
    }
    public static void main(String[] args) throws IOException {
        if (args.length < 2) throw new IllegalArgumentException("plugin.jar api.jar [api.jar ...]");
        for (int index = 1; index < args.length; index++) {
            Map<String, Symbol> available = symbols(args[index]);
            Set<String> errors = new TreeSet<>(), checked = new HashSet<>();
            try (JarFile jar = new JarFile(args[0])) {
                Enumeration<JarEntry> entries = jar.entries();
                while (entries.hasMoreElements()) {
                    JarEntry entry = entries.nextElement();
                    if (!entry.getName().startsWith("cn/starbridge/") || entry.getName().startsWith("cn/starbridge/lib/") || !entry.getName().endsWith(".class")) continue;
                    try (InputStream input = jar.getInputStream(entry)) {
                        new ClassReader(read(input)).accept(new ClassVisitor(Opcodes.ASM9) {
                            void type(String name) {
                                if (name != null && name.startsWith("org/bukkit/") && !available.containsKey(name)) errors.add("Missing class " + name);
                            }
                            void descriptor(String value) {
                                if (value.startsWith("(")) {
                                    for (Type type : Type.getArgumentTypes(value)) descriptor(type.getDescriptor());
                                    descriptor(Type.getReturnType(value).getDescriptor());
                                } else {
                                    Type type = Type.getType(value);
                                    if (type.getSort() == Type.ARRAY) type = type.getElementType();
                                    if (type.getSort() == Type.OBJECT) type(type.getInternalName());
                                }
                            }
                            void member(String owner, String name, String desc, boolean field) {
                                type(owner); descriptor(desc);
                                if (!owner.startsWith("org/bukkit/")) return;
                                checked.add(owner + "." + name + desc);
                                if (!exists(available, owner, name + desc, field, new HashSet<>())) errors.add("Missing member " + owner + "." + name + desc);
                            }
                            @Override public void visit(int version, int access, String name, String signature, String parent, String[] interfaces) {
                                if ((version & 0xffff) > 52) errors.add("Requires newer than Java 8: " + name);
                                type(parent); for (String value : interfaces) type(value);
                            }
                            @Override public FieldVisitor visitField(int access, String name, String desc, String signature, Object value) { descriptor(desc); return null; }
                            @Override public MethodVisitor visitMethod(int access, String name, String desc, String signature, String[] exceptions) {
                                descriptor(desc);
                                return new MethodVisitor(Opcodes.ASM9) {
                                    @Override public void visitMethodInsn(int opcode, String owner, String name, String desc, boolean itf) { member(owner, name, desc, false); }
                                    @Override public void visitFieldInsn(int opcode, String owner, String name, String desc) { member(owner, name, desc, true); }
                                    @Override public void visitTypeInsn(int opcode, String value) { type(value); }
                                    @Override public void visitLdcInsn(Object value) { if (value instanceof Type) descriptor(((Type) value).getDescriptor()); }
                                    @Override public void visitInvokeDynamicInsn(String name, String desc, Handle bootstrap, Object... values) {
                                        descriptor(desc);
                                        for (Object value : values) {
                                            if (value instanceof Type) descriptor(((Type) value).getDescriptor());
                                            if (value instanceof Handle) {
                                                Handle handle = (Handle) value;
                                                member(handle.getOwner(), handle.getName(), handle.getDesc(), handle.getTag() <= Opcodes.H_PUTSTATIC);
                                            }
                                        }
                                    }
                                };
                            }
                        }, ClassReader.SKIP_DEBUG | ClassReader.SKIP_FRAMES);
                    }
                }
            }
            if (!errors.isEmpty()) throw new AssertionError(args[index] + "\n" + String.join("\n", errors));
            System.out.println(new File(args[index]).getName() + ": " + checked.size() + " Bukkit references resolved");
        }
    }
}
