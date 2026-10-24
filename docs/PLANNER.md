# Kế hoạch tuyển sinh cá nhân

Ba tính năng có trang và mục sidebar riêng: **Tính điểm xét tuyển** (`/score-calculator`), **Nguyện vọng cá nhân** (`/preferences`) và **Checklist & lịch** (`/checklist`). Có thể mở từ thanh bên, tài khoản hoặc liên kết **Lưu nguyện vọng** trong danh mục ngành. Tính điểm không cần đăng nhập; nguyện vọng và checklist được lưu theo tài khoản, không chia sẻ giữa người dùng, kể cả tài khoản quản trị.

## Tính điểm

- Chế độ tự tính: nhập ba điểm môn thang 10, ưu tiên **đã điều chỉnh** và điểm cộng để tính thử. Công cụ cộng ba môn, cộng hai khoản nhập vào rồi giới hạn kết quả ở 30. Đây là phép tính tham khảo, không tự xác nhận điều kiện hoặc quy chế năm đó.
- Công thức đã đăng: chọn đúng năm/cơ sở/tổ hợp. Mỗi môn có hệ số; điểm môn chuẩn hóa = `sum(điểm × hệ số) × 3 / sum(hệ số)`. Tùy công thức, ưu tiên là 0, do người dùng nhập sau điều chỉnh, hoặc giảm dần theo `ƯT gốc × min(1, max(0, (30 − điểm môn chuẩn hóa) / 7,5))`. Chế độ giảm dần này tính trên điểm môn **trước** điểm cộng. Tổng cuối = min(30, điểm môn + ưu tiên áp dụng + điểm cộng).
- Tính bằng Decimal; làm tròn hai chữ số ở kết quả, không làm tròn giữa các bước. Kết quả phân tách điểm môn, ưu tiên, điểm cộng, công thức và nguồn.
- Chỉ hỗ trợ phạm vi công thức trên cho điểm ba môn THPT. Không tự quy đổi chứng chỉ ngoại ngữ, học bạ, giải thưởng hoặc ĐGNL/ĐGTD; không kết luận trúng tuyển. Hệ thống không suy ra diện ưu tiên từ dữ liệu cá nhân.

Năm 2026, chế độ tự tính PT1 dùng công thức trong [thông tin tuyển sinh UTC](https://tuyensinh.utc.edu.vn/?q=tin-tuyen-sinh/th%C3%B4ng-tin-tuy%E1%BB%83n-sinh-%C4%91%E1%BA%A1i-h%E1%BB%8Dc-h%E1%BB%87-ch%C3%ADnh-quy-2026): các ngành khác Ngôn ngữ Anh tính `(Toán × 2 + môn 2 + môn 3) × 3/4`; Ngôn ngữ Anh tính tổng ba môn hệ số 1. Sau đó cộng ưu tiên đã điều chỉnh và điểm cộng do người dùng nhập, giới hạn 30 điểm. Công cụ chưa xác minh điều kiện xét tuyển hay quyền hưởng điểm cộng.

Quản trị viên có thể đăng quy tắc cho phạm vi khác ở cuối trang Tính điểm xét tuyển, nhập tổ hợp/môn/hệ số/cách ưu tiên/mức trần, URL thông báo UTC và phạm vi áp dụng, rồi xác nhận đã đối chiếu. Chỉ đăng nếu công thức của thông báo thực sự khớp cách tính được hỗ trợ.

Quy tắc đã đăng không sửa tại chỗ: thu hồi và đăng bản mới. Người dùng gửi ID đã thu hồi hoặc sai năm/cơ sở sẽ bị từ chối tính theo ID đó. Công thức đăng bởi quản trị viên không đồng nghĩa với việc hệ thống đã tự tải và xác minh nội dung nguồn.

## Nguyện vọng

1. Chọn năm và cơ sở tra cứu, tìm theo tên hoặc mã ngành, bấm **Thêm**. Có thể thêm từ liên kết ở `/majors`; người dùng vẫn xác nhận thao tác trên trang kế hoạch.
2. Dùng nút lên/xuống để sắp xếp. Lưu phương thức, tổ hợp, điểm tự ước tính, thang điểm và ghi chú. Tối đa 50 mục/năm trong công cụ này, không phải hạn mức nguyện vọng chính thức.
3. Sau khi tính điểm, mở mục Nguyện vọng cá nhân trên sidebar hoặc bấm nút chuyển trang ở kết quả và bấm **Điền điểm vừa tính** ở mục cùng năm/cơ sở, PT1 và thang 30, rồi **Lưu thông tin**. Không tự chuyển điểm giữa các phương thức/thang điểm.
4. Mở phần điểm chuẩn lịch sử để xem từng năm, phương thức, điểm/thang điểm, tên chương trình nguyên văn và nguồn. Ghép theo mã/cơ sở; tên hoặc chương trình có thể thay đổi giữa các năm. Không tính xác suất hay tự đối chiếu trực tiếp các thang khác nhau.

Đây là kế hoạch cá nhân, không gửi đăng ký tới hệ thống xét tuyển. Danh mục bị ẩn/xóa không xóa bản lưu cá nhân: hiển thị trạng thái cần đối chiếu. Thứ tự có revision, ghi/sắp xếp nguyên tử; nếu hai phiên cùng sửa, phiên cũ nhận 409 và cần tải lại để tránh ghi đè.

## Checklist và lịch

- **Thêm checklist gợi ý** tạo tối đa năm công việc chuẩn bị chung. Gọi lại không nhân đôi và không ghi đè việc đã chỉnh sửa. Các mục này không có hạn chính thức hoặc ngày mặc định.
- Thêm/sửa/xóa việc cá nhân, ghi chú, liên kết HTTPS và ngày tự đặt. Đánh dấu hoàn thành để theo dõi tiến độ. Tối đa 200 việc/năm.
- Cảnh báo quá ngày dựa trên ngày lịch Việt Nam (`Asia/Ho_Chi_Minh`). Đây là ngày do người dùng đặt, không phải xác nhận hạn trường/Bộ.
- **Xuất lịch .ics** xuất các việc chưa hoàn thành đã đặt ngày dưới dạng sự kiện cả ngày. Nhập file vào ứng dụng lịch rồi đặt nhắc việc tại đó. Chưa gửi email, push hoặc đồng bộ lịch tự động. File có ghi chú cá nhân nên cần được giữ riêng.
- ICS có UID ổn định, CRLF, escape nội dung và gấp dòng theo tối đa 75 byte UTF-8 để bảo toàn tiếng Việt, không cho ghi chú chèn thêm thuộc tính lịch.

## Database và API

Sau schema v2, `planner_schema.ensure_planner` tự chạy migration **additive** `planner_v1` trong transaction có khóa ghi, rồi ghi marker. Database cũ v1 vẫn cần migration v2 offline trước; không thay thế quy trình đó. Bảng mới không sửa/xóa bản ghi v2 và có FK cascade theo tài khoản. Khi phát hành, sao lưu DATA_DIR theo quy trình hiện có; lần kết nối đầu bổ sung bảng, lần sau bỏ qua.

| Bảng | Vai trò |
| --- | --- |
| `planner_revisions` | Revision danh sách nguyện vọng của tài khoản |
| `planner_preferences` | Thứ tự theo năm, phương thức, điểm tự nhập, ghi chú và snapshot chương trình |
| `planner_tasks` | Công việc cá nhân, ngày tự đặt, hoàn thành và khóa mẫu chống trùng |
| `admission_score_rules` | Công thức có nguồn/phạm vi do quản trị viên đăng và trạng thái thu hồi |

| Endpoint | Xác thực và hành vi |
| --- | --- |
| `GET /score-rules?year=&campus=` | Công khai, chỉ trả quy tắc đang sử dụng |
| `POST /score-calculations` | Công khai, ba điểm môn + ưu tiên/điểm cộng; `rule_id` không bắt buộc |
| `POST /admin/score-rules`, `DELETE /admin/score-rules/{id}` | Chỉ admin đăng/thu hồi |
| `GET/POST /planner/preferences` | Xem/thêm danh sách của mình; thêm cần `offering_id`, `revision` |
| `PATCH/DELETE /planner/preferences/{id}` | Sửa/xóa mục của mình; bắt buộc revision |
| `POST /planner/preferences/reorder` | Gửi `year`, `revision`, đầy đủ `ids` theo thứ tự mới |
| `GET/POST /planner/checklist` | Xem/thêm công việc của mình |
| `PATCH/DELETE /planner/checklist/{id}` | Sửa/xóa công việc của mình |
| `POST /planner/checklist/templates` | Gieo checklist cho `year`, không ghi đè |
| `GET /planner/calendar?year=` | JSON chứa nội dung ICS và tên file; cần token tài khoản |

Các endpoint planner lấy owner từ phiên đăng nhập, không nhận account ID từ client. ID thuộc tài khoản khác trả 404; đăng nhập không hợp lệ trả 401. Dữ liệu planner được xóa cùng tài khoản. Các giới hạn trường và số mục được kiểm tra phía server, không chỉ trên giao diện.

## Điều hướng và chuyển điểm

Mỗi trang chỉ tải tính năng tương ứng; sidebar đánh dấu trang đang mở. Năm/cơ sở và kết quả tính được giữ trong bộ nhớ trình duyệt khi chuyển giữa ba trang, gồm các đầu vào của phép tính đã hoàn thành. Đổi phạm vi sẽ xóa kết quả cũ; kết quả không được chia sẻ giữa các phiên đăng nhập. Tải lại toàn bộ trang sẽ xóa phép tính chưa lưu vào nguyện vọng; nguyện vọng/checklist đã lưu vẫn ở database.

Các URL cũ `/planner`, `/planner?view=preferences` và `/planner?view=checklist` chuyển hướng lần lượt tới ba trang mới, giữ các tham số năm/cơ sở/chương trình. Liên kết từ danh mục ngành và tài khoản dùng trực tiếp URL mới.
