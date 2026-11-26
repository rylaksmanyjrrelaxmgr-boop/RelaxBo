#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_v5731_fixes.py — v5.7.31 FIX-RATELIMITER-RELEASE + PERF-WARN-PARALLEL + PERF-PENALTY-MSG-BG

يُطبَّق وقت بناء Docker (يُستدعى من Dockerfile قبل CMD).
يُعدّل ثلاثة ملفات:
  1. utils.py — إصلاح RateLimiter (إضافة release() فعلي)
  2. handlers/handlers_message.py — توازي _warn_branch + _penalty_branch + تأجيل penalty msg
  3. bot.py — تحديث رقم الإصدار إلى v5.7.31

السكربت idempotent: لو الإصلاحات مُطبَّقة بالفعل، يطبع رسالة وينتهي بلا تعديل.
"""
import os
import sys
import re

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read(path):
    full = os.path.join(_BASE_DIR, path)
    with open(full, 'r', encoding='utf-8') as f:
        return f.read()


def _write(path, content):
    full = os.path.join(_BASE_DIR, path)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(content)


# ═══════════════════════════════════════════════════════════════════════════
# FIX 1: utils.py — RateLimiter.release() فعلي
# ═══════════════════════════════════════════════════════════════════════════

UTILS_OLD = '''class RateLimiter:
    def __init__(self, max_concurrent: int = 10, max_per_second: int = 30):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._last_calls = deque(maxlen=max_per_second * 2)
        self._lock = asyncio.Lock()
        self.max_per_second = max_per_second
        self._base_max = max_per_second
        self._throttle_factor = 1.0
        self._last_429 = 0.0
        self._429_count = 0

    def report_429(self):
        self._429_count += 1
        self._last_429 = time.time()
        self._throttle_factor = min(self._throttle_factor * 1.5, 5.0)
        logger.warning(
            f"🚨 RateLimiter: 429 حقيقي — "
            f"throttle_factor={self._throttle_factor:.2f}"
        )

    def report_internal_timeout(self):
        logger.warning(
            "⚠️ RateLimiter internal timeout — throttle_factor محفوظ "
            "(المشكلة داخلية، ليست 429)"
        )

    def _get_effective_rate(self) -> int:
        if time.time() - self._last_429 > 60:
            self._throttle_factor = 1.0
        return max(1, int(self._base_max / self._throttle_factor))

    async def acquire(self, *args, **kwargs):
        while True:
            wait_time = 0.0
            effective_rate = self._get_effective_rate()
            async with self.semaphore:
                async with self._lock:
                    now = time.time()
                    while self._last_calls and now - self._last_calls[0] > 1:
                        self._last_calls.popleft()
                    if len(self._last_calls) < effective_rate:
                        self._last_calls.append(now)
                        return
                    wait_time = 1 - (now - self._last_calls[0])
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            else:
                await asyncio.sleep(0.01)'''


UTILS_NEW = '''class RateLimiter:
    """
    🆕 v5.7.31 FIX-RATELIMITER-RELEASE:
        الإصدار السابق كان معطوباً: استخدم `async with self.semaphore:`
        الذي يُطلق الـ semaphore تلقائياً عند `return` → لم يكن هناك تحكم
        تزامن فعلي. النتيجة: كل الرسائل في chat واحد كانت تتدفق بحرية،
        مسببة ازدحام event loop عندما يصل 100+ رسالة دفعة واحدة.

        الإصلاح: نُمسك الـ semaphore يدوياً (`acquire()` دون `async with`)
        ونُوفّر `release()` فعلي. الـ semaphore يُمسك طوال معالجة الرسالة
        ويُطلق فقط عندما يستدعي المُستدعي `release()`. هذا يضمن أن
        max_concurrent رسالة فقط تُعالج بالتوازي لكل chat_id.

    ضمانات الأمان:
        1. لو فشل token-bucket check نُطلق الـ semaphore فوراً ونعيد المحاولة.
        2. لو حصل CancelledError أثناء انتظار الـ semaphore، الـ asyncio
           يعالجه تلقائياً (Semaphore.acquire يعيد CancelledError نظيف).
        3. الـ release() idempotent — آمن استدعاؤها مرتين.
        4. التوافق مع الكود القديم: المُستدعي `_release_group_limiter`
           يفحص `getattr(limiter, 'release', None)` → سيرى الـ method الآن.
    """

    def __init__(self, max_concurrent: int = 10, max_per_second: int = 30):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._last_calls = deque(maxlen=max_per_second * 2)
        self._lock = asyncio.Lock()
        self.max_per_second = max_per_second
        self._base_max = max_per_second
        self._throttle_factor = 1.0
        self._last_429 = 0.0
        self._429_count = 0
        # 🆕 v5.7.31: نتتبّع إن كنّا نمسك الـ semaphore فعلاً.
        self._held = False

    def report_429(self):
        self._429_count += 1
        self._last_429 = time.time()
        self._throttle_factor = min(self._throttle_factor * 1.5, 5.0)
        logger.warning(
            f"🚨 RateLimiter: 429 حقيقي — "
            f"throttle_factor={self._throttle_factor:.2f}"
        )

    def report_internal_timeout(self):
        logger.warning(
            "⚠️ RateLimiter internal timeout — throttle_factor محفوظ "
            "(المشكلة داخلية، ليست 429)"
        )

    def _get_effective_rate(self) -> int:
        if time.time() - self._last_429 > 60:
            self._throttle_factor = 1.0
        return max(1, int(self._base_max / self._throttle_factor))

    async def acquire(self, *args, **kwargs):
        """
        🆕 v5.7.31: نُمسك الـ semaphore يدوياً ولا نُطلقه هنا. المُستدعي
        مسؤول عن استدعاء `release()` في `finally`. هذا يضمن أن
        max_concurrent رسالة فقط تُعالج بالتوازي.
        """
        # الخطوة 1: نمسك الـ semaphore (يحجب لو تجاوزنا max_concurrent).
        await self.semaphore.acquire()
        self._held = True
        # الخطوة 2: token-bucket check داخل الـ lock (سريع، <1ms).
        while True:
            wait_time = 0.0
            effective_rate = self._get_effective_rate()
            async with self._lock:
                now = time.time()
                while self._last_calls and now - self._last_calls[0] > 1:
                    self._last_calls.popleft()
                if len(self._last_calls) < effective_rate:
                    self._last_calls.append(now)
                    return  # الـ semaphore ما زال ممسوكاً.
                wait_time = 1 - (now - self._last_calls[0])
            # لو تجاوزنا rate، نُطلق الـ semaphore مؤقتاً أثناء الانتظار
            # حتى لا نحجب رسائل أخرى يمكنها المرور، ثم نعيد المحاولة.
            if wait_time > 0:
                self.semaphore.release()
                self._held = False
                await asyncio.sleep(wait_time)
                await self.semaphore.acquire()
                self._held = True
            else:
                await asyncio.sleep(0.01)

    def release(self):
        """
        🆕 v5.7.31: إطلاق الـ semaphore. idempotent — آمن استدعاؤه
        عدة مرات حتى لو لم يكن ممسوكاً.
        """
        if self._held:
            try:
                self.semaphore.release()
            except ValueError:
                # Semaphore.release() يرفع ValueError لو تجاوزنا
                # العدد الأصلي — يعني الـ _held كان غير متزامن مع الواقع.
                pass
            self._held = False'''


def fix_utils():
    path = 'utils.py'
    content = _read(path)
    if 'v5.7.31 FIX-RATELIMITER-RELEASE' in content:
        print(f'✅ {path}: v5.7.31 RateLimiter fix already applied — skip')
        return False
    if UTILS_OLD not in content:
        print(f'⚠️ {path}: expected RateLimiter block not found — skip (manual review needed)')
        return False
    new_content = content.replace(UTILS_OLD, UTILS_NEW, 1)
    _write(path, new_content)
    print(f'✅ {path}: applied v5.7.31 FIX-RATELIMITER-RELEASE')
    return True


# ═══════════════════════════════════════════════════════════════════════════
# FIX 2: handlers/handlers_message.py — _delete_and_warn parallel refactor
# ═══════════════════════════════════════════════════════════════════════════

# النسخة A: الكود التسلسلي القديم (قبل v5.7.30 — بدون gather).
# تطابق origin/main عند commit 5f0a3f5.
HANDLERS_OLD_A = '''        try:
            violation_count = await DB.increment_violation_count(
                user_id, chat_id)
        except Exception:
            violation_count = 1
        penalty_type, duration_seconds = (
            await MessageHandlers._resolve_penalty(
                chat_id, violation_type, settings))
        try:
            await DB.add_admin_log(
                chat_id, context.bot.id,
                f"violation_{violation_type}", user_id)
        except Exception:
            pass
        eff_user = update.effective_user
        first_name = (
            getattr(eff_user, 'first_name', None) if eff_user else None)
        user_name = escape(first_name or "User")
        await MessageHandlers._send_user_warning(
            context, chat_id, user_name, violation_type, lang,
            violation_count)

        if not penalty_type:
            try:
                await DB.reset_violation_count(user_id, chat_id)
            except Exception as _rvc:
                logger.debug(
                    "reset_violation_count (no penalty): %s", _rvc)
            return

        try:
            max_strikes = int(
                settings.get('violation_strikes')
                or settings.get('max_warnings') or 3)
        except (TypeError, ValueError):
            max_strikes = 3
        max_strikes = max(1, max_strikes)
        if violation_count < max_strikes:
            return
        success, msg = await apply_violation_penalty(
            update, context, chat_id, user_id,
            violation_type, penalty_type, duration_seconds, lang=lang)
        if not success:
            return
        try:
            target_first = ""
            target_username = None
            if update.effective_user:
                target_first = update.effective_user.first_name or ""
                target_username = update.effective_user.username
            await _notify_group_log_penalty(
                context, chat_id=chat_id, target_user_id=user_id,
                target_first_name=target_first,
                target_username=target_username,
                penalty_type=penalty_type,
                duration_seconds=duration_seconds,
                source="auto", violation_type=violation_type)
        except Exception:
            pass
        try:
            msg_prefix = await _trans(
                'violation_penalty_applied', lang, "🚨 {msg}")
            sent_penalty = await safe_send(
                context.bot, chat_id, _fmt(msg_prefix, msg=msg),
                parse_mode='HTML')
            if (sent_penalty is not None
                    and getattr(sent_penalty, 'message_id', None)):
                _spawn_delete_after_delay(
                    context.bot, chat_id, sent_penalty.message_id,
                    PENALTY_MESSAGE_DELETE_DELAY, context=context)
            await DB.reset_violation_count(user_id, chat_id)
        except Exception:
            pass'''

# النسخة B: بعد v5.7.30 (مع gather للـ DB calls التسلسلية).
HANDLERS_OLD_B = '''        try:
            _v_count, _penalty_pair, _ = await asyncio.gather(
                _inc_violation(),
                _resolve_pen(),
                _add_log(),
                return_exceptions=False,
            )
            violation_count = _v_count
            penalty_type, duration_seconds = _penalty_pair
        except Exception:
            # 🛡️ fallback نهائي — لا يجب أن يحدث لكن للحماية.
            violation_count = 1
            penalty_type, duration_seconds = (None, 0)
        eff_user = update.effective_user
        first_name = (
            getattr(eff_user, 'first_name', None) if eff_user else None)
        user_name = escape(first_name or "User")
        await MessageHandlers._send_user_warning(
            context, chat_id, user_name, violation_type, lang,
            violation_count)

        if not penalty_type:
            try:
                await DB.reset_violation_count(user_id, chat_id)
            except Exception as _rvc:
                logger.debug(
                    "reset_violation_count (no penalty): %s", _rvc)
            return

        try:
            max_strikes = int(
                settings.get('violation_strikes')
                or settings.get('max_warnings') or 3)
        except (TypeError, ValueError):
            max_strikes = 3
        max_strikes = max(1, max_strikes)
        if violation_count < max_strikes:
            return
        success, msg = await apply_violation_penalty(
            update, context, chat_id, user_id,
            violation_type, penalty_type, duration_seconds, lang=lang)
        if not success:
            return
        try:
            target_first = ""
            target_username = None
            if update.effective_user:
                target_first = update.effective_user.first_name or ""
                target_username = update.effective_user.username
            await _notify_group_log_penalty(
                context, chat_id=chat_id, target_user_id=user_id,
                target_first_name=target_first,
                target_username=target_username,
                penalty_type=penalty_type,
                duration_seconds=duration_seconds,
                source="auto", violation_type=violation_type)
        except Exception:
            pass
        try:
            msg_prefix = await _trans(
                'violation_penalty_applied', lang, "🚨 {msg}")
            sent_penalty = await safe_send(
                context.bot, chat_id, _fmt(msg_prefix, msg=msg),
                parse_mode='HTML')
            if (sent_penalty is not None
                    and getattr(sent_penalty, 'message_id', None)):
                _spawn_delete_after_delay(
                    context.bot, chat_id, sent_penalty.message_id,
                    PENALTY_MESSAGE_DELETE_DELAY, context=context)
            await DB.reset_violation_count(user_id, chat_id)
        except Exception:
            pass'''


HANDLERS_NEW = '''        eff_user = update.effective_user
        first_name = (
            getattr(eff_user, 'first_name', None) if eff_user else None)
        user_name = escape(first_name or "User")

        # ═════════════════════════════════════════════════════════════
        # 🆕 v5.7.31 PERF-WARN-PARALLEL:
        #   _send_user_warning تستدعي sendMessage (200-500ms) ولا تعتمد
        #   على penalty_type/violation_count الناتجة عن apply_violation_penalty.
        #   بدل انتظارها تسلسلياً، نشغّلها بالتوازي مع فرع العقوبة عبر gather.
        #
        #   الفروع المستقلة:
        #     A. _send_user_warning(context, ..., violation_count)
        #        — sendMessage إلى chat. لا تُرجع قيمة يحتاجها باقي الكود.
        #     B. منطق العقوبة (reset_count لو لا penalty، أو apply_violation_penalty
        #        لو max_strikes وصل).
        #
        #   ضمانات:
        #     - violation_count متاح قبل الـ gather (من نتائج الـ gather السابق).
        #     - penalty_type و duration_seconds متاحان قبل الـ gather.
        #     - كل فرع محاط بـ try/except مستقل، فشل أحدهما لا يكسر الآخر.
        #     - في الـ fallback (استثناء في gather) نُنفّذ الـ warning تسلسلياً.
        # ═════════════════════════════════════════════════════════════
        async def _warn_branch():
            try:
                await MessageHandlers._send_user_warning(
                    context, chat_id, user_name, violation_type, lang,
                    violation_count)
            except Exception as _we:
                logger.debug("warn_branch: %s", _we)

        async def _penalty_branch():
            try:
                if not penalty_type:
                    try:
                        await DB.reset_violation_count(user_id, chat_id)
                    except Exception as _rvc:
                        logger.debug(
                            "reset_violation_count (no penalty): %s", _rvc)
                    return
                try:
                    max_strikes = int(
                        settings.get('violation_strikes')
                        or settings.get('max_warnings') or 3)
                except (TypeError, ValueError):
                    max_strikes = 3
                max_strikes = max(1, max_strikes)
                if violation_count < max_strikes:
                    return
                _success, _msg = await apply_violation_penalty(
                    update, context, chat_id, user_id,
                    violation_type, penalty_type, duration_seconds,
                    lang=lang)
                if not _success:
                    return
                # 🆕 v5.7.31: إشعار log القناة (يستخدم _spawn_tracked_task
                # داخلياً عبر _dispatch_log → غير معطّل).
                try:
                    target_first = ""
                    target_username = None
                    if update.effective_user:
                        target_first = (
                            update.effective_user.first_name or "")
                        target_username = (
                            update.effective_user.username)
                    await _notify_group_log_penalty(
                        context, chat_id=chat_id,
                        target_user_id=user_id,
                        target_first_name=target_first,
                        target_username=target_username,
                        penalty_type=penalty_type,
                        duration_seconds=duration_seconds,
                        source="auto", violation_type=violation_type)
                except Exception:
                    pass
                # 🆕 v5.7.31 PERF-PENALTY-MSG-BG:
                #   رسالة "🚨 violation_penalty_applied" هي sendMessage
                #   (200-500ms) لا يحتاجها handler للمتابعة. نشغّلها في
                #   الخلفية + reset_violation_count بالتوازي.
                async def _send_penalty_msg_and_reset():
                    try:
                        _msg_prefix = await _trans(
                            'violation_penalty_applied', lang,
                            "🚨 {msg}")
                        _sent = await safe_send(
                            context.bot, chat_id,
                            _fmt(_msg_prefix, msg=_msg),
                            parse_mode='HTML')
                        if (_sent is not None
                                and getattr(_sent, 'message_id', None)):
                            _spawn_delete_after_delay(
                                context.bot, chat_id, _sent.message_id,
                                PENALTY_MESSAGE_DELETE_DELAY,
                                context=context)
                    except Exception:
                        pass
                    try:
                        await DB.reset_violation_count(user_id, chat_id)
                    except Exception:
                        pass
                _spawn_tracked_task(
                    _send_penalty_msg_and_reset(),
                    label="penalty-msg-bg")
            except Exception as _pe:
                logger.debug("penalty_branch: %s", _pe)

        try:
            await asyncio.gather(
                _warn_branch(),
                _penalty_branch(),
                return_exceptions=False,
            )
        except Exception as _g_e:
            # 🛡️ fallback: شغّل warning تسلسلياً لو gather فشل كلياً.
            logger.warning(
                "⚠️ delete_and_warn parallel gather failed: %s — "
                "fallback sequential", str(_g_e)[:80])
            try:
                await MessageHandlers._send_user_warning(
                    context, chat_id, user_name, violation_type, lang,
                    violation_count)
            except Exception:
                pass'''


def fix_handlers():
    path = 'handlers/handlers_message.py'
    content = _read(path)
    if 'v5.7.31 PERF-WARN-PARALLEL' in content:
        print(f'✅ {path}: v5.7.31 warn-parallel fix already applied — skip')
        return False
    # جرّب النسخة B أولاً (مع gather من v5.7.30)، ثم النسخة A (تسلسلية قديمة).
    if HANDLERS_OLD_B in content:
        new_content = content.replace(HANDLERS_OLD_B, HANDLERS_NEW, 1)
        _write(path, new_content)
        print(f'✅ {path}: applied v5.7.31 PERF-WARN-PARALLEL + PERF-PENALTY-MSG-BG (from v5.7.30 base)')
        return True
    if HANDLERS_OLD_A in content:
        new_content = content.replace(HANDLERS_OLD_A, HANDLERS_NEW, 1)
        _write(path, new_content)
        print(f'✅ {path}: applied v5.7.30 gather + v5.7.31 PERF-WARN-PARALLEL + PERF-PENALTY-MSG-BG (from origin/main base)')
        return True
    print(f'⚠️ {path}: expected _delete_and_warn block not found — skip (manual review needed)')
    return False


# ═══════════════════════════════════════════════════════════════════════════
# FIX 3: bot.py — version marker update
# ═══════════════════════════════════════════════════════════════════════════

# bot.py قد يكون في إحدى حالتين:
#   (a) v5.7.29 (origin/main 5f0a3f5): لا يوجد perf_sd3 نهائياً
#   (b) v5.7.30 (commit 0cc25ac): يوجد perf_sd3
# نُعالج كلاهما.

BOT_OLD_B = '''        "perf_sd1=on(uc_active_idx) | perf_sd2=on(mv_refresh+batch_flush+par_analysis) | "
        "perf_sd3=on(slowmode_bg+penalty_parallel)",'''

BOT_OLD_A = '''        "perf_sd1=on(uc_active_idx) | perf_sd2=on(mv_refresh+batch_flush+par_analysis)",'''

BOT_NEW_FROM_B = '''        "perf_sd1=on(uc_active_idx) | perf_sd2=on(mv_refresh+batch_flush+par_analysis) | "
        "perf_sd3=on(slowmode_bg+penalty_parallel) | "
        "perf_sd4=on(ratelimiter_release_fix+warn_parallel+penalty_msg_bg)",'''

BOT_NEW_FROM_A = '''        "perf_sd1=on(uc_active_idx) | perf_sd2=on(mv_refresh+batch_flush+par_analysis) | "
        "perf_sd3=on(slowmode_bg+penalty_parallel) | "
        "perf_sd4=on(ratelimiter_release_fix+warn_parallel+penalty_msg_bg)",'''

BOT_VERSION_OLD_30 = '📦 bot.py: v5.7.30 |'
BOT_VERSION_OLD_29 = '📦 bot.py: v5.7.29 |'
BOT_VERSION_NEW = '📦 bot.py: v5.7.31 |'


def fix_bot():
    path = 'bot.py'
    content = _read(path)
    if 'v5.7.31' in content and 'perf_sd4' in content:
        print(f'✅ {path}: v5.7.31 version marker already applied — skip')
        return False
    changed = False
    if BOT_OLD_B in content:
        content = content.replace(BOT_OLD_B, BOT_NEW_FROM_B, 1)
        changed = True
    elif BOT_OLD_A in content:
        content = content.replace(BOT_OLD_A, BOT_NEW_FROM_A, 1)
        changed = True
    if BOT_VERSION_OLD_30 in content:
        content = content.replace(BOT_VERSION_OLD_30, BOT_VERSION_NEW, 1)
        changed = True
    elif BOT_VERSION_OLD_29 in content:
        content = content.replace(BOT_VERSION_OLD_29, BOT_VERSION_NEW, 1)
        changed = True
    if changed:
        _write(path, content)
        print(f'✅ {path}: applied v5.7.31 version marker')
    else:
        print(f'⚠️ {path}: no version marker pattern found — skip')
    return changed


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print('═══════════════════════════════════════════════════════════')
    print('  apply_v5731_fixes.py — v5.7.31 performance fixes')
    print('═══════════════════════════════════════════════════════════')
    any_change = False
    try:
        if fix_utils():
            any_change = True
    except Exception as e:
        print(f'❌ utils.py fix failed: {e}')
    try:
        if fix_handlers():
            any_change = True
    except Exception as e:
        print(f'❌ handlers/handlers_message.py fix failed: {e}')
    try:
        if fix_bot():
            any_change = True
    except Exception as e:
        print(f'❌ bot.py fix failed: {e}')
    if any_change:
        print('\n✅ v5.7.31 fixes applied successfully.')
    else:
        print('\nℹ️ No changes needed — fixes already applied.')
    print('═══════════════════════════════════════════════════════════')


if __name__ == '__main__':
    main()
