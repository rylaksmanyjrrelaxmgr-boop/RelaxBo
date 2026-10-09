#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers/messages/banned_words_manager.py
===============================================================================
🛡️ Banned Words Manager v1.0.0 — Dual-Path System
===============================================================================

🎯 المساران المنفصلان:
    1. GlobalBannedWordsPath  (chat_id = -1)     → للمطور
    2. GroupBannedWordsPath   (chat_id = group)  → لمشرف المجموعة
===============================================================================
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict
from enum import Enum
from typing import Any, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

__version__ = "1.0.0"


# ═════════════════════════════════════════════════════════════════════════════
# 1. ثوابت
# ═════════════════════════════════════════════════════════════════════════════

GLOBAL_CHAT_ID: int = -1
MIN_WORD_LEN: int = 2
MAX_WORD_LEN: int = 100
_COMPACT_MIN_LEN: int = 5
_CACHE_MAX_PATTERNS: int = 5000


class BannedScope(str, Enum):
    GLOBAL = "global"
    GROUP = "group"

    def __str__(self) -> str:
        return self.value


class OpReason(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    DUPLICATE = "duplicate"
    NOT_FOUND = "not_found"
    NO_PERMS = "no_perms"
    INVALID = "invalid"
    DB_ERROR = "db_error"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return self.value


# ═════════════════════════════════════════════════════════════════════════════
# 2. استيرادات خارجية مع fallbacks
# ═════════════════════════════════════════════════════════════════════════════

try:
    from handlers.handlers_message_detectors import (
        _normalize_text,
        _normalize_arabic_for_compare,
        _is_arabic_dominant,
    )
    _HAS_DETECTOR_HELPERS = True
except ImportError:
    try:
        from handlers_message_detectors import (
            _normalize_text,
            _normalize_arabic_for_compare,
            _is_arabic_dominant,
        )
        _HAS_DETECTOR_HELPERS = True
    except ImportError:
        _HAS_DETECTOR_HELPERS = False

        def _normalize_text(t: Any) -> str:
            return (str(t) if t is not None else "").lower().strip()

        def _normalize_arabic_for_compare(t: Any) -> str:
            if not t:
                return ""
            s = str(t)
            s = re.sub(
                r"[\u064B-\u065F\u0670\u06D6-\u06DC"
                r"\u06DF-\u06E8\u06EA-\u06ED\u0640]",
                "", s,
            )
            s = re.sub(r"(?<!\S)ال", "", s)
            s = re.sub(r"[^\u0600-\u06FF\s]", "", s)
            s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
            s = s.replace("ى", "ي").replace("ة", "ه")
            s = re.sub(r"\s+", "", s)
            return s.strip()

        def _is_arabic_dominant(t: Any) -> bool:
            if not t:
                return False
            text = str(t)
            arabic = sum(1 for ch in text if "\u0600" <= ch <= "\u06FF")
            letters = sum(1 for ch in text if ch.isalpha())
            if letters == 0:
                return False
            return (arabic / letters) >= 0.6


try:
    from utils import get_banned_words_cached
    _HAS_BANNED_CACHE = True
except ImportError:
    _HAS_BANNED_CACHE = False

    async def get_banned_words_cached(chat_id: int) -> List[str]:
        try:
            from database import DB
            words = await DB.get_banned_words(chat_id)
            return list(words or [])
        except Exception:
            return []


try:
    from utils import invalidate_banned_words_cache_async as _inv_async
    _HAS_INV_ASYNC = True
except ImportError:
    _HAS_INV_ASYNC = False
    _inv_async = None


try:
    from utils import invalidate_banned_words_cache as _inv_sync
    _HAS_INV_SYNC = True
except ImportError:
    _HAS_INV_SYNC = False
    _inv_sync = None


try:
    from config import CONFIG
    _HAS_CONFIG = True
except ImportError:
    _HAS_CONFIG = False
    CONFIG = None


try:
    from database import DB
    _HAS_DB = True
except ImportError:
    _HAS_DB = False
    DB = None


# ═════════════════════════════════════════════════════════════════════════════
# 3. قائمة التحيات العربية
# ═════════════════════════════════════════════════════════════════════════════

_ARABIC_GREETINGS_RAW: frozenset = frozenset({
    "السلام عليكم", "سلام عليكم", "وعليكم السلام",
    "السلام عليكم ورحمة الله",
    "صباح الخير", "صباح النور", "صباح النور والسعادة",
    "مساء الخير", "مساء النور", "مساء الخير والسعادة",
    "كيف حالك", "كيف حالكم", "كيف الحال", "كيفكم", "كيفك",
    "شلونك", "شلونكم", "شخبارك", "شخباركم",
    "اهلا", "أهلا", "اهلا وسهلا", "أهلا وسهلا",
    "مرحبا", "مرحبتين", "هلا", "هلا والله", "هلاوسهلا",
    "يا هلا", "يا مرحبا",
    "شكرا", "شكراً", "مشكور", "مشكورة", "مشكورين",
    "جزاك الله", "جزاكم الله", "بارك الله", "بارك الله فيك",
    "الله يعطيك", "الله يعطيك العافية", "يعطيك العافية",
    "تسلم", "تسلمي", "تسلموا",
    "عفوا", "العفو", "على الرحب", "على الرحب والسعة",
    "تحياتي", "تحياتنا", "مع التحية",
    "الحمد لله", "الحمدلله", "بخير", "تمام", "زين",
    "طيب", "اوك", "اوكي", "ممتاز", "رائع", "جميل",
    "حلو", "حلوة", "زينة",
    "ياجماعه", "يا جماعة", "يا جماعه", "جماعة", "جماعه",
    "اخواني", "اخوان", "اخواتي", "اخوات",
    "شباب", "شبابنا", "بنات", "بناتنا",
    "تصبح على خير", "تصبحون على خير",
    "طابت ليلتكم", "طابت مساؤكم",
    "منورين", "منور", "نورت", "نورتي", "نورتوا",
    "الله يسعدك", "الله يسعدكم",
    "وفقك الله", "وفقكم الله",
    "بالتوفيق", "بالتوفيق للجميع",
})

_NORMALIZED_GREETINGS: frozenset = frozenset(
    _normalize_arabic_for_compare(g)
    for g in _ARABIC_GREETINGS_RAW
) - {""}


def is_arabic_greeting(text: str) -> bool:
    """هل النص تحية عربية طبيعية قصيرة؟"""
    if not text:
        return False
    text = str(text).strip()
    if not text or len(text) > 40:
        return False
    if not _is_arabic_dominant(text):
        return False
    if re.search(r"(?:https?://|www\.|t\.me/|@\w+)", text):
        return False

    normalized = _normalize_arabic_for_compare(text)
    if not normalized:
        return False
    if normalized in _NORMALIZED_GREETINGS:
        return True

    words = re.findall(r"[^\s]+", text)
    if not words or len(words) > 4:
        return False

    matched = 0
    for w in words:
        w_norm = _normalize_arabic_for_compare(w)
        if not w_norm:
            continue
        for g_norm in _NORMALIZED_GREETINGS:
            if g_norm and (
                g_norm == w_norm
                or g_norm in w_norm
                or w_norm in g_norm
            ):
                matched += 1
                break
    return matched == len(words)


# ═════════════════════════════════════════════════════════════════════════════
# 4. تطبيع + فحص الكلمات المحظورة
# ═════════════════════════════════════════════════════════════════════════════

_WORD_SEP_CLASS = r'[\s\-_.|/*+=~^´`°•●○◦▪▫■□♦♢※]'
_compiled_patterns: "OrderedDict[str, re.Pattern]" = OrderedDict()
_compiled_spaced: "OrderedDict[str, re.Pattern]" = OrderedDict()


def normalize_banned_word(word: Any) -> str:
    if not word:
        return ""
    return _normalize_text(str(word)).lower().strip()


def _get_pattern(word: str) -> Optional[re.Pattern]:
    cached = _compiled_patterns.get(word)
    if cached is not None:
        _compiled_patterns.move_to_end(word)
        return cached
    try:
        escaped = re.escape(word).replace(r'\ ', r'\s+')
        pat = re.compile(
            rf'(?<!\w){escaped}(?!\w)',
            re.IGNORECASE | re.UNICODE,
        )
    except Exception:
        return None
    _compiled_patterns[word] = pat
    if len(_compiled_patterns) > _CACHE_MAX_PATTERNS:
        _compiled_patterns.popitem(last=False)
    return pat


def _get_spaced_pattern(word: str) -> Optional[re.Pattern]:
    cached = _compiled_spaced.get(word)
    if cached is not None:
        _compiled_spaced.move_to_end(word)
        return cached
    try:
        if len(word) < 3 or len(word) > 15:
            return None
        chars = list(word)
        body = r'[\s\-_.|/*+=~^`•●○▪▫■□♦♢※]{1,2}'.join(
            re.escape(c) for c in chars
        )
        pat = re.compile(
            rf'(?<!\w){body}(?!\w)',
            re.IGNORECASE | re.UNICODE,
        )
    except Exception:
        return None
    _compiled_spaced[word] = pat
    if len(_compiled_spaced) > _CACHE_MAX_PATTERNS:
        _compiled_spaced.popitem(last=False)
    return pat


def _char_script(ch: str) -> str:
    if '\u0600' <= ch <= '\u06FF':
        return 'ar'
    if ch.isascii() and ch.isalpha():
        return 'lat'
    return 'other'


def _compact_boundary_ok(compact_text: str, compact_word: str) -> bool:
    try:
        idx = compact_text.find(compact_word)
        if idx == -1:
            return False
        if compact_word == compact_text:
            return True
        if len(compact_word) >= 6:
            return True
        end_idx = idx + len(compact_word)
        before = compact_text[idx - 1] if idx > 0 else ''
        after = compact_text[end_idx] if end_idx < len(compact_text) else ''
        if before and before.isalnum() and compact_word[0].isalnum():
            if _char_script(before) == _char_script(compact_word[0]):
                if _char_script(before) in ('ar', 'lat'):
                    return False
        if after and after.isalnum() and compact_word[-1].isalnum():
            if _char_script(after) == _char_script(compact_word[-1]):
                if _char_script(after) in ('ar', 'lat'):
                    return False
        return True
    except Exception:
        return True


def contains_banned_word(text: str, banned_word: str) -> bool:
    """هل النص يحتوي الكلمة؟ — يتخطى التحيات، يمنع substring القصير."""
    if not text or not banned_word:
        return False
    if len(text) > 4000:
        text = text[:4000]

    try:
        if is_arabic_greeting(text):
            return False

        norm_text = _normalize_text(text).lower()
        norm_word = normalize_banned_word(banned_word)
        if not norm_word:
            return False

        pat = _get_pattern(norm_word)
        if pat is not None and pat.search(norm_text):
            return True

        if len(norm_word) >= 3:
            spaced = _get_spaced_pattern(norm_word)
            if spaced is not None and spaced.search(norm_text):
                return True

        if len(norm_word) >= _COMPACT_MIN_LEN:
            compact_text = re.sub(_WORD_SEP_CLASS, '', norm_text)
            compact_word = re.sub(_WORD_SEP_CLASS, '', norm_word)
            if compact_word and compact_word in compact_text:
                if _compact_boundary_ok(compact_text, compact_word):
                    return True

        return False
    except Exception as e:
        logger.debug("contains_banned_word error: %s", e)
        return False


# ═════════════════════════════════════════════════════════════════════════════
# 5. إبطال الكاش
# ═════════════════════════════════════════════════════════════════════════════

async def _invalidate_cache(scope_id: Optional[int] = None) -> bool:
    if _HAS_INV_ASYNC and callable(_inv_async):
        try:
            r = _inv_async(scope_id) if scope_id is not None else _inv_async()
            if asyncio.iscoroutine(r):
                await r
            return True
        except Exception as e:
            logger.debug("invalidate async: %s", e)

    if _HAS_INV_SYNC and callable(_inv_sync):
        try:
            r = _inv_sync(scope_id) if scope_id is not None else _inv_sync()
            if asyncio.iscoroutine(r):
                await r
            return True
        except Exception as e:
            logger.debug("invalidate sync: %s", e)

    return False


# ═════════════════════════════════════════════════════════════════════════════
# 6. الصلاحيات
# ═════════════════════════════════════════════════════════════════════════════

def is_developer(user_id: int) -> bool:
    if not user_id or not _HAS_CONFIG:
        return False

    try:
        owner = int(getattr(CONFIG, 'PRIMARY_OWNER_ID', 0) or 0)
        if owner and user_id == owner:
            return True
    except Exception:
        pass

    for attr in ('is_developer', 'is_dev', 'is_owner', 'is_super_admin'):
        fn = getattr(CONFIG, attr, None)
        if callable(fn):
            try:
                if fn(user_id):
                    return True
            except Exception:
                continue

    for attr in ('DEVELOPER_IDS', 'OWNER_IDS', 'ADMIN_IDS'):
        ids = getattr(CONFIG, attr, None)
        if ids:
            try:
                if user_id in ids:
                    return True
            except Exception:
                continue

    return False


async def is_group_admin(
    chat_id: int,
    user_id: int,
    bot: Any = None,
) -> bool:
    if not user_id:
        return False
    if is_developer(user_id):
        return True
    if not chat_id or chat_id == GLOBAL_CHAT_ID:
        return False

    if bot is not None:
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            status = getattr(member, 'status', None)
            if status in ('administrator', 'creator'):
                return True
        except Exception as e:
            logger.debug("get_chat_member(%s,%s): %s", chat_id, user_id, e)

    if _HAS_DB:
        try:
            db_type = getattr(DB, 'DB_TYPE', 'sqlite')
            if db_type == 'postgres':
                sql = (
                    "SELECT 1 FROM group_admins "
                    "WHERE chat_id = $1 AND user_id = $2 LIMIT 1"
                )
            else:
                sql = (
                    "SELECT 1 FROM group_admins "
                    "WHERE chat_id = ? AND user_id = ? LIMIT 1"
                )
            row = await DB.fetchval(sql, (chat_id, user_id))
            if row is not None:
                return True
        except Exception as e:
            logger.debug("check group_admin in DB: %s", e)

    return False


# ═════════════════════════════════════════════════════════════════════════════
# 7. Path 1 — Global (المطور)
# ═════════════════════════════════════════════════════════════════════════════

class GlobalBannedWordsPath:
    """مسار الكلمات المحظورة عالمياً (chat_id = -1)."""

    SCOPE_ID: int = GLOBAL_CHAT_ID

    @classmethod
    async def add(cls, word: str, user_id: int) -> Tuple[bool, str]:
        if not is_developer(user_id):
            return False, OpReason.NO_PERMS.value

        word = (word or "").strip()
        if not word or len(word) < MIN_WORD_LEN or len(word) > MAX_WORD_LEN:
            return False, OpReason.INVALID.value
        if not _HAS_DB:
            return False, OpReason.DB_ERROR.value

        try:
            result = await DB.add_banned_word(cls.SCOPE_ID, word, user_id)
        except Exception as e:
            logger.error("Global.add(%r) DB error: %s", word, e, exc_info=True)
            return False, OpReason.DB_ERROR.value

        added_ok, is_dup = (
            result if isinstance(result, tuple) and len(result) == 2
            else (bool(result), False)
        )

        if added_ok:
            await _invalidate_cache(cls.SCOPE_ID)
            logger.info("✅ GLOBAL-ADD | word=%r user=%s", word, user_id)
            return True, OpReason.ADDED.value
        if is_dup:
            return False, OpReason.DUPLICATE.value
        return False, OpReason.DB_ERROR.value

    @classmethod
    async def remove(cls, word: str, user_id: int) -> Tuple[bool, str]:
        if not is_developer(user_id):
            return False, OpReason.NO_PERMS.value

        word = (word or "").strip()
        if not word:
            return False, OpReason.INVALID.value
        if not _HAS_DB:
            return False, OpReason.DB_ERROR.value

        removed = False
        for method in (
            'remove_banned_word',
            'delete_banned_word',
            'remove_banned_word_by_text',
        ):
            fn = getattr(DB, method, None)
            if not callable(fn):
                continue
            try:
                r = fn(cls.SCOPE_ID, word)
                if asyncio.iscoroutine(r):
                    r = await r
                if r:
                    removed = True
                    break
            except Exception as e:
                logger.debug("DB.%s(%s,%r): %s", method, cls.SCOPE_ID, word, e)
                continue

        if removed:
            await _invalidate_cache(cls.SCOPE_ID)
            logger.info("✅ GLOBAL-REMOVE | word=%r user=%s", word, user_id)
            return True, OpReason.REMOVED.value
        return False, OpReason.NOT_FOUND.value

    @classmethod
    async def list(cls) -> List[str]:
        try:
            words = await get_banned_words_cached(cls.SCOPE_ID)
            return list(words or [])
        except Exception as e:
            logger.debug("Global.list: %s", e)
            return []


# ═════════════════════════════════════════════════════════════════════════════
# 8. Path 2 — Group (مشرف المجموعة)
# ═════════════════════════════════════════════════════════════════════════════

class GroupBannedWordsPath:
    """مسار الكلمات المحظورة لمجموعة محددة."""

    @staticmethod
    async def add(
        chat_id: int,
        word: str,
        user_id: int,
        bot: Any = None,
    ) -> Tuple[bool, str]:
        if not chat_id or chat_id == GLOBAL_CHAT_ID:
            return False, OpReason.INVALID.value
        if not await is_group_admin(chat_id, user_id, bot=bot):
            return False, OpReason.NO_PERMS.value

        word = (word or "").strip()
        if not word or len(word) < MIN_WORD_LEN or len(word) > MAX_WORD_LEN:
            return False, OpReason.INVALID.value
        if not _HAS_DB:
            return False, OpReason.DB_ERROR.value

        try:
            result = await DB.add_banned_word(chat_id, word, user_id)
        except Exception as e:
            logger.error(
                "Group.add(%s, %r) DB error: %s",
                chat_id, word, e, exc_info=True,
            )
            return False, OpReason.DB_ERROR.value

        added_ok, is_dup = (
            result if isinstance(result, tuple) and len(result) == 2
            else (bool(result), False)
        )

        if added_ok:
            await _invalidate_cache(chat_id)
            logger.info(
                "✅ GROUP-ADD | chat=%s word=%r user=%s",
                chat_id, word, user_id,
            )
            return True, OpReason.ADDED.value
        if is_dup:
            return False, OpReason.DUPLICATE.value
        return False, OpReason.DB_ERROR.value

    @staticmethod
    async def remove(
        chat_id: int,
        word: str,
        user_id: int,
        bot: Any = None,
    ) -> Tuple[bool, str]:
        if not chat_id or chat_id == GLOBAL_CHAT_ID:
            return False, OpReason.INVALID.value
        if not await is_group_admin(chat_id, user_id, bot=bot):
            return False, OpReason.NO_PERMS.value

        word = (word or "").strip()
        if not word:
            return False, OpReason.INVALID.value
        if not _HAS_DB:
            return False, OpReason.DB_ERROR.value

        removed = False
        for method in (
            'remove_banned_word',
            'delete_banned_word',
            'remove_banned_word_by_text',
        ):
            fn = getattr(DB, method, None)
            if not callable(fn):
                continue
            try:
                r = fn(chat_id, word)
                if asyncio.iscoroutine(r):
                    r = await r
                if r:
                    removed = True
                    break
            except Exception as e:
                logger.debug("DB.%s(%s,%r): %s", method, chat_id, word, e)
                continue

        if removed:
            await _invalidate_cache(chat_id)
            logger.info(
                "✅ GROUP-REMOVE | chat=%s word=%r user=%s",
                chat_id, word, user_id,
            )
            return True, OpReason.REMOVED.value
        return False, OpReason.NOT_FOUND.value

    @staticmethod
    async def list(chat_id: int) -> List[str]:
        if not chat_id or chat_id == GLOBAL_CHAT_ID:
            return []
        try:
            words = await get_banned_words_cached(chat_id)
            return list(words or [])
        except Exception as e:
            logger.debug("Group.list(%s): %s", chat_id, e)
            return []


# ═════════════════════════════════════════════════════════════════════════════
# 9. BannedWordsManager (Router موحّد)
# ═════════════════════════════════════════════════════════════════════════════

class BannedWordsManager:

    @staticmethod
    async def add(
        word: str,
        user_id: int,
        scope: BannedScope,
        chat_id: Optional[int] = None,
        bot: Any = None,
    ) -> Tuple[bool, str]:
        if scope == BannedScope.GLOBAL:
            success, reason = await GlobalBannedWordsPath.add(word, user_id)
        elif scope == BannedScope.GROUP:
            if not chat_id:
                return False, OpReason.INVALID.value
            success, reason = await GroupBannedWordsPath.add(
                chat_id, word, user_id, bot=bot,
            )
        else:
            return False, OpReason.INVALID.value

        logger.info(
            "📍 ROUTE-ADD | scope=%s chat=%s word=%r user=%s → %s",
            scope.value, chat_id, word, user_id,
            "OK" if success else f"FAIL({reason})",
        )
        return success, reason

    @staticmethod
    async def remove(
        word: str,
        user_id: int,
        scope: BannedScope,
        chat_id: Optional[int] = None,
        bot: Any = None,
    ) -> Tuple[bool, str]:
        if scope == BannedScope.GLOBAL:
            success, reason = await GlobalBannedWordsPath.remove(word, user_id)
        elif scope == BannedScope.GROUP:
            if not chat_id:
                return False, OpReason.INVALID.value
            success, reason = await GroupBannedWordsPath.remove(
                chat_id, word, user_id, bot=bot,
            )
        else:
            return False, OpReason.INVALID.value

        logger.info(
            "📍 ROUTE-REMOVE | scope=%s chat=%s word=%r user=%s → %s",
            scope.value, chat_id, word, user_id,
            "OK" if success else f"FAIL({reason})",
        )
        return success, reason

    @staticmethod
    async def list(
        user_id: int,
        scope: BannedScope,
        chat_id: Optional[int] = None,
    ) -> List[str]:
        if scope == BannedScope.GLOBAL:
            return await GlobalBannedWordsPath.list()
        if scope == BannedScope.GROUP and chat_id:
            return await GroupBannedWordsPath.list(chat_id)
        return []

    @staticmethod
    async def get_words_for_filtering(chat_id: int) -> List[str]:
        """القائمة المُدمجة (global + group) للفلترة."""
        result: List[str] = []
        seen: Set[str] = set()

        try:
            global_words = await get_banned_words_cached(GLOBAL_CHAT_ID)
            for w in global_words or []:
                n = normalize_banned_word(w)
                if n and n not in seen:
                    seen.add(n)
                    result.append(str(w))
        except Exception as e:
            logger.debug("get global words for filtering: %s", e)

        if chat_id and chat_id != GLOBAL_CHAT_ID:
            try:
                group_words = await get_banned_words_cached(chat_id)
                for w in group_words or []:
                    n = normalize_banned_word(w)
                    if n and n not in seen:
                        seen.add(n)
                        result.append(str(w))
            except Exception as e:
                logger.debug("get group words for filtering: %s", e)

        return result

    @staticmethod
    async def check_message(text: str, chat_id: int) -> Optional[str]:
        """فحص رسالة — يُرجع الكلمة المطابقة أو None."""
        if not text:
            return None
        if is_arabic_greeting(text):
            logger.debug(
                "AR-GREETING-SKIP | chat=%s text=%r",
                chat_id, text[:60],
            )
            return None

        words = await BannedWordsManager.get_words_for_filtering(chat_id)
        if not words:
            return None

        for bw in words:
            if contains_banned_word(text, bw):
                return bw
        return None

    @staticmethod
    def is_developer(user_id: int) -> bool:
        return is_developer(user_id)

    @staticmethod
    async def is_group_admin(
        chat_id: int,
        user_id: int,
        bot: Any = None,
    ) -> bool:
        return await is_group_admin(chat_id, user_id, bot=bot)

    @staticmethod
    async def invalidate_cache(scope_id: Optional[int] = None) -> bool:
        return await _invalidate_cache(scope_id)


# ═════════════════════════════════════════════════════════════════════════════
# 10. Public API
# ═════════════════════════════════════════════════════════════════════════════

__all__ = [
    "BannedWordsManager",
    "GlobalBannedWordsPath",
    "GroupBannedWordsPath",
    "BannedScope",
    "OpReason",
    "GLOBAL_CHAT_ID",
    "MIN_WORD_LEN",
    "MAX_WORD_LEN",
    "is_developer",
    "is_group_admin",
    "normalize_banned_word",
    "contains_banned_word",
    "is_arabic_greeting",
    "__version__",
]


# ═════════════════════════════════════════════════════════════════════════════
# Load Beacon
# ═════════════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "✅ banned_words_manager v%s loaded | "
        "DUAL-PATH (global=%d, group) | "
        "greetings=%d | compact_min=%d | "
        "detector_helpers=%s | db=%s | cache=%s",
        __version__,
        GLOBAL_CHAT_ID,
        len(_ARABIC_GREETINGS_RAW),
        _COMPACT_MIN_LEN,
        "yes" if _HAS_DETECTOR_HELPERS else "no",
        "yes" if _HAS_DB else "no",
        "yes" if _HAS_BANNED_CACHE else "no",
    )
except Exception:
    pass