# Trợ lý tuyển sinh UTC dùng RAG

Ứng dụng hỏi đáp tuyển sinh bằng tiếng Việt, kèm nguồn để người dùng đối chiếu. Dự án gồm giao diện Next.js và API FastAPI. Bạn tự vận hành dữ liệu, tài khoản quản trị, tệp tài liệu và tìm kiếm vector trên máy chủ của mình. **Gemini là dịch vụ bên ngoài duy nhất trong luồng AI**: ứng dụng gửi câu hỏi và các đoạn tài liệu được chọn cho Gemini để tạo embedding và câu trả lời.

Tài liệu phân tích từng module, luồng xử lý và cấu trúc lưu trữ: [Kiến trúc chi tiết](docs/ARCHITECTURE.md).

## Mục lục

- [Chức năng](#chức-năng)
- [Kiến trúc và luồng dữ liệu](#kiến-trúc-và-luồng-dữ-liệu)
- [Yêu cầu và cấu hình](#yêu-cầu-và-cấu-hình)
- [Chạy trên Windows](#chạy-trên-windows)
- [Chạy trên Linux hoặc macOS](#chạy-trên-linux-hoặc-macos)
- [Sử dụng ứng dụng](#sử-dụng-ứng-dụng)
- [Công cụ nhập dữ liệu](#công-cụ-nhập-dữ-liệu)
- [Bộ đánh giá RAG](#bộ-đánh-giá-rag)
- [API chính](#api-chính)
- [Triển khai và sao lưu](#triển-khai-và-sao-lưu)
- [Dữ liệu từ Supabase cũ](#dữ-liệu-từ-supabase-cũ)
- [Kiểm thử và xử lý lỗi](#kiểm-thử-và-xử-lý-lỗi)

## Chức năng

- **Hỏi đáp tuyển sinh:** lọc theo năm và cơ sở Hà Nội/TP. Hồ Chí Minh; hiển thị trích dẫn, liên kết nguồn, lịch sử hội thoại và đánh giá câu trả lời.
- **Kho tài liệu:** quản trị viên xem trước nội dung từ URL hoặc tệp, xác nhận lập chỉ mục, tải lại tệp gốc, tạm ẩn, thử lại khi lập chỉ mục lỗi và xóa tài liệu.
- **Danh mục ngành học:** xem, tìm kiếm, lọc, phân trang; quản trị viên có thể thêm, sửa, ẩn/hiện, xóa hoặc nhập từ JSON.
- **Hướng dẫn tân sinh viên:** xem hướng dẫn theo khóa, mở PDF gốc; quản trị viên quản lý PDF và từng mục hồ sơ/minh chứng ưu tiên.

Các trang chính: `/` (chat), `/majors` (ngành học), `/freshmen` (tân sinh viên), `/admin` (quản trị). Tài liệu API tự sinh ở `/docs` trên backend.

## Kiến trúc và luồng dữ liệu

```text
Trình duyệt (Next.js)
        │ HTTP
        ▼
FastAPI ───────────► SQLite: tài khoản, phiên, tài liệu, embedding, hội thoại
   │ └─────────────► DATA_DIR/files/: tệp gốc và PDF hướng dẫn
   └───────────────► Gemini API: embedding và sinh câu trả lời
```

Khi quản trị viên thêm tài liệu, backend trích xuất văn bản, chia thành các đoạn khoảng 1.200 ký tự với phần chồng 180 ký tự, gọi Gemini tạo embedding 768 chiều và lưu vào SQLite. Khi có câu hỏi, backend xác định năm/cơ sở, tạo embedding cho câu hỏi, tính độ tương đồng cosine trên các đoạn tài liệu đang hoạt động, lấy tối đa 6 đoạn đạt ngưỡng rồi mới gọi Gemini tạo câu trả lời có nguồn. Nếu không tìm được nguồn phù hợp, ứng dụng trả lời rằng chưa đủ căn cứ.

**Dữ liệu gửi cho Gemini:** câu hỏi, văn bản của các đoạn được chọn và yêu cầu tạo câu trả lời; khi lập chỉ mục, nội dung các đoạn được gửi để tạo embedding. Cơ sở dữ liệu, phiên đăng nhập và tệp gốc nằm trên máy chủ của bạn.

## Yêu cầu và cấu hình

- Python **3.11+**, Node.js **22+**, npm.
- Gemini API key có quyền dùng model chat và embedding đã cấu hình.
- Một thư mục dữ liệu có quyền ghi cho tiến trình backend.
- Không cần tài khoản hoặc dự án Supabase cho bản chạy mới.

### Biến môi trường backend

Tạo `backend/.env` từ `backend/.env.example`. Nếu đã có file `.env`, cập nhật các biến dưới đây và bỏ các biến `SUPABASE_*` cũ sau khi đã sao lưu/migrate dữ liệu cần giữ.

| Biến | Ý nghĩa | Giá trị mẫu/mặc định |
| --- | --- | --- |
| `DATA_DIR` | Thư mục chứa `utc.sqlite3` và `files/`; đường dẫn tương đối tính từ thư mục chạy backend | `data/local` |
| `ADMIN_EMAIL` | Email tạo tài khoản quản trị đầu tiên | `admin@example.com` |
| `ADMIN_PASSWORD` | Mật khẩu ban đầu, **ít nhất 16 ký tự**, phải thay giá trị mẫu `CHANGE_ME...` | Tự đặt |
| `GOOGLE_API_KEY` | Khóa Gemini, chỉ đặt ở backend | Tự cấp |
| `GEMINI_MODEL` | Model tạo câu trả lời | `gemini-2.5-flash` |
| `EMBEDDING_MODEL` | Model tạo embedding | `gemini-embedding-001` |
| `FRONTEND_ORIGIN` | Origin được phép gọi API qua CORS | `http://localhost:3000` |
| `SIMILARITY_THRESHOLD` | Ngưỡng tương đồng tối thiểu khi tìm đoạn nguồn | `0.65` |

Tài khoản quản trị được tạo vào **lần đăng nhập đầu tiên**. Mật khẩu được lưu trong SQLite dưới dạng hash scrypt có salt; token đăng nhập hết hạn sau 12 giờ. Sau khi tạo tài khoản, có thể bỏ `ADMIN_PASSWORD` khỏi môi trường. Chỉ sửa biến này trong `.env` **không đổi** mật khẩu của tài khoản đã có; xem mục [Đổi mật khẩu quản trị](#đổi-mật-khẩu-quản-trị).

`GET /health` trả `configured: true` khi đã có tài khoản quản trị trong SQLite và đã cấu hình `GOOGLE_API_KEY`. Trước lần đăng nhập đầu tiên, `configured` vẫn là `false`.

### Biến môi trường frontend

Chỉ cần `NEXT_PUBLIC_API_URL`, ví dụ `http://localhost:8000`. Đặt trong `frontend/.env.local` hoặc cập nhật `frontend/.env` đang có. **Không đặt** mật khẩu quản trị, khóa Gemini hay khóa cơ sở dữ liệu trong biến `NEXT_PUBLIC_*`, vì các biến này xuất hiện ở trình duyệt.

## Chạy trên Windows

Mở PowerShell tại thư mục gốc dự án:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Sửa `backend/.env`: đặt `ADMIN_EMAIL`, `ADMIN_PASSWORD` riêng (ít nhất 16 ký tự) và `GOOGLE_API_KEY`. Nếu file đã tồn tại, không chạy lệnh `Copy-Item` ghi đè mà chỉ bổ sung các biến cần thiết. Sau đó chạy API từ thư mục `backend`:

```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Mở PowerShell thứ hai tại thư mục gốc:

```powershell
cd frontend
npm.cmd ci
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
npm.cmd run dev
```

Nếu `frontend/.env.local` đã tồn tại, chỉ cần kiểm tra `NEXT_PUBLIC_API_URL` thay vì ghi đè. Mở <http://localhost:3000>; trang quản trị ở <http://localhost:3000/admin>; API ở <http://localhost:8000/docs>.

## Chạy trên Linux hoặc macOS

Từ thư mục gốc dự án:

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
test -f .env || cp .env.example .env
# Sửa ADMIN_EMAIL, ADMIN_PASSWORD và GOOGLE_API_KEY trong .env.
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

Trong terminal khác:

```bash
cd frontend
npm ci
test -f .env.local || cp .env.example .env.local
npm run dev
```

Nếu `.env` hoặc `.env.local` đã tồn tại, cập nhật file hiện có thay vì ghi đè. Các đường dẫn tương đối trong cấu hình backend phụ thuộc vào thư mục làm việc; các lệnh trên giả định API được chạy từ `backend`.

## Sử dụng ứng dụng

### Nạp tài liệu cho chatbot

1. Vào `/admin`, đăng nhập bằng tài khoản cục bộ.
2. Nhập tiêu đề, URL nguồn chính thức, năm tuyển sinh và cơ sở.
3. Chọn PDF/TXT/Markdown hoặc để trống tệp để đọc nội dung trực tiếp từ URL. Bấm **Trích xuất & xem trước**.
4. Kiểm tra/chỉnh văn bản trích xuất, rồi bấm **Xác nhận & lập chỉ mục**.
5. Chờ trạng thái `ready`. Nếu là `failed`, kiểm tra cấu hình Gemini/hạn mức API rồi dùng **Thử lại**.

Giới hạn hiện tại: tệp tối đa **10 MB**, PDF tối đa **300 trang**, văn bản phải có ít nhất **30 ký tự**, tài liệu tối đa **2.000 đoạn**. PDF scan cần OCR trước. URL nguồn phải dùng HTTPS và thuộc một trong các tên miền được cho phép: `tuyensinh.utc.edu.vn`, `www.utc.edu.vn`, `utc.edu.vn`, `utc2.edu.vn`, `www.utc2.edu.vn`. Việc đọc URL không theo chuyển hướng. Tệp tải lên vẫn cần URL nguồn để trích dẫn.

Một tài liệu chỉ được lập chỉ mục một lần cho cùng năm, cơ sở và nội dung. Chỉ các tài liệu có trạng thái `ready` tham gia tìm kiếm. Admin có thể chuyển giữa `ready` và `inactive`.

### Hỏi đáp và phản hồi

Chọn năm/cơ sở trên trang chủ rồi gửi câu hỏi, không cần đăng ký hoặc đăng nhập. Nếu câu hỏi nêu rõ một năm hoặc cơ sở, backend ưu tiên thông tin trong câu hỏi; câu hỏi trộn nhiều năm hoặc cả hai cơ sở sẽ bị yêu cầu tách riêng. Khi gửi câu hỏi đầu tiên, backend tạo một token phiên chat ngẫu nhiên; trình duyệt lưu token này trong `localStorage` để xem lại lịch sử trên cùng trình duyệt. Nút **Cuộc trò chuyện mới** bỏ token hiện tại và tạo phiên mới ở lần gửi tiếp theo. Đánh giá hữu ích/chưa hữu ích chỉ ghi cho câu trả lời của đúng phiên. Token phiên là bí mật truy cập lịch sử: ai có token có thể xem hội thoại đó, nên tránh chia sẻ hoặc nhập trên thiết bị công cộng.

### Quản lý ngành học và hướng dẫn tân sinh viên

Tại `/admin`, dùng tab **Ngành học** để quản lý danh mục hoặc nhập JSON. Dùng tab **Tân sinh viên** để tạo khóa (ví dụ `K67`) với PDF, công bố/ẩn hướng dẫn và quản lý từng mục hồ sơ. Danh mục ngành học **không tự trở thành nguồn RAG**; muốn chatbot dùng dữ liệu mới, hãy nạp tài liệu nguồn tương ứng vào kho tài liệu.

### Đổi mật khẩu quản trị

Chạy từ `backend`:

```powershell
.venv\Scripts\python scripts/set_admin_password.py
```

Trên Linux/macOS, thay bằng `.venv/bin/python scripts/set_admin_password.py`. Script hỏi email và mật khẩu mới, yêu cầu ít nhất 16 ký tự, rồi thu hồi mọi phiên quản trị đang tồn tại.

## Công cụ nhập dữ liệu

Các script sau có chế độ kiểm tra trước; thêm `--apply` mới ghi vào SQLite. Chạy từ `backend` để dùng đúng `DATA_DIR`.

**Danh mục ngành từ JSON** (định dạng có `metadata.source_url` và mục `chi_tieu_YYYY`):

```powershell
.venv\Scripts\python scripts/import_majors.py "duong-dan\majors.json"
.venv\Scripts\python scripts/import_majors.py "duong-dan\majors.json" --apply
```

Dữ liệu đã có cùng năm, cơ sở và mã xét tuyển được bỏ qua; các sửa đổi của admin được giữ lại.

**Hướng dẫn K67** từ PDF và dữ liệu đã có tại `backend/data/freshmen_k67.json`:

```powershell
.venv\Scripts\python scripts/import_freshmen.py "duong-dan\huong-dan-K67.pdf"
.venv\Scripts\python scripts/import_freshmen.py "duong-dan\huong-dan-K67.pdf" --apply
```

Script kiểm tra PDF, số trang tham chiếu và các mục dữ liệu trước khi nhập. Script này hiện dành riêng cho dữ liệu K67 được lưu trong repository.

## Bộ đánh giá RAG

Bộ đánh giá nằm ở `backend/app/evaluation.py`, chạy bằng `backend/scripts/evaluate_rag.py`. Nó dùng **cùng bộ lọc năm/cơ sở, model embedding, ngưỡng tương đồng và top 6 đoạn** như API `POST /chat`. Lệnh chỉ đọc kho tài liệu; không tạo phiên chat hay ghi phản hồi.

### Chuẩn bị bộ câu hỏi

Sao chép `backend/evaluations/dataset.example.json` thành một file JSON riêng và sửa các câu hỏi cho phù hợp tài liệu đã nạp. File mẫu chỉ minh họa cấu trúc; URL có đoạn `duong-dan-tai-lieu-da-nap` phải được thay bằng **URL nguồn chính xác** của một tài liệu trạng thái `ready` trong `/admin`.

Mỗi câu trong `cases` cần `id` duy nhất, `question`, `year`, `campus` (`hanoi` hoặc `hcm`) và `expect_supported`:

- Nếu `expect_supported: true`, điền ít nhất một URL vào `expected_source_urls`. Có thể thêm `required_answer_phrases` để kiểm tra các cụm từ cần xuất hiện trong câu trả lời.
- Có thể điền `expected_answer` làm đáp án tham chiếu để người đọc đối chiếu trong báo cáo. Công cụ không chấm mức độ giống nhau về ngữ nghĩa với đáp án này; điều kiện tự động cho nội dung trả lời là các cụm từ trong `required_answer_phrases`. Với câu hỏi phải từ chối, không đặt `expected_answer`.
- Nếu `expect_supported: false`, để hai danh sách trên rỗng. Trường hợp này kiểm tra chatbot có từ chối khi thiếu căn cứ hay không; nó không yêu cầu bước truy xuất trả về 0 đoạn.
- URL kỳ vọng được so khớp **chính xác** với `source_url` đã lưu. Cụm từ đáp án được kiểm tra theo chuỗi, không phân biệt chữ hoa/thường và khoảng trắng thừa; đây là phép kiểm tra đơn giản, **không thay thế đánh giá đúng sai ngữ nghĩa** của người đọc.

Nên có cả câu hỏi có nguồn rõ ràng, câu hỏi về năm/cơ sở khác nhau và câu hỏi phải từ chối. Sau khi quản trị viên thay tài liệu hoặc đổi cách tìm kiếm/prompt, chạy lại **cùng một file JSON** để so sánh.

### Chạy đánh giá

Chạy từ thư mục `backend` sau khi cấu hình `GOOGLE_API_KEY` và nạp tài liệu:

```powershell
.venv\Scripts\python scripts/evaluate_rag.py evaluations/dataset.example.json
.venv\Scripts\python scripts/evaluate_rag.py evaluations/dataset.example.json --retrieval-only
```

Lần đầu chạy, hãy thay URL mẫu trước. `--retrieval-only` chỉ bỏ bước sinh câu trả lời; bước tạo embedding câu hỏi vẫn gọi Gemini. Ở chế độ đầy đủ, cả embedding lẫn sinh câu trả lời có thể tiêu thụ hạn mức API. Trên Linux/macOS, dùng `.venv/bin/python`.

Mỗi lần chạy tạo báo cáo JSON có dấu thời gian tại `DATA_DIR/evaluations/`; dùng `--output duong-dan/bao-cao.json` nếu muốn chọn đường dẫn khác. Báo cáo chứa câu hỏi, câu trả lời, URL nguồn và điểm từng câu; hãy giữ thư mục này riêng tư. Báo cáo không chứa API key hoặc toàn văn các đoạn truy xuất.

Để so với báo cáo trước và dùng trong CI:

```powershell
.venv\Scripts\python scripts/evaluate_rag.py evaluations/dataset.example.json --baseline "duong-dan\run-cu.json"
.venv\Scripts\python scripts/evaluate_rag.py evaluations/dataset.example.json --fail-below 1.0
```

`--baseline` yêu cầu cùng bộ câu hỏi, cùng chế độ và cùng model embedding; kết quả in phần chênh lệch của các chỉ số. `--fail-below` trả mã thoát 1 nếu tỷ lệ đạt thấp hơn ngưỡng, còn lỗi chạy câu hỏi trả mã 2.

### Cách đọc kết quả

| Chỉ số | Ý nghĩa |
| --- | --- |
| `retrieval_hit_at_6` | Tỷ lệ câu hỏi cần trả lời có ít nhất một URL kỳ vọng trong 6 đoạn truy xuất. |
| `mean_reciprocal_rank` | Trung bình `1 / vị trí` của nguồn kỳ vọng đầu tiên; nguồn xuất hiện sớm được điểm cao hơn. |
| `support_accuracy` | Tỷ lệ dự đoán đủ/không đủ căn cứ đúng theo `expect_supported`. |
| `citation_hit_rate` | Tỷ lệ câu hỏi cần trả lời có ít nhất một trích dẫn thuộc URL kỳ vọng. |
| `phrase_pass_rate` | Tỷ lệ câu có cụm từ bắt buộc mà câu trả lời chứa đủ các cụm từ đó. |
| `pass_rate` | Tỷ lệ câu đạt tất cả điều kiện áp dụng cho câu đó. Ở chế độ chỉ truy xuất, chỉ các câu `expect_supported: true` tham gia mẫu số. |

Nếu `retrieval_hit_at_6` thấp, kiểm tra tài liệu, bộ lọc, embedding và ngưỡng. Nếu truy xuất đúng nhưng `citation_hit_rate` hoặc `phrase_pass_rate` thấp, kiểm tra cách tạo câu trả lời và nội dung nguồn. Luôn đọc các câu bị đánh dấu `FAIL` trong báo cáo trước khi sửa hệ thống.


## API chính

| Nhóm | Endpoint | Công dụng |
| --- | --- | --- |
| Hệ thống | `GET /health` | Trạng thái và cờ cấu hình |
| Chat | `POST /sessions`, `GET /messages`, `POST /chat`, `POST /feedback` | Tạo phiên ẩn danh, lịch sử, hỏi đáp, đánh giá |
| Quản trị | `POST /admin/login`, `POST /admin/logout` | Đăng nhập, đăng xuất |
| Tài liệu | `GET/POST /admin/documents`, `POST /admin/documents/preview`, `POST /admin/documents/upload` | Danh sách, thêm và xem trước |
| Tài liệu | `GET /admin/documents/{id}/download`, `PATCH/DELETE /admin/documents/{id}`, `POST /admin/documents/{id}/retry` | Tải tệp gốc và quản lý trạng thái |
| Rà soát | `GET /admin/review` | Phản hồi và câu trả lời thiếu nguồn |
| Ngành học | `GET /majors`, `GET /majors/{id}`, `/admin/majors/*` | Tra cứu và quản trị |
| Tân sinh viên | `GET /freshmen`, `GET /freshmen/{cohort}`, `GET /freshmen/{cohort}/pdf`, `/admin/freshmen/*` | Hướng dẫn và quản trị |

Các endpoint `/admin/*` cần `Authorization: Bearer <token>` của quản trị viên, ngoại trừ `/admin/login`. `POST /sessions` không cần xác thực và trả token phiên. `GET /messages`, `POST /chat` và `POST /feedback` cần header `X-Session-Token` lấy từ phiên đó; đây là token riêng cho lịch sử chat, không cấp quyền quản trị. Xem schema yêu cầu/phản hồi đầy đủ tại `/docs`.

## Triển khai và sao lưu

- Build frontend bằng `npm ci && npm run build`, sau đó chạy `npm run start`. Chạy backend với `uvicorn app.main:app --port 8000` từ thư mục `backend`; trong môi trường production không dùng `--reload`.
- Đặt reverse proxy và HTTPS trước frontend/backend. Cập nhật `FRONTEND_ORIGIN` theo **origin** frontend công khai, và `NEXT_PUBLIC_API_URL` theo URL backend công khai. Build lại frontend nếu đổi biến `NEXT_PUBLIC_*`.
- Đặt `DATA_DIR` thành đường dẫn **tuyệt đối**, ổn định, nằm ngoài thư mục mã nguồn. Thư mục phải riêng tư và tiến trình backend phải có quyền đọc/ghi.
- Chạy một instance backend dùng SQLite. Tìm kiếm vector hiện tính cosine trên các đoạn phù hợp trong SQLite; bộ tài liệu rất lớn có thể cần một chỉ mục vector tự host riêng.
- Để sao lưu nhất quán, dừng backend rồi sao chép **toàn bộ** `DATA_DIR`, gồm `utc.sqlite3` và `files/`. Khôi phục cả hai vào cùng `DATA_DIR` trước khi khởi động lại. Thử khôi phục trên máy kiểm thử trước khi dùng bản sao lưu.
- Không commit `.env`, khóa Gemini, mật khẩu hoặc `DATA_DIR`. `.gitignore` đã loại các file `.env` thông thường và `backend/data/local/`; với đường dẫn dữ liệu tùy chỉnh, cần tự bảo vệ và sao lưu.

## Dữ liệu từ Supabase cũ

Phiên bản này **không tự sao chép dữ liệu cũ**. SQLite mới bắt đầu trống. Trước khi chuyển lưu lượng thật, hãy xuất và đối chiếu tài liệu cùng embedding, tệp gốc, danh mục ngành, hướng dẫn tân sinh viên/PDF và các mục liên quan từ dự án cũ. Tài khoản Supabase Auth không chuyển sang hệ thống mới; hãy tạo tài khoản quản trị cục bộ. Các file SQL trong `supabase/` chỉ còn là tham chiếu cho cấu trúc cũ và không chạy khi khởi động.

## Kiểm thử và xử lý lỗi

Chạy từ thư mục gốc:

```powershell
cd backend
.venv\Scripts\python -m pytest -q
cd ../frontend
npm.cmd run build
npm.cmd run typecheck
```

Trên Linux/macOS, dùng `.venv/bin/python` và `npm` thay cho các lệnh tương ứng của Windows.

| Hiện tượng | Kiểm tra |
| --- | --- |
| Không đăng nhập được | `ADMIN_EMAIL`, mật khẩu ban đầu đủ 16 ký tự và đã thay `CHANGE_ME...`; tài khoản cũ cần đổi bằng script, không chỉ sửa `.env`. |
| `/health` trả `configured: false` | Chưa có lần đăng nhập đầu tiên hoặc chưa đặt `GOOGLE_API_KEY`. |
| Frontend không gọi được API | Backend đang chạy, `NEXT_PUBLIC_API_URL` đúng, `FRONTEND_ORIGIN` khớp origin của trình duyệt. |
| Tài liệu ở trạng thái `failed` | Kiểm tra Gemini API key, model, hạn mức và nội dung tài liệu; sau đó dùng **Thử lại**. |
| Chat báo thiếu nguồn | Kiểm tra tài liệu đã `ready`, năm/cơ sở đúng và có đoạn đạt ngưỡng `SIMILARITY_THRESHOLD`. |
| PDF không trích xuất được chữ | PDF scan cần OCR trước khi tải lên. |
| Mất dữ liệu sau khi triển khai lại | Kiểm tra `DATA_DIR` trỏ tới ổ đĩa bền vững, không phải thư mục bị thay thế cùng mã nguồn. |

Các thay đổi trong `backend/.env` cần khởi động lại backend; thay đổi URL API của frontend cần chạy lại hoặc build lại frontend tùy cách triển khai.
