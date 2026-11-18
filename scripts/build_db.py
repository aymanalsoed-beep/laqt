#!/usr/bin/env python3
"""يبني قاعدة بيانات «لقط» (db/laqt.db) من المصادر في data/ ويتحقق منها.

التشغيل:  python3 scripts/build_db.py
"""
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mathur import import_mathur  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB = ROOT / "db" / "laqt.db"
SCHEMA = ROOT / "db" / "schema.sql"
REPORT = ROOT / "data" / "fawaid" / "link_report.md"
CONFIG = json.loads((ROOT / "scripts" / "site_config.json").read_text(encoding="utf-8"))

errors = []


def check(cond, msg):
    if not cond:
        errors.append(msg)


AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ࣰۭ-ࣳـ]")


def plain(s: str) -> str:
    """تجريد النص للمقارنة: حذف التشكيل وتوحيد الهمزات والألفات."""
    s = unicodedata.normalize("NFC", s)
    s = AR_DIACRITICS.sub("", s)
    s = re.sub("[إأآٱا]", "ا", s)
    s = s.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي").replace("ء", "")
    s = re.sub(r"[^ء-ي ]", " ", s)
    s = s.replace("ياايها", "يا ايها").replace("يايها", "يا ايها")
    return re.sub(r"\s+", " ", s).strip()


# مصادر المعنى الإجمالي. النص من بيانات QUL (https://qul.tarteel.ai) عبر
# github.com/spa5k/tafsir_api، وطوبق بنسختيهما في تراث (الكتابان 1407 و18102).
TAFSIR_SOURCES = [
    {"dir": "muyassar", "id": 1, "title": "التفسير الميسر",
     "author": "نخبة من أساتذة التفسير", "edition": "مجمع الملك فهد لطباعة المصحف الشريف",
     "notes": "QUL tafsir 38؛ يطابق ط2 (1430هـ) في تراث، الكتاب 1407"},
    {"dir": "mukhtasar", "id": 2, "title": "المختصر في تفسير القرآن الكريم",
     "author": "جماعة من علماء التفسير", "edition": "مركز تفسير للدراسات القرآنية",
     "notes": "QUL tafsir 251؛ يطابق ط3 في تراث، الكتاب 18102"},
]


def import_tafsir(con, gid_of):
    """يستورد المصدرين إلى entries بنوع maana. الآيات التي يجمعها المصدر في شرح واحد
    تُحفظ مادةً واحدة مربوطة بالمقطع كله. وما يسبق «[التفسير]» في أول السورة
    (تسمية السورة ومقاصدها) يُترك لأنه ليس من نص التفسير الميسر المطبوع."""
    counts = {}
    for src in TAFSIR_SOURCES:
        con.execute("INSERT INTO sources (id, title, author, edition, notes) VALUES (?,?,?,?,?)",
                    (src["id"], src["title"], src["author"], src["edition"], src["notes"]))
        n = 0
        for sura in range(1, 115):
            rows = json.loads((DATA / "sources/tafsir" / src["dir"] / f"{sura}.json").read_text(encoding="utf-8"))
            check(len(rows) == len([1 for (s, _) in gid_of if s == sura]) and
                  all(r["surah"] == sura and r["ayah"] == i for i, r in enumerate(rows, 1)),
                  f"{src['title']}: آيات سورة {sura} ناقصة أو غير مرتبة")
            groups = []
            for r in rows:
                text = r["text"].strip()
                if "[التفسير]" in text:
                    text = text.split("[التفسير]", 1)[1].strip()
                check(bool(text), f"{src['title']}: نص فارغ في {sura}:{r['ayah']}")
                if groups and groups[-1][2] == text:
                    groups[-1][1] = r["ayah"]
                else:
                    groups.append([r["ayah"], r["ayah"], text])
            for a, b, text in groups:
                cur = con.execute(
                    "INSERT INTO entries (kind, body, source_id, status, origin, sort_order) VALUES (?,?,?,?,?,?)",
                    ("maana", text, src["id"], "published", "qul", src["id"]))
                con.execute("INSERT INTO entry_ayat VALUES (?,?,?,?,?)",
                            (cur.lastrowid, gid_of[(sura, a)], gid_of[(sura, b)], None, "primary"))
                n += 1
        counts[src["title"]] = n
    return counts


def main():
    hafs = json.loads((DATA / "sources/kfgqpc/hafsData_v18.json").read_text(encoding="utf-8"))
    lists = json.loads((DATA / "sources/quran-meta/hafs_lists.json").read_text(encoding="utf-8"))
    fawaid = json.loads((DATA / "fawaid/initial_fawaid.json").read_text(encoding="utf-8"))

    check(len(hafs) == 6236, f"عدد الآيات {len(hafs)} وليس 6236")

    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))

    con.execute("INSERT INTO riwayat VALUES ('hafs','رواية حفص عن عاصم',"
                "'مجمع الملك فهد لطباعة المصحف الشريف — بيانات حفص للمطورين','18')")
    con.executemany("INSERT INTO content_kinds VALUES (?,?,?)", [
        # الخانات الخمس بترتيبها المعتمد في «الملف الجامع»
        ("qiraat", "القراءات", 1), ("maana", "المعنى الإجمالي", 2),
        ("tafsir", "التفسير بالمأثور", 3), ("irab", "الإعراب", 4), ("faida", "الفوائد", 5),
    ])

    # --- المصفوفات المساعدة (معرّف الآية التسلسلي 1..6236) ---
    def bucket(starts, gid):
        # starts: [0, s1, s2, ..., end+1]
        for i in range(1, len(starts) - 1):
            if starts[i] <= gid < starts[i + 1]:
                return i
        raise ValueError(gid)

    rubs = lists["HizbQuarterList"]
    juzs = lists["JuzList"]
    manzils = lists["ManzilList"]
    sajdas = set(lists["SajdaList"])
    surah_list = lists["SurahList"]  # [first_ayah_id, count, revelation_order, rukus, name, is_meccan]
    check(len(rubs) == 242 and rubs[-1] == 6237, "قائمة الأرباع غير مكتملة")

    # --- السور ---
    pages = {}
    for row in hafs:
        pages.setdefault(row["sora"], []).append(row["page"])
    first = {}
    for row in hafs:
        first.setdefault(row["sora"], row)
    for sid in range(1, 115):
        start, count, order, _rukus, name_meta, meccan = surah_list[sid]
        r = first[sid]
        check(len(pages[sid]) == count, f"سورة {sid}: عدد الآيات {len(pages[sid])} ≠ {count}")
        con.execute("INSERT INTO surahs VALUES (?,?,?,?,?,?,?,?,?,?)", (
            sid, r["sora_name_ar"], AR_DIACRITICS.sub("", r["sora_name_ar"]).replace("ٱ", "ا"), r["sora_name_en"],
            count, "makki" if meccan else "madani", order, start, min(pages[sid]), max(pages[sid]),
        ))

    # --- الآيات ---
    # بدايات الأرباع: علامات ۞ في نص المجمع (مصحف المدينة)، ويضاف إليها ما يبدأ مع أول سورة
    # (لا تُكتب العلامة هناك) من قائمة quran-meta.
    marks = [gid for gid, r in enumerate(hafs, 1) if r["aya_text"].startswith("۞")]
    surah_starts = {s[0] for s in surah_list[1:115]}
    meta_starts = set(rubs[1:-1])
    rub_starts = sorted(set(marks) | (meta_starts & surah_starts))
    check(len(rub_starts) == 240, f"عدد الأرباع {len(rub_starts)} وليس 240")
    meta_diff = sorted(meta_starts ^ set(rub_starts))
    rubs = [0] + rub_starts + [6237]
    rub_starts = set(rub_starts)
    for gid, row in enumerate(hafs, start=1):
        check(row["id"] == gid, f"ترتيب غير متوقع عند {gid}")
        marked = row["aya_text"]
        text = re.sub(r"[  ]*[٠-٩]+\s*$", "", marked)  # حذف رقم الآية
        text = re.sub(r"^۞[  ]*", "", text)                      # حذف علامة الربع
        rub = bucket(rubs, gid)
        juz = (rub - 1) // 8 + 1
        check(abs(juz - row["jozz"]) <= 1, f"الآية {gid}: الجزء {row['jozz']} في المصدر و{juz} بالأرباع")
        con.execute("INSERT INTO ayat VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            gid, row["sora"], row["aya_no"], text, marked, row["aya_text_emlaey"],
            row["page"], row["line_start"], row["line_end"], juz, row["jozz"],
            (rub - 1) // 4 + 1, rub, int(gid in rub_starts), bucket(manzils, gid), int(gid in sajdas),
        ))

    for rid in range(1, 241):
        f, l = rubs[rid], rubs[rid + 1] - 1
        juz = con.execute("SELECT juz FROM ayat WHERE id=?", (f,)).fetchone()[0]
        con.execute("INSERT INTO rubs VALUES (?,?,?,?,?,?)", (rid, (rid - 1) // 4 + 1, juz, (rid - 1) % 4 + 1, f, l))

    print("مواضع تختلف فيها بدايات الأرباع عن quran-meta (اعتمدنا المجمع):",
          [f"{hafs[g-1]['sora']}:{hafs[g-1]['aya_no']}" for g in meta_diff])
    check(set(juzs[1:-1]) <= rub_starts | set(meta_diff), "بدايات الأجزاء ليست بدايات أرباع")

    # --- الفوائد ---
    gid_of = {(r["sora"], r["aya_no"]): i for i, r in enumerate(hafs, 1)}
    hizb_of = {i: (bucket(rubs, i) - 1) // 4 + 1 for i in range(1, 6237)}
    report = ["# تقرير ربط الفوائد بالآيات", "",
              f"عدد الفوائد: {len(fawaid)}", ""]
    hizb_diffs, quote_misses = [], []
    for order, f in enumerate(fawaid, 1):
        flags = list(f["flags"])
        # راجع صاحب المشروع الفوائد كلها (2026-11-18)، وتبقى الملاحظات للتوثيق
        status = "ready"
        con.execute(
            "INSERT INTO entries (id, kind, body, status, origin, legacy_id, legacy_msg, edits, flags, sort_order)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f["id"], "faida", f["text"], status, f["origin"], f["id"], f["source_message"],
             json.dumps(f["edits"], ensure_ascii=False), json.dumps(flags, ensure_ascii=False), order))
        ref_ayat = []
        for ref in f["refs"]:
            s, a, b = ref["sura"], ref["from_"], ref["to"]
            check((s, a) in gid_of and (s, b) in gid_of, f"الفائدة {f['id']}: موضع غير موجود {s}:{a}-{b}")
            if (s, a) not in gid_of or (s, b) not in gid_of:
                continue
            g1, g2 = gid_of[(s, a)], gid_of[(s, b)]
            con.execute("INSERT INTO entry_ayat VALUES (?,?,?,?,?)", (f["id"], g1, g2, f["place"], "primary"))
            ref_ayat.extend(range(g1, g2 + 1))
            if ref.get("hizb") and ref["hizb"] != hizb_of[g1]:
                hizb_diffs.append(f"- الفائدة {f['id']} ({s}:{a}): الحزب في الملف {ref['hizb']}، وفي المصحف {hizb_of[g1]}")
        # تحقق: هل الآيات المقتبسة بين ﴿ ﴾ موجودة في الآيات المربوطة؟
        target = {w.replace("ا", "") for g in ref_ayat for w in plain(hafs[g - 1]["aya_text_emlaey"]).split()}
        for q in re.findall(r"﴿([^﴾]+)﴾", f["text"]):
            words = [w.replace("ا", "") for w in plain(q).split()]
            words = [w for w in words if w]
            if len(words) < 2 or sum(w in target for w in words) / len(words) >= 0.8:
                continue
            def score(g):
                ws = {w.replace("ا", "") for w in plain(hafs[g - 1]["aya_text_emlaey"]).split()}
                return sum(w in ws for w in words) / len(words)
            best = max(range(1, 6237), key=score)
            check(score(best) >= 0.8, f"الفائدة {f['id']}: لم يُعثر على «{q.strip()[:50]}»")
            if score(best) < 0.8:
                continue
            target |= {w.replace("ا", "") for w in plain(hafs[best - 1]["aya_text_emlaey"]).split()}
            # الفائدة تظهر أيضًا تحت الآية المستشهد بها
            con.execute("INSERT OR IGNORE INTO entry_ayat VALUES (?,?,?,?,?)", (f["id"], best, best, None, "cited"))
            quote_misses.append(f"- الفائدة {f['id']}: «{q.strip()[:70]}» ← {hafs[best-1]['sora_name_ar']} {hafs[best-1]['aya_no']}")

    report += ["## الأحزاب", ""] + (hizb_diffs or ["كل أرقام الأحزاب في الملف تطابق المصحف."]) + [""]
    report += ["## آيات مستشهد بها داخل الفوائد", "",
               "كل آية مقتبسة بين ﴿ ﴾ من غير الآيات الأصلية للفائدة رُبطت بها الفائدة أيضًا (role = cited)، "
               "فتظهر الفائدة تحتها كذلك.", ""] + (quote_misses or ["لا شيء."]) + [""]
    REPORT.write_text("\n".join(report), encoding="utf-8")

    # --- المعنى الإجمالي: التفسير الميسر والمختصر ---
    n_tafsir = import_tafsir(con, gid_of)

    # --- التفسير بالمأثور والقراءات: الموسوعة والبدور الزاهرة والمحتسب ---
    n_mathur = import_mathur(con, gid_of, CONFIG.get("qiraat_show_usul", True))

    con.commit()

    # --- ملخص ---
    n_ayat = con.execute("SELECT count(*) FROM ayat").fetchone()[0]
    n_with = con.execute("SELECT count(*) FROM ayah_overview WHERE fawaid>0").fetchone()[0]
    n_entries = con.execute("SELECT count(*) FROM entries WHERE kind='faida'").fetchone()[0]
    n_links = con.execute("SELECT count(*) FROM entry_ayat").fetchone()[0]
    con.execute("VACUUM")
    con.close()
    print(f"الآيات: {n_ayat} | الفوائد: {n_entries} | روابط: {n_links} | آيات لها فوائد: {n_with} | "
          f"آيات تنتظر: {n_ayat - n_with}")
    print("المعنى الإجمالي: " + " | ".join(f"{k}: {v} مقطعًا" for k, v in n_tafsir.items()))
    print(f"التفسير بالمأثور: {n_mathur['tafsir']} مادة | القراءات: {n_mathur['qiraat']} مادة")
    print(f"فروق الأحزاب: {len(hizb_diffs)} | روابط استشهاد: {len(quote_misses)}")
    if errors:
        print("أخطاء:", *errors, sep="\n- ")
        sys.exit(1)
    print("التحقق: سليم")


if __name__ == "__main__":
    main()
