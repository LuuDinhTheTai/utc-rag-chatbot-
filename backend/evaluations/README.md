# Bộ đánh giá RAG cho kho dữ liệu cục bộ UTC 2026

`utc-2026-local.json` gồm 13 câu hỏi: 8 câu có đáp án trong hai tài liệu đang ở trạng thái `ready` tại cơ sở Hà Nội năm 2026 (hướng dẫn hồ sơ K67 và lịch nộp lệ phí), cùng 5 câu kiểm tra từ chối khi thiếu dữ liệu hoặc sai năm/cơ sở. `expected_answer` là đáp án tham chiếu để đọc và đối chiếu thủ công; script chỉ chấm nguồn trích dẫn, trạng thái hỗ trợ và các cụm từ trong `required_answer_phrases`.

Chạy từ thư mục `backend`, sau khi cấu hình kho dữ liệu, thư viện Python và khóa Gemini:

```powershell
python scripts/evaluate_rag.py evaluations/utc-2026-local.json --retrieval-only
python scripts/evaluate_rag.py evaluations/utc-2026-local.json
```

Hai tài liệu hiện cùng lưu `source_url=https://www.utc.edu.vn/`. Vì bộ chấm đối chiếu URL, một câu có thể được tính là tìm đúng nguồn khi lấy nhầm tài liệu còn lại. Chỉ số retrieval/citation của bộ dữ liệu này vì vậy là phép kiểm tra bước đầu, chưa đủ để kết luận chất lượng truy xuất theo từng tài liệu. Trước khi dùng số liệu trong báo cáo, cập nhật URL nguồn riêng cho mỗi tài liệu, mở rộng bộ câu hỏi và rà soát đáp án với nguồn gốc.
