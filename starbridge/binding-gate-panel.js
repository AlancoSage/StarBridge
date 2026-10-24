'use strict';
(() => {
  let config = null, loading = false, working = false, draft = false, epoch = 0;
  const form = $('binding-gate-form');
  const message = $('binding-gate-message');
  const servers = $('binding-gate-servers');
  window.bindingGateHasDraft = () => draft || working;
  window.bindingGateBusy = () => working;

  function collect() {
    return {enabled_servers: [...servers.querySelectorAll('input:checked')].map(input => input.value).sort(), message: message.value.trim()};
  }
  function signature(settings) {
    return JSON.stringify({enabled_servers: [...settings.enabled_servers].sort(), message: settings.message.trim()});
  }
  function update() {
    draft = !!config && signature(collect()) !== signature(config.settings);
    $('binding-gate-save').disabled = !config || (!draft && !config.error) || working || loading;
    setText('binding-gate-save', config?.error ? '修复并保存设置' : '保存强制绑定设置');
    $('binding-gate-reload').disabled = working || loading;
    setText('binding-gate-draft', draft ? '强制绑定设置有尚未保存的更改。' : config?.error ? '请核对上方服务器开关，重新保存当前设置可修复读取错误。' : '单独保存，下一次连接时检查；不自动踢出当前在线玩家。');
  }
  function populate(data) {
    config = data;
    message.value = data.settings.message;
    servers.replaceChildren();
    const selected = new Set(data.settings.enabled_servers);
    const items = [...data.servers];
    for (const id of selected) if (!items.some(server => server.id === id)) items.push({id, name: id, missing: true, supported: false, online: false});
    for (const server of items) {
      const row = node('div', '', 'switch-row');
      const label = node('label');
      const input = node('input');
      input.id = 'binding-gate-server-' + server.id;
      input.type = 'checkbox'; input.value = server.id; input.setAttribute('role', 'switch');
      input.checked = selected.has(server.id);
      input.disabled = !input.checked && (!server.online || !server.supported || server.missing);
      label.htmlFor = input.id;
      label.append(node('strong', server.name));
      const status = server.missing ? '服务器已移除，可关闭现有设置' : !server.supported ? '需要支持强制绑定的 Paper / Spigot / Folia 游戏端' : !server.online ? '游戏端离线' : '已连接，支持进服前检查';
      const hint = node('p', server.id + ' · ' + status, 'hint');
      hint.id = input.id + '-hint'; input.setAttribute('aria-describedby', hint.id);
      label.append(hint); row.append(label, input); servers.append(row);
    }
    if (!items.length) servers.append(node('p', '还没有配置服务器，请先在「接入空间 → 服务器列表」添加。', 'hint'));
    setText('binding-gate-count', selected.size ? selected.size + ' 台已开启' : '默认关闭');
    notice('binding-gate-error', data.error || '', 'error', {persistent: true});
    update();
  }
  window.loadBindingGate = async (force = false) => {
    $('binding-gate-panel').hidden = !panelIdentity?.owner;
    if (!token || !panelIdentity?.owner || loading || working || saving || (draft && !force)) return;
    loading = true; update();
    const currentEpoch = epoch, accessToken = token;
    try {
      const data = await api('/api/binding-gate/settings');
      if (accessToken === token && panelIdentity?.owner && currentEpoch === epoch && !working && !saving && (!draft || force)
          && (force || !config || data.revision !== config.revision || data.error !== config.error || JSON.stringify(data.servers) !== JSON.stringify(config.servers))) populate(data);
    } catch (error) {
      if (accessToken === token && panelIdentity?.owner) notice('binding-gate-notice', error.message, 'error', {persistent: true});
    } finally { loading = false; update(); }
  };
  for (const type of ['input', 'change']) form.addEventListener(type, () => { epoch++; update(); });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!panelIdentity?.owner || !config || working || loading || saving || (!draft && !config.error)) return;
    working = true; epoch++; update();
    const controls = [...form.querySelectorAll('input,textarea,button')];
    const previousDisabled = controls.map(input => input.disabled);
    controls.forEach(input => { input.disabled = true; });
    const accessToken = token;
    notice('binding-gate-notice', '正在保存…', '', {persistent: true});
    try {
      const data = await api('/api/binding-gate/settings', {method: 'PUT', body: JSON.stringify({settings: collect(), revision: config.revision})});
      if (accessToken !== token || !panelIdentity?.owner) return;
      populate(data);
      notice('binding-gate-notice', '强制绑定设置已保存，下次连接时按该服务器的绑定检查。', 'success');
    } catch (error) {
      if (accessToken === token && panelIdentity?.owner) notice('binding-gate-notice', error.message, 'error', {persistent: true});
    } finally {
      controls.forEach((input, index) => { input.disabled = previousDisabled[index]; });
      working = false; update();
    }
  });
  $('binding-gate-reload').onclick = () => {
    if (!draft || confirm('放弃未保存的强制绑定设置并重新载入？')) window.loadBindingGate(true);
  };
})();
