package cn.starbridge.forge;

import com.google.gson.JsonObject;
import net.minecraft.network.protocol.game.*;
import net.minecraft.network.protocol.common.*;
import net.minecraft.commands.arguments.ArgumentSignatures;
import net.minecraft.network.chat.LastSeenMessages;
import java.time.Instant;
import java.util.BitSet;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ProtocolTest {
    @Test void endpointRejectsCredentialRedirectionAndMalformedIdentity() {
        String token = "12345678901234567890123456789012";
        assertEquals("https://bot.example/bridge/survival", Protocol.base("https://bot.example/", "survival", token));
        for (String url : new String[]{"file:///tmp/x", "https://name:secret@bot.example", "https://bot.example?token=x", "https://bot.example#x"})
            assertThrows(IllegalArgumentException.class, () -> Protocol.base(url, "survival", token));
        assertThrows(IllegalArgumentException.class, () -> Protocol.base("https://bot.example", "../x", token));
        assertThrows(IllegalArgumentException.class, () -> Protocol.base("https://bot.example", "survival", "CHANGE-ME-12345678901234567890"));
        assertThrows(IllegalArgumentException.class, () -> Protocol.base("https://bot.example", "survival", token + "\r\n"));
    }
    @Test void onlyExactLoginCommandRootsMayPassBeforeLogin() {
        for (String value : new String[]{"login secret password", "l password", "ql", "qqlogin", "starbridge:login secret", "starbridge:ql"})
            assertTrue(Protocol.loginCommand(value), value);
        for (String value : new String[]{"loginExtra x", "/login x", "minecraft:login x", "other:ql", "op user", "qbind", "logout", " LOGIN x"})
            assertFalse(Protocol.loginCommand(value), value);
    }
    @Test void gateKeepsConnectionAliveButBlocksInventoryAndMovement() {
        assertTrue(GameLogin.hygiene(new ServerboundKeepAlivePacket(1)));
        assertTrue(GameLogin.hygiene(new ServerboundPongPacket(1)));
        assertTrue(GameLogin.hygiene(new ServerboundAcceptTeleportationPacket(1)));
        assertFalse(GameLogin.hygiene(new ServerboundMovePlayerPacket.Pos(1, 2, 3, true)));
        assertFalse(GameLogin.hygiene(new ServerboundContainerClosePacket(0)));
        assertFalse(GameLogin.hygiene(new Object()));
    }
    @Test void identityAndReasonCannotInjectCommandsOrControlCharacters() {
        assertEquals("b50ad385-829d-3141-a216-7e7d7539ba7f", Protocol.offlineId("Notch").toString());
        assertThrows(IllegalArgumentException.class, () -> Protocol.player("Steve;op"));
        JsonObject value = new JsonObject(); value.addProperty("reason", "test\nban @a");
        assertThrows(IllegalArgumentException.class, () -> Protocol.reason(value));
    }
    @Test void configurationNegotiationIsAllowedButPlayPayloadsRemainBlocked() {
        var payload = new ServerboundCustomPayloadPacket(new net.minecraft.network.protocol.common.custom.DiscardedPayload(net.minecraft.resources.ResourceLocation.parse("neoforge:negotiation")));
        assertFalse(GameLogin.beforeJoinBlocked(payload, false));
        assertTrue(GameLogin.beforeJoinBlocked(payload, true));
        assertTrue(GameLogin.beforeJoinBlocked(new ServerboundMovePlayerPacket.Pos(1, 2, 3, true), false));
        assertFalse(GameLogin.beforeJoinBlocked(new ServerboundKeepAlivePacket(1), true));
    }
    @Test void authenticationScrubbingPreservesVanillaChatAcknowledgements() {
        Instant timestamp = Instant.now(); BitSet seen = new BitSet(); seen.set(3);
        LastSeenMessages.Update update = new LastSeenMessages.Update(2, seen);
        var original = new ServerboundChatCommandSignedPacket("l private password", timestamp, 99L, ArgumentSignatures.EMPTY, update);
        var safe = GameLogin.scrub(original);
        assertEquals("starbridge:session", safe.command());
        assertSame(update, safe.lastSeenMessages()); assertEquals(timestamp, safe.timeStamp()); assertEquals(99L, safe.salt());
        assertFalse(safe.toString().contains("private password"));
        assertTrue(GameLogin.hygiene(new ServerboundChatSessionUpdatePacket((net.minecraft.network.chat.RemoteChatSession.Data) null)));
        assertTrue(GameLogin.hygiene(new ServerboundChatPacket("blocked text", timestamp, 0L, null, update)));
    }
}
