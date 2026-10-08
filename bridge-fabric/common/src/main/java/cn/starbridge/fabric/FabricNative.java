package cn.starbridge.fabric;

import com.google.gson.*;
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import net.fabricmc.loader.api.FabricLoader;
import net.fabricmc.loader.api.MappingResolver;

/** Exact member bindings in intermediary or the unobfuscated official runtime namespace. */
public final class FabricNative {
    private final MappingResolver resolver;
    private final String minecraftVersion;
    private final boolean officialNamespace;
    private final Map<String,String> classes=new HashMap<String,String>();
    private final Map<String,List<Member>> methods=new HashMap<String,List<Member>>();
    private final Map<String,List<Member>> fields=new HashMap<String,List<Member>>();
    private final Map<String,Class<?>> loaded=new ConcurrentHashMap<String,Class<?>>();
    private final Map<String,Method> boundMethods=new ConcurrentHashMap<String,Method>();
    private final Map<String,Field> boundFields=new ConcurrentHashMap<String,Field>();

    private static final class Member {
        final String owner,name,intermediary,descriptor;
        Member(JsonObject value) {
            owner=value.get("owner").getAsString().replace('/','.');
            name=value.get("name").getAsString();
            intermediary=value.get("intermediary").getAsString();
            descriptor=value.get("descriptor").getAsString();
        }
        String key(){return owner+"#"+name+"#"+descriptor;}
    }

    public FabricNative() {
        resolver=FabricLoader.getInstance().getMappingResolver();
        try(InputStream input=FabricNative.class.getResourceAsStream("/starbridge-fabric-mappings.json")) {
            if(input==null)throw new IllegalStateException("Fabric native mappings missing");
            JsonObject document=new JsonParser().parse(new InputStreamReader(input,StandardCharsets.UTF_8)).getAsJsonObject();
            minecraftVersion=document.get("mcVersion").getAsString();
            String namespace=document.has("namespace")?document.get("namespace").getAsString():"intermediary";
            if(!namespace.equals("intermediary")&&!namespace.equals("official"))
                throw new IllegalStateException("Fabric native mapping namespace unsupported");
            officialNamespace=namespace.equals("official");
            for(Map.Entry<String,JsonElement> entry:document.getAsJsonObject("classes").entrySet())
                classes.put(entry.getKey().replace('/','.'),entry.getValue().getAsString().replace('/','.'));
            for(JsonElement value:document.getAsJsonArray("methods")) {
                Member member=new Member(value.getAsJsonObject());
                String key=member.owner+"#"+member.name;
                List<Member> list=methods.get(key);
                if(list==null){list=new ArrayList<Member>();methods.put(key,list);}
                list.add(member);
            }
            for(JsonElement value:document.getAsJsonArray("fields")) {
                Member member=new Member(value.getAsJsonObject());
                String key=member.owner+"#"+member.name;
                List<Member> list=fields.get(key);
                if(list==null){list=new ArrayList<Member>();fields.put(key,list);}
                list.add(member);
            }
        } catch(IOException error) {throw new IllegalStateException("Fabric native mappings unreadable",error);}
    }

    public boolean hasClass(String named){return classes.containsKey(named);}
    public String minecraftVersion(){return minecraftVersion;}
    public boolean hasMethod(String owner,String name){return methods.containsKey(owner+"#"+name);}
    public boolean hasMethod(String owner,String name,String descriptor) {
        List<Member> choices=methods.get(owner+"#"+name);
        if(choices!=null)for(Member member:choices)if(member.descriptor.equals(descriptor))return true;
        return false;
    }
    public boolean hasField(String owner,String name){return fields.containsKey(owner+"#"+name);}
    public String runtimeClassName(String binding) {
        return officialNamespace?binding:resolver.mapClassName("intermediary",binding);
    }
    private String runtimeMethodName(String owner,String name,String descriptor) {
        return officialNamespace?name:resolver.mapMethodName("intermediary",owner,name,descriptor);
    }
    private String runtimeFieldName(String owner,String name,String descriptor) {
        return officialNamespace?name:resolver.mapFieldName("intermediary",owner,name,descriptor);
    }
    public String methodName(String owner,String name,String descriptor) {
        List<Member> choices=methods.get(owner+"#"+name);
        if(choices!=null)for(Member member:choices)if(member.descriptor.equals(descriptor))
            return runtimeMethodName(classes.get(owner),member.intermediary,member.descriptor);
        throw new IllegalStateException("Native mapped descriptor missing: "+owner+"#"+name);
    }

    public Class<?> type(String named) {
        Class<?> saved=loaded.get(named);if(saved!=null)return saved;
        String intermediary=classes.get(named);
        String actual=intermediary==null?named:runtimeClassName(intermediary);
        try {
            Class<?> value=Class.forName(actual,false,FabricNative.class.getClassLoader());loaded.put(named,value);return value;
        } catch(ClassNotFoundException error){throw new IllegalStateException("Native class unavailable: "+named,error);}
    }

    private Class<?> descriptorType(String descriptor,int[] cursor) {
        char value=descriptor.charAt(cursor[0]++);
        switch(value) {
            case 'V':return void.class;case 'Z':return boolean.class;case 'B':return byte.class;
            case 'C':return char.class;case 'S':return short.class;case 'I':return int.class;
            case 'J':return long.class;case 'F':return float.class;case 'D':return double.class;
            case '[':return Array.newInstance(descriptorType(descriptor,cursor),0).getClass();
            case 'L':
                int end=descriptor.indexOf(';',cursor[0]);
                if(end<0)throw new IllegalArgumentException("Invalid native descriptor");
                String intermediary=descriptor.substring(cursor[0],end).replace('/','.');cursor[0]=end+1;
                String actual=intermediary.startsWith("net.minecraft.")?runtimeClassName(intermediary):intermediary;
                try{return Class.forName(actual,false,FabricNative.class.getClassLoader());}
                catch(ClassNotFoundException error){throw new IllegalStateException("Native descriptor class unavailable",error);}
            default:throw new IllegalArgumentException("Invalid native descriptor");
        }
    }
    private Class<?>[] parameters(String descriptor) {
        if(descriptor.charAt(0)!='(')throw new IllegalArgumentException("Invalid native method descriptor");
        int[] cursor={1};List<Class<?>> parameters=new ArrayList<Class<?>>();
        while(descriptor.charAt(cursor[0])!=')')parameters.add(descriptorType(descriptor,cursor));
        return parameters.toArray(new Class<?>[parameters.size()]);
    }
    private Class<?> returnType(String descriptor) {return descriptorType(descriptor,new int[]{descriptor.indexOf(')')+1});}
    private static Class<?> boxed(Class<?> type) {
        if(type==boolean.class)return Boolean.class;if(type==byte.class)return Byte.class;if(type==char.class)return Character.class;
        if(type==short.class)return Short.class;if(type==int.class)return Integer.class;if(type==long.class)return Long.class;
        if(type==float.class)return Float.class;if(type==double.class)return Double.class;return type;
    }
    private static boolean accepts(Class<?>[] parameters,Object[] arguments) {
        if(parameters.length!=arguments.length)return false;
        for(int index=0;index<parameters.length;index++) {
            if(arguments[index]==null){if(parameters[index].isPrimitive())return false;}
            else if(!boxed(parameters[index]).isInstance(arguments[index]))return false;
        }
        return true;
    }
    private Method bind(Member member) {
        Method saved=boundMethods.get(member.key());if(saved!=null)return saved;
        String owner=classes.get(member.owner);
        if(owner==null)throw new IllegalStateException("Native method owner missing: "+member.owner);
        String actual=runtimeMethodName(owner,member.intermediary,member.descriptor);
        try {
            Method value=type(member.owner).getDeclaredMethod(actual,parameters(member.descriptor));
            if(value.getReturnType()!=returnType(member.descriptor))throw new IllegalStateException("Native method return descriptor mismatch");
            value.setAccessible(true);boundMethods.put(member.key(),value);return value;
        } catch(NoSuchMethodException error){throw new IllegalStateException("Native mapped method unavailable: "+member.owner+"#"+member.name,error);}
    }
    private static Object invoke(Method method,Object target,Object...arguments) {
        try{return method.invoke(Modifier.isStatic(method.getModifiers())?null:target,arguments);}
        catch(InvocationTargetException error){throw new IllegalStateException("Native operation rejected",error.getCause());}
        catch(ReflectiveOperationException error){throw new IllegalStateException("Native invocation unavailable",error);}
    }
    public Object call(Object target,String owner,String name,Object...arguments) {
        List<Member> choices=methods.get(owner+"#"+name);
        if(choices==null)throw new IllegalStateException("Native mapped method missing: "+owner+"#"+name);
        Member found=null;
        for(Member choice:choices)if(!choice.name.equals("<init>")&&accepts(parameters(choice.descriptor),arguments)) {
            if(found!=null)throw new IllegalStateException("Native method overload ambiguous: "+owner+"#"+name);
            found=choice;
        }
        if(found==null)throw new IllegalStateException("Native method descriptor missing: "+owner+"#"+name);
        return invoke(bind(found),target,arguments);
    }
    /** Direct external Java API invocation still requires an exact descriptor. */
    public boolean hasExternalMethod(String owner,String name,String descriptor) {
        try {
            Method method=type(owner).getDeclaredMethod(name,parameters(descriptor));
            return method.getReturnType()==returnType(descriptor);
        } catch(NoSuchMethodException absent){return false;}
    }
    public Object direct(Object target,String owner,String name,String descriptor,Object...arguments) {
        try {
            Class<?>[] parameters=parameters(descriptor);
            if(!accepts(parameters,arguments))throw new IllegalArgumentException("External API arguments mismatch");
            Method method=type(owner).getDeclaredMethod(name,parameters);
            if(method.getReturnType()!=returnType(descriptor))throw new IllegalStateException("External API return descriptor mismatch");
            method.setAccessible(true);return invoke(method,target,arguments);
        } catch(NoSuchMethodException error){throw new IllegalStateException("External API method missing: "+owner+"#"+name,error);}
    }
    private Field bindField(String owner,String name) {
        String key=owner+"#"+name;Field saved=boundFields.get(key);if(saved!=null)return saved;
        List<Member> choices=fields.get(key);if(choices==null)throw new IllegalStateException("Native mapped field missing: "+key);
        if(choices.size()!=1)throw new IllegalStateException("Native mapped field ambiguous: "+key);
        Member member=choices.get(0);
        String actual=runtimeFieldName(classes.get(owner),member.intermediary,member.descriptor);
        try {
            Field value=type(owner).getDeclaredField(actual);
            if(value.getType()!=descriptorType(member.descriptor,new int[]{0}))throw new IllegalStateException("Native field descriptor mismatch: "+key);
            value.setAccessible(true);boundFields.put(key,value);return value;
        } catch(NoSuchFieldException error){throw new IllegalStateException("Native mapped field unavailable: "+key,error);}
    }
    public Object field(Object target,String owner,String name) {
        Field field=bindField(owner,name);
        try{return field.get(Modifier.isStatic(field.getModifiers())?null:target);}
        catch(IllegalAccessException error){throw new IllegalStateException("Native field inaccessible",error);}
    }
    public void set(Object target,String owner,String name,Object value) {
        Field field=bindField(owner,name);
        if(value==null?field.getType().isPrimitive():!boxed(field.getType()).isInstance(value))throw new IllegalArgumentException("Native field value mismatch");
        try{field.set(Modifier.isStatic(field.getModifiers())?null:target,value);}
        catch(IllegalAccessException error){throw new IllegalStateException("Native field inaccessible",error);}
    }
    /** Native fall distance changed from float to double; retain the exact declared type. */
    public void setFloating(Object target,String owner,String name,double value) {
        Class<?> kind=bindField(owner,name).getType();
        if(kind==float.class)set(target,owner,name,Float.valueOf((float)value));
        else if(kind==double.class)set(target,owner,name,Double.valueOf(value));
        else throw new IllegalStateException("Native floating field descriptor mismatch: "+owner+"#"+name);
    }
    public Object create(String owner,Object...arguments) {
        Class<?> type=type(owner);Constructor<?> found=null;
        List<Member> choices=methods.get(owner+"#<init>");
        try {
            if(choices!=null)for(Member choice:choices) {
                Class<?>[] parameters=parameters(choice.descriptor);if(!accepts(parameters,arguments))continue;
                if(found!=null)throw new IllegalStateException("Native constructor ambiguous: "+owner);
                found=type.getDeclaredConstructor(parameters);
            }
            else if(!classes.containsKey(owner))for(Constructor<?> candidate:type.getDeclaredConstructors()) {
                if(!accepts(candidate.getParameterTypes(),arguments))continue;
                if(found!=null)throw new IllegalStateException("External constructor ambiguous: "+owner);found=candidate;
            }
            if(found==null)throw new IllegalStateException("Native constructor descriptor missing: "+owner);
            found.setAccessible(true);return found.newInstance(arguments);
        } catch(InvocationTargetException error){throw new IllegalStateException("Native constructor rejected",error.getCause());}
        catch(ReflectiveOperationException error){throw new IllegalStateException("Native constructor unavailable: "+owner,error);}
    }
}
