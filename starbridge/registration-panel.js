'use strict';
let registrationConfig = null, registrationDirty = false, registrationLoading = false, registrationSaving = false, registrationPage = 1;
let registrationEpoch = 0;
window.registrationHasDraft = () => registrationDirty;
function registrationPopulate(data) {
  registrationConfig = data;
  for (const [key,value] of Object.entries(data.settings)) {
    const input = $('registration-'+key); if (!input) continue;
    if (typeof value === 'boolean') input.checked = value;
    else input.value = Array.isArray(value) ? value.join('\n') : value;
  }
  registrationDirty = false;
  setText('registration-draft-label','注册设置单独保存，立即生效。');
  $('registration-api-base').value = location.origin+'/api/v1';
  notice('registration-error',data.error || '', 'error', {persistent:true});
}
async function registrationAccounts() {
  const data = await api('/api/registration/accounts?'+new URLSearchParams({q:$('registration-search').value.trim(),page:String(registrationPage)}));
  renderChanged('registration-accounts',data,()=>{
    $('registration-accounts').replaceChildren(...data.accounts.map(account=>{
      const row=node('tr');for(const value of [account.player,account.email,account.qq || '—',new Date(account.created*1000).toLocaleString(),account.id,account.has_password?'已设置':'未设置'])row.append(node('td',value));
      const links=node('td');
      if(account.game_links?.length){
        links.append(node('span',account.game_links.map(link=>link.server).join('、'),'hint'),button('重置关联',async()=>{
          if(!confirm('确认重置 '+account.player+' 的游戏 UUID 关联？其当前游戏登录将失效，下次验证后重新关联。'))return;
          try{await api('/api/authentication/account-links/'+account.id,{method:'DELETE'});await registrationAccounts();notice('registration-notice','游戏身份关联已重置。','success');}
          catch(error){notice('registration-notice',error.message,'error');}
        }));
      }else links.textContent='首次登录后关联';
      row.append(links);return row;
    }));
    if(!data.accounts.length){const row=node('tr'),cell=node('td','暂无符合条件的注册账号。','empty-cell');cell.colSpan=7;row.append(cell);$('registration-accounts').append(row);}
    setText('registration-total',data.total+' 个账号');setText('registration-page','第 '+data.page+' / '+Math.max(1,Math.ceil(data.total/25))+' 页');
    $('registration-prev').disabled=data.page<=1;$('registration-next').disabled=data.page*25>=data.total;
  });
}
window.loadRegistration = async function(force=false) {
  if (!token || registrationLoading || registrationSaving) return;
  registrationLoading=true;const epoch=registrationEpoch;
  try {
    if (force || !registrationDirty) {
      const data=await api('/api/registration/settings');
      if(epoch===registrationEpoch && !registrationSaving && (force || !registrationDirty)
         && (force || data.revision!==registrationConfig?.revision || data.error!==registrationConfig?.error)){
        registrationPopulate(data);
        if(force)notice('registration-notice','已载入最新注册设置。','success');
      }
    }
    await registrationAccounts();
  }catch(error){notice('registration-notice',error.message,'error');}
  finally{registrationLoading=false;}
};
function registrationMarkDirty(){registrationDirty=true;registrationEpoch++;setText('registration-draft-label','注册设置有尚未保存的更改。');}
$('registration-settings-form').addEventListener('input',registrationMarkDirty);
$('registration-settings-form').addEventListener('change',registrationMarkDirty);
$('registration-settings-form').onsubmit=async event=>{
  event.preventDefault();if(registrationSaving || !registrationConfig)return;
  const settings=Object.fromEntries(Object.entries(registrationConfig.settings).map(([key,value])=>{
    const input=$('registration-'+key);
    return [key,typeof value==='boolean'?input.checked:typeof value==='number'?Number(input.value):Array.isArray(value)?input.value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean):input.value];
  }));
  registrationSaving=true;registrationEpoch++;
  const controls=[...$('registration-settings-form').querySelectorAll('input,textarea,select,button')],disabled=controls.map(input=>input.disabled);controls.forEach(input=>input.disabled=true);
  notice('registration-notice','正在保存…','',{persistent:true});
  try{
    registrationPopulate(await api('/api/registration/settings',{method:'PUT',body:JSON.stringify({settings,revision:registrationConfig.revision})}));
    notice('registration-notice','注册设置已保存并生效；此前的验证码已失效。','success');
  }catch(error){notice('registration-notice',error.message,'error');}
  finally{controls.forEach((input,index)=>input.disabled=disabled[index]);registrationSaving=false;}
};
$('registration-reload').onclick=()=>{if(!registrationDirty || confirm('重新载入会丢弃尚未保存的注册设置，是否继续？'))window.loadRegistration(true);};
$('registration-reveal-password').onclick=()=>{const input=$('registration-smtp_password');input.type=input.type==='password'?'text':'password';$('registration-reveal-password').textContent=input.type==='password'?'显示':'隐藏';};
$('registration-generate-key').onclick=()=>{$('registration-api_token').value=randomToken();registrationMarkDirty();};
async function registrationCopy(value){try{await navigator.clipboard.writeText(value);notice('registration-notice','已复制。','success');}catch{notice('registration-notice','复制失败，请手动复制。','error');}}
$('registration-copy-key').onclick=()=>registrationCopy($('registration-api_token').value);
$('registration-copy-base').onclick=()=>registrationCopy($('registration-api-base').value);
async function registrationDownload(kind){
  try{
    const response=await fetch('/api/registration/'+kind,{headers:{Authorization:'Bearer '+token},cache:'no-store',signal:AbortSignal.timeout(10000)});
    if(!response.ok)throw Error('下载失败，请检查登录状态。');
    const url=URL.createObjectURL(await response.blob()),link=node('a');link.href=url;link.download=kind==='guide'?'VexBot-account-api.md':'website-registration.js';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){notice('registration-notice',error.message,'error');}
}
$('registration-guide').onclick=()=>registrationDownload('guide');$('registration-example').onclick=()=>registrationDownload('example');
$('registration-search-form').onsubmit=event=>{event.preventDefault();registrationPage=1;window.loadRegistration();};
$('registration-prev').onclick=()=>{if(registrationLoading||registrationSaving)return;registrationPage=Math.max(1,registrationPage-1);window.loadRegistration();};
$('registration-next').onclick=()=>{if(registrationLoading||registrationSaving)return;registrationPage++;window.loadRegistration();};
