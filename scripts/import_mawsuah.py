#!/usr/bin/env python3
"""يحوّل صفحات «موسوعة التفسير المأثور» (تراث، الكتاب 639) المحفوظة في
data/sources/mawsuah/raw/<page_id>.json إلى ملف منظم لكل سورة:
data/sources/mawsuah/<sss>.json

البنية الناتجة على ترتيب الموسوعة نفسه:
  intro    : أقسام مقدمة السورة (نزولها، أسماؤها، عدد آياتها...)
  segments : أجزاء الآيات كما قسمتها الموسوعة، ولكل جزء أقسامه (قراءات، نزول،
             تفسير الآية، آثار متعلقة...)، ولكل قسم آثاره.
  notes    : حاشية التعليقات (كلام ابن جرير وابن عطية وابن تيمية وابن القيم وابن كثير)
             بأرقامها في الموسوعة.
كل أثر: رقمه، ونصه كما هو، وحواشيه (التخريج والغريب)، وإحالته إلى الدر المنثور
(«ز» لزوائد الموسوعة)، وأرقام تعليقاته، وصفحة الموسوعة.

التشغيل:  python3 scripts/import_mawsuah.py 1
"""
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data/sources/mawsuah/raw"
OUT = ROOT / "data/sources/mawsuah"

# صفحات كل سورة في تراث (الكتاب 639)
SURAH_PAGES = {1: range(574, 617)}

AR = "٠١٢٣٤٥٦٧٨٩"
DIG = f"[{AR}]+"
SEP = "\n_________\n"
TAG = re.compile(r"<[^>]+>")
REF_END = re.compile(rf"\s*\(?(ز|{DIG}\s*/\s*{DIG})\)\.?\s*$")
ATHAR = re.compile(rf"^({DIG}) - (.*)$")
FN = re.compile(rf"\(\^({DIG})\)")
NOTE = re.compile(rf"\s*\[({DIG})\]")
AYA = re.compile(r'<span id="aya-(\d+)">')
TITLE3 = re.compile(r'data-level="3"')


def num(s: str) -> int:
    return int(s.translate(str.maketrans(AR, "0123456789")))


def clean(s: str) -> str:
    s = html.unescape(TAG.sub("", s))
    return re.sub(r"[ \t]+", " ", s).strip()


def split_page(text: str):
    """متن الصفحة، والتعليقات [n]، والحواشي (^n)."""
    parts = text.split(SEP)
    body, notes, fns = parts[0], {}, {}
    for part in parts[1:]:
        cur = None
        for line in part.split("\n"):
            m = re.match(rf"^\[({DIG})\]\s*(.*)$", line)
            f = re.match(rf"^\(\^({DIG})\)\s*(.*)$", line)
            if m:
                cur = ("n", num(m.group(1)))
                notes[cur[1]] = m.group(2)
            elif f:
                cur = ("f", num(f.group(1)))
                fns[cur[1]] = f.group(2)
            elif cur and line.strip():
                (notes if cur[0] == "n" else fns)[cur[1]] += "\n" + line
    return body, notes, fns


def section_kind(title: str) -> str:
    t = title.replace("ُّ", "").replace("ّ", "")
    if t.startswith("قراءات"):
        return "qiraat"
    if t.startswith("نزول"):
        return "nuzul"
    if t.startswith("تفسير"):
        return "tafsir"
    if t.startswith("آثار متعلقة"):
        return "related"
    if "نسخ" in t:
        return "naskh"
    if "أحكام" in t:
        return "ahkam"
    return "other"


def build(surah: int):
    notes_all, items = {}, []   # items: ("athar"|"seg"|"sec"|"intro", ...)
    open_athar = None

    for pid in SURAH_PAGES[surah]:
        page = json.loads((RAW / f"{pid}.json").read_text(encoding="utf-8"))
        meta = page["meta"]
        body, notes, fns = split_page(page["text"])
        for n, t in notes.items():
            notes_all[n] = {"n": n, "text": t.strip(), "page": pid,
                            "vol": meta["vol"], "printed_page": meta["page"]}
        # حواشي هذه الصفحة تُربط بالآثار بمفتاح فريد
        body = FN.sub(lambda m: f"⟦{pid}:{num(m.group(1))}⟧", body)
        page_fns = {f"{pid}:{n}": t.strip() for n, t in fns.items()}

        lines = [l for l in body.split("\n") if l.strip()]
        for i, raw in enumerate(lines):
            text = clean(raw)
            # تتمة أثر من الصفحة السابقة أو سطر مقطوع داخل الأثر
            continues = open_athar is not None and (
                (i == 0 and not ATHAR.match(text) and not AYA.search(raw)
                 and not TITLE3.search(raw) and "مقدمة" not in text)
                or re.match(rf"^\(?(\^|ز\)|{DIG}\s*/)", text) or text.startswith("⟦"))
            if continues:
                open_athar["text"] += " " + text
                open_athar["fns"].update(page_fns)
                if REF_END.search(open_athar["text"]) or open_athar["text"].endswith("="):
                    open_athar = None
                continue
            m = ATHAR.match(text)
            if m:
                a = {"n": num(m.group(1)), "text": m.group(2), "page": pid,
                     "vol": meta["vol"], "printed_page": meta["page"], "fns": dict(page_fns)}
                items.append(("athar", a))
                open_athar = None if (REF_END.search(a["text"]) or a["text"].endswith("=")) else a
                continue
            open_athar = None
            aya = AYA.search(raw)
            if aya:
                label = re.sub(r"\s*\([٠-٩]+\)\s*", "", text).strip("﴿﴾ ")
                items.append(("seg", int(aya.group(1)), label))
            elif "مقدمة السورة" in text:
                items.append(("intro",))
            elif text in ("تفسير السورة",) or text.startswith("تفسير سورة"):
                continue
            elif len(text) < 60:
                items.append(("sec", text.rstrip(":：").strip()))
            else:
                raise SystemExit(f"سطر غير مصنف في الصفحة {pid}: {text[:80]}")

    # --- التجميع في أجزاء وأقسام ---
    intro, segments = [], []
    cur_list, cur_sec = None, None

    def new_sec(title, target):
        sec = {"title": title, "kind": section_kind(title), "athar": []}
        target.append(sec)
        return sec

    for it in items:
        if it[0] == "intro":
            cur_list = intro
            cur_sec = None
        elif it[0] == "seg":
            seg = {"ayah": it[1], "label": it[2], "sections": []}
            segments.append(seg)
            cur_list, cur_sec = seg["sections"], None
        elif it[0] == "sec":
            cur_sec = new_sec(it[1], cur_list)
        else:
            a = it[1]
            if cur_sec is None:   # آثار تحت الجزء مباشرة: تفسير الآية
                cur_sec = new_sec("تفسير الآية", cur_list)
            cur_sec["athar"].append(finish(a))
    return {"surah": surah, "source": {
                "title": "موسوعة التفسير المأثور",
                "by": "مركز الدراسات والمعلومات القرآنية بمعهد الإمام الشاطبي؛ إشراف أ.د. مساعد الطيار ود. نوح الشهري",
                "edition": "دار ابن حزم، ط1، 1439هـ/2017م",
                "turath_book": 639},
            "intro": intro, "segments": segments,
            "notes": [notes_all[k] for k in sorted(notes_all)]}


def finish(a):
    t = a["text"].strip()
    linked = t.endswith("=")
    if linked:
        t = t[:-1].strip()
    ref = None
    m = REF_END.search(t)
    if m:
        ref = m.group(1).replace(" ", "")
        t = t[:m.start()].rstrip()
    t = t.rstrip(". ")
    note_ids = [num(x) for x in NOTE.findall(t)]
    t = NOTE.sub("", t)
    fns, order = [], {}

    def repl(mm):
        key = mm.group(1)
        if key not in order:
            order[key] = len(order) + 1
            fns.append(a["fns"].get(key, ""))
        return f"[[{order[key]}]]"
    t = re.sub(r"⟦([^⟧]+)⟧", repl, t)
    t = re.sub(r"\s+\.", ".", t).strip()
    out = {"n": a["n"], "text": t, "footnotes": fns, "durr": ref,
           "notes": note_ids, "page": a["page"], "vol": a["vol"], "printed_page": a["printed_page"]}
    if linked:
        out["linked_next"] = True
    return out


def main():
    surah = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    data = build(surah)
    nums = [a["n"] for s in data["intro"] for a in s["athar"]] + \
           [a["n"] for g in data["segments"] for s in g["sections"] for a in s["athar"]]
    missing = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
    if missing or len(nums) != len(set(nums)):
        raise SystemExit(f"ترقيم الآثار غير متصل: ناقص {missing}")
    empty = [a["n"] for g in data["segments"] for s in g["sections"] for a in s["athar"] if any(not f for f in a["footnotes"])]
    if empty:
        raise SystemExit(f"حواشٍ لم تُربط: {empty}")
    p = OUT / f"{surah:03d}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{p.name}: {len(nums)} أثرًا ({min(nums)}–{max(nums)})، "
          f"{len(data['segments'])} جزءًا، {len(data['notes'])} تعليقًا")


if __name__ == "__main__":
    main()
