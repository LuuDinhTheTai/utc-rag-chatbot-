-- Additive, transactional upgrade of schema_v2. Applied once by runtime.
CREATE TABLE planner_revisions (
  account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0)
) STRICT;
CREATE TABLE planner_preferences (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  offering_id TEXT REFERENCES admission_offerings(id) ON DELETE SET NULL,
  admission_year INTEGER NOT NULL CHECK(admission_year BETWEEN 2000 AND 2100),
  campus TEXT NOT NULL REFERENCES campuses(code), admission_code TEXT NOT NULL,
  program_name TEXT NOT NULL, source_url TEXT NOT NULL,
  position INTEGER NOT NULL CHECK(position > 0),
  method TEXT NOT NULL CHECK(method IN ('PT1','PT2','PT3','PT4')),
  subject_group TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
  estimated_score REAL CHECK(estimated_score >= 0 AND estimated_score <= score_scale),
  score_scale INTEGER NOT NULL DEFAULT 30 CHECK(score_scale IN (30,100,150,1200)),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(account_id,admission_year,campus,admission_code),
  UNIQUE(account_id,admission_year,position)
) STRICT;
CREATE TABLE planner_tasks (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  admission_year INTEGER NOT NULL CHECK(admission_year BETWEEN 2000 AND 2100),
  title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', due_date TEXT,
  completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0,1)),
  source_url TEXT NOT NULL DEFAULT '', template_key TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(account_id,admission_year,template_key)
) STRICT;
CREATE INDEX planner_tasks_owner_date ON planner_tasks(account_id,admission_year,due_date);
CREATE TABLE admission_score_rules (
  id TEXT PRIMARY KEY, title TEXT NOT NULL,
  admission_year INTEGER NOT NULL CHECK(admission_year BETWEEN 2000 AND 2100),
  campus TEXT NOT NULL REFERENCES campuses(code), subject_group TEXT NOT NULL,
  subject_1 TEXT NOT NULL, subject_2 TEXT NOT NULL, subject_3 TEXT NOT NULL,
  weight_1 REAL NOT NULL CHECK(weight_1 > 0 AND weight_1 <= 3),
  weight_2 REAL NOT NULL CHECK(weight_2 > 0 AND weight_2 <= 3),
  weight_3 REAL NOT NULL CHECK(weight_3 > 0 AND weight_3 <= 3),
  priority_mode TEXT NOT NULL CHECK(priority_mode IN ('none','provided','taper_30')),
  priority_cap REAL NOT NULL CHECK(priority_cap BETWEEN 0 AND 5),
  bonus_cap REAL NOT NULL CHECK(bonus_cap BETWEEN 0 AND 3),
  source_url TEXT NOT NULL, scope_note TEXT NOT NULL,
  published_by TEXT REFERENCES accounts(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))
) STRICT;
CREATE INDEX score_rules_scope ON admission_score_rules(admission_year,campus,is_active);
INSERT INTO schema_migrations VALUES ('planner_v1',strftime('%Y-%m-%dT%H:%M:%fZ','now'));
