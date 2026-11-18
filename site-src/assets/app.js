/* لُقَط: سلوك الواجهة (بلا مكتبات) */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var prefix = document.body.getAttribute("data-prefix") || "";

  function store(k, v) {
    try { if (v === undefined) return localStorage.getItem("laqt:" + k); localStorage.setItem("laqt:" + k, v); } catch (e) { return null; }
  }

  var toastEl = $(".toast"), toastT;
  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastT);
    toastT = setTimeout(function () { toastEl.classList.remove("show"); }, 1800);
  }

  function copy(text, msg) {
    var done = function () { toast(msg || "نُسخ"); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(); });
    } else fallback();
    function fallback() {
      var t = document.createElement("textarea");
      t.value = text; t.style.position = "fixed"; t.style.opacity = "0";
      document.body.appendChild(t); t.select();
      try { document.execCommand("copy"); done(); } catch (e) { toast("تعذّر النسخ"); }
      t.remove();
    }
  }

  function absUrl(rel) { return new URL(prefix + rel, location.href).href; }

  /* ---------- مشاركة الفائدة ---------- */
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest(".share");
    if (b) {
      var url = absUrl(b.getAttribute("data-url"));
      var entry = b.closest(".entry");
      var text = entry ? $(".entry-body", entry).textContent.trim().slice(0, 140) + "…" : "";
      if (navigator.share) navigator.share({ title: "فائدة من لُقَط", text: text, url: url }).catch(function () {});
      else copy(url, "نُسخ رابط الفائدة");
      return;
    }
    var c = ev.target.closest(".copy-text");
    if (c) { copy($(".entry-body", c.closest(".entry")).textContent.trim() + "\n\n" + location.href, "نُسخ نص الفائدة"); }
  });

  /* ---------- الرئيسية: تصفية السور ---------- */
  var grid = $(".surah-grid");
  if (grid) {
    var norm = function (s) {
      return s.replace(/[ً-ٰٟـ]/g, "").replace(/[إأآٱ]/g, "ا").replace(/ى/g, "ي").replace(/ة/g, "ه")
        .replace(/[٠-٩]/g, function (d) { return "٠١٢٣٤٥٦٧٨٩".indexOf(d); }).trim();
    };
    var f = $(".surah-filter"), only = $(".only-content");
    var apply = function () {
      var q = norm(f.value).replace(/^ال/, "");
      $$(".surah-card", grid).forEach(function (li) {
        var name = li.getAttribute("data-name");
        var ok = !q || name.indexOf(q) > -1 || name.replace(/^ال/, "").indexOf(q) === 0 || li.getAttribute("data-n") === q;
        li.hidden = !ok;
      });
      grid.classList.toggle("only", only.checked);
    };
    f.addEventListener("input", apply);
    only.addEventListener("change", apply);
  }

  /* ---------- صفحة السورة ---------- */
  var page = $(".surah-page");
  if (page) initSurah(page);

  function initSurah(page) {
    var tpl = $("#empty-panel");
    var sid = page.getAttribute("data-surah"), lazyCache = {};
    function loadLazy(kind) {
      if (!lazyCache[kind]) lazyCache[kind] = fetch(prefix + "assets/" + kind + "/" + sid + ".json").then(function (r) {
        if (!r.ok) throw new Error(r.status); return r.json();
      }).catch(function (e) { delete lazyCache[kind]; throw e; });
      return lazyCache[kind];
    }
    function escH(t) { return t.replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
    function quranSpans(h) { return h.replace(/﴿[^﴿﴾\n]{1,400}﴾/g, function (m) { return '<span class="qv">' + m + "</span>"; }); }

    // الخانات: فتح وطي
    page.addEventListener("click", function (ev) {
      var slot = ev.target.closest(".slot");
      if (!slot) return;
      var ayah = slot.closest(".ayah");
      var kind = slot.getAttribute("data-kind");
      var wasOpen = slot.classList.contains("active");
      $$(".slot", ayah).forEach(function (s) { s.classList.remove("active"); s.setAttribute("aria-expanded", "false"); });
      $$(".panel", ayah).forEach(function (p) { p.hidden = true; });
      if (wasOpen) return;
      slot.classList.add("active");
      slot.setAttribute("aria-expanded", "true");
      var panel = $('.panel[data-kind="' + kind + '"]', ayah);
      if (!panel && slot.hasAttribute("data-lazy")) {
        panel = document.createElement("div");
        panel.className = "panel panel-loading";
        panel.setAttribute("data-kind", kind);
        panel.innerHTML = "<p>جارٍ التحميل…</p>";
        ayah.appendChild(panel);
        loadLazy(kind).then(function (data) {
          var items = data[ayah.getAttribute("data-n")] || [];
          panel.className = "panel";
          panel.innerHTML = items.map(function (it) {
            return '<article class="entry entry-' + kind + '">' + (it[0] ? '<p class="entry-src">' + escH(it[0]) + "</p>" : "") +
              (it[2] ? '<p class="entry-note">على الآيات ' + escH(it[2]) + ".</p>" : "") +
              '<div class="entry-body">' + quranSpans(escH(it[1])) + "</div></article>";
          }).join("");
        }, function () { panel.innerHTML = "<p>تعذّر التحميل، فأعد المحاولة.</p>"; panel.remove(); toast("تعذّر التحميل"); });
      } else if (!panel) {
        panel = tpl.content.firstElementChild.cloneNode(true);
        panel.setAttribute("data-kind", kind);
        $(".k", panel).textContent = slot.firstChild.textContent.trim();
        ayah.appendChild(panel);
      }
      panel.hidden = false;
    });

    // نسخ رابط الآية
    page.addEventListener("click", function (ev) {
      var b = ev.target.closest(".copy");
      if (!b) return;
      var a = b.closest(".ayah");
      copy(location.href.split("#")[0] + "#a" + a.getAttribute("data-n"), "نُسخ رابط الآية");
    });

    // الانتقال إلى آية
    var jump = $(".jump");
    jump.addEventListener("change", function () {
      var el = document.getElementById("a" + jump.value);
      if (el) { history.replaceState(null, "", "#a" + jump.value); el.scrollIntoView({ behavior: "smooth", block: "start" }); }
    });
    var syncJump = function () {
      var m = /^#a(\d+)$/.exec(location.hash);
      if (m) jump.value = m[1];
    };
    syncJump();
    window.addEventListener("hashchange", syncJump);

    // تتبع الآية الظاهرة لتحديث قائمة الانتقال
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) { if (e.isIntersecting) jump.value = e.target.getAttribute("data-n"); });
      }, { rootMargin: "-140px 0px -65% 0px" });
      $$(".ayah", page).forEach(function (a) { io.observe(a); });
    }

    // حجم الخط
    var size = parseFloat(store("qsize")) || 0;
    var setSize = function () {
      if (size) document.documentElement.style.setProperty("--quran-size", size + "rem");
      else document.documentElement.style.removeProperty("--quran-size");
    };
    setSize();
    var cur = function () { return size || parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--quran-size")) || 1.9; };
    $(".font-up").addEventListener("click", function () { size = Math.min(3.4, cur() + 0.15); setSize(); store("qsize", size); });
    $(".font-down").addEventListener("click", function () { size = Math.max(1.2, cur() - 0.15); setSize(); store("qsize", size); });

    // إخفاء الخانات الفارغة
    var he = $(".hide-empty");
    he.checked = store("hideEmpty") === "1";
    document.body.classList.toggle("hide-empty", he.checked);
    he.addEventListener("change", function () {
      document.body.classList.toggle("hide-empty", he.checked);
      store("hideEmpty", he.checked ? "1" : "0");
    });

    // الاستماع
    var tplUrl = page.getAttribute("data-audio");
    var audio = new Audio();
    audio.preload = "none";
    var current = null, continuous = false;
    var playAll = $(".play-all");

    function urlFor(n) { return tplUrl.replace("{aaa}", ("00" + n).slice(-3)); }
    function setState(ayah, on) {
      if (!ayah) return;
      ayah.classList.toggle("playing", on);
      $(".play", ayah).classList.toggle("is-playing", on);
    }
    function play(ayah) {
      setState(current, false);
      current = ayah;
      audio.src = urlFor(ayah.getAttribute("data-n"));
      setState(ayah, true);
      audio.play().catch(function () { setState(ayah, false); toast("تعذّر تشغيل التلاوة"); stopAll(); });
      if (continuous) ayah.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    function stop() { audio.pause(); setState(current, false); }
    function stopAll() { continuous = false; playAll.setAttribute("aria-pressed", "false"); playAll.classList.remove("is-playing"); }

    page.addEventListener("click", function (ev) {
      var b = ev.target.closest(".play");
      if (!b) return;
      var ayah = b.closest(".ayah");
      if (current === ayah && !audio.paused) { stop(); stopAll(); return; }
      play(ayah);
    });
    audio.addEventListener("ended", function () {
      setState(current, false);
      if (continuous && current) {
        var next = current.nextElementSibling;
        while (next && !next.classList.contains("ayah")) next = next.nextElementSibling;
        if (next) { play(next); return; }
      }
      stopAll();
    });
    playAll.addEventListener("click", function () {
      if (continuous) { stop(); stopAll(); return; }
      continuous = true;
      playAll.setAttribute("aria-pressed", "true");
      playAll.classList.add("is-playing");
      var m = /^#a(\d+)$/.exec(location.hash);
      var start = (current && !audio.paused) ? current : (document.getElementById("a" + jump.value) || $(".ayah", page));
      play(start);
    });
  }

  /* ---------- البحث ---------- */
  var qEl = $("#q");
  if (qEl && $("#results")) initSearch(qEl, $("#results"));

  function initSearch(qEl, out) {
    var idx = null, loading = null;
    var DIAC = /[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u08F0-\u08F3\u0640]/g;
    var DIAC1 = /[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u08F0-\u08F3\u0640]/;
    function plain(s) {
      return s.normalize("NFC").replace(DIAC, "").replace(/[إأآٱا]/g, "ا").replace(/ى/g, "ي").replace(/ة/g, "ه")
        .replace(/ؤ/g, "و").replace(/ئ/g, "ي").replace(/ء/g, "")
        .replace(/[٠-٩]/g, function (d) { return "٠١٢٣٤٥٦٧٨٩".indexOf(d); })
        .replace(/[^ء-ي0-9 ]/g, " ").replace(/\s+/g, " ").trim();
    }
    function ar(n) { return String(n).replace(/\d/g, function (d) { return "٠١٢٣٤٥٦٧٨٩"[d]; }); }
    function esc(s) { return s.replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
    function load() {
      if (!loading) loading = fetch(prefix + "assets/search-index.json").then(function (r) { return r.json(); }).then(function (d) {
        d.a.forEach(function (a) { a.push(plain(a[2])); });
        d.f.forEach(function (f) { f[2] = plain(f[2]); });
        idx = d;
      });
      return loading;
    }
    function surahOf(id) { return idx.s[id - 1]; }

    // تجريد مع خريطة المواضع، ليُبرز موضع الكلمة في النص الأصلي بدقة
    function plainMap(text) {
      var out = "", map = [];
      for (var i = 0; i < text.length; i++) {
        var ch = text[i];
        if (DIAC1.test(ch) || ch === "ء") continue;
        var c = plain(ch) || " ";
        if (c === " " && (out === "" || out[out.length - 1] === " ")) continue;
        out += c; map.push(i);
      }
      return { p: out, map: map };
    }
    function locate(text, q) {
      var pm = plainMap(text), i = pm.p.indexOf(q);
      if (i < 0) return null;
      return [pm.map[i], pm.map[i + q.length - 1] + 1];
    }
    function highlight(text, q) {
      var r = locate(text, q);
      if (!r) return esc(text);
      return esc(text.slice(0, r[0])) + "<mark>" + esc(text.slice(r[0], r[1])) + "</mark>" + esc(text.slice(r[1]));
    }
    function snippetAround(text, q) {
      var r = locate(text, q);
      if (!r) return esc(text.slice(0, 180)) + (text.length > 180 ? "…" : "");
      var s = Math.max(0, r[0] - 70), e = Math.min(text.length, r[1] + 110);
      return (s ? "…" : "") + esc(text.slice(s, r[0])) + "<mark>" + esc(text.slice(r[0], r[1])) + "</mark>" + esc(text.slice(r[1], e)) + (e < text.length ? "…" : "");
    }

    function run() {
      var raw = qEl.value.trim();
      var url = new URL(location.href);
      if (raw) url.searchParams.set("q", raw); else url.searchParams.delete("q");
      history.replaceState(null, "", url);
      if (!raw) { out.innerHTML = ""; return; }
      load().then(function () { render(raw); });
    }

    function render(raw) {
      var q = plain(raw), html = "";
      // آية بعينها: «البقرة ٢٥٥» أو «2:255»
      var m = /^(.+?)\s*[: ]\s*(\d+)$/.exec(q), direct = null;
      if (m) {
        var name = m[1].trim(), n = +m[2], sur = null;
        if (/^\d+$/.test(name)) sur = idx.s[+name - 1];
        else sur = idx.s.filter(function (s) { return s[2] === name || s[2] === "ال" + name || s[2].replace(/^ال/, "") === name; })[0];
        if (sur && n >= 1 && n <= sur[3]) direct = { s: sur, n: n };
      }
      if (direct) {
        var a = idx.a.filter(function (x) { return x[0] === direct.s[0] && x[1] === direct.n; })[0];
        html += '<section class="res-group"><h2>الآية</h2><a class="res" href="surah/' + direct.s[0] + ".html#a" + direct.n + '"><span class="res-ref">' +
          esc(direct.s[1]) + " " + ar(direct.n) + '</span><p class="quran">' + esc(a[3]) + "</p></a></section>";
      }
      var sMatches = idx.s.filter(function (s) { return q.length > 1 && (s[2] === q || s[2].replace(/^ال/, "") === q); });
      if (sMatches.length && !direct) {
        html += '<section class="res-group"><h2>السور</h2>' + sMatches.map(function (s) {
          return '<a class="res" href="surah/' + s[0] + '.html"><span class="res-ref">سورة ' + ar(s[0]) + '</span><div class="res-text">سورة ' + esc(s[1]) + "</div></a>";
        }).join("") + "</section>";
      }
      if (q.length >= 2 && !direct) {
        var fs = idx.f.filter(function (f) { return f[2].indexOf(q) > -1; });
        if (fs.length) {
          html += '<section class="res-group"><h2>الفوائد <small>(' + ar(fs.length) + ")</small></h2>" + fs.slice(0, 30).map(function (f) {
            return '<a class="res" href="faida/' + f[0] + '.html"><span class="res-ref">' + esc(f[1]) + '</span><div class="res-text">' + snippetAround(f[3], q) + "</div></a>";
          }).join("") + (fs.length > 30 ? '<p class="res-more">وغيرها ' + ar(fs.length - 30) + "</p>" : "") + "</section>";
        }
        var as = idx.a.filter(function (a) { return a[4].indexOf(q) > -1; });
        if (as.length) {
          html += '<section class="res-group"><h2>الآيات <small>(' + ar(as.length) + ")</small></h2>" + as.slice(0, 60).map(function (a) {
            var s = surahOf(a[0]);
            return '<a class="res" href="surah/' + a[0] + ".html#a" + a[1] + '"><span class="res-ref">' + esc(s[1]) + " " + ar(a[1]) +
              '</span><p class="quran">' + esc(a[3]) + '</p><div class="res-text">' + highlight(a[2], q) + "</div></a>";
          }).join("") + (as.length > 60 ? '<p class="res-more">عرضنا أول ٦٠ نتيجة من ' + ar(as.length) + "، فخصّص البحث بكلمة أخرى.</p>" : "") + "</section>";
        }
      }
      out.innerHTML = html || (q.length < 2 ? "" : '<p class="search-hint">لا نتائج لـ«' + esc(raw) + "».</p>");
    }

    var t;
    qEl.addEventListener("input", function () { clearTimeout(t); t = setTimeout(run, 220); });
    var initial = new URL(location.href).searchParams.get("q");
    if (initial) { qEl.value = initial; run(); }
  }
})();
