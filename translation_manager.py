#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
translation_manager.py - مدير الترجمة v1.0.0
=====================================================================
يقرأ النصوص من locales/translations.json
يدعم:
  - get_text(lang, key, **kwargs) → نص مترجم
  - get_available_languages() → dict {code: name}
  - translate(text, target_lang) → ترجمة تقريبية (dictionary lookup)
  - reload() → إعادة التحميل من الملف
=====================================================================
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

_DEFAULT_TRANSLATIONS_PATH = Path(__file__).parent / "locales" / "translations.json"

# قاموس ترجمة مشترك للعبارات الشائعة (لكي تترجم رسائل المستخدمين فعلياً)
# يمكن توسيعه بسهولة
_COMMON_PHRASES: Dict[str, Dict[str, str]] = {
    "ar": {
        "hello": "مرحبا",
        "hi": "أهلاً",
        "thanks": "شكراً",
        "thank you": "شكراً لك",
        "good morning": "صباح الخير",
        "good evening": "مساء الخير",
        "goodbye": "وداعاً",
        "yes": "نعم",
        "no": "لا",
        "please": "من فضلك",
        "sorry": "آسف",
        "how are you": "كيف حالك؟",
        "i love you": "أحبك",
        "welcome": "أهلاً وسهلاً",
        "help": "مساعدة",
    },
    "en": {
        "مرحبا": "Hello",
        "أهلاً": "Hi",
        "شكراً": "Thanks",
        "شكرا": "Thanks",
        "صباح الخير": "Good morning",
        "مساء الخير": "Good evening",
        "وداعاً": "Goodbye",
        "نعم": "Yes",
        "لا": "No",
        "من فضلك": "Please",
        "آسف": "Sorry",
        "كيف حالك": "How are you?",
        "كيف حالك؟": "How are you?",
        "أحبك": "I love you",
        "أهلاً وسهلاً": "Welcome",
        "مساعدة": "Help",
    },
    "fr": {
        "hello": "Bonjour",
        "hi": "Salut",
        "thanks": "Merci",
        "goodbye": "Au revoir",
        "yes": "Oui",
        "no": "Non",
        "please": "S'il vous plaît",
        "sorry": "Désolé",
        "welcome": "Bienvenue",
        "help": "Aide",
    },
    "ru": {
        "hello": "Привет",
        "hi": "Привет",
        "thanks": "Спасибо",
        "goodbye": "До свидания",
        "yes": "Да",
        "no": "Нет",
        "please": "Пожалуйста",
        "sorry": "Извините",
        "welcome": "Добро пожаловать",
        "help": "Помощь",
    },
    "tr": {
        "hello": "Merhaba",
        "hi": "Selam",
        "thanks": "Teşekkürler",
        "goodbye": "Hoşçakal",
        "yes": "Evet",
        "no": "Hayır",
        "please": "Lütfen",
        "sorry": "Üzgünüm",
        "welcome": "Hoş geldiniz",
        "help": "Yardım",
    },
}


class TranslationManager:
    """مدير الترجمة المركزي."""

    _translations: Dict[str, Dict[str, str]] = {}
    _languages_meta: Dict[str, str] = {}
    _default_lang: str = "ar"
    _loaded: bool = False
    _path: Optional[Path] = None

    # =============================================================
    # تحميل
    # =============================================================

    @classmethod
    def load(cls, path: Optional[Path] = None, force: bool = False) -> bool:
        """تحميل ملف الترجمات. يعيد True عند النجاح."""
        if cls._loaded and not force:
            return True

        cls._path = Path(path) if path else _DEFAULT_TRANSLATIONS_PATH

        if not cls._path.exists():
            logger.error(f"❌ ملف الترجمات غير موجود: {cls._path}")
            return False

        try:
            with open(cls._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"❌ فشل قراءة ملف الترجمات: {e}")
            return False

        meta = data.pop("_meta", {})
        cls._default_lang = meta.get("default", "ar")
        cls._languages_meta = meta.get("languages", {})

        cls._translations = {
            lang: dict(entries)
            for lang, entries in data.items()
            if isinstance(entries, dict)
        }

        cls._loaded = True
        logger.info(
            f"✅ تم تحميل الترجمات: "
            f"{len(cls._translations)} لغة، "
            f"{sum(len(v) for v in cls._translations.values())} نص"
        )
        return True

    @classmethod
    def reload(cls) -> bool:
        return cls.load(cls._path, force=True)

    # =============================================================
    # معلومات اللغات
    # =============================================================

    @classmethod
    def get_available_languages(cls) -> Dict[str, str]:
        """{code: display_name}"""
        if not cls._loaded:
            cls.load()
        return dict(cls._languages_meta)

    @classmethod
    def get_default_language(cls) -> str:
        return cls._default_lang

    @classmethod
    def is_supported(cls, lang: str) -> bool:
        if not cls._loaded:
            cls.load()
        return lang in cls._translations

    # =============================================================
    # جلب النصوص
    # =============================================================

    @classmethod
    def get_text(cls, lang: str, key: str, **kwargs) -> str:
        """
        يجلب نصاً بلغة معينة.
        - إن لم تكن اللغة موجودة → fallback للافتراضية
        - إن لم يكن المفتاح موجوداً → يعيد المفتاح نفسه
        - **kwargs يُمرَّر إلى str.format()
        """
        if not cls._loaded:
            cls.load()

        lang = lang or cls._default_lang

        # محاولة اللغة المطلوبة
        entry = cls._translations.get(lang, {}).get(key)
        if entry is None and lang != cls._default_lang:
            # fallback
            entry = cls._translations.get(cls._default_lang, {}).get(key)

        if entry is None:
            logger.debug(f"⚠️ مفتاح ترجمة مفقود: lang={lang}, key={key}")
            return key

        if kwargs:
            try:
                return entry.format(**kwargs)
            except (KeyError, IndexError, ValueError) as e:
                logger.warning(
                    f"⚠️ فشل format للنص: key={key}, lang={lang}, err={e}"
                )
                return entry
        return entry

    # =============================================================
    # الترجمة الفعلية (dictionary-based)
    # =============================================================

    @classmethod
    def translate(cls, text: str, target_lang: str) -> Optional[str]:
        """
        ترجمة نص بسيط باستخدام قاموس العبارات الشائعة.
        - إن كانت الترجمة غير معروفة → يعيد None
        - الحساسية للـ case → يبحث بصيغة lowercase
        """
        if not text or not target_lang:
            return None

        stripped = text.strip()
        if not stripped:
            return None

        # إزالة علامات ترقيم للأطراف
        normalized = re.sub(r"[!؟?،,.\s]+$", "", stripped).strip().lower()

        phrases = _COMMON_PHRASES.get(target_lang, {})
        if not phrases:
            return None

        # بحث مباشر
        if normalized in phrases:
            return phrases[normalized]

        # بحث عن تطابق كلمات كاملة
        for src, dst in phrases.items():
            pattern = r"\b" + re.escape(src) + r"\b"
            if re.search(pattern, stripped, flags=re.IGNORECASE):
                translated = re.sub(
                    pattern, dst, stripped, count=1, flags=re.IGNORECASE
                )
                return translated

        return None

    # =============================================================
    # إحصائيات
    # =============================================================

    @classmethod
    def stats(cls) -> Dict[str, Any]:
        if not cls._loaded:
            cls.load()
        return {
            "loaded": cls._loaded,
            "path": str(cls._path) if cls._path else None,
            "languages": list(cls._translations.keys()),
            "total_keys": sum(len(v) for v in cls._translations.values()),
            "default": cls._default_lang,
        }


# تحميل تلقائي عند الاستيراد
TranslationManager.load()