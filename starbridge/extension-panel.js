'use strict';
let extensionData = null, extensionLoading = false, extensionBusy = false;
let extensionCurrent = null, extensionDraft = false;
let extensionGeneration = 0, extensionDialogRevision = '';
let extensionPermissionMode = false;
window.extensionHasDraft = () => extensionDraft;
const extensionStatus = {running: '已启用', disabled: '已停用', error: '需要检查'};
const extensionEvents = {group_command: '群命令', player_join: '入服通知', player_quit: '退服通知', keyword_reply: '整条消息匹配'};

function renderExtensions(data) {
  extensionData = data;
  notice('extension-state-error', data.error || '', 'error', {persistent:true});
  renderChanged('extensions', data.plugins, () => {
    $('extension-list').replaceChildren();
    for (const plugin of data.plugins) {
      const card = node('article', '', 'extension-card'); card.dataset.pluginId = plugin.id;
      const head = node('div', '', 'section-head'), identity = node('div');
      identity.append(node('h3', plugin.name), node('p', `${plugin.id} · ${plugin.version || '版本未知'}${plugin.author ? ' · '+plugin.author : ''}`, 'hint'));
      head.append(identity, node('span', extensionStatus[plugin.status], 'pill '+(plugin.status === 'running' ? 'green' : '')));
      card.append(head, node('p', plugin.description || '这个插件没有填写介绍。', 'muted'));
      const rules = node('div', '', 'extension-rules');
      for (const rule of plugin.rules) rules.append(node('span', (rule.command || extensionEvents[rule.event]) + (rule.admin_only ? ' · 管理员' : rule.bound_only ? ' · 已绑定' : ''), 'tag'));
      card.append(rules);
      if (plugin.id==='keyword_replies') rules.append(node('span', `内置 · ${Object.keys(plugin.settings.replies).length} 条回复`, 'tag'));
      else if(plugin.builtin) rules.append(node('span', '内置 · 公告 / 命令 / 备份', 'tag'));
      if (plugin.error) card.append(node('p', plugin.error, 'extension-error'));
      const actions = node('div', '', 'extension-actions');
      if (plugin.status !== 'error') {
        actions.append(button(plugin.enabled ? '停用' : '启用', () => extensionMutation('/api/extensions/'+plugin.id, 'PUT', {enabled: !plugin.enabled, settings: plugin.settings}), plugin.enabled ? 'secondary small' : 'small'));
        if(plugin.id==='scheduled_tasks'){
          if(panelAllowed('schedules'))actions.append(button('管理任务',()=>selectTab('schedules')));
          else actions.append(node('span','管理任务需定时任务权限','hint'));
        }else actions.append(button(plugin.id==='keyword_replies' ? '管理回复' : '设置', () => openExtensionSettings(plugin)));
        actions.append(button('权限', () => openExtensionSettings(plugin, true)));
      }
      if (!plugin.builtin) {
        actions.append(button('版本与回退', () => openPluginVersions(plugin)));
        actions.append(button('重新加载', () => extensionMutation('/api/extensions/'+plugin.id+'/reload', 'POST')));
        if (!plugin.enabled) actions.append(button('移除', () => extensionMutation('/api/extensions/'+plugin.id, 'DELETE'), 'danger small'));
      }
      card.append(actions); $('extension-list').append(card);
    }
    if (!data.plugins.length) $('extension-list').append(node('p', '还没有插件，下载示例或导入一个 JSON 插件开始吧。', 'log-empty'));
  });
}
window.loadExtensions = async function(force = false) {
  if (!token || extensionLoading || extensionBusy || (!force && $('extension-dialog').open)) return;
  extensionLoading = true;
  const generation = extensionGeneration;
  try {
    const data = await api('/api/extensions');
    if (generation === extensionGeneration && !extensionBusy) renderExtensions(data);
  }
  catch (error) { notice('extension-notice', error.message, 'error'); }
  finally { extensionLoading = false; }
};
async function extensionMutation(url, method, payload = {}) {
  if (extensionBusy || !extensionData) return false;
  extensionBusy = true;
  extensionGeneration++;
  const controls = [...$('view-extensions').querySelectorAll('button,input'), ...$('extension-dialog').querySelectorAll('button,input,select,textarea')];
  const disabled = controls.map(el => el.disabled); controls.forEach(el => el.disabled = true);
  const target = $('extension-dialog').open ? 'extension-dialog-notice' : 'extension-notice';
  notice(target, '正在应用…', '', {persistent:true});
  try {
    const data = await api(url, {method, body: JSON.stringify({revision: extensionData.revision, ...payload})});
    renderExtensions(data);
    notice(target, '已应用。', 'success');
    return true;
  } catch (error) {
    notice(target, error.message, 'error');
    return false;
  } finally {
    controls.forEach((el, index) => el.disabled = disabled[index]); extensionBusy = false;
  }
}
function closeExtensionSettings() {
  if (extensionBusy) return;
  if (extensionDraft && !confirm('插件设置尚未保存，确定放弃修改？')) return;
  extensionDraft = false; $('extension-dialog').close();
}
function openExtensionSettings(plugin, permissions = false) {
  if (extensionBusy) return;
  extensionGeneration++;
  extensionDialogRevision = extensionData.revision;
  extensionCurrent = plugin; extensionDraft = false;
  extensionPermissionMode = permissions;
  $('extension-dialog').classList.toggle('keyword-dialog', !!plugin.builtin);
  $('extension-title').textContent = plugin.name + (permissions ? ' · 权限' : '');
  $('extension-subtitle').textContent = plugin.enabled ? '保存后立即生效' : '保存设置后，可在列表中启用插件';
  $('extension-settings').replaceChildren(); notice('extension-dialog-notice', '');
  if (permissions) {
    openExtensionPermissions(plugin.permissions);
    $('extension-save').textContent = '保存插件权限';
    $('extension-dialog').showModal(); return;
  }
  $('extension-save').textContent = '保存插件设置';
  for (const [key, spec] of Object.entries(plugin.schema)) {
    if (spec.type === 'reply_map') {
      openKeywordEditor(plugin.settings[key]);
      continue;
    }
    const wrap = node('div', '', 'field'+(spec.type === 'string' ? ' full' : ''));
    const label = node('label', spec.label), id = 'extension-setting-'+key;
    let input;
    if (spec.type === 'select') {
      input = node('select'); input.append(...spec.options.map(value => new Option(value, value))); input.value = plugin.settings[key];
    } else if (spec.type === 'boolean') {
      input = node('input'); input.type = 'checkbox'; input.checked = plugin.settings[key]; wrap.classList.add('extension-check');
    } else {
      input = node(spec.type === 'string' ? 'textarea' : 'input');
      if (spec.type !== 'string') {
        input.type = 'number'; input.min = spec.min ?? -1e9; input.max = spec.max ?? 1e9; input.step = spec.type === 'integer' ? '1' : 'any'; input.required = true;
      } else input.maxLength = spec.max_length ?? 2000;
      input.value = plugin.settings[key];
    }
    input.id = id; input.dataset.extensionSetting = key; label.htmlFor = id;
    wrap.append(label, input); if (spec.description) wrap.append(node('p', spec.description, 'hint'));
    $('extension-settings').append(wrap);
  }
  if (!Object.keys(plugin.schema).length) $('extension-settings').append(node('p', '这个插件没有可调整的设置。', 'muted'));
  $('extension-dialog').showModal();
}
$('extension-form').addEventListener('input', event => { if (event.target.type !== 'search') extensionDraft = true; });
$('extension-form').addEventListener('change', () => { extensionDraft = true; });
$('extension-form').onsubmit = async event => {
  event.preventDefault();
  let settings;
  try {
    settings = extensionPermissionMode ? extensionCurrent.settings : Object.fromEntries(Object.entries(extensionCurrent.schema).map(([key, spec]) => {
      if (spec.type === 'reply_map') return [key, pairs($('reply-editors'))];
      const input = $('extension-setting-'+key);
      return [key, spec.type === 'boolean' ? input.checked : ['integer','number'].includes(spec.type) ? Number(input.value) : input.value];
    }));
  } catch (error) { notice('extension-dialog-notice', error.message, 'error'); return; }
  const permissions = extensionPermissionMode ? collectExtensionPermissions() : extensionCurrent.permissions;
  if (await extensionMutation('/api/extensions/'+extensionCurrent.id, 'PUT', {revision: extensionDialogRevision, enabled: extensionCurrent.enabled, settings, permissions})) {
    extensionDraft = false; $('extension-dialog').close(); notice('extension-notice', extensionPermissionMode ? '插件权限已保存。' : '插件设置已保存。', 'success');
  }
};

function openExtensionPermissions(policy) {
  const scheduled=extensionCurrent.id==='scheduled_tasks';
  const wrap = node('div','','full permission-editor'),grid=node('div','','grid');
  wrap.append(node('p',scheduled?'每次执行都会检查动作权限和目标范围，包括立即执行。游戏命令还必须在服务器预设命令列表中。':'限制会立即生效。权限与插件规则同时满足时才响应；QQ 拒绝名单优先，不会被允许名单或管理员身份绕过。','hint'));
  const flags=scheduled?{send_group:'允许发送群公告',send_game:'允许发送游戏公告',execute_commands:'允许执行预设命令',create_backups:'允许创建备份'}:{send_group:'允许发送群消息',group_commands:'允许群命令 / 关键词回复',game_events:'允许游戏进退服通知',read_bindings:'允许读取绑定玩家名',read_server:'允许读取在线人数、玩家列表与状态'};
  for(const [key,label] of Object.entries(flags)){
    const field=node('div','','field extension-check'),caption=node('label',label),input=node('input');input.type='checkbox';input.id='permission-'+key;input.checked=policy[key];caption.prepend(input);field.append(caption);grid.append(field);
  }
  if(!scheduled){const modeField=node('div','','field'),modeLabel=node('label','允许使用者'),mode=node('select');mode.id='permission-user_mode';modeLabel.htmlFor=mode.id;mode.append(new Option('所有成员','all'),new Option('已绑定成员','bound'),new Option('机器人管理员','admins'));mode.value=policy.user_mode;modeField.append(modeLabel,mode);grid.append(modeField);}
  for(const [key,label,hint] of [['servers','允许的服务器 ID','留空允许所有服务器；多个 ID 用空格或逗号分隔。'],['groups','允许的 QQ 群','留空允许所有关联群。只在服务器关联群内生效。'],['allow_users','允许的 QQ 号','留空不额外限制；填写后只有名单内 QQ 可以使用。'],['deny_users','拒绝的 QQ 号','名单内 QQ 始终无法使用群命令或关键词回复。']]){
    if(scheduled&&['allow_users','deny_users'].includes(key))continue;
    const field=node('div','','field full'),caption=node('label',label),input=node('input');input.id='permission-'+key;caption.htmlFor=input.id;input.value=policy[key].join(', ');input.maxLength=4100;input.placeholder=hint;field.append(caption,input,node('p',hint,'hint'));grid.append(field);
  }
  wrap.append(grid,node('p',scheduled?'服务器范围用于公告和命令，群范围用于群公告；备份由单独的动作权限控制。任务管理仍需要面板的定时任务权限。':'使用者和 QQ 名单限制针对群命令。游戏通知依据服务器、群和通知权限执行。这里的授权只开放声明式规则能力。','hint'));$('extension-settings').append(wrap);
}
function collectExtensionPermissions(){
  const out={...extensionCurrent.permissions};for(const key of ['send_group','group_commands','game_events','read_bindings','read_server','send_game','execute_commands','create_backups'])if($('permission-'+key))out[key]=$('permission-'+key).checked;
  if($('permission-user_mode'))out.user_mode=$('permission-user_mode').value;
  for(const key of ['servers','groups','allow_users','deny_users'])if($('permission-'+key))out[key]=$('permission-'+key).value.trim().split(/[\s,，]+/).filter(Boolean);
  return out;
}

function filterKeywordEditor() {
  const cards = [...$('reply-editors').children], query = $('reply-search').value.trim().toLocaleLowerCase();
  let visible = 0;
  for (const card of cards) {
    const text = [...card.querySelectorAll('input,textarea')].map(el => el.value).join(' ').toLocaleLowerCase();
    card.hidden = !!query && !text.includes(query);
    if (!card.hidden) visible++;
  }
  $('reply-total').textContent = query ? `匹配 ${visible} / ${cards.length} 项` : `共 ${cards.length} / 200 条回复`;
  $('add-reply').disabled = cards.length >= 200;
  $('reply-empty').hidden = cards.length > 0;
}
function addKeywordReply(key = '', value = '') {
  addPair($('reply-editors'), key, value, true, () => { extensionDraft = true; filterKeywordEditor(); });
  const row = $('reply-editors').lastElementChild;
  row.querySelector('[data-field="key"]').maxLength = 80;
  row.querySelector('[data-field="value"]').maxLength = 3500;
}
function openKeywordEditor(replies) {
  const wrap = node('div', '', 'full keyword-editor'), toolbar = node('div', '', 'toolbar');
  const search = node('input'); search.id = 'reply-search'; search.type = 'search';
  search.placeholder = '搜索关键词或回复内容…'; search.setAttribute('aria-label', '搜索关键词回复');
  search.oninput = filterKeywordEditor;
  const total = node('span', '', 'count'); total.id = 'reply-total';
  const add = button('＋ 添加回复', () => {
    if ($('reply-editors').children.length >= 200) return;
    search.value = ''; addKeywordReply(); extensionDraft = true; filterKeywordEditor();
    $('reply-editors').lastElementChild.querySelector('input').focus();
  }); add.id = 'add-reply';
  toolbar.append(search, total, add);
  const editors = node('div', '', 'reply-grid'); editors.id = 'reply-editors';
  const empty = node('p', '还没有关键词，添加一条回复开始吧。', 'log-empty'); empty.id = 'reply-empty';
  wrap.append(node('p', '精确匹配整条群消息；回复以纯文字发送。帮助、绑定、状态等内置命令优先。', 'hint'), toolbar, editors, empty);
  $('extension-settings').append(wrap);
  for (const [key, value] of Object.entries(replies)) addKeywordReply(key, value);
  editors.addEventListener('input', filterKeywordEditor);
  filterKeywordEditor();
}
$('extension-close').onclick = closeExtensionSettings; $('extension-cancel').onclick = closeExtensionSettings;
$('extension-dialog').addEventListener('cancel', event => { event.preventDefault(); closeExtensionSettings(); });
$('extension-refresh').onclick = () => window.loadExtensions(true);
$('extension-scan').onclick = () => extensionMutation('/api/extensions/scan', 'POST');
$('extension-import').onclick = () => $('extension-file').click();
$('extension-file').onchange = async () => {
  const file = $('extension-file').files[0];
  if (!file) return;
  try {
    if (file.size > 64*1024) throw Error('插件 JSON 不能超过 64 KiB。');
    const plugin = JSON.parse((await file.text()).replace(/^\uFEFF/, ''));
    const previous=extensionData?.plugins.find(item=>item.id===plugin.id);
    if(previous){
      if(!confirm('更新 '+previous.name+'：'+previous.version+' → '+plugin.version+'？旧版本会保留，更新后插件保持停用。\n'+(plugin.changelog||'此版本没有填写更新说明。')))return;
      await extensionMutation('/api/extensions/upgrade','POST',{plugin});
    }else await extensionMutation('/api/extensions/install', 'POST', {plugin});
  } catch (error) { notice('extension-notice', '导入失败：'+error.message, 'error'); }
  finally { $('extension-file').value = ''; }
};
async function extensionDownload(document, filename) {
  try {
    const response = await fetch('/api/extension-documents/'+document, {headers:{Authorization:'Bearer '+token}, cache:'no-store', signal:AbortSignal.timeout(10000)});
    if (!response.ok) throw Error('下载失败，请检查登录状态。');
    const url = URL.createObjectURL(await response.blob()), link = node('a');
    link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { notice('extension-notice', error.message, 'error'); }
}
$('extension-example').onclick = () => extensionDownload('example', 'community_helper.json');
$('extension-guide').onclick = () => extensionDownload('guide', 'StarBridge-plugin-development.md');
async function openPluginVersions(plugin){
  try{const data=await api('/api/extensions/'+plugin.id+'/versions');$('plugin-version-title').textContent=plugin.name+' · '+plugin.version;$('plugin-version-changelog').textContent=plugin.changelog||'当前版本未填写更新说明。';$('plugin-version-list').replaceChildren(...data.versions.map(version=>{const row=node('article','','operation-history-row'),left=node('div');left.append(node('strong',version.version),node('p',new Date(version.created*1000).toLocaleString()+' · '+(version.note||'保存的旧版本'),'hint'));const rollback=button('回退到此版本',async()=>{if(!confirm('回退到 '+version.version+'？回退后插件保持停用，请确认设置后启用。'))return;if(await extensionMutation('/api/extensions/'+plugin.id+'/rollback','POST',{version_id:version.id}))$('plugin-version-dialog').close();});rollback.disabled=version.version===plugin.version;row.append(left,rollback);return row;}));if(!data.versions.length)$('plugin-version-list').append(node('p','更新插件时会自动保存旧版本，最多保留 5 个。','hint'));$('plugin-version-dialog').showModal();}catch(error){notice('extension-notice',error.message,'error');}
}
$('plugin-version-close').onclick=()=>$('plugin-version-dialog').close();
