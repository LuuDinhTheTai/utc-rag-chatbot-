import {
    reconcileJobLifecycle,
} from '../normalizers/job-lifecycle.js';
import Database from 'better-sqlite3';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const DEFAULT_DB_PATH = path.resolve(
    __dirname,
    '../../data/career.db'
);

export function createCareerStore(dbPath = DEFAULT_DB_PATH) {
    fs.mkdirSync(path.dirname(dbPath), { recursive: true });

    const db = new Database(dbPath);

    db.pragma('journal_mode = WAL');
    db.pragma('foreign_keys = ON');

    // =====================================================
    // 1. DATABASE MIGRATIONS
    // =====================================================

    function getColumns(tableName) {
        return db.prepare(
            `PRAGMA table_info(${tableName})`
        ).all().map(column => column.name);
    }


    function migrate() {
        // =====================================================
        // 1. CRAWL RUNS TABLE
        // =====================================================

        db.exec(`
            CREATE TABLE IF NOT EXISTS crawl_runs (
                run_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',

                crawl_scope TEXT,

                started_at TEXT NOT NULL,
                finished_at TEXT,

                pages_discovered INTEGER DEFAULT 0,
                pages_fetched INTEGER DEFAULT 0,
                jobs_found INTEGER DEFAULT 0,

                is_full_crawl INTEGER NOT NULL DEFAULT 0,

                error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_crawl_runs_source
            ON crawl_runs(source);

            CREATE INDEX IF NOT EXISTS idx_crawl_runs_started_at
            ON crawl_runs(started_at);
        `);

        // Additive migration for existing crawl_runs.
        const runColumns = getColumns('crawl_runs');

        if (!runColumns.includes('crawl_scope')) {
            db.exec(`
                ALTER TABLE crawl_runs
                ADD COLUMN crawl_scope TEXT
            `);
        }

        if (!runColumns.includes('lifecycle_reconciled')) {
            db.exec(`
                ALTER TABLE crawl_runs
                ADD COLUMN lifecycle_reconciled INTEGER NOT NULL DEFAULT 0
            `);
        }

        // =====================================================
        // 2. CAREER JOBS TABLE
        // =====================================================

        db.exec(`
            CREATE TABLE IF NOT EXISTS career_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                source TEXT NOT NULL,
                external_id TEXT NOT NULL,

                title TEXT NOT NULL,
                company TEXT,

                payload TEXT NOT NULL,
                content_hash TEXT NOT NULL,

                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_crawled_at TEXT NOT NULL,

                UNIQUE(source, external_id)
            );
        `);

        // Additive migration for existing databases.
        const jobColumns = getColumns('career_jobs');

        if (!jobColumns.includes('status')) {
            db.exec(`
                ALTER TABLE career_jobs
                ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
            `);
        }

        if (!jobColumns.includes('last_seen_run_id')) {
            db.exec(`
                ALTER TABLE career_jobs
                ADD COLUMN last_seen_run_id TEXT
                REFERENCES crawl_runs(run_id)
            `);
        }

        if (!jobColumns.includes('missing_full_runs')) {
            db.exec(`
                ALTER TABLE career_jobs
                ADD COLUMN missing_full_runs INTEGER NOT NULL DEFAULT 0
            `);
        }

        // =====================================================
        // 3. CAREER JOB SCOPES TABLE
        // =====================================================

        db.exec(`
            CREATE TABLE IF NOT EXISTS career_job_scopes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                crawl_scope TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'active',

                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,

                last_seen_run_id TEXT
                    REFERENCES crawl_runs(run_id),

                missing_full_runs INTEGER NOT NULL DEFAULT 0,

                UNIQUE(source, external_id, crawl_scope),

                FOREIGN KEY(source, external_id)
                    REFERENCES career_jobs(source, external_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_job_scopes_source_scope
            ON career_job_scopes(source, crawl_scope);

            CREATE INDEX IF NOT EXISTS idx_job_scopes_status
            ON career_job_scopes(status);

            CREATE INDEX IF NOT EXISTS idx_job_scopes_last_seen_run
            ON career_job_scopes(last_seen_run_id);

            CREATE INDEX IF NOT EXISTS idx_job_scopes_job
            ON career_job_scopes(source, external_id);
        `);

        // =====================================================
        // 4. CAREER JOBS INDEXES
        // =====================================================

        db.exec(`
            CREATE INDEX IF NOT EXISTS idx_career_jobs_source
            ON career_jobs(source);

            CREATE INDEX IF NOT EXISTS idx_career_jobs_content_hash
            ON career_jobs(content_hash);

            CREATE INDEX IF NOT EXISTS idx_career_jobs_status
            ON career_jobs(status);

            CREATE INDEX IF NOT EXISTS idx_career_jobs_last_seen_run
            ON career_jobs(last_seen_run_id);
        `);
    }


    migrate();

    // =====================================================
    // 2. PREPARED STATEMENTS
    // =====================================================

    const statements = {
        getAll: db.prepare(`
            SELECT
                source,
                external_id,
                payload,
                content_hash
            FROM career_jobs
        `),

        insert: db.prepare(`
            INSERT INTO career_jobs (
                source,
                external_id,
                title,
                company,
                payload,
                content_hash,
                first_seen_at,
                last_seen_at,
                last_crawled_at,
                status,
                last_seen_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        `),

        update: db.prepare(`
            UPDATE career_jobs
            SET
                title = ?,
                company = ?,
                payload = ?,
                content_hash = ?,
                last_seen_at = ?,
                last_crawled_at = ?,
                last_seen_run_id = ?
            WHERE source = ? AND external_id = ?
        `),

        touch: db.prepare(`
            UPDATE career_jobs
            SET
                last_seen_at = ?,
                last_crawled_at = ?,
                last_seen_run_id = ?
            WHERE source = ? AND external_id = ?
        `),

        createRun: db.prepare(`
            INSERT INTO crawl_runs (
                run_id,
                source,
                crawl_scope,
                status,
                started_at
            )
            VALUES (?, ?, ?, 'running', ?)
        `),

        getRun: db.prepare(`
            SELECT *
            FROM crawl_runs
            WHERE run_id = ?
        `),

        finishRun: db.prepare(`
            UPDATE crawl_runs
            SET
                status = ?,
                finished_at = ?,
                pages_discovered = ?,
                pages_fetched = ?,
                jobs_found = ?,
                is_full_crawl = ?,
                error = ?
            WHERE run_id = ? AND status = 'running'
        `),

        getRuns: db.prepare(`
            SELECT *
            FROM crawl_runs
            ORDER BY started_at DESC
            LIMIT ?
        `),
    };

    // =====================================================
    // 3. JOB STORAGE
    // =====================================================

    function loadAllJobs() {
        return statements.getAll.all().map(row => ({
            ...JSON.parse(row.payload),
            contentHash: row.content_hash,
        }));
    }

    function getJob(source, externalId) {
        const row = db.prepare(`
            SELECT *
            FROM career_jobs
            WHERE source = ? AND external_id = ?
        `).get(source, externalId);

        if (!row) {
            return null;
        }

        return {
            ...JSON.parse(row.payload),
            contentHash: row.content_hash,
            status: row.status,
            lastSeenRunId: row.last_seen_run_id,
        };
    }


    function saveClassifiedJobs({
        new: newJobs = [],
        updated = [],
        unchanged = [],
        runId = null,
    }) {
        const now = new Date().toISOString();

        let run = null;

        // Validate crawl session.
        if (runId) {
            run = statements.getRun.get(runId);

            if (!run || run.status !== 'running') {
                throw new Error(
                    `Invalid or inactive crawl run: ${runId}`
                );
            }

            if (!run.crawl_scope) {
                throw new Error(
                    `Crawl run has no scope: ${runId}`
                );
            }
        }

        // Upsert job-scope relationship.
        const recordScope = db.prepare(`
            INSERT INTO career_job_scopes (
                source,
                external_id,
                crawl_scope,
                status,
                first_seen_at,
                last_seen_at,
                last_seen_run_id,
                missing_full_runs
            )
            VALUES (?, ?, ?, 'active', ?, ?, ?, 0)

            ON CONFLICT(source, external_id, crawl_scope)
            DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                last_seen_run_id = excluded.last_seen_run_id,
                status = 'active',
                missing_full_runs = 0
        `);

        const saveTransaction = db.transaction(() => {
            function validateJob(job, type) {
                if (!job.source || !job.externalId || !job.title) {
                    throw new Error(
                        `Invalid ${type} job: ${JSON.stringify(job)}`
                    );
                }

                if (run && job.source !== run.source) {
                    throw new Error(
                        `Job source does not match crawl run: ${job.externalId}`
                    );
                }
            }

            function saveJobScope(job) {
                if (!run) return;

                recordScope.run(
                    job.source,
                    job.externalId,
                    run.crawl_scope,
                    now,
                    now,
                    runId
                );

                // Refresh global job status after reactivating scope.
                refreshGlobalJobStatus({
                    source: job.source,
                    externalId: job.externalId,
                });
            }

            // ================================================
            // 1. INSERT NEW JOBS
            // ================================================

            for (const item of newJobs) {
                const job = item.job ?? item;
                const contentHash =
                    item.contentHash ?? job.contentHash;

                validateJob(job, 'new');

                if (!contentHash) {
                    throw new Error(
                        `Missing contentHash for job ${job.externalId}`
                    );
                }

                statements.insert.run(
                    job.source,
                    job.externalId,
                    job.title,
                    job.company?.name ?? null,
                    JSON.stringify(job),
                    contentHash,
                    now,
                    now,
                    now,
                    runId
                );

                saveJobScope(job);
            }

            // ================================================
            // 2. UPDATE CHANGED JOBS
            // ================================================

            for (const item of updated) {
                const job = item.job ?? item;
                const contentHash =
                    item.contentHash ?? job.contentHash;

                validateJob(job, 'updated');

                if (!contentHash) {
                    throw new Error(
                        `Missing contentHash for job ${job.externalId}`
                    );
                }

                statements.update.run(
                    job.title,
                    job.company?.name ?? null,
                    JSON.stringify(job),
                    contentHash,
                    now,
                    now,
                    runId,
                    job.source,
                    job.externalId
                );

                saveJobScope(job);
            }

            // ================================================
            // 3. TOUCH UNCHANGED JOBS
            // ================================================

            for (const item of unchanged) {
                const job = item.job ?? item;

                validateJob(job, 'unchanged');

                statements.touch.run(
                    now,
                    now,
                    runId,
                    job.source,
                    job.externalId
                );

                saveJobScope(job);
            }
        });

        saveTransaction();
    }


    // =====================================================
    // 4. CRAWL SESSION MANAGEMENT
    // =====================================================

    function startCrawlRun({ source, scope }) {
        if (!source || typeof source !== 'string') {
            throw new Error('Crawl source is required.');
        }

        if (!scope || typeof scope !== 'string') {
            throw new Error('Crawl scope is required.');
        }

        const runId = randomUUID();
        const startedAt = new Date().toISOString();

        statements.createRun.run(
            runId,
            source,
            scope,
            startedAt
        );

        console.log('\n========== CRAWL SESSION STARTED ==========');
        console.log({
            runId,
            source,
            scope,
            startedAt,
        });

        return runId;
    }

    function finishCrawlRun({
        runId,
        status = 'completed',
        pagesDiscovered = 0,
        pagesFetched = 0,
        jobsFound = 0,
        isFullCrawl = false,
        error = null,
    }) {
        if (!runId) {
            throw new Error('runId is required.');
        }

        if (!['completed', 'failed'].includes(status)) {
            throw new Error(`Invalid crawl status: ${status}`);
        }

        const run = statements.getRun.get(runId);

        if (!run) {
            throw new Error(`Crawl run not found: ${runId}`);
        }

        if (run.status !== 'running') {
            throw new Error(
                `Crawl run is already finished: ${runId}`
            );
        }

        const finishedAt = new Date().toISOString();

        // A failed run can never be considered a full crawl.
        const fullCrawl =
            status === 'completed' &&
            isFullCrawl === true;

        const result = statements.finishRun.run(
            status,
            finishedAt,
            pagesDiscovered,
            pagesFetched,
            jobsFound,
            fullCrawl ? 1 : 0,
            error,
            runId
        );

        if (result.changes !== 1) {
            throw new Error(
                `Could not finish crawl run: ${runId}`
            );
        }

        console.log('\n========== CRAWL SESSION FINISHED ==========');
        console.log({
            runId,
            status,
            pagesDiscovered,
            pagesFetched,
            jobsFound,
            isFullCrawl: fullCrawl,
            error,
        });

        return statements.getRun.get(runId);
    }

    function failCrawlRun({ runId, error }) {
        return finishCrawlRun({
            runId,
            status: 'failed',
            error: error?.message ?? String(error),
        });
    }

    function getCrawlRun(runId) {
        return statements.getRun.get(runId) ?? null;
    }

    function getRecentCrawlRuns(limit = 20) {
        return statements.getRuns.all(limit);
    }


    // =====================================================
    // 5. JOB STATUS MANAGEMENT
    // =====================================================

    function updateJobStatus({
        source,
        externalId,
        status,
    }) {
        const allowedStatuses = [
            'active',
            'possibly_inactive',
            'expired',
            'closed',
        ];

        if (!allowedStatuses.includes(status)) {
            throw new Error(`Invalid job status: ${status}`);
        }

        const result = db.prepare(`
            UPDATE career_jobs
            SET status = ?
            WHERE source = ? AND external_id = ?
        `).run(status, source, externalId);

        return result.changes > 0;
    }

    function getJobsByStatus({
        source = null,
        status = 'active',
        limit = 100,
    } = {}) {
        if (source) {
            return db.prepare(`
                SELECT *
                FROM career_jobs
                WHERE source = ? AND status = ?
                ORDER BY last_seen_at DESC
                LIMIT ?
            `).all(source, status, limit);
        }

        return db.prepare(`
            SELECT *
            FROM career_jobs
            WHERE status = ?
            ORDER BY last_seen_at DESC
            LIMIT ?
        `).all(status, limit);
    }

    // =====================================================
    // 5.1 JOBS BY CRAWL SCOPE
    // =====================================================

    function getJobsByScope({
        source,
        scope,
        limit = 1000,
    }) {
        if (!source || !scope) {
            throw new Error('Source and scope are required.');
        }

        return db.prepare(`
            SELECT
                j.source,
                j.external_id AS externalId,
                j.title,
                j.payload,
                s.crawl_scope AS crawlScope,
                s.status,
                s.last_seen_at AS lastSeenAt,
                s.last_seen_run_id AS lastSeenRunId,
                s.missing_full_runs AS missingFullRuns
            FROM career_job_scopes s
            JOIN career_jobs j
                ON j.source = s.source
                AND j.external_id = s.external_id
            WHERE s.source = ?
                AND s.crawl_scope = ?
            ORDER BY s.last_seen_at DESC
            LIMIT ?
        `).all(source, scope, limit);
    }

    // =====================================================
    // 5.2 REFRESH GLOBAL JOB STATUS
    // =====================================================

    function refreshGlobalJobStatus({
        source,
        externalId,
    }) {
        if (!source || !externalId) {
            throw new Error('Source and externalId are required.');
        }

        const job = db.prepare(`
            SELECT status
            FROM career_jobs
            WHERE source = ? AND external_id = ?
        `).get(source, externalId);

        if (!job) {
            return false;
        }

        // Never automatically overwrite confirmed terminal states.
        if (['closed', 'expired'].includes(job.status)) {
            return false;
        }

        const scopeStats = db.prepare(`
            SELECT
                COUNT(*) AS totalScopes,
                SUM(
                    CASE WHEN status = 'active'
                    THEN 1 ELSE 0 END
                ) AS activeScopes
            FROM career_job_scopes
            WHERE source = ? AND external_id = ?
        `).get(source, externalId);

        // Legacy jobs without scope records are left untouched.
        if (scopeStats.totalScopes === 0) {
            return false;
        }

        const globalStatus =
            scopeStats.activeScopes > 0
                ? 'active'
                : 'possibly_inactive';

        db.prepare(`
            UPDATE career_jobs
            SET status = ?
            WHERE source = ? AND external_id = ?
        `).run(globalStatus, source, externalId);

        return true;
    }

    // =====================================================
    // 5.3 RECONCILE SCOPE LIFECYCLE
    // =====================================================

    function reconcileScopeLifecycle({
        runId,
        observedJobs = [],
    }) {
        if (!runId) {
            throw new Error('runId is required.');
        }

        const run = statements.getRun.get(runId);

        if (!run) {
            throw new Error(`Crawl run not found: ${runId}`);
        }

        if (!run.crawl_scope) {
            throw new Error(`Crawl run has no scope: ${runId}`);
        }

        // Early check for skippable runs (partial/failed) outside transaction
        // This avoids unnecessary transaction overhead
        const shouldSkipRun = run.status !== 'completed' || run.is_full_crawl !== 1;

        if (shouldSkipRun) {
            return {
                skipped: true,
                reason: `Skipping: status=${run.status}, isFullCrawl=${run.is_full_crawl}`,
                possiblyInactive: [],
                reactivated: [],
                unchanged: [],
            };
        }

        // Transaction-safe idempotency:
        // 1. Atomically claim the run (UPDATE with WHERE lifecycle_reconciled = 0)
        // 2. If claim succeeds, read existingJobs INSIDE transaction
        // 3. Compute reconciliation with fresh data
        // 4. Apply updates
        // 5. Commit
        const saveLifecycleChanges = db.transaction(() => {
            // Atomically mark run as reconciled
            // This serves as a distributed lock
            const markResult = db.prepare(`
                UPDATE crawl_runs
                SET lifecycle_reconciled = 1
                WHERE run_id = ?
                  AND lifecycle_reconciled = 0
            `).run(runId);

            // If no rows were updated, reconciliation already happened
            if (markResult.changes === 0) {
                return {
                    alreadyReconciled: true,
                    reconciliation: null,
                };
            }

            // Reconciliation claimed successfully
            // Now read existingJobs INSIDE transaction to get consistent snapshot
            // ORDER BY ensures deterministic processing order for batch updates
            const existingJobs = db.prepare(`
                SELECT
                    source,
                    external_id AS externalId,
                    crawl_scope AS crawlScope,
                    status
                FROM career_job_scopes
                WHERE source = ? AND crawl_scope = ?
                ORDER BY external_id
            `).all(run.source, run.crawl_scope);

            // Compute reconciliation with fresh data
            const reconciliation = reconcileJobLifecycle({
                existingJobs,
                observedJobs,
                runStatus: run.status,
                isFullCrawl: run.is_full_crawl === 1,
                source: run.source,
                scope: run.crawl_scope,
            });

            // Defensive check: if reconciliation should skip after claiming,
            // we must rollback the marker to allow future reconciliation
            if (reconciliation.skipped) {
                // Rollback the marker - this is critical for correctness
                db.prepare(`
                    UPDATE crawl_runs
                    SET lifecycle_reconciled = 0
                    WHERE run_id = ?
                `).run(runId);

                return {
                    alreadyReconciled: false,
                    reconciliation,
                };
            }

            const affectedJobs = [
                ...reconciliation.possiblyInactive,
                ...reconciliation.reactivated,
            ];

            // Apply updates in deterministic order (already sorted by ORDER BY)
            const updateScopeStatus = db.prepare(`
                UPDATE career_job_scopes
                SET
                    status = ?,
                    missing_full_runs =
                        CASE
                            WHEN ? = 'active' THEN 0
                            ELSE missing_full_runs + 1
                        END
                WHERE source = ?
                    AND external_id = ?
                    AND crawl_scope = ?
            `);

            for (const item of affectedJobs) {
                updateScopeStatus.run(
                    item.status,
                    item.status,
                    item.source,
                    item.externalId,
                    item.crawlScope
                );

                refreshGlobalJobStatus({
                    source: item.source,
                    externalId: item.externalId,
                });
            }

            return {
                alreadyReconciled: false,
                reconciliation,
            };
        });

        const result = saveLifecycleChanges();

        // If another process/thread already reconciled this run
        if (result.alreadyReconciled) {
            console.log(`\n⚠ Reconciliation already performed for run ${runId}`);
            return {
                skipped: true,
                reason: 'Run has already been reconciled.',
                possiblyInactive: [],
                reactivated: [],
                unchanged: [],
            };
        }

        return result.reconciliation;
    }


    // =====================================================
    // 6. DATABASE UTILITIES
    // =====================================================

    function getStats() {
        const jobs = db.prepare(`
            SELECT status, COUNT(*) AS count
            FROM career_jobs
            GROUP BY status
        `).all();

        const runs = db.prepare(`
            SELECT status, COUNT(*) AS count
            FROM crawl_runs
            GROUP BY status
        `).all();

        return {
            jobs,
            runs,
            totalJobs: db.prepare(`
                SELECT COUNT(*) AS count
                FROM career_jobs
            `).get().count,
            totalRuns: db.prepare(`
                SELECT COUNT(*) AS count
                FROM crawl_runs
            `).get().count,
        };
    }

    function close() {
        if (db.open) {
            db.close();
        }
    }

    // =====================================================
    // 7. PUBLIC STORE API
    // =====================================================

    return {
        // Jobs
        loadAllJobs,
        getJob,
        saveClassifiedJobs,

        // Crawl sessions
        startCrawlRun,
        finishCrawlRun,
        failCrawlRun,
        getCrawlRun,
        getRecentCrawlRuns,

        // Job statuses
        updateJobStatus,
        getJobsByStatus,
        getJobsByScope,
        refreshGlobalJobStatus,
        reconcileScopeLifecycle,

        // Statistics
        getStats,

        // Database
        close,
    };
}
