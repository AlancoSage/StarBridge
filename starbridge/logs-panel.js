'use strict';

/* A bounded, local view of the current process's log stream. Messages are text, never markup. */
(() => {
  const find = id => document.getElementById('runtime-log-' + id);
  const panel = find('panel'), view = document.getElementById('view-logs');
  if (!panel || !view) return;
  const viewport = find('viewport'), lines = find('lines');
  const levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];
  const preferencesKey = 'starbridge.panel.runtime-logs';
  let entries = [], instance = null, cursor = null, capacity = 1000;
  let paused = false, following = true, blocked = false, clearSnapshot = false;
  let request = null, timer = null, timeout = null, generation = 0, failures = 0, nextAt = 0;
  let sessionToken = null, expanded = false, visibleEntries = [], renderedIds = '';
  let lastScrollTop = 0, pendingScroll = null, feedbackTimer = null, lastSourceSignature = '', noteKind = '';
  const rows = new Map();

  function text(value) {
    // ANSI control sequences are irrelevant in a browser and must not leak into exports.
    return String(value ?? '').replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '')
      .replace(/(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]/g, '')
      .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, '');
  }
  function make(tag, content, className) {
    const element = document.createElement(tag); element.textContent = content;
    if (className) element.className = className;
    return element;
  }
  function currentToken() { return typeof token === 'string' ? token : ''; }
  function eligible() {
    return document.body.dataset.view === 'logs' && !document.hidden
      && !document.body.classList.contains('logged-out') && !view.hidden;
  }
  function status(state, message) {
    find('status').dataset.state = state; find('status').textContent = message;
  }
  function feedback(message) {
    clearTimeout(feedbackTimer); find('action-status').textContent = message;
    feedbackTimer = setTimeout(() => { find('action-status').textContent = ''; }, 5000);
  }
  function note(message, kind = '') {
    noteKind = kind;
    find('note').textContent = message; find('note').hidden = !message;
  }
  function savePreferences() {
    try {
      localStorage.setItem(preferencesKey, JSON.stringify({font: find('font').value, wrap: panel.dataset.wrap === 'true'}));
    } catch {}
  }
  function renderPreferences() {
    const font = ['10', '12', '14', '16'].includes(find('font').value) ? find('font').value : '12';
    panel.style.setProperty('--runtime-log-font', font + 'px');
    find('wrap').setAttribute('aria-pressed', panel.dataset.wrap);
    find('follow').setAttribute('aria-pressed', String(following));
    find('pause').setAttribute('aria-pressed', String(paused));
    find('pause').textContent = paused ? '继续接收' : '暂停接收';
    find('latest').hidden = following || !visibleEntries.length;
  }
  try {
    const saved = JSON.parse(localStorage.getItem(preferencesKey) || 'null');
    if (saved && ['10', '12', '14', '16'].includes(String(saved.font))) find('font').value = String(saved.font);
    if (typeof saved?.wrap === 'boolean') panel.dataset.wrap = String(saved.wrap);
  } catch {}

  function timeText(time) {
    const date = new Date(Number(time) * 1000);
    if (!Number.isFinite(date.getTime())) return {short: '--:--:--', full: '未知时间'};
    return {short: date.toLocaleTimeString('zh-CN', {hour12: false}) + '.' + String(date.getMilliseconds()).padStart(3, '0'), full: date.toLocaleString('zh-CN', {hour12: false})};
  }
  function rowFor(entry) {
    let row = rows.get(entry.id);
    if (row) return row;
    const date = timeText(entry.time);
    row = make('div', '', 'runtime-log-row');
    row.dataset.id = String(entry.id); row.dataset.level = entry.level; row.dataset.source = entry.source;
    const time = make('time', date.short, 'runtime-log-time'); time.title = date.full;
    const parsedDate = new Date(Number(entry.time) * 1000);
    if (Number.isFinite(parsedDate.getTime())) time.dateTime = parsedDate.toISOString();
    const level = make('span', entry.level, 'runtime-log-level');
    const source = make('span', entry.source, 'runtime-log-source'); source.title = entry.source;
    const message = make('pre', entry.message, 'runtime-log-message');
    row.append(time, level, source, message); rows.set(entry.id, row);
    return row;
  }
  function anchor() {
    const top = viewport.getBoundingClientRect().top;
    for (const row of lines.children) {
      const bounds = row.getBoundingClientRect();
      if (bounds.bottom > top) return {id: row.dataset.id, offset: bounds.top - top};
    }
    return null;
  }
  function scrollToEnd() {
    if (pendingScroll) cancelAnimationFrame(pendingScroll);
    viewport.scrollTop = viewport.scrollHeight; lastScrollTop = viewport.scrollTop;
    pendingScroll = requestAnimationFrame(() => {
      pendingScroll = null;
      if (following) { viewport.scrollTop = viewport.scrollHeight; lastScrollTop = viewport.scrollTop; }
    });
  }
  function updateSources() {
    const selected = find('source').value;
    const sources = [...new Set(entries.map(entry => entry.source))];
    if (selected && !sources.includes(selected)) sources.push(selected);
    sources.sort((left, right) => left.localeCompare(right));
    const signature = JSON.stringify(sources);
    if (signature === lastSourceSignature) return;
    lastSourceSignature = signature;
    const options = [new Option('全部来源', ''), ...sources.map(source => new Option(source, source))];
    find('source').replaceChildren(...options); find('source').value = selected;
  }
  function render(force = false) {
    const query = find('search').value.trim().toLocaleLowerCase();
    const level = find('level').value, source = find('source').value;
    visibleEntries = entries.filter(entry => (!level || entry.level === level) && (!source || entry.source === source)
      && (!query || (entry.message + '\n' + entry.source + '\n' + entry.level).toLocaleLowerCase().includes(query)));
    const ids = visibleEntries.map(entry => entry.id).join(',');
    if (force || ids !== renderedIds) {
      const preserved = following ? null : anchor();
      const oldHeight = viewport.scrollHeight, oldTop = viewport.scrollTop;
      const wanted = new Set(visibleEntries.map(entry => String(entry.id)));
      for (const child of [...lines.children]) if (!wanted.has(child.dataset.id)) child.remove();
      let reference = lines.firstChild;
      for (const entry of visibleEntries) {
        const row = rowFor(entry);
        if (row !== reference) lines.insertBefore(row, reference);
        reference = row.nextSibling;
      }
      renderedIds = ids;
      find('empty').hidden = visibleEntries.length > 0;
      if (following) scrollToEnd();
      else if (preserved) {
        const target = [...lines.children].find(row => row.dataset.id === preserved.id);
        viewport.scrollTop = target ? viewport.scrollTop + target.getBoundingClientRect().top - viewport.getBoundingClientRect().top - preserved.offset
          : Math.max(0, oldTop + viewport.scrollHeight - oldHeight);
      }
      lastScrollTop = viewport.scrollTop;
    }
    find('empty').hidden = visibleEntries.length > 0;
    find('empty-title').textContent = entries.length ? '没有匹配的日志' : clearSnapshot ? '已清空当前视图' : '等待新日志';
    find('empty-description').textContent = entries.length ? '调整关键词、等级或来源筛选，查看其他日志。'
      : paused ? '接收已暂停，继续接收后显示新的运行记录。' : '这里仅显示当前进程保留的日志，新记录会自动出现。';
    find('count').textContent = `显示 ${visibleEntries.length.toLocaleString()} / 已载入 ${entries.length.toLocaleString()} 条 · 缓存上限 ${capacity.toLocaleString()}`;
    find('copy').disabled = find('download').disabled = !visibleEntries.length;
    find('latest').hidden = following || !visibleEntries.length;
  }
  function ingest(data, skipEntries) {
    if (!data || typeof data.instance_id !== 'string' || !Number.isSafeInteger(data.cursor) || !Array.isArray(data.entries)) {
      throw Error('日志响应格式异常');
    }
    const changedInstance = instance !== null && instance !== data.instance_id;
    if (changedInstance || data.reset) {
      entries = []; rows.clear(); lines.replaceChildren(); renderedIds = '';
      note('服务已重新启动，已切换到新进程的日志。');
    } else if (data.truncated) {
      note('暂停或离线期间的部分旧日志已超出缓存范围，已从当前可用记录继续。');
    }
    instance = data.instance_id; cursor = data.cursor;
    capacity = Math.min(1000, Math.max(1, Number(data.capacity) || 1000));
    find('capture').textContent = `采集 ${levels.includes(data.capture_level) ? data.capture_level : 'INFO'} 及以上`;
    if (!skipEntries) {
      const known = new Set(entries.map(entry => entry.id));
      for (const incoming of data.entries) {
        if (!Number.isSafeInteger(incoming.id) || known.has(incoming.id)) continue;
        entries.push({id: incoming.id, time: incoming.time, level: levels.includes(incoming.level) ? incoming.level : 'INFO',
          source: text(incoming.source) || 'root', message: text(incoming.message)});
        known.add(incoming.id);
      }
      entries.sort((left, right) => left.id - right.id);
      if (entries.length > capacity) entries.splice(0, entries.length - capacity);
    }
    const retained = new Set(entries.map(entry => entry.id));
    for (const id of rows.keys()) if (!retained.has(id)) rows.delete(id);
    updateSources(); render();
    return data.entries.length;
  }
  function cancelRequest() {
    generation += 1;
    clearTimeout(timer); clearTimeout(timeout); timer = timeout = null;
    request?.abort(); request = null;
  }
  function schedule(delay) {
    if (!eligible() || paused || blocked || timer !== null || request) return;
    nextAt = Date.now() + Math.max(0, delay);
    timer = setTimeout(() => { timer = null; poll(); }, Math.max(0, delay));
  }
  async function poll(boundaryOnly = false) {
    // Clearing is an explicit action: a single snapshot may establish its boundary even while paused.
    if (!eligible() || (paused && !boundaryOnly) || blocked || request) return;
    const epoch = generation, initial = cursor === null || clearSnapshot;
    const skipEntries = clearSnapshot;
    const controller = new AbortController(); request = controller;
    let timedOut = false;
    timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 10000);
    if (!boundaryOnly && (instance === null || failures)) status('connecting', failures ? '正在重新连接…' : '正在连接…');
    const parameters = new URLSearchParams({limit: '500'});
    if (!initial) { parameters.set('after', String(cursor)); parameters.set('instance', instance); }
    let delay = 1000;
    try {
      const data = await api('/api/logs?' + parameters, {signal: controller.signal});
      if (epoch !== generation || !eligible() || (paused && !boundaryOnly)) return;
      if (noteKind === 'network') note('');
      const count = ingest(data, skipEntries);
      if (skipEntries) { clearSnapshot = false; note('已清空当前视图，服务端记录未删除。' + (paused ? '继续接收后可查看此后的新日志。' : '后续新日志将继续显示。')); }
      failures = 0; status(paused ? 'paused' : 'online', paused ? '已暂停接收' : '实时接收 · 1 秒刷新');
      if (!initial && count >= 500) delay = 50;
    } catch (error) {
      if (epoch !== generation || (!timedOut && controller.signal.aborted)) return;
      if ([401, 403].includes(error.status)) {
        blocked = true;
        status('auth', error.status === 403 ? '没有日志访问权限' : '登录已失效');
        note(error.status === 403 ? '运行日志仅服主可见。切换到服主账号后，点击「重新连接」。' : '请重新登录，再点击「重新连接」。日志接收已停止。');
      } else {
        failures += 1; delay = Math.min(15000, 1000 * 2 ** Math.min(failures, 4));
        status(paused ? 'paused' : 'offline', paused ? '已暂停 · 日志起点未更新' : `连接中断 · ${delay / 1000} 秒后重试`);
        note(paused ? '暂时无法建立清空后的日志起点，继续接收时将重新连接。' : timedOut
          ? '获取日志超时，稍后自动重试。已载入的日志仍可查看和导出。'
          : '暂时无法获取日志，稍后自动重试。已载入的日志仍可查看和导出。', 'network');
      }
    } finally {
      if (epoch === generation) {
        clearTimeout(timeout); timeout = null; request = null;
        schedule(delay);
      }
    }
  }
  function load() {
    if (!eligible()) return;
    const activeToken = currentToken();
    if (sessionToken !== null && sessionToken !== activeToken) reset();
    sessionToken = activeToken;
    if (blocked || paused || request || timer !== null) return;
    if (nextAt > Date.now()) schedule(nextAt - Date.now());
    else poll();
  }
  function stop() {
    cancelRequest();
    if (paused) status('paused', '已暂停接收');
    else if (!blocked) status('inactive', '页面离开时暂停接收');
    if (expanded) setExpanded(false, false);
  }
  function reset() {
    cancelRequest(); entries = []; instance = cursor = null; capacity = 1000;
    failures = 0; nextAt = 0; blocked = false; clearSnapshot = false; sessionToken = currentToken();
    rows.clear(); lines.replaceChildren(); renderedIds = ''; lastSourceSignature = ''; note('');
    find('source').value = ''; updateSources(); render(true);
  }
  function follow() {
    following = true; renderPreferences(); scrollToEnd();
  }
  function setExpanded(enabled, restoreFocus = true) {
    expanded = enabled; panel.dataset.expanded = String(enabled);
    document.body.classList.toggle('runtime-log-expanded', enabled);
    find('fullscreen').setAttribute('aria-pressed', String(enabled));
    find('fullscreen').textContent = enabled ? '收起' : '展开';
    find('fullscreen').title = enabled ? '退出展开，或按 Esc' : '展开日志，按 Esc 退出';
    panel.setAttribute('role', enabled ? 'dialog' : 'region');
    panel.setAttribute('aria-label', '实时日志');
    if (enabled) panel.setAttribute('aria-modal', 'true'); else panel.removeAttribute('aria-modal');
    if (following) scrollToEnd();
    if (restoreFocus) find('fullscreen').focus({preventScroll: true});
  }
  function exportText() {
    return visibleEntries.map(entry => {
      const date = new Date(Number(entry.time) * 1000);
      const timestamp = Number.isFinite(date.getTime()) ? date.toLocaleString('sv-SE', {hour12: false}) : '未知时间';
      return `[${timestamp}] [${entry.level}] [${entry.source}] ${entry.message}`;
    }).join('\n') + '\n';
  }

  for (const control of ['search', 'level', 'source']) find(control).addEventListener(control === 'search' ? 'input' : 'change', () => render());
  find('pause').onclick = () => {
    paused = !paused;
    if (paused) { cancelRequest(); status('paused', '已暂停接收'); }
    else { nextAt = 0; load(); }
    renderPreferences(); render();
  };
  find('reload').onclick = () => {
    cancelRequest(); blocked = false; failures = 0; nextAt = 0; paused = false; note('');
    renderPreferences(); load();
  };
  find('clear').onclick = () => {
    cancelRequest(); entries = []; rows.clear(); lines.replaceChildren(); renderedIds = '';
    clearSnapshot = true; nextAt = 0;
    note('已清空当前视图，服务端记录未删除。' + (paused ? '继续接收后显示新日志。' : '正在建立新的日志起点…'));
    updateSources(); render(true);
    if (paused) poll(true); else load();
  };
  find('follow').onclick = () => { if (following) { following = false; renderPreferences(); } else follow(); };
  find('latest').onclick = follow;
  find('wrap').onclick = () => {
    const saved = following ? null : anchor();
    panel.dataset.wrap = String(panel.dataset.wrap !== 'true'); renderPreferences(); savePreferences();
    if (following) scrollToEnd();
    else if (saved) {
      const target = [...lines.children].find(row => row.dataset.id === saved.id);
      if (target) viewport.scrollTop += target.getBoundingClientRect().top - viewport.getBoundingClientRect().top - saved.offset;
    }
    lastScrollTop = viewport.scrollTop;
  };
  find('font').onchange = () => { renderPreferences(); savePreferences(); if (following) scrollToEnd(); };
  find('fullscreen').onclick = () => setExpanded(!expanded);
  document.addEventListener('keydown', event => {
    if (!expanded) return;
    if (event.key === 'Escape') { event.preventDefault(); setExpanded(false); }
    if (event.key === 'Tab') {
      const controls = [...panel.querySelectorAll('button, input, select, [tabindex="0"]')]
        .filter(control => !control.disabled && control.getClientRects().length);
      const first = controls[0], last = controls[controls.length - 1];
      if (first && event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (last && !event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    }
  });
  viewport.addEventListener('scroll', () => {
    if (following && viewport.scrollTop < lastScrollTop - 2 && viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop > 24) {
      following = false; renderPreferences();
    } else if (!following && viewport.scrollTop > lastScrollTop + 2 && viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop <= 24) {
      following = true; renderPreferences();
    }
    lastScrollTop = viewport.scrollTop;
  }, {passive: true});
  find('copy').onclick = async () => {
    if (!visibleEntries.length) return;
    try { await navigator.clipboard.writeText(exportText()); feedback('已复制当前筛选的日志。'); }
    catch { feedback('剪贴板不可用，请下载日志或选中文字后复制。'); }
  };
  find('download').onclick = () => {
    if (!visibleEntries.length) return;
    const blob = new Blob([exportText()], {type: 'text/plain;charset=utf-8'}), url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url;
    link.download = 'VexBot-logs-' + new Date().toISOString().replace(/[:.]/g, '-') + '.log';
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    feedback('已下载当前筛选的日志。');
  };
  const observer = new MutationObserver(() => {
    if (document.body.classList.contains('logged-out')) { reset(); stop(); }
    else if (eligible()) load(); else stop();
  });
  observer.observe(document.body, {attributes: true, attributeFilter: ['data-view', 'class']});
  observer.observe(view, {attributes: true, attributeFilter: ['hidden']});
  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(() => { if (following && eligible()) scrollToEnd(); }).observe(viewport);
  }
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); else load(); });
  window.addEventListener('pagehide', stop);
  window.loadRuntimeLogs = load;
  window.stopRuntimeLogs = stop;
  window.resetRuntimeLogs = reset;
  renderPreferences(); render(); load();
})();
