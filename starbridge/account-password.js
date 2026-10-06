'use strict';
const passwordEl=id=>document.getElementById(id);
let passwordBusy=false,passwordNoticeTimer;
for(const el of document.querySelectorAll('input,button'))el.disabled=true;
function passwordNotice(text,type='',persistent=false){clearTimeout(passwordNoticeTimer);const el=passwordEl('password-notice');el.textContent=text;el.className='notice '+type;if(text&&!persistent)passwordNoticeTimer=setTimeout(()=>{el.textContent='';},5000);}
async function passwordApi(path,data){
  const response=await fetch('/api/v1/account/password/'+path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:{},...(data?{body:JSON.stringify(data)}:{}),cache:'no-store',signal:AbortSignal.timeout(45000)});
  const result=await response.json();if(!response.ok)throw Error(result.error||'请求失败。');return result;
}
async function passwordOperation(action){
  if(passwordBusy)return;passwordBusy=true;
  const controls=[...document.querySelectorAll('input,button')],disabled=controls.map(el=>el.disabled);controls.forEach(el=>el.disabled=true);
  passwordNotice('正在处理，请稍候…','',true);
  try{await action();}catch(error){passwordNotice(error.name==='TimeoutError'?'请求超时，请检查是否收到邮件后再重试。':error.message,'error');}
  finally{controls.forEach((el,index)=>el.disabled=disabled[index]);passwordBusy=false;}
}
passwordEl('password-request-form').onsubmit=event=>{event.preventDefault();passwordOperation(async()=>{
  const result=await passwordApi('request',{player:passwordEl('password-player').value.trim(),email:passwordEl('password-email').value.trim()});
  passwordEl('password-challenge').value=result.challenge_id;passwordEl('password-code').value='';passwordEl('password-request-form').hidden=true;passwordEl('password-verify-form').hidden=false;passwordNotice(result.message,'success');
});};
passwordEl('password-verify-form').onsubmit=event=>{event.preventDefault();passwordOperation(async()=>{
  if(passwordEl('password-new').value!==passwordEl('password-confirm').value)throw Error('两次输入的密码不一致。');
  const result=await passwordApi('verify',{challenge_id:passwordEl('password-challenge').value.trim(),code:passwordEl('password-code').value.trim(),password:passwordEl('password-new').value});
  passwordEl('password-new').value='';passwordEl('password-confirm').value='';passwordEl('password-verify-form').hidden=true;passwordEl('password-result').hidden=false;passwordNotice(result.message,'success');
});};
passwordEl('password-have-code').onclick=()=>{passwordEl('password-request-form').hidden=true;passwordEl('password-verify-form').hidden=false;passwordEl('password-challenge').focus();};
passwordEl('password-back').onclick=()=>{passwordEl('password-request-form').hidden=false;passwordEl('password-verify-form').hidden=true;passwordEl('password-new').value='';passwordEl('password-confirm').value='';};
(async()=>{try{const info=await passwordApi('info');if(!info.available){passwordNotice('密码设置邮件尚未配置，请联系管理员。','error',true);return;}for(const el of document.querySelectorAll('input,button'))el.disabled=false;}catch(error){passwordNotice(error.message,'error',true);}})();
