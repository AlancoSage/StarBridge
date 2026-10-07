package cn.starbridge.mods;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

/** Java 8 bridge protocol, native job dispatch and nonce-fenced game authentication. */
public final class BridgeEngine implements AutoCloseable {
    private final GameHost host;
    private final String base,token;
    private final ScheduledExecutorService io=Executors.newSingleThreadScheduledExecutor(r->daemon(r,"StarBridge-Tick"));
    private final ThreadPoolExecutor workers=new ThreadPoolExecutor(2,2,0,TimeUnit.SECONDS,new ArrayBlockingQueue<Runnable>(64),r->daemon(r,"StarBridge-Worker"));
    private final LinkedBlockingDeque<JsonObject> events=new LinkedBlockingDeque<JsonObject>(500),results=new LinkedBlockingDeque<JsonObject>(500);
    private final Set<String> inFlight=ConcurrentHashMap.newKeySet();
    private final LinkedHashMap<String,JsonObject> completed=new LinkedHashMap<String,JsonObject>();
    private final LinkedHashMap<UUID,JsonObject> catalog=new LinkedHashMap<UUID,JsonObject>();
    private final ConcurrentMap<UUID,Login> logins=new ConcurrentHashMap<UUID,Login>();
    private Set<String> commands;
    private volatile JsonObject snapshot=new JsonObject();
    private volatile boolean running=true,known,required=true;
    private boolean passwordLogin=true,qqLogin=true;
    private String revision="";
    private int seconds=120,ticks;
    private long warning;
    private static final class Login {
        final GameHost.Player player;
        final String nonce=UUID.randomUUID().toString();
        volatile boolean authenticated;
        boolean inFlight;
        long deadline,lastCommand,lastBind;
        Login(GameHost.Player player,int seconds) { this.player=player;deadline=System.currentTimeMillis()+seconds*1000L; }
        JsonObject request(String action) {
            JsonObject value=new JsonObject();value.addProperty("action",action);value.addProperty("uuid",player.id().toString());
            value.addProperty("nonce",nonce);value.addProperty("player",player.name());value.addProperty("ip",player.ip());return value;
        }
    }
    public BridgeEngine(GameHost host,BridgeConfig config) {
        this.host=host;this.token=config.token;this.base=Protocol.base(config.endpoint,config.serverId,token);commands=config.commands;loadCatalog();
    }
    private static Thread daemon(Runnable task,String name) { Thread thread=new Thread(task,name);thread.setDaemon(true);return thread; }
    public void start() { for(GameHost.Player player:host.players()) join(player);updateSnapshot();io.scheduleWithFixedDelay(this::tick,0,1,TimeUnit.SECONDS); }
    public void callback(Runnable task) { if(running) host.execute(()->{ if(running) task.run(); }); }
    private boolean current(GameHost.Player player) { GameHost.Player actual=host.player(player.id());return actual!=null&&actual.handle()==player.handle(); }
    public boolean locked(UUID id) { if(known&&!required)return false;Login login=logins.get(id);return !known||login==null||!login.authenticated; }
    public void join(GameHost.Player player) {
        Login login=begin(player);host.protect(player,this);remember(player);event("join",player,"");
    }
    private Login begin(GameHost.Player player) {
        Login login=new Login(player,seconds);logins.put(player.id(),login);
        if(known&&!required)login.authenticated=true;
        else { player.message("星桥正在检查本次游戏登录……");submit(login,login.request("join"),true); }
        return login;
    }
    public void leave(GameHost.Player player) {
        Login login=logins.get(player.id());if(login==null||login.player.handle()!=player.handle())return;
        remember(player);event("quit",player,"");logins.remove(player.id(),login);host.unprotect(player);saveCatalog();
        if(known&&required)try { workers.execute(()->{try{post("/auth",login.request("leave"));}catch(Exception ignored){} }); } catch(RejectedExecutionException ignored){}
    }
    public void chat(GameHost.Player player,String text) { if(!locked(player.id()))event("chat",player,text); }
    public void gameTick() {
        for(Login login:logins.values())if(locked(login.player.id())&&current(login.player)) {
            if(System.currentTimeMillis()>=login.deadline)login.player.kick("登录超时，请重新进入服务器。");else login.player.freeze();
        }
        if(++ticks%20==0) { updateSnapshot();if(ticks%1200==0)saveCatalog(); }
    }
    public static boolean authCommand(String command) { return Protocol.loginCommand(command); }
    public void command(GameHost.Player player,String raw) {
        if(!current(player))return;
        int split=raw.indexOf(' ');String root=split<0?raw:raw.substring(0,split),argument=split<0?"":raw.substring(split+1);
        if(!known) { player.message("正在同步认证设置，请稍后重试。");return; }
        if(root.equals("qbind")) { bind(player);return; }
        if(!required) { player.message("此服务器没有启用星桥游戏登录。");return; }
        if(root.equals("logout")) { begin(player);return; }
        if(!Protocol.loginCommand(raw))return;
        Login login=logins.get(player.id());if(login==null) { join(player);return; }
        if(login.authenticated) { player.message("你已经登录。");return; }
        long now=System.currentTimeMillis();if(now-login.lastCommand<1000)return;login.lastCommand=now;
        boolean password=!(root.endsWith("ql")||root.endsWith("qqlogin"));
        if(password?!passwordLogin:!qqLogin) { player.message("此登录方式没有开放。");return; }
        if(password&&(argument.length()<8||argument.length()>128)) { player.message("格式：/login <注册密码> 或 /l <密码>；QQ 确认使用 /ql。");return; }
        JsonObject request=login.request(password?"password":"qq");if(password)request.addProperty("password",argument);submit(login,request,false);
    }
    private void submit(Login login,JsonObject request,boolean joining) {
        if(login.inFlight) { request.remove("password");login.player.message("认证请求正在处理中，请稍候。");return; }
        login.inFlight=true;
        try { workers.execute(()->{
            JsonObject result;
            try { result=post("/auth",request); }
            catch(Exception error) { result=new JsonObject();result.addProperty("error","认证连接暂不可用，请稍后重试。"); }
            finally { request.remove("password"); }
            final JsonObject answer=result;
            callback(()->{
                if(logins.get(login.player.id())!=login||!current(login.player))return;login.inFlight=false;
                if(answer.has("error")) { login.player.message(answer.get("error").getAsString());if(joining)login.player.kick("认证服务不可用，请稍后重新进入服务器。"); }
                else apply(login,answer,joining,true);
            });
        }); } catch(RejectedExecutionException error) { request.remove("password");login.inFlight=false;login.player.message("认证请求繁忙，请稍后重试。");if(joining)login.player.kick("认证请求繁忙，请重新进入服务器。"); }
    }
    private void accept(JsonObject response) {
        if(!response.has("authentication"))return;
        JsonObject policy=response.getAsJsonObject("authentication");boolean oldKnown=known,oldRequired=required;String oldRevision=revision;
        required=policy.get("required").getAsBoolean();passwordLogin=policy.get("password_login").getAsBoolean();qqLogin=policy.get("qq_login").getAsBoolean();
        seconds=Math.max(30,Math.min(600,policy.get("login_seconds").getAsInt()));revision=policy.get("revision").getAsString();known=true;
        String engine=Protocol.text(policy,"login_engine","auto");
        if(required&&(!policy.get("available").getAsBoolean()||!(engine.equals("auto")||engine.equals("builtin")))) {
            known=false;for(Login login:logins.values())login.player.kick("模组游戏端请使用星桥内置或自动登录引擎。");return;
        }
        if(!required) { for(Login login:logins.values())login.authenticated=true;return; }
        if(oldKnown&&(!oldRequired||!oldRevision.equals(revision)))for(GameHost.Player player:host.players())begin(player);
        if(response.has("authentication_results"))for(JsonElement item:response.getAsJsonArray("authentication_results")) {
            JsonObject value=item.getAsJsonObject();Login login=logins.get(UUID.fromString(value.get("uuid").getAsString()));
            if(login==null||!login.nonce.equals(Protocol.text(value,"nonce","")))continue;
            if("missing".equals(Protocol.text(value,"status",""))) { if(!login.inFlight&&current(login.player))begin(login.player); }
            else apply(login,value,false,false);
        }
    }
    private void apply(Login login,JsonObject value,boolean joining,boolean notify) {
        if(logins.get(login.player.id())!=login||!current(login.player)||!login.nonce.equals(Protocol.text(value,"nonce",""))||!known||!revision.equals(Protocol.text(value,"revision","")))return;
        String status=Protocol.text(value,"status","");
        if(status.equals("authenticated")) { if(!login.authenticated) { login.authenticated=true;login.player.message("登录成功，欢迎回来！"); } }
        else if(status.equals("disabled")) { if(!required)login.authenticated=true; }
        else if(status.equals("denied")) { login.authenticated=false;login.player.kick(Protocol.text(value,"message","登录被拒绝")); }
        else if(status.equals("pending")) {
            if(joining) { login.deadline=System.currentTimeMillis()+Math.max(0,Math.min(600,value.get("expires_in").getAsInt()))*1000L;login.player.message(prompt()); }
            else if(notify)login.player.message(Protocol.text(value,"message",prompt()));
        }
    }
    private String prompt() { return "请登录："+(passwordLogin?"/login <注册密码> 或 /l <密码>；":"")+(qqLogin?"/qqlogin 或 /ql，绑定 QQ 私聊确认。":""); }
    private JsonArray authSnapshot() { JsonArray values=new JsonArray();for(Login login:logins.values()) { values.add(login.request("heartbeat"));if(values.size()>=500)break; }return values; }
    private void bind(GameHost.Player player) {
        if(locked(player.id())) { player.message("请先完成游戏登录。");return; }
        Login login=logins.get(player.id());if(login==null)return;
        long now=System.currentTimeMillis();if(now-login.lastBind<20000) { player.message("请等待 20 秒再获取绑定码。");return; }login.lastBind=now;
        player.message("正在获取绑定验证码……");JsonObject request=login.request("bind");request.remove("action");
        try { workers.execute(()->{
            String message;
            try { message="请在服务器 QQ 群发送：绑定 "+post("/bind-code",request).get("code").getAsString()+"（5 分钟有效，请勿转发）"; }
            catch(Exception error) { message="获取验证码失败，请联系管理员检查星桥连接。"; }
            final String answer=message;callback(()->{if(logins.get(player.id())==login&&current(player)&&!locked(player.id()))player.message(answer);});
        }); } catch(RejectedExecutionException error) { player.message("请求繁忙，请稍后重试。"); }
    }
    private JsonObject post(String route,JsonObject payload) throws Exception {
        BridgeHttp.Response response=BridgeHttp.request(base+route,token,Jsons.GSON.toJson(payload),route.equals("/auth")?16000:6000);
        if(response.status==200)return Jsons.parse(response.body).getAsJsonObject();
        if(route.equals("/auth")) { JsonObject error=Jsons.parse(response.body).getAsJsonObject();if(error.has("error"))return error; }
        throw new IllegalStateException("HTTP "+response.status);
    }
    private static void enqueue(LinkedBlockingDeque<JsonObject> queue,JsonObject value) { if(!queue.offerLast(value)) { queue.pollFirst();queue.offerLast(value); } }
    private void tick() {
        if(!running)return;
        try {
            events.removeIf(item->System.currentTimeMillis()-item.get("queued_at").getAsLong()>30000);
            List<JsonObject> sentEvents=new ArrayList<JsonObject>(),sentResults=new ArrayList<JsonObject>();
            for(JsonObject event:events) { sentEvents.add(event);if(sentEvents.size()>=50)break; }
            for(JsonObject result:results) { sentResults.add(result);if(sentResults.size()>=50)break; }
            JsonObject payload=Jsons.copy(snapshot);payload.add("events",Jsons.GSON.toJsonTree(sentEvents));payload.add("results",Jsons.GSON.toJsonTree(sentResults));
            JsonObject response=post("/tick",payload);events.removeAll(sentEvents);results.removeAll(sentResults);
            callback(()->{
                accept(response);
                if(response.has("allowed_commands")) { Set<String> next=new HashSet<String>();for(JsonElement value:response.getAsJsonArray("allowed_commands"))next.add(value.getAsString());commands=next; }
                if(response.has("jobs"))for(JsonElement value:response.getAsJsonArray("jobs")) {
                    JsonObject job=value.getAsJsonObject();String id=job.get("id").getAsString();if(inFlight.add(id))run(job);
                }
            });
        } catch(Exception error) { if(System.currentTimeMillis()-warning>30000) { host.log("星桥桥接暂不可用；错误类型："+error.getClass().getSimpleName(),null);warning=System.currentTimeMillis(); } }
    }
    private void event(String kind,GameHost.Player player,String text) {
        JsonObject event=new JsonObject();event.addProperty("id",UUID.randomUUID().toString());event.addProperty("kind",kind);event.addProperty("player",player.name());event.addProperty("text",Protocol.clip(text,500));event.addProperty("queued_at",System.currentTimeMillis());
        if(kind.equals("join")) { event.addProperty("uuid",player.id().toString());event.addProperty("ip",player.ip()); }enqueue(events,event);
    }
    private void remember(GameHost.Player player) {
        JsonObject value=new JsonObject();value.addProperty("uuid",player.id().toString());value.addProperty("name",player.name());value.addProperty("ip",player.ip());value.addProperty("last_played",System.currentTimeMillis());
        catalog.remove(player.id());catalog.put(player.id(),value);while(catalog.size()>10000)catalog.remove(catalog.keySet().iterator().next());
    }
    private void loadCatalog() {
        try {
            Path file=host.catalogFile();if(!Files.exists(file))return;if(Files.size(file)>8*1024*1024)throw new IllegalArgumentException();
            for(JsonElement item:Jsons.parse(new String(Files.readAllBytes(file),StandardCharsets.UTF_8)).getAsJsonArray()) {
                if(catalog.size()>=10000)break;JsonObject value=item.getAsJsonObject();Protocol.player(value.get("name").getAsString());catalog.put(UUID.fromString(value.get("uuid").getAsString()),value);
            }
        } catch(Exception error) { host.log("星桥玩家档案读取失败；错误类型："+error.getClass().getSimpleName(),null); }
    }
    private void saveCatalog() {
        final byte[] data=Jsons.GSON.toJson(catalog.values()).getBytes(StandardCharsets.UTF_8);
        try { io.execute(()->{
            try { Path file=host.catalogFile(),temp=file.resolveSibling("starbridge-players.json.tmp");Files.write(temp,data);
                try { Files.move(temp,file,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING); }
                catch(AtomicMoveNotSupportedException ignored) { Files.move(temp,file,StandardCopyOption.REPLACE_EXISTING); }
            } catch(Exception error) { host.log("星桥玩家档案保存失败",null); }
        }); } catch(RejectedExecutionException ignored){}
    }
    private void updateSnapshot() {
        Map<UUID,GameHost.Player> online=new LinkedHashMap<UUID,GameHost.Player>();JsonArray names=new JsonArray();
        for(GameHost.Player player:host.players()) { remember(player);online.put(player.id(),player);names.add(new JsonPrimitive(player.name())); }
        List<UUID> ids=new ArrayList<UUID>(online.keySet()),recent=new ArrayList<UUID>(catalog.keySet());Collections.reverse(recent);for(UUID id:recent)if(!online.containsKey(id))ids.add(id);
        JsonArray records=new JsonArray();
        for(UUID id:ids.subList(0,Math.min(500,ids.size()))) {
            JsonObject value=Jsons.copy(catalog.get(id));String name=value.get("name").getAsString();
            for(Map.Entry<String,JsonElement> flag:host.flags(id,name).entrySet())value.add(flag.getKey(),flag.getValue());
            GameHost.Player player=online.get(id);value.addProperty("online",player!=null);if(player!=null)for(Map.Entry<String,JsonElement> detail:player.details().entrySet())value.add(detail.getKey(),detail.getValue());records.add(value);
        }
        JsonObject value=host.status();value.add("players",names);value.add("player_records",records);value.addProperty("players_truncated",ids.size()>500);value.addProperty("java_version",System.getProperty("java.version"));
        value.add("capabilities",Jsons.GSON.toJsonTree(Arrays.asList("player_management","game_authentication","whitelist_application","managed_sanctions")));
        value.add("auth_sessions",authSnapshot());snapshot=value;
    }
    private void finish(String id,boolean ok,String detail) { JsonObject result=Protocol.result(id,ok,detail);completed.put(id,result);if(completed.size()>2000)completed.remove(completed.keySet().iterator().next());enqueue(results,result);inFlight.remove(id); }
    private void run(JsonObject job) {
        String id=job.get("id").getAsString();
        try {
            if(completed.containsKey(id)) { enqueue(results,completed.get(id));inFlight.remove(id);return; }
            if(Protocol.expired(job)) { finish(id,false,"任务已过期，未执行");return; }
            String kind=job.get("kind").getAsString();
            if(kind.equals("broadcast")) { host.broadcast(Protocol.clip(job.get("text").getAsString(),600));finish(id,true,"消息已同步"); }
            else if(kind.equals("command")) {
                String command=job.get("command").getAsString();if(!commands.contains(command)||command.contains("\n")||command.contains("\r")) { finish(id,false,"命令不在完整命令白名单中");return; }
                finish(id,true,host.command(command));
            } else if(kind.equals("player_action")) {
                UUID uuid=UUID.fromString(job.get("uuid").getAsString());String name=job.get("player").getAsString();Protocol.player(name);
                JsonObject record=catalog.get(uuid);if(record==null||!name.equals(record.get("name").getAsString()))throw new IllegalArgumentException("Player changed");
                host.manage(uuid,name,job.get("action").getAsString(),Protocol.reason(job),Protocol.text(job,"expected_ban_reason",null),Protocol.clip(Protocol.text(job,"kick_reason",Protocol.reason(job)),340));
                finish(id,true,name+" 操作已完成");updateSnapshot();
            } else if(kind.equals("whitelist_application"))whitelist(job);
            else finish(id,false,"未知任务类型");
        } catch(Exception error) { finish(id,false,"游戏端执行失败："+error.getClass().getSimpleName()); }
    }
    private void whitelist(JsonObject job) {
        final String id=job.get("id").getAsString(),name=job.get("player").getAsString();Protocol.player(name);
        String supplied=Protocol.text(job,"uuid","");final UUID expected=supplied.trim().isEmpty()?null:UUID.fromString(supplied);
        if(!host.onlineMode()) { completeWhitelist(job,expected==null?Protocol.offlineId(name):expected,name);return; }
        try { workers.execute(()->{
            UUID uuid;String canonical;
            try {
                BridgeHttp.Response response=BridgeHttp.request("https://api.mojang.com/users/profiles/minecraft/"+name,null,null,5000);if(response.status!=200)throw new IllegalStateException();
                JsonObject value=Jsons.parse(response.body).getAsJsonObject();String raw=value.get("id").getAsString();if(!raw.matches("[0-9a-fA-F]{32}"))throw new IllegalArgumentException();
                uuid=UUID.fromString(raw.replaceFirst("(.{8})(.{4})(.{4})(.{4})(.{12})","$1-$2-$3-$4-$5"));canonical=value.get("name").getAsString();Protocol.player(canonical);
                if(!canonical.equalsIgnoreCase(name)||expected!=null&&!expected.equals(uuid))throw new IllegalArgumentException();
            } catch(Exception error) { callback(()->finish(id,false,"正版身份查询失败、超时或 UUID 不匹配"));return; }
            final UUID answer=uuid;final String actual=canonical;callback(()->completeWhitelist(job,answer,actual));
        }); } catch(RejectedExecutionException error) { finish(id,false,"身份查询繁忙，请稍后重试"); }
    }
    private void completeWhitelist(JsonObject job,UUID uuid,String name) {
        String id=job.get("id").getAsString();
        try {
            if(Protocol.expired(job)) { finish(id,false,"任务已过期");return; }
            if(host.flags(uuid,name).get("banned").getAsBoolean()) { finish(id,false,"玩家已被封禁，未加入白名单");return; }
            host.whitelist(uuid,name);JsonObject record=new JsonObject();record.addProperty("uuid",uuid.toString());record.addProperty("name",name);record.addProperty("last_played",0L);record.addProperty("ip","");catalog.putIfAbsent(uuid,record);
            finish(id,true,name+" 已加入白名单（"+uuid+"）");updateSnapshot();saveCatalog();
        } catch(Exception error) { finish(id,false,"白名单保存失败"); }
    }
    @Override public void close() {
        for(Login login:logins.values()) { if(!known||required)login.player.kick("游戏认证已停止，请稍后重新连接。");host.unprotect(login.player); }
        logins.clear();saveCatalog();running=false;workers.shutdownNow();io.shutdown();
        try { if(!io.awaitTermination(7,TimeUnit.SECONDS))io.shutdownNow(); } catch(InterruptedException error) { io.shutdownNow();Thread.currentThread().interrupt(); }
    }
}
