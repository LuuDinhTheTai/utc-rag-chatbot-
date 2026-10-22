# Thiết kế database v2

Schema đích: [v2.sql](../backend/schema/v2.sql). ERD: [README](../README.md#thiết-kế-database-v2-và-erd). Thiết kế tham khảo [database-design](https://github.com/MoizIbnYousaf/ai-agent-skills/blob/main/skills/database-design/SKILL.md), điều chỉnh cho SQLite thay vì sao chép cú pháp PostgreSQL. Runtime, scripts import và lớp chuyển đổi đã tích hợp schema v2; database cũ chỉ được chuyển bằng lệnh offline rõ ràng.

## Quyết định thiết kế

| Hiện tại | Thiết kế đích và lý do |
| --- | --- |
| Danh mục và điểm chuẩn lặp năm/cơ sở/mã/tên chương trình | `admission_offerings` định danh một chương trình trong một năm tại một cơ sở. Danh mục chi tiết là quan hệ 0..1; điểm chuẩn không buộc phải có danh mục đầy đủ. `cutoff_scores.program_name_snapshot` giữ nguyên tên công bố ở từng nguồn vì có thể khác tên danh mục; đây là phi chuẩn hóa có chủ đích để không mất thông tin. |
| `methods`, `subject_groups` chứa JSON | Hai bảng nối có khóa ghép chống trùng và `sort_order` để giữ thứ tự mảng API. Phương thức có danh mục riêng; tổ hợp chỉ cần mã nguyên tử vì hiện chưa có metadata môn học. |
| Vector gắn trực tiếp vào chunk | Tách `embedding_models` và `chunk_embeddings`, cho phép tái lập chỉ mục song song; model và số chiều bất biến. Trigger kiểm tra số chiều và kiểu phần tử khi ghi/sửa vector. |
| `messages.sources` chứa mảng trích dẫn | `message_citations` định danh thứ tự trích dẫn, liên kết chunk nếu còn tồn tại, giữ JSON snapshot nguyên vẹn cho lịch sử. JSON có chủ đích ở dữ liệu chứng cứ bất biến và vector. |
| `documents.created_by` không có FK | Tham chiếu `accounts`; xóa tài khoản đặt tác giả thành NULL, không xóa nguồn. |
| Tài khoản quản trị cũ và mới cùng tồn tại | Chỉ dùng `accounts`/`auth_sessions` trong schema đích. Bảo tồn bảng cũ trong bản sao lưu, không mang token đăng nhập cũ sang. |
| Ràng buộc chủ yếu nằm ở API | STRICT, CHECK, UNIQUE và FK bảo vệ cả thao tác ghi trực tiếp. Điểm phải nằm trong thang, phản hồi chỉ -1/+1, boolean chỉ 0/1. |

Không tạo thực thể ngành toàn cục chỉ từ `major_code`: tên, chương trình và mã ngành lịch sử có thể khác giữa các năm; cần đối chiếu dữ liệu trước khi gộp. Không suy ra danh mục 2024/2025 từ danh mục 2026.

UUID dạng TEXT giữ các ID công khai hiện có; ứng dụng sinh UUID cho offering chỉ xuất hiện trong điểm chuẩn. Token chỉ lưu hash, mật khẩu chỉ lưu hash có salt. Timestamps dùng UTC ISO-8601 do ứng dụng cấp; bảng mutable có `updated_at` và adapter phải cập nhật cùng transaction. Bảng nối, chunk và snapshot không cần timestamp sửa nếu được thay thế nguyên khối.

Xóa phiên chat kéo theo tin nhắn, trích dẫn và phản hồi. Xóa tài liệu kéo theo chunk/vector nhưng giữ snapshot trích dẫn bằng `SET NULL`. Tài khoản có thể vô hiệu hóa bằng `is_active`; tài liệu dùng `inactive`, danh mục dùng `is_active`. Không dùng soft-delete chung cho mọi bảng vì token cần thu hồi và dữ liệu chat cần xóa được. Trigger trước khi xóa tài khoản thay hash token các phiên chat bằng giá trị ngẫu nhiên trước khi FK đặt `account_id=NULL`, tránh biến phiên riêng tư thành phiên ẩn danh còn truy cập được.

Không lưu `chunk_count` làm nguồn sự thật; tính COUNT theo document. SQLite vẫn tìm cosine ở ứng dụng, không có vector index tự động. Chỉ so sánh embedding cùng `model_id`; đổi model phải tạo vector mới trước khi chuyển truy vấn sang model mới. Model ID phải biểu diễn phiên bản cụ thể nếu nhà cung cấp thay đổi model sau alias.

## Chỉ mục và truy vấn

- UNIQUE `(admission_year,campus_code,admission_code)` phục vụ lọc năm/cơ sở và JOIN điểm chuẩn; `cutoff_scores_method` phục vụ lọc phương thức.
- `messages_session_created(session_id,created_at,id)` hỗ trợ lịch sử có thứ tự ổn định và phân trang cursor khi cập nhật API.
- Index FK cho phiên đăng nhập, tác giả, chunk, embedding và trích dẫn; index thời hạn phục vụ thu hồi phiên và rate limit cũ.
- UNIQUE `(document_id,chunk_index)` đã có index tiền tố document, không tạo thêm index trùng.
- `search_text` là dữ liệu dẫn xuất có chủ đích, cần giữ cách chuẩn hóa nhất quán khi import/update (cutoffs dùng `search_key`; catalogue hiện giữ hành vi tìm kiếm có sẵn). B-tree không tăng tốc `LIKE '%từ%'`; chỉ bổ sung FTS sau đo đạc và xác minh cách tìm không dấu.
- Dùng `EXPLAIN QUERY PLAN` cho SQLite, không dùng `EXPLAIN ANALYZE` hoặc `CREATE INDEX CONCURRENTLY` của PostgreSQL. Đo lại trên bản sao dữ liệu thực trước triển khai.

## Bản bổ sung kế hoạch tuyển sinh

`planner_v1` bổ sung bốn bảng theo [DDL planner](../backend/schema/planner.sql) sau schema v2. Runtime thực hiện một lần trong transaction, giữ dữ liệu v2. Xem [tính năng và API](PLANNER.md); ERD README đã gồm các bảng mới.

## Bản bổ sung lịch sử hội thoại

`conversations_v1` bổ sung metadata, bookmark và hai chỉ mục FTS5 sau schema v2/planner; backfill dữ liệu cũ trong cùng transaction. Xem [DDL](../backend/schema/conversations.sql) và [hướng dẫn lịch sử](CONVERSATIONS.md).

## Chạy migration

Chạy từ `backend`, dùng đúng DATA_DIR của dịch vụ. Dừng backend, indexer và mọi tiến trình có thể ghi SQLite hoặc files trước khi áp dụng/rollback. Frontend có thể giữ nguyên; API tạm ngừng trong khoảng chuyển đổi.

```bash
cd /workspace/utc-rag-chatbot-/backend
# Chạy thử toàn bộ chuyển đổi và đối soát trên file tạm; không thay nguồn.
.venv/bin/python scripts/migrate_database.py --data-dir /workspace/utc-runtime/data
# Sau khi dừng mọi tiến trình ghi:
.venv/bin/python scripts/migrate_database.py --data-dir /workspace/utc-runtime/data --apply --offline
```

Nếu có vector cũ, bắt buộc chỉ rõ `--embedding-model MODEL_DA_XAC_MINH --dimensions 768` ở cả hai lệnh. Tên model phải được xác minh từ lịch sử lập chỉ mục, không suy ra từ biến môi trường hiện tại. Không thể xác minh hoặc có nhiều model trộn lẫn: dừng chuyển đổi để phân loại/tái lập chỉ mục riêng, không tự gán nhãn. Sau migration đặt `EMBEDDING_MODEL`/`EMBEDDING_DIMENSIONS` khớp dữ liệu cần truy xuất.

Chương trình mặc định chỉ chạy thử. `--apply` thiếu `--offline` bị từ chối; cờ offline là xác nhận vận hành, không phải công cụ dừng dịch vụ tự động. Database đã có marker `schema_v2` trả `already_v2` sau kiểm tra integrity/FK; không chuyển đổi lại.

### Quy trình thực thi

1. Nhận diện các bảng nguồn; bảng lạ chặn migration để tránh bỏ dữ liệu plugin. Tạo bản SQLite tạm bằng backup API, bao gồm dữ liệu đã commit còn trong WAL. Chỉ nâng các schema cũ trên bản tạm bằng `legacydb.prepare`.
2. Tạo schema v2 trong file mới. Giữ ID, password hash, token hash, thời hạn phiên đăng nhập, tin nhắn, feedback và tệp nguồn. Tài khoản `admins` cũ được ánh xạ như migration accounts_v1: admin/editor/viewer → admin/lecturer/student; token `admin_sessions` cũ không còn được dùng. Các bảng cũ vẫn nằm trong backup.
3. Tạo offering từ hợp khóa năm/cơ sở/mã của catalogue và cutoff. Catalogue giữ ID cũ; các offering chỉ có điểm chuẩn nhận UUID mới. Lưu tên nguyên văn của cutoff vào snapshot, không dùng danh mục 2026 để suy ra chương trình 2024/2025. Sửa khóa năm/cơ sở/mã của offering đã có cutoff bị từ chối; tạo offering mới để tránh di chuyển lịch sử điểm chuẩn.
4. Tách JSON phương thức/tổ hợp thành bảng nối có thứ tự. Chỉ mã chính xác PT1..PT4 được nhận diện; nhãn tự do được giữ nguyên và gắn mã hash riêng, không đoán ý nghĩa.
5. Chuyển vector vào model đã xác minh, kiểm tra số chiều/kiểu phần tử. Nguồn có tác giả mồ côi được đặt NULL và ID gốc được lưu trong báo cáo backup. Snapshot citation giữ nguyên mọi trường; liên kết chunk mồ côi thành NULL. Phiên gắn `users` cũ được chuyển sang `accounts` để giữ quyền riêng tư.
6. Đối soát số hàng và từng giá trị được API biểu diễn, JSON round-trip và khóa ngoại; kiểm tra `integrity_check`. `chunk_count` được tính từ chunks thay cho bộ đếm cũ; không dùng bộ đếm làm nguồn sự thật. Mọi lỗi chuyển đổi giữ nguyên database nguồn.
7. Khi apply, checkpoint WAL, chuyển journal sang DELETE và khóa nguồn; nếu dữ liệu đổi từ lúc chạy thử nội bộ thì dừng. Tạo thư mục `utc-v1-backup-*` cạnh DATA_DIR, quyền 0700, chứa database v1, bản sao `files/` và `migration.json`. Kiểm tra hash nội dung backup và từng tệp. Sau đó thay file database bằng thao tác rename trên cùng filesystem; tệp nguồn không bị di chuyển.
8. Khởi động backend phiên bản v2, kiểm tra `/health`, `/majors`, `/cutoffs`, tạo phiên và lịch sử; kiểm thử đăng nhập/chat trên môi trường có credentials phù hợp. Không tuyên bố AI hoạt động chỉ từ migration thành công.

Lệnh áp dụng trả đường dẫn backup cần giữ. Backup chứa dữ liệu tài khoản và lịch sử riêng tư; không commit hoặc công khai. Dừng ghi là điều kiện bắt buộc: khóa SQLite không bảo vệ tệp nguồn trước một tiến trình bên ngoài vẫn chạy.

### Rollback

```bash
# Dừng mọi dịch vụ trước; thay đường dẫn bằng backup trả về khi apply.
.venv/bin/python scripts/migrate_database.py --data-dir /workspace/utc-runtime/data \
  --rollback /workspace/utc-runtime/utc-v1-backup-EXAMPLE --offline
```

Rollback chỉ được thực hiện nếu nội dung database và files vẫn trùng thời điểm chuyển đổi; kiểm tra bao gồm dữ liệu trong WAL. Backup cũng phải giữ nguyên và vượt qua kiểm tra integrity/hash. Nếu đã có ghi mới, lệnh từ chối để tránh mất dữ liệu: cần export/đồng bộ dữ liệu phát sinh có chủ đích. Sau rollback phải chạy lại phiên bản ứng dụng v1 tương ứng; runtime v2 sẽ từ chối schema v1. Trước khi chuyển lại v1, lưu riêng bản v2 nếu cần điều tra.

### Phạm vi kiểm thử

`tests/test_migrations.py` kiểm tra chạy thử không đổi nguồn, apply, chạy lại, rollback, từ chối rollback sau ghi mới, model/số chiều sai, bảng lạ, quyền riêng tư phiên cũ và API sau chuyển đổi. `test_schema_v2.py` kiểm tra ràng buộc, vector và cascade/SET NULL. Bộ kiểm thử API hiện có chạy trên schema v2 với DATA_DIR tạm riêng cho từng test. Chưa xác minh dữ liệu production hoặc hiệu năng trên kho vector lớn.
