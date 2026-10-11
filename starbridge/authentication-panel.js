'use strict';
let authenticationConfig=null, authenticationDirty=false, authenticationLoading=false, authenticationSaving=false, authenticationEpoch=0;
window.authenticationHasDraft=()=>authenticationDirty;
function authenticationPopulate(data){
  authenticationConfig=data;
  modBridgeSelect($('authentication-mod-version'), $('authentication-mod-version').value || 'forge/1.20.1').catch(error=>notice('authentication-notice',error.message,'error'));
  for(const [key,value] of Object.entries(data.settings)){
    const input=$('authentication-'+key);if(!input)continue;
    if(typeof value==='boolean')input.checked=value;else input.value=value;
  }
  $('authentication-servers').replaceChildren();
  const servers=[...data.servers];
  for(const sid of data.settings.enabled_servers)if(!servers.some(server=>server.id===sid))servers.push({id:sid,name:sid+'（已移除）'});
  for(const server of servers){
    const wrap=node('label','','authentication-server'),input=node('input');input.type='checkbox';input.value=server.id;
    input.checked=data.settings.enabled_servers.includes(server.id);
    const identity=node('span');identity.append(node('strong',server.name),node('span',server.id,'hint'));
    wrap.append(input,identity);$('authentication-servers').append(wrap);
  }
  if(!servers.length)$('authentication-servers').append(node('p','还没有服务器，在「接入空间」添加服务器后选择。','hint'));
  authenticationDirty=false;setText('authentication-draft-label','游戏登录设置单独保存，插件在线后自动应用。');
  notice('authentication-error',data.error || '', 'error', {persistent:true});
}
window.loadAuthentication=async function(force=false){
  if(!token || authenticationLoading || authenticationSaving || authenticationDirty&&!force)return;
  authenticationLoading=true;const epoch=authenticationEpoch;
  try{
    const data=await api('/api/authentication/settings');
    if(epoch===authenticationEpoch&&!authenticationSaving&&(!authenticationDirty||force)
      &&(force||data.revision!==authenticationConfig?.revision||JSON.stringify(data.servers)!==JSON.stringify(authenticationConfig?.servers)||data.error!==authenticationConfig?.error))authenticationPopulate(data);
  }catch(error){notice('authentication-notice',error.message,'error');}
  finally{authenticationLoading=false;}
};
function authenticationMarkDirty(){authenticationDirty=true;authenticationEpoch++;setText('authentication-draft-label','游戏登录设置有尚未保存的更改。');}
$('authentication-form').addEventListener('input',authenticationMarkDirty);
$('authentication-form').addEventListener('change',authenticationMarkDirty);
$('authentication-form').onsubmit=async event=>{
  event.preventDefault();if(authenticationSaving||!authenticationConfig)return;
  const settings=Object.fromEntries(Object.entries(authenticationConfig.settings).map(([key,value])=>{
    if(key==='enabled_servers')return [key,[...$('authentication-servers').querySelectorAll('input:checked')].map(input=>input.value)];
    const input=$('authentication-'+key);return [key,typeof value==='boolean'?input.checked:typeof value==='string'?input.value:Number(input.value)];
  }));
  authenticationSaving=true;authenticationEpoch++;
  const controls=[...$('authentication-form').querySelectorAll('input,select,button')],disabled=controls.map(el=>el.disabled);controls.forEach(el=>el.disabled=true);
  notice('authentication-notice','正在保存…','',{persistent:true});
  try{
    authenticationPopulate(await api('/api/authentication/settings',{method:'PUT',body:JSON.stringify({settings,revision:authenticationConfig.revision})}));
    notice('authentication-notice','游戏登录设置已保存，在线玩家将重新登录。','success');
  }catch(error){notice('authentication-notice',error.message,'error');}
  finally{controls.forEach((el,index)=>el.disabled=disabled[index]);authenticationSaving=false;}
};
$('authentication-reload').onclick=()=>{if(!authenticationDirty||confirm('放弃未保存的游戏登录设置并重新载入？'))window.loadAuthentication(true);};
$('authentication-download').onclick=async()=>{
  try{
    const response=await fetch('/api/plugin',{headers:{Authorization:'Bearer '+token},cache:'no-store',signal:AbortSignal.timeout(10000)});
    if(!response.ok)throw Error('插件下载失败。');const url=URL.createObjectURL(await response.blob()),link=node('a');link.href=url;link.download='Myrinbot-0.5.3.jar';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){notice('authentication-notice',error.message,'error');}
};
$('authentication-guide').onclick=async()=>{
  try{const response=await fetch('/api/authentication/guide',{headers:{Authorization:'Bearer '+token},cache:'no-store',signal:AbortSignal.timeout(10000)});if(!response.ok)throw Error('文档下载失败。');const url=URL.createObjectURL(await response.blob()),link=node('a');link.href=url;link.download='Myrinbot-game-login.md';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  catch(error){notice('authentication-notice',error.message,'error');}
};
$('authentication-forge-download').onclick=async()=>{
  try{
    await downloadModBridge($('authentication-mod-version').value || 'forge/1.20.1');
  }catch(error){notice('authentication-notice',error.message,'error');}
};
$('authentication-forge-guide').onclick=async()=>{
  try{
    const platform=$('authentication-mod-version').value.split('/')[0]||'forge';
    const response=await fetch('/api/authentication/guide?'+new URLSearchParams({platform}),{headers:{Authorization:'Bearer '+token},cache:'no-store',signal:AbortSignal.timeout(10000)});
    if(!response.ok)throw Error('模组安装文档下载失败。');
    const url=URL.createObjectURL(await response.blob()),link=node('a');link.href=url;link.download=platform==='fabric'?'Myrinbot-fabric-game-ends.md':'Myrinbot-mod-game-ends.md';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){notice('authentication-notice',error.message,'error');}
};
