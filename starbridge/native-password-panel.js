'use strict';
let nativePasswordConfig=null,nativePasswordDirty=false,nativePasswordBusy=false,nativePasswordEpoch=0;
window.nativePasswordHasDraft=()=>nativePasswordDirty||nativePasswordBusy;
const nativePasswordTargets=[['','不开放找回'],['bukkit/authme','Bukkit · AuthMe'],['bukkit/librelogin','Paper · LibreLogin'],['velocity/limboauth','Velocity · LimboAuth'],['velocity/librelogin','Velocity · LibreLogin']];
function nativePasswordPopulate(data){
  nativePasswordConfig=data;
  const wrap=$('native-password-servers');wrap.replaceChildren();
  const servers=[...data.servers];
  for(const sid of Object.keys(data.settings.servers))if(!servers.some(s=>s.id===sid))servers.push({id:sid,name:sid+'（已移除）'});
  for(const server of servers){
    const field=node('label','','field'),select=node('select');select.dataset.server=server.id;
    field.append(node('span',server.name+' · '+server.id));
    select.append(...nativePasswordTargets.map(([value,label])=>new Option(label,value)));
    const target=data.settings.servers[server.id];select.value=target?target.platform+'/'+target.engine:'';
    const peers=data.connections.filter(peer=>peer.server===server.id);
    field.append(select,node('span',peers.length?peers.map(p=>p.platform+' / '+(p.engine||'无可用适配器')).join('；'):'密码找回端尚未连接','hint'));wrap.append(field);
  }
  if(!servers.length)wrap.append(node('p','请先在接入空间添加服务器。','hint'));
  nativePasswordDirty=false;setText('native-password-draft','玩家私聊发送：/重置密码 服务器ID');
  notice('native-password-notice',data.error||'','error',{persistent:true});
}
window.loadNativePasswords=async function(force=false){
  if(!token||nativePasswordBusy||nativePasswordDirty&&!force)return;
  const epoch=nativePasswordEpoch;nativePasswordBusy=true;
  try{
    const data=await api('/api/native-passwords/settings');
    if(epoch===nativePasswordEpoch&&(!nativePasswordDirty||force)&&(force||JSON.stringify(data)!==JSON.stringify(nativePasswordConfig)))nativePasswordPopulate(data);
  }catch(error){notice('native-password-notice',error.message,'error');}
  finally{nativePasswordBusy=false;}
};
function nativePasswordMarkDirty(){
  const servers={};
  for(const select of $('native-password-servers').querySelectorAll('select'))if(select.value){const [platform,engine]=select.value.split('/');servers[select.dataset.server]={platform,engine};}
  const saved=nativePasswordConfig?.settings.servers||{},keys=new Set([...Object.keys(servers),...Object.keys(saved)]);
  nativePasswordDirty=[...keys].some(sid=>servers[sid]?.platform!==saved[sid]?.platform||servers[sid]?.engine!==saved[sid]?.engine);nativePasswordEpoch++;
  setText('native-password-draft',nativePasswordDirty?'密码找回设置有尚未保存的更改。':'玩家私聊发送：/重置密码 服务器ID');
}
$('native-password-form').addEventListener('change',nativePasswordMarkDirty);
$('native-password-form').onsubmit=async event=>{
  event.preventDefault();if(nativePasswordBusy||!nativePasswordConfig)return;
  const servers={};for(const select of $('native-password-servers').querySelectorAll('select'))if(select.value){const [platform,engine]=select.value.split('/');servers[select.dataset.server]={platform,engine};}
  nativePasswordBusy=true;nativePasswordEpoch++;
  const controls=[...$('native-password-form').querySelectorAll('button,select')];controls.forEach(el=>el.disabled=true);
  try{nativePasswordPopulate(await api('/api/native-passwords/settings',{method:'PUT',body:JSON.stringify({settings:{servers},revision:nativePasswordConfig.revision})}));notice('native-password-notice','密码找回设置已保存。','success');}
  catch(error){notice('native-password-notice',error.message,'error');}
  finally{controls.forEach(el=>el.disabled=false);nativePasswordBusy=false;}
};
$('native-password-reload').onclick=()=>{if(!nativePasswordDirty||confirm('放弃未保存的密码找回设置？'))window.loadNativePasswords(true);};
for(const kind of ['velocity','guide'])$('native-password-'+kind).onclick=async()=>{
  try{
    const response=await fetch('/api/native-passwords/'+kind,{headers:{Authorization:'Bearer '+token},cache:'no-store',signal:AbortSignal.timeout(10000)});
    if(!response.ok)throw Error('下载失败，请检查发布附件。');
    const url=URL.createObjectURL(await response.blob()),link=node('a');link.href=url;link.download=kind==='guide'?'Myrinbot-native-password-reset.md':'Myrinbot-Velocity-0.1.0.jar';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){notice('native-password-notice',error.message,'error');}
};
