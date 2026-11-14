
const SOURCE = 'topcv';

function cleanString(value) {
    if (typeof value !== 'string') return null;

    const cleaned = value.replace(/\s+/g, ' ').trim();

    return cleaned.length > 0 ? cleaned : null;
}


function normalizeUrl(value) {
    const cleaned = cleanString(value);

    if (!cleaned) return null;

    try {
        const url = new URL(cleaned);

        if (!['http:', 'https:'].includes(url.protocol)) {
            return null;
        }

        // Loại bỏ tracking parameters
        const trackingParams = [
            'ta_source',
            'u_sr_id',
        ];

        for (const param of trackingParams) {
            url.searchParams.delete(param);
        }

        // Loại bỏ các tham số UTM
        for (const key of [...url.searchParams.keys()]) {
            if (key.toLowerCase().startsWith('utm_')) {
                url.searchParams.delete(key);
            }
        }

        // Không lưu fragment
        url.hash = '';

        return url.href;
    } catch {
        return null;
    }
}


function normalizeTags(tags) {
    if (!Array.isArray(tags)) return [];

    return [
        ...new Set(
            tags
                .map(cleanString)
                .filter(Boolean)
        ),
    ];
}

/**
 * Chuẩn hóa một job lấy từ TopCV.
 *
 * Không tự suy diễn mức lương, kinh nghiệm hoặc ngày đăng.
 * Các giá trị chưa thể chuẩn hóa được giữ nguyên dưới dạng raw text.
 */
export function normalizeTopcvJob(job) {
    if (!job || typeof job !== 'object') {
        throw new Error('Invalid TopCV job: expected an object.');
    }

    const externalId = cleanString(job.externalId);
    const title = cleanString(job.title);

    if (!externalId) {
        throw new Error('Invalid TopCV job: missing externalId.');
    }

    if (!title) {
        throw new Error(
            `Invalid TopCV job ${externalId}: missing title.`
        );
    }

    return {
        source: SOURCE,
        externalId,

        type: 'job',

        title,

        url: normalizeUrl(job.url),

        company: {
            name: cleanString(job.company?.name),
            url: normalizeUrl(job.company?.url),
            logo: normalizeUrl(job.company?.logo),
        },

        salary: {
            raw: cleanString(job.salary),
            min: null,
            max: null,
            currency: null,
            unit: null,
        },

        location: {
            raw: cleanString(job.location),
        },

        experience: {
            raw: cleanString(job.experience),
        },

        tags: normalizeTags(job.tags),

        remainingTags: cleanString(job.remainingTags),

        published: {
            raw: cleanString(job.publishedText),
            publishedAt: null,
        },
    };
}

/**
 * Chuẩn hóa danh sách job.
 * Trả về danh sách hợp lệ và lỗi của từng bản ghi.
 */
export function normalizeTopcvJobs(jobs) {
    if (!Array.isArray(jobs)) {
        throw new Error('Expected jobs to be an array.');
    }

    const normalized = [];
    const errors = [];

    jobs.forEach((job, index) => {
        try {
            normalized.push(normalizeTopcvJob(job));
        } catch (error) {
            errors.push({
                index,
                externalId: job?.externalId ?? null,
                message: error.message,
            });
        }
    });

    return {
        total: jobs.length,
        success: normalized.length,
        failed: errors.length,
        jobs: normalized,
        errors,
    };
}
