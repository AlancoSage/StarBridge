'use strict';
const registerEl=id=>document.getElementById(id);
let registerInfo=null,registerBusy=false,registerNoticeTimer=null,registerToken='';
for(const el of document.querySelectorAll('input,button'))el.disabled=true;
function registerNotice(text,type='',persistent=false){
  clearTimeout(registerNoticeTimer);const el=registerEl('register-notice');el.textContent=text;el.className='notice '+type;
  if(text&&!persistent)registerNoticeTimer=setTimeout(()=>{el.textContent='';},5000);
}
async function registerApi(path,data,accessToken=''){
  const response=await fetch('/api/v1/'+path,{method:data?'POST':'GET',headers:{...(data?{'Content-Type':'application/json'}:{}),...(accessToken?{Authorization:'Bearer '+accessToken}:{})},...(data?{body:JSON.stringify(data)}:{}),cache:'no-store',signal:AbortSignal.timeout(45000)});
  let result;try{result=await response.json();}catch{throw Error('服务暂时不可用，请稍后重试。');}
  if(!response.ok)throw Error(result.error || '请求失败。');return result;
}
async function registerOperation(operation){
  if(registerBusy)return;registerBusy=true;
  const controls=[...document.querySelectorAll('input,button')],disabled=controls.map(el=>el.disabled);controls.forEach(el=>el.disabled=true);
  registerNotice('正在处理，请稍候…','',true);
  try{await operation();}catch(error){registerNotice(error.name==='TimeoutError'?'请求等待超时。如果已收到邮件，可用邮件中的申请编号继续验证。':error.message,'error');}
  finally{controls.forEach((el,index)=>el.disabled=disabled[index]);registerBusy=false;}
}
function registerChallenge(result){
  registerEl('register-challenge').value=result.challenge_id;registerEl('register-code').value='';
  registerEl('register-request-form').hidden=true;registerEl('register-verify-form').hidden=false;
  registerEl('register-email-note').textContent='验证码已发送到 '+result.email+'，'+Math.max(1,Math.ceil(result.expires_in/60))+' 分钟内有效。';
  registerNotice(result.message,'success');
}
registerEl('register-request-form').onsubmit=event=>{event.preventDefault();registerOperation(async()=>{
  registerChallenge(await registerApi('registration/request',{player:registerEl('register-player').value.trim(),email:registerEl('register-email').value.trim()}));
});};
registerEl('register-verify-form').onsubmit=event=>{event.preventDefault();registerOperation(async()=>{
  if(registerEl('register-password').value!==registerEl('register-password-confirm').value)throw Error('两次输入的密码不一致。');
  const result=await registerApi('registration/verify',{challenge_id:registerEl('register-challenge').value.trim(),code:registerEl('register-code').value.trim(),password:registerEl('register-password').value});
  registerEl('register-password').value='';registerEl('register-password-confirm').value='';
  registerToken=result.access_token;
  registerEl('register-verify-form').hidden=true;registerEl('register-result').hidden=false;
  registerEl('register-result-player').textContent='玩家名：'+result.account.player;registerEl('register-result-email').textContent='邮箱：'+result.account.email;
  registerNotice('账号已注册。','success');
});};
registerEl('register-have-code').onclick=()=>{registerEl('register-request-form').hidden=true;registerEl('register-verify-form').hidden=false;registerEl('register-challenge').focus();};
registerEl('register-resend').onclick=()=>registerOperation(async()=>{registerChallenge(await registerApi('registration/resend',{challenge_id:registerEl('register-challenge').value.trim()}));});
(async()=>{
  try{registerInfo=await registerApi('registration/info');registerEl('register-title').textContent='加入 '+registerInfo.site_name;document.title=registerInfo.site_name+' · 账号注册';
    if(!registerInfo.enabled){registerNotice('账号注册暂未开放，请联系管理员。','error',true);}
    else for(const el of document.querySelectorAll('input,button'))el.disabled=false;
  }catch(error){registerNotice(error.message,'error',true);for(const el of document.querySelectorAll('input,button'))el.disabled=true;}
})();
