#!/usr/bin/env python3
"""يستورد «الوقف والابتداء» من جمهرة العلوم (jamharah.net) إلى data/sources/jamharah/waqf/<sss>.json.

قسم «الوقف والابتداء» في جمهرة علوم القرآن (forumdisplay.php?f=430) فيه موضوع لكل سورة،
جمعه الشيخ عبد العزيز بن داخل المطيري. كل مشاركة فيه على آية أو مقطع: «قوله تعالى: {...}»،
ثم نقول أئمة الوقف بنصها مع موضعها من كتبهم:
  ابن الأنباري: إيضاح الوقف والابتداء | الداني: المكتفى | السجاوندي: علل الوقوف | الأشموني: منار الهدى
وأول المشاركات «مسائل عامة في وقوف السورة».

التشغيل:
  python3 scripts/import_jamharah.py            # يجلب الصفحات (نسخة الأرشيف) ويحوّلها
  python3 scripts/import_jamharah.py --cache DIR  # يحفظ الصفحات المجلوبة في DIR ويعيد استعمالها
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sources" / "jamharah" / "waqf"
FORUM = "https://jamharah.net/forumdisplay.php?f=430&order=asc&page={}"
ARCHIVE = "https://jamharah.net/archive/index.php/t-{}.html"
THREAD = "https://jamharah.net/showthread.php?t={}"

# الأئمة الأربعة: مفتاح، وما يُعرف به في سطر «قال ...»، والكتاب
AUTHORS = {
    "anbari": ("الأنباري", "ابن الأنباري", "إيضاح الوقف والابتداء"),
    "dani": ("الداني", "أبو عمرو الداني", "المكتفى في الوقف والابتدا"),
    "sajawandi": ("السجاوندي", "السجاوندي", "علل الوقوف"),
    "ashmuni": ("الأشموني", "الأشموني", "منار الهدى في بيان الوقف والابتدا"),
}
BOOK_KEYS = {"إيضاح الوقف والابتداء": "anbari", "المكتفى": "dani", "علل الوقوف": "sajawandi", "منار الهدى": "ashmuni"}

DIAC = re.compile("[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def bare(s):
    s = DIAC.sub("", s)
    s = re.sub("[إأآٱ]", "ا", s)
    return re.sub(r"\s+", " ", s).strip()


def name_key(s):
    """مفتاح اسم السورة للمطابقة: «الشورى» = «الشوري»، «سبأ» = «سبإ»، و«محمد (صلى الله عليه وسلم)» = «محمد»."""
    return bare(re.sub(r"\(.*?\)", "", s)).replace("ى", "ي").replace("ٱ", "ا")


def fetch(url, cache: Path | None, name: str) -> str:
    if cache and (cache / name).exists():
        raw = (cache / name).read_bytes()
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "laqt-importer"})
        for attempt in range(4):
            try:
                raw = urllib.request.urlopen(req, timeout=60).read()
                break
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        if cache:
            cache.mkdir(parents=True, exist_ok=True)
            (cache / name).write_bytes(raw)
        time.sleep(0.3)
    return raw.decode("windows-1256", "replace")


def text_of(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    t = t.replace("\r", "").replace(" ", " ")
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in t.split("\n")]
    return "\n".join(lines)


def surah_threads(cache, surah_names):
    """{رقم السورة: رقم الموضوع} من فهرس القسم."""
    found = {}
    for p in (1, 2, 3):
        s = fetch(FORUM.format(p), cache, f"forum-{p}.html")
        for tid, title in re.findall(r'id="thread_title_(\d+)"[^>]*>([^<]+)<', s):
            m = re.match(r"الوقف والابتداء في سورة (.+)$", bare(html.unescape(title)))
            if m:
                name = m.group(1).strip()
                sid = surah_names.get(name_key(name))
                if not sid:
                    sys.exit(f"اسم سورة غير معروف: {name}")
                found[sid] = int(tid)
    return found


QUOTE_START = re.compile(r"^قال.{0,160}?\(ت\s*:\s*[^)]*\)\s*:?\s*")   # يُطابق على النص المجرد من التشكيل
DEATH = re.compile(r"^.{0,220}?\(ت\s*:\s*[^)]*\)\s*:?\s*", re.S)


def is_quote_start(line):
    return bool(QUOTE_START.match(bare(line)))
CITE = re.compile(r"\[\s*([^\]\d:]{3,40}?)\s*:\s*([^\]]{1,40}?)\s*\]")


def author_key(line):
    b = bare(line[:200])
    for k, (needle, *_rest) in AUTHORS.items():
        if bare(needle) in b:
            return k
    return None


def parse_quote(key, lines):
    raw = "\n".join(lines).strip()
    label = ""
    m = re.match(r"^(فائدة|تنبيه)\s*:?\s*\n", raw)
    if m:
        label, raw = m.group(1) + ": ", raw[m.end():]
    raw = DEATH.sub("", raw, count=1)
    refs = []
    book_key = None

    def cite(m):
        nonlocal book_key
        bk = BOOK_KEYS.get(bare(m.group(1)).replace("  ", " "))
        if bk is None:
            for name, k in BOOK_KEYS.items():
                if bare(name) == bare(m.group(1)):
                    bk = k
        if bk is None:
            return m.group(0)        # إحالة داخل النص، مثل [البقرة: 2]
        book_key = bk
        refs.append(m.group(2).translate(AR_DIGITS).replace(" ", ""))
        return " "

    body = CITE.sub(cite, raw)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r" *\n *", "\n", body).strip()
    # النقل محصور بين قوسين: «(...)»
    if body.startswith("(") and body.rstrip(" .").endswith(")"):
        body = body[1:].rstrip(" .")[:-1].strip()
    elif body.startswith("("):
        body = body[1:].strip()
    body = re.sub(r"\)\s*\.?\s*$", "", body) if body.count(")") > body.count("(") else body
    # الآيات بين { } تُعرض بين ﴿ ﴾
    body = re.sub(r"\{\s*([^{}]+?)\s*\}", r"﴿\1﴾", body)
    # المنتدى يفصل كل سطر بسطر فارغ؛ يكفي سطر واحد
    body = re.sub(r"\n\s*\n+", "\n", body)
    ref = refs[0] if len(refs) == 1 else (f"{refs[0]}–{refs[-1]}" if refs else "")
    return {"author": key if key else book_key, "ref": ref, "text": label + body}


def parse_post(text):
    lines = [l for l in text.split("\n")]
    lines = [l for l in lines if "http://" not in l and "https://" not in l]
    while lines and not lines[0]:
        lines.pop(0)
    if not lines:
        return None
    head = lines[0]
    post = {"heading": head}
    m = re.match(r"^قول[ه]?\s*تعال[ىي]\s*:\s*(.*)$", head)
    if m:
        nums = [int(n) for n in re.findall(r"\((\d+)\)", m.group(1).translate(AR_DIGITS))]
        post["type"] = "ayat"
        post["ayat"] = [min(nums), max(nums)] if nums else None
        post["heading"] = re.sub(r"\{\s*([^{}]+?)\s*\}", r"﴿\1﴾", m.group(1)).strip()
    elif head.startswith("•"):
        return None                     # فهرس الموضوع
    else:
        post["type"] = "general"        # «مسائل عامة»، «الوقف بعد الاستعاذة»
    quotes, cur, cur_key, pre = [], None, None, []
    for l in lines[1:]:
        if is_quote_start(l):
            if cur is not None:
                quotes.append(parse_quote(cur_key, cur))
            cur, cur_key = pre + [l], author_key(l)
            pre = []
        elif re.match(r"^(فائدة|تنبيه)\s*:?$", l):
            # «فائدة:» تسبق النقل الذي بعدها
            if cur is not None:
                quotes.append(parse_quote(cur_key, cur))
                cur = None
            pre = [l]
        elif cur is not None:
            cur.append(l)
        elif l:
            pre.append(l)
    if cur is not None:
        quotes.append(parse_quote(cur_key, cur))
    post["quotes"] = [q for q in quotes if q["text"]]
    return post


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path)
    args = ap.parse_args()

    meta = json.loads((ROOT / "data/sources/kfgqpc/hafsData_v18.json").read_text(encoding="utf-8"))
    names, counts = {}, {}
    for r in meta:
        names[name_key(r["sora_name_ar"])] = r["sora"]
        counts[r["sora"]] = max(counts.get(r["sora"], 0), r["aya_no"])
    threads = surah_threads(args.cache, names)
    if len(threads) != 114:
        sys.exit(f"وُجد {len(threads)} موضوعًا للسور وليس 114: {sorted(set(range(1, 115)) - set(threads))}")

    OUT.mkdir(parents=True, exist_ok=True)
    problems, total = [], 0
    for sid in range(1, 115):
        tid = threads[sid]
        s = fetch(ARCHIVE.format(tid), args.cache, f"t-{tid}.html")
        posts = []
        for frag in re.findall(r'<div class="posttext">(.*?)</div></div>', s, re.S):
            p = parse_post(text_of(frag))
            if not p or not p["quotes"]:
                continue
            if p["type"] == "ayat":
                rng = p["ayat"]
                if not rng or rng[1] > counts[sid]:
                    problems.append(f"سورة {sid}: مقطع بلا أرقام آيات صحيحة: {p['heading'][:60]}")
                    continue
            for q in p["quotes"]:
                if not q["author"]:
                    problems.append(f"سورة {sid} «{p['heading'][:40]}»: نقل بلا قائل: {q['text'][:50]}")
            posts.append(p)
            total += len(p["quotes"])
        doc = {"surah": sid, "thread": tid, "url": THREAD.format(tid),
               "source": "جمهرة العلوم: الوقف والابتداء", "posts": posts}
        (OUT / f"{sid:03d}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{sid:3d} t={tid}: {len(posts)} مشاركة", file=sys.stderr)
    print(f"النقول: {total}")
    if problems:
        print("ملاحظات:", *problems, sep="\n- ")


if __name__ == "__main__":
    main()
