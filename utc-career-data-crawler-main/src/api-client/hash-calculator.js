/**
 * Content Hash Calculator - Node.js implementation matching Python backend
 *
 * CRITICAL: This implementation MUST produce identical hashes to Python's
 * calculate_content_hash() function in backend/app/career_models.py
 *
 * Hash is used for:
 * - Change detection (has job content changed?)
 * - Avoiding unnecessary database updates
 * - Deduplication across crawl sessions
 *
 * If hashes don't match between Node.js and Python:
 * - Unchanged jobs will be marked as updated (unnecessary DB writes)
 * - Updated jobs will be marked as unchanged (miss real changes)
 * - Data sync will fail between crawler and backend
 *
 * @module api-client/hash-calculator
 */

import { createHash } from 'node:crypto';

/**
 * Calculate content hash for a job posting
 *
 * This function MUST match Python's calculate_content_hash() exactly!
 *
 * Hashed fields (IN THIS ORDER):
 * - type
 * - title
 * - url
 * - company.name
 * - company.url
 * - salary (entire object)
 * - location (entire object)
 * - experience (entire object)
 * - tags (array)
 * - remainingTags
 *
 * Excluded fields (NOT in hash):
 * - source (identity, not content)
 * - externalId (identity, not content)
 * - company.logo (UI only, changes frequently)
 * - published (changes frequently, not content)
 *
 * JSON serialization MUST match Python:
 * - separators: (',', ':') - NO SPACES
 * - ensure_ascii: false - KEEP Unicode characters
 * - sort_keys: false - PRESERVE insertion order
 *
 * @param {Object} job - Job object
 * @returns {string} - SHA-256 hex hash (64 characters)
 *
 * @example
 * const hash = calculateContentHash({
 *   type: 'job',
 *   title: 'Backend Developer',
 *   url: 'https://example.com/job/1',
 *   company: { name: 'Test Co', url: 'https://test.com' },
 *   tags: ['Python', 'FastAPI']
 * });
 * // => 'a1b2c3d4e5f6...' (64 hex chars)
 */
export function calculateContentHash(job) {
  // Extract fields in exact order for hash calculation
  const content = {
    type: job.type ?? null,
    title: job.title ?? null,
    url: job.url ?? null,
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

  // Serialize to JSON matching Python's json.dumps()
  // CRITICAL: No spaces in separators, preserve Unicode, no key sorting
  const serialized = JSON.stringify(content);

  // SHA-256 hash
  const hash = createHash('sha256')
    .update(serialized, 'utf8')
    .digest('hex');

  return hash;
}

/**
 * Verify hash compatibility with Python backend
 *
 * Test vectors should be generated from Python backend:
 * ```python
 * from app.career_models import calculate_content_hash
 * jobs = [...]  # Test jobs
 * for job in jobs:
 *     print(f'{job["externalId"]}: {calculate_content_hash(job)}')
 * ```
 *
 * @param {Object[]} testVectors - Array of {job, expectedHash}
 * @returns {Object} - {passed, failed, results[]}
 */
export function verifyHashCompatibility(testVectors) {
  const results = [];
  let passed = 0;
  let failed = 0;

  for (const { job, expectedHash } of testVectors) {
    const actualHash = calculateContentHash(job);
    const matches = actualHash === expectedHash;

    results.push({
      externalId: job.externalId,
      expectedHash,
      actualHash,
      matches
    });

    if (matches) {
      passed++;
    } else {
      failed++;
      console.error(`[HashVerify] MISMATCH for ${job.externalId}:`, {
        expected: expectedHash,
        actual: actualHash
      });
    }
  }

  return { passed, failed, results };
}

/**
 * Generate test vectors for hash verification
 *
 * Use this to create test vectors to send to Python backend for verification.
 *
 * @param {Object[]} jobs - Array of job objects
 * @returns {Object[]} - Array of {job, hash}
 */
export function generateHashTestVectors(jobs) {
  return jobs.map(job => ({
    externalId: job.externalId,
    job,
    hash: calculateContentHash(job)
  }));
}

/**
 * Batch calculate hashes for multiple jobs
 *
 * @param {Object[]} jobs - Array of job objects
 * @returns {Map<string, string>} - Map of externalId -> hash
 */
export function batchCalculateHashes(jobs) {
  const hashes = new Map();

  for (const job of jobs) {
    const key = `${job.source}:${job.externalId}`;
    const hash = calculateContentHash(job);
    hashes.set(key, hash);
  }

  return hashes;
}

/**
 * Compare two jobs by content hash
 *
 * @param {Object} job1 - First job
 * @param {Object} job2 - Second job
 * @returns {boolean} - True if content is identical
 */
export function jobsHaveSameContent(job1, job2) {
  const hash1 = calculateContentHash(job1);
  const hash2 = calculateContentHash(job2);
  return hash1 === hash2;
}

/**
 * Reference implementation documentation
 *
 * This is the Python implementation we're matching:
 *
 * ```python
 * def calculate_content_hash(job: dict[str, Any]) -> str:
 *     content = {
 *         'type': job.get('type'),
 *         'title': job.get('title'),
 *         'url': job.get('url'),
 *         'company': {
 *             'name': job.get('company', {}).get('name') if isinstance(job.get('company'), dict) else None,
 *             'url': job.get('company', {}).get('url') if isinstance(job.get('company'), dict) else None,
 *         },
 *         'salary': job.get('salary'),
 *         'location': job.get('location'),
 *         'experience': job.get('experience'),
 *         'tags': job.get('tags', []),
 *         'remainingTags': job.get('remainingTags', []),
 *     }
 *
 *     serialized = json.dumps(
 *         content,
 *         separators=(',', ':'),
 *         sort_keys=False,
 *         ensure_ascii=False,
 *         allow_nan=False
 *     )
 *
 *     return hashlib.sha256(serialized.encode('utf-8')).hexdigest()
 * ```
 *
 * Key differences to watch for:
 *
 * 1. **separators**: Python (',', ':') vs JS default (', ', ': ')
 *    - JS default has SPACES which will break hash compatibility
 *    - Must NOT use JSON.stringify() with default settings
 *
 * 2. **ensure_ascii**: Python False vs JS default true
 *    - JS default escapes Unicode: "Hà Nội" -> "H\u00e0 N\u1ed9i"
 *    - Python keeps Unicode: "Hà Nội" -> "Hà Nội"
 *    - Must preserve Unicode characters in JS
 *
 * 3. **sort_keys**: Python False vs JS default (insertion order in ES2015+)
 *    - Modern JS (ES2015+) preserves insertion order by default
 *    - But we must construct object in EXACT same order as Python
 *
 * 4. **Null handling**: Python None vs JS null/undefined
 *    - Use ?? operator: job.field ?? null
 *    - Ensures consistent null serialization
 *
 * 5. **Array defaults**: Python get(key, []) vs JS ?? []
 *    - Both should produce same result: empty array
 *
 * @constant
 */
export const HASH_IMPLEMENTATION_NOTES = `
Hash Compatibility Notes:
========================

This Node.js implementation MUST produce identical hashes to:
  backend/app/career_models.py::calculate_content_hash()

Critical Requirements:
1. Field order MUST match Python exactly
2. JSON serialization MUST match (no spaces, preserve Unicode)
3. Null handling MUST be consistent (null vs undefined)
4. Array defaults MUST match ([] for missing arrays)

Testing:
- Run: node test-hash-vectors.js
- Compare with Python backend test vectors
- ALL hashes must match 100%

If hashes don't match:
- Debug JSON serialization (console.log(JSON.stringify(content)))
- Compare byte-by-byte with Python output
- Check for Unicode escaping issues
- Verify field order in content object
`;

/**
 * Create test job for hash verification
 *
 * @returns {Object} - Minimal test job
 */
export function createTestJob() {
  return {
    source: 'topcv',
    externalId: 'hash-test-001',
    type: 'job',
    title: 'Backend Developer - Hà Nội',
    url: 'https://example.com/job/1',
    company: {
      name: 'Công ty ABC',
      url: 'https://abc.com',
      logo: 'https://abc.com/logo.png'  // Excluded from hash
    },
    salary: {
      raw: '15-25 triệu',
      min: 15000000,
      max: 25000000,
      currency: 'VND',
      unit: 'month'
    },
    location: {
      raw: 'Hà Nội, Cầu Giấy'
    },
    experience: {
      raw: '2-3 năm'
    },
    tags: ['Python', 'FastAPI', 'PostgreSQL'],
    remainingTags: null,
    published: {  // Excluded from hash
      raw: '2 days ago',
      publishedAt: '2024-01-15T10:00:00Z'
    }
  };
}
