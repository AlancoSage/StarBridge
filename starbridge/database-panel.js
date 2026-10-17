'use strict';
const mysqlDefaults = {enabled:false, host:'127.0.0.1', port:3306, database:'myrinbot', user:'myrinbot', password:'', connect_timeout:5, read_timeout:5, write_timeout:5, tls:false, ssl_ca:''};
const mysqlNumbers = ['port', 'connect_timeout', 'read_timeout', 'write_timeout'];
function readMySQLSettings() {
  const value = {...mysqlDefaults, enabled:$('database-backend').value === 'mysql', tls:$('mysql-tls').checked};
  for (const key of Object.keys(value)) {
    if (['enabled', 'tls'].includes(key)) continue;
    value[key] = mysqlNumbers.includes(key) ? Number($('mysql-' + key).value)
      : key === 'password' ? $('mysql-password').value : $('mysql-' + key).value.trim();
  }
  if (!value.tls) value.ssl_ca = '';
  return value;
}
function renderDatabaseMode() {
  const mysql = $('database-backend').value === 'mysql';
  $('mysql-settings').hidden = !mysql;
  $('sqlite-settings').hidden = mysql;
  $('mysql-ca-field').hidden = !$('mysql-tls').checked;
}
function renderDatabaseSettings(config) {
  const value = {...mysqlDefaults, ...config.mysql};
  $('database-backend').value = value.enabled ? 'mysql' : 'sqlite';
  for (const [key, item] of Object.entries(value)) {
    if (key === 'enabled') continue;
    if (key === 'tls') $('mysql-tls').checked = item;
    else $('mysql-' + key).value = item;
  }
  renderDatabaseMode();
  api('/api/database/status').then(status => {
    $('database-running').textContent = '当前运行：' + (status.backend === 'mysql' ? 'MySQL' : 'SQLite') + '。保存后重启才会切换存储。';
    $('mysql-supervisor-hint').hidden = !status.full_restart_required;
    if (!status.driver_available) notice('mysql-test-notice', 'MySQL 驱动尚未安装，请通过启动脚本更新依赖后重新启动。', 'error', {persistent:true});
  }).catch(() => { $('database-running').textContent = '保存后重启切换数据库；已有数据需单独迁移。'; });
}
document.getElementById('database-backend').addEventListener('change', renderDatabaseMode);
document.getElementById('mysql-tls').addEventListener('change', renderDatabaseMode);
document.getElementById('mysql-test').onclick = async () => {
  const control = $('mysql-test'); control.disabled = true;
  notice('mysql-test-notice', '正在检测 MySQL 连接…', '', {persistent:true});
  try {
    const result = await api('/api/database/test', {method:'POST', body:JSON.stringify({mysql:readMySQLSettings()}), signal:AbortSignal.timeout(20000)});
    notice('mysql-test-notice', result.detail, result.status === 'ok' ? 'success' : 'error', {persistent:true});
  } catch (error) { notice('mysql-test-notice', error.message, 'error', {persistent:true}); }
  finally { control.disabled = false; }
};
