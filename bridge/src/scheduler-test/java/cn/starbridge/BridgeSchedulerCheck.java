package cn.starbridge;

import io.papermc.paper.threadedregions.scheduler.*;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;
import java.util.logging.Level;
import java.util.logging.Logger;
import org.bukkit.Bukkit;
import org.bukkit.entity.Player;
import org.bukkit.plugin.Plugin;
import org.bukkit.scheduler.BukkitScheduler;

/** Exercises scheduler ownership and retirement, including disable before handle publication. */
public final class BridgeSchedulerCheck {
    private static int checks;
    private static void check(boolean value, String message) {
        checks++;
        if (!value) throw new AssertionError(message);
    }
    private static final class TestPlugin implements Plugin {
        volatile boolean enabled = true;
        public boolean isEnabled() { return enabled; }
        public Logger getLogger() { return Logger.getLogger("scheduler-test"); }
    }
    // Deliberately private: reflection must target the public scheduler API interfaces.
    private static final class Task implements ScheduledTask {
        final Plugin owner;
        final Runnable callback;
        final Runnable retired;
        int cancels;
        Task(Plugin owner, Runnable callback, Runnable retired) { this.owner = owner; this.callback = callback; this.retired = retired; }
        public CancelledState cancel() { cancels++; return CancelledState.CANCELLED_BY_CALLER; }
        void fire() { callback.run(); }
        void retire() { if (retired != null) retired.run(); }
    }
    private static final class Schedulers implements GlobalRegionScheduler, EntityScheduler, BukkitScheduler {
        final List<Task> tasks = new ArrayList<>();
        boolean reject;
        boolean fail;
        Runnable beforeReturn;
        long delay, period;
        int cancelAll;
        Task latest() { return tasks.get(tasks.size() - 1); }
        private Task add(Plugin owner, Consumer<ScheduledTask> callback, Runnable retired) {
            if (fail) throw new IllegalStateException("Scheduling rejected");
            if (reject) return null;
            Task[] holder = new Task[1];
            Task result = new Task(owner, () -> callback.accept(holder[0]), retired);
            holder[0] = result;
            tasks.add(result);
            if (beforeReturn != null) { Runnable hook = beforeReturn; beforeReturn = null; hook.run(); }
            return result;
        }
        public ScheduledTask run(Plugin owner, Consumer<ScheduledTask> callback) { return add(owner, callback, null); }
        public ScheduledTask run(Plugin owner, Consumer<ScheduledTask> callback, Runnable retired) { return add(owner, callback, retired); }
        public ScheduledTask runAtFixedRate(Plugin owner, Consumer<ScheduledTask> callback, long delay, long period) {
            this.delay = delay; this.period = period; return add(owner, callback, null);
        }
        public int scheduleSyncDelayedTask(Plugin owner, Runnable callback) {
            Task task = add(owner, ignored -> callback.run(), null);
            return task == null ? -1 : tasks.indexOf(task);
        }
        public int scheduleSyncRepeatingTask(Plugin owner, Runnable callback, long delay, long period) {
            this.delay = delay; this.period = period; return scheduleSyncDelayedTask(owner, callback);
        }
        public void cancelTask(int id) { tasks.get(id).cancel(); }
        public void cancelTasks(Plugin owner) {
            cancelAll++;
            for (Task task : tasks) if (task.owner == owner) task.cancel();
        }
    }
    private static final class TestPlayer implements Player {
        final Schedulers scheduler;
        boolean online = true;
        TestPlayer(Schedulers scheduler) { this.scheduler = scheduler; }
        public boolean isOnline() {
            if (Bukkit.folia) throw new AssertionError("Player state read outside an entity task");
            return online;
        }
        public EntityScheduler getScheduler() {
            if (!Bukkit.folia) throw new AssertionError("Legacy player scheduler queried");
            return scheduler;
        }
    }
    public static void main(String[] args) throws Exception {
        Bukkit.folia = Boolean.parseBoolean(args[0]);
        check(BridgeScheduler.isFolia() == Bukkit.folia, "Folia detection mismatch");
        Logger.getLogger("scheduler-test").setLevel(Level.OFF);
        Schedulers scheduler = new Schedulers();
        Bukkit.global = scheduler; Bukkit.legacy = scheduler;
        TestPlayer player = new TestPlayer(scheduler);
        AtomicInteger runs = new AtomicInteger(), retired = new AtomicInteger();
        TestPlugin global = new TestPlugin();
        BridgeScheduler.runGlobal(global, runs::incrementAndGet);
        check(runs.get() == 0, "Global callback ran on caller thread");
        scheduler.latest().fire(); scheduler.latest().fire();
        check(runs.get() == 1, "Global callback should run once");
        BridgeScheduler.repeatGlobal(global, runs::incrementAndGet, 0, 20);
        check(scheduler.period == 20 && scheduler.delay == (Bukkit.folia ? 1 : 0), "Timer delay or period changed");
        Task timer = scheduler.latest(); timer.fire(); timer.fire();
        check(runs.get() == 3, "Repeating callback did not repeat");
        BridgeScheduler.cancel(global); timer.fire();
        check(runs.get() == 3 && timer.cancels > 0, "Cancelled global timer still ran");
        int count = scheduler.tasks.size();
        BridgeScheduler.runGlobal(global, runs::incrementAndGet);
        check(scheduler.tasks.size() == count, "Closed plugin scheduled new work");

        TestPlugin entity = new TestPlugin();
        check(BridgeScheduler.runPlayer(entity, player, runs::incrementAndGet, retired::incrementAndGet), "Player task was rejected");
        Task scheduled = scheduler.latest(); scheduled.fire(); scheduled.retire(); scheduled.fire();
        check(runs.get() == 4 && retired.get() == 0, "Run and retired callbacks both executed");
        check(BridgeScheduler.runPlayer(entity, player, runs::incrementAndGet, retired::incrementAndGet), "Pending player task was rejected");
        scheduled = scheduler.latest(); BridgeScheduler.cancel(entity); scheduled.retire(); scheduled.fire();
        check(runs.get() == 4 && retired.get() == 1 && scheduled.cancels > 0, "Disable failed to cancel pending entity task");
        TestPlugin disabled = new TestPlugin(); disabled.enabled = false;
        check(!BridgeScheduler.runPlayer(disabled, player, runs::incrementAndGet, retired::incrementAndGet), "Disabled plugin scheduled work");
        check(retired.get() == 2, "Disabled task did not clean up exactly once");
        check(!BridgeScheduler.runPlayer(new TestPlugin(), null, runs::incrementAndGet, retired::incrementAndGet), "Null player accepted");
        check(retired.get() == 3, "Null player task did not clean up");

        scheduler.reject = true;
        check(!BridgeScheduler.runPlayer(new TestPlugin(), player, runs::incrementAndGet, retired::incrementAndGet), "Retired scheduler accepted work");
        check(retired.get() == 4, "Rejected task cleanup count incorrect");
        boolean rejectedGlobal = false, rejectedTimer = false;
        try { BridgeScheduler.runGlobal(new TestPlugin(), runs::incrementAndGet); }
        catch (IllegalStateException expected) { rejectedGlobal = true; }
        try { BridgeScheduler.repeatGlobal(new TestPlugin(), runs::incrementAndGet, 1, 20); }
        catch (IllegalStateException expected) { rejectedTimer = true; }
        check(rejectedGlobal && rejectedTimer, "Invalid global scheduler handles were accepted"); scheduler.reject = false;
        scheduler.fail = true;
        check(!BridgeScheduler.runPlayer(new TestPlugin(), player, runs::incrementAndGet, retired::incrementAndGet), "Failed scheduler accepted work");
        check(retired.get() == 5, "Failed task cleanup count incorrect");
        boolean failed = false;
        try { BridgeScheduler.runGlobal(new TestPlugin(), runs::incrementAndGet); }
        catch (IllegalStateException expected) { failed = true; }
        check(failed, "Global scheduler failure must not use a fallback"); scheduler.fail = false;

        TestPlugin racing = new TestPlugin();
        scheduler.beforeReturn = () -> BridgeScheduler.cancel(racing);
        BridgeScheduler.runPlayer(racing, player, runs::incrementAndGet, retired::incrementAndGet);
        scheduled = scheduler.latest(); scheduled.fire(); scheduled.retire();
        check(scheduled.cancels > 0 && runs.get() == 4 && retired.get() == 6, "Disable race lost a returned task handle");

        // Pause scheduler API call; close from another thread; only then publish the handle.
        TestPlugin threaded = new TestPlugin(); CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        scheduler.beforeReturn = () -> {
            entered.countDown();
            try { release.await(); } catch (InterruptedException exception) { throw new AssertionError(exception); }
        };
        Thread submit = new Thread(() -> BridgeScheduler.runPlayer(threaded, player, runs::incrementAndGet, retired::incrementAndGet));
        submit.start(); entered.await(); BridgeScheduler.cancel(threaded); release.countDown(); submit.join();
        scheduled = scheduler.latest(); scheduled.fire(); scheduled.retire();
        check(scheduled.cancels > 0 && runs.get() == 4 && retired.get() == 7, "Cross-thread disable race lost cleanup");

        TestPlugin retireBeforeReturn = new TestPlugin();
        if (Bukkit.folia) {
            scheduler.beforeReturn = () -> scheduler.latest().retire();
            BridgeScheduler.runPlayer(retireBeforeReturn, player, runs::incrementAndGet, retired::incrementAndGet);
            scheduled = scheduler.latest(); scheduled.retire(); scheduled.fire();
            check(retired.get() == 8 && runs.get() == 4 && scheduled.cancels > 0, "Retirement before publication leaked a task");
        } else {
            player.online = false;
            BridgeScheduler.runPlayer(retireBeforeReturn, player, runs::incrementAndGet, retired::incrementAndGet);
            scheduler.latest().fire(); scheduler.latest().fire();
            check(retired.get() == 8 && runs.get() == 4, "Offline legacy player callback ran"); player.online = true;
        }
        TestPlugin disabledAfterSubmit = new TestPlugin();
        BridgeScheduler.runPlayer(disabledAfterSubmit, player, runs::incrementAndGet, retired::incrementAndGet);
        disabledAfterSubmit.enabled = false; scheduler.latest().fire(); scheduler.latest().retire();
        check(retired.get() == 9 && runs.get() == 4, "Disabled plugin callback ran after submission");
        System.out.println((Bukkit.folia ? "Folia" : "Bukkit") + " scheduler: " + checks + " checks passed");
    }
}
