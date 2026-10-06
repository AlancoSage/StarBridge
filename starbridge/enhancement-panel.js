'use strict';
const enhancementConfig={},enhancementDirty={},enhancementLoading={};
let managerData=null,managerSaving=false,statisticsLast=0;
window.enhancementHasDraft=()=>Object.values(enhancementDirty).some(Boolean);
function enhancementNotice(key,text,kind=''){notice(key==='monitoring'?'monitor-notice':key==='backup_policy'?'backup-policy-notice':key==='managers'?'manager-notice':'statistics-notice',text,kind);}
function simpleRows(id,rows,empty){
  renderChanged(id,rows,()=>{$(id).replaceChildren(...rows.map(parts=>{const row=node('div','','operation-history-row');for(const part of parts)row.append(node('span',part));return row;}));if(!rows.length)$(id).append(node('p',empty,'hint'));});
}
function enhancementPopulate(key,data){
  enhancementConfig[key]=data;
  if(enhancementDirty[key])return;
  const s=data.settings;
  if(key==='monitoring'){$('monitor-enabled').checked=s.enabled;$('monitor-grace').value=s.startup_grace_seconds;$('monitor-notify').checked=s.notify_groups;$('monitor-groups').value=s.groups.join(', ');}
  if(key==='statistics'){$('statistics-enabled').checked=s.enabled;$('statistics-retention').value=s.retention_days;}
  if(key==='backup_policy'){$('backup-policy-enabled').checked=s.enabled;$('backup-policy-count').value=s.keep_count;$('backup-policy-days').value=s.keep_days;$('backup-policy-manual').checked=s.protect_manual;}
}
function managerPreset(name){
  const selected=managerData?.presets[name];if(!selected)return;
  for(const input of $('manager-permissions').querySelectorAll('input'))input.checked=selected.includes(input.value);
}
function managerClear(){
  $('manager-form').reset();$('manager-id').value='';$('manager-revision').value='';$('manager-password').required=true;$('manager-enabled').checked=true;managerPreset('observer');enhancementDirty.managers=false;
}
function managerRender(data){
  managerData=data;
  if(!$('manager-permissions').children.length){
    for(const [key,label] of Object.entries(data.permissions)){const field=node('div','','field extension-check'),caption=node('label'),input=node('input');input.type='checkbox';input.value=key;input.checked=key==='status.read';input.disabled=key==='status.read';caption.append(input,document.createTextNode(' '+label));field.append(caption);$('manager-permissions').append(field);}managerClear();
  }
  $('manager-list').replaceChildren(...data.users.map(user=>{
    const row=node('article','','operation-history-row'),left=node('div');left.append(node('strong',user.username),node('p',(user.enabled?'已启用':'已停用')+' · '+user.permissions.map(key=>data.permissions[key]).join('、'),'hint'));
    const actions=node('div','','extension-actions');actions.append(button('编辑',()=>{$('manager-id').value=user.id;$('manager-revision').value=user.revision;$('manager-username').value=user.username;$('manager-password').value='';$('manager-password').required=false;$('manager-enabled').checked=!!user.enabled;$('manager-preset').value='custom';for(const input of $('manager-permissions').querySelectorAll('input'))input.checked=user.permissions.includes(input.value);$('manager-form').scrollIntoView({block:'start'});}),
      button(user.enabled?'停用':'启用',async()=>{try{managerRender(await api('/api/admin-users/'+user.id,{method:'PUT',body:JSON.stringify({revision:user.revision,enabled:!user.enabled})}));}catch(error){enhancementNotice('managers',error.message,'error');}}),
      button('删除',async()=>{if(!confirm('删除管理员 '+user.username+' 并撤销其登录？'))return;try{managerRender(await api('/api/admin-users/'+user.id,{method:'DELETE',body:JSON.stringify({revision:user.revision})}));managerClear();}catch(error){enhancementNotice('managers',error.message,'error');}},'danger small'));
    row.append(left,actions);return row;
  }));if(!data.users.length)$('manager-list').append(node('p','暂未创建团队账号，服主管理令牌仍可正常使用。','hint'));
}
function monitoringRender(data){
  enhancementPopulate('monitoring',data);
  renderChanged('monitor-alert-list',data.alerts,()=>{
    $('monitor-alert-list').replaceChildren(...data.alerts.map(alert=>{const row=node('article','','operation-history-row'),left=node('div');left.append(node('strong',alert.title),node('p',(alert.status==='resolved'?'已恢复':alert.acknowledged?'已知晓，仍待恢复':'待处理')+' · '+new Date(alert.updated*1000).toLocaleString(),'hint'));row.append(left);if(alert.status==='open'&&!alert.acknowledged)row.append(button('标记已知晓',async()=>{try{monitoringRender(await api('/api/monitoring/'+alert.id+'/ack',{method:'POST'}));}catch(error){enhancementNotice('monitoring',error.message,'error');}}));return row;}));
    if(!data.alerts.length)$('monitor-alert-list').append(node('p','尚无故障记录。启动宽限时间过后开始检查连接。','hint'));
  });
}
function statisticsChart(series){
  renderChanged('statistics-chart',series,()=>{
    const box=$('statistics-chart');box.replaceChildren();const valid=series.filter(point=>point.online_count!==null);
    if(!valid.length){box.append(node('p','尚无在线采样。连接服务器后会开始记录趋势。','hint'));setText('statistics-summary','离线期间不会记作 0 人。');return;}
    const create=(tag,attrs={},text='')=>{const element=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attrs))element.setAttribute(key,value);element.textContent=text;return element;};
    const svg=create('svg',{viewBox:'0 0 800 220',role:'presentation'}),max=Math.max(1,...valid.map(point=>point.online_count));
    for(let index=0;index<=3;index++){const y=18+index*54;svg.append(create('line',{x1:42,y1:y,x2:780,y2:y,stroke:'var(--border)'}),create('text',{x:0,y:y+4,fill:'var(--muted)','font-size':12},String(Math.round(max*(3-index)/3))));}
    let path='',start=true;
    series.forEach((point,index)=>{if(point.online_count===null){start=true;return;}const x=42+index/Math.max(1,series.length-1)*738,y=180-point.online_count/max*162;path+=(start?'M':'L')+x.toFixed(1)+' '+y.toFixed(1)+' ';start=false;});
    svg.append(create('path',{d:path,fill:'none',stroke:'var(--blue)','stroke-width':2.5,'stroke-linejoin':'round'}));
    if(valid.length===1)svg.append(create('circle',{cx:42,cy:180-valid[0].online_count/max*162,r:3,fill:'var(--blue)'}));
    svg.append(create('text',{x:42,y:208,fill:'var(--muted)','font-size':12},new Date(series[0].time*1000).toLocaleString()),create('text',{x:780,y:208,fill:'var(--muted)','font-size':12,'text-anchor':'end'},new Date(series.at(-1).time*1000).toLocaleString()));box.append(svg);
    setText('statistics-summary','采样区间平均在线人数 · 峰值 '+Math.max(...valid.map(point=>point.online_count))+' · '+series.length+' 个时间区间');
  });
}
function statisticsRender(data){
  enhancementPopulate('statistics',data);statisticsChart(data.series||[]);
  const selected=$('statistics-server').value;renderChanged('statistics-servers',data.servers,()=>{$('statistics-server').replaceChildren(new Option('全部服务器',''),...data.servers.map(server=>new Option(server.name,server.id)));$('statistics-server').value=selected;});
  simpleRows('statistics-daily',data.daily.map(day=>[day.day,day.active_players+' 位活跃玩家']),'采集开始后会显示每日活跃人数。');
  const names=Object.fromEntries(data.servers.map(server=>[server.id,server.name]));
  simpleRows('statistics-activity',data.activity.map(row=>[new Date(row.time*1000).toLocaleString(),names[row.server]||row.server,row.player,row.kind==='join'?'加入游戏':'离开游戏']),'尚无进退服记录。');
}
window.loadEnhancements=async function(name,force=false){
  if(!token||enhancementLoading[name]||document.hidden)return;
  if(name==='statistics'&&!force&&Date.now()-statisticsLast<30000)return;
  enhancementLoading[name]=true;
  try{const path=name==='managers'?'/api/admin-users':name==='monitoring'?'/api/monitoring':'/api/statistics?'+new URLSearchParams({server:$('statistics-server').value,days:$('statistics-days').value});const data=await api(path);if(name==='managers')managerRender(data);else if(name==='monitoring')monitoringRender(data);else{statisticsLast=Date.now();statisticsRender(data);}}
  catch(error){enhancementNotice(name,error.message,'error');}finally{enhancementLoading[name]=false;}
};
window.loadBackupPolicy=async()=>{if(!token||enhancementLoading.backup_policy)return;enhancementLoading.backup_policy=true;try{enhancementPopulate('backup_policy',await api('/api/backup-policy'));}catch(error){enhancementNotice('backup_policy',error.message,'error');}finally{enhancementLoading.backup_policy=false;}};
async function enhancementSave(key,form,settings){
  if(!enhancementConfig[key]||form.dataset.busy)return;form.dataset.busy='1';const controls=[...form.querySelectorAll('input,button')];controls.forEach(control=>control.disabled=true);
  try{const path=key==='backup_policy'?'/api/backup-policy':'/api/'+key;const data=await api(path,{method:'PUT',body:JSON.stringify({settings,revision:enhancementConfig[key].revision})});enhancementDirty[key]=false;enhancementPopulate(key,data);enhancementNotice(key,'设置已保存。','success');}
  catch(error){enhancementNotice(key,error.message,'error');}finally{delete form.dataset.busy;controls.forEach(control=>control.disabled=false);}
}
for(const [id,key] of [['manager-form','managers'],['monitor-form','monitoring'],['statistics-form','statistics'],['backup-policy-form','backup_policy']]){$(id).addEventListener('input',()=>enhancementDirty[key]=true);$(id).addEventListener('change',()=>enhancementDirty[key]=true);}
$('manager-new').onclick=()=>{if(enhancementDirty.managers&&!confirm('放弃未保存的管理员修改？'))return;managerClear();};
$('manager-preset').onchange=()=>managerPreset($('manager-preset').value);
$('manager-form').onsubmit=async event=>{event.preventDefault();if(managerSaving||!managerData)return;managerSaving=true;$('manager-save').disabled=true;try{const uid=$('manager-id').value,data={username:$('manager-username').value.trim(),password:$('manager-password').value,enabled:$('manager-enabled').checked,permissions:[...$('manager-permissions').querySelectorAll('input:checked')].map(input=>input.value),...(uid?{revision:Number($('manager-revision').value)}:{})};managerRender(await api('/api/admin-users'+(uid?'/'+uid:''),{method:uid?'PUT':'POST',body:JSON.stringify(data)}));managerClear();enhancementNotice('managers','管理员已保存，旧会话已撤销。','success');}catch(error){enhancementNotice('managers',error.message,'error');}finally{managerSaving=false;$('manager-save').disabled=false;}};
$('monitor-form').onsubmit=event=>{event.preventDefault();enhancementSave('monitoring',event.currentTarget,{enabled:$('monitor-enabled').checked,startup_grace_seconds:Number($('monitor-grace').value),notify_groups:$('monitor-notify').checked,groups:splitIds($('monitor-groups').value)});};
$('statistics-form').onsubmit=event=>{event.preventDefault();enhancementSave('statistics',event.currentTarget,{enabled:$('statistics-enabled').checked,retention_days:Number($('statistics-retention').value)});};
$('backup-policy-form').onsubmit=event=>{event.preventDefault();enhancementSave('backup_policy',event.currentTarget,{enabled:$('backup-policy-enabled').checked,keep_count:Number($('backup-policy-count').value),keep_days:Number($('backup-policy-days').value),protect_manual:$('backup-policy-manual').checked});};
$('backup-policy-cleanup').onclick=async()=>{if(enhancementDirty.backup_policy){enhancementNotice('backup_policy','请先保存保留规则。','error');return;}if(!confirm('按已保存的规则清理非保护备份？此操作会删除服务器上的旧 ZIP。'))return;$('backup-policy-cleanup').disabled=true;try{const result=await api('/api/backup-policy/cleanup',{method:'POST'});enhancementNotice('backup_policy','已清理 '+result.removed+' 份，释放 '+backupSize(result.bytes_freed)+'。','success');await loadBackups();}catch(error){enhancementNotice('backup_policy',error.message,'error');}finally{$('backup-policy-cleanup').disabled=false;}};
$('monitor-refresh').onclick=()=>loadEnhancements('monitoring',true);
$('statistics-refresh').onclick=()=>loadEnhancements('statistics',true);
$('statistics-server').onchange=$('statistics-days').onchange=()=>loadEnhancements('statistics',true);
$('panel-login-kind').onchange=()=>{const account=$('panel-login-kind').value==='account';$('token').hidden=account;$('token').disabled=account;$('panel-account-login').hidden=!account;for(const id of ['panel-username','panel-password']){$(id).disabled=!account;$(id).required=account;}};
