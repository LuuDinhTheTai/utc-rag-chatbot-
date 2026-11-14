# Tích hợp dữ liệu nghề nghiệp vào RAG

Mở rộng chatbot UTC để trả lời câu hỏi về thị trường việc làm, kỹ năng yêu cầu và con đường phát triển nghề nghiệp. Dữ liệu nghề nghiệp được thu thập từ các trang tuyển dụng, lưu trữ trong SQLite và lập chỉ mục tương tự tài liệu tuyển sinh. **Gemini vẫn là dịch vụ bên ngoài duy nhất**: ứng dụng gửi mô tả công việc và câu hỏi cho Gemini để tạo embedding và câu trả lời.

## Mục lục

- [Chức năng mở rộng](#chức-năng-mở-rộng)
- [Kiến trúc và luồng dữ liệu](#kiến-trúc-và-luồng-dữ-liệu)
- [Thiết kế database career](#thiết-kế-database-career)
- [Yêu cầu và cấu hình](#yêu-cầu-và-cấu-hình)
- [Chạy crawler thu thập dữ liệu](#chạy-crawler-thu-thập-dữ-liệu)
- [Lập chỉ mục dữ liệu nghề nghiệp](#lập-chỉ-mục-dữ-liệu-nghề-nghiệp)
- [Sử dụng tính năng career](#sử-dụng-tính-năng-career)
- [Xử lý lỗi và bảo trì](#xử-lý-lỗi-và-bảo-trì)

## Chức năng mở rộng

- **Định tuyến câu hỏi nghề nghiệp:** hệ thống tự động phân loại câu hỏi về nghề nghiệp (career intent) khác với câu hỏi tuyển sinh (admissions intent). Câu hỏi nghề nghiệp không yêu cầu năm tuyển sinh hay cơ sở, tìm kiếm trên toàn bộ kho dữ liệu việc làm.

- **Truy xuất thông tin việc làm:** khi có câu hỏi về nghề nghiệp, backend tạo embedding câu hỏi, tính độ tương đồng cosine với các đoạn mô tả công việc đã được lập chỉ mục, lấy tối đa 6 đoạn đạt ngưỡng rồi gọi Gemini tạo câu trả lời có trích dẫn nguồn.

- **Thu thập dữ liệu tự động:** crawler độc lập (`utc-career-data-crawler`) thu thập thông tin tuyển dụng từ TopCV, chuẩn hóa cấu trúc, loại bỏ trùng lặp và lưu vào SQLite. Hỗ trợ chạy định kỳ hoặc theo nhu cầu.

- **Trích dẫn nguồn tuyển dụng:** câu trả lời có liên kết đến bài đăng tuyển dụng gốc, công ty và vị trí tương ứng. Người dùng có thể đối chiếu thông tin chi tiết từ nguồn.

Các câu hỏi ví dụ hỗ trợ:
- "Backend Developer cần kỹ năng gì?"
- "Ngành CNTT ra trường có thể làm những công việc nào?"
- "Yêu cầu của vị trí Data Analyst?"
- "Frontend Developer cần biết những công nghệ gì?"

Câu hỏi tuyển sinh và câu hỏi nghề nghiệp dùng chung phiên chat; lịch sử hội thoại ghi cả hai loại. Người dùng không cần chuyển chế độ hay tạo phiên riêng.

## Kiến trúc và luồng dữ liệu

```text
TopCV/nguồn tuyển dụng
        │
        ▼
Crawler (Node.js)
        │
        ▼
SQLite: career_jobs, crawl_runs
        │
        ▼
Index script (Python)
 ├─► Extract text từ job
 ├─► Chunk (~1200 ký tự, overlap 180)
 ├─► Gemini embedding (768 chiều)
 └─► Lưu career_chunks, career_chunk_embeddings
        │
        ▼
User query → Question Router
        │
        ├─► career intent
        │   └─► match_career_chunks() → Gemini generation
        │
        └─► admissions intent
            └─► match_documents() → Gemini generation
```

**Crawler (Node.js):** đọc danh sách công việc từ trang tuyển dụng, trích xuất tiêu đề, công ty, mô tả, kỹ năng yêu cầu, mức lương và liên kết. Mỗi lần chạy tạo bản ghi `crawl_runs` ghi lại số trang, số job và trạng thái. Hỗ trợ crawl từng phần và theo dõi job đã không còn hoạt động.

**Indexing (Python):** đọc `career_jobs`, ghép các trường thành văn bản đầy đủ, chia thành đoạn, gửi Gemini tạo embedding và lưu vào `career_chunk_embeddings`. Tương tự quy trình lập chỉ mục tài liệu tuyển sinh nhưng không yêu cầu phạm vi năm/cơ sở.

**Question Router:** phân loại ý định bằng prompt hệ thống; câu hỏi về kỹ năng, công việc, vị trí, yêu cầu tuyển dụng được gắn `career` intent. Câu hỏi về điểm chuẩn, chỉ tiêu, ngành học giữ nguyên `admissions` intent.

**Retrieval:** tìm kiếm trong `career_chunk_embeddings` bằng cosine similarity, không lọc theo năm/cơ sở. Ngưỡng tương đồng dùng chung `SIMILARITY_THRESHOLD` của hệ thống.

**Dữ liệu gửi cho Gemini:** câu hỏi, nội dung các đoạn mô tả công việc được chọn và yêu cầu tạo câu trả lời; khi lập chỉ mục, nội dung các đoạn được gửi để tạo embedding. Crawler, database và tệp gốc nằm trên máy chủ của bạn.

## Thiết kế database career

Dữ liệu nghề nghiệp lưu trong **SQLite** cùng file `utc.sqlite3`, mở rộng schema hiện có. DDL có thể chạy trên database đang hoạt động tại [`backend/schema/career_chunks.sql`](backend/schema/career_chunks.sql) và [`utc-career-data-crawler/schema/schema.sql`](utc-career-data-crawler/schema/schema.sql). Migration tự động khi chạy script hoặc khi backend khởi động lần đầu sau khi cập nhật code.

```sql
-- Dữ liệu công việc từ crawler
CREATE TABLE career_jobs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,              -- 'topcv', 'vietnamworks', ...
    external_id TEXT,                  -- ID từ nguồn bên ngoài
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    job_type TEXT,                     -- full-time, part-time, ...
    salary_range TEXT,
    skills_required TEXT,              -- JSON array
    job_description TEXT,
    experience_required TEXT,
    posted_date TEXT,
    last_crawled_at TEXT,
    status TEXT DEFAULT 'active',      -- active, inactive
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Chunks để embedding
CREATE TABLE career_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES career_jobs(id) ON DELETE CASCADE
);

CREATE INDEX idx_career_chunks_job ON career_chunks(job_id);

-- Embeddings
CREATE TABLE career_chunk_embeddings (
    chunk_id INTEGER PRIMARY KEY,
    embedding BLOB NOT NULL,
    FOREIGN KEY (chunk_id) REFERENCES career_chunks(id) ON DELETE CASCADE
);

-- Lịch sử crawl
CREATE TABLE crawl_runs (
    run_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    scope TEXT,                        -- URL category hoặc filter
    status TEXT DEFAULT 'running',     -- running, completed, failed
    pages_discovered INTEGER,
    pages_fetched INTEGER,
    jobs_found INTEGER,
    is_full_crawl INTEGER DEFAULT 0,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    error_message TEXT
);
```

Một job có thể tạo nhiều chunk; mỗi chunk có một embedding. `career_jobs.status` cho phép tạm ẩn job không còn hoạt động mà không xóa dữ liệu lịch sử. Crawler không sửa nội dung job đã crawl; chỉ cập nhật `last_crawled_at` và `status`.

## Yêu cầu và cấu hình

Ngoài các yêu cầu chính của dự án (Python 3.11+, Node.js 22+, Gemini API key), tính năng career cần:

- **Node.js và npm** đã cài đặt cho crawler.
- **Backend đã chạy migration v2** nếu database có dữ liệu tuyển sinh cũ.
- **Dung lượng ổ đĩa:** crawler lưu tạm dữ liệu crawl trong SQLite riêng (`career-data.db`) trước khi submit backend hoặc chạy indexing.

### Biến môi trường crawler

Tạo `utc-career-data-crawler/.env` từ `utc-career-data-crawler/.env.example`:

| Biến | Ý nghĩa | Giá trị mặc định |
| --- | --- | --- |
| `TOPCV_CATEGORY_URL` | URL category TopCV muốn crawl | `https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257` |
| `MAX_PAGES` | Số trang tối đa crawl mỗi lần chạy | `5` |
| `CRAWL_DELAY_MS` | Delay giữa các request (ms) | `8000` |
| `CRAWL_TIMEOUT_MS` | Timeout mỗi request | `20000` |
| `SUBMIT_TO_API` | Tự động submit vào backend sau crawl | `false` |
| `API_URL` | Backend career ingest endpoint | `http://localhost:8000/api/v1/career/ingest` |
| `API_KEY` | API key có quyền `career:ingest` | Để trống nếu không submit |
| `API_SECRET` | API secret tương ứng | Để trống nếu không submit |

Nếu `SUBMIT_TO_API=true`, cần tạo API key bằng `backend/scripts/generate_api_key.py` với quyền `career:ingest`. Nếu chỉ crawl local, để `SUBMIT_TO_API=false` và bỏ qua `API_KEY`/`API_SECRET`.

### Biến môi trường backend (không thay đổi)

Backend dùng lại `GOOGLE_API_KEY`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` và `SIMILARITY_THRESHOLD` đã cấu hình. Không cần biến mới cho career; tất cả embedding dùng chung model.

## Chạy crawler thu thập dữ liệu

Crawler là một dự án Node.js độc lập trong thư mục `utc-career-data-crawler`. Nó **không cần backend chạy** khi chỉ crawl local.

### Cài đặt crawler

Mở PowerShell tại thư mục gốc dự án:

```powershell
cd utc-career-data-crawler
npm install
```

Kiểm tra `package.json` đã có `dotenv` và các dependencies.

### Cấu hình và chạy

Tạo file `.env` nếu chưa có:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Mở `.env` và sửa:

```env
TOPCV_CATEGORY_URL=https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257
MAX_PAGES=5
CRAWL_DELAY_MS=8000
SUBMIT_TO_API=false
```

Chạy crawler:

```powershell
node cli.js
```

Crawler sẽ:
1. Crawl tối đa 5 trang (hoặc `MAX_PAGES` đã đặt).
2. Trích xuất thông tin công việc từ mỗi trang.
3. Chuẩn hóa dữ liệu (loại bỏ HTML, làm sạch text).
4. Kiểm tra trùng lặp với dữ liệu cũ trong `career-data.db`.
5. Lưu job mới/cập nhật vào SQLite local.
6. In báo cáo: số trang, số job crawled, số job mới, số job cập nhật.

**Crawl nhiều trang:**

```powershell
node cli.js --pages 20
```

**Crawl và submit vào backend:**

```powershell
node cli.js --pages 10 --submit
```

Lệnh trên yêu cầu backend đang chạy và `API_KEY`/`API_SECRET` đã cấu hình trong `.env`. Crawler sẽ gửi batch 50 job một lần đến endpoint `/api/v1/career/ingest`.

### Xem dữ liệu crawl

```powershell
sqlite3 career-data.db "SELECT COUNT(*) FROM career_jobs;"
sqlite3 career-data.db "SELECT id, title, company FROM career_jobs LIMIT 5;"
```

Trên Linux/macOS dùng `sqlite3` tương tự. Database `career-data.db` là dữ liệu tạm của crawler; backend đọc từ `DATA_DIR/utc.sqlite3` sau khi chạy indexing hoặc khi crawler submit trực tiếp.

### Chạy theo lịch

Crawler hỗ trợ chạy tự động bằng `scheduler.js`:

```powershell
# Chạy mỗi 6 giờ
node scheduler.js --interval 6h

# Chạy mỗi ngày lúc 2 giờ sáng
node scheduler.js --cron "0 2 * * *"
```

Script scheduler dùng `node-cron` và tự động submit vào backend nếu `SUBMIT_TO_API=true`. Giữ tiến trình chạy trong screen/tmux hoặc dùng PM2.

## Lập chỉ mục dữ liệu nghề nghiệp

Sau khi crawl hoặc submit dữ liệu vào backend, chạy script indexing để tạo embedding và lưu vào `career_chunk_embeddings`.

### Chạy indexing

Từ thư mục `backend`:

```powershell
.\.venv\Scripts\activate
python scripts/index_career_data.py
```

Trên Linux/macOS:

```bash
.venv/bin/python scripts/index_career_data.py
```

Script sẽ:
1. Kết nối `DATA_DIR/utc.sqlite3`.
2. Lấy danh sách job chưa có embedding hoặc đã thay đổi.
3. Với mỗi job: trích xuất text (title, company, skills, description), chia thành chunks (~1200 ký tự, overlap 180), tạo embedding bằng Gemini.
4. Lưu `career_chunks` và `career_chunk_embeddings`.
5. In thống kê: số job đã index, số chunk, số embedding.

Mỗi job tạo trung bình 1–3 chunk tùy độ dài mô tả.

### Options indexing

```powershell
# Chỉ index 10 job đầu tiên
python scripts/index_career_data.py --limit 10

# Xem danh sách job sẽ được index mà không gọi Gemini
python scripts/index_career_data.py --dry-run

# Xóa toàn bộ embeddings cũ và tạo lại
python scripts/index_career_data.py --reindex
```

`--reindex` xóa `career_chunks` và `career_chunk_embeddings` rồi tạo lại từ đầu. Dùng khi thay đổi embedding model hoặc thuật toán chunking.

### Kiểm tra kết quả

```powershell
python -c "from app.localdb import connect; conn = connect(); print('Embeddings:', conn.execute('SELECT COUNT(*) FROM career_chunk_embeddings').fetchone()[0])"
```

Nếu số embeddings = 0, kiểm tra:
- Database có job trong `career_jobs` chưa.
- `GOOGLE_API_KEY` đã đặt đúng chưa.
- Hạn mức API Gemini còn không.

## Sử dụng tính năng career

### Hỏi đáp nghề nghiệp

Không cần thao tác đặc biệt. Mở trang chủ chatbot (`http://localhost:3000`) và hỏi câu hỏi liên quan nghề nghiệp:

**Ví dụ:**
- "Backend Developer cần kỹ năng gì?"
- "Lập trình viên Python cần học gì?"
- "Yêu cầu của vị trí Data Analyst?"

Backend tự động nhận dạng `career` intent và truy vấn `career_chunk_embeddings` thay vì `chunk_embeddings` của tài liệu tuyển sinh. Câu trả lời kèm trích dẫn job title, công ty và liên kết nguồn.

**Không cần chọn năm/cơ sở** khi hỏi về nghề nghiệp. Nếu câu hỏi nêu năm, backend bỏ qua năm đó cho career query.

### Phản hồi khi không có dữ liệu

Nếu chưa crawl hoặc chưa index job nào, câu hỏi career trả về `career_no_evidence` với thông báo chưa đủ căn cứ. Kiểm tra:
- Số job trong database: `SELECT COUNT(*) FROM career_jobs WHERE status='active';`
- Số embedding: `SELECT COUNT(*) FROM career_chunk_embeddings;`

### Hội thoại kết hợp

Người dùng có thể hỏi xen kẽ tuyển sinh và nghề nghiệp trong cùng một phiên:

**Ví dụ:**
1. "Điểm chuẩn CNTT 2026 cơ sở Hà Nội?"
2. "Ra trường ngành CNTT làm gì?"
3. "Phương thức 2 là gì?"

Câu 1 và 3 dùng admissions intent, câu 2 dùng career intent. Lịch sử ghi cả ba câu; trích dẫn nguồn độc lập theo từng loại.

## Xử lý lỗi và bảo trì

### TopCV trả về HTTP 403

Crawler có thể bị chặn nếu gửi request quá nhanh. Giải pháp:

1. **Tăng delay:**

```env
CRAWL_DELAY_MS=15000
```

2. **Thêm random delay** trong code (sửa `cli.js`):

```javascript
delayMs: 10000 + Math.floor(Math.random() * 5000), // 10-15s random
```

3. **Dùng proxy** (xem hướng dẫn trong `utc-career-data-crawler/README.md`).

4. **Rotate user agents** hoặc thêm header trình duyệt thực.

### Career query bị route nhầm sang admissions

Kiểm tra routing:

```powershell
cd backend
.\.venv\Scripts\activate
python
```

Trong Python shell:

```python
from app.question_router import route_question

route = route_question(
    "Backend Developer cần kỹ năng gì?",
    [],
    {'year': None, 'campus': None}
)

print(route.intent)       # Phải là 'career'
print(route.reason_code)  # Phải là 'career_request'
```

Nếu intent sai, kiểm tra prompt trong `question_router.py` hoặc nâng cấp Gemini model.

### Không có chunk nào match career query

Nguyên nhân có thể:
- Ngưỡng `SIMILARITY_THRESHOLD` quá cao (mặc định 0.65).
- Job description không chứa từ khóa liên quan.
- Embedding model không phù hợp với ngôn ngữ Việt.

Thử hạ ngưỡng tạm thời để test:

```env
SIMILARITY_THRESHOLD=0.55
```

Hoặc crawl thêm job từ nhiều category khác nhau.

### Reindex toàn bộ

Khi thay embedding model hoặc sửa thuật toán chunking:

```powershell
cd backend
.\.venv\Scripts\activate
python scripts/index_career_data.py --reindex
```

Lệnh trên xóa tất cả `career_chunks` và `career_chunk_embeddings` rồi tạo lại từ `career_jobs`. **Cảnh báo:** việc này gọi Gemini với toàn bộ job, có thể tiêu tốn hạn mức API.

### Dọn dẹp job không còn hoạt động

Crawler đánh dấu job là `inactive` nếu không còn trên trang nguồn sau full crawl. Để xóa job inactive quá 90 ngày:

```sql
DELETE FROM career_jobs
WHERE status = 'inactive'
AND last_crawled_at < date('now', '-90 days');
```

Cascade sẽ xóa `career_chunks` và `career_chunk_embeddings` tương ứng.

### Xem lịch sử crawler

```sql
SELECT run_id, status, pages_fetched, jobs_found, started_at
FROM crawl_runs
ORDER BY started_at DESC
LIMIT 10;
```

Hoặc dùng script Python:

```powershell
python -c "from app.localdb import connect; conn = connect(); rows = conn.execute('SELECT * FROM crawl_runs ORDER BY started_at DESC LIMIT 5').fetchall(); print(rows)"
```

### Kiểm tra tính toàn vẹn dữ liệu

Sau migration hoặc reindex, chạy:

```powershell
cd backend
.\.venv\Scripts\activate
python scripts/check_career_integrity.py
```

Script sẽ kiểm tra:
- Foreign key constraints giữa `career_jobs`, `career_chunks`, `career_chunk_embeddings`.
- Số chunk và embedding khớp nhau.
- Không có embedding orphan.
- Độ dài embedding đúng với `EMBEDDING_DIMENSIONS`.

Nếu phát hiện lỗi, script in ra các job_id hoặc chunk_id có vấn đề và đề xuất lệnh sửa.

---

**Cập nhật lần cuối:** 2026-11-14
**Phiên bản:** 1.0
