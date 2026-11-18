/* لوحة لُقَط: إضافة المواد وتعديلها ونشرها دون برمجة.
   كل مادة ملف JSON في data/entries/ داخل المستودع؛ والحفظ يكتب الملف عبر واجهة GitHub
   بمفتاح صاحب الموقع، فيُبنى الموقع وينشر من جديد تلقائيًا. */
(function () {
  "use strict";
  var cfg = window.LAQT_ADMIN || {};
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var AR = "٠١٢٣٤٥٦٧٨٩";
  var ar = function (n) { return String(n).replace(/[0-9]/g, function (d) { return AR[d]; }); };
  var en = function (s) { return String(s).replace(/[٠-٩]/g, function (d) { return AR.indexOf(d); }); };
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var norm = function (s) {
    return String(s).replace(/[ؐ-ًؚ-ٰٟۖ-ۭـ]/g, "").replace(/[إأآٱا]/g, "ا").replace(/ى/g, "ي")
      .replace(/ة/g, "ه").replace(/ؤ/g, "و").replace(/ئ/g, "ي").replace(/ء/g, "").replace(/\s+/g, " ").trim();
  };
  function store(k, v) {
    try {
      if (v === undefined) return localStorage.getItem("laqt-admin:" + k);
      if (v === null) localStorage.removeItem("laqt-admin:" + k);
      else localStorage.setItem("laqt-admin:" + k, v);
    } catch (e) { return null; }
  }
  function session(k, v) {
    try {
      if (v === undefined) return sessionStorage.getItem("laqt-admin:" + k);
      if (v === null) sessionStorage.removeItem("laqt-admin:" + k);
      else sessionStorage.setItem("laqt-admin:" + k, v);
    } catch (e) { return null; }
  }
  var toastT;
  function toast(msg, ms) {
    var t = $("#toast");
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toastT);
    toastT = setTimeout(function () { t.classList.remove("show"); }, ms || 3200);
  }

  var KIND = {}; (cfg.kinds || []).forEach(function (k) { KIND[k.id] = k.name; });
  var PUBLIC = cfg.public_statuses || ["ready", "published"];
  var isPublic = function (e) { return PUBLIC.indexOf(e.status) >= 0; };
  var HIDDEN = cfg.hidden_kinds || [];
  var KIND_NOTES = {
    maana: "التفسير الميسر والمختصر يظهران تحت كل آية تلقائيًا، وما تضيفه هنا يظهر معهما.",
    irab: "الإعراب مخفي عن الزوار الآن حتى يُفصل في حقوق المصدر؛ ما تنشره يُحفظ ويظهر متى أُظهرت الخانة.",
  };
  var PLACES = [["", "تحت الآية"], ["intro", "مقدمة السورة"], ["surah-end", "آخر السورة"], ["after-range", "بعد المقطع"]];

  /* ================================================================ GitHub */
  function b64enc(str) {
    var bytes = new TextEncoder().encode(str), bin = "";
    for (var i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(bin);
  }
  function b64dec(b) {
    var bin = atob(b.replace(/\s/g, ""));
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new TextDecoder().decode(bytes);
  }
  var token = null;
  function api(path, opts) {
    opts = opts || {};
    return fetch("https://api.github.com" + path, {
      method: opts.method || "GET",
      headers: {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
      },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      cache: "no-store",
    }).then(function (r) {
      return r.text().then(function (t) {
        var data = null; try { data = t ? JSON.parse(t) : null; } catch (e) { /* نص */ }
        if (!r.ok) { var err = new Error((data && data.message) || r.statusText); err.status = r.status; throw err; }
        return data;
      });
    });
  }
  function ghError(err) {
    if (err.status === 401) return "المفتاح غير صالح أو انتهت مدته. اخرج وادخل بمفتاح جديد.";
    if (err.status === 403) return "المفتاح لا يملك صلاحية الكتابة. تأكد أن Contents على Read and write وأن المستودع مختار.";
    if (err.status === 404) return "لم يُعثر على المستودع بهذا المفتاح. تأكد أنك اخترت المستودع " + cfg.repo + ".";
    if (err.status === 409 || err.status === 422) return "تغيّرت المادة على GitHub منذ فتحتها. أغلق المحرر وافتحها من جديد.";
    if (!err.status) return "تعذّر الاتصال بـ GitHub. تحقق من الإنترنت ثم أعد المحاولة.";
    return "خطأ من GitHub: " + err.message;
  }

  var gh = {
    whoami: function () {
      return api("/repos/" + cfg.repo).then(function () {
        return api("/user").then(function (u) { return u.login; }, function () { return ""; });
      });
    },
    getFile: function (path) {
      return api("/repos/" + cfg.repo + "/contents/" + path + "?ref=" + encodeURIComponent(cfg.branch))
        .then(function (d) { return { entry: JSON.parse(b64dec(d.content)), sha: d.sha }; },
          function (err) { if (err.status === 404) return null; throw err; });
    },
    putFile: function (path, obj, sha, message) {
      var body = { message: message, branch: cfg.branch, content: b64enc(JSON.stringify(obj, null, 2) + "\n") };
      if (sha) body.sha = sha;
      return api("/repos/" + cfg.repo + "/contents/" + path, { method: "PUT", body: body });
    },
    deleteFile: function (path, sha, message) {
      return api("/repos/" + cfg.repo + "/contents/" + path, { method: "DELETE", body: { message: message, sha: sha, branch: cfg.branch } });
    },
    lastRun: function () {
      return api("/repos/" + cfg.repo + "/actions/runs?branch=" + encodeURIComponent(cfg.branch) + "&per_page=1")
        .then(function (d) { return d.workflow_runs && d.workflow_runs[0]; });
    },
  };

  // النسخة التجريبية: «المستودع» في المتصفح
  var demo = {
    files: function () { try { return JSON.parse(store("demo-files") || "{}"); } catch (e) { return {}; } },
    save: function (f) { store("demo-files", JSON.stringify(f)); },
    whoami: function () { return Promise.resolve("تجربة"); },
    getFile: function (path) {
      var f = demo.files()[path];
      if (f === null) return Promise.resolve(null);
      if (f) return Promise.resolve({ entry: f, sha: "demo" });
      var id = parseInt(path.replace(/\D/g, ""), 10), e = entries.get(id);
      return Promise.resolve(e ? { entry: clean(e), sha: "demo" } : null);
    },
    putFile: function (path, obj, sha) {
      var f = demo.files();
      if (!sha && (f[path] || (f[path] !== null && entries.has(obj.id)))) { var err = new Error("exists"); err.status = 422; return Promise.reject(err); }
      f[path] = obj; demo.save(f);
      return new Promise(function (res) { setTimeout(res, 400); });
    },
    deleteFile: function (path) { var f = demo.files(); f[path] = null; demo.save(f); return Promise.resolve(); },
    lastRun: function () { return Promise.resolve(null); },
  };
  var backend = cfg.demo ? demo : gh;

  /* ================================================================ البيانات */
  var surahs = [];          // [{id, name, plain, count, start}]
  var ayat = [];            // [{s, n, im, ut, nim}] بالترتيب؛ index = gid-1
  var entries = new Map();  // id -> entry
  var builtAt = "";

  function gid(s, n) { var su = surahs[s - 1]; return su ? su.start + n - 1 : 0; }
  function clean(e) {
    var o = {}; Object.keys(e).forEach(function (k) { if (k.charAt(0) !== "_") o[k] = e[k]; }); return o;
  }
  function pathOf(id) { return cfg.entries_dir + "/" + String(id).padStart(4, "0") + ".json"; }
  function linksOf(e) {
    if (e._links && !e._pending) return e._links;
    return (e.locations || []).map(function (l) {
      return [gid(l.surah, l.from), gid(l.surah, l.to || l.from), l.role || "primary"];
    });
  }
  function primaryLoc(e) {
    var l = (e.locations || []).filter(function (x) { return (x.role || "primary") === "primary"; })[0] || (e.locations || [])[0];
    return l;
  }
  function locText(l) {
    if (!l) return "";
    var s = surahs[l.surah - 1]; if (!s) return "";
    var n = l.from === l.to || !l.to ? ar(l.from) : ar(l.from) + "–" + ar(l.to);
    var p = l.placement === "intro" ? " (مقدمة السورة)" : l.placement === "surah-end" ? " (آخر السورة)" : "";
    return s.plain + " " + n + p;
  }

  // ما حُفظ ولم يصل بعد إلى النسخة المنشورة من entries.json
  function pending() { try { return JSON.parse(store("pending:" + cfg.repo) || "{}"); } catch (e) { return {}; } }
  function setPending(id, e) {
    var p = pending();
    p[id] = { e: e ? clean(e) : null, at: new Date().toISOString() };
    store("pending:" + cfg.repo, JSON.stringify(p));
  }
  function applyPending() {
    var p = pending(), keep = {};
    Object.keys(p).forEach(function (id) {
      if (!cfg.demo && builtAt && p[id].at < builtAt) return; // وصل إلى النسخة المنشورة
      keep[id] = p[id];
      id = +id;
      if (p[id].e) { var e = p[id].e; e._pending = true; entries.set(id, e); }
      else entries.delete(id);
    });
    store("pending:" + cfg.repo, JSON.stringify(keep));
  }

  function loadData() {
    var v = "?t=" + Date.now();
    return Promise.all([
      fetch(cfg.index_url).then(function (r) { if (!r.ok) throw new Error("index"); return r.json(); }),
      fetch("entries.json" + v, { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error("entries"); return r.json(); }),
    ]).then(function (res) {
      var idx = res[0], start = 1;
      surahs = idx.s.map(function (s) {
        var o = { id: s[0], name: s[1], plain: s[1], key: norm(s[2] || s[1]), count: s[3], start: start };
        start += s[3]; return o;
      });
      ayat = idx.a.map(function (a) { return { s: a[0], n: a[1], im: a[2], ut: a[3], nim: norm(a[2]) }; });
      builtAt = res[1].built_at || "";
      entries = new Map();
      res[1].entries.forEach(function (e) { entries.set(e.id, e); });
      applyPending();
    });
  }

  /* ================================================================ الدخول */
  function showLogin(msg) {
    $("#loading").hidden = true;
    $("#app").hidden = true;
    $("#login").hidden = false;
    $("#who").hidden = $("#logout").hidden = true;
    $("#login-err").textContent = msg || "";
    var repo = (cfg.repo || "").split("/");
    $("#repo-name").textContent = repo[1] || cfg.repo;
    var q = new URLSearchParams({
      name: "لوحة لقط", description: "إضافة المواد ونشرها من لوحة موقع لقط",
      target_name: repo[0] || "", expires_in: "365", contents: "write", actions: "read",
    });
    $("#token-link").href = "https://github.com/settings/personal-access-tokens/new?" + q.toString();
    setTimeout(function () { $("#token").focus(); }, 50);
  }
  $("#login-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var t = $("#token").value.trim();
    if (!t) return;
    token = t;
    var btn = ev.submitter || $("#login-form .btn");
    btn.disabled = true; $("#login-err").textContent = "";
    gh.whoami().then(function (login) {
      if ($("#remember").checked) store("token", t); else session("token", t);
      $("#token").value = "";
      enter(login);
    }, function (err) {
      token = null;
      $("#login-err").textContent = ghError(err);
    }).then(function () { btn.disabled = false; });
  });
  $("#logout").addEventListener("click", function () {
    store("token", null); session("token", null); token = null;
    showLogin("خرجت من اللوحة. المفتاح حُذف من هذا الجهاز.");
  });

  function enter(login) {
    $("#login").hidden = true;
    $("#loading").hidden = true;
    $("#app").hidden = false;
    if (login) { $("#who").textContent = login; $("#who").hidden = false; }
    $("#logout").hidden = !!cfg.demo;
    route();
    checkDeploy(false);
  }

  /* ================================================================ التبويبات */
  var view = "ayah";
  $$(".tab").forEach(function (t) {
    t.addEventListener("click", function () { setView(t.getAttribute("data-view")); });
  });
  function setView(v) {
    view = v;
    $$(".tab").forEach(function (t) { t.setAttribute("aria-selected", String(t.getAttribute("data-view") === v)); });
    $("#view-ayah").hidden = v !== "ayah";
    $("#view-list").hidden = v === "ayah";
    $("#f-status").closest(".field").hidden = v === "drafts";
    render();
  }
  function counts() {
    var all = 0, drafts = 0;
    entries.forEach(function (e) { all++; if (!isPublic(e)) drafts++; });
    $("#count-all").textContent = "(" + ar(all) + ")";
    $("#count-drafts").textContent = drafts ? "(" + ar(drafts) + ")" : "";
  }
  function render() {
    counts();
    if (view === "ayah") renderAyah(); else renderList();
  }

  /* ================================================================ حسب الآية */
  var cur = { s: 1, n: 1 };
  function route() {
    var m = /^#(\d+):(\d+)$/.exec(location.hash);
    if (m) { cur.s = Math.min(114, Math.max(1, +m[1])); cur.n = +m[2]; }
    else {
      var last = store("last");
      if (last && /^\d+:\d+$/.test(last)) { cur.s = +last.split(":")[0]; cur.n = +last.split(":")[1]; }
    }
    cur.n = Math.min(surahs[cur.s - 1].count, Math.max(1, cur.n));
    render();
  }
  window.addEventListener("hashchange", function () { if (view !== "ayah") setView("ayah"); else route(); });
  function go(s, n) {
    if (n < 1 && s > 1) { s--; n = surahs[s - 1].count; }
    if (n > surahs[s - 1].count && s < 114) { s++; n = 1; }
    n = Math.min(surahs[s - 1].count, Math.max(1, n));
    cur.s = s; cur.n = n;
    store("last", s + ":" + n);
    history.replaceState(null, "", "#" + s + ":" + n);
    if (view !== "ayah") setView("ayah"); else renderAyah();
  }

  function fillSurahSelect(sel, value) {
    sel.innerHTML = surahs.map(function (s) {
      return '<option value="' + s.id + '"' + (s.id === value ? " selected" : "") + ">" + ar(s.id) + ". " + esc(s.name) + "</option>";
    }).join("");
  }
  $("#surah").addEventListener("change", function () { go(+this.value, 1); });
  $("#ayah").addEventListener("change", function () { go(cur.s, +en(this.value) || 1); });
  $("#prev").addEventListener("click", function () { go(cur.s, cur.n - 1); });
  $("#next").addEventListener("click", function () { go(cur.s, cur.n + 1); });

  function entriesAt(g) {
    var out = [];
    entries.forEach(function (e) {
      var ls = linksOf(e);
      for (var i = 0; i < ls.length; i++) {
        if (g >= ls[i][0] && g <= ls[i][1]) { out.push({ e: e, role: ls[i][2] }); break; }
      }
    });
    return out.sort(function (a, b) {
      return (a.role === "cited") - (b.role === "cited") || (a.e.sort_order || a.e.id) - (b.e.sort_order || b.e.id);
    });
  }

  function entryCard(e, opts) {
    opts = opts || {};
    var meta = [];
    if (opts.showKind) meta.push('<span class="badge kind-b">' + esc(KIND[e.kind] || e.kind) + "</span>");
    meta.push(isPublic(e) ? '<span class="badge">منشورة</span>' : '<span class="badge draft">مسودة</span>');
    if (e._pending) meta.push(isPublic(e) ? '<span class="badge pending" title="حُفظت، وتظهر في الموقع بعد اكتمال النشر">تُنشر الآن</span>'
      : '<span class="badge pending">حُفظت للتو</span>');
    if (e.source_auto) meta.push('<span class="badge auto" title="وجد Claude المصدر في مكتبة رقمية؛ افتح المادة وراجع الرابط">مصدر آلي: راجِعه</span>');
    if (opts.role === "cited") meta.push("<span>آية مستشهد بها فيها</span>");
    if (opts.showLoc) meta.push("<span>" + esc(locText(primaryLoc(e))) + "</span>");
    else if (opts.role !== "cited" && (e.locations || []).some(function (l) { return l.placement; }))
      meta.push("<span>" + esc(locText(primaryLoc(e))) + "</span>");
    meta.push('<span class="spacer"></span><span>رقم ' + ar(e.id) + "</span>");
    return '<div class="entry' + (isPublic(e) ? "" : " is-draft") + '">' +
      '<div class="entry-meta">' + meta.join("") + "</div>" +
      (e.title ? '<p class="entry-title">' + esc(e.title) + "</p>" : "") +
      '<p class="entry-snip">' + esc(e.body.replace(/\n{2,}/g, "\n").slice(0, 400)) + "</p>" +
      '<div class="entry-meta"><span class="spacer"></span><button class="btn small" type="button" data-edit="' + e.id + '">تعديل</button></div>' +
      "</div>";
  }

  function renderAyah() {
    var s = surahs[cur.s - 1], g = gid(cur.s, cur.n), a = ayat[g - 1];
    fillSurahSelect($("#surah"), cur.s);
    $("#ayah").max = s.count; $("#ayah").value = cur.n;
    $("#ayah-ref").textContent = "سورة " + s.name + "، الآية " + ar(cur.n);
    $("#ayah-text").textContent = a.ut + " ﴿" + ar(cur.n) + "﴾";
    var site = cfg.site_url;
    $("#ayah-site").hidden = cfg.demo;
    if (!cfg.demo) $("#ayah-site").href = site + "surah/" + cur.s + ".html#a" + cur.n;
    var here = entriesAt(g), html = "";
    (cfg.kinds || []).forEach(function (k) {
      var list = here.filter(function (x) { return x.e.kind === k.id; });
      html += '<section class="kind"><div class="kind-head"><h3>' + esc(k.name) + "</h3>" +
        '<button class="btn small" type="button" data-add="' + k.id + '">+ إضافة</button></div>' +
        (KIND_NOTES[k.id] ? '<p class="kind-note">' + esc(KIND_NOTES[k.id]) + "</p>" : "") +
        (list.length ? list.map(function (x) { return entryCard(x.e, { role: x.role }); }).join("")
          : '<p class="kind-empty">لا شيء بعد.</p>') + "</section>";
    });
    $("#kinds").innerHTML = html;
  }

  // البحث عن آية
  var findT;
  $("#find").addEventListener("input", function () {
    clearTimeout(findT); var q = this.value; findT = setTimeout(function () { find(q); }, 150);
  });
  $("#find").addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") { $("#find-results").hidden = true; }
    if (ev.key === "ArrowDown") { var b = $("#find-results button"); if (b) { ev.preventDefault(); b.focus(); } }
    if (ev.key === "Enter") { var f = $("#find-results button"); if (f) { ev.preventDefault(); f.click(); } }
  });
  document.addEventListener("click", function (ev) { if (!ev.target.closest(".find")) $("#find-results").hidden = true; });
  function parseRef(q) {
    var m = /^\s*(\d{1,3})\s*[:\s]\s*(\d{1,3})\s*$/.exec(en(q));
    if (m && surahs[+m[1] - 1]) return [{ s: +m[1], n: +m[2] }];
    m = /^\s*(?:سورة\s+)?(.+?)\s*[:\s]\s*(\d{1,3})\s*$/.exec(en(q));
    if (!m) return null;
    var key = norm(m[1]), n = +m[2], out = [];
    surahs.forEach(function (s) {
      if (s.key === key || s.key === "ال" + key || s.key.indexOf(key) === 0 || s.key.replace(/^ال/, "").indexOf(key) === 0)
        if (n <= s.count) out.push({ s: s.id, n: n });
    });
    return out.length ? out.slice(0, 8) : null;
  }
  function find(q) {
    var box = $("#find-results");
    q = q.trim();
    if (q.length < 2) { box.hidden = true; return; }
    var hits = parseRef(q) || [];
    if (!hits.length) {
      var nq = norm(q);
      for (var i = 0; i < ayat.length && hits.length < 30; i++) if (ayat[i].nim.indexOf(nq) >= 0) hits.push({ s: ayat[i].s, n: ayat[i].n });
    }
    box.innerHTML = hits.length ? hits.map(function (h) {
      var a = ayat[gid(h.s, h.n) - 1];
      return '<li><button type="button" data-go="' + h.s + ":" + h.n + '"><span class="r">' + esc(surahs[h.s - 1].plain) + " " + ar(h.n) +
        '</span><span class="t">' + esc(a.ut.length > 110 ? a.ut.slice(0, 110) + "…" : a.ut) + "</span></button></li>";
    }).join("") : '<li class="muted" style="padding:.4rem .6rem">لا نتائج.</li>';
    box.hidden = false;
  }
  $("#find-results").addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-go]"); if (!b) return;
    var p = b.getAttribute("data-go").split(":");
    $("#find-results").hidden = true; $("#find").value = "";
    go(+p[0], +p[1]);
  });
  $("#find-results").addEventListener("keydown", function (ev) {
    var li = ev.target.closest("li"); if (!li) return;
    if (ev.key === "ArrowDown" && li.nextElementSibling) { ev.preventDefault(); $("button", li.nextElementSibling).focus(); }
    if (ev.key === "ArrowUp") { ev.preventDefault(); if (li.previousElementSibling) $("button", li.previousElementSibling).focus(); else $("#find").focus(); }
  });

  /* ================================================================ القائمة */
  var listLimit = 60;
  (cfg.kinds || []).forEach(function (k) {
    var o = document.createElement("option"); o.value = k.id; o.textContent = k.name; $("#f-kind").appendChild(o);
  });
  ["#f-kind", "#f-status"].forEach(function (s) { $(s).addEventListener("change", function () { listLimit = 60; renderList(); }); });
  $("#f-q").addEventListener("input", function () { listLimit = 60; renderList(); });
  function renderList() {
    var kind = $("#f-kind").value, st = view === "drafts" ? "draft" : $("#f-status").value, q = norm($("#f-q").value);
    var list = [];
    entries.forEach(function (e) {
      if (kind && e.kind !== kind) return;
      if (st === "public" && !isPublic(e)) return;
      if (st === "draft" && isPublic(e)) return;
      if (q && norm((e.title || "") + " " + e.body).indexOf(q) < 0) return;
      list.push(e);
    });
    list.sort(function (a, b) { return (b.updated_at || "").localeCompare(a.updated_at || "") || b.id - a.id; });
    var html = list.slice(0, listLimit).map(function (e) { return "<li>" + entryCard(e, { showKind: true, showLoc: true }) + "</li>"; }).join("");
    if (!list.length) html = '<li class="kind-empty">' + (view === "drafts" ? "لا مسودات. كل ما حفظته منشور." : "لا مواد بهذا الوصف.") + "</li>";
    if (list.length > listLimit) html += '<li class="list-more"><button class="btn" type="button" id="more">عرض المزيد (' + ar(list.length - listLimit) + ")</button></li>";
    $("#entry-list").innerHTML = html;
  }
  $("#entry-list").addEventListener("click", function (ev) {
    if (ev.target.id === "more") { listLimit += 60; renderList(); }
  });

  document.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-edit]");
    if (b) { openEditor(entries.get(+b.getAttribute("data-edit"))); return; }
    b = ev.target.closest("[data-add]");
    if (b) openEditor(null, { kind: b.getAttribute("data-add"), s: cur.s, n: cur.n });
  });

  /* ================================================================ المحرر */
  var dlg = $("#editor"), ed = null; // {orig, sha, isNew}
  (cfg.kinds || []).forEach(function (k) {
    $("#ed-kinds").insertAdjacentHTML("beforeend",
      '<label><input type="radio" name="kind" value="' + k.id + '"><span>' + esc(k.name) + "</span></label>");
  });
  $("#ed-kinds").addEventListener("change", kindHint);
  function kindHint() {
    var k = ($("input[name=kind]:checked") || {}).value;
    $("#ed-kind-hint").textContent = HIDDEN.indexOf(k) >= 0 ? KIND_NOTES[k] || "هذه الخانة مخفية عن الزوار الآن." : "";
  }

  function locRow(l) {
    var row = document.createElement("div");
    row.className = "loc";
    row.innerHTML =
      '<label class="field f-surah"><span>السورة</span><select class="l-s"></select></label>' +
      '<label class="field f-from"><span>من آية</span><input class="l-a" type="number" min="1" inputmode="numeric"></label>' +
      '<label class="field f-to"><span>إلى آية</span><input class="l-b" type="number" min="1" inputmode="numeric"></label>' +
      '<label class="field f-role"><span>الصفة</span><select class="l-role"><option value="primary">موضع المادة</option><option value="cited">آية مستشهد بها</option></select></label>' +
      '<label class="field f-place"><span>مكان العرض</span><select class="l-p">' +
      PLACES.map(function (p) { return '<option value="' + p[0] + '">' + p[1] + "</option>"; }).join("") + "</select></label>" +
      '<button class="btn icon ghost loc-del" type="button" aria-label="حذف الموضع" title="حذف الموضع">×</button>' +
      '<p class="loc-text"></p>';
    fillSurahSelect($(".l-s", row), l.surah);
    $(".l-a", row).value = l.from; $(".l-b", row).value = l.to || l.from;
    $(".l-role", row).value = l.role || "primary";
    $(".l-p", row).value = l.placement || "";
    if (l.placement !== "after-range") $(".l-p option[value=after-range]", row).hidden = true;
    var upd = function () {
      var s = +$(".l-s", row).value, a = +en($(".l-a", row).value), b = +en($(".l-b", row).value);
      var su = surahs[s - 1];
      $(".l-a", row).max = $(".l-b", row).max = su.count;
      $(".loc-text", row).textContent = a >= 1 && a <= su.count ? ayat[gid(s, a) - 1].ut + (b > a ? " …" : "") : "رقم الآية خارج السورة";
    };
    $(".l-s", row).addEventListener("change", function () { $(".l-a", row).value = $(".l-b", row).value = 1; upd(); });
    $(".l-a", row).addEventListener("input", function () {
      if (+en($(".l-b", row).value) < +en($(".l-a", row).value)) $(".l-b", row).value = $(".l-a", row).value; upd();
    });
    $(".l-b", row).addEventListener("input", upd);
    $(".loc-del", row).addEventListener("click", function () {
      if ($$(".loc", $("#ed-locs")).length > 1) row.remove(); else toast("لا بد من موضع واحد على الأقل.");
    });
    upd();
    return row;
  }
  $("#ed-add-loc").addEventListener("click", function () {
    $("#ed-locs").appendChild(locRow({ surah: cur.s, from: cur.n, to: cur.n, role: "cited" }));
  });

  function fillSources() {
    var set = {};
    entries.forEach(function (e) { if (e.source) set[e.source] = 1; });
    ["التفسير الميسر", "المختصر في تفسير القرآن الكريم"].forEach(function (t) { set[t] = 1; });
    $("#sources").innerHTML = Object.keys(set).sort().map(function (t) { return '<option value="' + esc(t) + '">'; }).join("");
  }

  function fillForm(e) {
    var r = $('input[name=kind][value="' + e.kind + '"]'); if (r) r.checked = true;
    kindHint();
    $("#ed-title-in").value = e.title || "";
    $("#ed-body").value = e.body || "";
    $("#ed-source").value = e.source || "";
    $("#ed-source-ref").value = e.source_ref || "";
    $("#ed-source-url").value = e.source_url || "";
    $("#ed-auto-note").hidden = !e.source_auto;
    $("#ed-locs").innerHTML = "";
    (e.locations && e.locations.length ? e.locations : [{ surah: cur.s, from: cur.n, to: cur.n }])
      .forEach(function (l) { $("#ed-locs").appendChild(locRow(l)); });
    preview();
  }

  function openEditor(e, def) {
    $("#ed-err").textContent = "";
    $("#ed-confirm").hidden = true; $("#ed-actions").hidden = false;
    fillSources();
    if (e) {
      ed = { orig: e, sha: null, isNew: false };
      $("#ed-title").textContent = "تعديل " + (e.kind === "faida" ? "فائدة" : "مادة") + " (رقم " + ar(e.id) + ")";
      $("#ed-status-now").textContent = isPublic(e) ? "منشورة الآن" : "مسودة لا يراها الزوار";
      $("#ed-delete").hidden = false;
      $("#ed-publish").textContent = isPublic(e) ? "حفظ ونشر" : "نشر";
      $("#ed-draft").textContent = isPublic(e) ? "إرجاعها مسودة" : "حفظ المسودة";
      fillForm(e);
      busy(true, "جارٍ جلب أحدث نسخة…");
      backend.getFile(pathOf(e.id)).then(function (f) {
        busy(false);
        if (!f) { ed.isNew = true; return; } // لم يصل الملف بعد (مثلًا: حُذف)، فيُنشأ من جديد
        ed.sha = f.sha;
        if (JSON.stringify(f.entry) !== JSON.stringify(clean(e)) && !e._pending) { ed.orig = f.entry; fillForm(f.entry); }
      }, function (err) { busy(false); $("#ed-err").textContent = ghError(err); });
    } else {
      ed = { orig: null, sha: null, isNew: true };
      $("#ed-title").textContent = "إضافة " + (def.kind === "faida" ? "فائدة" : "مادة في «" + (KIND[def.kind] || "") + "»") +
        " على " + surahs[def.s - 1].plain + " " + ar(def.n);
      $("#ed-status-now").textContent = "";
      $("#ed-delete").hidden = true;
      $("#ed-publish").textContent = "نشر"; $("#ed-draft").textContent = "حفظ مسودة";
      fillForm({ kind: def.kind, body: "", locations: [{ surah: def.s, from: def.n, to: def.n }] });
      busy(false);
    }
    if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
    setTimeout(function () { $("#ed-body").focus(); }, 30);
  }
  function busy(on, msg) {
    ["#ed-publish", "#ed-draft", "#ed-delete", "#ed-del-yes"].forEach(function (s) { $(s).disabled = on; });
    if (msg) $("#ed-status-now").textContent = msg;
    else if (!on && ed && ed.orig) $("#ed-status-now").textContent = isPublic(ed.orig) ? "منشورة الآن" : "مسودة لا يراها الزوار";
  }
  function closeEditor() {
    if (dlg.open) { if (typeof dlg.close === "function") dlg.close(); else dlg.removeAttribute("open"); }
    ed = null;
  }
  $("#ed-close").addEventListener("click", closeEditor);
  dlg.addEventListener("cancel", function () { ed = null; });

  // أدوات النص
  $$("[data-wrap]").forEach(function (b) {
    b.addEventListener("click", function () {
      var p = b.getAttribute("data-wrap").split("|"), t = $("#ed-body");
      var a = t.selectionStart, z = t.selectionEnd, sel = t.value.slice(a, z);
      t.setRangeText(p[0] + sel + p[1], a, z, sel ? "end" : "start");
      if (!sel) t.selectionStart = t.selectionEnd = a + p[0].length;
      t.focus(); preview();
    });
  });
  $("#ed-ref").addEventListener("click", function () {
    var l = readLocs()[0] || { surah: cur.s, from: cur.n }, t = $("#ed-body");
    var txt = "[" + surahs[l.surah - 1].plain + ": " + ar(l.from) + "]";
    t.setRangeText(txt, t.selectionStart, t.selectionEnd, "end"); t.focus(); preview();
  });
  $("#ed-body").addEventListener("input", preview);
  function preview() {
    var body = esc($("#ed-body").value.trim().replace(/\n{3,}/g, "\n\n"));
    body = body.replace(/\[[^\]\n]{2,30}?\]/g, function (m) { return '<span class="xref">' + m + "</span>"; })
      .replace(/﴿[^﴿﴾\n]{1,400}﴾/g, function (m) { return '<span class="qv">' + m + "</span>"; });
    var url = $("#ed-source-url").value.trim(), t = esc($("#ed-source").value.trim());
    if (/^https?:\/\/[^\s<>"]+$/.test(url)) t = '<a class="xref" href="' + esc(url) + '" target="_blank" rel="noopener" title="' + libName(url) + '">' + (t || "الكتاب") + "</a>";
    var src = [t, esc($("#ed-source-ref").value.trim())].filter(Boolean).join("، ");
    $("#ed-preview").innerHTML = ($("#ed-title-in").value.trim() ? "<b>" + esc($("#ed-title-in").value.trim()) + "</b>\n" : "") +
      (body || '<span class="muted">اكتب النص لتراه هنا كما سيظهر.</span>') + (src ? '\n<span class="muted">المصدر: ' + src + "</span>" : "");
  }
  function libName(url) {
    var host = url.replace(/^https?:\/\/(www\.)?/, "").split("/")[0].toLowerCase();
    var L = { "turath.io": "تراث", "shamela.ws": "المكتبة الشاملة", "dorar.net": "الدرر السنية", "islamweb.net": "إسلام ويب",
      "waqfeya.net": "المكتبة الوقفية", "archive.org": "أرشيف الإنترنت", "ketabonline.com": "كتاب أونلاين" };
    for (var d in L) if (host === d || host.slice(-d.length - 1) === "." + d) return "افتح الموضع في " + L[d];
    return "افتح الموضع في مصدره";
  }
  ["#ed-title-in", "#ed-source", "#ed-source-ref", "#ed-source-url"].forEach(function (s) { $(s).addEventListener("input", preview); });

  function readLocs() {
    return $$(".loc", $("#ed-locs")).map(function (row) {
      var l = { surah: +$(".l-s", row).value, from: +en($(".l-a", row).value), to: +en($(".l-b", row).value) || +en($(".l-a", row).value),
        placement: $(".l-p", row).value || null };
      if ($(".l-role", row).value === "cited") l.role = "cited";
      return l;
    });
  }

  function buildEntry(status) {
    var kind = ($("input[name=kind]:checked") || {}).value;
    var body = $("#ed-body").value.replace(/\r\n/g, "\n").replace(/[ \t]+\n/g, "\n").trim();
    var locs = readLocs();
    if (!kind) return "اختر نوع المادة.";
    if (!body) return "النص فارغ.";
    for (var i = 0; i < locs.length; i++) {
      var l = locs[i], s = surahs[l.surah - 1];
      if (!s || !(l.from >= 1) || l.to < l.from || l.to > s.count)
        return "الموضع " + ar(i + 1) + " غير صحيح: سورة " + (s ? s.plain : "؟") + " آياتها " + ar(s ? s.count : 0) + ".";
    }
    if (!locs.some(function (l) { return !l.role; })) return "اجعل موضعًا واحدًا على الأقل «موضع المادة».";
    var url = $("#ed-source-url").value.trim();
    if (url && !/^https?:\/\/[^\s<>"]+$/.test(url)) return "رابط المصدر غير صالح. انسخه كاملًا من شريط العنوان، ويبدأ بـ https://";
    var now = new Date().toISOString().replace(/\.\d+Z$/, "Z");
    var o = ed.orig ? clean(ed.orig) : {};
    var e = {
      id: o.id, kind: kind, status: status,
      title: $("#ed-title-in").value.trim() || null, body: body, locations: locs,
      source: $("#ed-source").value.trim() || null, source_ref: $("#ed-source-ref").value.trim() || null,
      source_url: $("#ed-source-url").value.trim() || null,
      sort_order: o.sort_order != null ? o.sort_order : undefined,
    };
    Object.keys(o).forEach(function (k) { if (!(k in e)) e[k] = o[k]; }); // حقول قديمة تُحفظ كما هي
    delete e.source_auto; // حفظها من اللوحة يعني أن صاحب الموقع راجع المصدر
    e.created_at = o.created_at || now; e.updated_at = now;
    if (e.origin == null) e.origin = "admin";
    if (e.sort_order === undefined) delete e.sort_order;
    return e;
  }

  function nextId() {
    var max = 0;
    entries.forEach(function (_, id) { if (id > max) max = id; });
    Object.keys(pending()).forEach(function (id) { if (+id > max) max = +id; });
    return max + 1;
  }

  function save(status) {
    if (!ed) return;
    var e = buildEntry(status);
    if (typeof e === "string") { $("#ed-err").textContent = e; return; }
    $("#ed-err").textContent = "";
    var where = locText(primaryLoc(e)), kname = e.kind === "faida" ? "فائدة" : (KIND[e.kind] || "مادة");
    var verb = ed.isNew ? "إضافة" : "تعديل";
    var msg = verb + " " + kname + " على " + where + (status === "draft" ? " (مسودة)" : "") + "\n\nمن لوحة الإدخال";
    busy(true, "جارٍ الحفظ…");
    var attempt = function (id, tries) {
      e.id = id;
      return backend.putFile(pathOf(id), e, ed.sha, msg).catch(function (err) {
        // رقم مأخوذ (مادة أُضيفت من جهاز آخر): جرّب التالي
        if (ed.isNew && err.status === 422 && tries < 5) return attempt(id + 1, tries + 1);
        throw err;
      });
    };
    attempt(ed.isNew && !e.id ? nextId() : e.id, 0).then(function () {
      e._pending = true;
      entries.set(e.id, e);
      setPending(e.id, e);
      var pub = status !== "draft";
      closeEditor();
      render();
      toast(cfg.demo ? "حُفظت في النسخة التجريبية." :
        pub ? "حُفظت. تظهر في الموقع خلال دقيقتين تقريبًا." : "حُفظت مسودة. لا يراها الزوار حتى تنشرها.", 4500);
      if (!cfg.demo) checkDeploy(true);
    }, function (err) {
      busy(false);
      $("#ed-err").textContent = ghError(err);
    });
  }
  $("#ed-publish").addEventListener("click", function () {
    save(ed && ed.orig && isPublic(ed.orig) ? ed.orig.status : "published");
  });
  $("#ed-draft").addEventListener("click", function () { save("draft"); });
  $("#ed-delete").addEventListener("click", function () { $("#ed-actions").hidden = true; $("#ed-confirm").hidden = false; });
  $("#ed-del-no").addEventListener("click", function () { $("#ed-actions").hidden = false; $("#ed-confirm").hidden = true; });
  $("#ed-del-yes").addEventListener("click", function () {
    if (!ed || !ed.orig) return;
    var e = ed.orig, id = e.id;
    if (!ed.sha && !cfg.demo) { $("#ed-err").textContent = "لم يكتمل جلب المادة من GitHub بعد. انتظر لحظة ثم أعد المحاولة."; return; }
    busy(true, "جارٍ الحذف…");
    backend.deleteFile(pathOf(id), ed.sha, "حذف " + (e.kind === "faida" ? "فائدة" : "مادة") + " رقم " + id + " (" + locText(primaryLoc(e)) + ")\n\nمن لوحة الإدخال")
      .then(function () {
        entries.delete(id); setPending(id, null);
        closeEditor(); render();
        toast(cfg.demo ? "حُذفت من النسخة التجريبية." : "حُذفت. تختفي من الموقع خلال دقيقتين تقريبًا.", 4500);
        if (!cfg.demo) checkDeploy(true);
      }, function (err) { busy(false); $("#ed-err").textContent = ghError(err); });
  });

  /* ================================================================ حالة النشر */
  var deployT, deploySince = 0;
  function checkDeploy(afterSave) {
    if (cfg.demo) return;
    var el = $("#deploy");
    el.href = "https://github.com/" + cfg.repo + "/actions";
    if (afterSave) { deploySince = Date.now(); el.className = "deploy running"; el.textContent = "يُنشر الآن…"; el.hidden = false; }
    clearTimeout(deployT);
    if (afterSave) { deployT = setTimeout(function () { checkDeploy(false); }, 8000); return; }
    gh.lastRun().then(function (run) {
      if (!run) return;
      var started = Date.parse(run.created_at);
      var waiting = deploySince && started < deploySince - 10000; // لم يبدأ نشر الحفظ الأخير بعد
      el.hidden = false;
      if (waiting || run.status !== "completed") {
        el.className = "deploy running"; el.textContent = "يُنشر الآن…";
        if (Date.now() - (deploySince || started) < 10 * 60000) deployT = setTimeout(function () { checkDeploy(false); }, 10000);
      } else if (run.conclusion === "success") {
        el.className = "deploy ok"; el.textContent = deploySince ? "نُشر في الموقع" : "الموقع محدَّث";
        if (deploySince) toast("اكتمل النشر، وصار ما حفظته في الموقع.");
        deploySince = 0;
      } else {
        el.className = "deploy fail"; el.textContent = "تعثّر النشر، اضغط للتفاصيل"; deploySince = 0;
      }
    }, function () {
      // المفتاح بلا صلاحية Actions: رابط للمتابعة فقط
      el.className = "deploy"; el.textContent = "متابعة النشر"; el.hidden = false;
    });
  }

  /* ================================================================ البدء */
  if (cfg.demo) $("#demo-note").hidden = false;
  else $("#site-link").href = cfg.site_url || "../";
  if (cfg.demo) $("#site-link").hidden = true;
  loadData().then(function () {
    if (cfg.demo) { enter("تجربة"); return; }
    token = store("token") || session("token");
    if (!token) { showLogin(); return; }
    $("#loading").textContent = "جارٍ التحقق من المفتاح…";
    gh.whoami().then(enter, function (err) {
      if (err.status === 401) { store("token", null); session("token", null); token = null; showLogin(ghError(err)); }
      else enter(""); // انقطاع مؤقت: ادخل، وتظهر الأخطاء عند الحفظ
    });
  }, function () {
    $("#loading").textContent = "تعذّر تحميل بيانات اللوحة. حدّث الصفحة بعد قليل.";
  });
})();
