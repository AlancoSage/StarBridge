'use strict';

/* The market installs local, validated JSON rules; it never loads remote code. */
(() => {
  const view = $('view-market'), dialog = $('market-dialog');
  if (!view || !dialog) return;
  let catalog = null, loading = false, working = false, generation = 0;
  let category = 'all', selected = null, selectionRevision = null;
  let originPluginId = null, lastLoadFailed = false;
  let cardSignature = '', categorySignature = '';
  const statusNames = {available: '可安装', installed: '已安装', update: '可更新', custom: '本地版本', error: '需要检查'};
  const iconPaths = {
    community_rules: ['M5 4h12a2 2 0 0 1 2 2v14H7a3 3 0 0 1-3-3V5a1 1 0 0 1 1-1Z', 'M4 16h15M8 8h7M8 11h5'],
    server_address: ['M6 9H5a4 4 0 0 0 0 8h5a4 4 0 0 0 4-4', 'M18 15h1a4 4 0 0 0 0-8h-5a4 4 0 0 0-4 4', 'm8 12 8 0'],
    online_digest: ['M3 7h18v13H3Z', 'M3 7V4h18v3M7 11h.01M7 16h.01M11 11h6M11 16h6'],
    binding_card: ['M3 5h18v14H3Z', 'M7 16a3 3 0 0 1 6 0M16 9h2M16 12h2', 'M11.8 9.5a1.8 1.8 0 1 1-3.6 0 1.8 1.8 0 0 1 3.6 0Z'],
    join_quit_notice: ['M13 3H5v18h8', 'M10 12h11m-4-4 4 4-4 4'],
    community_faq: ['M20 11a8 8 0 0 1-8 8H5l-3 3V11a9 9 0 0 1 18 0Z', 'M9.8 7.5a2.4 2.4 0 1 1 3.3 2.2c-.9.4-1.1 1-1.1 1.8M12 15h.01'],
    default: ['M4 4h6v6H4ZM14 4h6v6h-6ZM4 14h6v6H4ZM17 13v8m-4-4h8'],
    check: ['m5 12 4 4L19 6'],
    search: ['M15.5 10a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0ZM14 14l6 6'],
    warning: ['m12 3 10 18H2Z', 'M12 9v5m0 3h.01'],
  };

  function icon(id) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    for (const shape of iconPaths[id] || iconPaths.default) {
      const path = document.createElementNS(svg.namespaceURI, 'path');
      path.setAttribute('d', shape); svg.append(path);
    }
    return svg;
  }
  function categoryName(id) {
    return catalog?.categories.find(item => item.id === id)?.name || id || '社群扩展';
  }
  function canInstall(plugin) {
    return ['available', 'update'].includes(plugin?.status) && !catalog?.error && !lastLoadFailed;
  }
  function isInstalled(plugin) { return plugin.installed_version !== null && plugin.installed_version !== undefined; }
  function validateCatalog(data) {
    if (!data || !Array.isArray(data.plugins) || !Array.isArray(data.categories)
        || typeof data.revision !== 'string' || typeof data.catalog_revision !== 'string') {
      throw Error('插件目录暂时不可用，请刷新目录后重试。');
    }
    return data;
  }
  function readCatalog(data) {
    catalog = validateCatalog(data); lastLoadFailed = false;
    $('market-total').textContent = catalog.plugins.length;
    $('market-installed').textContent = catalog.plugins.filter(isInstalled).length;
    $('market-updates').textContent = catalog.plugins.filter(plugin => plugin.status === 'update').length;
    notice('market-state-error', catalog.error ? '插件状态需要修复，当前仅供浏览，暂不能安装或更新。' + catalog.error : '', 'error', {persistent: true});
    renderCategories(); renderCards();
  }
  function renderCategories() {
    const items = [{id: 'all', name: '全部插件'}, ...catalog.categories];
    if (!items.some(item => item.id === category)) category = 'all';
    const signature = JSON.stringify([items, category]);
    if (signature === categorySignature) return;
    categorySignature = signature;
    const focused = document.activeElement?.dataset.marketCategory;
    const controls = items.map(item => {
      const control = button(item.name, () => {
        category = item.id;
        for (const chip of $('market-categories').children) chip.setAttribute('aria-pressed', String(chip.dataset.marketCategory === category));
        categorySignature = '';
        renderCards();
      }, 'market-chip');
      control.dataset.marketCategory = item.id;
      control.setAttribute('aria-pressed', String(category === item.id));
      return control;
    });
    $('market-categories').replaceChildren(...controls);
    if (focused) controls.find(control => control.dataset.marketCategory === focused)?.focus({preventScroll: true});
  }
  function emptyState(title, description, kind = 'default', action = null) {
    const empty = node('div', '', 'market-empty'), graphic = icon(kind);
    graphic.classList.add('nav-icon');
    empty.append(graphic, node('h3', title), node('p', description));
    if (action) empty.append(button(action.label, action.run, 'secondary small'));
    $('market-list').replaceChildren(empty);
  }
  function filteredPlugins() {
    const query = $('market-search').value.trim().toLocaleLowerCase();
    const status = $('market-status').value;
    return catalog.plugins.filter(plugin => {
      if (category !== 'all' && plugin.category !== category) return false;
      if (status === 'installed' ? !isInstalled(plugin) : status !== 'all' && plugin.status !== status) return false;
      const haystack = [plugin.name, plugin.id, plugin.description, plugin.author, categoryName(plugin.category), ...(plugin.tags || []), ...(plugin.commands || [])].join(' ').toLocaleLowerCase();
      return !query || haystack.includes(query);
    });
  }
  function renderCards() {
    if (!catalog) return;
    const plugins = filteredPlugins();
    $('market-result-count').textContent = `共 ${catalog.plugins.length} 款精选插件${plugins.length !== catalog.plugins.length ? ` · 显示 ${plugins.length} 款` : ' · 本机可用'}`;
    const signature = JSON.stringify([plugins, catalog.categories, category, $('market-search').value, $('market-status').value]);
    if (signature === cardSignature) return;
    cardSignature = signature;
    const focused = document.activeElement?.closest('.market-card')?.dataset.pluginId;
    if (!plugins.length) {
      const filtered = category !== 'all' || $('market-search').value.trim() || $('market-status').value !== 'all';
      emptyState(filtered ? '没有找到匹配的插件' : '当前版本还没有可用插件', filtered ? '试试其他关键词，或清除筛选查看全部精选插件。' : '更新 VexBot 后，可在这里查看随版本提供的插件。', filtered ? 'search' : 'default', filtered ? {label: '清除筛选', run: clearFilters} : null);
      return;
    }
    const cards = plugins.map(plugin => {
      const card = node('article', '', 'market-card'); card.dataset.pluginId = plugin.id;
      const top = node('div', '', 'market-card-top'), graphic = node('div', '', 'market-plugin-icon'); graphic.append(icon(plugin.id));
      const badge = node('span', statusNames[plugin.status] || '本地版本', 'market-badge'); badge.dataset.status = plugin.status;
      top.append(graphic, badge);
      const meta = node('div', '', 'market-card-meta');
      meta.append(node('span', `v${plugin.version}`), node('span', plugin.author || 'VexBot'));
      const commands = node('div', '', 'market-card-command');
      if (plugin.commands?.length) {
        commands.append(node('code', plugin.commands[0], 'market-command'));
        if (plugin.commands.length > 1) commands.append(node('span', `+${plugin.commands.length - 1} 个命令`));
      } else commands.append(node('span', '事件触发 · 无需命令'));
      const footer = node('div', '', 'market-card-footer');
      const actionText = plugin.status === 'available' ? '查看与安装' : plugin.status === 'update' ? '查看更新' : '查看详情';
      const action = button(actionText, () => openDetail(plugin.id), 'secondary market-card-action');
      action.setAttribute('aria-label', actionText + '：' + plugin.name); action.append(node('span', '↗'));
      footer.append(node('span', categoryName(plugin.category), 'market-card-category'), action);
      card.append(top, node('h3', plugin.name), node('p', plugin.description, 'market-card-description'), meta, commands, footer);
      return card;
    });
    $('market-list').replaceChildren(...cards);
    if (focused && !dialog.open) cards.find(card => card.dataset.pluginId === focused)?.querySelector('button')?.focus({preventScroll: true});
  }
  function clearFilters() {
    category = 'all'; $('market-search').value = ''; $('market-status').value = 'all';
    renderCategories(); renderCards(); $('market-search').focus({preventScroll: true});
  }
  function detailSection(title) {
    const section = node('section', '', 'market-detail-section'); section.append(node('h3', title));
    $('market-detail-sections').append(section); return section;
  }
  function prose(section, text) {
    for (const paragraph of String(text || '').split(/\n\s*\n/)) if (paragraph.trim()) section.append(node('p', paragraph, 'market-detail-prose'));
  }
  function metaEntry(label, value, full = false) {
    const entry = node('div', '', full ? 'market-meta-full' : '');
    entry.append(node('dt', label), node('dd', value)); $('market-detail-meta').append(entry);
  }
  function renderDetail(plugin) {
    selected = plugin;
    selectionRevision = {revision: catalog.revision, catalog_revision: catalog.catalog_revision, sha256: plugin.sha256};
    $('market-detail-icon').replaceChildren(icon(plugin.id));
    $('market-detail-category').textContent = categoryName(plugin.category) + ' / ' + (statusNames[plugin.status] || '本地版本');
    $('market-detail-name').textContent = plugin.name;
    $('market-detail-description').textContent = plugin.description;
    $('market-detail-meta').replaceChildren();
    metaEntry('精选版本', 'v' + plugin.version);
    metaEntry('作者', plugin.author || 'VexBot');
    metaEntry('本机版本', isInstalled(plugin) ? 'v' + plugin.installed_version : '尚未安装');
    metaEntry('可配置项', `${plugin.settings_count || 0} 项`);
    metaEntry('插件标识', plugin.id);
    metaEntry('来源', 'VexBot 本机部署包 · 随版本更新');
    $('market-detail-sections').replaceChildren();
    prose(detailSection('功能介绍'), plugin.readme || plugin.description || '暂无详细介绍。');
    if (plugin.commands?.length) {
      const section = detailSection('触发命令'), list = node('div', '', 'market-command-list');
      for (const command of plugin.commands) list.append(node('code', command, 'market-command'));
      section.append(list);
    }
    if (plugin.capabilities?.length) {
      const section = detailSection('功能与权限'), list = node('ul', '', 'market-capability-list');
      for (const capability of plugin.capabilities) {
        const item = node('li'); item.append(icon('check'), node('span', capability)); list.append(item);
      }
      section.append(list);
    }
    prose(detailSection('更新说明'), plugin.changelog || '当前版本未提供更新说明。');
    if (plugin.status === 'custom') {
      $('market-detail-confirm').textContent = '这是本地版本，可能经过手动修改，市场不会覆盖。请在插件管理中检查设置与版本。';
    } else if (plugin.status === 'error') {
      $('market-detail-confirm').textContent = '本机插件需要检查。请前往插件管理查看错误并处理，市场不会覆盖当前文件。';
    } else if (plugin.status === 'installed') {
      $('market-detail-confirm').textContent = '此插件已安装。前往插件管理查看当前运行状态、设置、权限与版本回退。';
    } else if (plugin.status === 'update') {
      $('market-detail-confirm').textContent = '确认更新后，插件将保持停用，并保留兼容的设置与权限。检查后可在插件管理中启用，或回退旧版本。';
    } else {
      $('market-detail-confirm').textContent = '确认安装后，插件保持停用。请先在插件管理中检查设置与权限，再手动启用。';
    }
    updateDetailControls();
  }
  function updateDetailControls() {
    const action = $('market-detail-action');
    $('market-detail-close').disabled = working;
    $('market-detail-cancel').disabled = working;
    dialog.setAttribute('aria-busy', String(working));
    if (!selected) { action.disabled = true; return; }
    const installableStatus = ['available', 'update'].includes(selected.status);
    action.disabled = working || (installableStatus && !canInstall(selected));
    action.textContent = working ? (selected.status === 'update' ? '正在更新…' : '正在安装…')
      : selected.status === 'available' ? '安装并保持停用'
      : selected.status === 'update' ? '更新并保持停用' : '前往插件管理';
  }
  function openDetail(id) {
    if (working || !catalog || dialog.open) return;
    const plugin = catalog.plugins.find(item => item.id === id); if (!plugin) return;
    generation++; originPluginId = id;
    notice('market-detail-notice', ''); renderDetail(plugin);
    if (catalog.error) notice('market-detail-notice', '插件状态需要修复，暂不能安装或更新。请前往插件管理检查。', 'error', {persistent: true});
    else if (lastLoadFailed) notice('market-detail-notice', '当前目录未能刷新，请返回市场刷新成功后再安装或更新。', 'error', {persistent: true});
    dialog.showModal(); dialog.scrollTop = 0;
    $('market-detail-close').focus({preventScroll: true});
  }
  function closeDetail() { if (!working) dialog.close(); }
  window.loadExtensionMarket = async function(force = false) {
    if (!token || loading || working || dialog.open || (!force && view.hidden)) return;
    loading = true;
    const requestGeneration = generation;
    $('market-refresh').disabled = true; $('market-list').setAttribute('aria-busy', 'true');
    if (!catalog) emptyState('正在载入精选插件', '读取本机可用的插件目录…');
    try {
      const data = validateCatalog(await api('/api/extension-market'));
      if (requestGeneration !== generation || working || dialog.open) return;
      notice('market-notice', ''); readCatalog(data);
    } catch (error) {
      if (requestGeneration !== generation || working || dialog.open) return;
      lastLoadFailed = true;
      const accessError = error.status === 401 || error.status === 403;
      notice('market-notice', accessError ? error.message : '插件目录未能刷新：' + error.message, 'error', {persistent: true});
      if (!catalog) emptyState(accessError ? '暂时无法访问插件市场' : '插件目录暂时不可用', accessError ? '请确认登录状态，当前账号需要插件管理权限。' : '请稍后重试。已安装的插件不会受到影响。', 'warning', {label: '重新载入', run: () => window.loadExtensionMarket(true)});
    } finally {
      loading = false; $('market-refresh').disabled = working; $('market-list').setAttribute('aria-busy', 'false');
    }
  };
  async function installSelected() {
    if (working || !selected || !selectionRevision) return;
    if (!['available', 'update'].includes(selected.status)) { closeDetail(); selectTab('extensions'); return; }
    if (!canInstall(selected)) return;
    const pluginId = selected.id, operation = selected.status === 'update' ? 'upgrade' : 'install';
    const payload = {...selectionRevision};
    generation++; working = true; updateDetailControls(); $('market-refresh').disabled = true;
    notice('market-detail-notice', operation === 'upgrade' ? '正在更新本机插件…' : '正在安装本机插件…', '', {persistent: true});
    try {
      const data = validateCatalog(await api('/api/extension-market/' + encodeURIComponent(pluginId) + '/' + operation, {method: 'POST', body: JSON.stringify(payload)}));
      readCatalog(data);
      const installed = data.plugins.find(plugin => plugin.id === pluginId);
      if (installed) renderDetail(installed);
      else { selected = null; selectionRevision = null; }
      const message = operation === 'upgrade' ? '已更新，插件保持停用。请确认设置与权限后再启用。' : '已安装，插件保持停用。请确认设置与权限后再启用。';
      notice('market-detail-notice', message, 'success', {persistent: true});
      notice('market-notice', message, 'success', {persistent: true});
      window.loadExtensions?.(true);
    } catch (error) {
      if (error.status === 409) {
        try {
          readCatalog(await api('/api/extension-market'));
          const latest = catalog.plugins.find(plugin => plugin.id === pluginId);
          if (latest) renderDetail(latest); else { selected = null; selectionRevision = null; }
          notice('market-detail-notice', '目录或本机插件已发生变化，已重新载入。请核对最新详情后再确认操作。', 'error', {persistent: true});
        } catch (refreshError) {
          lastLoadFailed = true;
          notice('market-detail-notice', '目录或本机插件已发生变化，刷新失败：' + refreshError.message + ' 请返回市场刷新后再操作。', 'error', {persistent: true});
        }
      } else {
        // A failed response may follow a successful write. Require a fresh listing
        // rather than allowing a second click to repeat an uncertain operation.
        lastLoadFailed = true;
        notice('market-detail-notice', error.message + (error.status === 401 || error.status === 403 ? ' 请确认登录状态与插件管理权限。' : ' 请返回市场刷新目录，确认本机状态后再操作。'), 'error', {persistent: true});
      }
    } finally {
      working = false; $('market-refresh').disabled = loading; updateDetailControls();
    }
  }
  $('market-search').addEventListener('input', renderCards);
  $('market-status').addEventListener('change', renderCards);
  $('market-refresh').onclick = () => window.loadExtensionMarket(true);
  $('market-detail-close').onclick = $('market-detail-cancel').onclick = closeDetail;
  $('market-detail-action').onclick = installSelected;
  dialog.addEventListener('cancel', event => { if (working) event.preventDefault(); });
  dialog.addEventListener('keydown', event => trapFocus(dialog, event));
  dialog.addEventListener('close', () => {
    selected = null; selectionRevision = null;
    if (!view.hidden) {
      const source = [...$('market-list').querySelectorAll('.market-card')].find(card => card.dataset.pluginId === originPluginId)?.querySelector('button');
      (source || $('market-search')).focus({preventScroll: true});
    }
    originPluginId = null;
  });
  dialog.addEventListener('click', event => {
    if (event.target !== dialog || working) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeDetail();
  });
  if (token && !view.hidden) window.loadExtensionMarket();
})();
