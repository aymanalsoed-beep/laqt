#!/usr/bin/env python3
"""يبني «لوحة الإدخال والنشر» في <الموقع>/admin/ بعد بناء الموقع.

اللوحة صفحة ثابتة تعمل في المتصفح: تقرأ المواد من admin/entries.json (يكتبه هذا
السكربت من data/entries/ ومن القاعدة)، وتحفظ ما يُضاف أو يُعدَّل ملفًّا في
data/entries/ داخل المستودع عبر واجهة GitHub بمفتاح دخول صاحب الموقع. وكل حفظ
يشغّل نشر الموقع من جديد (.github/workflows/pages.yml).

التشغيل:  python3 scripts/build_admin.py --out _site
           python3 scripts/build_admin.py --out DIR --demo   (نسخة تجريبية لا تتصل بـ GitHub)
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "laqt.db"
SRC = ROOT / "admin-src"
ENTRIES = ROOT / "data" / "entries"
CONFIG = json.loads((ROOT / "scripts" / "site_config.json").read_text(encoding="utf-8"))


def repo_name() -> str:
    """owner/repo: من بيئة GitHub Actions، وإلا من عنوان origin."""
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    try:
        url = subprocess.check_output(["git", "-C", str(ROOT), "remote", "get-url", "origin"], text=True).strip()
        m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return CONFIG.get("repo", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "_site"))
    ap.add_argument("--demo", action="store_true", help="نسخة تجريبية تحفظ في المتصفح فقط")
    args = ap.parse_args()
    site = Path(args.out)
    out = site if args.demo else site / "admin"
    if out.exists() and not args.demo:
        shutil.rmtree(out)
    shutil.copytree(SRC, out, dirs_exist_ok=True)
    (out / "fonts").mkdir(exist_ok=True)
    shutil.copy(ROOT / "site-src" / "assets" / "fonts" / "hafs.18.woff2", out / "fonts" / "hafs.18.woff2")

    con = sqlite3.connect(DB)
    kinds = [{"id": k, "name": n} for k, n in con.execute("SELECT id, name_ar FROM content_kinds ORDER BY sort_order")]
    # الروابط كما بُنيت في القاعدة، ومنها الآيات المستشهد بها التي يكتشفها البناء تلقائيًا
    links = {}
    for eid, g1, g2, placement, role in con.execute(
            "SELECT entry_id, first_ayah_id, last_ayah_id, placement, role FROM entry_ayat"):
        links.setdefault(eid, []).append([g1, g2, role])
    con.close()

    entries = []
    for f in sorted(ENTRIES.glob("*.json")):
        e = json.loads(f.read_text(encoding="utf-8"))
        e["_links"] = links.get(e.get("id"), [])
        entries.append(e)

    if args.demo:
        shutil.copy(site / "assets" / "search-index.json", out / "search-index.json") \
            if (site / "assets" / "search-index.json").exists() else None
    cfg = {
        "repo": repo_name(),
        "branch": CONFIG.get("publish_branch", "main"),
        "entries_dir": "data/entries",
        "kinds": kinds,
        "hidden_kinds": CONFIG.get("hidden_kinds", []),
        "public_statuses": CONFIG.get("public_statuses", []),
        "index_url": "search-index.json" if args.demo else "../assets/search-index.json",
        "site_url": "" if args.demo else "../",
        "demo": args.demo,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (out / "config.js").write_text(
        "window.LAQT_ADMIN = " + json.dumps(cfg, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    (out / "entries.json").write_text(
        json.dumps({"built_at": cfg["built_at"], "entries": entries}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    print(f"اللوحة: {out}  ({len(entries)} مادة، المستودع {cfg['repo'] or '؟'})")


if __name__ == "__main__":
    main()
