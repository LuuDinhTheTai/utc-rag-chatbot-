# Lưu và tìm lại hội thoại

Áp dụng [skill database-design](https://github.com/MoizIbnYousaf/ai-agent-skills/blob/main/skills/database-design/SKILL.md) cho schema bổ sung, khóa ngoại/cascade, chỉ mục tìm kiếm và migration trong transaction.

## Cách dùng

- **Đã đăng nhập:** mỗi cuộc trò chuyện mới gắn với tài khoản và tự lưu các lượt chat thành công. Mở **Lịch sử hội thoại** ở sidebar hoặc đầu khung chat để xem lại trên thiết bị đã đăng nhập khác.
- **Đặt tên:** tiêu đề mặc định lấy tối đa 80 ký tự từ câu hỏi đầu tiên; có thể đổi thành tên riêng tối đa 120 ký tự. Tên đã sửa không bị câu hỏi tiếp theo ghi đè. Danh sách sắp theo lượt chat gần nhất, không thay thứ tự chỉ vì đổi tên.
- **Tìm kiếm:** tìm trong tên hội thoại, câu hỏi hoặc nội dung câu trả lời; hỗ trợ không dấu, không phân biệt hoa/thường và tiền tố từ. Ví dụ `diem chuan` tìm được `Điểm chuẩn`, `dang ky` tìm được `Đăng ký`. Tối đa 12 từ và 200 ký tự mỗi lượt tìm. Các từ được kết hợp AND trong một tiêu đề hoặc một tin nhắn; không ghép từ rời rạc từ nhiều tin nhắn. Dấu câu không biến thành cú pháp tìm kiếm.
- **Lưu câu trả lời:** bấm “Lưu câu trả lời” cạnh phần phản hồi hữu ích. Tab “Câu trả lời đã lưu” cho phép tìm lại và mở đúng câu trả lời trong hội thoại, gồm nguồn trích dẫn gốc. Bỏ lưu không xóa tin nhắn.
- **Mở kết quả tìm kiếm:** khung chat tải một cửa sổ quanh tin nhắn được tìm thấy, đánh dấu vị trí đó. Có thể tải tin cũ hơn/mới hơn. Bấm “Về tin nhắn mới nhất” trước khi gửi tiếp để không nhầm ngữ cảnh đoạn lịch sử đang xem với phần cuối hội thoại.
- **Cuộc trò chuyện mới:** chỉ mở một phiên mới, không xóa các hội thoại đã lưu. Nút “Xóa” trong lịch sử yêu cầu xác nhận và xóa phiên cùng tin nhắn, trích dẫn, feedback, dấu lưu và mục chỉ mục liên quan. Backup trước đó có thể vẫn chứa dữ liệu cũ.

Khách tiếp tục dùng phiên gần nhất trên trình duyệt qua token đang có; chưa có danh sách nhiều hội thoại hoặc dấu lưu theo tài khoản. Đăng nhập không tự nhận quyền sở hữu phiên khách. Khi đăng nhập/đăng xuất, frontend xóa con trỏ hội thoại đang mở để tránh hiện nội dung của phiên tài khoản trước.

Sinh viên, Giảng viên và Admin có cùng quyền với **lịch sử của chính mình** trong chức năng này. API mới không cấp quyền xem lịch sử người khác cho Admin/Giảng viên. Luồng rà soát nội dung/phản hồi `/admin/review` có sẵn vẫn giữ phân quyền cũ; chức năng lịch sử không thay thế luồng quản trị đó.

## Lưu trữ và migration

`conversation_schema.ensure_conversations` chạy migration additive `conversations_v1` một lần sau schema v2 và planner. DDL: [`backend/schema/conversations.sql`](../backend/schema/conversations.sql). Cần SQLite có **FTS5**; đã xác minh trên runtime hiện tại. Nếu DDL/backfill lỗi, transaction rollback và không ghi marker hoàn thành.

| Thành phần | Vai trò |
| --- | --- |
| `chat_sessions`, `messages`, `message_citations` | Tiếp tục là nguồn dữ liệu chính; giữ ID, hash token và nội dung cũ |
| `conversation_metadata` | Tiêu đề, cờ tên tùy chỉnh, thời điểm lượt chat gần nhất; FK tới phiên |
| `conversation_bookmarks` | Dấu lưu tham chiếu tin nhắn trợ lý và tài khoản; không nhân bản nội dung hoặc trích dẫn |
| `conversation_message_search` | Cache FTS5 theo `messages.rowid` để tìm nội dung |
| `conversation_title_search` | Cache FTS5 theo rowid metadata để tìm tiêu đề |

Migration backfill metadata và chỉ mục cho mọi phiên cũ, kể cả phiên khách; việc lập chỉ mục không cấp quyền truy cập mới. Trigger đồng bộ chỉ mục khi thêm/sửa/xóa nội dung và tên, cập nhật metadata khi ghi tin, xóa dấu lưu khi đổi chủ phiên. Cache FTS không hỗ trợ FK trực tiếp nên được bảo trì bằng trigger; dữ liệu nghiệp vụ dùng FK/cascade và kiểm tra chủ sở hữu khi ghi bookmark.

FTS tokenizer `unicode61 remove_diacritics 2` bỏ dấu; ánh xạ thêm `đ/Đ → d/D` trước khi lập chỉ mục. Input tìm kiếm được tách thành từ, đặt trong dấu nháy và chỉ thêm toán tử tiền tố do server tạo; không chuyển nguyên chuỗi người dùng thành biểu thức FTS/SQL. Tìm kiếm không gọi Gemini và không gửi lịch sử cho dịch vụ ngoài.

Các thao tác tạo lượt chat hiện có vẫn ghi hai tin nhắn và trích dẫn nguyên tử. Lượt chat lỗi không được lưu thành một cặp hội thoại hoàn chỉnh; ô nhập giữ câu hỏi để gửi lại. Trigger tìm kiếm chạy trong cùng transaction nên không có mục tìm kiếm của lượt đã rollback.

## API và quyền truy cập

Tất cả endpoint `/conversations` yêu cầu Bearer token tài khoản đang hoạt động. Owner được lấy từ phiên đăng nhập, không nhận từ body. ID của tài khoản khác hoặc ID không tồn tại đều trả 404. Response lịch sử không trả token/hash phiên.

| Endpoint | Chức năng |
| --- | --- |
| `GET /conversations?q=&page=&page_size=` | Danh sách/tìm hội thoại riêng; mặc định 20, tối đa 50/trang |
| `GET /conversations/{id}` | Metadata của hội thoại sở hữu |
| `PATCH /conversations/{id}` | Đổi `title` |
| `DELETE /conversations/{id}` | Xóa hội thoại và dữ liệu con |
| `GET /conversations/{id}/messages` | Cửa sổ tin nhắn mới nhất, mặc định 50, tối đa 100 |
| `.../messages?before=ID` hoặc `after=ID` | Trang cũ hơn hoặc mới hơn, cursor là ID tin nhắn cùng hội thoại |
| `.../messages?around=ID` | Cửa sổ quanh kết quả tìm kiếm/dấu lưu |
| `GET /conversations/bookmarks?q=&page=&page_size=` | Tìm câu trả lời đã lưu của mình |
| `POST/DELETE /conversations/bookmarks/{message_id}` | Lưu/bỏ lưu một câu trả lời trợ lý thuộc phiên của mình |

Tin nhắn phân trang theo `(created_at,rowid)` để không bỏ/trùng tin khi timestamps bằng nhau. Response trả `next_before` và `next_after`; không giới hạn toàn bộ lịch sử ở 200 tin như endpoint guest cũ. Tìm thấy một tin xa ở đầu lịch sử vẫn mở được trực tiếp.

Các endpoint `/chat`, `/messages`, `/feedback` tiếp tục hỗ trợ `X-Session-Token` như cũ. Khi mở hội thoại tài khoản, frontend dùng **Bearer token + `X-Conversation-Id`**; chỉ biết ID không đủ truy cập. Không tạo lại hoặc xoay token phiên khi mở trên thiết bị khác, nên không làm mất phiên đang dùng ở thiết bị trước.

## Kiểm chứng

`tests/test_conversation_library.py` kiểm tra dữ liệu cũ, tính lặp lại/rollback migration, quyền giữa Student/Lecturer/Admin, tìm không dấu, đổi tên, thay nội dung cập nhật chỉ mục, bookmark và cascade, tìm/vượt qua nhiều trang tin có timestamp trùng nhau. `EXPLAIN QUERY PLAN` xác minh truy vấn tìm kiếm dùng FTS virtual index; kiểm tra integrity của FTS và FK.

Kiểm tra trình duyệt dùng database tách biệt và AI mô phỏng cho lượt chat: tạo hội thoại, đổi tên, tìm tiêu đề/nội dung, mở đúng tin, lưu câu trả lời, gửi tiếp, mở lịch sử dài, xóa và đăng xuất; kiểm tra cả desktop/mobile. Không suy ra Gemini thật hoạt động từ các kiểm tra lịch sử này. Chưa đo hiệu năng trên database production lớn.
