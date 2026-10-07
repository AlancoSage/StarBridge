package cn.starbridge.forge;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class BridgeHttpTest {
    @Test void bearerNeverFollowsRedirectAndResponsesAreBounded() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicBoolean reached = new AtomicBoolean();
        server.createContext("/redirect", exchange -> {
            exchange.getResponseHeaders().add("Location", "/secret"); exchange.sendResponseHeaders(302, -1); exchange.close();
        });
        server.createContext("/secret", exchange -> { reached.set(true); exchange.sendResponseHeaders(200, -1); exchange.close(); });
        server.createContext("/large", exchange -> {
            byte[] data = new byte[1024 * 1024 + 1]; exchange.sendResponseHeaders(200, data.length);
            try (var output = exchange.getResponseBody()) { output.write(data); }
        });
        server.start();
        try {
            String base = "http://127.0.0.1:" + server.getAddress().getPort();
            assertEquals(302, BridgeHttp.request(base + "/redirect", "private-token", "{}", 3000).status);
            assertFalse(reached.get());
            assertThrows(IOException.class, () -> BridgeHttp.request(base + "/large", "private-token", "{}", 3000));
        } finally { server.stop(0); }
    }
}
