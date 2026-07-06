import json
from pathlib import Path
from config import TRANSLATIONS_PATH

user_language = {}

class TranslationManager:
    def __init__(self):
        self.translations = {}
        self.default_lang = "ar"
        self.load_translations()
    
    def load_translations(self):
        file_path = TRANSLATIONS_PATH / "translations.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.translations = json.load(f)
                print(f"✅ تم تحميل الترجمات")
                return
            except Exception as e:
                print(f"⚠️ فشل تحميل الترجمات: {e}")
        self.create_default_translations()
    
    def create_default_translations(self):
        self.translations = {
            "ar": {
                "welcome": "🌿 **مرحباً بك في ريلاكس مانيجر**",
                "help": "❓ **المساعدة**\n/start - القائمة الرئيسية",
                "no_channels": "لا توجد قنوات",
                "add_channel": "➕ إضافة قناة",
                "my_channels": "📡 قنواتي",
                "settings": "⚙️ الإعدادات",
                "back": "🔙 رجوع",
                "admin_only": "🔒 هذا الأمر للمشرفين فقط!",
                "error": "⚠️ حدث خطأ، حاول مرة أخرى",
                "cancelled": "❌ تم الإلغاء"
            },
            "en": {
                "welcome": "🌿 **Welcome to Relax Manager**",
                "help": "❓ **Help**\n/start - Main menu",
                "no_channels": "No channels",
                "add_channel": "➕ Add channel",
                "my_channels": "📡 My channels",
                "settings": "⚙️ Settings",
                "back": "🔙 Back",
                "admin_only": "🔒 For admins only!",
                "error": "⚠️ An error occurred, try again",
                "cancelled": "❌ Cancelled"
            }
        }
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.translations, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ فشل إنشاء ملف الترجمات: {e}")
    
    def get_text(self, lang: str, key: str) -> str:
        if lang in self.translations and key in self.translations[lang]:
            return self.translations[lang][key]
        if self.default_lang in self.translations and key in self.translations[self.default_lang]:
            return self.translations[self.default_lang][key]
        return key

translator = TranslationManager()

def get_text(user_id: int, key: str) -> str:
    lang = user_language.get(user_id, "ar")
    return translator.get_text(lang, key)

async def load_all_languages():
    print("✅ تم تحميل نظام الترجمات")
