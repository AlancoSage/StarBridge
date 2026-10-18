package cn.starbridge;

import java.io.IOException;
import java.util.*;
import org.bukkit.Bukkit;
import org.bukkit.plugin.Plugin;

/** Chooses exactly one recognized authentication owner; configuration errors never fall back. */
final class LoginLinks {
    private static final String[] IDS = {"authme", "nlogin", "loginsecurity", "librelogin"};
    private static final String[] NAMES = {"AuthMe", "nLogin", "LoginSecurity", "LibreLogin"};
    private final Plugin owner;
    private LoginLink cached;
    private Plugin cachedPlugin;
    private String warning = "";

    LoginLinks(Plugin owner) { this.owner = owner; }

    private static Map<String, Plugin> enabled() {
        Map<String, Plugin> found = new LinkedHashMap<>();
        for (int index = 0; index < IDS.length; index++) {
            Plugin plugin = Bukkit.getPluginManager().getPlugin(NAMES[index]);
            if (plugin != null && plugin.isEnabled()) found.put(IDS[index], plugin);
        }
        return found;
    }

    static boolean hasExternal() { return !enabled().isEmpty(); }

    void close() {
        if (cached != null) cached.close();
        cached = null; cachedPlugin = null;
    }

    private IllegalStateException reject(String message) {
        close();
        if (!warning.equals(message)) owner.getLogger().severe(message);
        warning = message;
        return new IllegalStateException(message);
    }

    LoginLink select(String engine) {
        boolean explicit = Arrays.asList(IDS).contains(engine);
        if (!"auto".equals(engine) && !"builtin".equals(engine) && !explicit)
            throw reject("未知游戏登录引擎，VexBot未放行游戏登录。请检查认证设置。");
        Map<String, Plugin> found = enabled();
        if (found.size() > 1)
            throw reject("检测到多个已启用的登录插件，VexBot未放行游戏登录。请只保留一个登录插件并完整重启游戏服。");
        if (BridgeScheduler.isFolia() && !found.isEmpty())
            throw reject("Folia 游戏登录仅支持VexBot内置引擎，请移除第三方登录插件并完整重启；不能安全调用未经区域线程验证的登录 API。");
        if ("builtin".equals(engine) && !found.isEmpty())
            throw reject("VexBot内置引擎与已启用的登录插件冲突。请选择自动或匹配的兼容引擎并完整重启游戏服。");
        if (explicit && !found.containsKey(engine))
            throw reject("所选游戏登录插件未启用或与已安装插件不匹配，VexBot未放行游戏登录。");
        if (found.isEmpty()) {
            close(); warning = "";
            return null;
        }
        String selected = explicit ? engine : found.keySet().iterator().next();
        Plugin installed = found.get(selected);
        if (cached != null && cachedPlugin == installed && cached.id().equals(selected)) return cached;
        close();
        try {
            if ("authme".equals(selected)) cached = new AuthMeLink(installed, owner);
            else if ("nlogin".equals(selected)) cached = new NLoginLink(installed, owner);
            else if ("loginsecurity".equals(selected)) cached = new LoginSecurityLink(installed, owner);
            else cached = new LibreLoginLink(installed, owner);
            cachedPlugin = installed; warning = "";
            return cached;
        } catch (ReflectiveOperationException | IOException | RuntimeException | LinkageError error) {
            throw reject("" + installed.getName() + " 公开登录 API 无法接入，VexBot未放行游戏登录。请检查插件版本与启动日志。");
        }
    }
}
