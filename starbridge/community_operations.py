"""Private player conversations and UUID-scoped, acknowledged multi-server sanctions."""
from copy import deepcopy
import json
import re
import time
import uuid

from .registration import RegistrationError


def text(value, label, maximum, empty=False):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise RegistrationError(label + '格式错误或超过长度限制')
    value = value.strip()
    if not value and not empty:
        raise RegistrationError(label + '不能为空')
    return value


def page_number(value):
    try:
        number = int(value)
        if not 1 <= number <= 10000: raise ValueError()
        return number
    except (ValueError, TypeError):
        raise RegistrationError('分页参数错误') from None


def owned_identities(state, user):
    return {(r['server'], r['uuid']) for r in state['store'].db.execute(
        'SELECT server,uuid FROM account_game_links WHERE account_id=? UNION SELECT server,uuid FROM bindings WHERE qq=?',
        (user['id'], user.get('qq') or ''))}


class Tickets:
    DEFAULTS = {'enabled': False, 'max_open': 5}

    def __init__(self, state):
        self.state = state; self.db = state['store'].db

    def config(self):
        row = self.db.execute("SELECT value,revision FROM operations_settings WHERE key='tickets'").fetchone()
        settings = json.loads(row['value']) if row else deepcopy(self.DEFAULTS)
        if not row and self.db.execute('SELECT 1 FROM tickets LIMIT 1').fetchone():
            settings['enabled'] = True  # Preserve existing installations with conversations.
        return {'settings': settings, 'revision': row['revision'] if row else 0}

    def save(self, data):
        current = self.config(); settings = data.get('settings')
        if data.keys() - {'settings', 'revision'} or not isinstance(settings, dict) or settings.keys() != self.DEFAULTS.keys():
            raise RegistrationError('工单设置格式错误')
        if type(settings['enabled']) is not bool or type(settings['max_open']) is not int or not 1 <= settings['max_open'] <= 20:
            raise RegistrationError('工单开关需为布尔值，每人待处理上限为 1–20')
        if type(data.get('revision')) is not int or data['revision'] != current['revision']:
            raise RegistrationError('工单设置已变化，请刷新', 409)
        with self.db:
            self.db.execute("INSERT INTO operations_settings VALUES('tickets',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,revision=excluded.revision",
                            (json.dumps(settings), current['revision'] + 1))
        return self.config()

    def listing(self, account_id=None, status='', page=1):
        if status and status not in ('open', 'processing', 'resolved', 'closed'): raise RegistrationError('工单状态错误')
        page = page_number(page); where = []; args = []
        if account_id is not None: where.append('account_id=?'); args.append(account_id)
        if status: where.append('status=?'); args.append(status)
        clause = ' WHERE ' + ' AND '.join(where) if where else ''
        total = self.db.execute('SELECT count(*) FROM tickets' + clause, args).fetchone()[0]
        rows = [dict(r) for r in self.db.execute('SELECT * FROM tickets' + clause + ' ORDER BY updated DESC,id DESC LIMIT 20 OFFSET ?', [*args, (page - 1) * 20])]
        if account_id is not None:
            for row in rows: row.pop('account_id', None)
        return {'tickets': rows, 'total': total, 'page': page, 'page_size': 20, **self.config()}

    def detail(self, tid, account_id=None):
        row = self.db.execute('SELECT * FROM tickets WHERE id=?', (tid,)).fetchone()
        if not row or account_id is not None and row['account_id'] != account_id: raise RegistrationError('工单不存在', 404)
        out = dict(row)
        query = 'SELECT * FROM ticket_messages WHERE ticket=?' + (' AND internal=0' if account_id is not None else '')
        out['messages'] = [dict(r) for r in self.db.execute(query + ' ORDER BY created,id LIMIT 200', (tid,))]
        if account_id is not None:
            out.pop('account_id', None)
            for message in out['messages']: message.pop('internal', None)
        return out

    def create(self, user, data):
        settings = self.config()['settings']
        if not settings['enabled']: raise RegistrationError('暂未开放工单提交', 403)
        if data.keys() - {'title', 'body', 'kind', 'server', 'penalty_id'}: raise RegistrationError('工单请求包含未知字段')
        title = text(data.get('title'), '标题', 100); content = text(data.get('body'), '内容', 4000)
        kind, sid, penalty = data.get('kind', 'question'), data.get('server', ''), data.get('penalty_id', '')
        if kind not in ('question', 'appeal') or not isinstance(sid, str) or sid and sid not in self.state['bot'].servers:
            raise RegistrationError('工单类型或服务器错误')
        if not isinstance(penalty, str) or len(penalty) > 40: raise RegistrationError('处罚编号错误')
        if kind != 'appeal' and penalty: raise RegistrationError('普通问题不能关联处罚')
        if penalty:
            owned = owned_identities(self.state, user)
            sanction = self.db.execute('SELECT uuid,servers FROM sanctions WHERE id=?', (penalty,)).fetchone()
            action = self.db.execute("SELECT server,uuid FROM player_actions WHERE id=? AND action IN ('kick','ban','unban')", (penalty,)).fetchone()
            if not (sanction and any((server, sanction['uuid']) in owned for server in json.loads(sanction['servers'])) or action and (action['server'], action['uuid']) in owned):
                raise RegistrationError('处罚不存在或不属于此账号', 404)
        if self.db.execute("SELECT count(*) FROM tickets WHERE account_id=? AND status IN ('open','processing')", (user['id'],)).fetchone()[0] >= settings['max_open']:
            raise RegistrationError('待处理工单已达上限，请先处理已有工单', 409)
        if self.db.execute('SELECT count(*) FROM tickets').fetchone()[0] >= 10000: raise RegistrationError('工单存储已达上限，请联系管理员', 503)
        self.state['registration'].limit('ticket-create:' + user['id'], 5, 3600)
        tid, now = uuid.uuid4().hex, time.time()
        with self.db:
            self.db.execute('INSERT INTO tickets VALUES(?,?,?,?,?,?,?,?,?,?,?)', (tid, user['id'], user['player'], title, kind, sid, penalty, 'open', 1, now, now))
            self.db.execute('INSERT INTO ticket_messages VALUES(?,?,?,?,?,?,?)', (uuid.uuid4().hex, tid, user['player'], 'player', content, 0, now))
        self.state['store'].audit('ticket', user['player'] + ' 提交' + ('申诉' if kind == 'appeal' else '工单') + ' ' + tid)
        return self.detail(tid, user['id'])

    def reply(self, tid, data, author, account_id=None):
        if data.keys() - {'body', 'internal', 'status', 'revision'}: raise RegistrationError('工单操作包含未知字段')
        row = self.detail(tid, account_id)
        if type(data.get('revision')) is not int or data['revision'] != row['revision']: raise RegistrationError('工单已更新，请刷新', 409)
        status = data.get('status', row['status']); internal = data.get('internal', False)
        if type(internal) is not bool or status not in ('open', 'processing', 'resolved', 'closed'): raise RegistrationError('工单状态或备注开关错误')
        if account_id is not None and (internal or 'status' in data or row['status'] in ('resolved', 'closed')):
            raise RegistrationError('此账号不能修改状态、写内部备注或回复已结束工单', 403)
        content = text(data.get('body', ''), '回复', 4000, empty=account_id is None)
        if not content and status == row['status']: raise RegistrationError('请填写回复或修改状态')
        if self.db.execute('SELECT count(*) FROM ticket_messages WHERE ticket=?', (tid,)).fetchone()[0] >= 200: raise RegistrationError('工单回复已达上限', 409)
        if account_id is not None: self.state['registration'].limit('ticket-reply:' + account_id, 20, 300)
        now = time.time()
        with self.db:
            if content: self.db.execute('INSERT INTO ticket_messages VALUES(?,?,?,?,?,?,?)', (uuid.uuid4().hex, tid, author, 'player' if account_id else 'admin', content, int(internal), now))
            self.db.execute('UPDATE tickets SET status=?,revision=revision+1,updated=? WHERE id=?', (status, now, tid))
        return self.detail(tid, account_id)


class Sanctions:
    def __init__(self, state):
        self.state = state; self.db = state['store'].db

    def config(self):
        row = self.db.execute("SELECT value,revision FROM operations_settings WHERE key='sanctions'").fetchone()
        return {'settings': json.loads(row['value']) if row else {'enabled': bool(self.db.execute('SELECT 1 FROM sanctions LIMIT 1').fetchone())},
                'revision': row['revision'] if row else 0}

    def save(self, data):
        current = self.config(); settings = data.get('settings')
        if data.keys() != {'settings', 'revision'} or not isinstance(settings, dict) or settings.keys() != {'enabled'} or type(settings['enabled']) is not bool:
            raise RegistrationError('跨服处罚设置只接受布尔值开关')
        if type(data['revision']) is not int or data['revision'] != current['revision']:
            raise RegistrationError('跨服处罚设置已变化，请刷新', 409)
        with self.db:
            self.db.execute("INSERT INTO operations_settings VALUES('sanctions',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,revision=excluded.revision",
                            (json.dumps(settings), current['revision'] + 1))
        self.reconcile()
        return self.config()

    def listing(self, page=1):
        self.reconcile()
        page = page_number(page)
        rows = [self.detail(r['id']) for r in self.db.execute('SELECT id FROM sanctions ORDER BY created DESC,id DESC LIMIT 20 OFFSET ?', ((page - 1) * 20,))]
        return {'sanctions': rows, 'total': self.db.execute('SELECT count(*) FROM sanctions').fetchone()[0], 'page': page, 'page_size': 20,
                'servers': [{'id': s['id'], 'name': s['name']} for s in self.state['bot'].servers.values()]}

    def detail(self, sid):
        row = self.db.execute('SELECT * FROM sanctions WHERE id=?', (sid,)).fetchone()
        if not row: raise RegistrationError('处罚记录不存在', 404)
        out = dict(row); out['servers'] = json.loads(out['servers'])
        out['targets'] = [dict(r) for r in self.db.execute('SELECT * FROM sanction_targets WHERE sanction=? ORDER BY server', (sid,))]
        return out

    def create(self, data, author):
        if not self.config()['settings']['enabled']: raise RegistrationError('跨服处罚未开启，请在功能开关中开启', 403)
        self.reconcile()
        if data.keys() - {'uuid', 'reason', 'action', 'servers', 'minutes'}: raise RegistrationError('处罚请求包含未知字段')
        try: identity = str(uuid.UUID(data.get('uuid')))
        except (ValueError, TypeError, AttributeError): raise RegistrationError('需要完整玩家 UUID') from None
        profile = self.db.execute('SELECT name FROM player_profiles WHERE uuid=? AND deleted=0', (identity,)).fetchone()
        if not profile: raise RegistrationError('玩家档案不存在，请先同步游戏玩家', 404)
        servers = data.get('servers'); action = data.get('action', 'ban'); minutes = data.get('minutes', 0)
        if not isinstance(servers, list) or not 1 <= len(servers) <= 100 or any(not isinstance(s, str) or s not in self.state['bot'].servers for s in servers) or len(servers) != len(set(servers)):
            raise RegistrationError('请选择有效且不重复的服务器')
        if action not in ('ban', 'kick') or type(minutes) is not int or not 0 <= minutes <= 525600 or action == 'kick' and minutes:
            raise RegistrationError('处罚类型或期限错误；0 表示永久，踢出不设置期限')
        reason = text(data.get('reason'), '处罚原因', 300)
        if any(ord(c) < 32 or ord(c) == 127 for c in reason): raise RegistrationError('处罚原因不能包含控制字符或换行')
        for previous in self.db.execute("SELECT servers FROM sanctions WHERE uuid=? AND action='ban' AND status='active'", (identity,)):
            if action == 'ban' and set(json.loads(previous['servers'])) & set(servers): raise RegistrationError('所选服务器已有生效封禁，请先撤销原处罚', 409)
        if self.db.execute("SELECT count(*) FROM sanctions WHERE status='active'").fetchone()[0] >= 1000: raise RegistrationError('生效处罚已达上限', 409)
        rid, now = uuid.uuid4().hex, time.time()
        with self.db:
            expires = now + 60 if action == 'kick' else now + minutes * 60 if minutes else 0
            self.db.execute('INSERT INTO sanctions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (rid, identity, profile['name'], reason, action, json.dumps(servers), 'active', expires, now, now, 1, author))
            for server in servers: self.db.execute('INSERT INTO sanction_targets VALUES(?,?,?,?,?,?,?,?)', (rid, server, action, 'waiting', '', '等待游戏身份与桥接连接', 0, 0))
        self.state['store'].audit('sanction', author + ' 提交跨服' + action + ' ' + rid)
        self.reconcile()
        return self.detail(rid)

    def release(self, rid, revision):
        row = self.detail(rid)
        if type(revision) is not int or row['revision'] != revision: raise RegistrationError('处罚已更新，请刷新', 409)
        if row['action'] != 'ban' or row['status'] != 'active': raise RegistrationError('此记录没有可撤销的生效封禁', 409)
        self._release(row, 'revoked'); self.reconcile(); return self.detail(rid)

    def _release(self, row, status):
        with self.db:
            self.db.execute('UPDATE sanctions SET status=?,updated=?,revision=revision+1 WHERE id=?', (status, time.time(), row['id']))
            for target in row['targets']:
                # A leased ban may already have run. Cancel it and follow with a guarded unban.
                if target['job']: self.db.execute('DELETE FROM jobs WHERE id=?', (target['job'],))
                keep = target['status'] == 'superseded'
                self.db.execute("UPDATE sanction_targets SET phase='unban',status=?,job='',attempts=0,next_try=0,detail=? WHERE sanction=? AND server=?",
                                ('superseded' if keep else 'waiting', '保留独立处罚' if keep else '等待解除本条处罚', row['id'], target['server']))

    def reconcile(self, server=None):
        if self.state.get('maintenance'): return
        enabled = self.config()['settings']['enabled']
        now = time.time()
        query = "SELECT id FROM sanctions WHERE (status='active' OR id IN (SELECT sanction FROM sanction_targets WHERE phase='unban' AND status NOT IN ('success','superseded')))"
        if server is not None: query += ' AND id IN (SELECT sanction FROM sanction_targets WHERE server=?)'
        active = [self.detail(r['id']) for r in self.db.execute(query + ' LIMIT 1200', (server,) if server is not None else ())]
        for row in active:
            if row['status'] == 'active' and row['expires'] and row['expires'] <= now:
                if row['action'] == 'kick':
                    with self.db:
                        for target in row['targets']:
                            if target['job']: self.db.execute('DELETE FROM jobs WHERE id=?', (target['job'],))
                            if target['status'] == 'pending':
                                result = self.state['store'].player_action(target['job'])
                                if result and result['status'] == 'success':
                                    self.db.execute("UPDATE sanction_targets SET status='success',detail=? WHERE sanction=? AND server=?", (result['detail'], row['id'], target['server']))
                                    continue
                            if target['status'] not in ('success', 'superseded'): self._target(row['id'], target['server'], 'superseded', '踢出请求已过期，不在后续登录时执行')
                        self.db.execute("UPDATE sanctions SET status='completed',updated=?,revision=revision+1 WHERE id=?", (now, row['id']))
                    continue
                self._release(row, 'expired'); row = self.detail(row['id'])
            for target in row['targets']:
                sid = target['server']
                if server is not None and sid != server: continue
                if target['status'] in ('success', 'superseded'): continue
                if not enabled and target['phase'] != 'unban':
                    job = self.state['store'].player_action(target['job']) if target['job'] else None
                    if job and job['status'] == 'success':
                        with self.db: self.db.execute("UPDATE sanction_targets SET status='success',detail=? WHERE sanction=? AND server=?", (job['detail'], row['id'], sid))
                    else:
                        with self.db:
                            if target['job']: self.db.execute('DELETE FROM jobs WHERE id=?', (target['job'],))
                            self.db.execute("UPDATE sanction_targets SET status='waiting',job='',next_try=0,detail='功能已关闭，暂停下发' WHERE sanction=? AND server=?", (row['id'], sid))
                    continue
                if target['job']:
                    job = self.state['store'].player_action(target['job'])
                    if job and job['status'] == 'success':
                        with self.db: self.db.execute("UPDATE sanction_targets SET status='success',detail=? WHERE sanction=? AND server=?", (job['detail'], row['id'], sid))
                        continue
                    if job and job['status'] == 'pending' and job['expires'] > now: continue
                    with self.db: self.db.execute("UPDATE sanction_targets SET status='failed',job='',next_try=?,detail=? WHERE sanction=? AND server=?", (now + 30, job['detail'] if job else '执行未确认，将重试', row['id'], sid))
                    continue
                if target['next_try'] > now: continue
                if target['attempts'] >= 10:
                    self._target(row['id'], sid, 'failed', '连续执行失败，请检查核心后手动重试'); continue
                if sid not in self.state['bot'].servers:
                    self._target(row['id'], sid, 'failed', '服务器已从配置移除'); continue
                snapshot = self.state['bot'].snapshots.get(sid, {})
                if not self.state['bot'].online(sid) or 'player_management' not in snapshot.get('capabilities', []):
                    self._target(row['id'], sid, 'waiting', '等待可用的游戏桥接'); continue
                if 'managed_sanctions' not in snapshot.get('capabilities', []):
                    self._target(row['id'], sid, 'waiting', '请更新游戏插件以支持处罚归属校验'); continue
                if target['phase'] == 'ban' and self.db.execute("SELECT 1 FROM sanction_targets t JOIN sanctions s ON s.id=t.sanction WHERE t.server=? AND s.uuid=? AND t.phase='unban' AND t.status NOT IN ('success','superseded') LIMIT 1", (sid, row['uuid'])).fetchone():
                    self._target(row['id'], sid, 'waiting', '等待此前封禁解除确认后再应用新处罚'); continue
                player = next((p for p in snapshot.get('player_records', []) if p['uuid'] == row['uuid']), None)
                if not player:
                    self._target(row['id'], sid, 'waiting', '等待该服务器上报此 UUID，不按同名推断'); continue
                if target['phase'] == 'kick' and not player['online']:
                    self._target(row['id'], sid, 'superseded', '玩家已离线，无需踢出'); continue
                if target['phase'] == 'ban' and player.get('banned'):
                    submitted = target['attempts'] > 0 or self.db.execute('SELECT 1 FROM player_actions WHERE server=? AND uuid=? AND action=? AND reason=? LIMIT 1',
                        (sid, row['uuid'], 'ban', row['reason'] + ' [SB:' + row['id'] + ']')).fetchone()
                    if not submitted:
                        self._target(row['id'], sid, 'superseded', '已有其他封禁，保留原处罚')
                    else:
                        self._target(row['id'], sid, 'waiting', '游戏端已封禁但任务未确认；请核实，撤销时会校验归属')
                    continue
                if target['phase'] == 'unban' and not player.get('banned'):
                    self._target(row['id'], sid, 'success', '游戏端已解除封禁'); continue
                if target['phase'] == 'unban':
                    prior = self.db.execute("SELECT action,id FROM player_actions WHERE server=? AND uuid=? AND action IN ('ban','unban') ORDER BY created DESC LIMIT 1", (sid, row['uuid'])).fetchone()
                    if prior and prior['action'] == 'ban':
                        # Other panel bans must never be removed by an expired shared rule.
                        reason = self.db.execute('SELECT reason FROM player_actions WHERE id=?', (prior['id'],)).fetchone()['reason']
                        if reason != row['reason'] + ' [SB:' + row['id'] + ']':
                            self._target(row['id'], sid, 'superseded', '已有更新的独立封禁，保留原处罚'); continue
                jid = uuid.uuid4().hex
                reason = row['reason'] + ' [SB:' + row['id'] + ']' if target['phase'] == 'ban' else row['reason']
                try:
                    self.state['store'].create_player_action(jid, sid, row['uuid'], player['name'], target['phase'], reason)
                    payload = self.state['store'].job(sid, jid)
                    if target['phase'] == 'unban': payload['expected_ban_reason'] = row['reason'] + ' [SB:' + row['id'] + ']'
                    if target['phase'] == 'ban': payload['kick_reason'] = row['reason']
                    with self.db:
                        self.db.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(payload, ensure_ascii=False), jid))
                        self.db.execute("UPDATE sanction_targets SET status='pending',job=?,attempts=attempts+1,detail='等待游戏端确认' WHERE sanction=? AND server=?", (jid, row['id'], sid))
                except ValueError:
                    self._target(row['id'], sid, 'waiting', '游戏任务队列繁忙')
            if row['action'] == 'kick' and all(t['status'] in ('success', 'superseded') for t in self.detail(row['id'])['targets']):
                with self.db: self.db.execute("UPDATE sanctions SET status='completed',updated=?,revision=revision+1 WHERE id=?", (now, row['id']))

    def _target(self, rid, sid, status, detail):
        with self.db:
            self.db.execute('UPDATE sanction_targets SET status=?,detail=?,next_try=? WHERE sanction=? AND server=?', (status, detail, time.time() + 30, rid, sid))

    def observe(self, sid, records):
        # Reapply active bans after an external unban, while never repeating successful kicks.
        if not self.config()['settings']['enabled']:
            self.reconcile(sid)
            return
        identities = {p['uuid'] for p in records if not p.get('banned')}
        for row in self.db.execute("SELECT t.sanction,s.uuid FROM sanction_targets t JOIN sanctions s ON s.id=t.sanction WHERE t.server=? AND t.phase='ban' AND t.status='success' AND s.status='active'", (sid,)).fetchall():
            if row['uuid'] in identities:
                with self.db: self.db.execute("UPDATE sanction_targets SET status='waiting',job='',next_try=0 WHERE sanction=? AND server=?", (row['sanction'], sid))
        self.reconcile(sid)
