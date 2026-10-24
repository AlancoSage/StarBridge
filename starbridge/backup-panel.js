'use strict';
let backupBusy=false,backupLoading=false,backupPreview=null,backupCanRestore=false;
function backupSize(bytes){return bytes>=1048576?(bytes/1048576).toFixed(1)+' MiB':(bytes/1024).toFixed(1)+' KiB';}
async function backupApi(path,options={}){return api(path,{signal:AbortSignal.timeout(120000),...options});}
function backupControls(locked){
  for(const id of ['backup-create','backup-upload','backup-refresh','backup-cancel','backup-file'])$(id).disabled=locked;
  $('backup-restore').disabled=locked||!backupCanRestore;
  $('backup-list').querySelectorAll('button').forEach(el=>el.disabled=locked);
}
async function backupDownload(id){
  const response=await fetch('/api/backups/'+id,{headers:{Authorization:'Bearer '+token},cache:'no-store',signal:AbortSignal.timeout(120000)});
  if(!response.ok)throw Error('备份下载失败，请刷新列表后重试。');
  const url=URL.createObjectURL(await response.blob()),link=node('a');link.href=url;link.download='VexBot-'+id+'.zip';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
window.loadBackups=async function(){
  if(!token||backupLoading||backupBusy)return;backupLoading=true;
  try{
    const data=await api('/api/backups');if(backupBusy)return;backupCanRestore=data.can_restore;
    setText('backup-total',data.backups.length+' 份备份 · '+backupSize(data.total_bytes||0));
    renderChanged('backup-list',data.backups,()=>{
      $('backup-list').replaceChildren(...data.backups.map(entry=>{
        const row=node('tr');for(const value of [new Date(entry.created_at).toLocaleString(),entry.reason==='before_restore'?'恢复前安全备份':entry.reason==='scheduled'?'定时备份':entry.reason==='damaged'?'文件损坏，可删除':'手动备份',backupSize(entry.size),entry.app_version])row.append(node('td',value));
        const actions=node('td'),wrap=node('div','','backup-actions');
        if(panelIdentity?.owner)wrap.append(button('下载',()=>backupOperation(async()=>{await backupDownload(entry.id);notice('backup-notice','备份已下载。','success');})));
        wrap.append(button('删除',()=>{
          if(confirm('确认删除这份备份？已下载到本机的文件不会删除。'))backupOperation(async()=>{await backupApi('/api/backups/'+entry.id,{method:'DELETE'});notice('backup-notice','备份已删除。','success');});
        },'danger small'));
        actions.append(wrap);row.append(actions);return row;
      }));
      if(!data.backups.length){const row=node('tr'),cell=node('td','还没有备份，先为社区保存一份副本。','empty-cell');cell.colSpan=5;row.append(cell);$('backup-list').append(row);}
    });
    const result=data.last_restore;
    notice('backup-result',result?new Date(result.time).toLocaleString()+' · '+result.message:'',result?.status==='success'?'success':'error',{persistent:true});
    if(!data.can_restore)notice('backup-notice','此启动方式可以导出备份，暂不支持恢复后的自动重启。','error',{persistent:true});
    backupControls(data.busy);
  }catch(error){notice('backup-notice',error.message,'error');}
  finally{backupLoading=false;}
};
async function backupOperation(operation){
  if(backupBusy)return;backupBusy=true;backupControls(true);
  notice('backup-notice','正在处理，请稍候…','',{persistent:true});
  try{await operation();}catch(error){notice('backup-notice',error.name==='TimeoutError'?'操作等待超时，请刷新列表查看结果后再试。':error.message,'error');}
  finally{backupBusy=false;backupControls(false);await window.loadBackups();}
}
$('backup-create').onclick=()=>backupOperation(async()=>{
  const result=await backupApi('/api/backups',{method:'POST'});if(panelIdentity?.owner){await backupDownload(result.id);notice('backup-notice','备份已创建并下载。','success');}else notice('backup-notice','备份已创建，包含密钥的备份由服主下载。','success');
});
$('backup-refresh').onclick=()=>window.loadBackups();
$('backup-upload').onclick=()=>{
  if(dirty||window.registrationHasDraft?.()||window.authenticationHasDraft?.()||window.bindingGateHasDraft?.()||window.extensionHasDraft?.()||window.operationHasDraft?.()||window.websiteHasDraft?.()||window.enhancementHasDraft?.()){notice('backup-notice','请先保存或放弃面板中的未保存设置，再预览恢复。','error');return;}
  $('backup-file').click();
};
$('backup-file').onchange=()=>{
  const file=$('backup-file').files[0];$('backup-file').value='';if(!file)return;
  if(file.size>64*1048576){notice('backup-notice','备份文件不能超过 64 MiB。','error');return;}
  backupOperation(async()=>{
    const result=await backupApi('/api/backups/preview',{method:'POST',headers:{'Content-Type':'application/zip'},body:file});
    backupPreview=result;$('backup-preview').hidden=false;
    setText('backup-preview-meta',new Date(result.created_at).toLocaleString()+' · VexBot '+result.app_version);
    $('backup-preview-counts').replaceChildren(...Object.entries({players:'玩家档案',accounts:'注册账号',bindings:'绑定记录',servers:'服务器',plugins:'外部插件'}).map(([key,label])=>{const item=node('div');item.append(node('strong',result.counts[key]),node('span',label));return item;}));
    const labels={players:'玩家档案',accounts:'账号',bindings:'绑定',servers:'服务器',plugins:'插件'};
    $('backup-preview-differences').replaceChildren(...Object.entries(result.differences||{}).map(([key,value])=>node('p',labels[key]+'：当前 '+value.current+' → 备份 '+value.incoming+'（'+(value.delta>0?'+':'')+value.delta+'）')));
    if(result.changed_sections?.length)$('backup-preview-differences').append(node('p','将变更的设置：'+result.changed_sections.join('、')));
    notice('backup-notice','校验通过，请检查预览内容后选择恢复。','success');
  });
};
$('backup-cancel').onclick=()=>{backupPreview=null;$('backup-preview').hidden=true;};
$('backup-restore').onclick=()=>{
  if(!backupPreview)return;
  if(dirty||window.registrationHasDraft?.()||window.authenticationHasDraft?.()||window.bindingGateHasDraft?.()||window.extensionHasDraft?.()||window.operationHasDraft?.()||window.websiteHasDraft?.()||window.enhancementHasDraft?.()){notice('backup-notice','请先保存或放弃未保存的设置。','error');return;}
  if(!confirm('确认用预览中的备份替换当前数据和业务设置？开始前会创建安全备份，随后重启服务。'))return;
  backupOperation(async()=>{
    const result=await backupApi('/api/backups/restore',{method:'POST',body:JSON.stringify({preview_id:backupPreview.preview_id})});
    backupPreview=null;$('backup-preview').hidden=true;
    notice('backup-notice',result.message,'',{persistent:true});
    // Avoid showing old configuration or polling while the service drains its active work.
    clearInterval(timer);timer=null;
    for(let count=0;count<90;count++){
      await new Promise(resolve=>setTimeout(resolve,1000));
      try{
        const data=await api('/api/backups');
        if(data.last_restore?.safety_backup===result.safety_backup){
          renderedData.clear();registrationEpoch++;authenticationEpoch++;
          registrationConfig=null;authenticationConfig=null;
          window.resetOperations?.();window.resetWebsite?.();
          renderConfig(await api('/api/config'));await refresh();startAutoRefresh();
          notice('backup-notice',data.last_restore.message,data.last_restore.status==='success'?'success':'error');return;
        }
      }catch(error){/* Service restart is expected. Keep a single low-cost polling request. */}
    }
    notice('backup-notice','恢复还未完成，请稍后刷新面板查看结果。','error',{persistent:true});
    startAutoRefresh();
  });
};
