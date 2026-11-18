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

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB = ROOT / "db" / "laqt.db"
SCHEMA = ROOT / "db" / "schema.sql"
REPORT = ROOT / "data" / "entries_report.md"
STATUSES = ("draft", "needs_review", "ready", "published")
PLACEMENTS = (None, "intro", "surah-end", "after-range")

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
    entries = []
    for f in sorted((DATA / "entries").glob("*.json")):
        e = json.loads(f.read_text(encoding="utf-8"))
        e["_file"] = f.name
        entries.append(e)

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

    # --- المواد المحررة: الفوائد وغيرها، ملف لكل مادة في data/entries/ ---
    # هذه الملفات هي ما تكتبه «لوحة الإدخال» (admin/)، وهي مصدر المواد الوحيد بعد المصحف.
    gid_of = {(r["sora"], r["aya_no"]): i for i, r in enumerate(hafs, 1)}
    kinds = {k for (k,) in con.execute("SELECT id FROM content_kinds")}
    # المراجع: مصدرا المعنى الإجمالي بأرقامهما، ثم ما يُكتب في حقل «المصدر» من 101 فصاعدًا
    for src in TAFSIR_SOURCES:
        con.execute("INSERT INTO sources (id, title, author, edition, notes) VALUES (?,?,?,?,?)",
                    (src["id"], src["title"], src["author"], src["edition"], src["notes"]))
    known_sources = {s["title"]: s["id"] for s in TAFSIR_SOURCES}
    new_sources = {}
    for e in entries:
        title = (e.get("source") or "").strip()
        if title and title not in known_sources and title not in new_sources:
            new_sources[title] = 101 + len(new_sources)
            con.execute("INSERT INTO sources (id, title) VALUES (?,?)", (new_sources[title], title))
    report = ["# تقرير ربط المواد بالآيات", "",
              f"عدد المواد في data/entries: {len(entries)}"
              f" (منها {sum(e['kind'] == 'faida' for e in entries)} فائدة)", ""]
    quote_misses = []
    seen_ids = set()
    for e in entries:
        eid = e.get("id")
        where = f"المادة {eid} ({e.get('_file')})"
        check(isinstance(eid, int) and eid > 0 and eid not in seen_ids, f"{where}: رقم مفقود أو مكرر")
        check(e.get("kind") in kinds, f"{where}: نوع غير معروف {e.get('kind')}")
        check(e.get("status") in STATUSES, f"{where}: حالة غير معروفة {e.get('status')}")
        check(bool((e.get("body") or "").strip()), f"{where}: نص فارغ")
        check(bool(e.get("locations")), f"{where}: لا موضع لها")
        if not (isinstance(eid, int) and eid not in seen_ids and e.get("kind") in kinds
                and e.get("status") in STATUSES):
            continue
        seen_ids.add(eid)
        source_id = None
        if e.get("source"):
            title = e["source"].strip()
            source_id = known_sources.get(title) or new_sources[title]
        con.execute(
            "INSERT INTO entries (id, kind, title, body, source_id, source_ref, status, origin, legacy_id,"
            " legacy_msg, edits, flags, sort_order, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,coalesce(?, datetime('now')),coalesce(?, datetime('now')))",
            (eid, e["kind"], e.get("title") or None, e["body"].strip(), source_id, e.get("source_ref") or None,
             e["status"], e.get("origin"), e.get("legacy_id"), e.get("legacy_msg"),
             json.dumps(e.get("edits") or [], ensure_ascii=False),
             json.dumps(e.get("flags") or [], ensure_ascii=False),
             e.get("sort_order", eid), e.get("created_at"), e.get("updated_at")))
        ref_ayat = []
        for loc in e.get("locations") or []:
            s, a, b = loc.get("surah"), loc.get("from"), loc.get("to", loc.get("from"))
            ok = (s, a) in gid_of and (s, b) in gid_of and b >= a
            check(ok, f"{where}: موضع غير صحيح {s}:{a}-{b}")
            check(loc.get("placement") in PLACEMENTS, f"{where}: مكان عرض غير معروف {loc.get('placement')}")
            if not ok:
                continue
            g1, g2 = gid_of[(s, a)], gid_of[(s, b)]
            role = loc.get("role") or "primary"
            check(role in ("primary", "cited"), f"{where}: دور غير معروف {role}")
            con.execute("INSERT OR IGNORE INTO entry_ayat VALUES (?,?,?,?,?)",
                        (eid, g1, g2, loc.get("placement"), role))
            if role == "primary":
                ref_ayat.extend(range(g1, g2 + 1))
        if e["kind"] != "faida":
            continue
        # تحقق: هل الآيات المقتبسة بين ﴿ ﴾ موجودة في الآيات المربوطة؟
        target = {w.replace("ا", "") for g in ref_ayat for w in plain(hafs[g - 1]["aya_text_emlaey"]).split()}
        for q in re.findall(r"﴿([^﴾]+)﴾", e["body"]):
            words = [w.replace("ا", "") for w in plain(q).split()]
            words = [w for w in words if w]
            if len(words) < 2 or sum(w in target for w in words) / len(words) >= 0.8:
                continue
            def score(g):
                ws = {w.replace("ا", "") for w in plain(hafs[g - 1]["aya_text_emlaey"]).split()}
                return sum(w in ws for w in words) / len(words)
            best = max(range(1, 6237), key=score)
            # فائدة قديمة لم يُعثر على اقتباسها خطأ في البيانات؛ وفي المواد الجديدة يكفي التنبيه
            if e.get("legacy_id"):
                check(score(best) >= 0.8, f"{where}: لم يُعثر على «{q.strip()[:50]}»")
            if score(best) < 0.8:
                quote_misses.append(f"- {where}: لم يُعثر في المصحف على «{q.strip()[:70]}»")
                continue
            target |= {w.replace("ا", "") for w in plain(hafs[best - 1]["aya_text_emlaey"]).split()}
            # الفائدة تظهر أيضًا تحت الآية المستشهد بها
            con.execute("INSERT OR IGNORE INTO entry_ayat VALUES (?,?,?,?,?)", (eid, best, best, None, "cited"))
            quote_misses.append(f"- {where}: «{q.strip()[:70]}» ← {hafs[best-1]['sora_name_ar']} {hafs[best-1]['aya_no']}")

    report += ["## آيات مستشهد بها داخل الفوائد", "",
               "كل آية مقتبسة بين ﴿ ﴾ من غير الآيات الأصلية للفائدة رُبطت بها الفائدة أيضًا (role = cited)، "
               "فتظهر الفائدة تحتها كذلك.", ""] + (quote_misses or ["لا شيء."]) + [""]
    REPORT.write_text("\n".join(report), encoding="utf-8")

    # --- المعنى الإجمالي: التفسير الميسر والمختصر ---
    n_tafsir = import_tafsir(con, gid_of)

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
    print(f"روابط استشهاد: {len(quote_misses)}")
    if errors:
        print("أخطاء:", *errors, sep="\n- ")
        sys.exit(1)
    print("التحقق: سليم")


if __name__ == "__main__":
    main()
