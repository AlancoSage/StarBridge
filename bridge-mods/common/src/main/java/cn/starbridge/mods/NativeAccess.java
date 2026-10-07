package cn.starbridge.mods;

import java.lang.reflect.*;
import java.util.*;

/** Explicit MCP/SRG alternatives; never fall back to a guessed unrelated method. */
final class NativeAccess {
    private static boolean accepts(Class<?> type,Object value) {
        if(value==null)return !type.isPrimitive();
        if(type.isPrimitive()) { if(type==boolean.class)type=Boolean.class;else if(type==int.class)type=Integer.class;else if(type==double.class)type=Double.class;else if(type==float.class)type=Float.class;else if(type==long.class)type=Long.class; }
        return type.isInstance(value);
    }
    static Object call(Object target,String names,Object...args) {
        Class<?> start=target instanceof Class?(Class<?>)target:target.getClass();
        for(String name:names.split("\\|"))for(Class<?> type=start;type!=null;type=type.getSuperclass())for(Method method:type.getDeclaredMethods()) {
            if(!method.getName().equals(name)||method.getParameterTypes().length!=args.length)continue;
            boolean valid=true;Class<?>[] parameters=method.getParameterTypes();for(int i=0;i<args.length;i++)if(!accepts(parameters[i],args[i]))valid=false;
            if(!valid)continue;
            try { method.setAccessible(true);return method.invoke(target instanceof Class?null:target,args); }
            catch(InvocationTargetException error) { throw new IllegalStateException("Native operation rejected",error.getCause()); }
            catch(ReflectiveOperationException error) { throw new IllegalStateException("Native method unavailable",error); }
        }
        throw new IllegalStateException("Native method missing: "+names);
    }
    static Object field(Object target,String names) {
        for(String name:names.split("\\|"))for(Class<?> type=target.getClass();type!=null;type=type.getSuperclass())try { Field field=type.getDeclaredField(name);field.setAccessible(true);return field.get(target); }catch(NoSuchFieldException ignored){}catch(ReflectiveOperationException error){throw new IllegalStateException(error);}
        throw new IllegalStateException("Native field missing: "+names);
    }
    static void set(Object target,String names,Object value) {
        for(String name:names.split("\\|"))for(Class<?> type=target.getClass();type!=null;type=type.getSuperclass())try { Field field=type.getDeclaredField(name);field.setAccessible(true);field.set(target,value);return; }catch(NoSuchFieldException ignored){}catch(ReflectiveOperationException error){throw new IllegalStateException(error);}
        throw new IllegalStateException("Native field missing: "+names);
    }
    static Object byType(Object target,String className) {
        Class<?> wanted=type(className);
        for(Class<?> type=target.getClass();type!=null;type=type.getSuperclass())for(Field field:type.getDeclaredFields())if(wanted.isAssignableFrom(field.getType()))try { field.setAccessible(true);Object found=field.get(target);if(found!=null)return found; }catch(ReflectiveOperationException error){throw new IllegalStateException(error);}
        throw new IllegalStateException("Native typed field unavailable: "+className);
    }
    static Class<?> type(String names) {
        for(String name:names.split("\\|"))try { return Class.forName(name); }catch(ClassNotFoundException ignored){}
        throw new IllegalStateException("Native class unavailable: "+names);
    }
    static Object create(String names,Object...args) {
        for(Constructor<?> constructor:type(names).getDeclaredConstructors()) {
            Class<?>[] parameters=constructor.getParameterTypes();if(parameters.length!=args.length)continue;
            boolean valid=true;for(int i=0;i<args.length;i++)if(!accepts(parameters[i],args[i]))valid=false;
            if(valid)try { constructor.setAccessible(true);return constructor.newInstance(args); }catch(ReflectiveOperationException error){throw new IllegalStateException("Native constructor rejected",error);}
        }
        throw new IllegalStateException("Native constructor missing: "+names);
    }
    static Object property(Object target,String methods,String fields) { try{return call(target,methods);}catch(IllegalStateException error){if(!error.getMessage().startsWith("Native method missing:"))throw error;return field(target,fields);} }
}
