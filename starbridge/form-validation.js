'use strict';

// Keep the browser's constraint validation; replace only its native error bubble.
(() => {
  if (window.VexBotFormValidation) return;

  const errors = new Map();
  const focusCandidates = new Set();
  const invalidClass = 'field-validation-invalid';
  let nextId = 0, focusTimer = null, refreshTimer = null, refreshQueued = false;

  function isControl(control) {
    return control instanceof HTMLInputElement || control instanceof HTMLSelectElement || control instanceof HTMLTextAreaElement;
  }

  function isVisible(control) {
    if (!control.isConnected || control.closest('[hidden], [inert], dialog:not([open])')) return false;
    const style = getComputedStyle(control);
    return style.visibility !== 'hidden' && style.visibility !== 'collapse' && [...control.getClientRects()].some(rect => rect.width && rect.height);
  }

  function fieldLabel(control) {
    const label = control.labels?.[0]?.textContent?.replace(/\s+/g, ' ').trim().replace(/[：:]$/, '') || '';
    return label.length <= 40 ? label : '';
  }

  function constraint(control, name) {
    const value = control.getAttribute(name) || '';
    // These are public constraints, never the user's entered value.
    return value.length <= 32 ? value : '';
  }

  function fallbackMessage(control) {
    // A custom validator can quote its input; never repeat a password in feedback.
    if (control.type === 'password' || /(?:^|\s)(?:new|current)-password(?:\s|$)/.test(control.autocomplete || '')) {
      return '请检查密码是否符合要求。';
    }
    const message = control.validationMessage || '请检查此字段的填写内容。';
    const value = control.value;
    return value ? message.split(value).join('填写内容') : message;
  }

  function errorMessage(control) {
    const validity = control.validity, type = control.type;
    const label = fieldLabel(control);
    if (validity.customError) return fallbackMessage(control);
    if (validity.badInput) {
      if (type === 'number' || type === 'range') return '请输入有效的数字。';
      if (type === 'time') return '请输入有效的时间。';
      if (['date', 'datetime-local', 'month', 'week'].includes(type)) return '请输入有效的日期。';
      return '请检查填写格式。';
    }
    if (validity.valueMissing) {
      if (type === 'checkbox') return label ? `请勾选“${label}”。` : '请勾选此选项后继续。';
      if (type === 'radio') return '请选择一项后继续。';
      if (control instanceof HTMLSelectElement) return `请选择${label || '一项'}。`;
      return `请填写${label || '此字段'}。`;
    }
    if (validity.typeMismatch) {
      if (type === 'email') return '请输入有效的邮箱地址，例如 name@example.com。';
      if (type === 'url') return '请输入完整的网址，例如 https://example.com。';
      return '请检查填写格式。';
    }
    if (validity.tooShort) return `请至少填写 ${control.minLength} 个字符。`;
    if (validity.tooLong) return `最多可填写 ${control.maxLength} 个字符。`;
    if (validity.rangeUnderflow || validity.rangeOverflow) {
      const isMinimum = validity.rangeUnderflow;
      const limit = constraint(control, isMinimum ? 'min' : 'max');
      if (limit) {
        if (type === 'number' || type === 'range') return `请输入不${isMinimum ? '小' : '大'}于 ${limit} 的数值。`;
        return `请填写不${isMinimum ? '早' : '晚'}于 ${limit} 的${type === 'time' ? '时间' : '日期'}。`;
      }
      return `填写内容${isMinimum ? '低于下限' : '超过上限'}，请按字段要求调整。`;
    }
    if (validity.stepMismatch) {
      if (type === 'number' || type === 'range') {
        const step = constraint(control, 'step') || '1';
        return `请按 ${step} 的间隔填写数值。`;
      }
      return `请填写符合${type === 'time' ? '时间' : '日期'}间隔要求的值。`;
    }
    if (validity.patternMismatch) return '格式不正确，请按字段说明填写。';
    return fallbackMessage(control);
  }

  function createIcon() {
    const namespace = 'http://www.w3.org/2000/svg';
    const icon = document.createElementNS(namespace, 'svg');
    icon.setAttribute('viewBox', '0 0 24 24');
    icon.setAttribute('class', 'field-error-icon');
    icon.setAttribute('aria-hidden', 'true');
    icon.setAttribute('focusable', 'false');
    const circle = document.createElementNS(namespace, 'circle');
    circle.setAttribute('cx', '12'); circle.setAttribute('cy', '12'); circle.setAttribute('r', '9');
    const mark = document.createElementNS(namespace, 'path');
    mark.setAttribute('d', 'M12 7.5v5M12 16.5h.01');
    icon.append(circle, mark);
    return icon;
  }

  function startRefreshTimer() {
    if (refreshTimer !== null || !errors.size || document.hidden) return;
    // Assigning .value does not emit input or a DOM mutation. Watch only fields
    // already showing feedback, and stop as soon as it is no longer needed.
    refreshTimer = setInterval(() => refresh(), 400);
  }

  function stopRefreshTimer() {
    if (refreshTimer !== null) clearInterval(refreshTimer);
    refreshTimer = null;
  }

  function clearError(control) {
    const entry = errors.get(control);
    if (!entry) return;
    errors.delete(control);
    focusCandidates.delete(control);
    entry.node.remove();
    if (!entry.hadInvalidClass) control.classList.remove(invalidClass);
    if (control.getAttribute('aria-invalid') === 'true') {
      if (entry.previousInvalid === null) control.removeAttribute('aria-invalid');
      else control.setAttribute('aria-invalid', entry.previousInvalid);
    }
    const description = control.getAttribute('aria-describedby');
    if (description === entry.managedDescription) {
      if (entry.previousDescription === null) control.removeAttribute('aria-describedby');
      else control.setAttribute('aria-describedby', entry.previousDescription);
    } else if (description !== null) {
      const ids = description.split(/\s+/).filter(id => id && id !== entry.node.id);
      if (ids.length) control.setAttribute('aria-describedby', ids.join(' '));
      else control.removeAttribute('aria-describedby');
    }
    if (!errors.size) stopRefreshTimer();
  }

  function showError(control) {
    if (!control.willValidate || control.validity.valid || !isVisible(control)) {
      clearError(control);
      return;
    }
    let entry = errors.get(control);
    if (!entry) {
      const node = document.createElement('div');
      node.className = 'field-error';
      do { node.id = 'vexbot-field-error-' + (++nextId); } while (document.getElementById(node.id));
      const text = document.createElement('span');
      text.className = 'field-error-text';
      node.append(createIcon(), text);
      const previousDescription = control.getAttribute('aria-describedby');
      const managedDescription = [...new Set((previousDescription || '').split(/\s+/).filter(Boolean)), node.id].join(' ');
      entry = {node, text, previousDescription, managedDescription,
        previousInvalid: control.getAttribute('aria-invalid'), hadInvalidClass: control.classList.contains(invalidClass)};
      errors.set(control, entry);
      const field = control.closest('.field');
      if (field) field.append(node);
      else (control.closest('label, .secret') || control).after(node);
      control.classList.add(invalidClass);
      control.setAttribute('aria-invalid', 'true');
      control.setAttribute('aria-describedby', managedDescription);
      startRefreshTimer();
    }
    const message = errorMessage(control);
    if (entry.text.textContent !== message) entry.text.textContent = message;
  }

  function inScope(scope, control) {
    return scope === document || scope === control || !!scope?.contains?.(control);
  }

  function clear(scope = document) {
    for (const control of errors.keys()) if (inScope(scope, control)) clearError(control);
  }

  function refresh(scope = document) {
    for (const [control, entry] of errors) {
      if (!inScope(scope, control)) continue;
      if (!entry.node.isConnected || !control.isConnected) clearError(control);
      else showError(control);
    }
  }

  function queueRefresh() {
    if (!errors.size || refreshQueued) return;
    refreshQueued = true;
    queueMicrotask(() => { refreshQueued = false; refresh(); });
  }

  document.addEventListener('invalid', event => {
    const control = event.target;
    if (!isControl(control)) return;
    event.preventDefault();
    showError(control);
    if (!errors.has(control)) return;
    focusCandidates.add(control);
    if (focusTimer !== null) return;
    // Native form validation emits invalid for every failed field in one turn.
    // Focus only its first visible field, rather than jumping to the last one.
    focusTimer = setTimeout(() => {
      focusTimer = null;
      const first = [...focusCandidates].find(candidate => candidate.willValidate && !candidate.validity.valid && isVisible(candidate));
      focusCandidates.clear();
      if (!first) return;
      first.focus({preventScroll: true});
      // Move the field and its feedback together, including inside scrollable
      // dialogs; nearest alignment leaves an already visible field in place.
      const target = first.closest('.field') || first;
      target.scrollIntoView({block: 'nearest', inline: 'nearest', behavior: 'instant'});
    }, 0);
  }, true);

  for (const name of ['input', 'change', 'focusin']) {
    document.addEventListener(name, event => {
      if (errors.has(event.target)) showError(event.target);
    });
  }
  document.addEventListener('submit', event => refresh(event.target), true);
  document.addEventListener('reset', event => {
    setTimeout(() => { if (!event.defaultPrevented) clear(event.target); }, 0);
  }, true);
  document.addEventListener('close', event => {
    if (event.target instanceof HTMLDialogElement) clear(event.target);
  }, true);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopRefreshTimer();
    else { refresh(); startRefreshTimer(); }
  });
  new MutationObserver(queueRefresh).observe(document.documentElement, {
    childList: true, subtree: true, attributes: true,
    attributeFilter: ['class', 'style', 'hidden', 'inert', 'open', 'disabled', 'readonly', 'required', 'type', 'min', 'max', 'step', 'minlength', 'maxlength', 'pattern', 'multiple'],
  });

  // Populate/reload handlers may clear a form explicitly without touching values
  // or modifying the platform's checkValidity/reportValidity implementations.
  window.VexBotFormValidation = Object.freeze({clear, refresh});
})();
