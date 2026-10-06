'use strict';
let websiteConfig=null,websiteDirty=false,websiteLoading=false,websiteSaving=false,websiteChecking=false,websiteEpoch=0;
window.websiteHasDraft=()=>websiteDirty||websiteSaving;
window.resetWebsite=()=>{websiteEpoch++;websiteConfig=null;websiteDirty=false;};
function websiteModeUI(){
  const mode=$('website-website_mode').value,enabled=mode!=='none',provided=mode==='provided';
  $('website-connection_enabled').checked=enabled;
  for(const [id,show] of [['website-connection-fields',enabled],['website-provided-fields',provided]]){
    const group=$(id);group.hidden=!show;group.querySelectorAll('input,textarea,select').forEach(input=>input.disabled=!show);
  }
  $('website-deployment-panel').hidden=!enabled;$('website-project').hidden=!provided;
  $('website-check').disabled=websiteSaving||websiteChecking||!websiteConfig?.connection.enabled;
  $('website-unbind').disabled=websiteSaving||!websiteConfig?.connection.enabled;
  setText('website-save',!enabled?'保存接入设置':websiteConfig?.connection.enabled?'保存绑定与内容':'绑定网站');
  setText('website-mode-description',mode==='none'?'不接入官网，Bot 仍可正常使用。已保存的网站地址和设置会保留。':provided?'使用星桥提供的独立官网项目，自行选择部署位置，再填写网站地址接入。':'填写已有官网地址，通过 API 或 SDK 接入注册、登录和信息查询；网站界面由你自己的项目管理。');
  setText('website-deployment-title',provided?'部署星桥官网':'接入你自己的官网');
  setText('website-deployment-description',provided?'下载官网项目并部署到自己的服务器或静态托管，将接入配置 config.json 放到网站根目录。官网内容和外观可在本面板调整。':'使用接口文档与 SDK，在自己的网站中接入星桥账号和服务器信息。接入配置提供 Bot API 地址，页面设计和内容由你自行管理。');
}
function websitePopulate(data){
  websiteConfig=data;websiteDirty=false;
  for(const [key,value] of Object.entries(data.settings)){const input=$('website-'+key);if(typeof value==='boolean')input.checked=value;else input.value=value;}
  setText('website-origin',data.connection.origin||'尚未填写网站地址');
  setText('website-connection-status',data.connection.enabled?(data.connection.mode==='provided'?'已绑定星桥官网':'已绑定自己的官网'):'未绑定网站');
  setText('website-check-result','');
  const open=$('website-open');open.hidden=!data.connection.enabled||!!data.error;open.href=data.settings.website_url||'/community/';
  setText('website-draft-label','');
  websiteModeUI();
  if(data.error)notice('website-notice',data.error,'error',{persistent:true});
}
window.loadWebsite=async function(force=false){
  if(!token||websiteLoading||websiteSaving)return;
  websiteLoading=true;const epoch=websiteEpoch;
  try{const data=await api('/api/website/settings');if(epoch===websiteEpoch&&!websiteSaving&&(force||!websiteDirty)&&(force||data.revision!==websiteConfig?.revision))websitePopulate(data);}
  catch(error){notice('website-notice',error.message,'error');}finally{websiteLoading=false;}
};
function websiteMarkDirty(){websiteDirty=true;websiteEpoch++;setText('website-check-result','');setText('website-draft-label','网站绑定与内容有尚未保存的更改。');}
$('website-settings-form').addEventListener('input',websiteMarkDirty);
$('website-settings-form').addEventListener('change',websiteMarkDirty);
$('website-website_mode').addEventListener('change',websiteModeUI);
async function websiteSave(settings,message){
  if(websiteSaving||!websiteConfig)return;
  websiteSaving=true;websiteEpoch++;
  const controls=[...$('website-settings-form').querySelectorAll('input,textarea,select,button')],disabled=controls.map(input=>input.disabled);controls.forEach(input=>input.disabled=true);
  try{websitePopulate(await api('/api/website/settings',{method:'PUT',body:JSON.stringify({settings,revision:websiteConfig.revision})}));notice('website-notice',message,'success');}
  catch(error){notice('website-notice',error.message,'error');}finally{controls.forEach((input,index)=>input.disabled=disabled[index]);websiteSaving=false;websiteModeUI();}
}
$('website-settings-form').onsubmit=async event=>{
  event.preventDefault();if(websiteSaving||!websiteConfig)return;
  const settings=Object.fromEntries(Object.entries(websiteConfig.settings).map(([key,value])=>{const input=$('website-'+key);return [key,input.disabled?value:typeof value==='boolean'?input.checked:input.value];}));
  if(settings.website_mode!=='none'&&!settings.api_public_url){settings.api_public_url=location.origin+'/api/v1';}
  await websiteSave(settings,settings.website_mode==='none'?'网站接入设置已保存。':'网站绑定与内容已保存，网站来源授权已生效。');
};
$('website-unbind').onclick=async()=>{
  if(websiteSaving||!websiteConfig?.connection.enabled)return;
  if(websiteDirty){notice('website-notice','请先保存或重新载入未保存的设置，再解除绑定。','error');return;}
  if(!confirm('解除网站绑定后，将停止授权该网站来源。网站地址、内容和已有账号都会保留，是否继续？'))return;
  await websiteSave({...websiteConfig.settings,website_mode:'none',connection_enabled:false},'已解除网站绑定，原网站地址和内容已保留。');
};
$('website-check').onclick=async()=>{
  if(websiteSaving||websiteChecking||!websiteConfig?.connection.enabled)return;
  if(websiteDirty){notice('website-notice','请先保存网站绑定设置，再检查 API。','error');return;}
  const epoch=websiteEpoch;websiteChecking=true;websiteModeUI();setText('website-check-result','正在检查公开 API…');
  try{
    const address=websiteConfig.settings.api_public_url||location.origin+'/api/v1';
    const url=new URL(address.replace(/\/$/,'')+'/community/info',location.origin);
    const response=await fetch(url,{credentials:'omit',cache:'no-store',referrerPolicy:'no-referrer',redirect:'error',signal:AbortSignal.timeout(8000)});
    if(!response.ok)throw Error('API 返回 HTTP '+response.status+'。');
    const data=await response.json();
    if(typeof data.title!=='string'||typeof data.registration_enabled!=='boolean'||typeof data.login_enabled!=='boolean')throw Error('该地址未返回星桥官网 API 数据，请检查地址。');
    if(epoch===websiteEpoch)setText('website-check-result','API 可达 · '+data.title+'。此结果只验证当前浏览器的访问；请在官网完成接入测试。');
  }catch(error){if(epoch===websiteEpoch)setText('website-check-result',error.name==='TimeoutError'?'API 检查超时，请检查地址和网络。':error instanceof TypeError?'当前浏览器无法访问 API，请检查地址、HTTPS 和跨域来源设置。':error.message);}
  finally{websiteChecking=false;websiteModeUI();}
};
$('website-reload').onclick=()=>{if(!websiteDirty||confirm('重新载入会丢弃尚未保存的官网设置，是否继续？'))window.loadWebsite(true);};
$('website-api_public_url').placeholder=location.origin+'/api/v1';
async function websiteDownload(kind){
  const button=$('website-'+kind);if(button.disabled)return;
  if(kind==='config'&&websiteDirty){notice('website-download-notice','请先保存网站接入设置，再下载配置。','error');return;}
  button.disabled=true;
  try{
    const url=kind==='sdk'?'/api/registration/example':'/api/website/'+kind;
    const response=await fetch(url,{method:kind==='config'?'POST':'GET',headers:{Authorization:'Bearer '+token,...(kind==='config'?{'Content-Type':'application/json'}:{})},
      ...(kind==='config'?{body:JSON.stringify({})}:{}),cache:'no-store',signal:AbortSignal.timeout(15000)});
    if(!response.ok){const data=await response.json().catch(()=>({}));throw Error(data.error||'下载失败，请检查登录状态。');}
    const objectUrl=URL.createObjectURL(await response.blob()),link=node('a');link.href=objectUrl;link.download=kind==='project'?'StarBridge-website.zip':kind==='config'?'config.json':kind==='guide'?'StarBridge-website-deployment.md':'website-registration.js';link.click();setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);
    notice('website-download-notice',kind==='project'?'独立网站项目已下载。':'接入文件已下载。','success');
  }catch(error){notice('website-download-notice',error.message,'error');}finally{button.disabled=false;}
}
$('website-project').onclick=()=>websiteDownload('project');$('website-config').onclick=()=>websiteDownload('config');$('website-guide').onclick=()=>websiteDownload('guide');$('website-sdk').onclick=()=>websiteDownload('sdk');
