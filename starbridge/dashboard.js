'use strict';
const $ = id => document.getElementById(id);
let token = '', revision = '', timer = null, busy = false, dirty = false, saving = false;
let saved = null, canRestart = false, serial = 0;
let latestStatus = null, logsPaused = false, frozenLogs = [];
let panelIdentity = null;
let panelAuthBusy = false, ownerSetupRequired = false;
let communityFeatures = {whitelist:false,tickets:false,sanctions:false};
let managedPlayer = null, playerRequestId = null, playerSubmitting = false;
let latestPlayerActionId = null;
const serverCommands = new WeakMap();
const renderedData = new Map();
const noticeTimers = new Map();
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const activeMotion = new Map();
function stopMotion() { for (const animation of activeMotion.values()) animation.cancel(); activeMotion.clear(); }
function enterMotion(element, distance = 4, delay = 0) {
  activeMotion.get(element)?.cancel();
  if (reducedMotion.matches || document.hidden || !element.animate) return;
  const animation = element.animate([
    {opacity: .55, transform: `translateY(${distance}px)`},
    {opacity: 1, transform: 'none'},
  ], {duration: 160, delay, fill: 'backwards', easing: 'cubic-bezier(.2,.7,.2,1)'});
  activeMotion.set(element, animation);
  const release = () => { if (activeMotion.get(element) === animation) activeMotion.delete(element); };
  animation.addEventListener('finish', release, {once:true});
  animation.addEventListener('cancel', release, {once:true});
}
reducedMotion.addEventListener('change', () => { if (reducedMotion.matches) stopMotion(); });
function enterPageMotion(name) {
  stopMotion();
  if (reducedMotion.matches || document.hidden) return;
  const view = $('view-' + name);
  const candidates = name === 'overview'
    ? [...view.querySelectorAll('.overview-stats > .stat-card')]
    : [document.querySelector('.page-head'), ...view.querySelectorAll(':scope > .toolbar, :scope > .section-head, :scope > .panel > h2, .section-head, .connection-layout > .bot-card, .connection-layout > .connection-guide')];
  const targets = [];
  for (const element of candidates) {
    if (!element || !element.getClientRects().length || targets.some(target => target.contains(element) || element.contains(target))) continue;
    const bounds = element.getBoundingClientRect();
    if (bounds.bottom <= 0 || bounds.top >= innerHeight || bounds.height > innerHeight * .8 || bounds.width * bounds.height > innerWidth * innerHeight * .65) continue;
    targets.push(element);
    if (targets.length === 4) break;
  }
  targets.forEach((element, index) => enterMotion(element, 6, index * 20));
}
function renderChanged(key, data, render) {
  const signature = JSON.stringify(data);
  if (renderedData.get(key) === signature) return;
  render(); renderedData.set(key, signature);
}
function setText(id, value) { if ($(id).textContent !== String(value)) $(id).textContent = value; }
const pages = {
  overview: ['Myrinbot', '运行概览', '查看机器人、游戏服务器与社群的运行状态。'],
  connection: ['接入空间', '机器人连接', '配置 QQ 账号、管理权限与 OneBot 连接。'],
  servers: ['接入空间', '服务器列表', '管理游戏服务器、关联群聊与插件连接。'],
  bindings: ['成员', '账号绑定', '查询游戏玩家与 QQ 账号的绑定关系。'],
  players: ['成员', '玩家管理', '管理玩家档案、账号绑定与到访记录。'],
  accounts: ['成员', '注册账号', '管理社区账号注册、邮件验证和网站 API 接入。'],
  authentication: ['成员', '游戏登录', '设置注册密码登录、绑定 QQ 确认和未登录限制。'],
  features: ['自动化', '消息与事件', '设置双向消息同步、进退服通知与绑定事件。'],
  commands: ['自动化', '远程命令', '为每台服务器配置允许执行的控制台命令。'],
  logs: ['活动', '运行日志', '查看连接、消息、命令执行和配置变更记录。'],
  extensions: ['扩展', '插件管理', '导入插件、管理运行状态和调整插件设置。'],
  app: ['系统', '软件设置', '管理连接地址、数据存储与控制台访问。'],
  backups: ['系统', '备份与恢复', '保存社区数据，或从已校验的备份恢复。'],
  website: ['接入空间', '网站绑定', '绑定Myrinbot官网或自己的官网，设置网站地址和公开 API。'],
  schedules: ['扩展', '定时任务 · 管理任务', '管理内置定时任务插件的公告、预设命令与备份。'],
  whitelist: ['成员', '白名单申请', '审核入服申请，跟进游戏服务器的执行结果。'],
  managers: ['系统', '管理员与权限', '为团队建立独立账号，按职责授权。'],
  monitoring: ['活动', '故障提醒', '查看连接与邮件异常，按需启用群提醒。'],
  statistics: ['活动', '服务器统计', '查看在线趋势、每日活跃与进退服记录。'],
  diagnostics: ['接入空间', '连接诊断', '检查 QQ、游戏桥接、邮件与官网的连接情况。'],
  updates: ['系统', '更新与回退', '检查部署包，备份后切换版本或恢复升级前状态。'],
  deployment: ['系统', '部署模板', '预览导入配置，或应用常用部署模板。'],
  tickets: ['成员', '工单与申诉', '回复玩家问题，处理封禁申诉与内部备注。'],
  sanctions: ['成员', '跨服处罚', '按 UUID 下发封禁或踢出，跟进每台服务器的结果。'],
  'community-features': ['系统', '功能开关', '按需开启白名单申请、工单与申诉和跨服处罚。'],
};
const features = {
  qq_to_mc: ['QQ群 → 游戏', '将普通群消息同步到游戏聊天。'],
  mc_to_qq: ['游戏 → QQ群', '将玩家聊天同步到关联群。'],
  join_quit: ['进退服通知', '玩家加入或离开游戏时通知 QQ 群。'],
  unbind_on_leave: ['退群自动解绑', '退出任意关联群时，解除该服务器的账号绑定。'],
  set_group_card: ['绑定后更新群名片', '把群名片改为玩家名，机器人需要对应管理权限。'],
};

function node(tag, text = '', cls = '') {
  const el = document.createElement(tag); el.textContent = text;
  if (cls) el.className = cls;
  return el;
}
function button(text, action, cls = 'secondary small') {
  const el = node('button', text, cls); el.type = 'button'; el.onclick = action; return el;
}
function notice(id, text, type = '', {persistent = false} = {}) {
  clearTimeout(noticeTimers.get(id)); noticeTimers.delete(id);
  const changed = $(id).textContent !== text;
  setText(id, text);
  const cls = 'notice ' + type; if ($(id).className !== cls) $(id).className = cls;
  if (text && changed) enterMotion($(id), 3);
  if (text && !persistent) noticeTimers.set(id, setTimeout(() => {
    setText(id, ''); noticeTimers.delete(id);
  }, 5000));
}
function markDirty(value = true) {
  document.body.classList.toggle('has-unsaved', value);
  dirty = value; $('save').disabled = !dirty || saving;
  $('save-top').disabled = !dirty || saving;
  $('connection-save').disabled = !dirty || saving;
  $('dirty-label').textContent = dirty ? '有尚未保存的更改' : '所有更改已保存';
  renderConnection();
}
function randomToken() { return Array.from(crypto.getRandomValues(new Uint8Array(32)), v => v.toString(16).padStart(2, '0')).join(''); }
async function copy(value) {
  const target = $('connection-dialog').open ? 'connection-dialog-notice' : 'save-notice';
  try { await navigator.clipboard.writeText(value); notice(target, '已复制到剪贴板。', 'success'); }
  catch { notice(target, '复制失败，请显示并手动复制。', 'error'); }
}
async function api(url, options = {}) {
  const response = await fetch(url, {signal: AbortSignal.timeout(10000), ...options, headers: {'Authorization': 'Bearer ' + token, ...(options.body ? {'Content-Type': 'application/json'} : {}), ...options.headers}, cache: 'no-store'});
  const raw = await response.text();
  let data; try { data = JSON.parse(raw); } catch { data = {error: raw}; }
  if (!response.ok) {
    const error = Error(data.error || (response.status === 401 ? '登录无效或已过期，请重新登录。' : '请求失败：' + response.status));
    error.status = response.status; error.code = data.code; throw error;
  }
  return data;
}
const areaPages = {
  overview: ['overview'], connections: ['connection', 'servers', 'website', 'diagnostics'],
  automation: ['commands', 'features'], community: ['players', 'bindings', 'accounts', 'authentication', 'whitelist', 'tickets', 'sanctions'],
  activity: ['logs', 'monitoring', 'statistics'], system: ['app', 'community-features', 'backups', 'managers', 'updates', 'deployment'], extensions: ['extensions', 'schedules'],
};
const navMobile = matchMedia('(max-width: 900px)');
const expandedAreas = new Set();
let navCollapsed = false, navOpen = false;
try { navCollapsed = localStorage.getItem('starbridge.panel.nav-collapsed') === 'true'; } catch {}
function renderSidebar() {
  const area = Object.keys(areaPages).find(key => areaPages[key].includes(document.body.dataset.view || 'overview'));
  const compact = navCollapsed && !navMobile.matches;
  document.body.classList.toggle('nav-collapsed', navCollapsed);
  $('sidebar').inert = navMobile.matches && !navOpen;
  for (const group of $('section-nav').querySelectorAll('[data-group]')) {
    const name = group.dataset.group, visible = areaPages[name].some(panelAllowed);
    group.hidden = !visible;
    const header = group.querySelector('[data-area]'), expanded = visible && !compact && expandedAreas.has(name);
    header.classList.toggle('active', name === area);
    header.setAttribute('aria-expanded', String(expanded));
    group.querySelector('.sidebar-pages').hidden = !expanded;
  }
  for (const el of $('section-nav').querySelectorAll('[data-tab]')) {
    el.hidden = !panelAllowed(el.dataset.tab);
    const active = el.dataset.tab === document.body.dataset.view;
    el.classList.toggle('active', active);
    if (active) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current');
  }
  $('nav-toggle').setAttribute('aria-expanded', String(navMobile.matches ? navOpen : !navCollapsed));
  $('nav-toggle').setAttribute('aria-label', navMobile.matches ? (navOpen ? '关闭导航' : '打开导航') : (navCollapsed ? '展开导航' : '收起导航'));
}
function setNavCollapsed(value) {
  navCollapsed = value;
  try { localStorage.setItem('starbridge.panel.nav-collapsed', String(value)); } catch {}
  renderSidebar();
}
function setNavOpen(value) {
  const wasOpen = navOpen;
  navOpen = value && navMobile.matches && !document.body.classList.contains('logged-out');
  document.body.classList.toggle('nav-open', navOpen);
  $('sidebar-backdrop').hidden = !navOpen;
  document.querySelector('.workspace').inert = navOpen;
  $('app-topbar').inert = navOpen;
  $('save-bar').inert = navOpen;
  $('sidebar').setAttribute('role', navOpen ? 'dialog' : 'complementary');
  renderSidebar();
  if (navOpen) {
    $('sidebar').setAttribute('aria-modal', 'true');
    $('nav-close').focus();
  } else {
    $('sidebar').removeAttribute('aria-modal');
    if (wasOpen) $('nav-toggle').focus();
  }
}
function trapFocus(container, event) {
  if (event.key !== 'Tab') return;
  const controls = [...container.querySelectorAll('button,input,textarea,select,a[href],[tabindex]')]
    .filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length);
  if (!controls.length) { event.preventDefault(); return; }
  const first = controls[0], last = controls.at(-1);
  if (!container.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
  else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}
function renderTheme() {
  const dark = document.documentElement.dataset.theme === 'dark';
  $('theme-toggle').setAttribute('aria-label', dark ? '切换到浅色主题' : '切换到深色主题');
  $('theme-toggle').setAttribute('aria-pressed', String(dark));
  $('theme-dark-icon').toggleAttribute('hidden', dark); $('theme-light-icon').toggleAttribute('hidden', !dark);
}
$('theme-toggle').onclick = () => {
  const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('starbridge.panel.theme', theme); } catch {}
  renderTheme();
};
$('nav-toggle').onclick = () => { if (navMobile.matches) setNavOpen(!navOpen); else setNavCollapsed(!navCollapsed); };
$('nav-close').onclick = $('sidebar-backdrop').onclick = () => setNavOpen(false);
navMobile.addEventListener('change', () => { if (!navMobile.matches) setNavOpen(false); renderSidebar(); });
document.addEventListener('keydown', event => {
  if (navOpen) {
    if (event.key === 'Escape') { event.preventDefault(); setNavOpen(false); }
    else trapFocus($('sidebar'), event);
  } else if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === 'k' && !document.querySelector('dialog[open]') && token) {
    event.preventDefault(); openGlobalSearch();
  }
});
const panelScopes={overview:'status.read',players:'players.manage',bindings:'players.manage',whitelist:'whitelist.review',extensions:'plugins.manage',schedules:'schedules.manage',monitoring:'monitoring.manage',statistics:'stats.read',backups:'backups.manage',diagnostics:'diagnostics.run',tickets:'tickets.manage',sanctions:'sanctions.manage'};
function panelAllowed(name){return (!(name in communityFeatures)||communityFeatures[name])&&(!panelIdentity||panelIdentity.owner||panelIdentity.permissions.includes(panelScopes[name]));}
renderSidebar(); renderTheme();
window.setCommunityFeatures = data => {
  const next=Object.fromEntries(Object.entries(data).map(([key,value])=>[key,typeof value==='boolean'?value:value.settings.enabled]));
  if(JSON.stringify(next)===JSON.stringify(communityFeatures))return;
  communityFeatures=next;panelAccess();
  if(!panelAllowed(document.body.dataset.view))selectTab(panelIdentity?.owner?'community-features':'overview');
  renderSidebar();
  renderPageResults();
};
function panelAccess(){
  renderSidebar();
  for(const el of document.querySelectorAll('[data-go]'))el.hidden=!!panelIdentity&&!panelAllowed(el.dataset.go);
  $('save-bar').hidden=!panelIdentity?.owner;
  for(const id of ['backup-upload','backup-file','backup-restore'])$(id).hidden=!panelIdentity?.owner;
  $('backup-create').textContent=panelIdentity?.owner?'创建并下载备份':'创建备份';
  $('statistics-form').hidden=!!panelIdentity&&!panelIdentity.owner&&!panelIdentity.permissions.includes('stats.manage');
  $('whitelist-settings-form').hidden=!!panelIdentity&&!panelIdentity.owner;
}
function selectTab(name) {
  if (name === 'replies') name = 'extensions';
  if (!pages[name]) name = 'overview';
  if (!panelAllowed(name)) name=panelIdentity?.owner&&name in communityFeatures?'community-features':'overview';
  const changed = document.body.dataset.view !== name;
  if (name !== 'connection' && $('connection-dialog').open) $('connection-dialog').close();
  if (name !== 'commands' && $('command-create-dialog').open) $('command-create-dialog').close();
  const wasNavOpen = navOpen;
  if (navOpen) setNavOpen(false);
  document.body.dataset.view = name;
  const area = Object.keys(areaPages).find(key => areaPages[key].includes(name));
  expandedAreas.add(area);
  renderSidebar();
  document.querySelectorAll('.view').forEach(el => { el.hidden = el.id !== 'view-' + name; });
  const [section, title, caption] = pages[name];
  $('breadcrumb').textContent = section + ' / ' + title;
  $('page-title').textContent = title; $('page-caption').textContent = caption;
  setText('top-current-page', title);
  if (wasNavOpen) $('page-title').focus();
  if (changed) window.scrollTo(0, 0);
  history.replaceState(null, '', '#' + name);
  if (token && latestStatus) renderLiveView();
  if (token && name === 'extensions') window.loadExtensions?.();
  if (token && name === 'accounts') window.loadRegistration?.();
  if (token && name === 'authentication') window.loadAuthentication?.();
  if (token && name === 'backups') window.loadBackups?.();
  if (token && name === 'website') window.loadWebsite?.();
  if (token && name === 'schedules') window.loadSchedules?.();
  if (token && name === 'whitelist') window.loadWhitelist?.();
  if (token && ['managers','monitoring','statistics'].includes(name)) window.loadEnhancements?.(name);
  if (token && name === 'backups') window.loadBackupPolicy?.();
  if (token && ['diagnostics','updates','deployment','tickets','sanctions','community-features'].includes(name)) window.loadServicePage?.(name);
  $('page-actions').hidden=!!panelIdentity&&!panelIdentity.owner||['diagnostics','updates','deployment','tickets','sanctions','community-features'].includes(name);
  if (changed && !$('content').hidden) enterPageMotion(name);
}
document.querySelectorAll('[data-tab]').forEach(el => { el.onclick = () => selectTab(el.dataset.tab); });
document.querySelectorAll('[data-area]').forEach(el => { el.onclick = () => {
  const area = el.dataset.area;
  if (area === 'overview') { selectTab('overview'); return; }
  if (navCollapsed && !navMobile.matches) { expandedAreas.add(area); setNavCollapsed(false); }
  else { if (expandedAreas.has(area)) expandedAreas.delete(area); else expandedAreas.add(area); renderSidebar(); }
}; });
document.querySelectorAll('[data-go]').forEach(el => { el.onclick = () => selectTab(el.dataset.go); });
const pageKeywords = {
  'community-features':'开关 启用 关闭 白名单 工单 申诉 跨服 处罚 可选',
  diagnostics:'诊断 连接 检测 SMTP Java QQ 官网',updates:'升级 更新 回退 版本 ZIP',deployment:'模板 配置 导入 导出 单服 多服',tickets:'工单 申诉 回复 问题',sanctions:'封禁 跨服 处罚 UUID 解封 踢出',
  overview: '首页 状态 概览 工作台', connection: 'QQ OneBot 账号 管理员 令牌 连接',
  servers: 'Minecraft MC 插件 游戏 群聊 服务器', bindings: '玩家 验证码 绑定',
  players: '玩家 在线 离线 UUID 封禁 踢出 白名单 管理',
  accounts: '注册 申请 邮箱 邮件 SMTP API 网站 账号 验证码',
  authentication: '登录 密码 QQ 验证 认证 AuthMe nLogin LoginSecurity LibreLogin 游戏 安全',
  features: '同步 通知 退群 名片 消息 事件',
  commands: '执行 指令 控制台 远程命令', logs: '日志 活动 错误',
  app: '端口 地址 数据库 登录 重启 系统 软件设置',
  backups: '备份 恢复 导出 导入 数据 ZIP 迁移 回滚',
  website: '官网 网站 绑定 接入 解除 地址 部署 静态 API 信息 玩家 公开 资料 社区',
  schedules: '定时 任务 公告 自动 备份 周期 星期 时间', whitelist: '白名单 申请 审核 入服 批准 拒绝',
  extensions: '插件 扩展 导入 开发 文档 命令 关键词 自动回复',
  managers:'多管理员 权限 团队 服主 审核员 账号',monitoring:'故障 提醒 QQ SMTP 失联 告警',statistics:'统计 活跃 趋势 曲线 进服 退服',
};
function openGlobalSearch() {
  if (!token || document.querySelector('dialog[open]')) return;
  selectTab('overview');
  $('page-search').focus();
  $('page-search').scrollIntoView({block: 'center'});
}
$('global-search').onclick = openGlobalSearch;
function findPages() {
  const query = $('page-search').value.trim().toLocaleLowerCase();
  return query ? Object.entries(pages).filter(([key, value]) => panelAllowed(key)&&
    (value.join(' ') + ' ' + pageKeywords[key]).toLocaleLowerCase().includes(query)) : [];
}
function renderPageResults() {
  const result = $('page-results'); result.replaceChildren();
  result.hidden = !$('page-search').value.trim();
  if (result.hidden) return;
  const matches = findPages();
  if (!matches.length) result.append(node('p', '没有找到相关功能，试试「QQ」「服务器」或「回复」。', 'hint'));
  for (const [key, [, title, caption]] of matches) {
    const item = button('', () => { selectTab(key); $('page-search').value = ''; renderPageResults(); $('page-title').focus(); }, 'search-result');
    item.append(node('strong', title), node('span', caption)); result.append(item);
  }
}
$('page-title').tabIndex = -1;
$('page-search').addEventListener('input', renderPageResults);
$('page-search').addEventListener('keydown', event => {
  if (event.key === 'Escape') { $('page-search').value = ''; renderPageResults(); }
});
$('quick-nav').onsubmit = event => {
  event.preventDefault(); renderPageResults();
  const first = $('page-results').querySelector('button');
  if (first) first.click(); else $('page-search').focus();
};


function field(parent, title, value, role, {multiline = false, secret = false, hint = '', full = false} = {}) {
  const wrap = node('div', '', 'field' + (full ? ' full' : ''));
  const id = 'field-' + (++serial), label = node('label', title);
  label.htmlFor = id;
  const input = document.createElement(multiline ? 'textarea' : 'input');
  input.id = id; input.dataset.field = role; input.value = value;
  if (secret) { input.type = 'password'; input.autocomplete = 'off'; }
  wrap.append(label);
  if (secret) {
    const row = node('div', '', 'secret');
    const reveal = button('显示', () => { input.type = input.type === 'password' ? 'text' : 'password'; reveal.textContent = input.type === 'password' ? '显示' : '隐藏'; });
    row.append(input, reveal, button('生成随机令牌', () => { input.value = randomToken(); markDirty(); }), button('复制', () => copy(input.value)));
    wrap.append(row);
  } else wrap.append(input);
  if (hint) wrap.append(node('p', hint, 'hint'));
  parent.append(wrap);
  return input;
}

function addPair(container, key = '', value = '', isReply = false, changed = markDirty) {
  const row = node('div', '', 'pair' + (isReply ? '' : ' remote'));
  const head = node('div', '', 'command-card-head'), title = node('strong', key || (isReply ? '新回复' : '新命令'));
  const remove = button('×', () => { row.remove(); changed(); filterCommandCards(); }, '');
  remove.setAttribute('aria-label', isReply ? '移除回复' : '移除命令');
  head.append(node('span', isReply ? 'A' : '⌘'), title, node('span', isReply ? '文本' : '命令', 'tag'), remove);
  const body = node('div', '', 'command-card-body');
  const name = field(body, isReply ? '触发关键词' : '群内命令名', key, 'key');
  name.addEventListener('input', () => { title.textContent = name.value || (isReply ? '新回复' : '新命令'); });
  field(body, isReply ? '回复内容' : '控制台命令', value, 'value', {multiline: isReply});
  const meta = node('div', '', 'command-meta');
  meta.append(node('span', '权限与触发方式'), node('b', isReply ? '全体成员 · 精确匹配' : '指定管理员'));
  body.append(meta); row.append(head, body);
  container.append(row);
  filterCommandCards();
  return row;
}
function pairs(container) {
  const map = Object.create(null);
  for (const row of container.querySelectorAll(':scope > .pair')) {
    const key = row.querySelector('[data-field="key"]').value.trim();
    const value = row.querySelector('[data-field="value"]').value;
    if (!key || !value.trim()) throw Error('关键词、命令名称和对应内容不能为空；不需要的条目请移除。');
    if (Object.hasOwn(map, key)) throw Error('存在重复名称：' + key);
    map[key] = value;
  }
  return map;
}
function splitIds(text) { return text.trim() ? text.trim().split(/[\s,，;；]+/).filter(Boolean) : []; }

function commandTargets() {
  return [...$('server-editors').children].map(card => ({
    card, value: card.querySelector('[data-field="id"]').id,
    name: card.querySelector('[data-field="name"]').value.trim() || '新服务器',
    id: card.querySelector('[data-field="id"]').value.trim() || '未填写',
  }));
}
function syncCommandTargets() {
  const select = $('command-target-server'), previous = select.value, targets = commandTargets();
  select.replaceChildren(new Option('请选择目标服务器', ''));
  for (const target of targets) select.append(new Option(target.name + ' · ID：' + target.id, target.value));
  select.value = targets.some(target => target.value === previous) ? previous : '';
  $('command-create-confirm').disabled = saving || !panelIdentity?.owner || !select.value;
  if ($('command-create-dialog').open && targets.length < 2) $('command-create-dialog').close();
}
function goToCommandServers() {
  if (!panelIdentity?.owner || saving) return;
  selectTab('servers'); $('add-server').focus();
}
function addCommandDraft(card) {
  if (!panelIdentity?.owner || saving || !card?.isConnected) return;
  $('command-search').value = '';
  const row = addPair(serverCommands.get(card));
  markDirty(); row.querySelector('[data-field="key"]').focus();
}
$('command-create').onclick = () => {
  if (!panelIdentity?.owner || saving || $('command-create-dialog').open) return;
  const targets = commandTargets();
  if (!targets.length) { goToCommandServers(); return; }
  if (targets.length === 1) { addCommandDraft(targets[0].card); return; }
  $('command-target-server').value = ''; syncCommandTargets();
  $('command-create-dialog').returnValue = '';
  $('command-create-dialog').showModal(); $('command-target-server').focus();
};
$('command-server-add').onclick = goToCommandServers;
$('command-search-clear').onclick = () => { $('command-search').value = ''; filterCommandCards(); $('command-search').focus(); };
$('command-target-server').onchange = () => {
  $('command-create-confirm').disabled = saving || !panelIdentity?.owner || !$('command-target-server').value;
};
$('command-create-form').onsubmit = event => {
  event.preventDefault();
  if (!panelIdentity?.owner || saving || !$('command-create-dialog').open) return;
  const target = commandTargets().find(row => row.value === $('command-target-server').value);
  if (!target) { syncCommandTargets(); $('command-target-server').focus(); return; }
  $('command-create-dialog').close('created'); addCommandDraft(target.card);
};
for (const id of ['command-create-close', 'command-create-cancel']) $(id).onclick = () => { if (!saving) $('command-create-dialog').close(); };
$('command-create-dialog').addEventListener('cancel', event => { if (saving) event.preventDefault(); });
$('command-create-dialog').addEventListener('keydown', event => trapFocus($('command-create-dialog'), event));
$('command-create-dialog').addEventListener('close', () => {
  if ($('command-create-dialog').returnValue !== 'created' && panelIdentity?.owner && $('command-create').getClientRects().length) $('command-create').focus();
});

function addServer(server) {
  const card = node('div', '', 'server-card');
  const commandGroup = node('section', '', 'command-group');
  const head = node('div', '', 'section-head');
  head.append(node('h3', server.name || '新服务器', 'server-title'), button('移除服务器', () => {
    card.remove(); commandGroup.remove(); markDirty(); filterCommandCards();
  }, 'danger small'));
  card.append(head);
  const grid = node('div', '', 'grid');
  const id = field(grid, '服务器 ID', server.id, 'id', {hint: '与插件 server-id 一致；更改 ID 不会迁移旧绑定。'});
  const name = field(grid, '显示名称', server.name, 'name');
  const updateCommandServer = () => {
    head.querySelector('h3').textContent = name.value || '新服务器';
    commandHead.querySelector('h3').textContent = name.value || '新服务器';
    commandHead.querySelector('.hint').textContent = 'ID：' + (id.value.trim() || '未填写');
    filterCommandCards();
  };
  id.addEventListener('input', updateCommandServer); name.addEventListener('input', updateCommandServer);
  field(grid, '关联 QQ 群', server.groups.join('\n'), 'groups', {multiline: true, full: true, hint: '每行一个群号，也可用逗号或空格分隔。'});
  field(grid, '游戏插件连接令牌', server.token, 'token', {secret: true, full: true, hint: '修改后需要在游戏插件同步此令牌，可使用下方下载的配置。'});
  card.append(grid);
  const commands = node('div', '', 'commands');
  serverCommands.set(card, commands);
  const commandHead = node('div', '', 'section-head');
  const commandTitle = node('div'); commandTitle.append(node('h3', server.name || '新服务器'), node('p', 'ID：' + (server.id || '未填写'), 'hint'));
  commandHead.append(commandTitle, button('＋ 添加命令', () => addCommandDraft(card)));
  commandGroup.append(commandHead, commands, node('p', '还没有指令，点击「＋ 添加命令」开始配置。', 'hint command-group-empty'));
  $('command-editors').append(commandGroup);
  card.append(button('管理远程命令 →', () => { selectTab('commands'); commandGroup.scrollIntoView({block: 'center', behavior: reducedMotion.matches ? 'instant' : 'smooth'}); }));
  for (const [key, value] of Object.entries(server.commands || {})) addPair(commands, key, value);
  const details = document.createElement('details');
  details.append(node('summary', '安装插件 · 下载连接配置'));
  const endpoint = field(details, '主程序访问地址', location.origin, 'endpoint', {hint: '填写游戏服务器能访问的地址。这个地址写入下载的插件配置。'});
  endpoint.style.marginTop = '12px';
  details.append(button('下载插件 config.yml', () => downloadPlugin(card)));
  details.append(button('下载新版插件 JAR', downloadPluginJar));
  addModBridgeControls(details, card, server.id);
  card.append(details);
  $('server-editors').append(card);
  filterCommandCards();
}
function readServer(card) {
  const val = role => card.querySelector('[data-field="' + role + '"]').value;
  return {id: val('id').trim(), name: val('name').trim(), token: val('token'), groups: splitIds(val('groups')), commands: pairs(serverCommands.get(card))};
}
async function downloadPlugin(card, platform = 'bukkit') {
  try {
    if (dirty) throw Error('请先保存全部设置，再下载与已生效设置一致的插件配置。');
    const server = readServer(card), endpoint = new URL(card.querySelector('[data-field="endpoint"]').value);
    if (!['http:', 'https:'].includes(endpoint.protocol) || endpoint.username || endpoint.password || endpoint.search || endpoint.hash) throw Error('主程序访问地址必须是有效的 HTTP / HTTPS 地址，不包含账号、查询参数或片段。');
    const yaml = '# 从Myrinbot面板导出，包含连接令牌，请妥善保管。\n' +
      'endpoint: ' + JSON.stringify(endpoint.href.replace(/\/+$/, '')) + '\n' +
      'server-id: ' + JSON.stringify(server.id) + '\ntoken: ' + JSON.stringify(server.token) + '\n' +
      '# 新版插件连接后会从主程序自动同步命令白名单。\nallowed-commands: ' + JSON.stringify(Object.values(server.commands)) + '\n';
    const mod = platform !== 'bukkit';
    const selected = mod ? (await modBridgeCatalog()).find(row=>row.platform+'/'+row.version===platform) : null;
    if (mod && !selected) throw Error('请选择支持的模组加载器与游戏版本。');
    const usesProperties = selected?.config === 'properties';
    const toml = '# 从Myrinbot面板导出，包含连接令牌，请妥善保管。\n' +
      'endpoint = ' + JSON.stringify(endpoint.href.replace(/\/+$/, '')) + '\n' +
      'server-id = ' + JSON.stringify(server.id) + '\ntoken = ' + JSON.stringify(server.token) + '\n' +
      'allowed-commands = ' + JSON.stringify(Object.values(server.commands)) + '\n';
    const propertiesEscape = value => value.replace(/\\/g, '\\\\').replace(/\r/g, '\\r').replace(/\n/g, '\\n').replace(/\t/g, '\\t').replace(/^ /, '\\ ');
    const properties = '# 从Myrinbot面板导出，包含连接令牌，请妥善保管。\nendpoint=' + propertiesEscape(endpoint.href.replace(/\/+$/, '')) + '\nserver-id=' + propertiesEscape(server.id) + '\ntoken=' + propertiesEscape(server.token) + '\nallowed-commands=list\n';
    const configName = usesProperties ? 'starbridge-bridge.properties' : 'starbridge-common.toml';
    const url = URL.createObjectURL(new Blob([usesProperties ? properties : mod ? toml : yaml], {type: 'text/plain;charset=utf-8'}));
    const a = document.createElement('a'); a.href = url; a.download = mod ? configName : 'Myrinbot-' + server.id + '-config.yml'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice('save-notice', mod ? '已下载。将 '+configName+' 放入游戏服 config 目录，然后重启游戏服。' : '已下载。将文件重命名为 config.yml，放入游戏服 plugins/StarBridge 后重启游戏服。', 'success');
  } catch (e) { notice('save-notice', e.message, 'error'); }
}

function pendingBanner(fields, error = '') {
  const labels = {host: '监听地址', port: '端口', database: '数据库路径'};
  const banner = $('restart-banner'); banner.replaceChildren(); banner.hidden = !fields.length && !error;
  if (error) banner.append(node('p', error));
  if (fields.length) {
    banner.append(node('span', '已保存，等待重启生效：' + fields.map(f => labels[f]).join('、') + '。 '));
    banner.append(button('前往重启', () => selectTab('app')));
  }
}
function renderConfig(data) {
  if ($('command-create-dialog').open) $('command-create-dialog').close();
  saved = data.config; revision = data.revision; canRestart = data.can_restart;
  $('self-id').value = saved.onebot.self_id;
  $('admins').value = saved.onebot.admins.join('\n');
  $('onebot-token').value = saved.onebot.token;
  for (const key of ['host', 'port', 'database']) $(key).value = saved.app[key];
  $('admin-token').value = saved.app.admin_token;
  $('onebot-url').value = location.origin.replace(/^http/, 'ws') + '/onebot/ws';
  $('server-editors').replaceChildren(); $('command-editors').replaceChildren(); saved.servers.forEach(addServer);
  $('feature-editors').replaceChildren();
  for (const [key, [title, hint]] of Object.entries(features)) {
    const row = node('div', '', 'switch-row'), label = node('label', title), input = document.createElement('input');
    input.type = 'checkbox'; input.id = 'feature-' + key; input.checked = saved.features[key]; label.htmlFor = input.id;
    label.append(node('p', hint, 'hint')); row.append(label, input); $('feature-editors').append(row);
  }
  $('restart').disabled = !canRestart;
  pendingBanner(data.restart_required, data.restart_error);
  markDirty(false);
  filterCommandCards();
}

function renderConnection() {
  if (!saved) return;
  const connection = saved.onebot, online = latestStatus?.onebot === true;
  const connectedId = online ? latestStatus.self_id : '';
  setText('connection-status-text', latestStatus ? (online ? '已连接' : '等待连接') : '正在读取');
  $('connection-status').classList.toggle('is-online', online);
  $('connection-status').querySelector('.status-dot').classList.toggle('online', online);
  setText('connection-account', connectedId || connection.self_id || '自动识别');
  setText('connection-groups', new Set(saved.servers.flatMap(server => server.groups)).size + ' 个');
  setText('connection-admin-count', connection.admins.length + ' 位');
  setText('connection-address', $('onebot-url').value);
  setText('connection-state-hint', online ? '连接正常，可以接收和发送群消息。' : '等待 QQ 协议端连接，请确认地址与令牌一致。');
  const changed = $('self-id').value.trim() !== connection.self_id || $('onebot-token').value !== connection.token ||
    JSON.stringify(splitIds($('admins').value)) !== JSON.stringify(connection.admins);
  $('connection-draft').hidden = !changed;
  setText('connection-save-hint', dirty ? '保存会同时应用面板中尚未保存的设置。' : '更改会保留为草稿，保存后生效。');
}
function openConnectionSettings() {
  if (!saved || !panelIdentity?.owner || saving || $('connection-dialog').open) return;
  notice('connection-dialog-notice', '');
  $('connection-dialog').showModal();
}
document.querySelectorAll('[data-open-connection]').forEach(btn => { btn.onclick = openConnectionSettings; });
for (const id of ['connection-close', 'connection-done']) $(id).onclick = () => {
  if (!saving) $('connection-dialog').close();
};
$('connection-dialog').addEventListener('cancel', event => { if (saving) event.preventDefault(); });
$('connection-dialog').addEventListener('keydown', event => {
  trapFocus($('connection-dialog'), event);
});
$('connection-dialog').addEventListener('close', () => {
  $('onebot-token').type = 'password';
  $('connection-dialog').querySelector('[data-reveal="onebot-token"]').textContent = '显示';
});
$('connection-dialog').addEventListener('click', event => {
  if (event.target !== $('connection-dialog') || saving) return;
  const bounds = $('connection-dialog').getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) $('connection-dialog').close();
});
$('connection-save').onclick = async () => {
  if (!dirty || saving) return;
  notice('connection-dialog-notice', '');
  await $('save').onclick();
  if (!dirty) $('connection-dialog').close();
};

function filterCommandCards() {
  const container = $('command-editors'), query = $('command-search').value.trim().toLowerCase();
  const cards = [...container.querySelectorAll('.pair')], groups = [...container.children]; let visible = 0;
  for (const card of cards) {
    const text = [...card.querySelectorAll('input,textarea')].map(el => el.value).join(' ').toLowerCase();
    card.hidden = query !== '' && !text.includes(query); if (!card.hidden) visible++;
  }
  $('command-total').textContent = query ? `匹配 ${visible} / ${cards.length} 项` : `全部命令：${cards.length}`;
  for (const group of groups) group.querySelector('.command-group-empty').hidden = !!group.querySelector('.pair');
  $('command-create').hidden = $('command-server-add').hidden = !panelIdentity?.owner;
  $('command-create').disabled = saving;
  $('command-empty').hidden = !!groups.length || !panelIdentity?.owner;
  $('command-search-empty').hidden = !query || !!visible || !groups.length || !panelIdentity?.owner;
  syncCommandTargets();
}

const playerActionLabels = {kick: '踢出', ban: '永久封禁', unban: '解除封禁', whitelist_add: '加入白名单', whitelist_remove: '移出白名单'};
const playerStatusLabels = {online: '在线', offline: '离线', unknown: '状态未知'};
const actionStateLabels = {pending: '等待执行', success: '已完成', failed: '执行失败', expired: '结果未确认', cancelled: '已撤销'};
let profilePage = 1, profilePages = 1, profileSequence = 0, profileTimer;
let profileItems = [], profileCurrent = null, profileWorking = false;
const profileSelection = new Set();
const profileFilterIds = {name:'player-search',uuid:'player-uuid-filter',ip:'player-ip-filter',region:'player-region-filter',binding:'player-binding-filter',server:'player-server',status:'player-state'};
const profileDate = value => value ? new Date(value * 1000).toLocaleString() : '暂无记录';
function selectionChanged() {
  $('profile-bulk-bar').hidden = profileSelection.size === 0;
  $('profile-selected').textContent = `已选 ${profileSelection.size} 位`;
  $('profile-select-all').checked = profileItems.length > 0 && profileSelection.size === profileItems.length;
  $('profile-select-all').indeterminate = profileSelection.size > 0 && profileSelection.size < profileItems.length;
  $('profile-select-all').disabled = profileItems.length === 0;
  for (const row of $('player-list').querySelectorAll('.profile-row')) {
    const selected = profileSelection.has(Number(row.dataset.id));
    row.querySelector('input[type="checkbox"]').checked = selected;
    row.classList.toggle('is-selected', selected);
  }
}
function resetProfileSelection() { profileSelection.clear(); selectionChanged(); }
function renderProfileRows() {
  // Heartbeat timestamps and unused game fields should not rebuild the table.
  const visible = profileItems.map(p => [p.id,p.name,p.uuid,p.ip,p.region,p.status,p.bound,
    p.bindings.map(b=>[b.qq,b.server_name]),p.servers.map(v=>[v.server_name,v.historical,v.status])]);
  renderChanged('profile-rows', visible, () => {
  $('player-list').replaceChildren(...profileItems.map(p => {
    const row = node('tr', '', 'profile-row'); row.dataset.id = p.id;
    row.classList.toggle('is-selected', profileSelection.has(p.id));
    const checkCell = node('td'), checkbox = node('input'); checkbox.type = 'checkbox';
    checkbox.setAttribute('aria-label', `选择 ${p.name}`); checkbox.checked = profileSelection.has(p.id);
    checkbox.onchange = () => { if (checkbox.checked) profileSelection.add(p.id); else profileSelection.delete(p.id); row.classList.toggle('is-selected', checkbox.checked); selectionChanged(); };
    checkCell.append(checkbox);
    const person = node('td'), identity = node('div', '', 'catalog-person'), text = node('div');
    const name = node('div', '', 'player-title'); name.append(node('strong',p.name),node('span',playerStatusLabels[p.status],'pill '+(p.status==='online'?'green':'')));
    text.append(name,node('p',p.uuid,'player-uuid')); identity.append(node('span',p.name.slice(0,2).toUpperCase(),'catalog-avatar'),text);person.append(identity);
    const ip = node('td');ip.append(node('p',p.ip || '未记录'),node('p',p.region || '归属地未记录','muted'));
    const bindings = node('td');
    for (const b of p.bindings) { const block=node('div','','catalog-cell-item');block.append(node('p','QQ '+b.qq),node('p',b.server_name,'muted'));bindings.append(block); }
    if (!p.bindings.length) bindings.append(node('span','未绑定','muted'));
    const visits=node('td');for(const v of p.servers){const block=node('div','','catalog-cell-item');block.append(node('p',v.server_name+(v.historical?'（历史）':'')),node('p',playerStatusLabels[v.status],'muted'));visits.append(block);}
    if(!p.servers.length)visits.append(node('span','暂无到访记录','muted'));
    const actions=node('td'),buttons=node('div','','catalog-row-actions');
    const detail=button('详情',()=>openProfile(p.id),'text-button profile-detail');
    const unbind=button('解绑',()=>bulkProfiles([p.id],'unbind'),'text-button profile-unbind');unbind.disabled=!p.bound;
    buttons.append(detail,unbind,button('删除',()=>bulkProfiles([p.id],'delete'),'text-button profile-delete danger'));actions.append(buttons);
    row.append(checkCell,node('td',String(p.id),'catalog-id'),person,ip,bindings,visits,actions);return row;
  }));
  if(!profileItems.length){const row=node('tr'),cell=node('td','暂无符合条件的玩家。可新增档案，或连接游戏插件自动记录。','empty-cell');cell.colSpan=7;row.append(cell);$('player-list').append(row);}
  });
  selectionChanged();
}
async function loadProfiles() {
  if (!token) return;
  const seq = ++profileSequence, query = new URLSearchParams({page:profilePage,page_size:$('profile-page-size').value});
  for (const [key,id] of Object.entries(profileFilterIds)) if ($(id).value.trim()) query.set(key,$(id).value.trim());
  try {
    const data = await api('/api/player-profiles?'+query);
    if(seq !== profileSequence || !token)return;
    const selectedServer=$('player-server').value;
    renderChanged('profile-server-options', data.servers, () => $('player-server').replaceChildren(new Option('全部服务器',''),...data.servers.map(s=>new Option(s.name+(s.historical?'（历史）':''),s.id))));
    $('player-server').value=selectedServer;
    profilePage=data.page;profilePages=data.pages;profileItems=data.items;
    for(const id of profileSelection)if(!profileItems.some(p=>p.id===id))profileSelection.delete(id);
    setText('player-total', `共 ${data.total} 位玩家 · 本页 ${data.items.length} 位`);
    setText('profile-page-label', `${profilePage} / ${profilePages}`);
    $('profile-prev').disabled=profilePage<=1;$('profile-next').disabled=profilePage>=profilePages;
    renderProfileRows();
  } catch(error) { if(seq===profileSequence)notice('player-notice',error.message,'error'); }
}
function filterProfiles() {profilePage=1;resetProfileSelection();clearTimeout(profileTimer);profileTimer=setTimeout(loadProfiles,250);}
for(const id of Object.values(profileFilterIds))$(id).addEventListener($(id).tagName==='SELECT'?'change':'input',filterProfiles);
$('profile-search-form').onsubmit=event=>{event.preventDefault();profilePage=1;resetProfileSelection();clearTimeout(profileTimer);loadProfiles();};
$('profile-clear').onclick=()=>{for(const id of Object.values(profileFilterIds))$(id).value='';filterProfiles();};
$('profile-page-size').onchange=filterProfiles;
$('profile-prev').onclick=()=>{profilePage--;resetProfileSelection();loadProfiles();};
$('profile-next').onclick=()=>{profilePage++;resetProfileSelection();loadProfiles();};
$('profile-select-all').onchange=()=>{profileSelection.clear();if($('profile-select-all').checked)for(const p of profileItems)profileSelection.add(p.id);renderProfileRows();};
async function bulkProfiles(ids,action,server='') {
  if(profileWorking || !ids.length)return;
  const names=ids.length===1?(profileItems.find(p=>p.id===ids[0])?.name || profileCurrent?.name || '这位玩家'):`选中的 ${ids.length} 位玩家`;
  const question=action==='delete'?`删除 ${names} 的本地档案、到访记录与全部 QQ 绑定？不会删除游戏存档或封禁玩家。`:`解除 ${names} ${server?'在此服务器':'在全部服务器'}的 QQ 绑定？`;
  if(!confirm(question))return;
  profileWorking=true;
  try{
    const result=await api('/api/player-profiles/bulk',{method:'POST',body:JSON.stringify({ids,action,server})});
    latestPlayerActionId=null;notice('player-notice',`已${action==='delete'?'删除':'处理'} ${result.profiles} 份档案，移除 ${result.bindings_removed} 项账号绑定。`,'success');
    if(profileCurrent&&ids.includes(profileCurrent.id)){
      if(action==='delete')$('profile-dialog').close();else populateProfile(await api('/api/player-profiles/'+profileCurrent.id));
    }
    resetProfileSelection();await loadProfiles();await refresh();
  }catch(error){notice($('profile-dialog').open?'profile-notice':'player-notice',error.message,'error');}
  finally{profileWorking=false;}
}
$('profile-bulk-unbind').onclick=()=>bulkProfiles([...profileSelection],'unbind');
$('profile-bulk-delete').onclick=()=>bulkProfiles([...profileSelection],'delete');
function populateProfile(p) {
  profileCurrent=p;
  $('profile-title').textContent=p?`${p.name} 的档案`:'新增玩家';
  $('profile-subtitle').textContent=p?`ID ${p.id} · 建档 ${profileDate(p.created)} · 最近游戏 ${profileDate(p.last_seen)}`:'填写真实的玩家名与 UUID，之后可关联 QQ 账号。';
  for(const key of ['name','uuid','ip','region','notes'])$('profile-'+key).value=p?.[key] || '';
  for(const key of ['name','uuid','ip'])$('profile-'+key).readOnly=Boolean(p);
  $('profile-save').textContent=p?'保存档案':'创建档案';
  $('profile-identity-note').textContent=p?'玩家名、UUID 与 IP 由游戏端记录；可以修改归属地与备注。':'手动新增不会更改游戏存档、封禁或白名单。';
  $('profile-extra').hidden=!p;
  notice('profile-notice','');
  if(!p)return;
  $('profile-bindings').replaceChildren(...p.bindings.map(b=>{const row=node('div','','profile-record');const text=node('div');text.append(node('strong','QQ '+b.qq),node('p',b.server_name+' · '+profileDate(b.created),'muted'));row.append(text,button('解绑',()=>bulkProfiles([p.id],'unbind',b.server),'text-button'));return row;}));
  if(!p.bindings.length)$('profile-bindings').append(node('p','尚未绑定 QQ。','hint'));
  $('profile-bind-server').replaceChildren(...(latestStatus?.servers || []).map(s=>new Option(s.name,s.id)));
  $('profile-bind-form').querySelector('button').disabled=!$('profile-bind-server').options.length;$('profile-bind-qq').value='';
  $('profile-visits').replaceChildren(...p.servers.map(v=>{
    const row=node('div','','profile-record'),text=node('div');text.append(node('strong',v.server_name+(v.historical?'（历史）':'')),node('p',`${playerStatusLabels[v.status]} · 最近游戏 ${profileDate(v.last_seen)}`,'muted'));
    const facts=[];if(v.banned)facts.push('已封禁');if(v.whitelisted)facts.push('白名单');if(v.op)facts.push('OP');if(v.status==='online'&&v.world)facts.push(`${v.world} · ${v.ping} ms · 生命 ${v.health}`);
    if(facts.length)text.append(node('p',facts.join(' · '),'hint'));
    const manage=button('游戏管理',()=>{$('profile-dialog').close();openPlayerDialog(v);});manage.disabled=!v.manageable;if(!v.manageable)manage.title='需要服务器连接新版插件并上报此玩家';row.append(text,manage);return row;
  }));
  if(!p.servers.length)$('profile-visits').append(node('p','暂无到访记录。','hint'));
}
async function openProfile(id) {
  if(profileWorking)return;
  try{populateProfile(id?await api('/api/player-profiles/'+id):null);$('profile-dialog').showModal();}
  catch(error){notice('player-notice',error.message,'error');}
}
$('profile-add').onclick=()=>openProfile(null);
$('profile-close').onclick=()=>{if(!profileWorking)$('profile-dialog').close();};
$('profile-dialog').addEventListener('cancel',event=>{if(profileWorking)event.preventDefault();});
async function profileMutation(operation) {
  if(profileWorking)return;
  profileWorking=true;const controls=[...$('profile-dialog').querySelectorAll('input,select,textarea,button')];const disabled=controls.map(el=>el.disabled);controls.forEach(el=>el.disabled=true);
  notice('profile-notice','正在保存…','', {persistent:true});
  try{const p=await operation();populateProfile(p);notice('profile-notice','已保存。','success');await loadProfiles();await refresh();}
  catch(error){notice('profile-notice',error.message,'error');}
  finally{profileWorking=false;controls.forEach((el,i)=>el.disabled=disabled[i]);$('profile-bind-form').querySelector('button').disabled=!$('profile-bind-server').options.length;}
}
$('profile-form').onsubmit=event=>{
  event.preventDefault();
  const fields=Object.fromEntries(['name','uuid','ip','region','notes'].map(k=>[k,$('profile-'+k).value.trim()]));
  const current=profileCurrent;
  profileMutation(()=>api('/api/player-profiles'+(current?'/'+current.id:''),{method:current?'PATCH':'POST',body:JSON.stringify(current?{region:fields.region,notes:fields.notes,revision:current.revision}:fields)}));
};
$('profile-bind-form').onsubmit=event=>{
  event.preventDefault();if(!profileCurrent)return;
  const data={server:$('profile-bind-server').value,qq:$('profile-bind-qq').value.trim()};
  profileMutation(()=>api('/api/player-profiles/'+profileCurrent.id+'/bind',{method:'POST',body:JSON.stringify(data)}));
};
function renderPlayers() {
  if (!latestStatus) return;
  const data=latestStatus,servers=data.player_servers || [],notes=[];
  if(servers.some(s=>!s.online))notes.push('未连接的服务器显示历史资料，当前游戏状态未知。');
  if(servers.some(s=>s.online&&!s.supported))notes.push('部分服务器需要升级插件才能管理玩家。');
  if(servers.some(s=>s.truncated))notes.push('插件单次上报最近 500 位玩家；已记录的档案会保留。');
  if(servers.some(s=>s.online&&s.whitelist_enabled===false))notes.push('部分服务器未开启白名单限制。');
  notice('player-note',notes.join(' '), '', {persistent:true});
  renderChanged('player-operations', [data.player_actions, servers.map(s=>[s.id,s.name])], () => {
  $('player-operations').replaceChildren(...(data.player_actions || []).map(item=>{
    const row=node('div','','player-operation'),left=node('div');const server=servers.find(s=>s.id===item.server);
    left.append(node('strong',`${item.player} · ${playerActionLabels[item.action]}`),node('p',`${server?.name || item.server} · ${profileDate(item.created)}`,'muted'),node('p',item.detail,'hint'));
    row.append(left,node('span',actionStateLabels[item.status] || item.status,'pill '+(item.status==='success'?'green':'')));return row;
  }));
  if(!(data.player_actions || []).length)$('player-operations').append(node('p','暂无游戏操作记录。','log-empty'));
  });
  const last=(data.player_actions || []).find(item=>item.id===latestPlayerActionId);
  if(last)renderChanged('player-action-notice',[last.id,last.status,last.detail],()=>notice('player-notice',`${last.player} · ${playerActionLabels[last.action]} · ${actionStateLabels[last.status]}：${last.detail}`,last.status==='success'?'success':last.status==='failed'?'error':''));
  if(document.body.dataset.view==='players')loadProfiles();
}

function playerActionEffect() {
  const action = $('player-action').value;
  const effects = {
    kick: '将断开这位玩家的当前连接，玩家仍可重新加入。',
    ban: '将永久禁止这位玩家加入当前服务器，并断开其当前连接；可通过「解除封禁」恢复。',
    unban: '将移除这位玩家在当前服务器的封禁记录。',
    whitelist_add: '将这位玩家加入当前服务器的白名单。只有游戏服务器开启白名单限制时才影响加入权限。',
    whitelist_remove: '将这位玩家移出当前服务器的白名单，不会主动断开其当前连接。',
  };
  $('player-action-effect').textContent = effects[action];
  $('player-reason-field').hidden = !['kick', 'ban'].includes(action);
  playerRequestId = null;
}
function openPlayerDialog(player) {
  managedPlayer = player; playerRequestId = null;
  $('player-dialog-target').textContent = `${player.name} · ${player.server_name}`;
  $('player-reason').value = ''; notice('player-dialog-notice', '');
  for (const option of $('player-action').options) option.disabled = option.value === 'kick' && player.status !== 'online';
  $('player-action').value = player.banned ? 'unban' : player.status === 'online' ? 'kick' : 'whitelist_add';
  playerActionEffect(); $('player-dialog').showModal();
}
function closePlayerDialog() { if (!playerSubmitting) $('player-dialog').close(); }
$('player-dialog-close').onclick = closePlayerDialog; $('player-dialog-cancel').onclick = closePlayerDialog;
$('player-dialog').addEventListener('cancel', event => { if (playerSubmitting) event.preventDefault(); });
$('player-action').onchange = playerActionEffect;
$('player-reason').oninput = () => { playerRequestId = null; };
$('player-action-form').onsubmit = async event => {
  event.preventDefault(); if (playerSubmitting || !managedPlayer) return;
  playerSubmitting = true;
  const controls = [...$('player-action-form').querySelectorAll('input,select,button')]; controls.forEach(el => { el.disabled = true; });
  playerRequestId ||= crypto.randomUUID();
  const action = $('player-action').value;
  try {
    const result = await api('/api/player-actions', {method: 'POST', body: JSON.stringify({request_id: playerRequestId, server: managedPlayer.server, uuid: managedPlayer.uuid, player: managedPlayer.name, action, reason: ['kick', 'ban'].includes(action) ? $('player-reason').value.trim() : ''})});
    latestPlayerActionId = result.id;
    notice('player-notice', result.status === 'pending' ? `${managedPlayer.name} 的「${playerActionLabels[action]}」已提交，等待游戏插件返回结果。` : result.detail, result.status === 'success' ? 'success' : '');
    $('player-dialog').close(); await refresh();
  } catch (error) { notice('player-dialog-notice', error.message, 'error'); }
  finally { playerSubmitting = false; controls.forEach(el => { el.disabled = false; }); }
};
$('players-refresh').onclick = async () => { await refresh(); await loadProfiles(); };
async function downloadPluginJar() {
  try {
    const response = await fetch('/api/plugin', {headers: {Authorization: 'Bearer ' + token}, signal: AbortSignal.timeout(30000), cache: 'no-store'});
    if (!response.ok) throw Error('插件下载失败：' + response.status);
    const url = URL.createObjectURL(await response.blob()), link = node('a');
    link.href = url; link.download = 'Myrinbot-0.5.3.jar'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    latestPlayerActionId = null;
    notice('player-notice', '新版插件已下载。替换游戏服务器 plugins 中的旧版游戏端 JAR，然后重启游戏服务器。', 'success');
  } catch (error) { notice('player-notice', error.message, 'error'); selectTab('players'); }
}
$('download-player-plugin').onclick = downloadPluginJar;
function renderBindings() {
  if (!latestStatus) return;
  const query = $('binding-search').value.trim().toLowerCase(), server = $('binding-server').value;
  const names = new Map(latestStatus.servers.map(s => [s.id, s.name]));
  const rows = latestStatus.bindings.filter(b => (!server || b.server === server) && (!query || [b.name, b.qq, b.server, names.get(b.server) || ''].join(' ').toLowerCase().includes(query)));
  setText('binding-total', rows.length + ' / ' + latestStatus.bindings.length + ' 条记录');
  renderChanged('bindings', [rows, [...names], Boolean(query || server)], () => {
  $('bindings').replaceChildren(...rows.map(b => { const row = node('tr'); for (const v of [b.name, b.qq, names.get(b.server) || b.server, new Date(b.created * 1000).toLocaleString()]) row.append(node('td', v)); return row; }));
  if (!rows.length) { const row = node('tr'), cell = node('td', query || server ? '没有找到符合条件的绑定记录。' : '暂无绑定记录。玩家可在游戏中输入 /qbind 获取验证码。', 'empty-cell'); cell.colSpan = 4; row.append(cell); $('bindings').append(row); }
  });
}
const logLabels = {onebot: '机器人连接', relay: '消息同步', binding: '账号绑定', command: '命令执行', player: '玩家管理', settings: '配置保存', extension: '插件', registration: '账号注册', error: '错误'};
function logRow(l) {
  const row = node('div', '', 'log'); row.append(node('span', new Date(l.time * 1000).toLocaleTimeString(), 'muted'), node('span', logLabels[l.kind] || l.kind, 'log-kind'), node('span', l.detail)); return row;
}
function renderLogs() {
  if (!latestStatus) return;
  const query = $('log-search').value.trim().toLowerCase(), kind = $('log-kind').value;
  const rows = (logsPaused ? frozenLogs : latestStatus.logs).filter(l => (!kind || l.kind === kind) && (!query || l.detail.toLowerCase().includes(query)));
  if (document.body.dataset.view === 'logs') renderChanged('logs', rows, () => {
  $('logs').replaceChildren(...rows.map(logRow));
  if (!rows.length) $('logs').append(node('p', '暂无符合条件的日志。', 'log-empty'));
  });
  if (document.body.dataset.view === 'overview') renderChanged('mini-logs', latestStatus.logs.slice(0, 4), () => {
  $('mini-logs').replaceChildren(...latestStatus.logs.slice(0, 4).map(logRow));
  if (!latestStatus.logs.length) $('mini-logs').append(node('p', '暂无活动，等待机器人与插件连接。', 'log-empty'));
  });
}
$('command-search').oninput = filterCommandCards;
$('command-editors').addEventListener('input', filterCommandCards);
$('binding-search').oninput = renderBindings; $('binding-server').onchange = renderBindings;
$('log-search').oninput = renderLogs; $('log-kind').onchange = renderLogs;
$('pause-logs').onclick = () => { logsPaused = !logsPaused; if (logsPaused) frozenLogs = [...(latestStatus?.logs || [])]; $('pause-logs').textContent = logsPaused ? '继续更新' : '暂停更新'; renderLogs(); };
function collect() {
  return {
    app: {host: $('host').value.trim(), port: Number($('port').value), database: $('database').value.trim(), admin_token: $('admin-token').value},
    onebot: {self_id: $('self-id').value.trim(), admins: splitIds($('admins').value), token: $('onebot-token').value},
    features: Object.fromEntries(Object.keys(features).map(k => [k, $('feature-' + k).checked])),
    replies: saved.replies, // Retain the pre-migration backup; live replies belong to the plugin.
    servers: Array.from($('server-editors').children, readServer),
  };
}

function renderLiveView() {
  if (!latestStatus) return;
  const view = document.body.dataset.view, d = latestStatus;
  if (view === 'overview') {
    const servers = d.servers.map(s => [s.id,s.name,s.groups,s.online,(s.players || []).length,s.max_players]);
    renderChanged('overview-servers', servers, () => {
      $('servers-status').replaceChildren(...d.servers.map(s => {
        const row = node('div', '', 'server-status-row'), left = node('div', '', 'details');
        left.append(node('strong', s.name), node('p', '群 ' + (s.groups.join('、') || '未配置') + ' · ' + (s.online ? (s.players || []).length + '/' + s.max_players + ' 在线' : '桥接未连接'), 'muted'));
        row.append(node('span', '▤', 'server-tile'), left, node('span', s.online ? '在线' : '离线', 'pill ' + (s.online ? 'green' : 'dim'))); return row;
      }));
      if (!d.servers.length) $('servers-status').append(node('p', '尚未添加服务器，可在接入空间随时添加。', 'log-empty'));
    });
    renderLogs();
  } else if (view === 'connection') renderConnection();
  else if (view === 'logs') renderLogs();
  else if (view === 'bindings') renderBindings();
  else if (view === 'players') renderPlayers();
}
async function refresh() {
  if (busy || !token || saving) return;
  busy = true;
  try {
    const d = await api('/api/status');
    latestStatus = d;
    window.setCommunityFeatures(d.community_features);
    const hasAlerts = d.alerts_open > 0;
    setText('panel-alert-count', hasAlerts ? d.alerts_open + ' 项待处理故障' : '');
    $('panel-alert-count').hidden = !hasAlerts || !panelAllowed('monitoring');
    notice('notice', d.restart_error || '', d.restart_error ? 'error' : '', {persistent:true});
    setText('bot', d.onebot ? '已连接' : '等待连接'); $('bot').className = 'number ' + (d.onebot ? 'green' : 'dim');
    setText('self', d.onebot && d.self_id ? 'QQ ' + d.self_id : '等待机器人连接');
    setText('overview-refreshed', '最近刷新 ' + new Date().toLocaleTimeString());
    setText('server-count', d.servers.filter(s => s.online).length + ' / ' + d.servers.length);
    setText('binding-count', d.bindings.length); setText('uptime', Math.floor(d.uptime / 60) + ' 分钟');
    setText('group-count', new Set(d.servers.flatMap(s => s.groups)).size);
    setText('nav-server-count', d.servers.length); setText('nav-binding-count', d.bindings.length);
    $('top-status-dot').classList.toggle('online', d.onebot); setText('top-status-text', d.onebot ? '机器人已连接' : '机器人未连接');
    const selectedServer = $('binding-server').value;
    renderChanged('binding-server-options', [d.servers.map(s=>[s.id,s.name]), [...new Set(d.bindings.map(b=>b.server))]], () => {
      $('binding-server').replaceChildren(new Option('全部服务器', ''), ...d.servers.map(s => new Option(s.name, s.id)));
      for (const id of new Set(d.bindings.map(b => b.server))) if (!d.servers.some(s => s.id === id)) $('binding-server').append(new Option(id + '（历史）', id));
    });
    $('binding-server').value = selectedServer;
    renderLiveView();
    if (document.body.dataset.view === 'extensions') window.loadExtensions?.();
    if (document.body.dataset.view === 'authentication') window.loadAuthentication?.();
    if (document.body.dataset.view === 'backups') window.loadBackups?.();
    if (document.body.dataset.view === 'schedules') window.loadSchedules?.();
    if (document.body.dataset.view === 'whitelist') window.loadWhitelist?.();
    if (document.body.dataset.view === 'website') window.loadWebsite?.();
    if (document.body.dataset.view === 'accounts') window.loadRegistration?.();
    if (['monitoring','statistics'].includes(document.body.dataset.view)) window.loadEnhancements?.(document.body.dataset.view);
  } catch (e) { notice('notice', e.message + ' · 状态数据可能已过期。', 'error', {persistent:true}); }
  finally { busy = false; }
}
function startAutoRefresh() {
  clearInterval(timer); timer = null;
  if (token && !document.hidden) timer = setInterval(refresh, 5000);
}
document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopMotion();
  startAutoRefresh();
  if (!document.hidden && token) refresh();
});

async function enterPanel(accessToken) {
  token = accessToken;
  if (typeof token !== 'string' || !token) { token = ''; throw Error('登录响应无效，请重新登录。'); }
  try {
    panelIdentity=await api('/api/session');
    communityFeatures=Object.fromEntries(Object.entries(await api('/api/community-features')).map(([key,value])=>[key,value.settings.enabled]));
    if(panelIdentity.owner){const data=await api('/api/config');renderConfig(data);}
    $('login').hidden = $('owner-setup').hidden = true; $('content').hidden = false; $('save-bar').hidden = false; $('logout').hidden = false;
    $('page-actions').hidden = false; document.body.classList.remove('logged-out'); selectTab(location.hash.slice(1) || 'overview');
    $('panel-password').value='';panelAccess();setText('panel-user',panelIdentity.username);
    setText('panel-avatar', Array.from(panelIdentity.username || 'Myrinbot')[0].toUpperCase());
    await refresh(); startAutoRefresh();
  } catch (error) {
    try { await api('/api/admin-auth/logout',{method:'POST'}); } catch {}
    token = ''; panelIdentity = null; clearInterval(timer);
    document.body.classList.add('logged-out'); $('content').hidden = $('save-bar').hidden = $('logout').hidden = $('page-actions').hidden = true;
    $('owner-setup').hidden = true; $('login').hidden = false; setNavOpen(false);
    throw error;
  }
}
function setPanelAuthBusy(value) {
  panelAuthBusy = value;
  for (const id of ['login','owner-setup']) {
    $(id).setAttribute('aria-busy', String(value));
    for (const control of $(id).querySelectorAll('input,button')) control.disabled = value;
  }
}
async function checkOwnerSetup() {
  const result = await api('/api/admin-auth/setup');
  ownerSetupRequired = result.required === true;
  $('panel-setup-open').hidden = !ownerSetupRequired;
  return ownerSetupRequired;
}
function showPanelLogin() {
  $('owner-setup').hidden = true; $('login').hidden = false;
  $('owner-setup-form').reset(); notice('owner-setup-notice','');
  $('panel-username').focus();
}
$('panel-setup-open').onclick = () => {
  if (panelAuthBusy || !ownerSetupRequired) return;
  $('panel-password').value = ''; notice('login-notice','');
  $('login').hidden = true; $('owner-setup').hidden = false;
  $('owner-username').focus();
};
$('owner-setup-back').onclick = () => { if (!panelAuthBusy) showPanelLogin(); };
$('form').addEventListener('submit', async event => {
  event.preventDefault(); if (panelAuthBusy) return;
  const username = $('panel-username').value.trim(), password = $('panel-password').value;
  token = ''; panelIdentity = null; notice('login-notice',''); setPanelAuthBusy(true);
  $('panel-login-submit').textContent = '正在登录…';
  try {
    const result = await api('/api/admin-auth/login',{method:'POST',body:JSON.stringify({username,password})});
    await enterPanel(result.access_token);
  } catch (error) { notice('login-notice',error.message,'error',{persistent:true}); }
  finally { $('panel-password').value=''; setPanelAuthBusy(false); $('panel-login-submit').textContent='登录'; }
});
$('owner-setup-form').addEventListener('submit', async event => {
  event.preventDefault(); if (panelAuthBusy || !ownerSetupRequired) return;
  if ($('owner-password').value !== $('owner-password-confirm').value) {
    notice('owner-setup-notice','两次输入的密码不一致。','error',{persistent:true}); $('owner-password-confirm').focus(); return;
  }
  const username = $('owner-username').value.trim(), password = $('owner-password').value;
  const authorization = $('owner-authorization').value.trim();
  notice('owner-setup-notice',''); setPanelAuthBusy(true); $('owner-setup-submit').textContent='正在创建…';
  let created = false;
  try {
    const result = await api('/api/admin-auth/setup',{method:'POST',headers:{Authorization:'Bearer '+authorization},body:JSON.stringify({username,password})});
    created = true; ownerSetupRequired = false; $('panel-setup-open').hidden = true;
    $('owner-setup-form').reset(); $('panel-username').value = username;
    await enterPanel(result.access_token);
  } catch (error) {
    if (created) { showPanelLogin(); notice('login-notice','服主账号已创建，请使用新用户名和密码登录。'+error.message,'error',{persistent:true}); }
    else if (error.status === 409) {
      try { await checkOwnerSetup(); } catch {}
      if (!ownerSetupRequired) { showPanelLogin(); notice('login-notice',error.message,'error',{persistent:true}); }
      else notice('owner-setup-notice',error.message,'error',{persistent:true});
    } else notice('owner-setup-notice',error.message,'error',{persistent:true});
  } finally {
    $('owner-authorization').value = ''; setPanelAuthBusy(false); $('owner-setup-submit').textContent='创建服主账号';
  }
});
checkOwnerSetup().catch(() => notice('login-notice','暂时无法检查首次设置状态，请刷新页面重试。','error',{persistent:true}));
$('content').addEventListener('input', e => {
  if (e.target.matches('input,textarea') && e.target.type !== 'search' && !e.target.readOnly && e.target.dataset.field !== 'endpoint' && !e.target.closest('#view-players, #view-extensions, #view-accounts, #view-authentication, #view-backups, #view-schedules, #view-whitelist, #view-website, #view-managers, #view-monitoring, #view-statistics, .service-space')) markDirty();
});
document.querySelectorAll('[data-reveal]').forEach(btn => { btn.onclick = () => {
  const input = $(btn.dataset.reveal); input.type = input.type === 'password' ? 'text' : 'password'; btn.textContent = input.type === 'password' ? '显示' : '隐藏';
}; });
document.querySelectorAll('[data-generate]').forEach(btn => { btn.onclick = () => { $(btn.dataset.generate).value = randomToken(); markDirty(); }; });
document.querySelectorAll('[data-copy]').forEach(btn => { btn.onclick = () => copy($(btn.dataset.copy).value); });
$('add-server').onclick = () => { addServer({id: '', name: '', token: randomToken(), groups: [], commands: {}}); markDirty(); };
$('save-top').onclick = () => $('save').click();
$('reload-top').onclick = () => $('reload').click();
$('reload').onclick = async () => {
  if (dirty && !confirm('重新载入会丢弃尚未保存的更改，是否继续？')) return;
  try { renderConfig(await api('/api/config')); notice('save-notice', '已载入最新配置。', 'success'); }
  catch (e) { notice('save-notice', e.message, 'error'); }
};
$('save').onclick = async () => {
  if (saving) return;
  saving = true; $('save').disabled = true; $('save').textContent = '正在保存…';
  $('connection-save').textContent = '正在保存…';
  $('connection-dialog').setAttribute('aria-busy', 'true');
  // Lock editing while sending so a late response cannot overwrite newer input.
  const controls = [...$('content').querySelectorAll('input,textarea,button,select'), $('reload'), $('reload-top'), $('save-top')];
  const disabled = controls.map(el => el.disabled); controls.forEach(el => { el.disabled = true; });
  try {
    const cfg = collect();
    const data = await api('/api/config', {method: 'PUT', body: JSON.stringify({config: cfg, revision})});
    renderConfig(data);
    notice('save-notice', '设置已保存。' + (data.restart_required.length ? '监听地址、端口或数据库更改将在重启后生效。' : '业务设置已立即生效。') + (data.onebot_reconnect ? '请同步 QQ 实现端令牌或账号设置，等待重新连接。' : ''), 'success');
  } catch (e) { notice($('connection-dialog').open ? 'connection-dialog-notice' : 'save-notice', e.message, 'error'); }
  finally {
    controls.forEach((el, i) => { el.disabled = disabled[i]; });
    saving = false; $('save').textContent = '保存全部设置'; $('connection-save').textContent = '保存全部设置';
    $('connection-dialog').removeAttribute('aria-busy'); markDirty(dirty); filterCommandCards(); await refresh();
  }
};
$('restart').onclick = async () => {
  if (dirty) { notice('save-notice', '请先保存或重新载入设置，再重启主程序。', 'error'); return; }
  $('restart').disabled = true;
  try {
    await api('/api/restart', {method: 'POST'});
    const url = new URL(location.origin);
    const host = ['0.0.0.0', '::'].includes(saved.app.host) ? location.hostname : saved.app.host;
    url.hostname = host.includes(':') && !host.startsWith('[') ? '[' + host + ']' : host;
    url.port = String(saved.app.port);
    notice('restart-result', '正在重启，QQ 和游戏插件将自动重新连接。', '', {persistent:true});
    if (url.origin !== location.origin) {
      $('restart-result').append(node('p', '连接地址已更改，请打开新面板并使用用户名和密码登录：'));
      const a = node('a', url.origin, 'link'); a.href = url.origin; a.target = '_blank'; a.rel = 'noopener'; $('restart-result').append(a);
    } else {
      await new Promise(resolve => setTimeout(resolve, 1500));
      let connected = false;
      for (let attempt = 0; attempt < 20; attempt++) {
        try { const data = await api('/api/config'); renderConfig(data); notice('restart-result', data.restart_error || '重启完成，面板已重新连接。', data.restart_error ? 'error' : 'success'); connected = true; break; }
        catch { await new Promise(resolve => setTimeout(resolve, 1000)); }
      }
      if (!connected) notice('restart-result', '暂时无法重新连接，请稍后刷新面板。', 'error');
    }
  } catch (e) { notice('restart-result', e.message, 'error'); }
  finally { $('restart').disabled = !canRestart; }
};
$('logout').onclick = async () => { if (dirty && !confirm('有未保存的更改，确认退出？')) return; if ($('command-create-dialog').open) $('command-create-dialog').close(); try{await api('/api/admin-auth/logout',{method:'POST'});}catch{}dirty = false; token = ''; clearInterval(timer); location.reload(); };
