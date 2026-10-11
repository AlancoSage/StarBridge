'use strict';
let operationBusy=false,scheduleLoading=false,whitelistLoading=false;
let scheduleCurrent=null,scheduleDraft=false,whitelistCurrent=null,whitelistDialogDraft=false;
let whitelistSettings=null,whitelistDraft=false,whitelistPage=1;
let scheduleData=null,operationServers=null;
const operationStatus={running:'执行中',submitted:'等待游戏端确认',success:'已完成',failed:'失败',skipped:'已跳过',interrupted:'未完成，未重放',unconfirmed:'结果未确认',paused:'已暂停',invalid:'定义损坏'};
const whitelistStatus={pending:'待审核',approved:'已批准，待下发',submitted:'等待游戏端确认',success:'已加入白名单',rejected:'已拒绝',failed:'执行失败',unconfirmed:'执行未确认',cancelled:'下发已撤销'};
const taskActions={qq_message:'群公告',game_message:'游戏公告',command:'预设命令',backup:'创建备份'};
window.operationHasDraft=()=>scheduleDraft||whitelistDraft||whitelistDialogDraft;
const operationTime=value=>value?new Date(value*1000).toLocaleString():'—';
const operationServer=id=>(operationServers||saved?.servers||[]).find(s=>s.id===id);
window.resetOperations=()=>{scheduleData=null;operationServers=null;whitelistSettings=null;whitelistDraft=false;scheduleDraft=false;whitelistDialogDraft=false;};

function schedulePermitted(definition,plugin){
  if(!plugin?.enabled||plugin.status!=='running')return false;
  const policy=plugin.permissions,capability={qq_message:'send_group',game_message:'send_game',command:'execute_commands',backup:'create_backups'}[definition.action];
  return policy[capability]&&(definition.action==='backup'||!policy.servers.length||policy.servers.includes(definition.server))&&(definition.action!=='qq_message'||!policy.groups.length||policy.groups.includes(definition.group));
}

async function operationMutation(target,action){
  if(operationBusy)return false;
  operationBusy=true;
  const controls=[...document.querySelectorAll('#view-schedules button,#view-whitelist button,#view-whitelist input,#view-whitelist select,#schedule-dialog button,#schedule-dialog input,#schedule-dialog select,#schedule-dialog textarea,#whitelist-dialog button,#whitelist-dialog input,#whitelist-dialog select')];
  const disabled=controls.map(el=>el.disabled);controls.forEach(el=>el.disabled=true);
  notice(target,'正在处理…','',{persistent:true});
  try{await action();notice(target,'已保存。','success');return true;}
  catch(error){notice(target,error.message,'error');return false;}
  finally{controls.forEach((el,i)=>el.disabled=disabled[i]);operationBusy=false;}
}

window.loadSchedules=async function(){
  if(!token||scheduleLoading||operationBusy||$('schedule-dialog').open)return;scheduleLoading=true;
  try{
    const data=await api('/api/schedules');if(operationBusy||$('schedule-dialog').open)return;
    scheduleData=data;operationServers=data.servers;
    const enabled=data.plugin?.enabled&&data.plugin?.status==='running';
    setText('schedule-plugin-status',enabled?'已启用':'已暂停');$('schedule-plugin-status').className='pill'+(enabled?' green':'');
    setText('schedule-plugin-description',data.plugin?.error||(enabled?'任务按各自的开关和时间运行，执行时检查插件动作权限。':'插件已停用，自动执行和立即执行均暂停；任务与执行记录保留。'));
    setText('schedule-plugin-toggle',enabled?'停用插件':'启用插件');$('schedule-plugin-toggle').disabled=!data.plugin||data.plugin.status==='error';
    renderChanged('schedule-list',{tasks:data.tasks,plugin:data.plugin},()=>{
      $('schedule-list').replaceChildren(...data.tasks.map(task=>{
        const d=task.definition,card=node('article','','extension-card'),head=node('div','','section-head');
        head.append(node('h3',d?.name||'损坏的任务'),node('span',d?.enabled?(enabled?'已启用':'等待插件启用'):'已停用','pill'+(d?.enabled&&enabled?' green':'')));card.append(head);
        if(d){const days=d.weekdays.length===7?'每天':'每周'+d.weekdays.map(day=>['一','二','三','四','五','六','日'][day-1]).join('、');card.append(node('p',d.schedule==='interval'?`每 ${d.interval_minutes} 分钟`:`${days} · ${d.clock}（北京时间）`,'muted'),node('p',taskActions[d.action]+(d.action==='backup'?'':` · ${operationServer(d.server)?.name||d.server}`),'hint'));
          card.append(node('p',(d.enabled&&enabled?'下次：'+operationTime(task.next_run):'启用插件与任务后开始计时')+' · 上次：'+operationTime(task.last_run),'hint'));
        }
        if(task.detail)card.append(node('p',(operationStatus[task.status]||task.status)+' · '+task.detail,'hint'));
        const actions=node('div','','extension-actions');
        if(d){actions.append(button('编辑',()=>openSchedule(task)),button(d.enabled?'停用':'启用',async()=>{
          if(await operationMutation('schedule-notice',()=>api('/api/schedules/'+task.id,{method:'PUT',body:JSON.stringify({revision:task.revision,definition:{...d,enabled:!d.enabled}})})))await loadSchedules();
        }));const immediate=button('立即执行',async()=>{
          if(!confirm('立即执行「'+d.name+'」？这会发送公告、执行预设命令或创建备份。'))return;
          let result;
          if(await operationMutation('schedule-notice',async()=>{result=await api('/api/schedules/'+task.id+'/run',{method:'POST',body:JSON.stringify({revision:task.revision}),signal:AbortSignal.timeout(120000)});})){await loadSchedules();notice('schedule-notice',result.detail,result.status==='failed'?'error':'success');}
        });immediate.disabled=!schedulePermitted(d,data.plugin);immediate.title=immediate.disabled?'请先启用插件并授予对应动作和目标权限':'';actions.append(immediate);}
        actions.append(button('删除',async()=>{
          if(confirm('删除这项定时任务？执行记录会保留。')&&await operationMutation('schedule-notice',()=>api('/api/schedules/'+task.id,{method:'DELETE',body:JSON.stringify({revision:task.revision})})))await loadSchedules();
        },'danger small'));card.append(actions);return card;
      }));
      if(!data.tasks.length)$('schedule-list').append(node('p','还没有定时任务，先安排一次公告或备份吧。','log-empty'));
    });
    renderChanged('schedule-runs',data.runs,()=>{
      $('schedule-runs').replaceChildren(...data.runs.map(run=>{const row=node('article'),body=node('div');body.append(node('strong',run.name),node('p',operationTime(run.started),'hint'),node('p',run.detail,'muted'));row.append(body,node('span',operationStatus[run.status]||run.status,'pill'+(run.status==='success'?' green':'')));return row;}));
      if(!data.runs.length)$('schedule-runs').append(node('p','任务执行后，结果会显示在这里。','log-empty'));
    });
  }catch(error){notice('schedule-notice',error.message,'error');}finally{scheduleLoading=false;}
};
function populateOperationServers(id,value=''){
  const select=$(id);select.replaceChildren(...(operationServers||saved?.servers||[]).map(s=>new Option(s.name,s.id)));
  if(!select.options.length)select.append(new Option('请先添加服务器',''));
  if(value)select.value=value;
}
function scheduleVisibility(){
  const daily=$('schedule-kind').value==='daily',action=$('schedule-action').value;
  $('schedule-interval-field').hidden=daily;$('schedule-clock-field').hidden=!daily;$('schedule-days-field').hidden=!daily;
  $('schedule-interval').disabled=daily;$('schedule-clock').disabled=!daily;
  $('schedule-server-field').hidden=action==='backup';$('schedule-group-field').hidden=action!=='qq_message';$('schedule-command-field').hidden=action!=='command';$('schedule-message-field').hidden=!['qq_message','game_message'].includes(action);
  $('schedule-server').required=action!=='backup';$('schedule-server').disabled=action==='backup';$('schedule-group').required=action==='qq_message';$('schedule-group').disabled=action!=='qq_message';$('schedule-command').required=action==='command';$('schedule-command').disabled=action!=='command';$('schedule-message').required=['qq_message','game_message'].includes(action);$('schedule-message').disabled=!$('schedule-message').required;
  $('schedule-message').maxLength=action==='game_message'?600:2000;
}
function scheduleTargets(group='',command=''){
  const server=operationServer($('schedule-server').value);
  $('schedule-group').replaceChildren(...(server?.groups||[]).map(g=>new Option('QQ 群 '+g,g)));
  $('schedule-command').replaceChildren(...Object.keys(server?.commands||{}).map(c=>new Option(c,c)));
  if(group)$('schedule-group').value=group;if(command)$('schedule-command').value=command;
}
function openSchedule(task=null){
  if(operationBusy)return;scheduleCurrent=task;scheduleDraft=false;
  const d=task?.definition||{name:'',enabled:false,schedule:'interval',interval_minutes:60,clock:'08:00',weekdays:[1,2,3,4,5,6,7],action:'backup',server:'',group:'',command:'',message:''};
  $('schedule-title').textContent=task?'编辑定时任务':'新建定时任务';$('schedule-name').value=d.name;$('schedule-kind').value=d.schedule;$('schedule-interval').value=d.interval_minutes;$('schedule-clock').value=d.clock;$('schedule-action').value=d.action;$('schedule-message').value=d.message;$('schedule-enabled').checked=d.enabled;
  populateOperationServers('schedule-server',d.server);scheduleTargets(d.group,d.command);
  $('schedule-days').replaceChildren(...['一','二','三','四','五','六','日'].map((day,i)=>{const label=node('label','周'+day),input=node('input');input.type='checkbox';input.value=i+1;input.checked=d.weekdays.includes(i+1);label.prepend(input);return label;}));
  scheduleVisibility();notice('schedule-dialog-notice','');$('schedule-dialog').showModal();
}
function closeOperationDialog(name){
  if(operationBusy)return;
  const hasDraft=name==='schedule'?scheduleDraft:whitelistDialogDraft;
  if(hasDraft&&!confirm('尚未保存，确定放弃修改？'))return;
  if(name==='schedule')scheduleDraft=false;else whitelistDialogDraft=false;
  $(name+'-dialog').close();
}
$('schedule-form').oninput=()=>scheduleDraft=true;
$('schedule-form').onchange=()=>scheduleDraft=true;
$('schedule-kind').onchange=scheduleVisibility;$('schedule-action').onchange=scheduleVisibility;$('schedule-server').onchange=()=>scheduleTargets();
$('schedule-form').onsubmit=async event=>{
  event.preventDefault();const definition={name:$('schedule-name').value,enabled:$('schedule-enabled').checked,schedule:$('schedule-kind').value,interval_minutes:Number($('schedule-interval').value),clock:$('schedule-clock').value,weekdays:[...$('schedule-days').querySelectorAll('input:checked')].map(el=>Number(el.value)),action:$('schedule-action').value,server:$('schedule-server').value,group:$('schedule-group').value,command:$('schedule-command').value,message:$('schedule-message').value};
  if(await operationMutation('schedule-dialog-notice',()=>api('/api/schedules'+(scheduleCurrent?'/'+scheduleCurrent.id:''),{method:scheduleCurrent?'PUT':'POST',body:JSON.stringify({definition,revision:scheduleCurrent?.revision})}))){scheduleDraft=false;$('schedule-dialog').close();await loadSchedules();notice('schedule-notice','任务已保存。','success');}
};
$('schedule-add').onclick=()=>openSchedule();$('schedule-refresh').onclick=()=>loadSchedules();
$('schedule-plugin-toggle').onclick=async()=>{
  if(!scheduleData?.plugin)return;
  const enabled=!scheduleData.plugin.enabled;
  if(!enabled&&!confirm('停用定时任务插件后，所有任务将暂停；已经发送或下发的操作继续等待结果。是否继续？'))return;
  if(await operationMutation('schedule-notice',()=>api('/api/schedules/plugin',{method:'PUT',body:JSON.stringify({enabled,revision:scheduleData.plugin_revision})}))){await loadSchedules();notice('schedule-notice',enabled?'定时任务插件已启用。暂停期间错过的任务已跳过。':'定时任务插件已停用，任务与记录已保留。','success');}
};

function renderWhitelistSettings(data){
  if(whitelistDraft)return;whitelistSettings=data;
  const d=data.settings;$('whitelist-enabled').checked=d.enabled;$('whitelist-registered').checked=d.require_registered;$('whitelist-bound').checked=d.require_bound;$('whitelist-cooldown').value=d.cooldown_minutes;$('whitelist-max').value=d.max_pending;
  if(data.error)notice('whitelist-notice',data.error,'error',{persistent:true});
  setText('whitelist-draft-label','申请设置单独保存，立即生效。');
}
window.loadWhitelist=async function(){
  if(!token||whitelistLoading||operationBusy||$('whitelist-dialog').open)return;whitelistLoading=true;
  try{
    const data=await api('/api/whitelist?status='+encodeURIComponent($('whitelist-filter').value)+'&page='+whitelistPage);if(operationBusy||$('whitelist-dialog').open)return;
    renderWhitelistSettings(data);setText('whitelist-total',data.total+' 项申请');setText('whitelist-page',`第 ${data.page} / ${Math.max(1,Math.ceil(data.total/25))} 页`);$('whitelist-prev').disabled=whitelistPage<=1;$('whitelist-next').disabled=whitelistPage*25>=data.total;
    renderChanged('whitelist-list',data.applications,()=>{
      $('whitelist-list').replaceChildren(...data.applications.map(app=>{
        const row=node('article'),body=node('div'),head=node('div','','extension-actions');head.append(node('strong',app.player),node('span',whitelistStatus[app.status]||app.status,'pill'+(app.status==='success'?' green':'')));body.append(head,node('p',(operationServer(app.server)?.name||app.server)+' · QQ '+app.qq+' · '+operationTime(app.created),'hint'),node('p',app.reason||'没有填写申请理由','muted'));if(app.review)body.append(node('p',app.review,'hint'));
        if(app.review_note&&app.review_note!==app.review)body.append(node('p','审核备注：'+app.review_note,'hint'));
        row.append(body);if(['pending','approved','failed','unconfirmed','cancelled'].includes(app.status))row.append(button(app.status==='pending'?'审核':'重试下发',()=>openWhitelist(app)));return row;
      }));
      if(!data.applications.length)$('whitelist-list').append(node('p','暂无符合条件的申请。','log-empty'));
    });
  }catch(error){notice('whitelist-notice',error.message,'error');}finally{whitelistLoading=false;}
};
$('whitelist-settings-form').oninput=()=>{whitelistDraft=true;setText('whitelist-draft-label','有尚未保存的申请设置');};
$('whitelist-settings-form').onchange=$('whitelist-settings-form').oninput;
$('whitelist-settings-form').onsubmit=async event=>{
  event.preventDefault();if(!whitelistSettings)return;
  const settings={enabled:$('whitelist-enabled').checked,require_registered:$('whitelist-registered').checked,require_bound:$('whitelist-bound').checked,cooldown_minutes:Number($('whitelist-cooldown').value),max_pending:Number($('whitelist-max').value)};
  let result;if(await operationMutation('whitelist-notice',async()=>{result=await api('/api/whitelist/settings',{method:'PUT',body:JSON.stringify({settings,revision:whitelistSettings.revision})});})){whitelistDraft=false;renderWhitelistSettings(result);}
};
$('whitelist-settings-reload').onclick=async()=>{if(whitelistDraft&&!confirm('放弃未保存的申请设置？'))return;whitelistDraft=false;await loadWhitelist();};
function openWhitelist(app=null){
  if(operationBusy)return;whitelistCurrent=app;whitelistDialogDraft=false;
  $('whitelist-title').textContent=app?'审核白名单申请':'代提交白名单申请';$('whitelist-create-fields').hidden=!!app;
  for(const id of ['whitelist-server','whitelist-player','whitelist-qq'])$(id).disabled=!!app;
  $('whitelist-target').hidden=!app;if(app)setText('whitelist-target',app.player+' · QQ '+app.qq+' · '+(operationServer(app.server)?.name||app.server));
  populateOperationServers('whitelist-server');$('whitelist-player').value='';$('whitelist-qq').value='';$('whitelist-note').value='';$('whitelist-note-label').textContent=app?'审核备注':'申请理由';$('whitelist-uuid').value=app?.identity||'';
  $('whitelist-uuid-field').hidden=!app;$('whitelist-review-field').hidden=!app;
  for(const option of $('whitelist-review-action').options)option.disabled=app?app.status==='pending'?option.value==='retry':option.value!=='retry':false;
  $('whitelist-review-action').value=app?.status==='pending'?'approve':'retry';$('whitelist-submit').textContent=app?'确认审核':'提交申请';notice('whitelist-dialog-notice','');$('whitelist-dialog').showModal();
}
$('whitelist-form').oninput=()=>whitelistDialogDraft=true;$('whitelist-form').onchange=()=>whitelistDialogDraft=true;
$('whitelist-form').onsubmit=async event=>{
  event.preventDefault();const app=whitelistCurrent,action=$('whitelist-review-action').value;
  if(app&&!confirm(action==='reject'?'确认拒绝这个申请？':'确认批准 / 重试下发？游戏端执行成功后会加入白名单。'))return;
  const url=app?'/api/whitelist/'+app.id+'/review':'/api/whitelist';const payload=app?{action,revision:app.revision,note:$('whitelist-note').value,uuid:$('whitelist-uuid').value.trim()}:{server:$('whitelist-server').value,player:$('whitelist-player').value,qq:$('whitelist-qq').value,reason:$('whitelist-note').value};
  if(await operationMutation('whitelist-dialog-notice',()=>api(url,{method:'POST',body:JSON.stringify(payload)}))){whitelistDialogDraft=false;$('whitelist-dialog').close();await loadWhitelist();notice('whitelist-notice',app?'审核已保存，执行状态请查看申请记录。':'申请已提交。','success');}
};
$('whitelist-add').onclick=()=>openWhitelist();$('whitelist-refresh').onclick=()=>loadWhitelist();$('whitelist-filter').onchange=()=>{whitelistPage=1;loadWhitelist();};$('whitelist-prev').onclick=()=>{whitelistPage--;loadWhitelist();};$('whitelist-next').onclick=()=>{whitelistPage++;loadWhitelist();};
for(const name of ['schedule','whitelist']){for(const suffix of ['close','cancel'])$(name+'-'+suffix).onclick=()=>closeOperationDialog(name);$(name+'-dialog').addEventListener('cancel',event=>{event.preventDefault();closeOperationDialog(name);});}
async function operationsGuide(){
  try{const response=await fetch('/api/operations/guide',{headers:{Authorization:'Bearer '+token},cache:'no-store',signal:AbortSignal.timeout(10000)});if(!response.ok)throw Error('文档下载失败。');const url=URL.createObjectURL(await response.blob()),link=node('a');link.href=url;link.download='Myrinbot-automation-and-whitelist.md';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  catch(error){notice(document.body.dataset.view==='schedules'?'schedule-notice':'whitelist-notice',error.message,'error');}
}
$('schedule-guide').onclick=operationsGuide;$('whitelist-guide').onclick=operationsGuide;
$('whitelist-plugin').onclick=()=>$('authentication-download').onclick();
