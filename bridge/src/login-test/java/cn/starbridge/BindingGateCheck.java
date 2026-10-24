package cn.starbridge;

import com.google.gson.JsonObject;
import org.bukkit.Bukkit;
import org.bukkit.Server;
import org.bukkit.event.player.AsyncPlayerPreLoginEvent;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.PluginManager;

import java.io.IOException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.net.InetAddress;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Logger;

/** Exercises admission against the real Bukkit event API without starting a game server. */
public final class BindingGateCheck {
    private static final UUID ID = UUID.fromString("069a79f4-44e9-4726-a5be-fca90e38aaf5");
    private static final Logger LOG = Logger.getLogger("VexBot-binding-gate-test");
    private static final class Transport implements BindingGate.Transport {
        volatile JsonObject response;
        volatile boolean unavailable;
        volatile CountDownLatch started, release;
        volatile JsonObject request;
        volatile String thread;
        final AtomicInteger calls = new AtomicInteger();
        public JsonObject post(String route, JsonObject data) throws Exception {
            assert route.equals("/binding-check");
            calls.incrementAndGet(); request = data; thread = Thread.currentThread().getName();
            JsonObject answer = response;
            if (started != null) started.countDown();
            if (release != null) release.await(7, TimeUnit.SECONDS);
            if (unavailable) throw new IOException("isolated unavailable backend");
            return answer;
        }
    }
    @SuppressWarnings("unchecked")
    private static <T> T proxy(Class<T> type, java.lang.reflect.InvocationHandler handler) {
        return (T) Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, handler);
    }
    private static Object fallback(Method method) {
        if (method.getReturnType() == boolean.class) return false;
        if (method.getReturnType() == int.class) return 0;
        return null;
    }
    private static Plugin plugin(Path directory) {
        return proxy(Plugin.class, (self, method, values) -> {
            String name = method.getName();
            if (name.equals("getDataFolder")) return directory.toFile();
            if (name.equals("getLogger")) return LOG;
            if (name.equals("getServer")) return Bukkit.getServer();
            if (name.equals("isEnabled")) return true;
            if (name.equals("getName")) return "VexBot-test";
            return fallback(method);
        });
    }
    private static JsonObject answer(boolean required, boolean available, boolean allowed, String revision) {
        JsonObject result = new JsonObject();
        result.addProperty("required", required); result.addProperty("available", available);
        result.addProperty("allowed", allowed); result.addProperty("revision", revision);
        result.addProperty("message", "请先绑定 QQ"); return result;
    }
    private static void accept(BindingGate gate, JsonObject answer) {
        JsonObject tick = new JsonObject(); tick.add("binding_policy", answer); gate.accept(tick);
    }
    private static AsyncPlayerPreLoginEvent event(String name, UUID identity) throws Exception {
        return new AsyncPlayerPreLoginEvent(name, InetAddress.getLoopbackAddress(), identity);
    }
    public static void main(String[] args) throws Exception {
        PluginManager manager = proxy(PluginManager.class, (self, method, values) -> fallback(method));
        Server server = proxy(Server.class, (self, method, values) -> {
            String name = method.getName();
            if (name.equals("getPluginManager")) return manager;
            if (name.equals("getLogger")) return LOG;
            if (name.equals("getName") || name.equals("getVersion") || name.equals("getBukkitVersion"))
                return "isolated binding admission check";
            return fallback(method);
        });
        Bukkit.setServer(server);
        assert BindingGate.supported();
        Path directory = Files.createTempDirectory("vexbot-binding-admission-");
        Transport transport = new Transport(); transport.unavailable = true;
        BindingGate gate = new BindingGate(plugin(directory), transport);
        try {
            assert gate.check(ID, "Notch", true) != null : "Unknown policy must reject offline admission";
            gate.accept(new JsonObject());
            assert gate.check(ID, "Notch", true) == null : "A successful old-backend tick remains compatible";

            accept(gate, answer(true, true, false, "enabled"));
            gate.accept(new JsonObject());
            assert gate.check(ID, "Notch", true) != null : "Missing policy cannot downgrade a gate already enabled";
            assert Files.exists(directory.resolve("binding-gate-policy.seen"));

            transport.unavailable = false; transport.response = answer(true, true, true, "enabled");
            assert gate.check(ID, "Notch", true) == null;
            assert ID.toString().equals(transport.request.get("uuid").getAsString());
            assert "Notch".equals(transport.request.get("player").getAsString());
            assert transport.request.size() == 2 : "Admission must not invent login proof or binding codes";
            assert transport.thread.startsWith("VexBot-BindingGate");
            int beforeUnbind = transport.calls.get();
            transport.response = answer(true, true, false, "enabled");
            String denied = gate.check(ID, "Notch", true);
            assert denied.contains(ID.toString()) && denied.contains("联系管理员核实");
            assert transport.calls.get() == beforeUnbind + 1 : "No player approval may be cached across reconnects";

            int beforeInvalid = transport.calls.get();
            assert gate.check(null, "Notch", true) != null;
            assert gate.check(ID, "bad name", true) != null;
            assert gate.check(ID, "Notch", false) != null : "Never block a main-thread admission";
            assert transport.calls.get() == beforeInvalid;
            AsyncPlayerPreLoginEvent banned = event("Notch", ID);
            banned.disallow(AsyncPlayerPreLoginEvent.Result.KICK_BANNED, "original ban"); gate.onPreLogin(banned);
            assert banned.getLoginResult() == AsyncPlayerPreLoginEvent.Result.KICK_BANNED;
            assert banned.getKickMessage().equals("original ban");
            assert transport.calls.get() == beforeInvalid;

            AsyncPlayerPreLoginEvent unbound = event("Notch", ID); gate.onPreLogin(unbound);
            assert unbound.getLoginResult() == AsyncPlayerPreLoginEvent.Result.KICK_OTHER;
            transport.response = answer(true, true, true, "enabled");
            AsyncPlayerPreLoginEvent bound = event("Notch", ID); gate.onPreLogin(bound);
            assert bound.getLoginResult() == AsyncPlayerPreLoginEvent.Result.ALLOWED;

            for (String field : new String[]{"required", "available", "allowed", "revision", "message"}) {
                JsonObject malformed = answer(true, true, true, "enabled"); malformed.remove(field);
                transport.response = malformed;
                assert gate.check(ID, "Notch", true) != null : "Missing " + field + " must fail closed";
            }
            for (String field : new String[]{"required", "available", "allowed"}) {
                JsonObject malformed = answer(true, true, true, "enabled"); malformed.addProperty(field, "false");
                transport.response = malformed;
                assert gate.check(ID, "Notch", true) != null : "String boolean must fail closed";
                malformed.addProperty(field, 1);
                assert gate.check(ID, "Notch", true) != null : "Numeric boolean must fail closed";
            }
            transport.response = answer(true, false, true, "not-ready");
            assert gate.check(ID, "Notch", true) != null : "Unavailable required gate must reject even a claimed allow";
            transport.response = answer(false, false, true, "contradictory-disabled");
            assert gate.check(ID, "Notch", true) != null : "Unavailable response cannot grant admission even if disabled";
            StringBuilder configured = new StringBuilder();
            for (int index = 0; index < 299; index++) configured.appendCodePoint(0x1F31F);
            configured.append('末');
            transport.response = answer(true, true, false, "long-message");
            transport.response.addProperty("message", configured.toString());
            String fullDenial = gate.check(ID, "Notch", true);
            assert fullDenial.startsWith(configured.toString()) : "All 300 configured Unicode code points remain intact";
            assert fullDenial.contains(ID.toString());

            accept(gate, answer(false, true, true, "disabled"));
            transport.unavailable = true;
            assert gate.check(ID, "Notch", true) == null : "Known disabled policy must tolerate an outage";
            transport.unavailable = false;
            transport.response = answer(false, true, true, "disabled");
            transport.started = new CountDownLatch(1); transport.release = new CountDownLatch(1);
            CompletableFuture<String> stale = CompletableFuture.supplyAsync(() -> gate.check(ID, "Notch", true));
            assert transport.started.await(1, TimeUnit.SECONDS);
            accept(gate, answer(true, true, false, "changed-during-request"));
            transport.release.countDown();
            assert stale.get(1, TimeUnit.SECONDS) != null : "Old disabled response cannot undo a newer enabled tick";

            transport.started = new CountDownLatch(1); transport.release = new CountDownLatch(1);
            transport.response = answer(true, true, true, "changed-during-request");
            long start = System.nanoTime();
            String timeout = gate.check(ID, "Notch", true);
            long elapsed = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - start);
            assert timeout != null && elapsed >= 4000 && elapsed < 6000 : "Admission wait must be bounded: " + elapsed;
            transport.release.countDown();

            transport.started = new CountDownLatch(1); transport.release = new CountDownLatch(1);
            CompletableFuture<String> closing = CompletableFuture.supplyAsync(() -> gate.check(ID, "Notch", true));
            assert transport.started.await(1, TimeUnit.SECONDS);
            gate.close(); transport.release.countDown();
            assert closing.get(1, TimeUnit.SECONDS) != null : "A late successful response cannot outlive gate shutdown";
            assert gate.check(ID, "Notch", true) != null;
        } finally { gate.close(); }

        Transport reopenedTransport = new Transport(); reopenedTransport.unavailable = true;
        BindingGate reopened = new BindingGate(plugin(directory), reopenedTransport);
        try {
            reopened.accept(new JsonObject());
            assert reopened.check(ID, "Notch", true) != null : "Restart then old backend cannot remove prior gate protocol";
            accept(reopened, answer(false, true, true, "explicitly-disabled"));
            assert reopened.check(ID, "Notch", true) == null;
        } finally {
            reopened.close();
            Files.deleteIfExists(directory.resolve("binding-gate-policy.seen")); Files.delete(directory);
        }
        Path malformedDirectory = Files.createTempDirectory("vexbot-binding-malformed-");
        BindingGate malformedFirst = new BindingGate(plugin(malformedDirectory), reopenedTransport);
        try {
            JsonObject malformedTick = new JsonObject(); malformedTick.addProperty("binding_policy", false);
            malformedFirst.accept(malformedTick); malformedFirst.accept(new JsonObject());
            assert malformedFirst.check(ID, "Notch", true) != null : "Malformed new policy cannot downgrade to legacy disabled";
        } finally {
            malformedFirst.close();
            Files.deleteIfExists(malformedDirectory.resolve("binding-gate-policy.seen")); Files.delete(malformedDirectory);
        }
        System.out.println("Bukkit binding admission checks passed (native UUID, no cached approvals, strict JSON, outages, legacy/restart, bounded async wait, policy/shutdown races)");
    }
}
