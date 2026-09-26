from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    script: re.Pattern
    name_examples: str = ""
    label_examples: str = ""


_ARABIC = r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
_CYRILLIC = r"[\u0400-\u04FF]"

LANGUAGES: dict[str, Language] = {
    lang.code: lang
    for lang in [
        Language(
            "he",
            "Hebrew",
            re.compile(r"[\u0590-\u05FF]"),
            name_examples='"אבי כהן" -> "Avi Cohen" (not "my father priest"), "יוסי" -> "Yossi", '
            '"חיים" -> "Haim", "צביקה" -> "Tzvika", "שירה" -> "Shira", "תהילה" -> "Tehila"',
            label_examples='"אבא" -> "Dad", "אמא" -> "Mom", "דירה" -> "Apartment", '
            '"חברת אשראי" -> "Credit Company", "שיעור פרטי" -> "Private Lesson", "בר אילן" -> "Bar Ilan"',
        ),
        Language(
            "ar",
            "Arabic",
            re.compile(_ARABIC),
            name_examples='"محمد" -> "Mohammed", "فاطمة" -> "Fatima", "خالد" -> "Khaled"',
            label_examples='"أمي" -> "Mom", "أبي" -> "Dad", "طبيب الأسنان" -> "Dentist"',
        ),
        Language("fa", "Persian", re.compile(_ARABIC)),
        Language(
            "ru",
            "Russian",
            re.compile(_CYRILLIC),
            name_examples='"Саша Иванов" -> "Sasha Ivanov", "Юлия" -> "Yulia", "Щукин" -> "Shchukin"',
            label_examples='"мама" -> "Mom", "папа" -> "Dad", "работа" -> "Work"',
        ),
        Language("uk", "Ukrainian", re.compile(_CYRILLIC)),
        Language("bg", "Bulgarian", re.compile(_CYRILLIC)),
        Language("el", "Greek", re.compile(r"[\u0370-\u03FF\u1F00-\u1FFF]")),
        Language("hi", "Hindi", re.compile(r"[\u0900-\u097F]")),
        Language("th", "Thai", re.compile(r"[\u0E00-\u0E7F]")),
        Language("zh", "Chinese", re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")),
        Language("ja", "Japanese", re.compile(r"[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF]")),
        Language("ko", "Korean", re.compile(r"[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7AF]")),
    ]
}
