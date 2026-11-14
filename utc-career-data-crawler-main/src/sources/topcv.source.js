
import { gotScraping } from 'got-scraping';
import * as cheerio from 'cheerio';

import { parseTopcvJobs } from '../parsers/topcv-job.parser.js';

const DEFAULT_TIMEOUT_MS = 20000;
const DEFAULT_DELAY_MS = 5000;

// Nghỉ giữa các request
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// Tạo URL cho từng trang
function buildPageUrl(categoryUrl, page) {
    const url = new URL(categoryUrl);

    url.searchParams.delete('page');

    if (page > 1) {
        url.searchParams.set('page', String(page));
    }

    return url.toString();
}

// Đọc tổng số trang từ HTML
function extractTotalPages($) {
    const paginationText = $('#job-listing-paginate-text')
        .text()
        .replace(/\s+/g, ' ')
        .trim();

    // Ví dụ: "1 / 52 trang"
    const match = paginationText.match(/\/\s*(\d+)\s*trang/i);

    if (match) {
        return Number(match[1]);
    }

    // Fallback: tìm số trang trong các liên kết phân trang
    const pageNumbers = [];

    $('nav.box-pagination a').each((_, element) => {
        const href = $(element).attr('data-href')
            || $(element).attr('href');

        if (!href) return;

        try {
            const url = new URL(href, 'https://www.topcv.vn');
            const page = Number(url.searchParams.get('page'));

            if (Number.isInteger(page) && page > 0) {
                pageNumbers.push(page);
            }
        } catch {
            // Bỏ qua URL không hợp lệ
        }
    });

    if (pageNumbers.length > 0) {
        return Math.max(...pageNumbers);
    }

    // Danh mục chỉ có một trang
    if (/1\s*trang/i.test(paginationText)) {
        return 1;
    }

    throw new Error(
        `Cannot determine total pages. Pagination text: "${paginationText}"`
    );
}

// Kiểm tra response trước khi parse
function validateResponse(response, page) {
    const status = response.statusCode;

    if (status === 403) {
        throw new Error(
            `TopCV denied access to page ${page} (HTTP 403). ` +
            'Stopping crawl. Check access permissions and site restrictions.'
        );
    }

    if (status === 429) {
        throw new Error(
            `TopCV rate-limited page ${page} (HTTP 429). ` +
            'Stopping crawl. Reduce request frequency and respect Retry-After.'
        );
    }

    if (status !== 200) {
        throw new Error(
            `Unexpected HTTP status ${status} on page ${page}.`
        );
    }

    const contentType = response.headers['content-type'] || '';

    if (!contentType.includes('text/html')) {
        throw new Error(
            `Unexpected Content-Type on page ${page}: ${contentType}`
        );
    }
}

// Tải một trang
async function fetchPage(categoryUrl, page, timeoutMs) {
    const url = buildPageUrl(categoryUrl, page);

    console.log(`Requesting page ${page}: ${url}`);

    const response = await gotScraping({
        url,
        method: 'GET',
        timeout: {
            request: timeoutMs,
        },
        retry: {
            limit: 0,
        },
        throwHttpErrors: false,
    });

    validateResponse(response, page);

    const html = response.body;
    const $ = cheerio.load(html);
    const cardCount = $('.job-item-search-result').length;

    if (cardCount === 0) {
        throw new Error(
            `Page ${page} returned HTTP 200 but contains no job cards.`
        );
    }

    return {
        page,
        url: response.url,
        html,
        cardCount,
    };
}

// Thống kê ID trùng, không xóa dữ liệu
function analyzeDuplicates(pages) {
    const occurrences = new Map();

    for (const pageData of pages) {
        pageData.jobs.forEach((job, index) => {
            if (!job.externalId) return;

            if (!occurrences.has(job.externalId)) {
                occurrences.set(job.externalId, []);
            }

            occurrences.get(job.externalId).push({
                page: pageData.page,
                position: index + 1,
            });
        });
    }

    const duplicates = [];

    for (const [id, locations] of occurrences) {
        if (locations.length > 1) {
            duplicates.push({
                id,
                occurrences: locations,
            });
        }
    }

    return {
        uniqueIds: occurrences.size,
        duplicates,
    };
}

/**
 * Crawl một danh mục việc làm TopCV.
 *
 * @param {Object} options
 * @param {string} options.categoryUrl URL danh mục TopCV
 * @param {number|null} options.maxPages Giới hạn số trang, null = tất cả
 * @param {number} options.delayMs Khoảng nghỉ giữa các request
 * @param {number} options.timeoutMs Timeout mỗi request
 */
export async function crawlTopcvCategory({
    categoryUrl,
    maxPages = null,
    delayMs = DEFAULT_DELAY_MS,
    timeoutMs = DEFAULT_TIMEOUT_MS,
}) {
    if (!categoryUrl) {
        throw new Error('categoryUrl is required.');
    }

    if (maxPages !== null &&
        (!Number.isInteger(maxPages) || maxPages < 1)) {
        throw new Error('maxPages must be a positive integer or null.');
    }

    if (!Number.isFinite(delayMs) || delayMs < 0) {
        throw new Error('delayMs must be a non-negative number.');
    }

    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
        throw new Error('timeoutMs must be a positive number.');
    }

    const parsedUrl = new URL(categoryUrl);

    if (parsedUrl.hostname !== 'www.topcv.vn') {
        throw new Error('Only www.topcv.vn URLs are supported.');
    }

    const pages = [];

    // 1. Tải trang đầu tiên
    const firstPage = await fetchPage(
        categoryUrl,
        1,
        timeoutMs
    );

    const $firstPage = cheerio.load(firstPage.html);

    // 2. Đọc tổng số trang
    const totalPages = extractTotalPages($firstPage);

    const pagesToFetch = maxPages === null
        ? totalPages
        : Math.min(totalPages, maxPages);

    console.log('\n========== CRAWL CONFIG ==========');
    console.log('Category:', categoryUrl);
    console.log('Total pages discovered:', totalPages);
    console.log('Pages to fetch:', pagesToFetch);
    console.log('Delay:', delayMs, 'ms');

    // 3. Parse trang đầu tiên
    firstPage.jobs = parseTopcvJobs(firstPage.html);

    pages.push(firstPage);

    console.log(
        `Page 1: ${firstPage.jobs.length} jobs parsed`
    );

    // 4. Crawl các trang còn lại
    for (let page = 2; page <= pagesToFetch; page++) {
        await sleep(delayMs);

        const pageData = await fetchPage(
            categoryUrl,
            page,
            timeoutMs
        );

        pageData.jobs = parseTopcvJobs(pageData.html);

        pages.push(pageData);

        console.log(
            `Page ${page}: ${pageData.jobs.length} jobs parsed`
        );
    }

    // 5. Tổng hợp dữ liệu
    const jobs = pages.flatMap(page => page.jobs);

    const validIds = jobs.filter(
        job => job.externalId
    ).length;

    const duplicateAnalysis = analyzeDuplicates(pages);

    return {
        source: 'topcv',
        categoryUrl,

        totalPagesDiscovered: totalPages,
        pagesRequested: pagesToFetch,
        pagesFetched: pages.length,

        totalJobs: jobs.length,
        validIds,
        missingIds: jobs.length - validIds,

        uniqueIds: duplicateAnalysis.uniqueIds,
        duplicateCount: duplicateAnalysis.duplicates.length,
        duplicates: duplicateAnalysis.duplicates,

        pages: pages.map(page => ({
            page: page.page,
            url: page.url,
            jobCount: page.jobs.length,
        })),

        // Giữ nguyên dữ liệu parse, chưa loại bỏ job trùng
        jobs,
    };
}
