/**
 * Career API Client - Submit job postings to Python backend
 *
 * Features:
 * - Batch job submission with configurable batch size
 * - Automatic retry with exponential backoff
 * - Request timeout handling
 * - Detailed logging and error reporting
 * - Statistics tracking (created/updated/unchanged/rejected)
 *
 * @module api-client/career-api.client
 */

/**
 * @typedef {Object} CareerJob
 * @property {string} source - Data source identifier (e.g., 'topcv')
 * @property {string} externalId - External job ID from source
 * @property {string} type - Job type (usually 'job')
 * @property {string} title - Job title
 * @property {string} url - Job posting URL
 * @property {Object} [company] - Company information
 * @property {string} [company.name] - Company name
 * @property {string} [company.url] - Company website
 * @property {string} [company.logo] - Company logo URL
 * @property {Object} [salary] - Salary information
 * @property {string} [salary.raw] - Raw salary text
 * @property {number} [salary.min] - Minimum salary
 * @property {number} [salary.max] - Maximum salary
 * @property {string} [salary.currency] - Currency code
 * @property {string} [salary.unit] - Salary unit (e.g., 'month')
 * @property {Object} [location] - Location information
 * @property {string} [location.raw] - Raw location text
 * @property {Object} [experience] - Experience requirement
 * @property {string} [experience.raw] - Raw experience text
 * @property {string[]} [tags] - Job tags/skills
 * @property {string|null} [remainingTags] - Additional tags as string
 * @property {Object} [published] - Publication information
 * @property {string} [published.raw] - Raw published text
 * @property {string} [published.publishedAt] - ISO timestamp
 */

/**
 * @typedef {Object} IngestResult
 * @property {string} source - Source identifier
 * @property {string} externalId - External job ID
 * @property {'created'|'updated'|'unchanged'|'rejected'} status - Result status
 * @property {string|null} jobId - Backend job UUID (null if rejected)
 * @property {string|null} message - Error message (null if successful)
 */

/**
 * @typedef {Object} IngestResponse
 * @property {number} received - Number of jobs received
 * @property {IngestResult[]} results - Per-job results
 * @property {Object} summary - Summary statistics
 * @property {number} summary.created - Jobs created
 * @property {number} summary.updated - Jobs updated
 * @property {number} summary.unchanged - Jobs unchanged
 * @property {number} summary.rejected - Jobs rejected
 */

/**
 * @typedef {Object} APIClientConfig
 * @property {string} apiUrl - Backend API URL
 * @property {string} apiKey - API key (public, can be logged)
 * @property {string} apiSecret - API secret (NEVER log this!)
 * @property {number} [batchSize=50] - Jobs per batch request
 * @property {number} [timeout=30000] - Request timeout in ms
 * @property {number} [retries=3] - Max retry attempts
 * @property {number} [retryDelay=1000] - Initial retry delay in ms
 */

export class CareerAPIClient {
  /**
   * @param {APIClientConfig} config - Client configuration
   */
  constructor(config) {
    this.apiUrl = config.apiUrl;
    this.apiKey = config.apiKey;
    this.apiSecret = config.apiSecret;
    this.batchSize = config.batchSize || 50;
    this.timeout = config.timeout || 30000;
    this.retries = config.retries || 3;
    this.retryDelay = config.retryDelay || 1000;

    // Statistics
    this.stats = {
      totalSubmitted: 0,
      totalCreated: 0,
      totalUpdated: 0,
      totalUnchanged: 0,
      totalRejected: 0,
      batchesSubmitted: 0,
      batchesFailed: 0,
      retriesPerformed: 0
    };

    // Validate config
    if (!this.apiUrl || !this.apiKey || !this.apiSecret) {
      throw new Error('CareerAPIClient: apiUrl, apiKey, and apiSecret are required');
    }

    console.log('[CareerAPIClient] Initialized', {
      apiUrl: this.apiUrl,
      batchSize: this.batchSize,
      timeout: this.timeout,
      retries: this.retries
    });
  }

  /**
   * Submit jobs to backend API in batches
   *
   * @param {CareerJob[]} jobs - Array of job objects
   * @returns {Promise<IngestResponse>} - Aggregated response
   */
  async submitJobs(jobs) {
    if (!jobs || jobs.length === 0) {
      console.log('[CareerAPIClient] No jobs to submit');
      return {
        received: 0,
        results: [],
        summary: { created: 0, updated: 0, unchanged: 0, rejected: 0 }
      };
    }

    console.log(`[CareerAPIClient] Submitting ${jobs.length} jobs in batches of ${this.batchSize}`);

    const allResults = [];
    const aggregatedSummary = {
      created: 0,
      updated: 0,
      unchanged: 0,
      rejected: 0
    };

    // Split into batches
    const batches = this._createBatches(jobs, this.batchSize);

    console.log(`[CareerAPIClient] Created ${batches.length} batches`);

    // Submit batches sequentially (to avoid overwhelming backend)
    for (let i = 0; i < batches.length; i++) {
      const batch = batches[i];

      console.log(`[CareerAPIClient] Submitting batch ${i + 1}/${batches.length} (${batch.length} jobs)`);

      try {
        const response = await this._submitBatchWithRetry(batch);

        // Aggregate results
        allResults.push(...response.results);
        aggregatedSummary.created += response.summary.created;
        aggregatedSummary.updated += response.summary.updated;
        aggregatedSummary.unchanged += response.summary.unchanged;
        aggregatedSummary.rejected += response.summary.rejected;

        this.stats.batchesSubmitted++;

        console.log(`[CareerAPIClient] Batch ${i + 1}/${batches.length} completed`, response.summary);

      } catch (error) {
        console.error(`[CareerAPIClient] Batch ${i + 1}/${batches.length} failed after retries:`, error.message);

        this.stats.batchesFailed++;

        // Mark all jobs in failed batch as rejected
        for (const job of batch) {
          allResults.push({
            source: job.source,
            externalId: job.externalId,
            status: 'rejected',
            jobId: null,
            message: `Batch submission failed: ${error.message}`
          });
          aggregatedSummary.rejected++;
        }
      }
    }

    // Update global stats
    this.stats.totalSubmitted += jobs.length;
    this.stats.totalCreated += aggregatedSummary.created;
    this.stats.totalUpdated += aggregatedSummary.updated;
    this.stats.totalUnchanged += aggregatedSummary.unchanged;
    this.stats.totalRejected += aggregatedSummary.rejected;

    console.log('[CareerAPIClient] Submission complete', {
      total: jobs.length,
      batches: batches.length,
      summary: aggregatedSummary
    });

    return {
      received: jobs.length,
      results: allResults,
      summary: aggregatedSummary
    };
  }

  /**
   * Submit single batch with retry logic
   *
   * @private
   * @param {CareerJob[]} batch - Batch of jobs
   * @returns {Promise<IngestResponse>}
   */
  async _submitBatchWithRetry(batch) {
    let lastError;

    for (let attempt = 0; attempt <= this.retries; attempt++) {
      if (attempt > 0) {
        const delay = this.retryDelay * Math.pow(2, attempt - 1);
        console.log(`[CareerAPIClient] Retry attempt ${attempt}/${this.retries} after ${delay}ms`);
        await this._sleep(delay);
        this.stats.retriesPerformed++;
      }

      try {
        return await this._submitBatch(batch);
      } catch (error) {
        lastError = error;

        // Don't retry client errors (4xx)
        if (error.statusCode && error.statusCode >= 400 && error.statusCode < 500) {
          console.error('[CareerAPIClient] Client error, not retrying:', error.message);
          throw error;
        }

        console.error(`[CareerAPIClient] Attempt ${attempt + 1}/${this.retries + 1} failed:`, error.message);
      }
    }

    throw new Error(`Failed after ${this.retries + 1} attempts: ${lastError.message}`);
  }

  /**
   * Submit single batch to backend
   *
   * @private
   * @param {CareerJob[]} batch - Batch of jobs
   * @returns {Promise<IngestResponse>}
   */
  async _submitBatch(batch) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeout);

    try {
      const response = await fetch(this.apiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': this.apiKey,
          'X-API-Secret': this.apiSecret
        },
        body: JSON.stringify({ jobs: batch }),
        signal: controller.signal
      });

      clearTimeout(timeoutId);

      // Parse response
      const data = await response.json();

      // Check for HTTP errors
      if (!response.ok) {
        const error = new Error(data.detail || `HTTP ${response.status}: ${response.statusText}`);
        error.statusCode = response.status;
        error.response = data;
        throw error;
      }

      return data;

    } catch (error) {
      clearTimeout(timeoutId);

      // Handle fetch errors
      if (error.name === 'AbortError') {
        throw new Error(`Request timeout after ${this.timeout}ms`);
      }

      if (error.code === 'ECONNREFUSED') {
        throw new Error('Connection refused - is backend server running?');
      }

      throw error;
    }
  }

  /**
   * Split jobs into batches
   *
   * @private
   * @param {CareerJob[]} jobs - All jobs
   * @param {number} batchSize - Batch size
   * @returns {CareerJob[][]} - Array of batches
   */
  _createBatches(jobs, batchSize) {
    const batches = [];

    for (let i = 0; i < jobs.length; i += batchSize) {
      batches.push(jobs.slice(i, i + batchSize));
    }

    return batches;
  }

  /**
   * Sleep for specified milliseconds
   *
   * @private
   * @param {number} ms - Milliseconds to sleep
   * @returns {Promise<void>}
   */
  _sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Get client statistics
   *
   * @returns {Object} - Statistics object
   */
  getStats() {
    return { ...this.stats };
  }

  /**
   * Reset statistics
   */
  resetStats() {
    this.stats = {
      totalSubmitted: 0,
      totalCreated: 0,
      totalUpdated: 0,
      totalUnchanged: 0,
      totalRejected: 0,
      batchesSubmitted: 0,
      batchesFailed: 0,
      retriesPerformed: 0
    };
    console.log('[CareerAPIClient] Statistics reset');
  }

  /**
   * Print statistics summary
   */
  printStats() {
    console.log('\n========================================');
    console.log('Career API Client Statistics');
    console.log('========================================');
    console.log(`Total Submitted:   ${this.stats.totalSubmitted}`);
    console.log(`  - Created:       ${this.stats.totalCreated}`);
    console.log(`  - Updated:       ${this.stats.totalUpdated}`);
    console.log(`  - Unchanged:     ${this.stats.totalUnchanged}`);
    console.log(`  - Rejected:      ${this.stats.totalRejected}`);
    console.log(`Batches Submitted: ${this.stats.batchesSubmitted}`);
    console.log(`Batches Failed:    ${this.stats.batchesFailed}`);
    console.log(`Retries Performed: ${this.stats.retriesPerformed}`);
    console.log('========================================\n');
  }

  /**
   * Check backend health
   *
   * @returns {Promise<Object>} - Health check response
   */
  async checkHealth() {
    const healthUrl = this.apiUrl.replace('/ingest', '/health');

    try {
      const response = await fetch(healthUrl, {
        method: 'GET',
        signal: AbortSignal.timeout(5000)
      });

      const data = await response.json();

      console.log('[CareerAPIClient] Health check:', data);

      return data;

    } catch (error) {
      console.error('[CareerAPIClient] Health check failed:', error.message);
      throw error;
    }
  }
}

/**
 * Create API client from environment variables
 *
 * @returns {CareerAPIClient}
 */
export function createClientFromEnv() {
  const config = {
    apiUrl: process.env.CAREER_API_URL,
    apiKey: process.env.CAREER_API_KEY,
    apiSecret: process.env.CAREER_API_SECRET,
    batchSize: parseInt(process.env.CAREER_API_BATCH_SIZE || '50', 10),
    timeout: parseInt(process.env.CAREER_API_TIMEOUT || '30000', 10),
    retries: parseInt(process.env.CAREER_API_RETRIES || '3', 10),
    retryDelay: parseInt(process.env.CAREER_API_RETRY_DELAY || '1000', 10)
  };

  return new CareerAPIClient(config);
}
