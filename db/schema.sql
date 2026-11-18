-- مخطط قاعدة بيانات «لقط»
-- مكتوب بـ SQLite، ويُنقل إلى PostgreSQL لاحقًا بتغييرات يسيرة.

PRAGMA foreign_keys = ON;

------------------------------------------------------------------
-- (١) المصحف: رواية حفص عن عاصم، نص مجمع الملك فهد (الإصدار 18)
------------------------------------------------------------------

CREATE TABLE riwayat (
  id          TEXT PRIMARY KEY,          -- 'hafs'
  name_ar     TEXT NOT NULL,
  source      TEXT NOT NULL,
  version     TEXT
);

CREATE TABLE surahs (
  id                INTEGER PRIMARY KEY CHECK (id BETWEEN 1 AND 114),
  name_ar           TEXT NOT NULL,        -- الاسم كما في بيانات المجمع (مشكول)
  name_ar_plain     TEXT NOT NULL,        -- بلا تشكيل، للبحث والروابط
  name_en           TEXT NOT NULL,
  ayah_count        INTEGER NOT NULL,
  revelation_place  TEXT NOT NULL CHECK (revelation_place IN ('makki','madani')),
  revelation_order  INTEGER NOT NULL,
  first_ayah_id     INTEGER NOT NULL,
  page_start        INTEGER NOT NULL,
  page_end          INTEGER NOT NULL
);

-- الآيات: صف لكل آية من الـ 6236، والمعرّف تسلسلي على ترتيب المصحف
CREATE TABLE ayat (
  id            INTEGER PRIMARY KEY CHECK (id BETWEEN 1 AND 6236),
  surah_id      INTEGER NOT NULL REFERENCES surahs(id),
  number        INTEGER NOT NULL,          -- رقم الآية في سورتها
  text_uthmani  TEXT NOT NULL,             -- الرسم العثماني بلا رقم الآية
  text_marked   TEXT NOT NULL,             -- كما في المصدر: مع علامة الحزب ۞ ورقم الآية
  text_imlaei   TEXT NOT NULL,             -- الرسم الإملائي بلا تشكيل، للبحث
  page          INTEGER NOT NULL CHECK (page BETWEEN 1 AND 604),
  line_start    INTEGER NOT NULL,
  line_end      INTEGER NOT NULL,
  juz           INTEGER NOT NULL CHECK (juz BETWEEN 1 AND 30),  -- بحسب علامة بداية الجزء ۞
  page_juz      INTEGER NOT NULL CHECK (page_juz BETWEEN 1 AND 30), -- الجزء المطبوع أعلى الصفحة
  hizb          INTEGER NOT NULL CHECK (hizb BETWEEN 1 AND 60),
  rub           INTEGER NOT NULL CHECK (rub BETWEEN 1 AND 240),   -- ربع الحزب (تسلسلي)
  rub_start     INTEGER NOT NULL DEFAULT 0, -- 1 إن كانت أول آية في ربع
  manzil        INTEGER NOT NULL CHECK (manzil BETWEEN 1 AND 7),
  sajda         INTEGER NOT NULL DEFAULT 0,
  UNIQUE (surah_id, number)
);
CREATE INDEX ayat_page ON ayat(page);
CREATE INDEX ayat_hizb ON ayat(hizb);

-- أرباع الأحزاب (240) ومواضع بدايتها
CREATE TABLE rubs (
  id             INTEGER PRIMARY KEY CHECK (id BETWEEN 1 AND 240),
  hizb           INTEGER NOT NULL,
  juz            INTEGER NOT NULL,
  quarter        INTEGER NOT NULL CHECK (quarter BETWEEN 1 AND 4),
  first_ayah_id  INTEGER NOT NULL REFERENCES ayat(id),
  last_ayah_id   INTEGER NOT NULL REFERENCES ayat(id)
);

------------------------------------------------------------------
-- (٢) المحتوى: الفوائد والتفسير والإعراب وما يُستجد
------------------------------------------------------------------

-- أنواع المحتوى؛ كل نوع يصير تبويبًا تحت الآية في الموقع
CREATE TABLE content_kinds (
  id          TEXT PRIMARY KEY,           -- qiraat, maana, tafsir, irab, faida, ...
  name_ar     TEXT NOT NULL,
  sort_order  INTEGER NOT NULL
);

-- المراجع: الكتب والمؤلفون الذين يُنقل عنهم (تمتلئ في المرحلة الرابعة)
CREATE TABLE sources (
  id          INTEGER PRIMARY KEY,
  title       TEXT NOT NULL,              -- مثل: تيسير الكريم الرحمن
  author      TEXT,                       -- مثل: عبدالرحمن السعدي
  edition     TEXT,
  notes       TEXT
);

-- مادة واحدة: فائدة أو تفسير أو إعراب...
CREATE TABLE entries (
  id            INTEGER PRIMARY KEY,
  kind          TEXT NOT NULL REFERENCES content_kinds(id),
  title         TEXT,
  body          TEXT NOT NULL,
  source_id     INTEGER REFERENCES sources(id),
  source_ref    TEXT,                     -- الجزء والصفحة كما ورد
  status        TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','needs_review','ready','published')),
  origin        TEXT,                     -- من أين جاء النص: user / image / chatgpt
  legacy_id     INTEGER,                  -- رقمه في ملف «برمجة لقط الأولية»
  legacy_msg    INTEGER,                  -- رقم الرسالة الأصلية في المحادثة
  edits         TEXT NOT NULL DEFAULT '[]', -- JSON: تعديلات أُجريت على النص
  flags         TEXT NOT NULL DEFAULT '[]', -- JSON: ملاحظات تحتاج مراجعة
  sort_order    INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX entries_kind ON entries(kind);

-- ربط المادة بآية أو مقطع من الآيات (المادة قد ترتبط بأكثر من موضع)
CREATE TABLE entry_ayat (
  entry_id       INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  first_ayah_id  INTEGER NOT NULL REFERENCES ayat(id),
  last_ayah_id   INTEGER NOT NULL REFERENCES ayat(id),
  placement      TEXT,     -- NULL: تحت الآية | intro: مقدمة السورة | surah-end: آخر السورة | after-range: بعد المقطع
  role           TEXT NOT NULL DEFAULT 'primary'
                 CHECK (role IN ('primary','cited')), -- primary: موضع الفائدة الأصلي | cited: آية مستشهد بها فيها
  PRIMARY KEY (entry_id, first_ayah_id, last_ayah_id),
  CHECK (last_ayah_id >= first_ayah_id)
);
CREATE INDEX entry_ayat_first ON entry_ayat(first_ayah_id);

------------------------------------------------------------------
-- (٣) عروض جاهزة للموقع
------------------------------------------------------------------

-- كل آية مع عدد المواد في كل تبويب. الآية التي ليس لها مادة تظهر بأصفار:
-- وهي «الخانة الفارغة» التي تنتظر ما يُنشر فيها لاحقًا.
CREATE VIEW ayah_overview AS
SELECT a.id, a.surah_id, a.number, a.page, a.juz, a.hizb, a.rub,
  (SELECT count(*) FROM entry_ayat ea JOIN entries e ON e.id = ea.entry_id
     WHERE a.id BETWEEN ea.first_ayah_id AND ea.last_ayah_id AND e.kind = 'qiraat') AS qiraat,
  (SELECT count(*) FROM entry_ayat ea JOIN entries e ON e.id = ea.entry_id
     WHERE a.id BETWEEN ea.first_ayah_id AND ea.last_ayah_id AND e.kind = 'maana')  AS maana,
  (SELECT count(*) FROM entry_ayat ea JOIN entries e ON e.id = ea.entry_id
     WHERE a.id BETWEEN ea.first_ayah_id AND ea.last_ayah_id AND e.kind = 'tafsir') AS tafsir,
  (SELECT count(*) FROM entry_ayat ea JOIN entries e ON e.id = ea.entry_id
     WHERE a.id BETWEEN ea.first_ayah_id AND ea.last_ayah_id AND e.kind = 'irab')   AS irab,
  (SELECT count(*) FROM entry_ayat ea JOIN entries e ON e.id = ea.entry_id
     WHERE a.id BETWEEN ea.first_ayah_id AND ea.last_ayah_id AND e.kind = 'faida')  AS fawaid
FROM ayat a;

-- المواد مع مواضعها بصيغة مقروءة (سورة:آية-آية)
CREATE VIEW entry_locations AS
SELECT e.id AS entry_id, e.kind, e.status, ea.placement, ea.role,
       af.surah_id, af.number AS ayah_from, al.number AS ayah_to,
       ea.first_ayah_id, ea.last_ayah_id
FROM entries e
JOIN entry_ayat ea ON ea.entry_id = e.id
JOIN ayat af ON af.id = ea.first_ayah_id
JOIN ayat al ON al.id = ea.last_ayah_id;
