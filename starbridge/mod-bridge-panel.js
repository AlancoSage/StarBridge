'use strict';
let modBridgeRows = null;
async function modBridgeCatalog() {
  if (!modBridgeRows) {
    const response = await fetch('/api/plugin/catalog', {headers:{Authorization:'Bearer '+token}, cache:'no-store', signal:AbortSignal.timeout(10000)});
    if (!response.ok) throw Error('游戏端版本列表读取失败。');
    modBridgeRows = (await response.json()).bridges;
  }
  return modBridgeRows;
}
async function modBridgeSelect(select, preferred='forge/1.20.1') {
  const rows = await modBridgeCatalog();
  select.replaceChildren();
  for (const row of rows) {
    const option = node('option', row.label+' · Java '+row.java+(row.available?'':'（未构建）'));
    option.value = row.platform+'/'+row.version;
    select.append(option);
  }
  select.value = rows.some(row => row.platform+'/'+row.version===preferred) ? preferred : 'forge/1.20.1';
  select.dispatchEvent(new Event('change', {bubbles:true}));
}
async function downloadModBridge(value) {
  const rows = await modBridgeCatalog(), row = rows.find(row => row.platform+'/'+row.version===value);
  if (!row) throw Error('请选择游戏端版本。');
  const response = await fetch('/api/plugin?'+new URLSearchParams({platform:row.platform,version:row.version}), {
    headers:{Authorization:'Bearer '+token},cache:'no-store',signal:AbortSignal.timeout(10000)});
  if (!response.ok) throw Error('游戏端下载失败，请检查该版本是否已构建。');
  const url=URL.createObjectURL(await response.blob()), link=node('a');
  link.href=url;link.download=row.filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function addModBridgeControls(details, card, serverId) {
  const wrap=node('div','','field'), label=node('label','Forge / NeoForge 游戏版本'), select=node('select');
  select.dataset.modBridge='version';select.setAttribute('aria-label','Forge / NeoForge 游戏版本');label.append(select);wrap.append(label);details.append(wrap);
  const snapshot=latestStatus?.servers?.find(server=>server.id===serverId);
  const preferred=(snapshot?.server_software?.startsWith('NeoForge')?'neoforge':'forge')+'/'+(snapshot?.version||'1.20.1');
  modBridgeSelect(select, preferred).catch(error=>notice('save-notice',error.message,'error'));
  details.append(button('下载模组连接配置',()=>downloadPlugin(card,select.value)));
  details.append(button('下载所选模组 JAR',async()=>{try{await downloadModBridge(select.value);}catch(error){notice('save-notice',error.message,'error');}}));
}
