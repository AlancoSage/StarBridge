package cn.starbridge.velocity;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;

/** Bounded transport. Never follow redirects or include credentials in errors/logs. */
final class BridgeHttp {
    static String post(String address, String token, String body) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(address).openConnection();
        connection.setConnectTimeout(3000); connection.setReadTimeout(7000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestMethod("POST"); connection.setDoOutput(true);
        connection.setRequestProperty("Authorization", "Bearer " + token);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        try {
            try (OutputStream output = connection.getOutputStream()) {
                output.write(body.getBytes(StandardCharsets.UTF_8));
            }
            if (connection.getResponseCode() != 200) throw new IOException("bridge request rejected");
            try (InputStream input = connection.getInputStream(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(7);
                byte[] bytes = new byte[4096]; int count;
                while ((count = input.read(bytes)) != -1) {
                    if (output.size() + count > 128 * 1024 || System.nanoTime() > deadline)
                        throw new IOException("bridge response limit exceeded");
                    output.write(bytes, 0, count);
                }
                return new String(output.toByteArray(), StandardCharsets.UTF_8);
            }
        } finally { connection.disconnect(); }
    }
}
