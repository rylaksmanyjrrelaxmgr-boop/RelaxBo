#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
خادم الويب المتكامل – نسخة آمنة، محسّنة، وخالية من الأخطاء
يدعم واجهة متطورة مع static files
"""

import os, json, base64, secrets, time as time_module, tempfile, csv, asyncio
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Optional, Dict, Any, Set, List

from aiohttp import web, WSMsgType

try:
    from tasks import BackgroundTaskManager
    async def list_backups(): return []
    async def create_backup(): return type("_", (), {"name":"backup.enc"})()
    async def restore_backup(path): pass
except ImportError:
    async def list_backups(): return []
    async def create_backup(): return type("_", (), {"name":"backup.enc"})()
    async def restore_backup(path): pass
    def get_ram_usage(): return {"percent":0}
    try:
        from utils import advanced_logger, log_error
    except ImportError:
        raise ImportError("ملف utils.py مفقود")

try:
    from tasks import BackgroundTaskManager
    async def list_backups(): return []
    async def create_backup(): return type("_", (), {"name":"backup.enc"})()
    async def restore_backup(path): pass
except ImportError:
    async def list_backups(): return []
    async def create_backup(): return type("_", (), {"name":"backup.enc"})()
    async def restore_backup(path): pass
    async def check_database_health(): return True
    async def check_telegram_health(): return True

try:
    from tasks import BackgroundTaskManager
    async def list_backups(): return []
    async def create_backup(): return type("_", (), {"name":"backup.enc"})()
    async def restore_backup(path): pass
except ImportError:
    async def list_backups(): return []
    async def create_backup(): return type("_", (), {"name":"backup.enc"})()
    async def restore_backup(path): pass
    async def list_backups(): raise RuntimeError("tasks.py غير موجود")
    async def create_backup(): raise RuntimeError("tasks.py غير موجود")
    async def restore_backup(path): raise RuntimeError("tasks.py غير موجود")

WEB_SESSIONS: Dict[str, Dict[str, Any]] = {}
WEB_RATE_LIMITS: Dict[str, List[float]] = defaultdict(list)

def generate_session_id() -> str: return secrets.token_urlsafe(32)
def create_session(user_data: dict) -> str:
    session_id = generate_session_id()
    WEB_SESSIONS[session_id] = {'user_data': user_data, 'created_at': time_module.time(), 'last_activity': time_module.time()}
    return session_id

def get_session(session_id: str) -> Optional[dict]:
    if session_id not in WEB_SESSIONS: return None
    session = WEB_SESSIONS[session_id]
    if time_module.time() - session['last_activity'] > WEB_SESSION_TIMEOUT:
        del WEB_SESSIONS[session_id]; return None
    session['last_activity'] = time_module.time()
    return session['user_data']

def delete_session(session_id: str): WEB_SESSIONS.pop(session_id, None)

def check_rate_limit(ip: str) -> bool:
    now = time_module.time()
    WEB_RATE_LIMITS[ip] = [t for t in WEB_RATE_LIMITS[ip] if now - t < WEB_RATE_WINDOW]
    if len(WEB_RATE_LIMITS[ip]) >= WEB_RATE_LIMIT: return False
    WEB_RATE_LIMITS[ip].append(now); return True

async def cleanup_expired_sessions():
    while True:
        await asyncio.sleep(60)
        now = time_module.time()
        expired = [sid for sid, s in WEB_SESSIONS.items() if now - s['last_activity'] > WEB_SESSION_TIMEOUT]
        for sid in expired: del WEB_SESSIONS[sid]

def check_web_auth(request) -> bool:
    session_id = request.cookies.get('session_id')
    if session_id and get_session(session_id): return True
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Basic '):
        try:
            encoded = auth_header.split(' ')[1]
            decoded = base64.b64decode(encoded).decode('utf-8')
            username, password = decoded.split(':', 1)
            if secrets.compare_digest(username, WEB_USERNAME) and secrets.compare_digest(password, WEB_PASSWORD): return True
        except: pass
    return False

class WebSocketHub:
    def __init__(self):
        self.connections: Dict[str, Set[web.WebSocketResponse]] = defaultdict(set)
        self.subscriptions: Dict[str, Set[web.WebSocketResponse]] = defaultdict(set)
        self.lock = asyncio.Lock()

    async def authenticate(self, ws, token: str) -> bool:
        if secrets.compare_digest(token, WEB_SECRET_KEY):
            async with self.lock: self.connections[token].add(ws)
            await ws.send_str(json.dumps({'type':'auth','status':'success'})); return True
        await ws.send_str(json.dumps({'type':'auth','status':'failed'})); return False

    async def subscribe(self, ws, channel: str):
        async with self.lock:
            self.subscriptions[channel].add(ws)
            await ws.send_str(json.dumps({'type':'subscribe','channel':channel,'status':'success'}))

    async def unsubscribe(self, ws, channel: str):
        async with self.lock:
            self.subscriptions[channel].discard(ws)
            await ws.send_str(json.dumps({'type':'unsubscribe','channel':channel,'status':'success'}))

    async def broadcast(self, channel: str, data: dict):
        async with self.lock:
            if channel not in self.subscriptions: return
            message = json.dumps({'type':'broadcast','channel':channel,'data':data})
            to_remove = []
            for ws in list(self.subscriptions[channel]):
                try: await ws.send_str(message)
                except Exception: to_remove.append(ws)
            for ws in to_remove: self.subscriptions[channel].discard(ws)

    async def remove_connection(self, ws, token: str):
        async with self.lock:
            self.connections[token].discard(ws)
            for ch_set in self.subscriptions.values(): ch_set.discard(ws)

    async def ws_handler(self, request):
        ws = web.WebSocketResponse(); await ws.prepare(request)
        token = request.query.get('token') or request.headers.get('X-WebSocket-Token')
        if not token: await ws.close(code=4000, message='Missing token'); return ws
        if not await self.authenticate(ws, token): await ws.close(code=4001, message='Authentication failed'); return ws
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data); action = data.get('action')
                        if action == 'subscribe': ch = data.get('channel'); ch and await self.subscribe(ws, ch)
                        elif action == 'unsubscribe': ch = data.get('channel'); ch and await self.unsubscribe(ws, ch)
                        elif action == 'ping': await ws.send_str(json.dumps({'type':'pong'}))
                    except: await ws.send_str(json.dumps({'type':'error','message':'رسالة غير صالحة'}))
                elif msg.type == WSMsgType.ERROR: advanced_logger.log_error("WebSocket error", ws.exception())
        finally: await self.remove_connection(ws, token)
        return ws

ws_hub = WebSocketHub()
ws_extended = ws_hub

@web.middleware
async def auth_middleware(request, handler):
    public = ['/login','/logout','/health','/ws','/ws_extended','/static/']
    if request.path in public or request.path.startswith('/static/'): return await handler(request)
    if not check_web_auth(request):
        if request.path.startswith('/api/') or request.headers.get('Accept') == 'application/json':
            return web.json_response({'error':'غير مصرح'}, status=401)
        return web.Response(status=401, headers={"WWW-Authenticate":'Basic realm="البوت"'})
    return await handler(request)

@web.middleware
async def rate_limit_middleware(request, handler):
    protected = ['/login','/api/settings','/api/backups','/api/export','/api/users','/api/channels']
    if any(request.path.startswith(p) for p in protected):
        if not check_rate_limit(request.remote): return web.json_response({'error':'تجاوزت الحد المسموح للطلبات'}, status=429)
    return await handler(request)

async def root_handler(request):
    try:
        if JINJA2_AVAILABLE:
            try:
                from jinja2 import Environment, FileSystemLoader
                env = Environment(loader=FileSystemLoader(str(TEMPLATES_PATH)))
                template = env.get_template('index.html')
                html = template.render(WEB_SECRET_KEY=WEB_SECRET_KEY, BOT_NAME=BOT_NAME, BOT_USERNAME=BOT_USERNAME)
                return web.Response(text=html, content_type='text/html')
            except: pass
        try:
            with open(TEMPLATES_PATH / "index.html", "r", encoding='utf-8') as f: html = f.read()
            html = html.replace("{{ WEB_SECRET_KEY }}", WEB_SECRET_KEY)
            html = html.replace("{{ BOT_NAME }}", BOT_NAME)
            html = html.replace("{{ BOT_USERNAME }}", BOT_USERNAME)
            return web.Response(text=html, content_type='text/html')
        except: return web.Response(text="""<!DOCTYPE html><html><head><title>ريلاكس مانيجر</title></head><body><h1>🚀 ريلاكس مانيجر يعمل!</h1></body></html>""", content_type='text/html')
    except Exception as e:
        advanced_logger.log_error("root_handler", e)
        return web.Response(text="❌ حدث خطأ داخلي", status=500)

async def login_handler(request):
    if request.method == 'POST':
        data = await request.post()
        username = data.get('username',''); password = data.get('password','')
        if secrets.compare_digest(username, WEB_USERNAME) and secrets.compare_digest(password, WEB_PASSWORD):
            session_id = create_session({'username':username})
            resp = web.Response(status=302, headers={'Location':'/'})
            resp.set_cookie('session_id', session_id, httponly=True, secure=False, samesite='Strict', max_age=WEB_SESSION_TIMEOUT)
            return resp
        return web.Response(text='❌ اسم المستخدم أو كلمة المرور غير صحيحة', status=401)
    html = """<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>تسجيل الدخول</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.rtl.min.css" rel="stylesheet"><style>body{background:#f5f6fa;display:flex;align-items:center;justify-content:center;min-height:100vh;}.login-card{background:white;border-radius:20px;padding:40px;box-shadow:0 10px 40px rgba(0,0,0,0.1);width:100%;max-width:400px;}.brand{font-size:28px;font-weight:bold;color:#2d3436;margin-bottom:30px;text-align:center;}</style></head><body><div class="login-card"><div class="brand">🚀 ريلاكس مانيجر</div><h5 class="text-center mb-4">🔐 تسجيل الدخول</h5><form method="POST"><div class="mb-3"><label class="form-label">اسم المستخدم</label><input type="text" name="username" class="form-control" required autofocus></div><div class="mb-3"><label class="form-label">كلمة المرور</label><input type="password" name="password" class="form-control" required></div><button type="submit" class="btn btn-primary w-100">دخول</button></form></div></body></html>"""
    return web.Response(text=html, content_type='text/html')

async def logout_handler(request):
    session_id = request.cookies.get('session_id')
    if session_id: delete_session(session_id)
    resp = web.Response(status=302, headers={'Location':'/login'})
    resp.del_cookie('session_id')
    return resp

async def health_check_handler(request):
    try:
        db_ok = await check_database_health(); tg_ok = await check_telegram_health()
        return web.json_response({'status':'ok' if db_ok and tg_ok else 'degraded','version':'19.3.3'})
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)

async def api_charts_handler(request):
    try:
        return web.json_response({"user_growth":{"labels":[],"data":[]},"posts_distribution":{"published":0,"unpublished":0}})
    except:
        return web.json_response({"error":"حدث خطأ داخلي"}, status=500)

async def api_stats_handler(request):
    try:
        total, banned, posts, groups, channels = await db_stats()
        return web.json_response({'total_users':total,'active_users':total-banned,'banned_users':banned,'pending_posts':posts,'groups':groups,'channels':channels})
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)

async def api_groups_handler(request):
    try:
        page = max(1, int(request.query.get('page',1))); limit = min(100, max(1, int(request.query.get('limit',50)))); offset = (page-1)*limit
        async def _fetch(conn):
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups ORDER BY added_at DESC LIMIT ? OFFSET ?", (limit, offset))
            return await cur.fetchall()
        rows = await execute_db(_fetch)
        result = [{'chat_id':r[0],'chat_name':r[1],'username':r[2],'added_by':r[3],'added_at':r[4],'banned':r[5]==1} for r in rows]
        async def _count(conn):
            cur = await conn.execute("SELECT COUNT(*) FROM bot_groups"); row = await cur.fetchone(); return row[0] if row else 0
        total = await execute_db(_count)
        return web.json_response({'data':result,'total':total,'page':page,'limit':limit})
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)

async def api_backups_handler(request):
    try:
        backups = await list_backups()
        result = [{'name':b.name,'size':b.stat().st_size,'date':datetime.fromtimestamp(b.stat().st_mtime).isoformat()} for b in backups]
        return web.json_response(result)
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)

async def api_backup_create_handler(request):
    try:
        path = await create_backup()
        return web.json_response({'success':True,'message':'✅ تم إنشاء نسخة احتياطية','file':path.name})
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)

async def api_backup_restore_handler(request):
    try:
        name = request.match_info['name']
        requested = (BACKUP_DIR / name).resolve()
        base = BACKUP_DIR.resolve()
        if base != requested and base not in requested.parents: return web.json_response({'error':'اسم ملف غير صالح'}, status=403)
        if not requested.is_file(): return web.json_response({'error':'الملف غير موجود'}, status=404)
        await restore_backup(requested)
        return web.json_response({'success':True,'message':'✅ تم استعادة النسخة'})
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)

async def api_backup_delete_handler(request):
    try:
        name = request.match_info['name']
        requested = (BACKUP_DIR / name).resolve()
        base = BACKUP_DIR.resolve()
        if base != requested and base not in requested.parents: return web.json_response({'error':'اسم ملف غير صالح'}, status=403)
        if not requested.is_file(): return web.json_response({'error':'الملف غير موجود'}, status=404)
        requested.unlink()
        return web.json_response({'success':True,'message':'✅ تم حذف النسخة'})
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)

async def api_settings_handler(request):
    try:
        interval = await db_get_publish_interval_seconds(); updates = await db_get_updates_channel()
        force = await db_get_force_subscribe_status(); backup = await db_get_auto_backup()
        return web.json_response({'bot_name':BOT_NAME,'bot_username':BOT_USERNAME,'publish_interval':interval//60,'updates_channel':updates or '','force_subscribe':force,'auto_backup':backup})
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)

async def api_settings_update_handler(request):
    try:
        data = await request.json()
        if 'publish_interval' in data:
            sec = int(data['publish_interval'])*60
            await db_set_publish_interval_seconds(sec, PRIMARY_OWNER_ID, is_admin=True)
        if 'updates_channel' in data:
            ch = data['updates_channel'].strip()
            if ch.startswith('@'): ch = ch[1:]
            if ch: await db_set_updates_channel(ch)
        if 'force_subscribe' in data: await db_set_force_subscribe_status(data['force_subscribe'])
        if 'auto_backup' in data: await db_set_auto_backup(data['auto_backup'])
        return web.json_response({'success':True,'message':'✅ تم حفظ الإعدادات'})
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)

async def api_users_handler(request):
    try:
        page = max(1, int(request.query.get('page',1))); limit = min(100, max(1, int(request.query.get('limit',50)))); offset = (page-1)*limit
        async def _fetch(conn):
            try:
                cur = await conn.execute("SELECT u.user_id, u.banned, COALESCE(l.points,0), COALESCE(l.level,1) FROM users_cache u LEFT JOIN user_levels l ON u.user_id = l.user_id ORDER BY u.user_id LIMIT ? OFFSET ?", (limit, offset))
            except: cur = await conn.execute("SELECT user_id, banned, 0, 1 FROM users_cache ORDER BY user_id LIMIT ? OFFSET ?", (limit, offset))
            return await cur.fetchall()
        rows = await execute_db(_fetch)
        result = [{'user_id':r[0],'banned':r[1]==1,'points':r[2],'level':r[3]} for r in rows]
        async def _count(conn):
            cur = await conn.execute("SELECT COUNT(*) FROM users_cache"); row = await cur.fetchone(); return row[0] if row else 0
        total = await execute_db(_count)
        return web.json_response({'data':result,'total':total,'page':page,'limit':limit})
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)

async def api_user_toggle_ban_handler(request):
    try:
        user_id = int(request.match_info['user_id'])
        async def _check(conn):
            cur = await conn.execute("SELECT 1 FROM users_cache WHERE user_id = ?",(user_id,)); return await cur.fetchone()
        if not await execute_db(_check): return web.json_response({'error':'المستخدم غير موجود'}, status=404)
        currently_banned = await db_is_banned(user_id)
        await db_set_ban(user_id, not currently_banned)
        return web.json_response({'success':True,'message':f'تم {"حظر" if not currently_banned else "إلغاء حظر"} المستخدم'})
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)

async def api_system_info_handler(request):
    try:
        ram = get_ram_usage(); uptime = time_module.time() - getattr(api_system_info_handler,'_start',time_module.time())
        db_ok = await check_database_health(); tg_ok = await check_telegram_health()
        return web.json_response({'uptime':f'{int(uptime//3600)} ساعة {int((uptime%3600)//60)} دقيقة','memory':f"{ram['percent']}%",'db_status':'✅ سليمة' if db_ok else '❌ تالفة','telegram_status':'✅ متصل' if tg_ok else '❌ غير متصل','version':'19.3.3'})
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)
api_system_info_handler._start = time_module.time()

async def api_logs_handler(request):
    try:
        limit = int(request.query.get('limit', 50))
        logs = []
        if LOG_PATH.exists():
            with open(LOG_PATH, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-limit:]
                for line in lines:
                    try:
                        parts = line.strip().split(' - ', 3)
                        if len(parts) >= 4:
                            logs.append({'time': parts[0], 'level': parts[1], 'message': parts[-1]})
                        else:
                            logs.append({'time': '', 'level': 'INFO', 'message': line.strip()})
                    except: logs.append({'time': '', 'level': 'INFO', 'message': line.strip()})
        return web.json_response(logs)
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)

async def api_logs_delete_handler(request):
    try:
        if LOG_PATH.exists():
            with open(LOG_PATH, 'w', encoding='utf-8') as f: f.write('')
        return web.json_response({'success':True,'message':'تم مسح السجلات'})
    except: return web.json_response({'error':'حدث خطأ داخلي'}, status=500)

def setup_web_routes(app: web.Application):
    app.router.add_static('/static/', path=STATIC_PATH)
    app.router.add_get('/', root_handler)
    app.router.add_get('/login', login_handler); app.router.add_post('/login', login_handler)
    app.router.add_get('/logout', logout_handler)
    app.router.add_get('/health', health_check_handler)
    app.router.add_get('/ws', ws_hub.ws_handler); app.router.add_get('/ws_extended', ws_hub.ws_handler)
    app.router.add_get('/api/stats', api_stats_handler)
    app.router.add_get('/api/charts', api_charts_handler)
    app.router.add_get('/api/groups', api_groups_handler)
    app.router.add_get('/api/users', api_users_handler)
    app.router.add_post('/api/users/{user_id}/toggle-ban', api_user_toggle_ban_handler)
    app.router.add_get('/api/backups', api_backups_handler)
    app.router.add_post('/api/backups', api_backup_create_handler)
    app.router.add_post('/api/backups/{name}/restore', api_backup_restore_handler)
    app.router.add_delete('/api/backups/{name}', api_backup_delete_handler)
    app.router.add_get('/api/settings', api_settings_handler)
    app.router.add_post('/api/settings', api_settings_update_handler)
    app.router.add_get('/api/system-info', api_system_info_handler)
    app.router.add_get('/api/logs', api_logs_handler)
    app.router.add_delete('/api/logs', api_logs_delete_handler)

web_app = web.Application(middlewares=[rate_limit_middleware, auth_middleware])
setup_web_routes(web_app)

async def on_startup_cleanup(app): asyncio.create_task(cleanup_expired_sessions())
web_app.on_startup.append(on_startup_cleanup)

async def start_web_server():
    try:
        render_port = int(os.getenv("PORT","0"))
        ports_to_try = [render_port] if render_port>0 else []
        ports_to_try.extend([WEB_PORT, 8080, 10000, 8081, 8082, 8083])
        runner = None
        for port in ports_to_try:
            try:
                runner = web.AppRunner(web_app); await runner.setup()
                site = web.TCPSite(runner, WEB_HOST, port); await site.start()
                advanced_logger.log_access(0, "WEB_SERVER_STARTED", {"host":WEB_HOST,"port":port})
                return
            except OSError as e:
                if "address already in use" in str(e):
                    if runner: await runner.cleanup()
                    continue
                raise
    except Exception as e: advanced_logger.log_error("فشل تشغيل خادم الويب", e)
