package cn.starbridge;

import com.sun.net.httpserver.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Exercises the real transport against a local HTTP server on Java 8. */
public final class BridgeHttpCheck {
    private static void reply(HttpExchange exchange, int status, byte[] body) throws IOException {
        exchange.sendResponseHeaders(status, body.length);
        try (OutputStream output = exchange.getResponseBody()) { output.write(body); }
    }
    public static void main(String[] args) throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        ExecutorService executor = Executors.newCachedThreadPool(); server.setExecutor(executor);
        AtomicBoolean correct = new AtomicBoolean(), redirected = new AtomicBoolean();
        final String payload = "{\"message\":\"你好，星桥\"}";
        server.createContext("/post", exchange -> {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[1024]; int count;
            while ((count = exchange.getRequestBody().read(buffer)) != -1) bytes.write(buffer, 0, count);
            correct.set("POST".equals(exchange.getRequestMethod()) && "Bearer isolated-test".equals(exchange.getRequestHeaders().getFirst("Authorization"))
                && "application/json; charset=utf-8".equals(exchange.getRequestHeaders().getFirst("Content-Type"))
                && payload.equals(new String(bytes.toByteArray(), StandardCharsets.UTF_8)));
            reply(exchange, 200, payload.getBytes(StandardCharsets.UTF_8));
        });
        server.createContext("/redirect", exchange -> { exchange.getResponseHeaders().set("Location", "/destination"); reply(exchange, 302, new byte[]{1}); });
        server.createContext("/destination", exchange -> { redirected.set(true); reply(exchange, 200, new byte[]{1}); });
        server.createContext("/large", exchange -> reply(exchange, 200, new byte[1024 * 1024 + 1]));
        server.createContext("/slow", exchange -> { try { Thread.sleep(500); reply(exchange, 200, new byte[]{1}); } catch (InterruptedException ignored) {} });
        server.createContext("/error", exchange -> reply(exchange, 401, "{\"error\":\"拒绝\"}".getBytes(StandardCharsets.UTF_8)));
        server.start();
        String base = "http://127.0.0.1:" + server.getAddress().getPort();
        try {
            BridgeHttp.Response value = BridgeHttp.request(base + "/post", "isolated-test", payload, 2000);
            assert correct.get() && value.status == 200 && value.body.equals(payload);
            assert BridgeHttp.request(base + "/redirect", "isolated-test", null, 2000).status == 302;
            assert !redirected.get() : "Credentials must never follow redirects";
            value = BridgeHttp.request(base + "/error", null, payload, 2000);
            assert value.status == 401 && value.body.contains("拒绝");
            boolean rejected = false;
            try { BridgeHttp.request(base + "/large", null, null, 2000); } catch (IOException expected) { rejected = true; }
            assert rejected : "Oversized response was accepted";
            long started = System.nanoTime(); rejected = false;
            try { BridgeHttp.request(base + "/slow", null, null, 100); } catch (SocketTimeoutException expected) { rejected = true; }
            assert rejected && TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) < 2000;
            System.out.println("Java 8 HTTP checks passed: Unicode, authorization, errors, redirects, limits, timeout");
        } finally { server.stop(0); executor.shutdownNow(); }
    }
}
