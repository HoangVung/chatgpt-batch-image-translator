# Kế hoạch chuyển tài khoản khi hết quota tạo ảnh ChatGPT

Ngày: 2026-09-14. Trạng thái: đã triển khai bản đầu; chưa chạy E2E trên ChatGPT thật để cố ý làm hết quota.

Bản đầu hiện đã có: detector các câu báo hết lượt/đạt giới hạn tạo ảnh, chuyển giữa các profile ChatGPT đã đăng nhập trong cùng worker, chạy lại đúng ảnh đang dở, không ghi quota thành `fail`, checkpoint nguyên tử và trạng thái GUI riêng. Phần xác minh profile dự phòng là không tương tác: profile chưa đăng nhập sẽ được bỏ qua để thử profile kế tiếp.

## Quyết định chính

Khi có thông báo rõ ràng rằng tài khoản hiện tại đã hết lượt tạo ảnh, giữ nguyên ảnh đang xử lý, chuyển sang tài khoản đủ điều kiện tiếp theo trong danh sách đã chuẩn bị, xử lý xong ảnh đó rồi mới sang ảnh kế tiếp.

Phạm vi đã chốt: chỉ quan tâm thông báo hết lượt/đạt giới hạn tạo ảnh. Không phân tích thời gian reset, không lập lịch thử lại theo thông báo và không xây dựng xử lý riêng cho các câu phụ đi kèm. Có câu báo giới hạn rõ ràng là đủ để kích hoạt chuyển tài khoản, không cần thêm câu xác nhận khác.

Bản đầu chạy lại toàn bộ quy trình của **đúng ảnh đang dở**: chat mới → tải ảnh nguồn → chép lại → dịch → tạo ảnh → tải và kiểm tra kết quả. Các ảnh đã hoàn tất không bị chạy lại. Hết quota là trạng thái tạm chặn của tài khoản, không phải lỗi nội dung ảnh.

Bản tối ưu tiếp theo lưu bản dịch đã hoàn tất và gửi lại bản dịch cùng ảnh nguồn vào chat của tài khoản mới để tiếp tục từ bước tạo ảnh. Chưa chọn cách này làm mặc định ngay vì mã hiện tại chỉ xác nhận bước dịch thành công, chưa trích xuất/lưu toàn bộ bản dịch đáng tin cậy.

Tự tiếp tục được khi còn tài khoản dùng được. Khi toàn bộ tài khoản đều bị chặn hoặc cần đăng nhập, lưu tiến trình và chuyển sang trạng thái chờ; không hứa tạo ảnh liên tục trong trường hợp này.

## Căn cứ từ mã hiện tại

- `run_chatgpt_batch.py::has_clear_generation_error()` đọc toàn bộ `body` và tìm các cụm lỗi chung. Không đủ chính xác để quyết định hết quota: có thể nhầm lỗi mạng, câu trong ảnh nguồn hoặc thông báo cũ.
- `try_create_image()` có vòng chờ bắt đầu tới 120 giây, rồi gọi vòng chờ ảnh. Nhận diện quota phải có ở cả hai nơi và trước các lần gửi lại.
- `wait_image_generation_finished_or_image_ready()` chờ thêm 90 giây với lỗi chung. Quota đã xác nhận cần một nhánh riêng, không đi qua toàn bộ chu kỳ này.
- `main()` bắt mọi `Exception`, ghi `fail`, tăng số lỗi, và luôn tăng `completed_count` trong `finally`. Cấu trúc này phải tách sự kiện đổi tài khoản khỏi kết quả cuối của một ảnh.
- `get_job_state()` tách ảnh lỗi khỏi ảnh đang chờ. Nếu ghi quota thành `fail`, lần chạy chính tiếp theo có thể bỏ qua ảnh đó.
- `run_dich_step()` chỉ trả `True/False`; chữ ký phản hồi chỉ giữ độ dài và phần đuôi để nhận diện thay đổi, không phải bản dịch đầy đủ.
- Danh sách tài khoản hiện có `id`, `name`, `profile_dir`; chưa ghi thời điểm xác nhận đăng nhập, workspace hay trạng thái quota. Hàm chuẩn hóa tái tạo danh sách, nên cần thống nhất cập nhật theo ID và bảo toàn trường mới trước khi thêm trạng thái.
- GUI dùng thay đổi các ô cấu hình để đánh dấu can thiệp và hủy auto-next. Cập nhật tài khoản tự động từ worker phải có đường xử lý riêng để không bị coi là thao tác thủ công.

## 1. Nhận diện thông báo quota

Tạo bộ nhận diện riêng, trả kết quả có cấu trúc: có hết quota tạo ảnh hay không, phạm vi nếu xác định được, đoạn thông báo bằng chứng và thời điểm phát hiện.

Nguồn bằng chứng:

- Phản hồi assistant mới thuộc lượt yêu cầu tạo ảnh hiện tại.
- Thẻ công cụ tạo ảnh hoặc thông báo hệ thống đang hiển thị trong cuộc chat đó.
- Ghi dấu lượt chat/phản hồi và các thông báo hiện có trước khi gửi để phân biệt nội dung mới với nội dung cũ. Thông báo quota hệ thống tồn tại sẵn chỉ được dùng nếu còn hiển thị và rõ ràng đang chặn thao tác hiện tại.

Điều kiện:

- Phải có ý nghĩa hết lượt/đạt giới hạn gắn trực tiếp với tạo ảnh. Các mẫu tiếng Việt/Anh cần lấy từ thông báo thực tế; chỉ so khớp phần báo giới hạn tạo ảnh, bỏ qua các câu phụ.
- Xác nhận thông báo không phải nội dung người dùng, bản chép/dịch, trích dẫn, lịch sử cũ hoặc sidebar. Với phản hồi dạng văn bản, đợi đoạn báo giới hạn ổn định; đề xuất hai lần đọc cách nhau khoảng 2 giây để tránh kết luận từ văn bản đang sinh dở.
- Kiểm tra trong vòng chờ bắt đầu, vòng chờ ảnh và trước khi gửi lại. Mục tiêu kiểm thử: phát hiện thông báo rõ, ổn định trong khoảng 10 giây trên trang phản hồi bình thường; đây không phải bảo đảm độ trễ của dịch vụ.
- Ưu tiên thu hồi ảnh kết quả hợp lệ đã tạo trong lượt hiện tại trước khi đổi tài khoản. Nếu chỉ tải ảnh bị lỗi, thử tải lại trong phiên cũ trước.
- Không chuyển tài khoản vì nội dung bị từ chối, thiếu quyền workspace, lỗi mạng hoặc timeout không rõ nguyên nhân. Các trường hợp này có nhánh xử lý riêng.

### Mẫu tiếng Việt người dùng đã cung cấp

Ảnh người dùng cung cấp cho thấy thông báo có hai lớp bằng chứng cần hỗ trợ: một thẻ cảnh báo trong luồng chat và một đoạn giải thích nằm bên dưới. Detector không cần khớp toàn bộ giao diện; chỉ cần bắt được cụm giới hạn tạo ảnh ở một trong các vùng phản hồi mới, đúng lượt yêu cầu hiện tại.

```text
Bạn đã hết lượt tạo hình ảnh&#x20;
Bạn hiện đã hết lượt tạo ảnh.
Bạn đã đạt giới hạn yêu cầu tạo ảnh của gói Plus.
```

Cách nhận diện dự kiến:

- “Bạn đã hết lượt tạo hình ảnh” hoặc “Bạn hiện đã hết lượt tạo ảnh” trong thẻ cảnh báo là bằng chứng trực tiếp.
- “Bạn đã đạt giới hạn yêu cầu tạo ảnh” trong đoạn giải thích bên dưới cũng là bằng chứng trực tiếp; phần “của gói Plus” chỉ là thông tin gói, không phải điều kiện bắt buộc. Không suy ra quota Business từ tên gói trong mẫu.
- Chỉ cần một bằng chứng trực tiếp xuất hiện trong phản hồi mới của lượt hiện tại; nếu cả thẻ và đoạn giải thích cùng xuất hiện thì vẫn chỉ tạo một sự kiện quota, không chuyển tài khoản hai lần.
- Không cần quan tâm nút “Nâng cấp lên Pro”, giờ “12:05”, câu “sau 1 giờ” hoặc câu “Hiện tại tôi chưa thể gọi công cụ tạo ảnh…”. Các phần này không tham gia quyết định fallback.

Chuẩn hóa văn bản để so khớp: giải mã HTML entity như `&#x20;`/`&nbsp;` khi còn ở dạng chuỗi, chuẩn hóa Unicode NFC, khoảng trắng và chữ hoa/thường; giữ nguyên bản gốc làm bằng chứng. Không bỏ dấu tiếng Việt tùy tiện. Văn bản lấy từ DOM thường đã được giải mã; tránh giải mã lặp. Vẫn loại trừ những câu trên nếu nằm trong nguồn, yêu cầu người dùng, bản chép/dịch hoặc trích dẫn.

## 2. Danh sách tài khoản đủ điều kiện

Đã thêm lựa chọn “Tự chuyển tài khoản khi hết lượt tạo ảnh” và dùng thứ tự tài khoản trong danh sách. Mặc định bật cho luồng người dùng đang yêu cầu; vẫn có thể tắt.

Tách thông tin cấu hình khỏi trạng thái quan sát được:

| Nhóm | Dữ liệu đề xuất |
| --- | --- |
| Cấu hình | ID ổn định, tên, profile, có tham gia fallback, thứ tự, workspace đã chọn |
| Phiên đăng nhập | Trạng thái xác minh, lần xác minh gần nhất, định danh tài khoản/workspace nếu đọc được tin cậy từ UI |
| Giới hạn | Trạng thái hết quota tạo ảnh, phạm vi nếu xác định được, thông báo bằng chứng ngắn, thời điểm phát hiện |
| Điều phối | Tài khoản đang sử dụng, tài khoản đã thử trong đợt phục hồi, lý do bỏ qua |

“Đã đăng nhập trước” không đồng nghĩa phiên vẫn còn hiệu lực. Khi mở profile dự phòng, kiểm tra phiên và đúng workspace trước khi tải ảnh. Nếu phiên hết hạn, yêu cầu MFA, gặp CAPTCHA, profile đang bị khóa hoặc không xác định đúng workspace, ghi lý do và thử ứng viên khác với thời gian chờ hữu hạn. Nếu không còn ứng viên thì chờ người dùng xử lý.

Loại trừ profile trùng đường dẫn sau chuẩn hóa; nếu đọc được định danh, tránh thử lại cùng tài khoản và workspace qua hai tên profile. Không suy đoán mọi tài khoản Business có quota độc lập. Nếu thông báo xác nhận giới hạn chung cho một workspace thì loại tạm các ứng viên thuộc chính phạm vi đó.

## 3. Điều phối ngay trong worker

Giữ một worker sở hữu danh sách ảnh cố định của batch; chuyển browser context tại chỗ. Việc khởi chạy lại batch qua nút GUI sẽ làm phức tạp đếm tiến trình và lựa chọn ảnh.

Luồng đề xuất:

1. Nhận thông báo quota rõ ràng; kiểm tra có ảnh mới có thể tải về trước hay không.
2. Lưu nguyên nhân chặn của tài khoản và điểm phục hồi của ảnh hiện tại.
3. Ngừng mọi retry tạo ảnh trên tài khoản vừa hết quota; không tăng bộ đếm ảnh lỗi/hoàn tất.
4. Đóng browser context cũ để giải phóng profile.
5. Chọn tài khoản kế tiếp có phiên đã chuẩn bị, chưa bị chặn và chưa bị loại trong đợt phục hồi.
6. Mở context mới, xác nhận đăng nhập/workspace và cập nhật GUI qua sự kiện worker.
7. Chạy lại đúng ảnh hiện tại từ đầu ở bản đầu tiên.
8. Sau khi ảnh được lưu và kiểm tra hợp lệ, ghi `done` một lần, tăng tiến trình một lần, tiếp tục danh sách ảnh còn lại.

Tài khoản mới tiếp tục được dùng cho các ảnh sau; không quay lại tài khoản cũ sau mỗi ảnh. Quota không tiêu thụ bộ đếm retry lỗi ảnh thông thường. Mỗi ứng viên chỉ được thử một lần trong một lượt chuyển. Tài khoản bị quota được bỏ qua ở các ảnh/batch tiếp theo cho tới khi người dùng chủ động cho thử lại; không tự quay vòng về tài khoản đó.

Áp dụng cùng quy tắc cho chạy chính, chạy lại ảnh lỗi và chạy lại một ảnh. Trong chế độ chạy lại một ảnh có chủ đích, không tự bỏ qua ảnh chỉ vì đã tồn tại kết quả cũ; phải phân biệt kết quả trước đó với kết quả của lần chạy này.

## 4. Lưu tiến trình, kết quả và chờ quota

Tệp điểm phục hồi riêng trong thư mục output, ví dụ `job_checkpoint.json`, lưu:

- Phiên bản schema, ID job/batch, chế độ chạy, ảnh thuộc batch và vị trí hiện tại.
- Định danh nguồn và cấu hình công việc: đường dẫn, dấu vân tay ảnh, thư mục output, phiên bản prompt và tùy chọn thực sự ảnh hưởng nội dung.
- Tài khoản đang dùng, bước đang xử lý, các thử nghiệm phục hồi và thời điểm cập nhật.
- Trạng thái `running`, `switching_account`, `waiting_quota`, `needs_login`, `stopped` hoặc `complete`.

Ghi tệp bằng thay thế nguyên tử. Lúc tiếp tục phải đối chiếu với ảnh output thật; có file hợp lệ và đúng lần xử lý mới được xác nhận hoàn tất. Không chỉ tin bộ đếm trong JSON/CSV. Lỗi không lưu được điểm phục hồi cần dừng có thông báo, tránh tiếp tục mà mất khả năng phục hồi.

Nếu hết tài khoản dùng được:

- Giữ ảnh ở trạng thái chưa hoàn tất, không đẩy vào danh sách “ảnh lỗi” vì quota.
- Hiện “Tạm chờ: tất cả tài khoản đã hết lượt” hoặc “Cần đăng nhập”, kèm lý do từng tài khoản.
- Lưu trạng thái và chờ người dùng bổ sung tài khoản hoặc chủ động cho thử lại tài khoản cũ rồi tiếp tục; không tự hẹn giờ reset hay quay vòng các tài khoản vô hạn.
- Nút Dừng hủy quá trình chuyển và lịch auto-next hiện có. Đóng rồi mở lại app hiển thị điểm tiếp tục để người dùng chủ động chạy lại, không âm thầm gửi yêu cầu ngay khi mở app.

Phân biệt rõ “chờ tài khoản” với các exit code lỗi hiện tại. Đề xuất thêm exit code 4 cho kết thúc worker có thể tiếp tục (`job.state=waiting_quota` hoặc `needs_login`); xử lý trước quy tắc “không tiến triển” hiện có. Khi chỉ đang chuyển context trong cùng worker thì không kết thúc batch.

## 5. Giao diện và tính nhất quán

- Hiển thị tài khoản đang dùng thực tế, trạng thái từng tài khoản và thông báo chuyển; không hiển thị số lượt còn lại nếu chưa có bằng chứng.
- Worker gửi sự kiện JSON riêng, ví dụ `account_quota_exhausted`, `account_switched`, `job_waiting`, gắn ID job/batch/ảnh/tài khoản. Bộ đếm không phân tích những dòng chữ tự do về lỗi quota.
- GUI là nơi ghi cấu hình tài khoản; worker là nơi ghi điểm phục hồi của batch. Đồng bộ trạng thái qua sự kiện, tránh hai tiến trình cùng ghi đè `app_settings.json`.
- Cập nhật tài khoản tự động không kích hoạt callback can thiệp thủ công hay hủy lịch auto-next. Batch có ảnh phục hồi thành công vẫn được tính là batch thành công như bình thường.
- Việc dựng lại giao diện/đổi phong cách không làm mất tài khoản đang chạy, tiến trình, điểm phục hồi hay trạng thái chờ tài khoản.
- Thêm tài khoản mới khi đang chờ sẽ được xét ở lượt tiếp tục; danh sách đang được worker sử dụng là snapshot ổn định cho đợt chuyển hiện tại.

## 6. Tối ưu bằng bản dịch đã lưu (giai đoạn sau)

Sau khi cơ chế phục hồi toàn ảnh ổn định:

- Trích xuất đầy đủ đúng phản hồi dịch đã hoàn tất, gồm cấu trúc/công thức cần giữ; không dùng `last_tail` làm bản dịch.
- Lưu cùng dấu vân tay ảnh, cấu hình prompt và trạng thái xác nhận hoàn tất; không lưu phản hồi quota/từ chối làm bản dịch.
- Khi chuyển tài khoản, mở chat mới, tải ảnh nguồn và gửi toàn bộ bản dịch cùng yêu cầu tái tạo bố cục. Không chỉ gửi câu “Tạo ảnh với bản dịch” vào một chat chưa có ngữ cảnh.
- Chỉ dùng cache khi khớp nguồn và cấu hình. Cache thiếu/hỏng hoặc bản dịch quá dài chưa có cách chuyển đầy đủ thì chạy lại toàn bộ đúng ảnh đó.
- Kiểm chứng chất lượng ảnh, công thức, nội dung và bố cục với luồng gốc trước khi bật mặc định.

## 7. Thứ tự triển khai và tiêu chí nghiệm thu

1. Sửa nền tảng cập nhật/ghi danh sách tài khoản theo ID; bổ sung xác minh phiên và bảo toàn metadata khi tải/lưu/đổi tên/xóa khỏi danh sách.
2. Thêm detector quota tách biệt, dùng mẫu thông báo thực tế và trang chat mô phỏng.
3. Thêm điều phối chuyển context, retry đúng ảnh, tách bộ đếm lỗi và hoàn tất.
4. Thêm điểm phục hồi, sự kiện GUI, trạng thái chờ và đồng bộ auto-next.
5. Kiểm chứng end-to-end; sau đó mới tối ưu dùng lại bản dịch.

Các ca bắt buộc:

- A hết quota ở ảnh thứ 4/10, B chạy được: cuối batch đủ 10 kết quả hợp lệ, ảnh 1–3 không làm lại, ảnh 4 được tính hoàn tất đúng một lần.
- A rồi B hết quota, C chạy được: không bỏ sót ảnh hiện tại, không tăng lỗi giả, batch sau tiếp tục ở C.
- A báo quota nhưng ảnh hiện tại đã tạo xong: tải ảnh trước, chỉ đổi cho công việc tiếp theo nếu cần.
- Quota ở vòng chờ bắt đầu tạo ảnh và vòng chờ ảnh đều được phát hiện.
- Thông báo quota tiếng Việt/Anh, câu nằm trong nội dung nguồn, thông báo cũ và văn bản đang sinh dở được phân biệt đúng.
- Ba câu báo giới hạn tiếng Việt đã cung cấp nhận diện đúng sau chuẩn hóa `&#x20;`, khoảng trắng và Unicode; tên gói Plus không phải điều kiện bắt buộc.
- Câu báo giới hạn xuất hiện độc lập hoặc có thêm câu phụ đều kích hoạt cùng một luồng chuyển tài khoản; không phụ thuộc việc đọc được thời gian reset hay câu xác nhận khác.
- Lỗi mạng, timeout, từ chối nội dung, hết hạn đăng nhập và thiếu quyền workspace không bị gán nhầm thành quota tạo ảnh.
- Toàn bộ tài khoản bị chặn hoặc hết phiên: điểm phục hồi còn nguyên, không lặp vô hạn và không mất ảnh đang dở.
- Dừng/đóng app giữa lúc chuyển hoặc ngay sau khi tải ảnh: khi tiếp tục không bỏ sót hay ghi đè nhầm kết quả; chế độ chạy lại một ảnh vẫn giữ đúng ý định.
- Qua ranh giới batch, đổi phong cách hoặc mở lại app: trạng thái tài khoản bị quota không mất, tiến trình/auto-next không bị hủy bởi cập nhật nội bộ.

Test điều phối dùng browser và đồng hồ giả để không tiêu quota. Test tích hợp dùng trang chat mô phỏng với DOM/thông báo đại diện. Đã có mẫu văn bản tiếng Việt do người dùng cung cấp để xây dựng fixture; chưa có xác minh DOM live trong lượt này, nên chưa coi đó là bằng chứng detector chạy đúng trên ChatGPT thật. Mẫu tiếng Anh cần bổ sung riêng. Không cố dùng hết quota để kiểm thử.

## Nguồn và giới hạn xác minh

Kế hoạch và bản triển khai dựa trên mã tại `app.pyw`, `run_chatgpt_batch.py`, `progress_utils.py` và quy tắc `JOB_COMPLETION.md` của workspace hiện tại. Bản đầu đã triển khai các điểm điều phối nêu ở đầu tài liệu; các mục tối ưu dùng bản dịch lưu và xác minh DOM live vẫn là phần tiếp theo.

Đã tham khảo [tài liệu Pricing của OpenAI](https://learn.chatgpt.com/docs/pricing). Trang này mô tả nhiều luồng sử dụng, trong đó có Codex và tín dụng; không dùng số liệu đó để suy ra quota tạo ảnh cụ thể trong chat web của người dùng. Trong phạm vi nguồn đã kiểm tra chưa xác nhận được số lượt, chu kỳ reset hoặc mức chia sẻ quota cho các tài khoản Business đang dùng. Thiết kế lấy thông báo hiện hành làm bằng chứng và để trạng thái chưa biết khi không xác minh được.
