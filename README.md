# UTC RAG Chatbot tuyển sinh

Next.js + Python/FastAPI + LangChain + Supabase (Auth, PostgreSQL, pgvector) + Gemini API. Giao diện và các chức năng dựa trên báo cáo được cung cấp; công nghệ theo yêu cầu của người dùng.

## Thiết lập

Yêu cầu Node.js 22+, Python 3.11+, dự án Supabase và Gemini API key.

1. Chạy `supabase/schema.sql` một lần trong SQL Editor của dự án Supabase mới, sau đó chạy `supabase/storage.sql`. Với dự án đã có dữ liệu, chỉ chạy `supabase/storage.sql`.
2. Tạo tài khoản quản trị trong Supabase Authentication → Users. Gán quyền qua SQL Editor (thay email):

```sql
update auth.users
set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb) || '{"role":"admin"}'::jsonb
where email = 'admin@example.com';
```

Đăng xuất/đăng nhập lại sau khi đổi quyền. Không dùng user_metadata để phân quyền.

3. Chạy backend:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Điền SUPABASE_URL, SUPABASE_SECRET_KEY, GOOGLE_API_KEY vào .env
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

4. Mở terminal khác, chạy frontend:

```powershell
cd frontend
npm.cmd ci
Copy-Item .env.example .env.local
# Điền URL và publishable key Supabase vào .env.local
npm.cmd run dev
```

Chat: http://localhost:3000. Quản trị: http://localhost:3000/admin. Swagger: http://localhost:8000/docs.

Secret key Supabase và Gemini API key chỉ đặt ở backend. Health `/health` báo có cấu hình, không xác nhận kết nối dịch vụ.

## Nạp tri thức

Đăng nhập quản trị → nhập tiêu đề, URL chính thức, năm và cơ sở → chọn PDF/TXT/Markdown hoặc để trống tệp để đọc URL → trích xuất/xem trước → xác nhận lập chỉ mục → chờ READY.

Không kèm sẵn số liệu tuyển sinh chưa kiểm chứng. Báo cáo không tự động trở thành nguồn tuyển sinh. Tệp upload vẫn cần URL nguồn cho trích dẫn. PDF scan cần OCR trước. URL chỉ cho phép HTTPS tại các domain UTC liệt kê trong rag.py; không theo redirect.

## Chức năng

- Chat tiếng Việt, lọc năm/cơ sở; ưu tiên năm/cơ sở nêu trong câu hỏi.
- LangChain chia đoạn 1.200 ký tự, overlap 180; Gemini embedding 768 chiều; pgvector truy xuất top 6 theo cosine.
- Gemini trả lời có cấu trúc và trích dẫn; thiếu nguồn vượt ngưỡng sẽ từ chối mà không gọi mô hình sinh.
- Nguồn có tên, năm, đoạn trích, URL và ID chunk/document.
- Lịch sử theo mã phiên lưu trong trình duyệt; đánh giá hữu ích/chưa hữu ích.
- Supabase Auth cho admin; tải tài liệu, xem trạng thái, thử lại lỗi, bật/tắt, xóa.
- Xem phản hồi và câu chưa đủ nguồn, ghi log thời gian và loại lỗi không ghi API key.

## Kiểm thử

```powershell
cd backend
.venv\Scripts\python -m pytest -q
cd ../frontend
npm.cmd run build
npm.cmd run typecheck
```

Test local mock dịch vụ bên ngoài: phân quyền, quyền sở hữu phiên, lọc metadata, URL, tệp, rate limit, từ chối thiếu nguồn và trích dẫn ngoài phạm vi.

Kiểm thử tích hợp cần credentials thật: nạp tài liệu → READY → hỏi đúng năm/cơ sở → kiểm tra nguồn → gửi đánh giá → kiểm tra admin → vô hiệu hóa tài liệu → hỏi lại. Chưa xác nhận SQL trên Supabase hoặc Gemini khi chưa có credentials.

## Giới hạn triển khai

- Backend chạy một worker. Ingestion dùng BackgroundTasks; khi tiến trình dừng giữa chừng cần đổi tài liệu processing sang failed trong SQL Editor rồi thử lại. Quy mô lớn cần queue bền vững.
- Rate limit 20 request/phút/IP lưu trong bộ nhớ; nhiều worker cần Redis/gateway. Reverse proxy cần cấu hình trusted proxy và giới hạn tại gateway.
- Lịch sử trả tối đa 200 tin đầu tiên; admin tối đa 200 tài liệu và 100 phản hồi/câu thiếu nguồn. Chưa có phân trang.
- Lịch sử để xem lại; chưa dùng làm conversational memory cho câu hỏi nối tiếp.
- Chưa có OCR, reranker, đồng bộ định kỳ, benchmark dữ liệu UTC thật. Kiểm tra ID nguồn không bảo đảm mọi phát biểu đều được chứng minh; cần đánh giá trước khi công bố.
- Thay embedding model phải tái lập chỉ mục. Model cấu hình qua .env, chọn model còn được tài khoản Gemini hỗ trợ.
- Lưu văn bản trích xuất để retry; tệp gốc tải lên được lưu trong bucket riêng tư admission-documents. Cần cấu hình backup, thời hạn lưu lịch sử và TLS trước triển khai công khai.
- Mã phiên có quyền đọc lịch sử của phiên đó; không chia sẻ mã này.

## Tài liệu tham khảo

- https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai
- https://docs.langchain.com/oss/python/integrations/embeddings/google_generative_ai
- https://supabase.com/docs/guides/ai/vector-columns
- https://supabase.com/docs/reference/python/auth-getuser


## Khi Gemini báo 503 UNAVAILABLE

Log “This model is currently experiencing high demand” nghĩa là model Gemini đang quá tải. Backend thử tối đa 3 lần với thời gian chờ tăng dần và jitter, timeout 20 giây mỗi lần gọi sinh câu trả lời. Cấu hình SDK max_retries=1 tương ứng một lần gọi ở phiên bản đang khóa; retry được quản lý bên ngoài để không nhân số lần gọi.

Nếu vẫn thất bại, API trả thông báo tiếng Việt và Retry-After: 30; câu hỏi không bị ghi thành câu trả lời thiếu nguồn. Đợi khoảng 30 giây rồi gửi lại. Lỗi 429 cần kiểm tra quota nếu kéo dài; lỗi cấu hình 400/401/403/404 không được tự thử lại. Không cần nạp lại tài liệu vì lỗi sinh câu trả lời này.

Khởi động lại backend nếu không chạy với --reload. Việc thử lại giúp xử lý lỗi nhất thời, không bảo đảm Google hết quá tải.

Tham khảo: https://ai.google.dev/gemini-api/docs/troubleshooting


## Lưu tệp gốc trên Supabase Storage

- Bucket riêng tư: admission-documents. Chạy supabase/storage.sql khi thiết lập dự án mới hoặc nâng cấp dự án cũ.
- Khi xác nhận tài liệu tải lên, frontend gửi tệp gốc cùng nội dung đã xem trước qua POST /admin/documents/upload.
- Tệp nằm ở <document_id>/original.pdf (hoặc .txt, .md). Bảng documents lưu storage_path, original_filename và original_size.
- Nút “Tải tệp gốc” yêu cầu quyền admin và tạo signed URL có hạn 60 giây. Không chia sẻ liên kết khi chưa muốn người khác tải tệp.
- Tài liệu nạp bằng URL chỉ lưu văn bản đã trích xuất; tài liệu cũ không tự có bản gốc.
- Xóa tài liệu sẽ chuyển sang deleting, xóa object qua Storage API rồi xóa bản ghi và chunks. Nếu lỗi giữa chừng, bấm Xóa lần nữa; không bật lại hoặc retry ingestion của tài liệu deleting.
- Nếu lưu metadata thất bại sau upload, backend thử xóa object vừa tạo. Nếu Storage cũng gián đoạn, log storage_cleanup_failed ghi document_id để quản trị kiểm tra object còn sót.
- Storage và PostgreSQL không có transaction chung. Nếu backend dừng đột ngột giữa upload và insert, có thể còn object không có bản ghi; cần kiểm tra các thư mục không có document_id tương ứng khi bảo trì.
- Quyền Storage đi qua backend; không tạo policy công khai cho anon/authenticated.

Lỗi chat “null value in column sources” đã được sửa bằng cách gửi sources=[] cho tin nhắn user và cùng bộ cột cho hai bản ghi trong bulk insert.


Kiểm tra tích hợp Storage đã chạy trên dự án cấu hình: upload/download đúng bytes, signed URL hoạt động, URL công khai bị chặn, xóa tệp thử thành công. Bulk insert lịch sử chat với sources=[] cũng đã chạy thành công; dữ liệu thử đã được xóa. Bộ kiểm thử local: 42 test; frontend production build đạt.

Supabase Security Advisor còn cảnh báo có sẵn ở hàm match_document_chunks (search_path), handle_new_user (quyền EXECUTE) và cấu hình kiểm tra mật khẩu rò rỉ. Các mục này không được thay đổi trong phần tích hợp Storage. Các bảng ứng dụng bật RLS không có policy vì truy cập thông qua backend service role.
#   u t c - r a g - c h a t b o t -  
 