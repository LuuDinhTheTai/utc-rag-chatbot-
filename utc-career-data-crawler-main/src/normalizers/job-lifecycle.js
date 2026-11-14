
/**
 * Job Lifecycle Manager
 *
 * Responsibilities:
 * - Detect jobs missing from a completed full crawl.
 * - Mark missing job-scope relationships as possibly_inactive.
 * - Reactivate job-scope relationships when jobs reappear.
 *
 * IMPORTANT:
 * - Reconciliation is isolated by source and crawl scope.
 * - This module only calculates scope-level status changes.
 * - Global job status is handled by SQLite Store.
 */

function getJobKey(job) {
    const source = job?.source;
    const externalId = job?.externalId ?? job?.external_id;

    if (!source || !externalId) {
        throw new Error(
            'Cannot identify job: source and externalId are required.'
        );
    }

    return `${source}:${externalId}`;
}

function getJobScope(job) {
    return job?.crawlScope ?? job?.crawl_scope;
}

export function reconcileJobLifecycle({
    existingJobs = [],
    observedJobs = [],
    runStatus,
    isFullCrawl,
    source,
    scope,
}) {
    // Never modify lifecycle states after partial or failed crawls.
    if (runStatus !== 'completed' || isFullCrawl !== true) {
        return {
            skipped: true,
            reason: 'Crawl was not a completed full crawl.',
            possiblyInactive: [],
            reactivated: [],
            unchanged: [],
        };
    }

    if (!source) {
        throw new Error('Source is required.');
    }

    if (!scope) {
        throw new Error('Crawl scope is required.');
    }

    const observedKeys = new Set();

    // Collect jobs observed in this crawl.
    for (const job of observedJobs) {
        if (job.source !== source) {
            throw new Error(
                `Observed job belongs to another source: ${job.source}`
            );
        }

        observedKeys.add(getJobKey(job));
    }

    const possiblyInactive = [];
    const reactivated = [];
    const unchanged = [];

    // Reconcile only existing relationships in this scope.
    for (const job of existingJobs) {
        const jobSource = job.source;
        const externalId = job.externalId ?? job.external_id;
        const jobScope = getJobScope(job);

        if (jobSource !== source) {
            throw new Error(
                `Existing job belongs to another source: ${jobSource}`
            );
        }

        if (jobScope !== scope) {
            throw new Error(
                `Existing job belongs to another scope: ${jobScope}`
            );
        }

        const key = getJobKey(job);
        const currentStatus = job.status ?? 'active';

        if (observedKeys.has(key)) {
            if (currentStatus === 'possibly_inactive') {
                reactivated.push({
                    source,
                    externalId,
                    crawlScope: scope,
                    previousStatus: currentStatus,
                    status: 'active',
                });
            } else {
                unchanged.push({
                    source,
                    externalId,
                    crawlScope: scope,
                    status: currentStatus,
                });
            }

            continue;
        }

        // Job is missing from this full crawl.
        // - active -> possibly_inactive (first miss)
        // - possibly_inactive -> possibly_inactive (subsequent misses)
        // Never automatically overwrite expired or closed.
        if (currentStatus === 'active' || currentStatus === 'possibly_inactive') {
            possiblyInactive.push({
                source,
                externalId,
                crawlScope: scope,
                previousStatus: currentStatus,
                status: 'possibly_inactive',
            });
        } else {
            unchanged.push({
                source,
                externalId,
                crawlScope: scope,
                status: currentStatus,
            });
        }
    }

    return {
        skipped: false,
        reason: null,
        possiblyInactive,
        reactivated,
        unchanged,

        summary: {
            source,
            scope,
            existing: existingJobs.length,
            observed: observedKeys.size,
            possiblyInactive: possiblyInactive.length,
            reactivated: reactivated.length,
            unchanged: unchanged.length,
        },
    };
}
