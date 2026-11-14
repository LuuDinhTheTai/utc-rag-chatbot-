#!/usr/bin/env node

/**
 * Scheduler để crawl nhiều ngành nghề
 *
 * Usage:
 *   node scheduler.js                          # Crawl tất cả ngành (sequential)
 *   node scheduler.js --top 5                  # Crawl top 5 ngành ưu tiên cao
 *   node scheduler.js --categories cntt marketing  # Crawl specific categories
 *   node scheduler.js --parallel               # Crawl song song (cẩn thận với rate limit!)
 *   node scheduler.js --pages 10 --submit      # Crawl 10 trang/ngành và submit vào backend
 */

import { runTopcvPipeline } from './src/pipelines/topcv.pipeline.js';
import { createCareerStore } from './src/storage/sqlite.store.js';
import {
    getAllCategories,
    getTopCategories,
    getCategoryById
} from './categories.js';
import dotenv from 'dotenv';

dotenv.config();

// Parse arguments
const args = process.argv.slice(2);
const getArg = (name, defaultValue) => {
    const index = args.indexOf(`--${name}`);
    if (index === -1) return defaultValue;
    const value = args[index + 1];
    return value !== undefined ? parseInt(value, 10) : defaultValue;
};
const hasFlag = (name) => args.includes(`--${name}`);
const getMultiArg = (name) => {
    const index = args.indexOf(`--${name}`);
    if (index === -1) return null;
    const values = [];
    for (let i = index + 1; i < args.length; i++) {
        if (args[i].startsWith('--')) break;
        values.push(args[i]);
    }
    return values.length > 0 ? values : null;
};

// Configuration
const config = {
    maxPages: getArg('pages', parseInt(process.env.MAX_PAGES || '5', 10)),
    delayMs: parseInt(process.env.CRAWL_DELAY_MS || '8000', 10),
    timeoutMs: parseInt(process.env.CRAWL_TIMEOUT_MS || '20000', 10),
    submitToApi: hasFlag('submit') || process.env.SUBMIT_TO_API === 'true',
    parallel: hasFlag('parallel'),

    // Category selection
    topN: getArg('top', null),
    categoryIds: getMultiArg('categories'),
};

// Determine which categories to crawl
let categories;
if (config.categoryIds) {
    // Specific categories
    categories = config.categoryIds.map(id => getCategoryById(id)).filter(Boolean);
    if (categories.length === 0) {
        console.error('❌ No valid categories found!');
        console.error('Available categories:', getAllCategories().map(c => c.id).join(', '));
        process.exit(1);
    }
} else if (config.topN) {
    // Top N categories
    categories = getTopCategories(config.topN);
} else {
    // All categories
    categories = getAllCategories();
}

console.log('\n🚀 UTC CAREER DATA SCHEDULER');
console.log('═'.repeat(60));
console.log(`📂 Categories: ${categories.length}`);
console.log(`📄 Pages per category: ${config.maxPages}`);
console.log(`⏱️  Delay: ${config.delayMs}ms`);
console.log(`🔌 Submit to API: ${config.submitToApi ? 'YES' : 'NO'}`);
console.log(`🔄 Mode: ${config.parallel ? 'PARALLEL' : 'SEQUENTIAL'}`);
console.log('═'.repeat(60));
console.log('\n📋 Categories to crawl:');
categories.forEach((cat, i) => {
    console.log(`   ${i + 1}. [${cat.id}] ${cat.name}`);
});
console.log('');

// Estimate time
const estimatedMinutesPerCategory = Math.ceil((config.maxPages * config.delayMs) / 60000);
const totalEstimatedMinutes = config.parallel
    ? estimatedMinutesPerCategory
    : estimatedMinutesPerCategory * categories.length;

console.log(`⏰ Estimated time: ~${totalEstimatedMinutes} minutes`);
console.log('');

// Shared store for all pipelines
const store = createCareerStore();

/**
 * Crawl một category
 */
async function crawlCategory(category, index, total) {
    console.log(`\n${'='.repeat(60)}`);
    console.log(`🔍 [${index + 1}/${total}] Crawling: ${category.name}`);
    console.log(`${'='.repeat(60)}\n`);

    try {
        const result = await runTopcvPipeline({
            categoryUrl: category.url,
            maxPages: config.maxPages,
            delayMs: config.delayMs,
            timeoutMs: config.timeoutMs,
            store: store,
            submitToApi: config.submitToApi,
        });

        return {
            category: category,
            success: true,
            result: result,
        };

    } catch (error) {
        console.error(`\n❌ Failed to crawl ${category.name}:`, error.message);

        return {
            category: category,
            success: false,
            error: error.message,
        };
    }
}

/**
 * Main execution
 */
async function main() {
    const startTime = Date.now();
    let results;

    try {
        if (config.parallel) {
            // Parallel crawling (cẩn thận với rate limit!)
            console.log('⚠️  WARNING: Parallel crawling may trigger rate limits!');
            console.log('');

            results = await Promise.all(
                categories.map((cat, i) => crawlCategory(cat, i, categories.length))
            );

        } else {
            // Sequential crawling (an toàn hơn)
            results = [];

            for (let i = 0; i < categories.length; i++) {
                const result = await crawlCategory(categories[i], i, categories.length);
                results.push(result);

                // Delay between categories (thêm thời gian nghỉ giữa các ngành)
                if (i < categories.length - 1) {
                    const categoryDelay = 10000; // 10s giữa các ngành
                    console.log(`\n⏸️  Waiting ${categoryDelay / 1000}s before next category...\n`);
                    await new Promise(resolve => setTimeout(resolve, categoryDelay));
                }
            }
        }

    } finally {
        store.close();
    }

    const endTime = Date.now();
    const totalMinutes = Math.ceil((endTime - startTime) / 60000);

    // Summary
    console.log('\n' + '═'.repeat(60));
    console.log('📊 FINAL SUMMARY');
    console.log('═'.repeat(60));

    const successful = results.filter(r => r.success);
    const failed = results.filter(r => !r.success);

    console.log(`\n✅ Success: ${successful.length}/${categories.length}`);
    console.log(`❌ Failed: ${failed.length}/${categories.length}`);
    console.log(`⏱️  Total time: ${totalMinutes} minutes`);

    if (successful.length > 0) {
        console.log('\n📈 Crawl Statistics:');

        let totalJobs = 0;
        let totalNew = 0;
        let totalUpdated = 0;
        let totalUnchanged = 0;
        let totalApiCreated = 0;
        let totalApiUpdated = 0;

        successful.forEach(({ category, result }) => {
            totalJobs += result.crawl.totalJobs;
            totalNew += result.deduplication.new;
            totalUpdated += result.deduplication.updated;
            totalUnchanged += result.deduplication.unchanged;

            if (result.apiSubmission?.enabled && !result.apiSubmission.error) {
                totalApiCreated += result.apiSubmission.summary.created || 0;
                totalApiUpdated += result.apiSubmission.summary.updated || 0;
            }
        });

        console.log(`   ├─ Total jobs crawled: ${totalJobs}`);
        console.log(`   ├─ New jobs: ${totalNew}`);
        console.log(`   ├─ Updated jobs: ${totalUpdated}`);
        console.log(`   └─ Unchanged jobs: ${totalUnchanged}`);

        if (config.submitToApi) {
            console.log(`\n🔌 API Submission:`);
            console.log(`   ├─ Created: ${totalApiCreated}`);
            console.log(`   └─ Updated: ${totalApiUpdated}`);
        }

        console.log('\n✅ Successful categories:');
        successful.forEach(({ category, result }) => {
            console.log(`   ├─ [${category.id}] ${category.name}: ${result.crawl.totalJobs} jobs`);
        });
    }

    if (failed.length > 0) {
        console.log('\n❌ Failed categories:');
        failed.forEach(({ category, error }) => {
            console.log(`   ├─ [${category.id}] ${category.name}: ${error}`);
        });
    }

    console.log('\n' + '═'.repeat(60));
    console.log('✨ Scheduler finished!');

    if (successful.length > 0) {
        console.log('\n💡 Next steps:');
        console.log('   1. Check database: sqlite3 career-data.db "SELECT COUNT(*) FROM career_jobs;"');
        console.log('   2. Index to RAG:');
        console.log('      cd ../backend');
        console.log('      .venv\\Scripts\\activate');
        console.log('      python scripts/index_career_data.py');
    }

    console.log('');

    process.exit(failed.length > 0 ? 1 : 0);
}

main().catch(err => {
    console.error('\n❌ Scheduler error:', err);
    store.close();
    process.exit(1);
});
