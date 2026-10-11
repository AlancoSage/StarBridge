'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
  const states = {online:'在线', offline:'离线', unknown:'状态未知'};
  let base = '', info = null, accessToken = '', expires = 0, storageKey = '';
  let profileEpoch = 0, serverEpoch = 0, serverLoading = false, challenge = '', resetChallenge = '', noticeTimer = null;
  let motion = null;
  let appearanceKey = '', appearance = null;
  const palettes = {forest:{accent:'#54745d',secondary:'#b78758'},slate:{accent:'#536e8c',secondary:'#a3a889'},sand:{accent:'#916b48',secondary:'#809774'}};
  const systemTheme = matchMedia('(prefers-color-scheme: dark)');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  function applyAppearance() {
    const mode = appearance?.mode || info?.theme_mode || 'system';
    const colors = appearance?.palette ? palettes[appearance.palette] : {accent:info?.accent_color || palettes.forest.accent,secondary:info?.secondary_color || palettes.forest.secondary};
    const root = document.documentElement;
    root.dataset.theme = mode === 'system' ? systemTheme.matches ? 'dark' : 'light' : mode;
    root.style.setProperty('--accent',colors.accent); root.style.setProperty('--secondary',colors.secondary);
    // Pick the more legible button text against the configured primary color.
    const rgb = colors.accent.slice(1).match(/../g).map(v => parseInt(v,16) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
    const luminance = .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
    root.style.setProperty('--on-accent',luminance > .179 ? '#17221a' : '#ffffff');
    root.style.setProperty('--soft','color-mix(in srgb, var(--accent) 12%, var(--paper))');
    root.style.setProperty('--scene-leaf','color-mix(in srgb, var(--accent) 40%, var(--paper))');
    root.style.setProperty('--scene-ground','color-mix(in srgb, var(--accent) 18%, var(--bg))');
    root.style.setProperty('--scene-line','color-mix(in srgb, var(--accent) 30%, var(--line))');
    document.body.dataset.grid = info?.grid_background === false ? 'off' : 'on';
    document.querySelectorAll('[data-palette]').forEach(button => button.setAttribute('aria-pressed',String(appearance?.palette === button.dataset.palette)));
    document.querySelectorAll('[data-mode]').forEach(button => button.setAttribute('aria-pressed',String(mode === button.dataset.mode)));
    $('appearance-state').textContent = appearance ? '正在使用此浏览器保存的外观偏好。' : '正在使用官网默认外观。';
  }
  function saveAppearance() {
    try { if (appearance) localStorage.setItem(appearanceKey,JSON.stringify(appearance)); else localStorage.removeItem(appearanceKey); } catch { /* Appearance also works without persistent browser storage. */ }
    applyAppearance();
  }
  function message(text, kind = '', persistent = false) {
    clearTimeout(noticeTimer); $('notice').textContent = text; $('notice').className = 'notice ' + kind; $('notice').hidden = !text;
    if (text && !persistent) noticeTimer = setTimeout(() => { $('notice').hidden = true; }, 6000);
  }
  function storeSession() {
    try { if (accessToken) sessionStorage.setItem(storageKey, JSON.stringify({token:accessToken, expires})); else sessionStorage.removeItem(storageKey); } catch { /* Memory-only sessions also work. */ }
  }
  function clearSession() { accessToken = ''; expires = 0; profileEpoch++; storeSession(); $('account-link').querySelector('span').textContent = '账号'; $('profile-shell').hidden = true; $('login-shell').hidden = false; $('reset-shell').hidden = true; $('account-facts').replaceChildren(); $('own-players').replaceChildren(); $('own-services').replaceChildren(); }
  function session(result) { accessToken = result.access_token; expires = Date.now() + result.expires_in * 1000; storeSession(); $('login-password').value = ''; $('register-password').value = ''; $('register-confirm').value = ''; $('account-link').querySelector('span').textContent = '账号'; }
  async function request(path, body = null, authenticated = false) {
    if (!base) throw Error('官网还未连接到 Myrinbot，请稍后再试。');
    if (authenticated && (!accessToken || expires <= Date.now())) { clearSession(); throw Error('登录已过期，请重新登录。'); }
    const response = await fetch(base + path, {method:body === null ? 'GET' : 'POST', cache:'no-store', credentials:'omit',
      headers:{...(body !== null ? {'Content-Type':'application/json'} : {}), ...(authenticated ? {Authorization:'Bearer ' + accessToken} : {})},
      ...(body !== null ? {body:JSON.stringify(body)} : {}), signal:AbortSignal.timeout(45000)});
    let data; try { data = await response.json(); } catch { throw Error('API 响应格式错误，请检查官网 API 地址。'); }
    if (!response.ok) { if (authenticated && response.status === 401) clearSession(); const error = Error(data.error || '请求失败'); error.code = data.code; throw error; }
    return data;
  }
  async function action(form, callback) {
    if (form.dataset.busy) return; form.dataset.busy = '1';
    const inputs = [...form.querySelectorAll('input,button,textarea,select')], original = inputs.map(node => node.disabled);
    inputs.forEach(node => { node.disabled = true; });
    try { await callback(); } catch (error) { message(error.name === 'TimeoutError' ? '请求超时，请稍后重试。' : error.message, 'error'); }
    finally { inputs.forEach((node, i) => { node.disabled = original[i]; }); delete form.dataset.busy; }
  }
  function statusBadge(status) { return el('span', states[status] || '状态未知', 'badge ' + status); }
  function facts(target, values) {
    target.replaceChildren(...values.map(([name, value]) => { const item = el('div', undefined, 'fact'); item.append(el('dt', name), el('dd', value || '—')); return item; }));
  }
  const date = value => value ? new Date(value * 1000).toLocaleString('zh-CN') : '暂无记录';
  function playerCard(player) {
    const card = el('article', undefined, 'player-card'), body = el('div', undefined, 'player-body');
    card.append(el('div', player.name.slice(0,1).toUpperCase(), 'avatar'), body);
    body.append(el('h3', player.name), el('p', player.uuid, 'uuid'), statusBadge(player.status));
    body.append(el('p', player.server_name, 'muted'), el('p', '最近到访：' + date(player.last_seen), 'field-hint'));
    return card;
  }
  function applyInfo(value) {
    info = value; document.title = value.title;
    ['brand-name','footer-name','hero-title'].forEach(id => { $(id).textContent = value.title; });
    applyAppearance(); $('theme-toggle').disabled = false;
    $('site-subtitle').textContent = value.subtitle; $('site-description').textContent = value.description;
    $('site-rules').textContent = value.rules || '请联系管理员了解社区规则。';
    $('join-address').textContent = value.join_address ? '游戏地址：' + value.join_address : '请联系管理员获取游戏地址。';
    $('copy-address').hidden = !value.join_address;
    $('group-link').hidden = !value.group_url;
    if (value.group_url) { const url = new URL(value.group_url); if (['http:','https:'].includes(url.protocol)) $('group-link').href = url.href; else $('group-link').hidden = true; }
    $('explore-link').hidden = !value.public_servers;
    $('refresh-servers').hidden = $('refresh-all-servers').hidden = !value.public_servers;
    $('registration-state').textContent = value.registration_enabled ? '邮箱验证通过后即可完成注册。验证码有效期 ' + value.code_minutes + ' 分钟。' : '注册暂未开放，请联系社区管理员。';
    $('request-code').disabled = !value.registration_enabled;
    $('login-submit').disabled = !value.login_enabled;
    $('open-reset').hidden = $('change-password').hidden = !value.password_reset_enabled;
    if (!value.login_enabled) $('login-shell').querySelector('.muted').textContent = '官网登录暂未开放，请联系管理员。';
    else $('login-shell').querySelector('.muted').textContent = '用注册时的密码，查看属于你的社区档案。';
  }
  async function servers() {
    if (serverLoading) return;
    const epoch = ++serverEpoch;
    const targets = [$('server-list'),$('servers-list')];
    const unavailable = text => { targets.forEach(target => target.replaceChildren(el('p',text,'empty'))); ['servers-total','servers-connected','servers-online'].forEach(id => { $(id).textContent = '—'; }); $('servers-updated').textContent = '每 30 秒刷新，切换到后台时暂停。在线人数合计只统计已连接服务器。'; };
    if (!info?.public_servers) { unavailable('服务器信息暂未公开。'); return; }
    serverLoading = true;
    try {
      const data = await request('/servers'); if (epoch !== serverEpoch) return;
      const connected = data.servers.filter(server => server.connected);
      $('servers-total').textContent = data.servers.length;
      $('servers-connected').textContent = connected.length;
      $('servers-online').textContent = connected.length ? connected.reduce((total,server) => total + server.online_count,0) : data.servers.length ? '—' : '0';
      $('servers-updated').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN') + ' · 每 30 秒刷新，后台暂停。在线人数合计只统计已连接服务器。';
      targets.forEach(target => {
        target.replaceChildren(...data.servers.map(server => {
          const card = el('article',undefined,'server-card'), meta = el('div',undefined,'server-meta');
          card.append(el('h3',server.name),meta);
          meta.append(el('span',server.connected ? server.online_count + ' / ' + (server.max_players ?? '—') + ' 位玩家在线' : '等待游戏服务器连接','muted'),el('span',server.connected ? '已连接' : '未连接','badge ' + (server.connected ? 'online' : 'unknown')));
          return card;
        }));
        if (!data.servers.length) target.append(el('p','暂未配置服务器。','empty'));
      });
    } catch (error) { if (epoch === serverEpoch) unavailable(error.message); }
    finally { serverLoading = false; }
  }
  async function profile() {
    const epoch = ++profileEpoch;
    $('reset-shell').hidden = true;
    if (!accessToken || expires <= Date.now()) { clearSession(); return; }
    $('login-shell').hidden = true; $('profile-shell').hidden = false;
    try { const data = await request('/me/profile',null,true); if (epoch !== profileEpoch) return;
      $('profile-title').textContent = '你好，' + data.account.player;
      facts($('account-facts'), [['玩家名',data.account.player],['注册邮箱',data.account.email],['关联 QQ',data.account.qq],['注册时间',date(data.account.created)],['密码',data.account.has_password ? '已设置' : '尚未设置']]);
      $('own-players').replaceChildren(...data.game_profiles.map(player => playerCard(player)));
      if (!data.game_profiles.length) $('own-players').append(el('p','还没有关联的游戏档案。进入游戏验证登录，或绑定注册邮箱对应的 QQ 后再来看看。','empty'));
        if (data.truncated) $('own-players').append(el('p','仅展示前 100 个关联身份，请联系管理员查询完整记录。','empty'));
        const services=await request('/me/services',null,true);if(epoch!==profileEpoch)return;renderServices(services);await renderTickets(services,epoch);
    } catch (error) { message(error.message,'error'); }
  }
  function renderServices(data){
    const container=$('own-services');container.replaceChildren();
    const status={pending:'等待审核',approved:'已批准，等待下发',submitted:'游戏端处理中',success:'已加入白名单',rejected:'申请未通过',failed:'下发失败',unconfirmed:'等待确认',cancelled:'下发已撤销'};
    const names=Object.fromEntries(data.servers.map(server=>[server.id,server.name]));
    const section=(title)=>{const box=el('section',undefined,'soft-card');box.append(el('h2',title));container.append(box);return box;};
    const bindings=section('我的账号绑定');
    if(!data.bindings.length)bindings.append(el('p','还没有绑定。进入游戏输入 /qbind 获取验证码，再在这里完成绑定。','muted'));
    for(const bound of data.bindings){const row=el('div',undefined,'service-row');row.append(el('span',(names[bound.server]||bound.server)+' · '+bound.name));const remove=el('button','解除绑定','quiet small');remove.type='button';remove.onclick=async()=>{if(!confirm('解除 '+(names[bound.server]||bound.server)+' 的游戏绑定？QQ 游戏登录会话也会失效。'))return;remove.disabled=true;try{renderServices(await request('/me/unbind',{server:bound.server},true));await profile();message('已解除绑定。','success');}catch(error){message(error.message,'error');}finally{remove.disabled=false;}};row.append(remove);bindings.append(row);}
    function serverSelect(form){const label=el('label','服务器'),select=el('select');select.name='server';select.required=true;select.setAttribute('aria-label','服务器');for(const server of data.servers)select.append(new Option(server.name,server.id));form.append(label,select);return select;}
    const bind=el('form',undefined,'service-form'),server=serverSelect(bind),codeLabel=el('label','游戏绑定码'),code=el('input'),submit=el('button','验证并绑定');code.name='code';code.maxLength=8;code.pattern='[0-9A-Fa-f]{8}';code.required=true;code.autocomplete='off';code.setAttribute('aria-label','游戏绑定码');submit.disabled=!data.servers.length;bind.append(codeLabel,code,submit);bind.onsubmit=event=>{event.preventDefault();action(bind,async()=>{renderServices(await request('/me/bind',{server:server.value,code:code.value.trim()},true));await profile();message('绑定成功。','success');});};bindings.append(bind);
    const whitelist=section('我的白名单申请');
    if(data.whitelist_enabled){const form=el('form',undefined,'service-form'),select=serverSelect(form),label=el('label','申请理由（可选）'),reason=el('input'),submit=el('button','提交申请');reason.maxLength=300;reason.name='reason';reason.setAttribute('aria-label','申请理由');submit.disabled=!data.servers.length;form.append(label,reason,submit);form.onsubmit=event=>{event.preventDefault();action(form,async()=>{renderServices(await request('/me/whitelist',{server:select.value,reason:reason.value.trim()},true));message('申请已提交，可在这里查看进度。','success');});};whitelist.append(form);}else whitelist.append(el('p','白名单申请暂未开放。','muted'));
    for(const app of data.applications){const row=el('div',undefined,'service-row');row.append(el('span',(names[app.server]||app.server)+' · '+app.player),el('span',status[app.status]||app.status,'muted'));whitelist.append(row);}if(!data.applications.length)whitelist.append(el('p','暂无申请记录。','muted'));
    const penalties=section('我的处罚记录'),labels={kick:'踢出游戏',ban:'封禁',unban:'解除封禁'};
    for(const item of data.penalties){const row=el('div',undefined,'service-row');row.append(el('span',(names[item.server]||item.server)+' · '+labels[item.action]),el('span',date(item.created)+' · '+(item.reason||'未填写原因'),'muted'));penalties.append(row);}if(!data.penalties.length)penalties.append(el('p','暂无处罚记录。','muted'));
    for(const item of data.shared_penalties||[]){const row=el('div',undefined,'service-row');row.append(el('span','跨服'+labels[item.action]+' · '+item.servers.map(s=>names[s]||s).join('、')),el('span',item.reason+' · '+({active:'生效中',revoked:'已撤销',expired:'已到期',completed:'已结束'}[item.status]||item.status),'muted'));penalties.append(row);}
  }
  async function renderTickets(services,epoch,page=1){
    const data=await request('/me/tickets?page='+page,null,true);if(epoch!==profileEpoch)return;
    let box=$('own-tickets');if(!box){box=el('section',undefined,'soft-card');box.id='own-tickets';$('own-services').append(box);}box.replaceChildren(el('h2','工单与处罚申诉'),el('p','提交的问题只向你和有权限的管理员展示。','muted'));
    const labels={open:'待处理',processing:'处理中',resolved:'已解决',closed:'已关闭'};
    function input(form,title,kind='input',options=null){const l=el('label',title),i=el(kind);i.setAttribute('aria-label',title);if(options)for(const [value,name]of options)i.append(new Option(name,value));l.append(i);form.append(l);return i;}
    if(data.settings.enabled){const f=el('form',undefined,'service-form'),kind=input(f,'类型','select',[['question','玩家问题'],['appeal','处罚申诉']]),title=input(f,'标题'),body=input(f,'问题详情','textarea'),server=input(f,'服务器（可选）','select',[['','整个社区'],...services.servers.map(s=>[s.id,s.name])]),penalty=input(f,'关联处罚（申诉时可选）','select',[['','不关联'],...[...(services.shared_penalties||[]),...services.penalties].map(p=>[p.id,p.player+' · '+p.reason.slice(0,70)])]);title.required=true;title.maxLength=100;body.required=true;body.maxLength=4000;penalty.disabled=true;kind.onchange=()=>{penalty.disabled=kind.value!=='appeal';if(penalty.disabled)penalty.value='';};const b=el('button','提交工单');f.append(b);f.onsubmit=e=>{e.preventDefault();action(f,async()=>{await request('/me/tickets',{title:title.value,body:body.value,kind:kind.value,server:server.value,penalty_id:kind.value==='appeal'?penalty.value:''},true);await renderTickets(services,epoch);message('工单已提交。','success');});};box.append(f);}else box.append(el('p','暂未开放新工单，可以查看已有记录。','muted'));
    const detail=el('div',undefined,'ticket-detail');
    for(const t of data.tickets){const row=el('div',undefined,'service-row'),b=el('button','查看与回复','quiet small');row.append(el('span',t.title+' · '+labels[t.status]),b);b.onclick=async()=>{b.disabled=true;try{await show(t.id);}catch(e){message(e.message,'error');}finally{b.disabled=false;}};box.append(row);}
    if(!data.tickets.length)box.append(el('p','暂无工单。','muted'));const pager=el('div',undefined,'actions'),prev=el('button','上一页','quiet small'),next=el('button','下一页','quiet small');prev.disabled=page<=1;next.disabled=page*data.page_size>=data.total;prev.onclick=()=>action(pager,()=>renderTickets(services,epoch,page-1));next.onclick=()=>action(pager,()=>renderTickets(services,epoch,page+1));pager.append(prev,el('span',`共 ${data.total} 项 · 第 ${page} 页`,'muted'),next);box.append(pager,detail);
    async function show(id){const t=await request('/me/tickets/'+id,null,true);if(epoch!==profileEpoch)return;detail.replaceChildren(el('h3',t.title),el('p',labels[t.status],'muted'));for(const m of t.messages){const r=el('div',undefined,'ticket-message');r.append(el('strong',m.author+' · '+date(m.created)),el('p',m.body));detail.append(r);}if(!['resolved','closed'].includes(t.status)){const f=el('form',undefined,'service-form'),body=input(f,'回复','textarea'),b=el('button','发送回复');body.required=true;body.maxLength=4000;f.append(b);f.onsubmit=e=>{e.preventDefault();action(f,async()=>{await request('/me/tickets/'+id+'/reply',{body:body.value,revision:t.revision},true);await show(id);message('回复已发送。','success');});};detail.append(f);}}
  }
  function navigate() {
    if (location.hash === '#players') history.replaceState(null,'','#servers');
    const name = ['home','servers','register','account'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'home';
    document.querySelectorAll('.view').forEach(node => { node.hidden = node.id !== 'view-' + name; });
    document.querySelectorAll('nav a').forEach(link => { if (link.hash === '#' + name) link.setAttribute('aria-current','page'); else link.removeAttribute('aria-current'); });
    motion?.cancel(); if (!reducedMotion.matches && !document.hidden) motion = $('view-' + name).animate([{opacity:.65,transform:'translateY(4px)'},{opacity:1,transform:'none'}],{duration:160,easing:'ease-out'});
    if (!info) return;
    if (name === 'home' || name === 'servers') servers(); if (name === 'account') profile();
  }
  $('theme-toggle').onclick = () => { applyAppearance(); $('theme-dialog').showModal(); };
  $('theme-close').onclick = () => $('theme-dialog').close();
  document.querySelectorAll('[data-palette]').forEach(button => { button.onclick = () => { appearance = {...appearance,palette:button.dataset.palette}; saveAppearance(); }; });
  document.querySelectorAll('[data-mode]').forEach(button => { button.onclick = () => { appearance = {...appearance,mode:button.dataset.mode}; saveAppearance(); }; });
  $('theme-reset').onclick = () => { appearance = null; saveAppearance(); };
  systemTheme.addEventListener('change',applyAppearance);
  $('refresh-servers').onclick = async () => { try { applyInfo(await request('/community/info')); await servers(); } catch (error) { message(error.message,'error'); } };
  $('refresh-all-servers').onclick = $('refresh-servers').onclick;
  $('refresh-profile').onclick = profile;
  $('copy-address').onclick = async () => { try { await navigator.clipboard.writeText(info.join_address); message('游戏地址已复制。','success'); } catch { message('复制失败，请手动复制游戏地址。','error'); } };
  $('register-request').onsubmit = event => { event.preventDefault(); action(event.currentTarget,async () => {
    const data = await request('/registration/request',{player:$('register-player').value.trim(),email:$('register-email').value.trim()});
    challenge = data.challenge_id; $('register-target').textContent = '验证码已发送至 ' + data.email + '，有效期约 ' + Math.ceil(data.expires_in / 60) + ' 分钟。';
    $('register-request').hidden = true; $('register-verify').hidden = false; $('register-code').focus(); message('验证码已发送，请检查邮箱。','success');
  }); };
  $('register-verify').onsubmit = event => { event.preventDefault(); action(event.currentTarget,async () => {
    if ($('register-password').value !== $('register-confirm').value) throw Error('两次输入的密码不一致。');
    const result = await request('/registration/verify',{challenge_id:challenge,code:$('register-code').value,password:$('register-password').value});
    session(result); challenge = ''; $('register-verify').reset(); $('register-request').reset(); $('register-request').hidden = false; $('register-verify').hidden = true;
    location.hash = 'account'; message('注册成功，欢迎加入社区。','success');
  }); };
  $('resend-code').onclick = () => action($('register-verify'),async () => {
    const data = await request('/registration/resend',{challenge_id:challenge}); challenge = data.challenge_id;
    $('register-target').textContent = '验证码已重新发送至 ' + data.email + '。'; $('register-code').value = ''; message('验证码已重新发送。','success');
  });
  $('register-back').onclick = () => { challenge = ''; $('register-verify').reset(); $('register-verify').hidden = true; $('register-request').hidden = false; };
  $('login-form').onsubmit = event => { event.preventDefault(); action(event.currentTarget,async () => {
    session(await request('/account/login',{player:$('login-player').value.trim(),password:$('login-password').value})); await profile(); message('登录成功。','success');
  }); };
  $('logout').onclick = async () => { $('logout').disabled = true; try { await request('/account/logout',{},true); clearSession(); message('已退出登录。','success'); } catch (error) { message(error.message,'error'); } finally { $('logout').disabled = false; } };
  function openReset() { $('login-shell').hidden = $('profile-shell').hidden = true; $('reset-shell').hidden = false; $('reset-request').hidden = false; $('reset-verify').hidden = true; resetChallenge = ''; }
  $('open-reset').onclick = $('change-password').onclick = openReset;
  $('reset-back').onclick = profile;
  $('reset-request').onsubmit = event => { event.preventDefault(); action(event.currentTarget,async () => {
    const data = await request('/account/password/request',{player:$('reset-player').value.trim(),email:$('reset-email').value.trim()});
    resetChallenge = data.challenge_id; $('reset-request').hidden = true; $('reset-verify').hidden = false; $('reset-code').focus(); message(data.message,'success');
  }); };
  $('reset-verify').onsubmit = event => { event.preventDefault(); action(event.currentTarget,async () => {
    if ($('reset-password').value !== $('reset-confirm').value) throw Error('两次输入的密码不一致。');
    await request('/account/password/verify',{challenge_id:resetChallenge,code:$('reset-code').value,password:$('reset-password').value});
    clearSession(); $('reset-verify').reset(); $('reset-request').reset(); message('密码已更新，请使用新密码登录。','success');
  }); };
  window.addEventListener('hashchange',navigate);
  reducedMotion.addEventListener('change',() => { if (reducedMotion.matches) motion?.cancel(); });
  document.addEventListener('visibilitychange',() => { if (document.hidden) motion?.cancel(); else if (info && location.hash === '#servers') servers(); });
  setInterval(() => { if (info && !document.hidden && location.hash === '#servers') servers(); },30000);
  async function boot() {
    $('request-code').disabled = $('login-submit').disabled = true;
    try {
      const configResponse = await fetch(new URL('./config.json',document.baseURI),{cache:'no-store',signal:AbortSignal.timeout(10000)});
      if (!configResponse.ok) throw Error('无法读取 config.json，请检查官网部署文件。');
      const config = await configResponse.json(), url = new URL(config.apiBase,location.origin);
      if (!['http:','https:'].includes(url.protocol) || url.username || url.password || url.pathname.replace(/\/$/,'') !== '/api/v1' || url.search || url.hash) throw Error('config.json 的 apiBase 需为 /api/v1 或完整的 HTTP(S) API 地址。');
      base = url.href.replace(/\/$/,''); storageKey = 'starbridge-community-session:' + base;
      appearanceKey = 'starbridge-community-appearance:' + base;
      try {
        const saved = JSON.parse(localStorage.getItem(appearanceKey));
        if (saved && typeof saved === 'object' && !Array.isArray(saved)
            && Object.keys(saved).every(key => ['palette','mode'].includes(key))
            && (saved.palette === undefined || Object.hasOwn(palettes,saved.palette))
            && (saved.mode === undefined || ['system','light','dark'].includes(saved.mode))) appearance = saved;
      } catch { /* Ignore invalid or unavailable local appearance storage. */ }
      try { const saved = JSON.parse(sessionStorage.getItem(storageKey)); if (saved && typeof saved.token === 'string' && saved.token.length >= 30 && saved.expires > Date.now()) { accessToken = saved.token; expires = saved.expires; } else sessionStorage.removeItem(storageKey); } catch { /* No browser storage required. */ }
      applyInfo(await request('/community/info')); navigate();
    } catch (error) { message(error.message + ' 可检查 API 地址、网络连接和允许的网站来源。','error',true); }
  }
  applyAppearance(); navigate(); boot();
})();
