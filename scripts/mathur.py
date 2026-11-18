"""قسما «التفسير بالمأثور» و«القراءات»: يحوّل بيانات الموسوعة (data/sources/mawsuah)
وملفات القراءات (data/qiraat) إلى مواد في القاعدة، نصها HTML جاهز للعرض (body_format='html').

- التفسير بالمأثور: مادة لكل جزء من أجزاء الآية كما قسمتها الموسوعة، فيها أقسامه بترتيبها
  (النزول، التفسير، النسخ، الأحكام، الآثار المتعلقة) ما عدا القراءات، والآثار بنصها
  وأرقامها وحواشيها، وتعليقات المفسرين تحت الأثر الذي علّقت عليه. ومقدمة السورة مادة
  في موضع «مقدمة السورة».
- القراءات: مادة لكل آية: المتواتر من البدور الزاهرة مع شواهده من الآثار، ثم ما اتفق
  عليه العشرة، ثم الشاذ، ولكلٍّ توجيهه.
"""
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAWSUAH = ROOT / "data/sources/mawsuah"
QIRAAT = ROOT / "data/qiraat"
TURATH = "https://app.turath.io/book/{book}?page={page}"

SOURCES = [
    {"id": 3, "key": "mawsuah", "title": "موسوعة التفسير المأثور",
     "author": "مركز الدراسات والمعلومات القرآنية بمعهد الإمام الشاطبي (إشراف أ.د. مساعد الطيار ود. نوح الشهري)",
     "edition": "دار ابن حزم، ط1، 1439هـ/2017م", "notes": "تراث، الكتاب 639"},
    {"id": 4, "key": "badour", "title": "البدور الزاهرة في القراءات العشر المتواترة",
     "author": "عبد الفتاح القاضي", "edition": None, "notes": "تراث، الكتاب 57"},
    {"id": 5, "key": "muhtasib", "title": "المحتسب في تبيين وجوه شواذ القراءات والإيضاح عنها",
     "author": "ابن جني", "edition": "المجلس الأعلى للشئون الإسلامية", "notes": "تراث، الكتاب 8660"},
]
SRC_ID = {s["key"]: s["id"] for s in SOURCES}
AR = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def ar(n) -> str:
    return str(n).translate(AR)


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def rich(s: str) -> str:
    """نص من المصدر: تهريب، ثم تمييز الآيات ﴿...﴾، وأسطر جديدة."""
    t = esc(s)
    t = re.sub(r"﴿[^﴿﴾\n]{1,400}﴾", lambda m: f'<span class="qv">{m.group(0)}</span>', t)
    return t.replace("\n", "<br>")


def link(book, page, label) -> str:
    return f'<a href="{TURATH.format(book=book, page=page)}" target="_blank" rel="noopener">{esc(label)}</a>'


class Mawsuah:
    def __init__(self, surah):
        self.data = json.loads((MAWSUAH / f"{surah:03d}.json").read_text(encoding="utf-8"))
        self.notes = {n["n"]: n for n in self.data["notes"]}
        self.athar = {}
        for sec in self.data["intro"]:
            for a in sec["athar"]:
                self.athar[a["n"]] = a
        for seg in self.data["segments"]:
            for sec in seg["sections"]:
                for a in sec["athar"]:
                    self.athar[a["n"]] = a
        self.book = self.data["source"]["turath_book"]

    def note_html(self, n) -> str:
        note = self.notes[n]
        return (f'<aside class="m-note"><p class="m-note-h">تعليق [{ar(n)}] '
                f'<small>{link(self.book, note["page"], "الموسوعة " + note["vol"] + "/" + ar(note["printed_page"]))}</small></p>'
                f'<p>{rich(note["text"])}</p></aside>')

    def athar_html(self, a, with_notes=True, anchor=True) -> str:
        text = rich(a["text"])
        text = re.sub(r"\[\[(\d+)\]\]", lambda m: f'<sup class="fn">{ar(m.group(1))}</sup>', text)
        durr = ""
        if a["durr"] == "ز":
            durr = '<span class="m-durr" title="من زوائد الموسوعة على الدر المنثور">(ز)</span>'
        elif a["durr"]:
            durr = f'<span class="m-durr" title="موضعه في الدر المنثور">(الدر {esc(a["durr"])})</span>'
        fns = ""
        if a["footnotes"]:
            items = "".join(f"<li>{rich(f)}</li>" for f in a["footnotes"])
            fns = (f'<details class="m-fns"><summary>التخريج والحواشي</summary><ol>{items}</ol>'
                   f'<p class="m-page">{link(self.book, a["page"], "الموسوعة " + a["vol"] + "/" + ar(a["printed_page"]))}</p></details>')
        joined = " linked" if a.get("linked_next") else ""
        notes = "".join(self.note_html(n) for n in a["notes"]) if with_notes else ""
        aid = f' id="m{a["n"]}"' if anchor else ""
        return (f'<li class="m-athar{joined}"{aid}><span class="m-n">{ar(a["n"])}</span>'
                f'<p class="m-text">{text}{(" " + durr) if durr else ""}</p>{fns}{notes}</li>')

    def section_html(self, sec) -> str:
        items = "".join(self.athar_html(a) for a in sec["athar"])
        title = "" if sec["title"] == "تفسير الآية" else f'<h4 class="m-sec-h">{esc(sec["title"])}</h4>'
        return f'<section class="m-sec">{title}<ol class="m-list">{items}</ol></section>'

    def source_line(self, athar) -> str:
        pages = sorted({(a["vol"], a["printed_page"], a["page"]) for a in athar}, key=lambda x: x[2])
        if not pages:
            return ""
        first, last = pages[0], pages[-1]
        rng = ar(first[1]) if first == last else f"{ar(first[1])}–{ar(last[1])}"
        return (f'<p class="m-src">موسوعة التفسير المأثور {esc(first[0])}/{rng} · '
                f'{link(self.book, first[2], "في تراث")}</p>')


def tafsir_entries(surah):
    """[(ayah|None, placement, title, html, sort)]"""
    m = Mawsuah(surah)
    out = []
    if m.data["intro"]:
        secs = "".join(m.section_html(s) for s in m.data["intro"])
        allA = [a for s in m.data["intro"] for a in s["athar"]]
        out.append((1, "intro", "مقدمة السورة",
                    f'<div class="mathur"><h3 class="m-seg">مقدمة السورة</h3>{secs}{m.source_line(allA)}</div>', 0))
    for i, seg in enumerate(m.data["segments"], 1):
        secs = [s for s in seg["sections"] if s["kind"] != "qiraat"]
        has_q = any(s["kind"] == "qiraat" for s in seg["sections"])
        body = "".join(m.section_html(s) for s in secs)
        if has_q:
            body += '<p class="m-hint">آثار القراءات في هذا الموضع منقولة إلى خانة «القراءات».</p>'
        allA = [a for s in seg["sections"] for a in s["athar"]]
        out.append((seg["ayah"], None, seg["label"],
                    f'<div class="mathur"><h3 class="m-seg"><span class="qv">﴿{esc(seg["label"])}﴾</span></h3>'
                    f'{body}{m.source_line(allA)}</div>', i))
    return out


def qiraat_entries(surah, first_seen):
    """first_seen: asl_key -> (سورة، آية) لأول موضع ذُكر فيه الأصل كاملًا، يُملأ بترتيب المصحف.
    الفرش يُذكر في كل موضع، والأصل يُذكر كاملًا في أول موضع وفي غيره إحالة إليه."""
    p = QIRAAT / f"{surah:03d}.json"
    if not p.exists():
        return []
    q = json.loads(p.read_text(encoding="utf-8"))
    m = Mawsuah(surah)
    src = q["sources"]

    def athar_block(nums, label="نص الآثار"):
        if not nums:
            return ""
        items = "".join(m.athar_html(m.athar[n], with_notes=False, anchor=False) for n in nums)
        return f'<details class="q-athar"><summary>{esc(label)} ({ar(len(nums))})</summary><ol class="m-list">{items}</ol></details>'

    def nums(ns):
        return "، ".join(f'<span class="q-an">{ar(n)}</span>' for n in ns)

    def ref_html(r):
        if r["src"] == "muhtasib":
            return f'<li>{link(src["muhtasib"]["turath_book"], r["page"], "المحتسب " + r["printed"])}</li>'
        return f"<li>{rich(r['text'])}</li>"

    ayat = sorted({x["ayah"] for x in q["mutawatir"]} | {x.get("also_ayah") for x in q["mutawatir"] if x.get("also_ayah")}
                  | {x["ayah"] for x in q["ijma"] + q["shadh"]} | set(q.get("no_farsh", [])))
    def later(it, ay):
        """نص الإحالة إن كان هذا الأصل قد ذُكر كاملًا في موضع سابق، وإلا None."""
        if it.get("type") != "asl":
            return None
        k = it["asl_key"]
        here = (surah, it["ayah"])
        if k not in first_seen:
            first_seen[k] = here
        fs, fa = first_seen[k]
        if (fs, fa) == here:
            return None
        where = f"الآية {ar(fa)}" if fs == surah else f"سورة {ar(fs)}، الآية {ar(fa)}"
        return f"أصلٌ سبق بيانه في {where}، فيُرجع إليه."

    out = []
    for ay in ayat:
        parts = []
        mut = [x for x in q["mutawatir"] if x["ayah"] == ay or x.get("also_ayah") == ay]
        if mut:
            blocks = []
            for it in mut:
                ref = later(it, ay)
                if ref:
                    blocks.append(f'<div class="q-item"><p class="q-word"><span class="qv">﴿{esc(it["word"])}﴾</span> '
                                  f'<span class="q-tag">أصل</span></p><p class="q-ref">{ref}</p></div>')
                    continue
                if it["ayah"] != ay:   # موضع ثانٍ: إحالة إلى الأول
                    blocks.append(f'<div class="q-item"><p class="q-word"><span class="qv">﴿{esc(it["word"])}﴾</span> '
                                  f'<span class="q-tag">{"أصل" if it["type"] == "asl" else "فرش"}</span></p>'
                                  f'<p class="q-ref">سبق بيانه في الآية {ar(it["ayah"])}.</p></div>')
                    continue
                rows = "".join(
                    f'<tr><th><span class="qv">{esc(r["text"])}</span><small>{esc(r["desc"])}</small></th>'
                    f'<td>{esc("، ".join(r["readers"]))}</td>'
                    f'<td>{nums(r["athar"]) or "—"}</td></tr>' for r in it["readings"])
                table = (f'<table class="q-table"><thead><tr><th>القراءة</th><th>القرّاء</th><th>شواهد الآثار</th></tr></thead>'
                         f'<tbody>{rows}</tbody></table>')
                badour = (f'<blockquote class="q-badour"><p>{rich(it["badour"])}</p>'
                          + (f'<p>{rich(it["badour_extra"])}</p>' if it.get("badour_extra") else "")
                          + f'<cite>{link(src["badour"]["turath_book"], it["badour_page"], "البدور الزاهرة")}</cite></blockquote>')
                remarks = "".join(f'<p class="q-remark">{rich(r)}</p>' for r in it.get("remarks", []))
                tawjih = "".join(m.note_html(n) for n in it.get("tawjih_notes", []))
                if tawjih:
                    tawjih = f'<h5 class="q-sub">التوجيه</h5>{tawjih}'
                obj = ""
                if it.get("objection"):
                    o = it["objection"]
                    obj = (f'<h5 class="q-sub">الاعتراض وجوابه</h5><p class="q-remark">{esc(o["summary"])} '
                           f'(الآثار {nums(o["athar"])})</p>' + "".join(m.note_html(n) for n in o["notes"]))
                allA = [n for r in it["readings"] for n in r["athar"]] + it.get("objection", {}).get("athar", [])
                allA = sorted(set(allA))
                blocks.append(f'<div class="q-item"><p class="q-word"><span class="qv">﴿{esc(it["word"])}﴾</span> '
                              f'<span class="q-tag">{"أصل" if it["type"] == "asl" else "فرش"}</span></p>'
                              f'{table}{badour}{remarks}{tawjih}{obj}{athar_block(allA)}</div>')
            parts.append(f'<section class="q-sec"><h4>القراءات المتواترة</h4>{"".join(blocks)}</section>')
        elif ay in q.get("no_farsh", []):
            parts.append('<section class="q-sec"><h4>القراءات المتواترة</h4><p class="q-remark">'
                         'لم يذكر «البدور الزاهرة» خلافًا بين القراء العشرة في فرش هذه الآية.</p></section>')
        ij = [x for x in q["ijma"] if x["ayah"] == ay]
        if ij:
            lis = "".join(f'<li>{rich(x["text"])} وبها جاءت الآثار: {nums(x["athar"])}.{athar_block(x["athar"])}</li>' for x in ij)
            parts.append(f'<section class="q-sec"><h4>ما اتفق عليه العشرة</h4><ul class="q-list">{lis}</ul></section>')
        sh = [x for x in q["shadh"] if x["ayah"] == ay]
        if sh:
            lis = []
            for x in sh:
                ref = later(x, ay)
                if ref:
                    lis.append(f'<li class="q-shadh"><p class="q-word"><span class="qv">({esc(x["text"])})</span> '
                               f'<span class="q-tag">أصل</span></p><p class="q-ref">{ref}</p></li>')
                    continue
                refs = "".join(ref_html(r) for r in x.get("refs", []))
                tw = ""
                if x.get("tawjih"):
                    who = "ابن جني في المحتسب" + (" (بتصرف)" if x["tawjih"].get("paraphrase") else "")
                    tw = f'<p class="q-tawjih"><b>التوجيه:</b> {rich(x["tawjih"]["text"])} <small>({who})</small></p>'
                tw += "".join(m.note_html(n) for n in x.get("tawjih_notes", []))
                an = f' · الآثار: {nums(x["athar"])}' if x["athar"] else ""
                tag = '<span class="q-tag">أصل</span> ' if x.get("type") == "asl" else ""
                lis.append(f'<li class="q-shadh"><p class="q-word"><span class="qv">({esc(x["text"])})</span> {tag}'
                           f'<small>{esc(x["desc"])}</small></p><p class="q-by">{esc(x["by"])}{an}</p>{tw}'
                           f'{("<ul class=" + chr(34) + "q-refs" + chr(34) + ">" + refs + "</ul>") if refs else ""}'
                           f'{athar_block(x["athar"])}</li>')
            parts.append(f'<section class="q-sec"><h4>القراءات الشاذة</h4><ul class="q-list">{"".join(lis)}</ul></section>')
        out.append((ay, f'<div class="qiraat">{"".join(parts)}</div>'))
    return out


def import_mathur(con, gid_of):
    for s in SOURCES:
        con.execute("INSERT INTO sources (id, title, author, edition, notes) VALUES (?,?,?,?,?)",
                    (s["id"], s["title"], s["author"], s["edition"], s["notes"]))
    counts = {"tafsir": 0, "qiraat": 0}
    surahs = sorted(int(p.stem) for p in MAWSUAH.glob("[0-9][0-9][0-9].json"))
    first_seen = {}   # أول موضع لكل أصل، بترتيب المصحف
    for sura in surahs:
        for ay, placement, title, body, sort in tafsir_entries(sura):
            cur = con.execute(
                "INSERT INTO entries (kind, title, body, body_format, source_id, status, origin, sort_order) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("tafsir", title, body, "html", SRC_ID["mawsuah"], "published", "mawsuah", sort))
            g = gid_of[(sura, ay)]
            con.execute("INSERT INTO entry_ayat VALUES (?,?,?,?,?)", (cur.lastrowid, g, g, placement, "primary"))
            counts["tafsir"] += 1
        for ay, body in qiraat_entries(sura, first_seen):
            cur = con.execute(
                "INSERT INTO entries (kind, body, body_format, source_id, status, origin, sort_order) VALUES (?,?,?,?,?,?,?)",
                ("qiraat", body, "html", SRC_ID["badour"], "published", "qiraat", 0))
            g = gid_of[(sura, ay)]
            con.execute("INSERT INTO entry_ayat VALUES (?,?,?,?,?)", (cur.lastrowid, g, g, None, "primary"))
            counts["qiraat"] += 1
    return counts
