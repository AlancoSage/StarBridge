"""Bounded, low-frequency monitoring, statistics and backup retention settings."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
import time
import uuid
from .registration import RegistrationError

DEFAULTS = {
    'monitoring':{'enabled':True,'startup_grace_seconds':30,'notify_groups':False,'groups':[]},
    'statistics':{'enabled':True,'retention_days':30},
    'backup_policy':{'enabled':False,'keep_count':20,'keep_days':30,'protect_manual':True}
}


def validate_setting(key,value):
    if key not in DEFAULTS or not isinstance(value,dict) or value.keys()-DEFAULTS[key].keys():raise RegistrationError('运行设置包含未知字段')
    out=DEFAULTS[key]|value
    for field,default in DEFAULTS[key].items():
        if type(default) is bool and type(out[field]) is not bool:raise RegistrationError('设置开关必须是布尔值')
    limits={'monitoring':{'startup_grace_seconds':(15,300)},'statistics':{'retention_days':(1,90)},
            'backup_policy':{'keep_count':(1,100),'keep_days':(1,365)}}[key]
    for field,(low,high) in limits.items():
        if type(out[field]) is not int or not low<=out[field]<=high:raise RegistrationError(f'{field} 范围需为 {low}–{high}')
    if key=='monitoring':
        groups=out['groups']
        if not isinstance(groups,list) or len(groups)>10 or any(not isinstance(g,str) or not re.fullmatch(r'[1-9][0-9]{0,19}',g) for g in groups) or len(groups)!=len(set(groups)):raise RegistrationError('提醒群最多 10 个，需为不重复的群号')
        if out['notify_groups'] and not groups:raise RegistrationError('启用群提醒前需要填写接收群')
    return out


class RuntimeFeatures:
    def __init__(self,state):
        self.state=state;self.db=state['store'].db;self.started=time.time()
        self.mail_failed=bool(self.db.execute("SELECT 1 FROM health_alerts WHERE source='smtp' AND status='open' LIMIT 1").fetchone());self.next_sample=0;self.next_cleanup=0;self.next_notify=0
        self.next_sanctions = 0

    def config(self,key):
        row=self.db.execute('SELECT value,revision FROM runtime_settings WHERE key=?',(key,)).fetchone()
        return {'settings':validate_setting(key,json.loads(row['value'])) if row else deepcopy(DEFAULTS[key]),'revision':row['revision'] if row else 0}

    def save(self,key,value,revision):
        current=self.config(key)
        if type(revision) is not int or revision!=current['revision']:raise RegistrationError('设置已变化，请刷新后保存',409)
        value=validate_setting(key,value)
        with self.db:self.db.execute('INSERT INTO runtime_settings VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,revision=excluded.revision',
                                    (key,json.dumps(value),revision+1))
        self.state['store'].audit('settings','保存运行设置 '+key)
        return self.config(key)

    def alert(self,source,title,failed,now=None):
        now=time.time() if now is None else now
        row=self.db.execute("SELECT * FROM health_alerts WHERE source=? AND status='open' ORDER BY created DESC LIMIT 1",(source,)).fetchone()
        with self.db:
            if failed and not row:
                self.db.execute('INSERT INTO health_alerts(id,source,title,status,acknowledged,created,updated) VALUES(?,?,?,\'open\',0,?,?)',(uuid.uuid4().hex,source,title,now,now))
                self.state['store'].audit('alert',title)
            elif not failed and row:
                self.db.execute("UPDATE health_alerts SET status='resolved',updated=? WHERE id=?",(now,row['id']))
                self.state['store'].audit('alert',title+' · 已恢复')
            self.db.execute("DELETE FROM health_alerts WHERE id IN (SELECT id FROM health_alerts WHERE status='resolved' ORDER BY updated DESC LIMIT -1 OFFSET 500)")

    def mail_result(self,ok):
        self.mail_failed=not ok
        if self.config('monitoring')['settings']['enabled']:self.alert('smtp','邮件发送失败，请检查 SMTP 配置',not ok)

    def monitoring(self):
        return self.config('monitoring')|{'alerts':[dict(row) for row in self.db.execute('SELECT * FROM health_alerts ORDER BY updated DESC LIMIT 100')],
            'open_count':self.db.execute("SELECT count(*) FROM health_alerts WHERE status='open'").fetchone()[0]}

    def acknowledge(self,alert_id):
        with self.db:
            if not self.db.execute('UPDATE health_alerts SET acknowledged=1 WHERE id=?',(alert_id,)).rowcount:raise RegistrationError('提醒不存在',404)
        return self.monitoring()

    async def check(self,now=None):
        now=time.time() if now is None else now;policy=self.config('monitoring')['settings']
        if now >= self.next_sanctions and not self.state.get('maintenance'):
            self.next_sanctions = now + 30
            if self.state.get('sanctions'): self.state['sanctions'].reconcile()
        if policy['enabled'] and now-self.started>=policy['startup_grace_seconds']:
            self.alert('onebot','QQ 机器人连接中断',not self.state['onebot'].connected,now)
            configured=self.state['bot'].servers
            for sid,server in configured.items():self.alert('server:'+sid,server['name']+' · 游戏桥接失联',not self.state['bot'].online(sid),now)
            for row in self.db.execute("SELECT DISTINCT source FROM health_alerts WHERE status='open' AND source LIKE 'server:%'").fetchall():
                if row['source'][7:] not in configured:self.alert(row['source'],'服务器已移除',False,now)
            self.alert('smtp','邮件发送失败，请检查 SMTP 配置',self.mail_failed,now)
        if self.config('statistics')['settings']['enabled'] and now>=self.next_sample:
            self.sample(now);self.next_sample=now+60
        if now>=self.next_cleanup:
            self.prune_statistics(now);self.next_cleanup=now+3600
            backups=self.state.get('backups')
            if backups and backups.root is not None and self.config('backup_policy')['settings']['enabled'] and not backups.busy and not self.state.get('maintenance'):
                await backups.cleanup_policy()
        if policy['enabled'] and policy['notify_groups'] and self.state['onebot'].connected and now>=self.next_notify:
            self.next_notify=now+60
            rows=self.db.execute("SELECT * FROM health_alerts WHERE status='open' AND notified=0 AND acknowledged=0 ORDER BY created LIMIT 5").fetchall()
            if rows:
                text='Myrinbot故障提醒\n'+'\n'.join(row['title'] for row in rows)+'\n请在管理面板查看。'
                try:
                    for group in policy['groups']:await self.state['onebot'].send_group(group,text)
                except (ConnectionError,RuntimeError,TimeoutError):
                    self.state['store'].audit('alert','故障群提醒发送失败，将在后续检查中重试')
                else:
                    with self.db:self.db.executemany('UPDATE health_alerts SET notified=1 WHERE id=?',[(row['id'],) for row in rows])

    async def worker(self):
        while True:
            try:
                if not self.state.get('maintenance'):await self.check()
            except Exception as exc:self.state['store'].audit('error','运行维护检查失败：'+type(exc).__name__)
            await asyncio.sleep(5)

    def sample(self,now):
        day=datetime.fromtimestamp(now,timezone.utc).date().isoformat();bucket=int(now//60)*60
        with self.db:
            for sid in self.state['bot'].servers:
                online=self.state['bot'].online(sid);snap=self.state['bot'].snapshots.get(sid,{})
                self.db.execute('INSERT INTO server_samples VALUES(?,?,?,?,?) ON CONFLICT(server,bucket) DO UPDATE SET connected=excluded.connected,online_count=excluded.online_count,max_players=excluded.max_players',
                                (sid,bucket,int(online),len(snap.get('players',[])) if online else None,snap.get('max_players') if online else None))
                if online:
                    records={record['name']:record['uuid'] for record in snap.get('player_records',[]) if record.get('online')}
                    for name in snap.get('players',[])[:2000]:
                        identity=hashlib.sha256(records.get(name,name.lower()).encode()).hexdigest()
                        self.db.execute('INSERT OR IGNORE INTO server_daily_players VALUES(?,?,?)',(sid,day,identity))

    def event(self,sid,event):
        if event['kind'] not in ('join','quit') or not self.config('statistics')['settings']['enabled']:return
        now=time.time();day=datetime.fromtimestamp(now,timezone.utc).date().isoformat()
        identity=hashlib.sha256(event.get('uuid',event['player'].lower()).encode()).hexdigest()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO server_activity VALUES(?,?,?,?,?)',('mc:'+sid+':'+event['id'],sid,event['player'][:32],event['kind'],now))
            self.db.execute('INSERT OR IGNORE INTO server_daily_players VALUES(?,?,?)',(sid,day,identity))
            self.db.execute('DELETE FROM server_activity WHERE id IN (SELECT id FROM server_activity ORDER BY time DESC LIMIT -1 OFFSET 10000)')

    def prune_statistics(self,now):
        cutoff=now-self.config('statistics')['settings']['retention_days']*86400
        day=datetime.fromtimestamp(cutoff,timezone.utc).date().isoformat()
        with self.db:
            self.db.execute('DELETE FROM server_samples WHERE bucket<?',(cutoff,));self.db.execute('DELETE FROM server_activity WHERE time<?',(cutoff,))
            self.db.execute('DELETE FROM server_daily_players WHERE day<?',(day,))

    def statistics(self,sid='',days=1):
        if sid and sid not in self.state['bot'].servers:raise RegistrationError('服务器不存在',404)
        if days not in (1,7,30):raise RegistrationError('统计范围需为 1、7 或 30 天')
        cutoff=time.time()-days*86400;step=300 if days==1 else 1800 if days==7 else 10800
        args=[cutoff];clause='bucket>=?'
        if sid:clause+=' AND server=?';args.append(sid)
        else:
            ids=list(self.state['bot'].servers)
            if not ids:return self.config('statistics')|{'series':[],'daily':[],'activity':[],'servers':[]}
            clause+=' AND server IN ('+','.join('?' for _ in ids)+')';args.extend(ids)
        # Average each server separately before summing, so extra heartbeats cannot inflate totals.
        series=[{'time':row[0],'online_count':round(row[1],1) if row[1] is not None else None,'connected_servers':row[2]}
                for row in self.db.execute('SELECT period,sum(online_count),sum(connected) FROM (SELECT (bucket / ?) * ? AS period,server,avg(online_count) AS online_count,max(connected) AS connected FROM server_samples WHERE '+clause+' GROUP BY period,server) GROUP BY period ORDER BY period',(step,step,*args))]
        server_ids=[sid] if sid else list(self.state['bot'].servers);marks=','.join('?' for _ in server_ids)
        daily=[{'day':row[0],'active_players':row[1]} for row in self.db.execute('SELECT day,count(DISTINCT identity) FROM server_daily_players WHERE day>=? AND server IN ('+marks+') GROUP BY day ORDER BY day',(datetime.fromtimestamp(cutoff,timezone.utc).date().isoformat(),*server_ids))]
        activity=[dict(row) for row in self.db.execute('SELECT server,player,kind,time FROM server_activity WHERE time>=? AND server IN ('+marks+') ORDER BY time DESC LIMIT 100',(cutoff,*server_ids))]
        return self.config('statistics')|{'series':series,'daily':daily,'activity':activity,'servers':[{'id':s['id'],'name':s['name']} for s in self.state['bot'].servers.values()]}
