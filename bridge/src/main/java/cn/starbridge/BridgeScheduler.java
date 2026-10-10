package cn.starbridge;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.WeakHashMap;
import java.util.function.Consumer;
import java.util.logging.Level;
import org.bukkit.Bukkit;
import org.bukkit.entity.Player;
import org.bukkit.plugin.Plugin;

/** Uses public Folia scheduler interfaces without linking old Bukkit servers to them. */
final class BridgeScheduler {
    private static final boolean FOLIA = detectFolia();
    private static final Map<Plugin, State> STATES = new WeakHashMap<>();

    private BridgeScheduler() {}

    static boolean isFolia() { return FOLIA; }

    private static boolean detectFolia() {
        try {
            Class.forName("io.papermc.paper.threadedregions.RegionizedServer", false, Bukkit.class.getClassLoader());
            return true;
        } catch (ClassNotFoundException ignored) { return false; }
        catch (LinkageError unavailableFoliaRuntime) { return true; }
    }

    private static State state(Plugin plugin) {
        synchronized (STATES) {
            State value = STATES.get(plugin);
            if (value == null) { value = new State(); STATES.put(plugin, value); }
            return value;
        }
    }

    private static Ticket register(Plugin plugin, Runnable run, Runnable retired, boolean repeating, Player legacyPlayer) {
        if (run == null) throw new IllegalArgumentException("Task is required");
        State state = state(plugin);
        synchronized (state) {
            if (state.closed || !plugin.isEnabled()) return null;
            Ticket ticket = new Ticket(state, plugin, run, retired, repeating, legacyPlayer);
            state.tasks.add(ticket);
            return ticket;
        }
    }

    static void runGlobal(Plugin plugin, Runnable run) {
        Ticket ticket = register(plugin, run, null, false, null);
        if (ticket == null) return;
        try {
            if (FOLIA) {
                Object scheduler = globalScheduler();
                Object handle = invoke(api("GlobalRegionScheduler").getMethod("run", Plugin.class, Consumer.class),
                    scheduler, plugin, (Consumer<Object>) ignored -> ticket.fire());
                if (handle == null) throw new IllegalStateException("Global scheduler rejected a task");
                ticket.attach(handle);
            } else {
                int handle = Bukkit.getScheduler().scheduleSyncDelayedTask(plugin, ticket::fire);
                if (handle < 0) throw new IllegalStateException("Bukkit scheduler rejected a task");
                ticket.attach(handle);
            }
        } catch (ReflectiveOperationException | RuntimeException | LinkageError exception) {
            ticket.finish(true);
            throw failure(exception);
        }
    }

    static void repeatGlobal(Plugin plugin, Runnable run, long delay, long period) {
        if (period < 1) throw new IllegalArgumentException("Task period must be positive");
        Ticket ticket = register(plugin, run, null, true, null);
        if (ticket == null) return;
        try {
            if (FOLIA) {
                Object scheduler = globalScheduler();
                Object handle = invoke(api("GlobalRegionScheduler").getMethod("runAtFixedRate", Plugin.class,
                    Consumer.class, long.class, long.class), scheduler, plugin,
                    (Consumer<Object>) ignored -> ticket.fire(), Math.max(1, delay), period);
                if (handle == null) throw new IllegalStateException("Global scheduler rejected a timer");
                ticket.attach(handle);
            } else {
                int handle = Bukkit.getScheduler().scheduleSyncRepeatingTask(plugin, ticket::fire, delay, period);
                if (handle < 0) throw new IllegalStateException("Bukkit scheduler rejected a timer");
                ticket.attach(handle);
            }
        } catch (ReflectiveOperationException | RuntimeException | LinkageError exception) {
            ticket.finish(true);
            throw failure(exception);
        }
    }

    /** Retired callbacks may only clean up non-entity state, including when scheduling is rejected. */
    static boolean runPlayer(Plugin plugin, Player player, Runnable run, Runnable retired) {
        if (player == null) { retire(plugin, retired); return false; }
        Ticket ticket = register(plugin, run, retired, false, FOLIA ? null : player);
        if (ticket == null) { retire(plugin, retired); return false; }
        try {
            if (FOLIA) {
                // Obtain methods from public API interfaces, never inaccessible implementation classes.
                Object scheduler = invoke(Player.class.getMethod("getScheduler"), player);
                Object handle = invoke(api("EntityScheduler").getMethod("run", Plugin.class, Consumer.class, Runnable.class),
                    scheduler, plugin, (Consumer<Object>) ignored -> ticket.fire(), (Runnable) () -> ticket.finish(true));
                if (handle == null) { ticket.finish(true); return false; }
                ticket.attach(handle);
            } else {
                int handle = Bukkit.getScheduler().scheduleSyncDelayedTask(plugin, ticket::fire);
                if (handle < 0) { ticket.finish(true); return false; }
                ticket.attach(handle);
            }
            return true;
        } catch (ReflectiveOperationException | RuntimeException | LinkageError exception) {
            ticket.finish(true);
            plugin.getLogger().log(Level.WARNING, "Could not schedule a player task", exception);
            return false;
        }
    }

    static void cancel(Plugin plugin) {
        State state = state(plugin);
        ArrayList<Ticket> tasks;
        synchronized (state) {
            state.closed = true;
            tasks = new ArrayList<>(state.tasks);
        }
        for (Ticket ticket : tasks) ticket.finish(true);
        try {
            if (FOLIA) invoke(api("GlobalRegionScheduler").getMethod("cancelTasks", Plugin.class), globalScheduler(), plugin);
            else Bukkit.getScheduler().cancelTasks(plugin);
        } catch (ReflectiveOperationException | RuntimeException | LinkageError exception) {
            plugin.getLogger().log(Level.WARNING, "Could not cancel bridge scheduler tasks", exception);
        }
    }

    private static Class<?> api(String name) throws ClassNotFoundException {
        return Class.forName("io.papermc.paper.threadedregions.scheduler." + name, false, Bukkit.class.getClassLoader());
    }

    private static Object globalScheduler() throws ReflectiveOperationException {
        return invoke(Bukkit.class.getMethod("getGlobalRegionScheduler"), null);
    }

    private static Object invoke(Method method, Object target, Object... arguments) throws ReflectiveOperationException {
        try { return method.invoke(target, arguments); }
        catch (InvocationTargetException exception) {
            Throwable cause = exception.getCause();
            if (cause instanceof RuntimeException) throw (RuntimeException) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw exception;
        }
    }

    private static IllegalStateException failure(Throwable exception) {
        return new IllegalStateException("Server scheduler API failed", exception);
    }

    private static void retire(Plugin plugin, Runnable retired) {
        if (retired == null) return;
        try { retired.run(); }
        catch (RuntimeException exception) { plugin.getLogger().log(Level.WARNING, "Player task cleanup failed", exception); }
    }

    private static void cancelHandle(Plugin plugin, Object handle) {
        if (handle == null) return;
        try {
            if (handle instanceof Integer) Bukkit.getScheduler().cancelTask((Integer) handle);
            else invoke(api("ScheduledTask").getMethod("cancel"), handle);
        } catch (ReflectiveOperationException | RuntimeException | LinkageError exception) {
            plugin.getLogger().log(Level.WARNING, "Could not cancel a bridge task", exception);
        }
    }

    private static final class State {
        final Set<Ticket> tasks = new HashSet<>();
        boolean closed;
    }

    private static final class Ticket {
        final State state;
        final Plugin plugin;
        final boolean repeating;
        Runnable run;
        Runnable retired;
        Player legacyPlayer;
        Object handle;
        boolean done;

        Ticket(State state, Plugin plugin, Runnable run, Runnable retired, boolean repeating, Player legacyPlayer) {
            this.state = state; this.plugin = plugin; this.run = run; this.retired = retired;
            this.repeating = repeating; this.legacyPlayer = legacyPlayer;
        }

        void attach(Object handle) {
            boolean cancel;
            synchronized (state) {
                cancel = done || state.closed;
                if (!cancel) this.handle = handle;
            }
            // A disable can race the scheduler call before its task handle is returned.
            if (cancel) cancelHandle(plugin, handle);
        }

        void fire() {
            Runnable callback;
            boolean rejected;
            synchronized (state) {
                if (done) return;
                rejected = state.closed || !plugin.isEnabled() || (legacyPlayer != null && !legacyPlayer.isOnline());
                callback = rejected ? null : run;
                if (!rejected && !repeating) release();
            }
            if (rejected) { finish(true); return; }
            try { callback.run(); }
            catch (RuntimeException | Error exception) { finish(true); throw exception; }
        }

        void finish(boolean notifyRetired) {
            Runnable callback;
            Object cancelled;
            synchronized (state) {
                if (done) return;
                callback = notifyRetired ? retired : null;
                cancelled = handle;
                release();
            }
            cancelHandle(plugin, cancelled);
            retire(plugin, callback);
        }

        private void release() {
            done = true;
            state.tasks.remove(this);
            // Scheduler callbacks retain only this empty ticket after retirement or completion.
            run = null; retired = null; legacyPlayer = null; handle = null;
        }
    }
}
