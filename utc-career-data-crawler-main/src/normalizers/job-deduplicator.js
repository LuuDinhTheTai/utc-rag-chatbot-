
import { createHash } from 'node:crypto';

function stableStringify(value) {
    if (Array.isArray(value)) {
        return `[${value.map(stableStringify).join(',')}]`;
    }

    if (value && typeof value === 'object') {
        const keys = Object.keys(value).sort();

        return `{${keys
            .map(key =>
                `${JSON.stringify(key)}:${stableStringify(value[key])}`
            )
            .join(',')}}`;
    }

    return JSON.stringify(value);
}

// Chỉ hash các trường phản ánh nội dung tuyển dụng
export function createJobContentHash(job) {
  // Chỉ hash nội dung thực sự của tin tuyển dụng.
  // Không đưa published.raw vào vì đây là thời gian tương đối.
  const content = {
    type: job.type,
    title: job.title,
    url: job.url,

    company: {
      name: job.company?.name ?? null,
      url: job.company?.url ?? null,
    },

    salary: job.salary ?? null,
    location: job.location ?? null,
    experience: job.experience ?? null,
    tags: job.tags ?? [],
    remainingTags: job.remainingTags ?? [],
  };

  return createHash('sha256')
    .update(JSON.stringify(content))
    .digest('hex');
}

function createIdentityKey(job) {
    if (!job?.source || !job?.externalId) {
        throw new Error(
            'Cannot identify job: source and externalId are required.'
        );
    }

    return `${job.source}:${job.externalId}`;
}

/**
 * Phân loại danh sách job mới so với dữ liệu đã có.
 *
 * existingJobs: danh sách job đã lưu trước đó.
 * incomingJobs: danh sách job vừa crawl và normalize.
 */
export function deduplicateJobs({
    existingJobs = [],
    incomingJobs = [],
}) {
    const existingMap = new Map();

    for (const job of existingJobs) {
        const key = createIdentityKey(job);

        existingMap.set(key, {
            job,
            hash: createJobContentHash(job),
        });
    }

    const seenIncoming = new Set();

    const result = {
        new: [],
        unchanged: [],
        updated: [],
        duplicatesInBatch: [],
    };

    for (const job of incomingJobs) {
        const key = createIdentityKey(job);

        // Trùng ngay trong cùng một batch crawl
        if (seenIncoming.has(key)) {
            result.duplicatesInBatch.push(job);
            continue;
        }

        seenIncoming.add(key);

        const existing = existingMap.get(key);

        if (!existing) {
            result.new.push({
                job,
                contentHash: createJobContentHash(job),
            });

            continue;
        }

        const newHash = createJobContentHash(job);

        if (existing.hash === newHash) {
            result.unchanged.push({
                job,
                contentHash: newHash,
            });
        } else {
            result.updated.push({
                job,
                previousHash: existing.hash,
                contentHash: newHash,
            });
        }
    }

    return {
        ...result,

        summary: {
            incoming: incomingJobs.length,
            new: result.new.length,
            unchanged: result.unchanged.length,
            updated: result.updated.length,
            duplicatesInBatch: result.duplicatesInBatch.length,
        },
    };
}
