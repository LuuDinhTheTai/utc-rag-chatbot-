
import { crawlTopcvCategory } from '../sources/topcv.source.js';

import {
    normalizeTopcvJobs,
} from '../normalizers/topcv-job.normalizer.js';

import {
    deduplicateJobs,
} from '../normalizers/job-deduplicator.js';

import {
    createCareerStore,
} from '../storage/sqlite.store.js';

import {
    createClientFromEnv,
} from '../api-client/career-api.client.js';

/**
 * TopCV pipeline:
 *
 * Start Session
 *     |
 * Crawl -> Parse
 *     |
 * Normalize
 *     |
 * Load Database
 *     |
 * Deduplicate
 *     |
 * Save Jobs (SQLite)
 *     |
 * Submit to Backend API (optional)
 *     |
 * Finish Session
 *
 * Nếu có lỗi ở bất kỳ bước nào, session sẽ được đánh dấu failed.
 */
export async function runTopcvPipeline({
    categoryUrl,
    maxPages = null,
    delayMs = 5000,
    timeoutMs = 20000,
    store: externalStore = null,
    submitToApi = false,  // New option: enable API submission
}) {
    console.log('\n========== TOPCV PIPELINE START ==========');

    const store = externalStore ?? createCareerStore();
    const shouldCloseStore = !externalStore;

    let runId = null;

    try {
        // ================================================
        // 1. START CRAWL SESSION
        // ================================================

        console.log('\n[1/5] Starting crawl session...');

        runId = store.startCrawlRun({
            source: 'topcv',
            scope: categoryUrl,
        });

        // ================================================
        // 2. CRAWL AND PARSE
        // ================================================

        console.log('\n[2/5] Crawling TopCV...');

        const crawlResult = await crawlTopcvCategory({
            categoryUrl,
            maxPages,
            delayMs,
            timeoutMs,
        });

        // ================================================
        // 3. NORMALIZE
        // ================================================

        console.log('\n[3/5] Normalizing jobs...');

        const normalization = normalizeTopcvJobs(
            crawlResult.jobs
        );

        // ================================================
        // 4. LOAD DATABASE AND DEDUPLICATE
        // ================================================

        console.log('\n[4/5] Loading database and deduplicating...');

        const existingJobs = store.loadAllJobs();

        const deduplication = deduplicateJobs({
            existingJobs,
            incomingJobs: normalization.jobs,
        });

        // ================================================
        // 5. SAVE JOBS
        // ================================================

        console.log('\n[5/5] Saving jobs to SQLite...');

        store.saveClassifiedJobs({
            new: deduplication.new,
            updated: deduplication.updated,
            unchanged: deduplication.unchanged,
            runId,
        });

        // ================================================
        // 6. SUBMIT TO BACKEND API (OPTIONAL)
        // ================================================

        let apiSubmission = null;

        if (submitToApi) {
            console.log('\n[6/6] Submitting jobs to backend API...');

            try {
                const apiClient = createClientFromEnv();

                // Check backend health first
                await apiClient.checkHealth();

                // Submit all normalized jobs (new, updated, unchanged)
                // Backend will handle deduplication and change detection
                const jobsToSubmit = normalization.jobs;

                console.log(`Submitting ${jobsToSubmit.length} jobs to backend...`);

                apiSubmission = await apiClient.submitJobs(jobsToSubmit);

                console.log('API Submission Summary:', apiSubmission.summary);

                // Print detailed stats
                apiClient.printStats();

            } catch (apiError) {
                console.error('❌ API submission failed:', apiError.message);
                console.error('Pipeline will continue (SQLite data is safe)');

                // Store error but don't fail the pipeline
                apiSubmission = {
                    error: apiError.message,
                    summary: { created: 0, updated: 0, unchanged: 0, rejected: jobsToSubmit.length }
                };
            }
        } else {
            console.log('\n[6/6] Skipping API submission (submitToApi=false)');
            console.log('To enable: set submitToApi=true or CAREER_API_ENABLED=true');
        }

        // ================================================
        // 7. DETERMINE CRAWL COMPLETENESS
        // ================================================

        const isFullCrawl =
            crawlResult.totalPagesDiscovered > 0 &&
            crawlResult.pagesFetched === crawlResult.totalPagesDiscovered &&
            normalization.failed === 0;
        // ================================================
        // 8. FINISH CRAWL SESSION
        // ================================================

        const session = store.finishCrawlRun({
            runId,
            status: 'completed',

            pagesDiscovered: crawlResult.totalPagesDiscovered,
            pagesFetched: crawlResult.pagesFetched,
            jobsFound: crawlResult.totalJobs,

            isFullCrawl,
        });

        console.log('\n[9/10] Reconciling job lifecycle...');

        let lifecycle;

        if (session.status === 'completed' && session.is_full_crawl === 1) {
            lifecycle = store.reconcileScopeLifecycle({
                runId,
                observedJobs: normalization.jobs,
            });
        } else {
            lifecycle = {
                skipped: true,
                reason: 'Crawl was not a completed full crawl.',
                possiblyInactive: [],
                reactivated: [],
                unchanged: [],
            };
        }

        console.log('\n========== JOB LIFECYCLE RESULT ==========');
        console.log(lifecycle.summary ?? {
            skipped: lifecycle.skipped,
            reason: lifecycle.reason,
        });

        // ================================================
        // 9. BUILD RESULT
        // ================================================

        const result = {
            source: 'topcv',

            session: {
                runId: session.run_id,
                status: session.status,
                isFullCrawl: Boolean(session.is_full_crawl),
                startedAt: session.started_at,
                finishedAt: session.finished_at,
            },

            crawl: {
                totalPagesDiscovered: crawlResult.totalPagesDiscovered,
                pagesFetched: crawlResult.pagesFetched,
                totalJobs: crawlResult.totalJobs,
            },

            normalization: {
                total: normalization.total,
                success: normalization.success,
                failed: normalization.failed,
                errors: normalization.errors,
            },

            deduplication: deduplication.summary,

            apiSubmission: apiSubmission ? {
                enabled: true,
                error: apiSubmission.error ?? null,
                summary: apiSubmission.summary,
            } : {
                enabled: false,
                error: null,
                summary: null,
            },

            lifecycle: {
                skipped: lifecycle.skipped,
                reason: lifecycle.reason,
                summary: lifecycle.summary ?? {
                    possiblyInactive: 0,
                    reactivated: 0,
                    unchanged: 0,
                },
            },

            jobs: {
                new: deduplication.new,
                unchanged: deduplication.unchanged,
                updated: deduplication.updated,
                duplicatesInBatch: deduplication.duplicatesInBatch,
            },

            normalizedJobs: normalization.jobs,
        };

        // ================================================
        // 10. SUMMARY
        // ================================================

        console.log('\n========== TOPCV PIPELINE SUMMARY ==========');

        console.log({
            runId: result.session.runId,
            sessionStatus: result.session.status,
            isFullCrawl: result.session.isFullCrawl,

            pagesFetched: result.crawl.pagesFetched,
            pagesDiscovered: result.crawl.totalPagesDiscovered,
            crawledJobs: result.crawl.totalJobs,

            normalized: result.normalization.success,
            normalizationFailed: result.normalization.failed,

            new: result.deduplication.new,
            unchanged: result.deduplication.unchanged,
            updated: result.deduplication.updated,
            duplicatesInBatch: result.deduplication.duplicatesInBatch,

            apiSubmissionEnabled: result.apiSubmission.enabled,
            apiSubmissionError: result.apiSubmission.error,
            apiCreated: result.apiSubmission.summary?.created ?? 0,
            apiUpdated: result.apiSubmission.summary?.updated ?? 0,
            apiUnchanged: result.apiSubmission.summary?.unchanged ?? 0,
            apiRejected: result.apiSubmission.summary?.rejected ?? 0,

            lifecycleSkipped: result.lifecycle.skipped,
            possiblyInactive: result.lifecycle.summary.possiblyInactive,
            reactivated: result.lifecycle.summary.reactivated,
            lifecycleUnchanged: result.lifecycle.summary.unchanged,
        });

        console.log('\n========== TOPCV PIPELINE FINISHED ==========');

        return result;

    } catch (error) {
        // ================================================
        // ERROR HANDLING
        // ================================================

        console.error('\n========== TOPCV PIPELINE ERROR ==========');
        console.error(error);

        if (runId) {
            try {
                const currentRun = store.getCrawlRun(runId);

                if (currentRun?.status === 'running') {
                    store.failCrawlRun({
                        runId,
                        error,
                    });
                }
            } catch (sessionError) {
                console.error(
                    'Failed to update crawl session:',
                    sessionError
                );
            }
        }

        throw error;

    } finally {
        if (shouldCloseStore) {
            store.close();
        }
    }
}
