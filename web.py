#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
خادم الويب المتكامل
- واجهة تسجيل الدخول
- لوحة تحكم (Dashboard)
- API لإحصائيات البوت
- WebSocket للتحديثات الفورية
- نظام توثيق متقدم
"""

import os
import json
import base64
import secrets
import time as time_module
import tempfile
import csv
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional, Dict, Any

from aiohttp import web, WSMsgType
import aiohttp

from constants import (
    WEB_HOST, WEB_PORT, WEB_USERNAME, WEB_PASSWORD,
    WEB_SECRET_KEY, WEB_SESSION_TIMEOUT,
    WEB_RATE_LIMIT, WEB_RATE_WINDOW,
    PRIMARY_OWNER_ID, BOT_NAME, BOT_USERNAME,
    TEMPLATES_PATH, STATIC_PATH, JINJA2_AVAILABLE,
    TOKEN, DB_PATH, BACKUP_DIR, LOG_PATH
)
from utils import (
    utc_now, mecca_now, utc_now_iso, safe_int,
    advanced_logger, log_error, memory_optimizer
)
from database import (
    db_stats, db_get_all_users, db_get_channels,
    db_get_user_groups, db_get_all_groups,
    db_get_all_user_channels_no_limit, db_all_users_channels,
    db_get_all_bot_channels, db_get_contest_winners,
    db_get_active_contests_with_participants,
    db_get_channel_stats, db_get_channel_growth,
    db_get_referral_stats, db_get_referral_settings,
    db_get_updates_channel, db_get_force_subscribe_status,
    db_get_force_subscribe_channel, db_get_log_channel_id,
    db_get_auto_backup, db_get_publish_interval_seconds,
    db_set_publish_interval_seconds, db_set_updates_channel,
    db_set_force_subscribe_status, db_set_force_subscribe_channel,
    db_set_log_channel_id, db_set_auto_backup,
    db_stats, db_get_all_users, db_set_ban,
    db_is_banned, db_get_user_level, db_update_user_level,
    execute_db
)
from security import get_ram_usage, check_database_health, check_telegram_health

# ===================== إعدادات WebSocket =====================

class WebSocketManager:
    """مدير اتصالات WebSocket"""
    def __init__(self):
        self.connections = set()
        self.lock = asyncio.Lock()

    async def broadcast(self, data: dict):
        """بث رسالة لجميع العملاء المتصلين"""
        async with self.lock:
            if not self.connections:
                return
            message = json.dumps(data)
            to_remove = []
            for ws in self.connections:
                try:
                    await ws.send_str(message)
                except:
                    to_remove.append(ws)
            for ws in to_remove:
                self.connections.discard(ws)

    async def handler(self, request):
        """معالج WebSocket"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async with self.lock:
            self.connections.add(ws)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        if data.get('type') == 'ping':
                            await ws.send_str(json.dumps({'type': 'pong'}))
                    except:
                        pass
                elif msg.type == WSMsgType.ERROR:
                    advanced_logger.log_error("خطأ في WebSocket", ws.exception())
        finally:
            async with self.lock:
                self.connections.discard(ws)
        return ws

class WebSocketExtendedHandler:
    """معالج WebSocket المتقدم مع المصادقة والاشتراك في القنوات"""
    def __init__(self):
        self.connections = {}
        self.subscriptions = defaultdict(set)
        self.lock = asyncio.Lock()

    async def handle_auth(self, ws, token: str) -> bool:
        """مصادقة العميل"""
        if token == WEB_SECRET_KEY:
            self.connections[token] = ws
            await ws.send_str(json.dumps({'type': 'auth', 'status': 'success'}))
            return True
        await ws.send_str(json.dumps({'type': 'auth', 'status': 'failed'}))
        return False

    async def handle_subscribe(self, ws, channel: str):
        """الاشتراك في قناة"""
        async with self.lock:
            self.subscriptions[channel].add(ws)
            await ws.send_str(json.dumps({'type': 'subscribe', 'channel': channel, 'status': 'success'}))

    async def handle_unsubscribe(self, ws, channel: str):
        """إلغاء الاشتراك من قناة"""
        async with self.lock:
            if channel in self.subscriptions:
                self.subscriptions[channel].discard(ws)
            await ws.send_str(json.dumps({'type': 'unsubscribe', 'channel': channel, 'status': 'success'}))

    async def broadcast(self, channel: str, data: dict):
        """بث رسالة لقناة محددة"""
        async with self.lock:
            if channel in self.subscriptions:
                message = json.dumps({'type': 'broadcast', 'channel': channel, 'data': data})
                for ws in list(self.subscriptions[channel]):
                    try:
                        await ws.send_str(message)
                    except:
                        self.subscriptions[channel].discard(ws)

    async def get_stats(self) -> dict:
        """الحصول على إحصائيات البوت"""
        total, banned, posts, groups, channels = await db_stats()
        return {
            'total_users': total,
            'banned_users': banned,
            'pending_posts': posts,
            'groups': groups,
            'channels': channels
        }

    async def handler(self, request):
        """معالج WebSocket المتقدم"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        token = request.query.get('token')
        if not token:
            await ws.close()
            return ws
        authenticated = await self.handle_auth(ws, token)
        if not authenticated:
            await ws.close()
            return ws
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        action = data.get('action')
                        if action == 'subscribe':
                            channel = data.get('channel')
                            if channel:
                                await self.handle_subscribe(ws, channel)
                        elif action == 'unsubscribe':
                            channel = data.get('channel')
                            if channel:
                                await self.handle_unsubscribe(ws, channel)
                        elif action == 'get_stats':
                            stats = await self.get_stats()
                            await ws.send_str(json.dumps({'type': 'response', 'action': 'get_stats', 'data': stats}))
                        elif action == 'ping':
                            await ws.send_str(json.dumps({'type': 'pong'}))
                    except Exception as e:
                        await ws.send_str(json.dumps({'type': 'error', 'message': str(e)}))
        except Exception as e:
            advanced_logger.log_error("خطأ في WebSocket المتقدم", e)
        finally:
            for channel in list(self.subscriptions):
                self.subscriptions[channel].discard(ws)
        return ws

ws_manager = WebSocketManager()
ws_extended = WebSocketExtendedHandler()

# ===================== إدارة الجلسات =====================

WEB_SESSIONS = {}
WEB_SESSION_TIMEOUT = WEB_SESSION_TIMEOUT
WEB_RATE_LIMITS = defaultdict(list)

def generate_session_id() -> str:
    """توليد معرف جلسة فريد"""
    return secrets.token_urlsafe(32)

def create_session(user_data: dict) -> str:
    """إنشاء جلسة جديدة"""
    session_id = generate_session_id()
    WEB_SESSIONS[session_id] = {
        'user_data': user_data,
        'created_at': time_module.time(),
        'last_activity': time_module.time()
    }
    return session_id

def get_session(session_id: str) -> Optional[dict]:
    """استرداد جلسة"""
    if session_id not in WEB_SESSIONS:
        return None
    session = WEB_SESSIONS[session_id]
    if time_module.time() - session['last_activity'] > WEB_SESSION_TIMEOUT:
        del WEB_SESSIONS[session_id]
        return None
    session['last_activity'] = time_module.time()
    return session['user_data']

def delete_session(session_id: str):
    """حذف جلسة"""
    if session_id in WEB_SESSIONS:
        del WEB_SESSIONS[session_id]

def check_rate_limit(ip: str) -> bool:
    """التحقق من حد المعدل"""
    now = time_module.time()
    WEB_RATE_LIMITS[ip] = [t for t in WEB_RATE_LIMITS[ip] if now - t < WEB_RATE_WINDOW]
    if len(WEB_RATE_LIMITS[ip]) >= WEB_RATE_LIMIT:
        return False
    WEB_RATE_LIMITS[ip].append(now)
    return True

def check_web_auth(request) -> bool:
    """التحقق من المصادقة"""
    session_id = request.cookies.get('session_id')
    if session_id:
        session = get_session(session_id)
        if session:
            return True
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Basic '):
        try:
            encoded = auth_header.split(' ')[1]
            decoded = base64.b64decode(encoded).decode('utf-8')
            username, password = decoded.split(':', 1)
            if username == WEB_USERNAME and password == WEB_PASSWORD:
                return True
        except:
            pass
    return False

# ===================== الصفحة الرئيسية =====================

async def root_handler(request):
    """صفحة البداية"""
    if not check_web_auth(request):
        return web.Response(status=401, headers={"WWW-Authenticate": 'Basic realm="البوت"'})
    try:
        if JINJA2_AVAILABLE:
            try:
                from jinja2 import Environment, FileSystemLoader
                template_env = Environment(loader=FileSystemLoader(str(TEMPLATES_PATH)))
                template = template_env.get_template('index.html')
                html = template.render(
                    WEB_SECRET_KEY=WEB_SECRET_KEY,
                    BOT_NAME=BOT_NAME,
                    BOT_USERNAME=BOT_USERNAME
                )
                return web.Response(text=html, content_type='text/html')
            except:
                pass
        # إذا لم يكن Jinja2 متاحاً
        try:
            with open(TEMPLATES_PATH / "index.html", "r", encoding='utf-8') as f:
                html = f.read()
                html = html.replace("{{ WEB_SECRET_KEY }}", WEB_SECRET_KEY)
                html = html.replace("{{ BOT_NAME }}", BOT_NAME)
                html = html.replace("{{ BOT_USERNAME }}", BOT_USERNAME)
                return web.Response(text=html, content_type='text/html')
        except:
            return web.Response(
                text="""<!DOCTYPE html>
                <html><head><title>ريلاكس مانيجر</title></head>
                <body><h1>🚀 ريلاكس مانيجر يعمل!</h1>
                <p>الإصدار 19.3.3</p>
                <p>👑 المطور: @RelaxMgr</p>
                </body></html>""",
                content_type='text/html'
            )
    except Exception as e:
        advanced_logger.log_error("خطأ في عرض الصفحة الرئيسية", e)
        return web.Response(text=f"❌ حدث خطأ: {str(e)[:200]}", status=500)

async def login_handler(request):
    """صفحة تسجيل الدخول"""
    try:
        if request.method == 'POST':
            data = await request.post()
            username = data.get('username', '')
            password = data.get('password', '')
            if username == WEB_USERNAME and password == WEB_PASSWORD:
                session_id = create_session({'username': username})
                response = web.Response(status=302, headers={'Location': '/'})
                response.set_cookie('session_id', session_id, httponly=True, max_age=WEB_SESSION_TIMEOUT)
                return response
            return web.Response(text='❌ اسم المستخدم أو كلمة المرور غير صحيحة', status=401)
        html = """
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>تسجيل الدخول - ريلاكس مانيجر</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body { background: #f5f6fa; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
                .login-card { background: white; border-radius: 20px; padding: 40px; box-shadow: 0 10px 40px rgba(0,0,0,0.1); width: 100%; max-width: 400px; }
                .login-card .brand { font-size: 28px; font-weight: bold; color: #2d3436; margin-bottom: 30px; text-align: center; }
                .login-card .brand i { color: #0984e3; }
            </style>
        </head>
        <body>
            <div class="login-card">
                <div class="brand"><i class="bi bi-robot"></i> ريلاكس مانيجر</div>
                <h5 class="text-center mb-4">🔐 تسجيل الدخول</h5>
                <form method="POST">
                    <div class="mb-3"><label class="form-label">اسم المستخدم</label><input type="text" name="username" class="form-control" required autofocus></div>
                    <div class="mb-3"><label class="form-label">كلمة المرور</label><input type="password" name="password" class="form-control" required></div>
                    <button type="submit" class="btn btn-primary w-100">دخول</button>
                </form>
                <hr><p class="text-center text-muted small">© 2026 ريلاكس مانيجر - الإصدار 19.3.3</p>
            </div>
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
        </body>
        </html>
        """
        return web.Response(text=html, content_type='text/html')
    except Exception as e:
        advanced_logger.log_error("خطأ في صفحة تسجيل الدخول", e)
        return web.Response(text=f"❌ حدث خطأ: {str(e)[:200]}", status=500)

async def logout_handler(request):
    """تسجيل الخروج"""
    session_id = request.cookies.get('session_id')
    if session_id:
        delete_session(session_id)
    response = web.Response(status=302, headers={'Location': '/login'})
    response.del_cookie('session_id')
    return response

# ===================== مسارات API =====================

async def health_check_handler(request):
    """التحقق من صحة البوت"""
    db_healthy = await check_database_health()
    tg_healthy = await check_telegram_health()
    return web.json_response({
        'status': 'ok' if db_healthy and tg_healthy else 'degraded',
        'version': '19.3.3',
        'db_status': '✅ سليمة' if db_healthy else '❌ تالفة',
        'telegram_status': '✅ متصل' if tg_healthy else '❌ غير متصل'
    })

async def api_stats_handler(request):
    """إحصائيات عامة"""
    try:
        total, banned, posts, groups, channels = await db_stats()
        return web.json_response({
            'total_users': total,
            'active_users': total - banned,
            'banned_users': banned,
            'pending_posts': posts,
            'groups': groups,
            'channels': channels
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_charts_handler(request):
    """بيانات الرسوم البيانية"""
    try:
        user_growth = {'labels': [], 'data': []}
        try:
            async def _get_user_growth(conn):
                cur = await conn.execute("""
                    SELECT date(last_updated) as date, COUNT(*) as count
                    FROM users_cache
                    WHERE last_updated >= datetime('now', '-30 days')
                    GROUP BY date(last_updated)
                    ORDER BY date
                """)
                return await cur.fetchall()
            growth_data = await execute_db(_get_user_growth)
            for row in growth_data:
                user_growth['labels'].append(row[0])
                user_growth['data'].append(row[1])
        except:
            pass
        posts_distribution = {'published': 0, 'unpublished': 0}
        try:
            async def _get_posts_dist(conn):
                cur = await conn.execute("SELECT published, COUNT(*) FROM posts GROUP BY published")
                return await cur.fetchall()
            dist_data = await execute_db(_get_posts_dist)
            for row in dist_data:
                if row[0] == 1:
                    posts_distribution['published'] = row[1]
                else:
                    posts_distribution['unpublished'] = row[1]
        except:
            pass
        return web.json_response({
            'user_growth': user_growth,
            'posts_distribution': posts_distribution
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_export_handler(request):
    """تصدير البيانات بصيغة CSV"""
    try:
        export_type = request.query.get('type', 'all')
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8')
        writer = csv.writer(temp_file)
        if export_type == 'users' or export_type == 'all':
            users = await db_get_all_users()
            writer.writerow(['User ID', 'Banned'])
            for user_id, banned in users:
                writer.writerow([user_id, banned])
            temp_file.write('\n')
        if export_type == 'channels' or export_type == 'all':
            channels = await db_get_all_user_channels_no_limit()
            writer.writerow(['User ID', 'Channel DB ID', 'Channel ID', 'Channel Name', 'Banned'])
            for user_id, ch_id, ch_tele, ch_name, banned in channels:
                writer.writerow([user_id, ch_id, ch_tele, ch_name, banned])
            temp_file.write('\n')
        if export_type == 'groups' or export_type == 'all':
            groups = await db_get_all_groups()
            writer.writerow(['Chat ID', 'Chat Name', 'Username', 'Added By', 'Added At', 'Banned'])
            for chat_id, chat_name, username, added_by, added_at, banned in groups:
                writer.writerow([chat_id, chat_name, username, added_by, added_at, banned])
            temp_file.write('\n')
        if export_type == 'posts' or export_type == 'all':
            async def _get_posts(conn):
                cur = await conn.execute("SELECT p.id, p.text, p.media_type, p.published, p.created_at, uc.channel_id FROM posts p JOIN user_channels uc ON p.channel_db_id = uc.id LIMIT 1000")
                return await cur.fetchall()
            posts = await execute_db(_get_posts)
            writer.writerow(['Post ID', 'Text', 'Media Type', 'Published', 'Created At', 'Channel ID'])
            for post in posts:
                writer.writerow([post[0], post[1][:100] if post[1] else '', post[2], post[3], post[4], post[5]])
        temp_file.close()
        with open(temp_file.name, 'rb') as f:
            data = f.read()
        os.unlink(temp_file.name)
        filename = f"export_{export_type}_{mecca_now().strftime('%Y%m%d_%H%M%S')}.csv"
        return web.Response(body=data, headers={
            'Content-Type': 'text/csv',
            'Content-Disposition': f'attachment; filename="{filename}"'
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_users_handler(request):
    """قائمة المستخدمين"""
    try:
        users = await db_get_all_users()
        result = []
        for user_id, banned in users:
            level_data = await db_get_user_level(user_id)
            result.append({
                'user_id': user_id,
                'banned': banned == 1,
                'points': level_data['points'],
                'level': level_data['level']
            })
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_user_toggle_ban_handler(request):
    """تبديل حالة حظر المستخدم"""
    try:
        user_id = int(request.match_info['user_id'])
        users = await db_get_all_users()
        user_exists = any(u[0] == user_id for u in users)
        if not user_exists:
            return web.json_response({'error': 'المستخدم غير موجود'}, status=404)
        current_ban = await db_is_banned(user_id)
        await db_set_ban(user_id, not current_ban)
        return web.json_response({
            'success': True,
            'message': f'تم {"حظر" if not current_ban else "إلغاء حظر"} المستخدم'
        })
    except ValueError:
        return web.json_response({'error': 'معرف غير صالح'}, status=400)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_channels_handler(request):
    """قائمة قنوات المستخدمين"""
    try:
        channels = await db_get_all_user_channels_no_limit()
        result = []
        for user_id, ch_id, ch_tele, ch_name, banned in channels:
            result.append({
                'user_id': user_id,
                'channel_id': ch_tele,
                'channel_name': ch_name,
                'banned': banned == 1
            })
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_groups_handler(request):
    """قائمة المجموعات"""
    try:
        groups = await db_get_all_groups()
        result = []
        for chat_id, chat_name, username, added_by, added_at, banned in groups:
            result.append({
                'chat_id': chat_id,
                'chat_name': chat_name,
                'username': username,
                'added_by': added_by,
                'added_at': added_at,
                'banned': banned == 1
            })
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_posts_handler(request):
    """قائمة المنشورات غير المنشورة"""
    try:
        async def _get_posts(conn):
            cur = await conn.execute("""
                SELECT p.id, p.channel_db_id, p.text, p.media_type, p.created_at,
                       uc.channel_id, uc.channel_name
                FROM posts p
                JOIN user_channels uc ON p.channel_db_id = uc.id
                WHERE p.published = 0
                ORDER BY p.created_at DESC
                LIMIT 100
            """)
            return await cur.fetchall()
        posts = await execute_db(_get_posts)
        result = []
        for post in posts:
            result.append({
                'id': post[0],
                'channel_db_id': post[1],
                'text': post[2],
                'media_type': post[3],
                'created_at': post[4],
                'channel_id': post[5],
                'channel_name': post[6]
            })
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_contests_handler(request):
    """قائمة المسابقات النشطة"""
    try:
        contests = await db_get_active_contests_with_participants(limit=20)
        result = []
        for contest in contests:
            result.append({
                'id': contest[0],
                'title': contest[1],
                'description': contest[2],
                'prize': contest[3],
                'end_date': contest[4],
                'participants': contest[5] if len(contest) > 5 else 0,
                'status': 'active'
            })
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_logs_handler(request):
    """سجلات البوت"""
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
                            logs.append({
                                'time': parts[0],
                                'level': parts[1] if len(parts) > 1 else 'INFO',
                                'message': parts[-1]
                            })
                        else:
                            logs.append({
                                'time': '',
                                'level': 'INFO',
                                'message': line.strip()
                            })
                    except:
                        logs.append({
                            'time': '',
                            'level': 'INFO',
                            'message': line.strip()
                        })
        return web.json_response(logs)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_logs_delete_handler(request):
    """حذف السجلات"""
    try:
        if LOG_PATH.exists():
            with open(LOG_PATH, 'w', encoding='utf-8') as f:
                f.write('')
        return web.json_response({'success': True, 'message': 'تم مسح السجلات'})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_backups_handler(request):
    """قائمة النسخ الاحتياطية"""
    try:
        from tasks import list_backups
        backups = await list_backups()
        result = []
        for backup in backups:
            stat = backup.stat()
            result.append({
                'name': backup.name,
                'size': stat.st_size,
                'date': datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_backup_create_handler(request):
    """إنشاء نسخة احتياطية"""
    try:
        from tasks import create_backup
        backup_path = await create_backup()
        return web.json_response({
            'success': True,
            'message': '✅ تم إنشاء نسخة احتياطية',
            'file': backup_path.name
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_backup_restore_handler(request):
    """استعادة نسخة احتياطية"""
    try:
        from tasks import restore_backup
        name = request.match_info['name']
        backup_path = BACKUP_DIR / name
        if not backup_path.exists():
            return web.json_response({'error': 'الملف غير موجود'}, status=404)
        await restore_backup(backup_path)
        return web.json_response({'success': True, 'message': '✅ تم استعادة النسخة'})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_backup_delete_handler(request):
    """حذف نسخة احتياطية"""
    try:
        name = request.match_info['name']
        backup_path = BACKUP_DIR / name
        if not backup_path.exists():
            return web.json_response({'error': 'الملف غير موجود'}, status=404)
        backup_path.unlink()
        return web.json_response({'success': True, 'message': '✅ تم حذف النسخة'})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_settings_handler(request):
    """إعدادات البوت"""
    try:
        publish_interval = await db_get_publish_interval_seconds()
        updates_channel = await db_get_updates_channel()
        force_subscribe = await db_get_force_subscribe_status()
        auto_backup = await db_get_auto_backup()
        return web.json_response({
            'bot_name': BOT_NAME,
            'bot_username': BOT_USERNAME,
            'publish_interval': publish_interval // 60,
            'updates_channel': updates_channel or '',
            'force_subscribe': force_subscribe,
            'auto_backup': auto_backup
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_settings_update_handler(request):
    """تحديث الإعدادات"""
    try:
        data = await request.json()
        if 'publish_interval' in data:
            seconds = int(data['publish_interval']) * 60
            await db_set_publish_interval_seconds(seconds, PRIMARY_OWNER_ID, is_admin=True)
        if 'updates_channel' in data:
            channel = data['updates_channel'].strip()
            if channel:
                if channel.startswith('@'):
                    channel = channel[1:]
                await db_set_updates_channel(channel)
        if 'force_subscribe' in data:
            await db_set_force_subscribe_status(data['force_subscribe'])
        if 'auto_backup' in data:
            await db_set_auto_backup(data['auto_backup'])
        return web.json_response({'success': True, 'message': '✅ تم حفظ الإعدادات'})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_system_info_handler(request):
    """معلومات النظام"""
    try:
        ram = get_ram_usage()
        uptime = time_module.time() - getattr(api_system_info_handler, 'start_time', time_module.time())
        uptime_hours = int(uptime / 3600)
        uptime_minutes = int((uptime % 3600) / 60)
        db_healthy = await check_database_health()
        tg_healthy = await check_telegram_health()
        return web.json_response({
            'uptime': f'{uptime_hours} ساعة {uptime_minutes} دقيقة',
            'memory': f"{ram['percent']}%",
            'db_status': '✅ سليمة' if db_healthy else '❌ تالفة',
            'telegram_status': '✅ متصل' if tg_healthy else '❌ غير متصل',
            'version': '19.3.3'
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

# ===================== دالة تسجيل المسارات =====================

def setup_web_routes(app: web.Application):
    """تسجيل جميع مسارات الويب"""
    # الصفحات الرئيسية
    app.router.add_get('/', root_handler)
    app.router.add_get('/login', login_handler)
    app.router.add_post('/login', login_handler)
    app.router.add_get('/logout', logout_handler)
    app.router.add_get('/health', health_check_handler)
    
    # WebSocket
    app.router.add_get('/ws', ws_manager.handler)
    app.router.add_get('/ws_extended', ws_extended.handler)
    
    # API
    app.router.add_get('/api/stats', api_stats_handler)
    app.router.add_get('/api/charts', api_charts_handler)
    app.router.add_get('/api/export', api_export_handler)
    app.router.add_get('/api/users', api_users_handler)
    app.router.add_post('/api/users/{user_id}/toggle-ban', api_user_toggle_ban_handler)
    app.router.add_get('/api/channels', api_channels_handler)
    app.router.add_get('/api/groups', api_groups_handler)
    app.router.add_get('/api/posts', api_posts_handler)
    app.router.add_get('/api/contests', api_contests_handler)
    app.router.add_get('/api/logs', api_logs_handler)
    app.router.add_delete('/api/logs', api_logs_delete_handler)
    app.router.add_get('/api/backups', api_backups_handler)
    app.router.add_post('/api/backups', api_backup_create_handler)
    app.router.add_post('/api/backups/{name}/restore', api_backup_restore_handler)
    app.router.add_delete('/api/backups/{name}', api_backup_delete_handler)
    app.router.add_get('/api/settings', api_settings_handler)
    app.router.add_post('/api/settings', api_settings_update_handler)
    app.router.add_get('/api/system-info', api_system_info_handler)

# ===================== التشغيل =====================

web_app = web.Application()

# إضافة وسيط المصادقة
@web.middleware
async def auth_middleware(request, handler):
    if request.path.startswith('/api/') or request.path.startswith('/static/') or request.path in ['/login', '/logout', '/health', '/ws', '/ws_extended']:
        return await handler(request)
    if not check_web_auth(request):
        return web.Response(status=401, headers={"WWW-Authenticate": 'Basic realm="البوت"'})
    return await handler(request)

web_app.middlewares.append(auth_middleware)

# تسجيل المسارات
setup_web_routes(web_app)

async def start_web_server():
    """بدء خادم الويب"""
    try:
        render_port = int(os.getenv("PORT", "0"))
        ports_to_try = []
        if render_port > 0:
            ports_to_try.append(render_port)
        ports_to_try.extend([WEB_PORT, 8080, 10000, 8081, 8082, 8083])
        for port in ports_to_try:
            try:
                runner = web.AppRunner(web_app)
                await runner.setup()
                site = web.TCPSite(runner, WEB_HOST, port)
                await site.start()
                advanced_logger.log_access(0, "WEB_SERVER_STARTED", {"host": WEB_HOST, "port": port})
                global WEB_PORT_USED
                WEB_PORT_USED = port
                return
            except OSError as e:
                if "address already in use" in str(e):
                    continue
                raise
        advanced_logger.log_error("لا يمكن العثور على منفذ متاح لخادم الويب", None)
    except Exception as e:
        advanced_logger.log_error("فشل تشغيل خادم الويب", e)

WEB_PORT_USED = WEB_PORT

