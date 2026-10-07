package cn.starbridge.mods;
import com.google.gson.*;
/** Forge 1.7.10 ships Gson 2.2: use its public API rather than modern static parsing. */
final class Jsons {
    static final Gson GSON=new Gson();
    static JsonElement parse(String text) { return new JsonParser().parse(text); }
    static JsonObject copy(JsonObject value) { return parse(GSON.toJson(value)).getAsJsonObject(); }
}
