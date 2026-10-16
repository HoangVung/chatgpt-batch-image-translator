# Kiểm tra và chuẩn hóa bố cục trang sách

Chức năng hậu xử lý bằng Pillow, chạy offline. Không gọi ChatGPT/Gemini và không
thay đổi ba prompt, quá trình tải ảnh hay schema/trạng thái dịch trong progress.csv.

## Bật từ giao diện

Trong phần **Cấu hình** của sách đang chọn, bật **Nhất quán trang sách** rồi
bấm **Lưu cấu hình** (hoặc **Chạy**, thao tác này cũng lưu cấu hình).
Nút mặc định tắt, được lưu riêng cho từng sách và chỉ hiển thị với ChatGPT.
Khi sách đang chạy, nhóm cấu hình bị khóa giống các tùy chọn hiện có.

- Để trống **Mẫu bố cục**: dùng canvas 1600 × 2400 px, lề trái/trên/phải 100 px,
  lề dưới 140 px; kết quả hậu xử lý ở thư mục layout_results bên trong thư mục
  ảnh VN của sách.
- Hoặc chọn file JSON riêng để đổi khổ trang, lề và các ngưỡng. Có thể dùng
  layout_profile.example.json làm điểm bắt đầu. Nút gạt quyết định bật/tắt;
  khi bật, GUI dùng bản sao cấu hình với enabled: true, không sửa file mẫu.
- Mỗi lần chạy tạo bản sao cấu hình riêng để các sách không dùng nhầm mẫu.
  Thay đổi áp dụng từ lần chạy mới; phiên đang chạy không bị can thiệp.

Ứng dụng đang mở từ trước lúc cập nhật cần được mở lại sau khi các phiên hoàn
tất để nhận giao diện/backend mới. Không chỉ reload giao diện trong cửa sổ cũ.

## Cấu hình JSON và CLI

Khi chạy worker hoặc CLI trực tiếp, sao chép layout_profile.example.json thành
file riêng, đặt enabled: true và điều chỉnh khổ trang. Mặc định tính năng tắt.

- `target_size`: [rộng, cao], pixel.
- `margins`: [trái, trên, phải, dưới], pixel trên canvas đích.
- `content_region`: [x0, y0, x1, y1], nằm trong lề; null để dùng lề.
- `page_number_region`: vùng mẫu ở chân trang, hoặc null. Đây chỉ là hướng dẫn
  QC/xem lại. Khi khai báo vùng này, chuẩn hóa trả NEEDS_RELAYOUT vì không có
  dữ liệu đáng tin cậy để nhận diện, di chuyển hay vẽ số trang.
- `approved_sample`: đường dẫn trang tiếng Việt đã duyệt, cùng loại bố cục
  (mở bài/nội dung/kết thúc), hoặc null. Không mặc nhiên dùng trang Trung làm
  mẫu mật độ chữ hay chiều cao tiêu đề của bản Việt.
- `qc_enabled`, `normalize_enabled`: bật/tắt độc lập từng thao tác.
- `annotate`: lưu một bản đánh dấu riêng khi có vùng nghi vấn.
- `output_dir`: nơi lưu hậu xử lý. Đường dẫn tương đối được tính từ file JSON.
- `thresholds`: ngưỡng theo tỷ lệ 0–1; không phải pixel.
- `ink_luma_threshold`: ngưỡng xác định điểm tối trên nền giấy sáng.
- `max_pixels`: giới hạn số pixel của từng ảnh/canvas để hạn chế bộ nhớ.

Dùng đường dẫn tuyệt đối cho biến môi trường, ví dụ PowerShell:

~~~powershell
$env:BATCH_LAYOUT_PROFILE = 'G:\books\book-a\layout_profile.json'
py -3.12 .\run_chatgpt_batch.py
~~~

Worker Books 3–4 hỗ trợ cùng biến môi trường khi chạy trực tiếp.
Ứng dụng desktop bỏ biến môi trường layout được thừa kế, rồi truyền cấu hình
theo nút gạt của đúng sách. Vì vậy biến đặt trong shell không bật nhầm layout
cho các sách khác hoặc luồng đăng nhập/Gemini. Không cần sửa thủ công cấu hình
ứng dụng hay cấu hình tài khoản.

Bỏ biến để tắt hoàn toàn hook; không có biến thì worker không import module layout:

~~~powershell
Remove-Item Env:BATCH_LAYOUT_PROFILE -ErrorAction SilentlyContinue
~~~

Chỉ worker ChatGPT gọi hậu xử lý. Luồng Gemini giữ nguyên. Bản EXE đang cài đặt
không tự cập nhật theo source; chưa kiểm chứng tính năng này trong EXE đóng gói.

## Xử lý lại ảnh đã có

Một cặp ảnh:

~~~powershell
py -3.12 .\layout_pipeline.py --profile 'G:\books\book-a\layout_profile.json' --source 'G:\books\book-a\images\73_129.jpg' --generated 'G:\books\book-a\images_vn\00073_00129VN.png'
~~~

Các ảnh đã tải thành công theo bản ghi mới nhất của progress.csv:

~~~powershell
py -3.12 .\layout_pipeline.py --profile 'G:\books\book-a\layout_profile.json' --progress 'G:\books\book-a\images_vn\progress.csv' --source-dir 'G:\books\book-a\images' --generated-dir 'G:\books\book-a\images_vn'
~~~

Thêm `--qc-only` để chỉ kiểm tra. Profile vẫn phải có enabled=true.
Lệnh `--progress` chỉ đọc các cặp ảnh được ghi trong progress.csv và không gọi lại dịch.
Chế độ `--pair-by-page` mới chỉ ghép theo số trang khi được yêu cầu rõ bên dưới.
Dòng mới nhất có status khác done được bỏ qua. Mỗi lỗi xử lý được ghi riêng;
các trang còn lại tiếp tục chạy.

## Kết quả và giới hạn

Mỗi lần xử lý một trang tạo thư mục riêng dưới output_dir, có report.json,
report.csv, bản sao byte của ảnh ChatGPT ở original/, và nếu xử lý an toàn
được thì có normalized/page.png. Bản đánh dấu nằm riêng trong annotations/.
Không ghi đè ảnh nguồn, ảnh ChatGPT hay kết quả lần chạy trước.
Báo cáo có hash ảnh để đối chiếu; trạng thái QC tách khỏi trạng thái chuẩn hóa
và trạng thái dịch. Sau chuẩn hóa, báo cáo có kiểm tra QC lần nữa nếu QC bật.

Đoạn này mô tả chế độ giai đoạn 1 (`source_aware_enabled: false`).
Mục tiêu là các trang tiếng Việt nhất quán, cân đối và giữ cấu trúc sách gốc;
không yêu cầu khổ ảnh, số dòng hay mật độ chữ khớp từng trang tiếng Trung.
`target_size` là khổ chung do người dùng chọn cho bản Việt. Chênh lệch kích thước,
tỷ lệ và mật độ chữ với ảnh Trung được ghi trong `metrics.source_comparison`
để tham khảo, không làm tăng mức cảnh báo. Lề được kiểm tra như vùng an toàn,
không bắt buộc nội dung lấp đầy trang; QC cũng cảnh báo khi khối nội dung lệch
trái/phải rõ so với vùng đã cấu hình. Khi so lề với mẫu, bố cục đối xứng trái/phải
được chấp nhận để hỗ trợ trang chẵn/lẻ; đây không phải nhận diện số trang.
Lề/vùng nội dung khai báo rõ trong profile vẫn có hiệu lực riêng; profile có lề
trái/phải bất đối xứng không tự đổi bên theo số trang. Khoảng trắng dư bên dưới
không bị coi là lệch lề so với mẫu. Hình vẽ và họa tiết vẫn ảnh hưởng đến phép
đo cân đối vùng mực; phép đo này không xác nhận căn lề của riêng phần chữ.
Khoảng trắng lớn vốn có ở trang gốc không bị coi là bất thường chỉ vì mẫu
đã duyệt nhiều chữ hơn. So mật độ chữ chỉ áp dụng với mẫu Việt đã duyệt và vẫn
cần xem xét loại trang, độ dài nội dung. QC không tự phân loại trang hoặc xác
nhận phông/cỡ chữ và khoảng cách dòng đồng đều nếu chưa có OCR.

QC dùng kích thước, tỷ lệ trang, điểm tối, lề, khoảng trắng bên trong, vùng đầu/
chân trang và so sánh mẫu. PASS nghĩa là không phát hiện bất thường theo các
quy tắc này; **không bảo đảm dịch đúng, đủ chữ hay đúng công thức**. Nền màu,
giấy scan tối, hình vẽ lớn, trang mở đầu chương và trang thưa chữ có thể tạo cảnh
báo giả. Nên duyệt mẫu đại diện và điều chỉnh ngưỡng cho từng loại trang.

Chuẩn hóa chỉ thêm canvas trắng và dịch chuyển toàn bộ raster bằng số pixel
nguyên. Không resize, bóp méo, cắt, xóa hoặc vẽ lại nội dung. Ảnh quá lớn so với
canvas, không thể đáp ứng vùng nội dung, có yêu cầu sửa tiêu đề/số trang,
ảnh nhiều frame hoặc EXIF xoay cần xem lại: NEEDS_RELAYOUT hoặc lỗi QC giải thích
cụ thể. Không hỗ trợ thay cỡ chữ, sửa khoảng cách dòng hay dựng lại công thức.
RGB/RGBA được giữ nguyên pixel; các chế độ màu khác cần xem lại.

Khi tải ảnh đã hợp lệ và trạng thái dịch đã là done, lỗi layout không đổi trạng
thái dịch, không xóa ảnh và không gây retry ChatGPT. Nếu file cấu hình sai hoặc
không ghi được output_dir, worker ghi cảnh báo; không thể bảo đảm có báo cáo trên
đĩa trong trường hợp này. Có thể chạy lại CLI sau khi sửa lỗi.

CLI trả 0 khi xử lý không có cảnh báo (hoặc bị tắt), 1 khi cần xem lại bố cục,
2 khi có lỗi kỹ thuật. Không dùng mã thoát QC để quyết định dịch lại ảnh.

## Kiểm thử offline

~~~powershell
py -3.12 -m unittest discover -s tests -p 'test_layout_*.py' -v
~~~

Bộ kiểm thử dùng ảnh tổng hợp và worker với các thao tác trình duyệt được mock.
Không sử dụng quota thật. Cần duyệt trực quan một tập ảnh sách đã có trước khi
bật cho cả cuốn, đặc biệt đối với các trang có hình học, bảng và nhiều công thức.


## Giai đoạn 2: đối chiếu với trang nguồn

`source_aware_enabled` mặc định **false**. Đặt `enabled: true` và
`source_aware_enabled: true` trong bản sao profile để kiểm tra SOURCE/TRANSLATED.
Hoặc thêm `--source-aware` vào CLI đã có; cờ này chỉ bật đối chiếu nguồn,
không bỏ qua nút bật tổng `enabled`. `--qc-only` tắt tạo ảnh chuẩn hóa.
Không đổi worker, ba prompt, upload/download, retry/resume, tài khoản hoặc
schema progress.csv. Không phát sinh lượt gọi ChatGPT/Gemini.

Chế độ này tách sai lệch canvas khỏi sai lệch cấu trúc bên trong. Phân tích ảnh
bằng Pillow/OpenCV nhẹ (không OCR): ước lượng khung giấy, tọa độ vùng mực theo tỷ
lệ khung trang, header/body/footer, thành phần nét và chỉ dấu hình học/công thức.
Scan có viền, giấy tối hoặc nghiêng có thể làm giảm độ tin cậy. Nội dung không
bị kéo giãn/cắt/sửa; phép biến đổi chỉ dùng trong đo lường và ảnh đối chiếu.
Không đối chiếu pixel chữ Trung với pixel chữ Việt để kết luận mất nội dung.

### Cấu hình bổ sung và hiệu chỉnh

- `source_thresholds`: các ngưỡng tỷ lệ 0–1 độc lập với `thresholds` giai đoạn 1.
  Các giá trị mặc định là **đề xuất ban đầu, chưa phải ngưỡng đã hiệu chỉnh**.
- `aspect_warning`: sai lệch tỷ lệ canvas; `margin_warning`, `position_warning`,
  `width_warning`: lề, vị trí và độ rộng vùng nội dung tương đối.
- `header_footer_warning`: sai lệch vị trí đầu/chân trang.
- `density_warning`, `whitespace_warning`: mật độ/vùng trắng. Vùng trắng đã có
  trong nguồn không được tự động xem là lỗi hoặc tự lấp đầy.
- `geometry_size_warning`, `geometry_structure_warning`: chỉ dấu khác biệt vùng
  hình lớn; không xác nhận cấu trúc hình học đúng hoặc nhãn điểm đầy đủ.
- `typography_warning`: chênh lệch chỉ số thị giác chiều cao chữ/khoảng dòng;
  không phải phép đo cỡ font chính xác.
- `edge_warning`: dấu hiệu nội dung sát mép; `min_confidence`: độ tin cậy tối
  thiểu để kết luận theo phép đo. Dưới ngưỡng cần duyệt thủ công.
- `mirrored_layout`: mặc định true. `header_alignment` và `footer_alignment`
  nhận `mirrored` (lẻ bên phải, chẵn bên trái), `center`, `unconstrained`.
  Khai báo số trang in thật để áp dụng đúng quy tắc chẵn/lẻ.
- `approved_sample`: tiếp tục dùng trang Việt đã duyệt. `sample_page_number`
  khai báo số trang mẫu để không coi đối xứng chẵn/lẻ là lỗi.
- `canonical_header`: tiêu đề chuẩn tùy chọn. Chỉ so nội dung chữ khi manifest
  cung cấp `running_header` và `trusted_header_text: true` từ dữ liệu đã kiểm
  chứng. Không suy đoán chữ từ ảnh raster và không tự nhận dạng chữ bằng OCR.

Batch chưa có mẫu duyệt dùng trang dịch đầu tiên đủ tin cậy trong cùng nhóm
chẵn/lẻ và `page_type` làm mốc typography tạm thời. Mốc và đường dẫn được ghi
trong metadata/summary. Đây không phải quy chuẩn đã được duyệt; nếu không khai
báo `page_type`, các loại trang khác nhau có thể tạo cảnh báo. Nên cung cấp các
mẫu đại diện trước khi áp dụng cho cả cuốn, không điều chỉnh ngưỡng chỉ để năm
trang mẫu đều PASS.

### Một cặp trang hoặc hai thư mục

~~~powershell
py -3.12 .\layout_pipeline.py --profile 'G:\books\book-a\layout_profile.json' --source-aware --qc-only --source 'G:\books\book-a\source\23_023.jpg' --generated 'G:\books\book-a\vn\00023_00023VN.png' --page-number 9 --output-dir 'G:\books\book-a\qc'
py -3.12 .\layout_pipeline.py --profile 'G:\books\book-a\layout_profile.json' --source-aware --qc-only --pair-by-page --source-dir 'G:\books\book-a\source' --generated-dir 'G:\books\book-a\vn' --output-dir 'G:\books\book-a\qc'
~~~

`--pair-by-page` chỉ đọc ảnh ngay trong hai thư mục, không duyệt toàn bộ cây.
Tên ảnh phải có đúng **một nhóm số** như `page009.png` và `009VN.png`.
Không có số, nhiều nhóm số (`23_023.jpg`), số trang không dương hoặc trùng số
trong cùng thư mục sẽ bị từ chối, yêu cầu manifest. Ảnh nguồn/dịch chưa có cặp
được ghi rõ trong tổng hợp, không âm thầm bỏ qua. Đây chỉ kiểm tra số trong tên,
không chứng minh nội dung hai trang khớp nhau; cần kiểm chứng sơ bộ tập đầu vào.

`--page-number` là khai báo số trang in trên sách cho một cặp đã biết. Số này
được ưu tiên hơn số thứ tự lưu trong tên file. Nếu không khai báo, số trang
chỉ được suy ra khi mỗi tên có đúng một nhóm số. Số nguồn/dịch suy ra khác nhau
được ghi là ghép sai, không phân tích chúng như một cặp đã xác nhận.

### Manifest cho số trang in khác số thứ tự file

Ví dụ file `pairs.json`; đường dẫn tương đối được tính từ thư mục chứa manifest.
Không cần đổi tên ảnh gốc hoặc cấu trúc progress.csv.

~~~json
{
  "version": 1,
  "pages": [
    {
      "page": 9,
      "source": "source/23_023.jpg",
      "generated": "vn/00023_00023VN.png",
      "source_page_number": 9,
      "generated_page_number": 9,
      "page_type": "exercise"
    },
    {
      "page": 10,
      "source": "source/24_024.jpg",
      "generated": "vn/00024_00024VN.png",
      "page_type": "exercise"
    }
  ]
}
~~~

~~~powershell
py -3.12 .\layout_pipeline.py --profile 'G:\books\book-a\layout_profile.json' --source-aware --qc-only --manifest 'G:\books\book-a\pairs.json' --output-dir 'G:\books\book-a\qc'
~~~

`page` (hoặc `page_number`) là số trang in thật, bắt buộc, nguyên dương và duy
nhất. `source_page_number`/`generated_page_number` mặc định bằng `page`; nếu
khai báo phải khớp. Manifest rõ ràng được tin là ánh xạ đã xác minh, không ép số
thứ tự lưu trong tên file bằng số trang in. `generated` cũng có alias `translated`.
`source` có thể null hoặc trỏ tới file chưa có; báo cáo vẫn giữ nguyên ảnh dịch
và ghi lý do không thể đối chiếu. `running_header`, `canonical_header`,
`trusted_header_text`, `page_type` đều tùy chọn. Không đặt trusted=true cho văn
bản suy đoán. Không đưa ảnh mẫu hoặc đường dẫn cá nhân vào Git.

Lệnh `--progress` cũ tiếp tục dùng được với `--source-aware`. Cặp ảnh trong
progress.csv là ánh xạ đáng tin; cột `index` không được coi là số trang in. Cần
manifest nếu muốn kiểm tra chẵn/lẻ và tiêu đề theo số trang thật.

### Báo cáo và trạng thái

Mỗi cặp tạo thư mục `page-*` mới, không ghi đè kết quả cũ:

- `original/source.*`, `original/chatgpt.*`: bản sao byte của ảnh nguồn/dịch,
  kèm SHA-256. Nếu thiếu nguồn, không tạo bản sao nguồn giả.
- `comparison.png`: hai trang đặt cạnh nhau trong ô so sánh cùng kích thước,
  mỗi ảnh được thu/phóng đồng đều, giữ tỷ lệ và căn giữa; không kéo giãn.
- `evidence-overlay.png`: cùng hệ hiển thị, đỏ cho sai lệch đã xác nhận theo
  tiêu chí đo được, vàng cho nghi vấn, xanh cho vùng không đủ chứng cứ.
  Chỉ đánh dấu các vùng có tọa độ; nhận xét không có vùng nằm trong JSON.
- `report.json`/`report.csv`: chỉ số, ngưỡng, mức lệch, độ tin cậy, lý do,
  nguồn metadata và hướng xử lý. `qc.source_aware` bổ sung trạng thái chi tiết
  nhưng giữ lớp PASS/WARNING/FAIL cũ để tương thích.

Chế độ batch tạo thêm `batch-*/summary.json` và `summary.csv`, dẫn đến báo cáo
của từng trang, kể cả lỗi kỹ thuật hoặc thiếu cặp. QC không chỉ trả một điểm
số tổng hợp. `PASS` chỉ nói các tiêu chí đã đo không phát hiện vi phạm;
`WARNING` là sai lệch/nghi vấn; `FAIL` chỉ cho vi phạm chắc chắn theo tiêu chí
xác định được; `REVIEW_REQUIRED` nghĩa là không đủ chứng cứ;
`NEEDS_RELAYOUT` nghĩa là nội dung cần dàn lại. Những trạng thái chuyên biệt
nằm trong metadata và không đổi trạng thái dịch đã tải thành công.

Khác tỷ lệ/lề canvas có thể xử lý bằng normalization nếu toàn bộ raster vẫn
vừa khổ đích và vùng an toàn. Tiêu đề, hình hay công thức dịch chuyển/thiếu,
xung đột vùng, typography không nhất quán cần duyệt và có thể cần re-layout;
thêm canvas không khôi phục nội dung đã thiếu. Khi thiếu nguồn, QC nguồn ghi
REVIEW_REQUIRED, không xóa ảnh dịch hoặc kích hoạt dịch lại. Khi tắt source-aware,
hành vi giai đoạn 1 giữ nguyên.

### Giới hạn toán học và hướng tiếp theo

Phát hiện hình dùng dấu hiệu nét, vùng và kích thước. Các hình nằm sát chữ,
đồ thị nhiều nhãn, scan mờ hoặc hình có đường cong có thể bị gộp/tách sai.
Công thức chỉ được đánh giá bằng vùng và dấu hiệu cắt/xung đột, chưa nhận dạng
ký hiệu toán học. Các báo cáo không chứng minh định lý/công thức đúng, hình
vẽ đủ nhãn điểm, bản dịch đủ nội dung hoặc tiêu đề raster thống nhất. Cần duyệt
thủ công khi bằng chứng yếu và luôn kiểm tra nội dung toán học trước xuất bản.

`preserve_original_geometry` **chỉ là thiết kế tương lai, chưa triển khai**:
tách vùng hình nguồn kèm mặt nạ, ảnh gốc/hash, tọa độ, nhãn và caption liên kết;
tự đánh giá vùng đích bằng ngưỡng tin cậy, kiểm tra chồng lấn và ghép khi đủ điều kiện. Cần giữ tỷ
lệ, tránh đè chữ/công thức, dịch lại nhãn/caption cần thiết và ghi provenance.
Không phù hợp khi hình dính sát đoạn văn, scan kém, nhãn tiếng Trung nằm trong
hình, nền khác nhau hoặc cần thay cấu trúc hình. Khi không đủ bằng chứng hoặc không có vùng đặt an toàn, giữ ảnh hiện tại và
ghi lý do tự động bỏ qua; không tạo bước chờ người dùng. Không tự thay hình
chỉ vì thuật toán cho rằng chúng giống nhau.

`layout_rebuilder` nên là bước riêng sau khi có cấu trúc nội dung đáng tin:
văn bản Việt đã duyệt, công thức có biểu diễn xác minh được, hình nguyên bản,
thứ tự đọc, liên kết chú thích và mẫu trang chẵn/lẻ. Dựng bản mới, tự đối chiếu
với nguồn và chỉ chọn bản đạt các tiêu chí bảo toàn; nếu chưa đủ bằng chứng thì
giữ bản hiện có, ghi cảnh báo và tiếp tục. Không dùng ảnh raster đơn lẻ để khẳng
định đã khôi phục đủ nội dung. Task này không typeset lại hoặc tự sửa cỡ chữ.

### Cơ sở thuật toán và kiểm chứng trên mẫu thật (10/10/2026)

OpenCV và NumPy chỉ được import khi bật source-aware. Nếu môi trường thiếu
chúng, trả REVIEW_REQUIRED và giữ ảnh tải. Không tự cài thư viện, không gọi
OCR hay dịch vụ mạng. Phân tích dùng mặt nạ mực sáng/tối, thumbnail tối đa
1600 pixel cạnh dài, thành phần liên thông, phép chiếu dòng và mô tả phân bố
nét 12x12. Các giá trị confidence là mức tin cậy heuristic, không phải xác
suất đã được hiệu chỉnh thống kê. Dải scan gần đặc ở mép được bỏ khỏi phép đo;
nghiêng nhẹ được ước lượng trong +/-2 độ và cộng dung sai, không xoay ảnh gốc.

Header/footer ưu tiên nét trang trí hoặc đường kẻ liền, tránh lấy công thức
và chú thích trong thân trang làm footer. Nhiễu scan nhỏ được bỏ khỏi khung
body. Hình cắt qua ranh giới body/footer được xét theo tâm vùng; không tự coi
nó bị mất. Tiêu đề chỉ là ứng viên thị giác nổi bật, cách biệt; khi không ghép
được đáng tin thì chỉ số là REVIEW_REQUIRED. Vùng công thức là ứng viên chữ
độc lập, mặc định confidence thấp: báo vị trí, kích thước, vượt vùng nội dung
hoặc chồng hình nếu có dấu hiệu; không đủ để xác minh công thức inline/ký hiệu.

Để phân biệt thêm canvas với reflow, hai vùng mực có nội dung và kích thước
hoàn toàn giống nhau được nhận bằng SHA-256 mặt nạ mực trong bounding box.
Khi khớp, sai lệch tọa độ chỉ do canvas được ghi canvas_explained, không kết
luận phải dàn lại. Điều này không chứng minh nội dung dịch đúng. Ảnh chỉ khác
độ phân giải vẫn được đo bằng tọa độ tương đối.

Đã đối chiếu số trang in và manifest cho năm cặp thật 9–13; tên tệp dùng số
scan 23–27. Kiểm tra hash xác nhận cả 10 ảnh đầu vào không đổi. Không đọc hay
suy đoán trang 14. Không đưa ảnh mẫu vào Git.

| Trang | QC tiêu chí đo | Sai tỷ lệ canvas | Vùng hình nguồn/dịch | Ghi nhận |
| --- | --- | --- | --- | --- |
| 9 | WARNING | 10,59% | 3 / 3 | Canvas khác tỷ lệ; họa tiết header gần mép |
| 10 | PASS | 0,07% | 0 / 0 | Không cảnh báo khoảng trắng vốn có trong nguồn |
| 11 | WARNING | 11,46% | 2 / 2 | Vị trí hình thay đổi; tiêu đề metadata khác dấu câu |
| 12 | WARNING | 11,33% | 4 / 4 | Có khác biệt vị trí/kích thước/phân bố nét của vùng hình |
| 13 | WARNING | 13,27% | 3 / 3 | Vị trí hình thay đổi; tiêu đề metadata đổi 1/I và Các/Những |

Tiêu đề bài trang 11 đo được dịch dọc 5,32%; ngưỡng áp dụng 6,56% gồm dung sai
nghiêng. Chỉ số này PASS theo ngưỡng, vẫn cần người duyệt xét ý đồ bố cục.
Không sửa ngưỡng để ép kết quả mong muốn. Tiêu đề chuẩn metadata tạm dùng bản
chép thủ công trang 9/10; chưa phải quy chuẩn biên tập được duyệt. Số vùng hình
khớp kiểm tra bằng mắt không xác nhận đủ nhãn điểm hay quan hệ hình học.

Trạng thái bảo toàn nội dung toán học của cả năm trang vẫn REVIEW_REQUIRED.
Ngưỡng mặc định còn sơ bộ: năm cặp này là kiểm chứng thực tế có giới hạn, chưa
đủ để khẳng định độ chính xác trên cả sách. Cần nhãn duyệt và tập trang đa dạng
hơn để hiệu chỉnh false positive/false negative. Không tự thay hình, dàn lại
hoặc chỉnh font trong giai đoạn này.

### Vận hành tự động, không chờ can thiệp

Khi tính năng đã được bật trong cấu hình sách, mỗi ảnh ChatGPT tải thành công
được QC ngay bằng đúng ảnh nguồn worker vừa sử dụng. Worker tự truyền cặp ảnh;
không cần lập manifest, nhập số trang hoặc chép header cho từng trang. Các dữ
liệu bổ sung đó hoàn toàn tùy chọn, phục vụ các phép đo có đủ căn cứ tương ứng.
Tính năng vẫn mặc định OFF theo yêu cầu tương thích; bật một lần trong cấu hình,
không có bước duyệt giữa các trang. Với source-aware, profile cần
`source_aware_enabled: true`; bật nút giai đoạn 1 đơn thuần không tự bật cờ này.

`REVIEW_REQUIRED` trong JSON là nhãn **chưa đủ bằng chứng**, không phải một
trạng thái chờ người dùng. `NEEDS_RELAYOUT` cũng chỉ ghi nhận rằng bộ chuẩn hóa
canvas không khắc phục được theo quy tắc hiện có. Mọi trường hợp đều tự ghi báo
cáo, giữ ảnh đã tải và tiếp tục trang tiếp theo; không hiện yêu cầu duyệt, không
đổi done thành failed, không tự gọi ChatGPT lại. Metadata `automation` ghi rõ
`mode: unattended`, `blocks_batch: false`, `manual_action_required: false` và
`next_action: continue`. Người dùng không có thao tác bắt buộc từ báo cáo QC.

Nếu đã bật normalize, việc thêm canvas an toàn được thực hiện tự động. Khi
không thể sửa bằng thao tác bảo toàn pixel, chương trình giữ nguyên ảnh và ghi
lý do. Những đề cập duyệt nội dung trong tài liệu mô tả giới hạn xác minh và
việc kiểm tra chất lượng tùy chọn, không phải bước bắt buộc của luồng chạy.
Không suy đoán công thức/nhãn điểm đã đúng và không tự thay hình hay dàn lại
nội dung toán học khi chưa có cơ chế xác minh phù hợp.
### TASK 2D — QC theo vùng và hậu kiểm offline

`layout_regions.py` tái sử dụng các phép đo source-aware: HEADER, BODY_TEXT,
MATH_FORMULA, GEOMETRY_DIAGRAM, FOOTER, DECORATION, UNKNOWN. Mỗi vùng có bbox
pixel gốc và tọa độ tương đối trong page_frame, confidence heuristic, phương
pháp và counterpart_id hai chiều khi ghép được. Công thức/chữ độc lập chưa
phân biệt tin cậy giữ UNKNOWN. Phân loại dự đoán không phải ground truth;
`predicted_type` giữ nguyên khi có `independent_label`, còn `comparison_type`
cho biết loại được dùng để đối chiếu. Các vùng là ứng viên/envelope, có thể
chồng lấn và bỏ sót nội dung; không phải một phân đoạn ngữ nghĩa hoàn chỉnh.

Pipeline ghi thêm `region_qc` và `qc_accepted` khi enabled + source-aware + QC
được bật. Giữ các trường/trạng thái cũ, không đổi parser, profile hoặc worker.
HIGH_RISK và lỗi phân vùng không dừng worker, không retry, không đổi done thành
failed, không yêu cầu nhập liệu; ảnh gốc được giữ nguyên. `qc_accepted=false`
cho rủi ro cao, thiếu chứng cứ hoặc cảnh báo; giá trị true cũng không chứng
nhận dịch thuật/toán học. Feature OFF không gọi module vùng. Các nhóm rủi ro:
COSMETIC, LAYOUT, CONTENT_SUSPECTED, MATH_HIGH_RISK, UNKNOWN. Confidence chưa
được hiệu chỉnh thống kê; HIGH_RISK là ưu tiên hậu kiểm, không phải lỗi đã
xác nhận. Body dùng envelope/lề/mật độ thay vì đòi số dòng tiếng Việt giống
nguồn. Chẵn/lẻ chỉ tái dùng số trang in và template source-aware, không suy
số trang từ storage ID. Bìa màu ngoài mô hình giấy trắng giữ UNKNOWN.

Hậu kiểm sau batch: tạo tệp JSON riêng gồm `labels` là danh sách các đối tượng
`image_sha256`, `region` (bbox tương đối 0..1 theo page_frame), `type`, `reviewer`,
`basis`, `verified: true`. Nhãn chỉ áp dụng khi hash ảnh và bbox khớp; không tự
sao chép dự đoán vào nhãn. Dùng `--labels` với pilot, xuất thư mục mới. Nhãn mép
TASK 2C chỉ áp dụng tại đúng vùng đã hậu kiểm. Nhãn vùng còn thiếu nên không
báo accuracy/precision/recall. Ghép tên tệp chỉ xác nhận storage mapping, chưa
loại trừ sai nguồn/sai thứ tự trang; nghi vấn nội dung mã 6 không quy nguyên
nhân cho AI.

Chạy offline, không dùng quota:

```powershell
py -3.12 layout_region_pilot.py --task2b output/task2b-real-book-20261010-163729 --task2c output/task2c-qc-calibration --output output/task2d-new-run
py -3.12 -m unittest discover -s tests -p 'test_layout*.py'
```

Pilot dùng 142 ảnh thật/71 cặp và phép đo TASK 2C gắn với hash bất biến, lưu
thống kê, bảng trước/sau, hàng đợi hậu kiểm, nhãn riêng, ảnh side-by-side có
bbox/chú giải và kiểm tra derivative 2/42/64. Không ghi đè đợt cũ. Những phép
đo chuẩn hóa 2/42/64 được chạy mới; các cặp chính dùng cached evidence, không
khẳng định đã chạy lại segmentation trên toàn tập.

`rebuilder_input` chỉ cung cấp danh sách ID vùng nội dung/hình/công thức/header
footer/vùng chưa tin cậy. `ready_for_rebuild` luôn false. TASK 3 cần văn bản
Việt, thứ tự đọc và công thức đã kiểm chứng, hình nguồn/mặt nạ/nhãn/caption,
khung đặt không chồng lấn và quy tắc chẵn/lẻ đáng tin cùng tập nhãn vùng độc
lập đa dạng. Chưa triển khai engine, sửa chữ, công thức hoặc hình học.
### TASK 2E — Bằng chứng dịch và dataset phụ trợ

Hai worker có hook riêng, mặc định OFF. Bật một lần qua biến môi trường
`BATCH_TRANSLATION_EVIDENCE_DIR` trỏ tới thư mục sidecar; biến được dùng cho
cả phiên batch, không thêm thao tác từng trang. Nếu muốn dataset kèm vùng,
giữ cấu hình `BATCH_LAYOUT_PROFILE` source-aware từ TASK 2D. Không thay đổi
schema/profile/API/parser hoặc progress.csv; không tự bật cờ ở các phiên đang
chạy và không khởi động lại ứng dụng để thử tính năng.

`translation_evidence.py` dùng DOM read-only, giữ nguyên cơ chế chờ hiện có.
Session mới gắn với đối tượng page, nguồn/hash và token riêng. Mốc trước prompt
dịch chứa ID/role/text của lượt chép đã hoàn tất. Chỉ nhận đúng một cặp user
“dịch bản chép lại” và assistant mới ở cùng conversation, lịch sử cũ không
đổi, không còn nút Stop, hai snapshot liên tiếp giống nhau. Khi DOM thiếu ID,
lịch sử bị virtualize, lượt trả lời mơ hồ hoặc phản hồi chưa hoàn tất, ghi
EVIDENCE_INCOMPLETE. Không gửi prompt bổ sung, không OCR, không đổi retry.

Phản hồi được lưu trước bước tạo ảnh: textContent Unicode nguyên trạng, DOM
HTML, các block theo thứ tự DOM và annotation LaTeX/data-tex hoặc chuỗi LaTeX
literal có sẵn (giữ delimiter). Đây là biểu diễn thu thập từ DOM, không phải
raw Markdown từ provider. KaTeX có thể tạo text trùng; HTML và LaTeX gốc được
giữ riêng để hậu kiểm. Chuỗi LaTeX chỉ là ứng viên cú pháp, không phải danh mục
công thức hoàn chỉnh hoặc liên kết đã xác minh tới vùng raster. Không tự sửa
công thức hay coi văn bản ChatGPT là tiếng Việt đã kiểm chứng.

Sau khi tải/validate ảnh và ghi done theo workflow cũ, sidecar dataset liên
kết hash SOURCE, TRANSLATED, phản hồi và vùng QC; SOURCE phải không đổi so với
lúc bắt đầu. QC chỉ được ghép nếu source_sha256/original_sha256 khớp. Thiếu dữ
liệu hoặc lỗi lưu không retry/quota/pause; nhật ký ghi EVIDENCE_INCOMPLETE nếu
không thể lưu. Mỗi lần tạo thư mục UUID riêng; không ghi đè artifact cũ.

`layout_dataset.py` tạo `layout-ready-v1` độc lập: ảnh/hash, phản hồi/công thức/
block, vùng TASK 2D, metadata nguồn gốc, nhãn độc lập, crop ứng viên và readiness.
`COLLECTED_UNVERIFIED` chỉ nói đã thu thập; `CANDIDATE_UNVERIFIED` không chứng
nhận hình học. Crop nguồn lưu PNG ở mode gốc, không rotate/scale/chỉnh nhãn;
kiểm tra byte pixel giải mã khi mở lại và hash ảnh gốc trước/sau. Bbox sai,
orientation hoặc mode chưa hỗ trợ bị từ chối, không tự cắt sát/convert.
Không thay hình trong bản dịch; crop luôn `eligible_for_final_page=false`.

Hậu kiểm sau batch qua file `reviews` JSON riêng, mỗi record có source_sha256,
generated_sha256, evidence_sha256, regions_sha256, reviewer, basis,
verified=true và các check boolean tường minh: pairing, translation, formulas,
geometry, region_coverage, reading_order, page_template. Tất cả check phải được
kiểm chứng độc lập và hash khớp để READY_FOR_PILOT; thiếu công thức có vùng đã
biết, thiếu crop nguồn hoặc còn UNKNOWN/confidence thấp vẫn chưa READY.
QC không cảnh báo hoặc nhãn máy không thay thế các check. Các cảnh báo toán/
nội dung nghiêm trọng giữ HIGH_RISK_HOLD kể cả check chung được nhập; cần hậu
kiểm và xử lý căn cứ rủi ro ở giai đoạn sau, không tự phát hành. READY_FOR_PILOT
chỉ cho phép xem xét thử dựng trang, không cho xuất bản thành phẩm.

Pilot offline tái sử dụng 71 cặp TASK 2D; nếu không có text capture thật, ghi
thiếu bằng chứng, không tạo văn bản giả. Có thể dùng --evidence-dir cho các
artifact thu thập tương lai và --reviews cho nhãn độc lập; nhiều phản hồi
khác nhau cùng hash ảnh bị coi là mơ hồ, không chọn tùy tiện.

```powershell
py -3.12 layout_evidence_pilot.py --task2d output/task2d-region-qc-20261010/pilot --output output/task2e-new-run
py -3.12 -m unittest discover -s tests -p 'test_layout*.py'
```

Bộ đọc được kiểm thử bằng browser fixture offline cho DOM role/message ID
và search-unit/selection ID hiện có trong regression của dự án. Chưa có bằng
chứng hoạt động trên phiên ChatGPT thật trong TASK 2E; nếu provider thay DOM,
thu thập từ chối an toàn. TASK 3 vẫn cần văn bản/LaTeX/định danh hình đã hậu
kiểm, thứ tự đọc, ghép vùng và template trang đáng tin. Chưa có Layout Rebuilder.

## TASK 2F — Hậu kiểm capture và liên kết live

`layout_live_evidence.py` là công cụ offline độc lập; không mở trình duyệt,
không gửi prompt, không sửa dataset, progress hay quota. Kiểm tra tối đa 5 cặp,
đọc capture-audit-v1 của sidecar tương lai, dựng lại kết quả từ baseline và
snapshot ổn định, so ID lượt dịch, conversation, hash phản hồi, hash ảnh,
đường dẫn nguồn, token/phiên/trang/batch, dataset và vùng QC. Thư mục output
phải mới. Sidecar 2E cũ không có snapshot được giữ CAPTURE_UNVERIFIED.

CAPTURE_VALID chỉ xác nhận cấu trúc/byte/turn capture nhất quán. Nó không
chứng minh tiếng Việt đúng hoặc nguồn là phiên provider thật: fixture có thể
mô phỏng DOM. ASSOCIATION_VERIFIED còn cần một attestation độc lập có reviewer,
basis, hash dataset, conversation, user/assistant lượt dịch, ID phản hồi tạo
ảnh, hash source/generated/response, token, batch và trang khớp chính xác.
Không tự tạo attestation từ capture; chỉ ghi sau khi người hậu kiểm thực sự
quan sát nguồn, lượt dịch và ảnh tải từ đúng lượt tạo ảnh. Thiếu/mơ hồ giữ
ASSOCIATION_UNVERIFIED. Định danh page là tên file nguồn, không suy ra số trang
in; batch là đường dẫn root capture riêng cho batch. ID phiên là token cùng
đối tượng Playwright đã được gate ở 2E, không phải chứng thư provider.

Readiness tách khỏi capture: EVIDENCE_INCOMPLETE khi thiếu dữ liệu/review;
HIGH_RISK_HOLD ưu tiên nếu còn rủi ro nghiêm trọng; READY_FOR_PILOT chỉ khi
capture, association và mọi check độc lập 2E đều đạt. Không tự nâng nhãn vùng,
công thức, hình học, thứ tự đọc hay bản dịch thành verified. Mọi trạng thái
đều blocks_batch=false, eligible_for_final_page=false.

Inventory Unicode/LaTeX giữ nguyên text, HTML, thứ tự block, annotation/data-tex,
literal LaTeX, lớp KaTeX, sup/sub và số lần xuất hiện ký hiệu. Không gộp lớp
KaTeX, phục dựng raw Markdown, đoán công thức hay sửa nội dung. Ký tự thay thế
Unicode và thứ tự block bất nhất cần hậu kiểm. Hash có thể được tính lại bởi
người sửa file; đây là kiểm tra toàn vẹn và nhất quán, không phải chữ ký nguồn.

Pilot thật tối thiểu (CHƯA chạy; cần người dùng duyệt việc dùng quota):
1. Chọn 3–5 trang trong một batch mới, có tiếng Việt/toán/hình học; giữ cả
   source và file ảnh ChatGPT tải về. Ghi riêng ID batch và tên file trang.
2. Chờ worker hiện tại kết thúc. Trong môi trường khởi chạy workflow bình
   thường, đặt BATCH_TRANSLATION_EVIDENCE_DIR thành một thư mục tuyệt đối mới
   cho batch, ví dụ output/task2f-approved-capture-001. Không sửa profile/login
   hoặc khởi động lại worker đang hoạt động. Flag trong shell khác không tự
   truyền vào app đã chạy; app cần khởi chạy bình thường từ môi trường đó.
3. Chạy workflow vốn có với ba prompt nguyên trạng. Quan sát conversation,
   ID lượt dịch và ID lượt tạo ảnh; ghi bằng chứng thực tế để hậu kiểm. Không
   ép chạy lại các trang done, không dùng retry/prompt phụ cho việc thu thập.
4. Sau batch, chạy lệnh offline dưới đây. Mở dataset/ảnh nguồn/ảnh tải về và
   đối chiếu toàn trang: bản dịch, công thức, hình học và nhãn, thứ tự đọc,
   vùng thiếu, template; ghi reviews 2E đúng hash. Attestation theo mẫu output
   chỉ được hoàn thiện khi có quan sát thật; không điền true theo suy đoán.
5. Chạy hậu kiểm lần nữa vào thư mục mới với --provenance. Nếu cần bổ sung
   reviews, tạo dataset mới qua công cụ 2E và liên kết attestation tới hash
   dataset mới. Giữ HIGH_RISK_HOLD cho rủi ro chưa được xử lý độc lập.

```powershell
py -3.12 layout_live_evidence.py --dataset-root output/task2f-approved-capture-001 --output output/task2f-approved-review-001 --limit 5
py -3.12 layout_live_evidence.py --dataset-root output/task2f-approved-capture-001 --output output/task2f-approved-review-002 --limit 5 --provenance output/task2f-approved-review-001/provenance.json
py -3.12 -m unittest discover -s tests -p 'test_layout*.py'
```

TASK 2F hiện tại: không có capture live được tìm thấy trong output/run_configs
đã kiểm tra, flag shell trống. Tiến trình Python/browser có tồn tại nhưng
không chứng minh đang đăng nhập hay conversation nào hợp lệ. Chưa truy cập
phiên đó, chưa gửi prompt, chưa tiêu quota. Ngoài phạm vi thư mục đã kiểm tra
có thể có artifact khác; trạng thái phiên provider thật chưa xác minh.

## TASK 2I — Metadata provenance instrumentation (mặc định OFF)

`BATCH_PROVENANCE_EVENTS=1` bật hook chỉ cho ChatGPT và chỉ khi session đã được
khởi tạo bởi `BATCH_TRANSLATION_EVIDENCE_DIR`. Flag thiếu hoặc khác `1` không
đọc DOM, ghi log hoặc đổi hành vi worker. Không bật trong app_settings.json.
Không thêm prompt, sửa parser, send/wait/download, retry/resume/account/progress.

Metadata reader dùng allowlist root, ancestor (tối đa 3 cấp, dừng trước ancestor
chứa nhiều message), descendant (tối đa 24). Ghi role; data-message-id,
data-chatgpt-selection-message-id, data-dil-message-id/source-message-id;
parent/turn/container ID và conversation. Các thuộc tính khác, HTML, text,
cookie, access/session token và URL ảnh có chữ ký không vào metadata log.
`id` của container và `fallback-turn-*` không được dùng làm stable message ID.
Các candidate ID xung đột là AMBIGUOUS, thiếu trường là NOT_OBSERVED.

Hook ghi `provenance-events.jsonl` trong capture session:
1. translation_before_send: ngay trước thao tác gửi hiện có; token attempt mới.
2. translation_sent: sau verify_prompt_sent thành công, trước sleep hiện có.
3. translation_complete: sau wait trả True và capture 2E; reference/hash của
   translation-attempt-N.json để nối metadata với raw capture không sửa đổi.
4. generation_before_send: trước gửi prompt tạo ảnh, gắn translation attempt
   và generation attempt mới; baseline giữ phản hồi dịch vừa hoàn tất.
5. generation_sent: sau xác nhận gửi prompt tạo ảnh.
6. generation_complete: sau wait ảnh hiện có trả resource, kể cả ảnh đến muộn.
7. download_complete: sau downloader hiện có lưu file; path và SHA256 thực tế.

Từng event có phase, UTC timestamp, page/batch/source/session/attempt identity,
conversation, snapshot metadata/reference/hash và hash chain. Chỉ hai prompt
nguyên trạng `dịch bản chép lại`, `Tạo ảnh với bản dịch` được ghi exact/hash;
prompt chép không thêm instrumentation. Độ trễ đọc DOM là chi phí instrumentation
khi ON; không thêm sleep/poll hay thay timeout/wait hiện có.

Ảnh trong message được đọc asset ID thật từ data-asset-id/data-image-id/data-file-id
nếu UI cung cấp, kèm response identity và quan hệ DOM. Resource do downloader
chọn được đối chiếu bằng URL trong bộ nhớ; log chỉ lưu digest resource locator.
Digest này không phải stable asset ID, không thay thế observed asset identity.
Download hook ghi sau normalize/save của downloader cũ, không đổi byte hoặc cách
fetch, không hook network/auth. Không kết luận association từ tên file/thời gian/hash.

Giới hạn mỗi session: 200 message/snapshot, 12 ảnh/message, 64 event,
256 KiB/event, 4 MiB/log. Metadata bị cắt được đánh dấu; vượt giới hạn không ghi
thêm. Capture lỗi chỉ log phase và exception type, không stack/error nội dung;
worker tiếp tục. Event bị thiếu hoặc log bị cắt không được xem là chuỗi hoàn chỉnh.

`layout_live_evidence.py` tự đọc log cạnh translation-attempt-N.json khi audit
một dataset. Hậu kiểm kiểm tra chain/hash/source/generated/reference/prompt,
conversation/session/attempt, user/assistant ID ổn định qua các phase, response
mới, parent user→assistant và translation→generation, asset→response→download.
Nhiều attempt/phase bị lặp cần review và giữ PROVENANCE_UNVERIFIED; không chọn
ngầm lần cuối. Chuỗi đầy đủ chỉ đạt EVENT_CHAIN_CONSISTENT_UNVERIFIED. Không tự
cấp attestation/live origin, VERIFIED, READY_FOR_PILOT hoặc nội dung thành phẩm.
Giữ nguyên math extraction 2H và toàn bộ 66 node/LaTeX của fixture trang 114.

Cấu hình một trang chỉ chuẩn bị, chưa chạy:
`output/task2i-minimal-provenance-20261010/pilot-settings.template.json` giữ schema
settings đã có, batch_size=1, auto_next/account fallback OFF, source/output riêng
chưa có trang được chọn. `pilot-plan.json` chứa environment dự kiến, flag capture
và điều kiện preflight. Không tái sử dụng 114/115/116, không chạy script worker
hay xin quota trong TASK 2I. Cần phê duyệt riêng cho lần live mới sau offline QA.

TASK 3A có thể được đề xuất dưới dạng prototype offline trên artifact đã có,
phân biệt candidate/AMBIGUOUS và không xuất bản trang cuối; chưa triển khai ở 2I.
Muốn prototype dùng nguồn được xác minh, vẫn phải hoàn tất association/review
độc lập và adjudicate geometry/UNKNOWN/HIGH_RISK_HOLD trước đó.

## TASK 3A — Offline Book Layout Rebuilder

`layout_rebuilder.py` là CLI độc lập; không được gọi từ worker. Cấu hình riêng
`layout_rebuilder.example.json` không thay schema/API/parser/layout profile cũ.
Chromium cục bộ + native MathML đã lưu, Times New Roman/Cambria Math hỗ trợ
Unicode. Không CDN, không gọi provider, không cài dependency. LaTeX lưu nguyên
văn trong layout-report.json; MathML render thành công không xác minh nội dung.

Lệnh pilot từ repo (Python 3.12 có Playwright/Pillow):
```powershell
python layout_rebuilder.py --dataset output/task2g-live-resume-20261010-192802/capture/capture-50a0ac2d28e3424c9f8a40befdcab1c1/dataset/dataset.json --fixture tests/fixtures/layout_task2g_page114.json --profile layout_rebuilder.example.json --output output/task3a-page114-new-run
python -m pytest tests/test_layout_rebuilder.py -q
python -m py_compile layout_rebuilder.py
```
Output phải chưa tồn tại. Pilot đối chiếu hash dataset/capture/fixture/ảnh,
sau đó dùng bounded candidate của 2H, giữ HIGH_RISK_HOLD. Thiếu candidate
hoặc hash xung đột thì dừng, không dựng dữ liệu giả. Mỗi trang thử có nhãn
EXPERIMENTAL_UNVERIFIED. Crop chưa xác minh được giữ nguyên trong debug,
không ghép vào trang. UNKNOWN được liệt kê trong báo cáo.

Khổ target mặc định bám tỷ lệ ảnh scan, chưa phải trim in được duyệt; có thể
cấu hình height. Font/cỡ/lề cố định; không thu nhỏ để vừa trang. Phân trang
ở biên block, báo OVERFLOW nếu có preview nối tiếp. Block quá cao được giữ
trong HTML mở rộng và overflow-full-N.png, ngoài PNG khổ cố định. Chỉ số
continuation không tạo số trang sách mới. Không tự tạo chapter/page_number;
tên file 114 không chứng minh số trang in. Trang chẵn/lẻ theo page_number
được cấu hình có lề trong/ngoài đối xứng; parity chưa biết dùng template
mặc định, không coi là đã xác minh. Header bỏ trống nếu không có chapter,
tiêu đề nội dung vẫn giữ nguyên.

Kiểm tra browser đo text giữ nguyên, inventory math, biên MathML, nội dung
vượt vùng in và hình chồng text. Chưa có kiểm định nội dung/LaTeX–MathML,
phân trang trong đoạn, kiểm định crop đầy đủ hay hiệu chuẩn số đo typography
của raster nguồn. Không tuyên bố gần bản gốc hoặc đạt tiêu chuẩn in.
