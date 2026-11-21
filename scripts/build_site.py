#!/usr/bin/env python3
"""يولّد موقع «لقط» الثابت من قاعدة البيانات db/laqt.db إلى المجلد _site/.

التشغيل:  python3 scripts/build_site.py [--out _site]

- صفحة لكل سورة فيها كل آياتها، وتحت كل آية الخانات الخمس (القراءات، المعنى
  الإجمالي، التفسير بالمأثور، الإعراب، الفوائد) بترتيب جدول content_kinds.
  الخانة التي ليس فيها مادة تظهر هادئة وتنتظر ما يُنشر فيها.
- صفحة مستقلة لكل فائدة (رابط للنشر)، وفهرس للفوائد، وصفحة بحث.
- الإعدادات في scripts/site_config.json (الحالات المنشورة، الخانات المخفية، القارئ).
- كل الروابط نسبية، فيعمل الموقع من أي مسار (GitHub Pages أو نطاق خاص أو ملف محلي).
"""
import argparse
import html
import json
import re
import shutil
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "laqt.db"
SRC = ROOT / "site-src"
CONFIG = json.loads((ROOT / "scripts" / "site_config.json").read_text(encoding="utf-8"))

AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
EN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
AR_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟۖ-ࣰۭ-ࣳـ]")


def ar(n) -> str:
    return str(n).translate(AR_DIGITS)


def count_word(n: int) -> str:
    """العدد مع تمييزه: فائدة واحدة، فائدتان، ٣ فوائد، ١١ فائدة."""
    if n == 1:
        return "فائدة واحدة"
    if n == 2:
        return "فائدتان"
    return f"{ar(n)} {'فوائد' if 3 <= n % 100 <= 10 else 'فائدة'}"


def verse_html(cls: str) -> str:
    """البيت الشعري بشطريه، كما يُكتب الشعر: صدر وعجز متقابلان."""
    sadr, ajz = CONFIG["tagline"]
    return (f'<p class="verse {cls}"><span class="shatr">{html.escape(sadr)}</span>'
            f'<span class="shatr">{html.escape(ajz)}</span></p>')


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def plain(s: str) -> str:
    """تجريد للبحث: نفس قواعد build_db.py (حذف التشكيل وتوحيد الهمزات)."""
    s = unicodedata.normalize("NFC", s)
    s = AR_DIACRITICS.sub("", s)
    s = re.sub("[إأآٱا]", "ا", s)
    s = s.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي").replace("ء", "")
    s = re.sub(r"[^ء-ي0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------------ البيانات

def load(con):
    con.row_factory = sqlite3.Row
    surahs = [dict(r) for r in con.execute("SELECT * FROM surahs ORDER BY id")]
    ayat = [dict(r) for r in con.execute("SELECT * FROM ayat ORDER BY id")]
    kinds = [dict(r) for r in con.execute("SELECT * FROM content_kinds ORDER BY sort_order")]
    statuses = CONFIG["public_statuses"]
    hidden = set(CONFIG["hidden_kinds"])
    q = ",".join("?" * len(statuses))
    entries = {r["id"]: dict(r) for r in con.execute(
        f"""SELECT e.*, s.title AS source_title, s.author AS source_author
            FROM entries e LEFT JOIN sources s ON s.id = e.source_id
            WHERE e.status IN ({q}) ORDER BY e.sort_order, e.id""", statuses)
        if r["kind"] not in hidden}
    links = [dict(r) for r in con.execute(
        "SELECT * FROM entry_ayat ORDER BY first_ayah_id, last_ayah_id, entry_id")]
    links = [l for l in links if l["entry_id"] in entries]
    return surahs, ayat, kinds, entries, links


class Site:
    def __init__(self, out: Path):
        self.out = out
        con = sqlite3.connect(DB)
        self.surahs, self.ayat, self.kinds, self.entries, self.links = load(con)
        self.kind_name = {k["id"]: k["name_ar"] for k in self.kinds}
        self.ayah = {a["id"]: a for a in self.ayat}
        self.surah = {s["id"]: s for s in self.surahs}
        self.by_surah = defaultdict(list)
        for a in self.ayat:
            self.by_surah[a["surah_id"]].append(a)

        # مواضع العرض: تحت آية، أو مقدمة السورة، أو آخرها
        self.under = defaultdict(lambda: defaultdict(list))   # ayah_id -> kind -> [(entry, link)]
        self.lazy_kinds = set(CONFIG.get("lazy_kinds", []))
        self.lazy = defaultdict(lambda: defaultdict(list))    # ما يُحمَّل من assets/<kind>/<سورة>.json
        self.intro = defaultdict(list)                         # surah_id -> [(entry, link)]
        self.end = defaultdict(list)
        self.entry_links = defaultdict(list)                   # entry_id -> [link]
        for l in self.links:
            e = self.entries[l["entry_id"]]
            self.entry_links[e["id"]].append(l)
            sid = self.ayah[l["first_ayah_id"]]["surah_id"]
            if l["placement"] == "intro":
                self.intro[sid].append((e, l))
            elif l["placement"] == "surah-end":
                self.end[sid].append((e, l))
            else:
                if e["kind"] in self.lazy_kinds:
                    # المعنى الإجمالي: يظهر تحت كل آية من المقطع، ويُحمَّل عند فتح الخانة
                    for g in range(l["first_ayah_id"], l["last_ayah_id"] + 1):
                        self.lazy[g][e["kind"]].append((e, l))
                else:
                    # المقطع يُعرض تحت آخر آية فيه
                    self.under[l["last_ayah_id"]][e["kind"]].append((e, l))

        # أسماء السور للروابط داخل النصوص: [البقرة: ٦١]
        self.surah_by_name = {}
        for s in self.surahs:
            n = plain(s["name_ar_plain"])
            self.surah_by_name[n] = s["id"]
            if n.startswith("ال"):
                self.surah_by_name[n[2:]] = s["id"]

    # ---------------------------------------------------------- مساعدات

    def ref(self, l, with_surah=True) -> str:
        a, b = self.ayah[l["first_ayah_id"]], self.ayah[l["last_ayah_id"]]
        s = self.surah[a["surah_id"]]["name_ar_plain"]
        n = ar(a["number"]) if a["id"] == b["id"] else f"{ar(a['number'])}–{ar(b['number'])}"
        return f"{s} {n}" if with_surah else n

    def ayah_href(self, ayah_id, prefix="") -> str:
        a = self.ayah[ayah_id]
        return f"{prefix}surah/{a['surah_id']}.html#a{a['number']}"

    def primary_link(self, entry_id):
        ls = self.entry_links[entry_id]
        return next((l for l in ls if l["role"] == "primary"), ls[0] if ls else None)

    def linkify(self, text: str, prefix: str) -> str:
        """يهرّب النص ويحوّل الإحالات مثل [البقرة: ٦١] إلى روابط."""
        out, pos = [], 0
        pat = re.compile(r"\[\s*([^\]\[\d٠-٩:\n]{2,20}?)\s*:?\s*([\d٠-٩]+)(?:\s*[-–]\s*([\d٠-٩]+))?\s*\]")
        for m in pat.finditer(text):
            sid = self.surah_by_name.get(plain(m.group(1)))
            if not sid:
                continue
            n = int(m.group(2).translate(EN_DIGITS))
            if not 1 <= n <= self.surah[sid]["ayah_count"]:
                continue
            out.append(esc(text[pos:m.start()]))
            out.append(f'<a class="xref" href="{prefix}surah/{sid}.html#a{n}">{esc(m.group(0))}</a>')
            pos = m.end()
        out.append(esc(text[pos:]))
        # الآيات المقتبسة بين القوسين المزخرفين تُعرض بخط المصحف
        return re.sub(r"﴿[^﴿﴾\n]{1,400}﴾", lambda m: f'<span class="qv">{m.group(0)}</span>', "".join(out))

    def body_html(self, e, prefix) -> str:
        body = re.sub(r"\n{3,}", "\n\n", e["body"].strip())
        return f'<div class="entry-body">{self.linkify(body, prefix)}</div>'

    def source_html(self, e) -> str:
        parts = [p for p in (e.get("source_author"), e.get("source_title"), e.get("source_ref")) if p]
        return f'<p class="entry-source">المصدر: {esc("، ".join(parts))}</p>' if parts else ""

    # ---------------------------------------------------------- القالب

    def page(self, path: str, title: str, body: str, prefix: str, desc: str = "", body_class="") -> None:
        full_title = f"{title} · {CONFIG['site_title']}" if title else \
            f"{CONFIG['site_title']} · {CONFIG['site_subtitle']}"
        desc = desc or f"{CONFIG['site_subtitle']}: المصحف كاملًا برواية حفص، وتحت كل آية فوائدها وتفسيرها وإعرابها."
        doc = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(desc)}">
<meta property="og:title" content="{esc(full_title)}">
<meta property="og:description" content="{esc(desc)}">
<meta name="theme-color" content="#1F5C4A">
<link rel="icon" href="{prefix}assets/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Aref+Ruqaa:wght@400;700&family=Markazi+Text:wght@400;500;600;700&display=swap">
<link rel="preload" href="{prefix}assets/fonts/hafs.18.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{prefix}assets/style.css">
</head>
<body class="{body_class}" data-prefix="{prefix}">
<a class="skip" href="#main">تخطَّ إلى المحتوى</a>
<header class="site-header">
  <div class="wrap header-row">
    <a class="brand" href="{prefix}index.html" aria-label="لُقَط: الصفحة الرئيسية">
      <span class="logo"><span class="logo-word">لُقَط</span></span>
      <span class="brand-sub">{esc(CONFIG['site_subtitle'])}</span>
    </a>
    <nav class="main-nav" aria-label="التنقل الرئيسي">
      <a href="{prefix}index.html#surahs">السور</a>
      <a href="{prefix}fawaid.html">الفوائد</a>
      <a href="{prefix}search.html" class="nav-search" aria-label="البحث">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <span>بحث</span>
      </a>
    </nav>
  </div>
</header>
<main id="main">
{body}
</main>
<footer class="site-footer">
  <div class="wrap">
    {verse_html("footer-tag")}
    <p>نص المصحف برواية حفص عن عاصم من <a href="https://qurancomplex.gov.sa/techquran/dev/">مجمع الملك فهد لطباعة المصحف الشريف</a> (الإصدار ١٨)، ويُعرض بخطه.
    التلاوة: {esc(CONFIG['audio']['name'])}.</p>
  </div>
</footer>
<div class="toast" role="status" aria-live="polite"></div>
<script src="{prefix}assets/app.js" defer></script>
</body>
</html>
"""
        p = self.out / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(doc, encoding="utf-8")

    # ---------------------------------------------------------- الرئيسية

    def fawaid_count(self, sid) -> int:
        ids = set()
        for a in self.by_surah[sid]:
            ids.update(e["id"] for e, _ in self.under[a["id"]].get("faida", []))
        ids.update(e["id"] for e, _ in self.intro[sid] + self.end[sid] if e["kind"] == "faida")
        return len(ids)

    def build_index(self):
        n_fawaid = sum(1 for e in self.entries.values() if e["kind"] == "faida")
        n_with = sum(1 for a in self.ayat if self.under[a["id"]])
        cards = []
        for s in self.surahs:
            fc = self.fawaid_count(s["id"])
            place = "مكية" if s["revelation_place"] == "makki" else "مدنية"
            badge = f'<span class="badge">{count_word(fc)}</span>' if fc else ""
            cards.append(f"""<li class="surah-card{' has-content' if fc else ''}" data-name="{esc(plain(s['name_ar_plain']))}" data-n="{s['id']}">
  <a href="surah/{s['id']}.html">
    <span class="sc-num">{ar(s['id'])}</span>
    <span class="sc-name">{esc(s['name_ar_plain'])}</span>
    <span class="sc-meta">{place} · {ar(s['ayah_count'])} آية</span>
    {badge}
  </a>
</li>""")
        body = f"""
<section class="hero">
  <div class="wrap">
    <h1 class="hero-logo"><span class="logo logo-xl"><span class="logo-word">لُقَط</span></span></h1>
    <p class="hero-title">{esc(CONFIG['site_subtitle'])}</p>
    {verse_html("hero-tag")}
    <form class="hero-search" action="search.html" role="search">
      <input type="search" name="q" placeholder="ابحث في الآيات والفوائد، أو اكتب: البقرة ٢٥٥" aria-label="البحث">
      <button type="submit">بحث</button>
    </form>
    <dl class="stats">
      <div><dt>سورة</dt><dd>{ar(len(self.surahs))}</dd></div>
      <div><dt>آية برواية حفص</dt><dd>{ar(len(self.ayat))}</dd></div>
      <div><dt>فائدة منتقاة</dt><dd>{ar(n_fawaid)}</dd></div>
      <div><dt>آية فيها فوائد</dt><dd>{ar(n_with)}</dd></div>
    </dl>
  </div>
</section>
<section class="wrap surah-index" id="surahs">
  <div class="section-head">
    <h2>سور القرآن الكريم</h2>
    <div class="index-tools">
      <input type="search" class="surah-filter" placeholder="اسم السورة أو رقمها" aria-label="تصفية السور">
      <label class="chip"><input type="checkbox" class="only-content"> ما فيه فوائد</label>
    </div>
  </div>
  <ol class="surah-grid">
{''.join(cards)}
  </ol>
</section>
"""
        self.page("index.html", "", body, "", body_class="home")

    # ---------------------------------------------------------- السورة

    def src_label(self, e) -> str:
        """عنوان المصدر فوق المادة: الكتاب، ومعه قائله وموضعه إن وُجدا (كما في نقول الوقف)."""
        label = e.get("source_title") or ""
        if label and e["kind"] == "waqf" and e.get("source_author"):
            label = f'{e["source_author"].split(" (")[0]}: {label}'
        if label and e.get("source_ref"):
            ref = re.sub(r"\s*[-–]\s*", " – ", e["source_ref"])   # «١/٤٧٤ – ٤٧٥» تُقرأ صحيحة من اليمين
            label += f' ({ref.translate(AR_DIGITS)})'
        return label

    def entry_card(self, e, l, prefix, here_ayah=None) -> str:
        """بطاقة مادة واحدة (فائدة أو غيرها)."""
        note = ""
        if l["role"] == "cited":
            p = self.primary_link(e["id"])
            if p and p is not l:
                note = (f'<p class="entry-note">تستشهد هذه الفائدة بالآية، وموضعها الأصلي '
                        f'<a href="{self.ayah_href(p["last_ayah_id"], prefix)}">{esc(self.ref(p))}</a>.</p>')
        elif l["first_ayah_id"] != l["last_ayah_id"]:
            note = f'<p class="entry-note">على الآيات {esc(self.ref(l, False))}.</p>'
        tools = ""
        if e["kind"] == "faida":
            tools = (f'<div class="entry-tools"><a class="btn-ghost" href="{prefix}faida/{e["id"]}.html">'
                     f'رابط الفائدة</a><button class="btn-ghost share" data-url="faida/{e["id"]}.html" '
                     f'type="button">مشاركة</button></div>')
        if e["kind"] != "faida" and e.get("source_title"):
            src = f'<p class="entry-src">{esc(self.src_label(e))}</p>'
            return (f'<article class="entry entry-{e["kind"]}">{src}{note}{self.body_html(e, prefix)}</article>')
        return (f'<article class="entry entry-{e["kind"]}" id="f{e["id"]}-{l["first_ayah_id"]}">'
                f'{note}{self.body_html(e, prefix)}{self.source_html(e)}{tools}</article>')

    def ayah_html(self, a, prefix) -> str:
        content = self.under.get(a["id"], {})
        default = CONFIG["default_open_kind"]
        tabs, panels = [], []
        open_kind = default if content.get(default) else None
        lazy = self.lazy.get(a["id"], {})
        for k in self.kinds:
            items = content.get(k["id"], [])
            n = len(items) or len(lazy.get(k["id"], []))
            is_open = k["id"] == open_kind
            cls = "slot" + ("" if n else " empty") + (" active" if is_open else "")
            count = f'<span class="slot-count">{ar(n)}</span>' if n else ""
            lz = " data-lazy" if lazy.get(k["id"]) else ""
            tabs.append(f'<button type="button" class="{cls}" data-kind="{k["id"]}"{lz} '
                        f'aria-expanded="{"true" if is_open else "false"}">{esc(k["name_ar"])}{count}</button>')
            if items:
                cards = "".join(self.entry_card(e, l, prefix) for e, l in items)
                panels.append(f'<div class="panel" data-kind="{k["id"]}"{"" if is_open else " hidden"}>{cards}</div>')
        has = " has-content" if content else ""
        return f"""<article class="ayah{has}" id="a{a['number']}" data-g="{a['id']}" data-n="{a['number']}">
  <div class="ayah-head">
    <a class="ayah-ref" href="#a{a['number']}" title="رابط الآية">{ar(a['number'])}</a>
    <span class="ayah-meta">الصفحة {ar(a['page'])} · الجزء {ar(a['juz'])}{' · سجدة' if a['sajda'] else ''}</span>
    <span class="ayah-actions">
      <button type="button" class="icon-btn play" aria-label="استماع للآية" title="استماع"><svg viewBox="0 0 24 24" aria-hidden="true"><path class="i-play" d="M8 5v14l11-7z"/><path class="i-pause" d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg></button>
      <button type="button" class="icon-btn copy" aria-label="نسخ رابط الآية" title="نسخ الرابط"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg></button>
    </span>
  </div>
  <p class="quran">{esc(a['text_marked'])}</p>
  <div class="slots" role="group" aria-label="خانات الآية">{''.join(tabs)}</div>
  {''.join(panels)}
</article>"""

    def surah_block(self, title, items, prefix, cls) -> str:
        if not items:
            return ""
        cards = "".join(self.entry_card(e, l, prefix) for e, l in items)
        return f'<section class="surah-block {cls}"><h2>{esc(title)}</h2>{cards}</section>'

    def waqf_intro(self, sid, prefix) -> str:
        """«مسائل عامة في وقوف السورة» من جمهرة العلوم: مطوية قبل أول آية."""
        items = [x for x in self.intro[sid] if x[0]["kind"] == "waqf"]
        if not items:
            return ""
        groups = defaultdict(list)
        for e, l in items:
            groups[e["title"] or "مسائل عامة في وقوف السورة"].append((e, l))
        out = []
        for title, its in groups.items():
            cards = "".join(f'<article class="entry entry-waqf"><p class="entry-src">{esc(self.src_label(e))}</p>'
                            f'{self.body_html(e, prefix)}</article>' for e, _ in its)
            out.append(f'<details class="surah-block waqf-intro"><summary>{esc(title)}</summary>{cards}</details>')
        return "".join(out)

    def build_surah(self, s):
        prefix = "../"
        sid = s["id"]
        ayat = self.by_surah[sid]
        place = "مكية" if s["revelation_place"] == "makki" else "مدنية"
        fc = self.fawaid_count(sid)
        parts = []
        for a in ayat:
            if a["id"] == 1 or self.ayah[a["id"] - 1]["juz"] != a["juz"]:
                parts.append(f'<div class="juz-mark"><span>بداية الجزء {ar(a["juz"])}</span></div>')
            parts.append(self.ayah_html(a, prefix))
        for kind in self.lazy_kinds:
            # كل مادة تُكتب مرة واحدة في "e"، و"a" يذكر لكل آية أرقام موادها
            # (المقطع الطويل يظهر تحت كل آياته دون أن يتكرر نصه في الملف)
            data, index = {"e": [], "a": {}}, {}
            for a in ayat:
                items = sorted(self.lazy[a["id"]].get(kind, []), key=lambda x: (x[0]["sort_order"], x[0]["id"]))
                for e, l in items:
                    k = (e["id"], l["first_ayah_id"], l["last_ayah_id"])
                    if k not in index:
                        index[k] = len(data["e"])
                        data["e"].append([self.src_label(e), e["body"].strip(),
                                          "" if l["first_ayah_id"] == l["last_ayah_id"] else self.ref(l, False)])
                    data["a"].setdefault(a["number"], []).append(index[k])
            credit = CONFIG.get("credits", {}).get(kind)
            if credit and data["e"]:
                data["_credit"] = credit
            p = self.out / "assets" / kind / f"{sid}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        basmala = ""
        if sid not in (1, 9):
            basmala = f'<p class="basmala quran">{esc(self.ayah[1]["text_uthmani"])}</p>'
        prev_s = self.surah.get(sid - 1)
        next_s = self.surah.get(sid + 1)
        pager = '<nav class="pager" aria-label="السور المجاورة">'
        pager += (f'<a class="prev" href="{prev_s["id"]}.html"><small>السورة السابقة</small>{esc(prev_s["name_ar_plain"])}</a>'
                  if prev_s else "<span></span>")
        pager += (f'<a class="next" href="{next_s["id"]}.html"><small>السورة التالية</small>{esc(next_s["name_ar_plain"])}</a>'
                  if next_s else "<span></span>")
        pager += "</nav>"
        options = "".join(f'<option value="{a["number"]}">{ar(a["number"])}</option>' for a in ayat)
        audio_tpl = CONFIG["audio"]["url_pattern"].replace("{sss}", f"{sid:03d}")
        fawaid_txt = f" · فيها {count_word(fc)}" if fc else ""
        body = f"""
<div class="surah-page" data-surah="{sid}" data-audio="{esc(audio_tpl)}">
<header class="surah-head">
  <div class="wrap">
    <p class="crumbs"><a href="../index.html#surahs">السور</a> <span aria-hidden="true">/</span> {ar(sid)}</p>
    <h1 class="surah-name">سورة {esc(s['name_ar_plain'])}</h1>
    <p class="surah-meta">{place} · {ar(s['ayah_count'])} آية · الصفحات {ar(s['page_start'])}–{ar(s['page_end'])}{fawaid_txt}</p>
  </div>
</header>
<div class="toolbar" role="toolbar" aria-label="أدوات السورة">
  <div class="wrap toolbar-row">
    <label class="tb-item">الآية
      <select class="jump" aria-label="الانتقال إلى آية">{options}</select>
    </label>
    <button type="button" class="tb-btn play-all" aria-pressed="false">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path class="i-play" d="M8 5v14l11-7z"/><path class="i-pause" d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>
      <span>استماع للسورة</span></button>
    <span class="tb-group" role="group" aria-label="حجم خط الآيات">
      <button type="button" class="tb-btn font-down" aria-label="تصغير الخط">أ−</button>
      <button type="button" class="tb-btn font-up" aria-label="تكبير الخط">أ+</button>
    </span>
    <label class="chip"><input type="checkbox" class="hide-empty"> إخفاء الخانات الفارغة</label>
  </div>
</div>
<div class="wrap surah-body">
  {self.surah_block("فوائد عامة في السورة", [x for x in self.intro[sid] if x[0]["kind"] != "waqf"], prefix, "intro")}
  {self.waqf_intro(sid, prefix)}
  {basmala}
  {''.join(parts)}
  {self.surah_block("فوائد في ختام السورة", self.end[sid], prefix, "outro")}
  {pager}
</div>
</div>
<template id="empty-panel"><div class="panel panel-empty"><p>لم تُنشر مادة في «<span class="k"></span>» لهذه الآية بعد، وستظهر هنا إن شاء الله.</p></div></template>
"""
        self.page(f"surah/{sid}.html", f"سورة {s['name_ar_plain']}", body, prefix,
                  desc=f"سورة {s['name_ar_plain']} كاملة برواية حفص، مع فوائدها وتفسيرها وإعرابها.")

    # ---------------------------------------------------------- الفوائد

    def snippet(self, e, n=170) -> str:
        t = re.sub(r"\s+", " ", e["body"]).strip()
        return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"

    def ordered_fawaid(self):
        def key(e):
            p = self.primary_link(e["id"])
            return (p["first_ayah_id"] if p else 99999, e["id"])
        return sorted((e for e in self.entries.values() if e["kind"] == "faida"), key=key)

    def build_fawaid(self):
        items, cur = [], None
        for e in self.ordered_fawaid():
            p = self.primary_link(e["id"])
            sid = self.ayah[p["first_ayah_id"]]["surah_id"] if p else None
            if sid != cur:
                if cur is not None:
                    items.append("</ol></section>")
                items.append(f'<section class="fl-group"><h2><a href="surah/{sid}.html">سورة {esc(self.surah[sid]["name_ar_plain"])}</a></h2><ol class="faida-list">')
                cur = sid
            where = esc(self.ref(p)) if p else ""
            items.append(f'<li><a href="faida/{e["id"]}.html"><span class="fl-ref">{where}</span>'
                         f'<span class="fl-text">{esc(self.snippet(e))}</span></a></li>')
        if cur is not None:
            items.append("</ol></section>")
        body = f"""<div class="wrap narrow">
<header class="page-head"><h1>الفوائد</h1><p>كل الفوائد المنتقاة مرتبة بحسب مواضعها في المصحف.</p></header>
{''.join(items)}
</div>"""
        self.page("fawaid.html", "الفوائد", body, "")

        for e in self.entries.values():
            if e["kind"] != "faida":
                continue
            self.build_faida(e)

    def build_faida(self, e):
        prefix = "../"
        ls = self.entry_links[e["id"]]
        prim = [l for l in ls if l["role"] == "primary"]
        cited = [l for l in ls if l["role"] == "cited"]
        quotes = []
        for l in prim:
            text = " ".join(esc(self.ayah[g]["text_marked"]) for g in range(l["first_ayah_id"], l["last_ayah_id"] + 1))
            label = {"intro": "مقدمة سورة", "surah-end": "ختام سورة"}.get(l["placement"])
            ref = (f'{label} {esc(self.surah[self.ayah[l["first_ayah_id"]]["surah_id"]]["name_ar_plain"])}'
                   if label else esc(self.ref(l)))
            if label:
                quotes.append(f'<p class="faida-where">{ref.replace(label, f"<a href={chr(34)}{self.ayah_href(l["last_ayah_id"], prefix)}{chr(34)}>{label}", 1)}</a></p>')
            else:
                quotes.append(f'<figure class="faida-ayah"><p class="quran">{text}</p><figcaption><a href="{self.ayah_href(l["last_ayah_id"], prefix)}">{ref}</a></figcaption></figure>')
        cited_html = ""
        if cited:
            lis = "".join(f'<li><a href="{self.ayah_href(l["last_ayah_id"], prefix)}">{esc(self.ref(l))}</a></li>' for l in cited)
            cited_html = f'<div class="faida-cited"><h2>آيات تستشهد بها الفائدة، وتظهر تحتها أيضًا</h2><ul>{lis}</ul></div>'
        p = prim[0] if prim else (ls[0] if ls else None)
        title = f"فائدة في {self.ref(p)}" if p else "فائدة"
        body = f"""<div class="wrap narrow faida-page">
<p class="crumbs"><a href="../fawaid.html">الفوائد</a></p>
{''.join(quotes)}
<article class="entry entry-faida entry-solo">{self.body_html(e, prefix)}{self.source_html(e)}
<div class="entry-tools"><button class="btn share" data-url="faida/{e['id']}.html" type="button">مشاركة الفائدة</button>
<button class="btn-ghost copy-text" type="button">نسخ النص</button></div>
</article>
{cited_html}
</div>"""
        self.page(f"faida/{e['id']}.html", title, body, prefix, desc=self.snippet(e, 150))

    # ---------------------------------------------------------- البحث

    def build_search(self):
        idx = {
            "s": [[s["id"], s["name_ar_plain"], plain(s["name_ar_plain"]), s["ayah_count"]] for s in self.surahs],
            "a": [[a["surah_id"], a["number"], a["text_imlaei"], a["text_uthmani"]] for a in self.ayat],
            "f": [],
        }
        for e in self.ordered_fawaid():
            p = self.primary_link(e["id"])
            idx["f"].append([e["id"], self.ref(p) if p else "", plain(e["body"]),
                             re.sub(r"\s+", " ", e["body"]).strip()])
        (self.out / "assets").mkdir(parents=True, exist_ok=True)
        (self.out / "assets" / "search-index.json").write_text(
            json.dumps(idx, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        body = """<div class="wrap narrow search-page">
<header class="page-head"><h1>البحث</h1></header>
<form class="hero-search" role="search" onsubmit="return false">
  <input type="search" name="q" id="q" placeholder="كلمة من آية أو فائدة، أو: البقرة ٢٥٥" aria-label="البحث" autofocus>
</form>
<p class="search-hint">يُبحث في نص الآيات بالرسم الإملائي دون تشكيل، وفي نصوص الفوائد. ولفتح آية بعينها اكتب اسم السورة ورقم الآية.</p>
<div id="results" aria-live="polite"></div>
</div>"""
        self.page("search.html", "البحث", body, "", body_class="search")

    # ---------------------------------------------------------- التشغيل

    def build(self):
        if self.out.exists():
            shutil.rmtree(self.out)
        shutil.copytree(SRC, self.out)
        self.build_index()
        for s in self.surahs:
            self.build_surah(s)
        self.build_fawaid()
        self.build_search()
        (self.out / ".nojekyll").write_text("")
        n = sum(1 for _ in self.out.rglob("*.html"))
        print(f"الموقع: {self.out}  ({n} صفحة)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "_site"))
    Site(Path(ap.parse_args().out)).build()


if __name__ == "__main__":
    main()
