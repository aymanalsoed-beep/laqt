#!/usr/bin/env python3
"""يحوّل نسخ «التفصيل في إعراب آيات التنزيل» من data/sources/tafseel/txt/<sss>.txt
إلى data/sources/tafseel/<sss>.json الذي يقرؤه build_db.py.

صيغة الملف النصي (يُكتب يدويًا بعد مراجعة ناتج arabi.tools على صور الكتاب):
  # <الآية أو من-إلى> | <المجلد>:<الصفحة الأولى>-<الصفحة الأخيرة>
  سطور الإعراب، وفيها: [[كلمة]] للكلمة المعربة، ^ن لرقم الحاشية (مرقمة لكل آية)،
  «## عنوان» لعنوان فائدة أو وجه، و«※» في أول سطر حكم الجملة.
  ~ سطر حاشية (بترتيب أرقامها)، و«~~ » فقرة تابعة للحاشية السابقة

التشغيل:  python3 scripts/import_tafseel.py 2
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "sources" / "tafseel"
AR = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def convert(sura: int) -> None:
    src = DIR / "txt" / f"{sura:03d}.txt"
    ayat, cur = [], None
    for ln, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
        line = line.rstrip()
        m = re.match(r"^# ([\d-]+) \| (\d+):(\d+)-(\d+)$", line)
        if m:
            a = [int(x) for x in m.group(1).split("-")]
            cur = {"ayah": a[0] if len(a) == 1 else a, "volume": int(m.group(2)),
                   "pages": [int(m.group(3)), int(m.group(4))], "body": [], "notes": []}
            ayat.append(cur)
        elif line.startswith("~~ "):
            cur["notes"][-1] += "\n" + line[3:].strip()
        elif line.startswith("~ "):
            cur["notes"].append(line[2:].strip())
        elif line.strip():
            cur["body"].append(line.strip())
    out = []
    for it in ayat:
        text = "\n".join(it["body"])
        refs = sorted({int(x.translate(AR)) for x in re.findall(r"\^([٠-٩\d]+)", text)})
        if refs != list(range(1, len(it["notes"]) + 1)):
            sys.exit(f"الآية {it['ayah']}: أرقام الحواشي {refs} لا توافق عددها {len(it['notes'])}")
        out.append({"ayah": it["ayah"], "volume": it["volume"], "pages": it["pages"],
                    "text": text, "notes": it["notes"]})
    doc = {"surah": sura, "book": "التفصيل في إعراب آيات التنزيل",
           "method": "استُخرج النص بأداة arabi.tools (OCR) ثم رُوجع على صور الكتاب، وأُعيد ترقيم الحواشي لكل آية",
           "ayat": out}
    (DIR / f"{sura:03d}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"سورة {sura}: {len(out)} مادة")


if __name__ == "__main__":
    for s in sys.argv[1:]:
        convert(int(s))
