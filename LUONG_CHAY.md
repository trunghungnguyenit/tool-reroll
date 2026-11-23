# Luồng chạy TFT Auto Buy

Tài liệu mô tả tool chạy từ file nào → file nào, theo thứ tự thực tế.

---

## 1. Khởi động tool

```
run.bat
  │
  ├─► Tìm Python (AppData\Local\Python\bin\python.exe)
  ├─► pip install -r requirements.txt
  └─► python main.py          ← ĐIỂM VÀO CHÍNH
```

| File               | Vai trò                                   |
| ------------------ | ----------------------------------------- |
| `run.bat`          | Script Windows: cài thư viện + gọi Python |
| `requirements.txt` | Danh sách thư viện cần cài                |
| `main.py`          | Điểm vào mỏng: `--selftest` hoặc mở giao diện |

---

### Đóng gói exe (`build.bat`)

```
build.bat
  ├─► pip install -r requirements-build.txt     (thư viện + pytest + ruff + pyinstaller==6.22.3)
  ├─► python -m pytest                          ← test hỏng thì DỪNG, không đóng gói
  ├─► python -m PyInstaller TFT_Auto_Buy.spec   (spec ghi core/_build_stamp.py: giờ build + mã commit)
  └─► dist\TFT_Auto_Buy.exe --selftest          (báo cáo ở %TEMP%\TFT_Auto_Buy_selftest.txt, lỗi thì báo)
```

- **Phiên bản `1.0.0.N`** nằm trong file `VERSION`. Mỗi lần đóng gói, spec so băm mã nguồn (`core/`, `ui/`, `main.py`, spec,
  `requirements.txt`) với lần build trước (`.version_hash`): code đã đổi thì N tăng 1, build lại không đổi code thì giữ nguyên.
  Build đầu tiên (chưa có `.version_hash`) giữ nguyên số. Ba số đầu tự sửa trong `VERSION` khi muốn nâng bản lớn/nhỏ. Hai file
  `VERSION` và `.version_hash` phải được commit để máy khác build tiếp đúng số. Chỉ đổi test/tài liệu thì không tăng.
- Mở app, dòng đầu Nhật ký chỉ ghi `Phiên bản: 1.0.0.1` (chạy từ mã nguồn: `1.0.0.1 (dev)`; exe đóng gói từ bản cũ: `không rõ`).
  Ngày giờ build và mã commit không còn ở Nhật ký, chỉ nằm trong báo cáo `--selftest` (dòng `phiên bản`).
- `data/` (config cá nhân, ảnh chụp, cache, log) nằm cạnh exe, được `.gitignore` bỏ qua hoàn toàn.
- Thêm file mới vào `core/` thì phải khai báo trong `hiddenimports` của spec **và** `selftest.CORE_MODULES`
  (`tests/test_build_files.py` bắt nếu quên).

---

## 2. Khi mở `main.py`

```
main.py → ui/app.py → run_app()
  ├─► core/single_instance.py → acquire_instance_lock()   (mutex 'Local\\TFTAutoBuy.SingleInstance')
  │     └─► đã có bản khác → activate_existing_window() đưa cửa sổ cũ lên trước (chờ tối đa 3 s nếu
  │         nó đang khởi động), không thấy cửa sổ thì hiện hộp thoại → THOÁT (mã 0), không ghi log/config
  └─► (bản đầu tiên) setup_logging() → QApplication → ensure_license() → MainWindow(make_controller).show() → app.exec()
                                                         └─► chưa có Key hợp lệ cho máy này: hộp thoại nhập Key, đóng = THOÁT
```

Chỉ một bản chạy mỗi phiên đăng nhập Windows, kể cả hai exe ở hai thư mục khác nhau. Khóa tự nhả khi tiến trình
thoát hoặc bị kill, nên không bao giờ kẹt khóa cũ.

Giao diện (PySide6/Qt) chỉ vẽ và chuyển thao tác; **mọi quyết định nằm ở `core/controller.py`** (không import Qt):
controller gửi sự kiện lên giao diện qua `notify(event, **data)`, việc ở luồng nền quay về luồng giao diện qua `post(fn)`.

Sau khi cửa sổ dựng xong, `AppController.start_up()`:

```
ui/main_window.py → QTimer → controller.start_up()
  ├─► ghi 'Phiên bản: 1.0.0.N' vào Nhật ký; báo config hỏng/đã sửa; báo vùng Shop bị xóa vì đổi hệ tọa độ
  ├─► register_hotkey()          → phím F8 (thư viện keyboard, gọi về luồng giao diện qua post)
  ├─► load_champions_async()
  │     └─► core/champions.py load_all_champions()   (MỌI mùa có trong Data Dragon, cả vi_VN và en_US — xem mục "Danh sách tướng")
  │           └─► API Riot Data Dragon (internet) → rồi fetch_portraits_async(): tải ngầm ảnh chân dung của MỌI thẻ
  └─► request_preview(capture_live=False)
        └─► data/shop_capture.png (ảnh chụp sạch lần trước, nếu có và khớp kích thước vùng)
```

### Giấy phép (Key xác thực, hoàn toàn offline) — `core/license.py`, `ui/license_dialog.py`

```
Người dùng mở exe (chưa kích hoạt) → hộp thoại "Cần Key xác thực" + MÃ MÁY (nút Sao chép)
   └─► gửi MÃ MÁY cho người bán
Người bán: python keygen.py issue <MÃ MÁY>   (công cụ NẰM NGOÀI repo, giữ khóa riêng, ghi sổ issued.csv)
   └─► gửi KEY (chuỗi dài, chỉ cần dán) cho người dùng
Người dùng dán KEY → activate(): chữ ký Ed25519 → đúng mã máy → chưa dùng → còn trong hạn 24h → lưu giấy phép
   └─► %PROGRAMDATA%\TFT_Auto_Buy\license.dat (DPAPI, gắn máy) + used_keys.dat (các key_id đã dùng)
```

| Yêu cầu | Cách thực hiện |
| ------- | -------------- |
| Không có Key thì không dùng được | `ensure_license()` trước khi dựng cửa sổ chính; bấm Bắt đầu (`controller._validate_start`) và bật quét (`ShopScanner.start`) kiểm tra lại |
| Key chỉ dùng cho đúng một máy | Mã máy (băm MachineGuid + serial ổ hệ thống) nằm trong phần được ký của Key |
| Dùng một lần | key_id đã kích hoạt được ghi vào `used_keys.dat`; nhập lại cùng Key bị từ chối |
| Hạn 24h kể cả chưa kích hoạt | `hạn nhập = lúc cấp + 24h` nằm trong phần được ký; so với giờ máy lúc kích hoạt |
| Kích hoạt xong dùng lâu dài | Giấy phép đã lưu không xét lại hạn nhập, chỉ xét chữ ký + mã máy |
| Chia sẻ exe / chép giấy phép sang máy khác thì không chạy | Giấy phép nằm NGOÀI exe, mã hóa DPAPI theo máy, và đối chiếu lại mã máy mỗi lần mở |

- Exe chỉ chứa **khóa công khai** (`PUBLIC_KEY_B64`): kiểm tra được chữ ký nhưng không tự tạo Key được. **Khóa riêng**
  (`private.key`) chỉ nằm trong thư mục công cụ cấp Key của người bán, ngoài repo (`.gitignore` chặn `*.key`); mất nó là không cấp
  được Key nữa, lộ nó là ai cũng cấp được Key.
- Xem lại giấy phép: **Nâng cao → Giấy phép** hiện trạng thái (✓ đã kích hoạt / ✗ lý do), Key ID và giờ kích hoạt. Chỉ xem, không
  có nút xóa/nhập lại; không bao giờ hiện chuỗi Key. **Mã máy không hiện ở đây**: chỉ hiện ở hộp thoại "Cần Key xác thực" khi
  máy chưa có giấy phép hợp lệ (lần mở đầu, hoặc sau khi cài lại Windows thì hộp thoại tự hiện lại với Mã máy mới).
- `--selftest` không cần máy đã kích hoạt: chỉ kiểm tra thư viện ký số, mã máy và DPAPI chạy được trong bản đóng gói.

### Giao diện (thư mục `ui/`)

| File                   | Vai trò                                                                                              |
| ---------------------- | ---------------------------------------------------------------------------------------------------- |
| `ui/main_window.py`    | Cửa sổ chính: thanh điều khiển, danh sách tướng, 'Sẵn sàng chạy?', vùng Shop, Nâng cao, Nhật ký        |
| `ui/champion_view.py`  | Danh sách tướng dạng thẻ ảnh hoặc chữ gọn (model + delegate tự vẽ, gõ tìm kiếm không dựng lại widget)  |
| `ui/overlay.py`        | Overlay chọn vùng / đặt 5 điểm click / xem lại trên màn hình thật; MỘT cửa sổ cho mỗi màn hình (đúng DPI từng màn hình), có kính lúp; lưu tọa độ vật lý lấy từ `GetCursorPos` |
| `ui/theme.py`          | Bảng màu sáng/tối (token) + stylesheet (kể cả nền `QDialog`/`QMessageBox`: không có rule này hộp thoại nền đen); `theme: auto` theo chế độ sáng/tối của Windows |
| `ui/widgets.py`        | `FlowLayout` (tự xuống dòng), `Switch` (công tắc), `ElidedButton` (chữ dài cắt bằng …)                  |
| `ui/app.py`            | Điểm vào: khóa một-bản-chạy, log, QApplication                                                        |

Bố cục tự đổi theo bề rộng (ngưỡng 900 px, vùng đệm ±40 px chống nhấp nháy). Chỉ CHUYỂN widget giữa hai bố cục, không dựng
lại nên kéo cửa sổ không giật. Nguyên tắc: **khung "Chọn tướng cần bắt" luôn được ưu tiên diện tích**.

- **Rộng**: thanh trên MỘT hàng (tên | chip sẵn sàng/số tướng/OCR/tốc độ | phím + nút BẮT ĐẦU); thân là hai vùng cạnh nhau, vùng
  Tướng chiếm mọi phần rộng thêm còn **cột phải cố định ~320 px** (kéo được trong khoảng 280–400 px).
- **Hẹp**: tên + nút ở hàng trên, chip xuống dưới; một cột với thanh tab dưới (1·Tướng, 2·Vùng Shop, 3·Chạy), không cuộn ngang.
- **Khung tướng**: hàng đầu = tiêu đề + đếm | ô tìm | Dạng chữ (hẹp: ô tìm xuống hàng dưới); một hàng lọc gồm chip cost, Đã chọn và
  chip mùa cỡ nhỏ (cao ~22 px) chung hàng và tự xuống dòng; lưới thẻ tự tính số cột theo bề rộng và **chia đều phần dư cho các
  cột** (thẻ lấp kín hàng), thanh cuộn dọc luôn hiện nên lọc/tìm không làm lưới chia lại; dưới khung chỉ còn MỘT hàng: Chọn tất cả /
  Bỏ chọn / Upload ảnh / Tải lại + công tắc nhận diện Ảnh/Tên (OCR) + nút "Tên gõ tay ▸" (ô nhập ẩn, tự hiện nếu đã có tên gõ tay).
- **Cột phải** gồm ba khối bấm tiêu đề để thu/mở: **Sẵn sàng chạy** (tự co thành một dòng "✓ Sẵn sàng chạy" khi đủ điều kiện, tự mở
  liệt kê khi thiếu), **Vùng Shop và điểm click** (ba nút ① ② 👁 cùng một hàng; thu lại lúc mở app nếu đã cấu hình xong, tự mở khi
  cấu hình hỏng/chờ xác nhận hoặc khi được dẫn tới bước đó), **Nâng cao** (mặc định đóng). Thu/mở của người dùng được giữ cho tới
  khi trạng thái đổi; KHÔNG nhớ giữa các lần mở app.
- **Nhật ký** ở dưới cùng, mặc định ĐÓNG: một dòng gồm tiêu đề, badge số dòng mới (cam khi có cảnh báo, đỏ khi có lỗi — phân loại
  bằng `controller.classify_log`), dòng mới nhất, nút Sao chép (lấy toàn bộ Nhật ký kể cả khi đóng). Bấm để mở (cao 120 px, hẹp 96 px)
  với Sao chép / Xóa / Cuộn cuối; mở ra thì badge được xóa. Có lỗi KHÔNG tự mở Nhật ký (không làm nhảy bố cục lúc đang chơi).
- Nút BẮT ĐẦU luôn bấm được: nếu thiếu điều kiện thì nút viền đứt, bấm vào sẽ báo thiếu gì và dẫn tới đúng bước (đổi tab hoặc mở và
  nháy khối tương ứng). Mỗi thay đổi (đổi chế độ, kéo thanh, gõ tên, chọn tướng) cập nhật danh sách điều kiện ngay lập tức.

---

## 3. Sơ đồ phụ thuộc giữa các file

```
                    ┌─────────────┐
                    │   run.bat   │
                    └──────┬──────┘
                    ┌──────▼──────┐
                    │   main.py   │  ← chỉ phân nhánh: --selftest hoặc ui.app.run_app()
                    └──────┬──────┘
                    ┌──────▼──────┐        sự kiện (notify) ┌──────────────┐
                    │ ui/ (Qt)    │◄────────────────────────┤ controller.py│  ← điều phối, KHÔNG import Qt
                    │ main_window │──── thao tác ──────────►│              │
                    └─────────────┘                         └──┬───┬───┬───┘
         ┌─────────────────────────────────────────────────────┘   │   └─────────────┐
         │                                                         │                 │
  ┌──────▼──────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────▼───┐   ┌──────────▼──┐
  │ config.py   │   │ champions.py│   │ preview.py  │   │ ocr_check.py│   │ hotkey.py   │
  └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
         │                 │
         │           ┌───────▼───────┐
         │           │  scanner.py   │  ← quét shop + mua
         │           └───┬───────┬───┘
         │        ┌──────▼──┐ ┌──▼────────────┐
         │        │ buyer.py│ │ name_matcher.py│
         │        └─────────┘ └────────────────┘
  ┌──────▼──────┐
  │ config.json │  ← lưu cấu hình shop, tướng đã chọn
  │ templates/  │  ← ảnh mẫu tướng
  └─────────────┘
```

---

## 4. Luồng cấu hình Shop (làm 1 lần cho mỗi màn hình)

```
Người dùng bấm "① Chọn vùng Shop"
  │
  └─► ui/main_window.py → _calibrate_region()
        ├─► thu nhỏ cửa sổ, chờ Windows vẽ xong, CHỤP từng màn hình (ở độ phân giải thật) và hiện RegionOverlay:
        │     một cửa sổ overlay cho MỖI màn hình, mỗi cửa sổ dùng ảnh chụp + hệ số DPI của chính màn hình đó
        │     (kéo khung có kích thước trực tiếp + kính lúp; khung quá nhỏ thì bỏ và cho kéo lại; Esc hủy;
        │      khung bị giữ trong MỘT màn hình — màn hình nơi bắt đầu kéo)
        ├─► controller.set_region(region)   → save_config() ghi shop_region (pixel VẬT LÝ từ GetCursorPos)
        │                                      + ghi bộ của màn hình chứa vùng vào monitor_profiles
        └─► controller.request_preview()    → core/preview.py build_shop_preview() → chụp + hiện preview

Người dùng bấm "② Đặt 5 điểm click"
  │
  └─► ui/main_window.py → _calibrate_clicks()        (chưa có vùng Shop thì báo và dẫn về bước ①)
        ├─► ClickOverlay: click lần lượt 5 ô, điểm ngoài vùng bị từ chối kèm thông báo, Backspace lùi 1 điểm
        ├─► controller.set_click_points()   → save_config() ghi slot_centers (5 tọa độ) + cập nhật bộ của màn hình
        └─► core/preview.py → build_shop_preview() → vẽ chấm đỏ 1→5

Người dùng bấm "👁 Xem trên màn hình"
  │
  └─► ui/main_window.py → _view_on_screen() → controller.view_plan()
        └─► ViewOverlay: hiện khung xanh vùng Shop + 5 chấm đỏ đánh số TRÊN MÀN HÌNH THẬT (đúng nơi tool sẽ chụp/click),
            chặn click: click bất kỳ hoặc Esc thì đóng. Chỉ xem, không đổi gì.
            (Màn hình chưa có bộ đã xác nhận: hiện GỢI Ý quy đổi, Enter/Space = dùng, click/Esc = bỏ qua.)
```

**Dữ liệu lưu tại:** `data/config.json`

### Nhiều màn hình: bộ vùng Shop riêng cho từng màn hình (`core/monitors.py`, `core/profiles.py`)

Tool chạy DPI-aware nên mọi tọa độ là pixel vật lý trên desktop ảo. `core/monitors.py` liệt kê các màn hình (Win32:
`EnumDisplayMonitors`, tên thiết bị, kích thước vật lý, % scale) và tìm màn hình đang chứa cửa sổ game. Mỗi màn hình có một **bộ**
(vùng Shop + 5 điểm click + hình chữ nhật của màn hình lúc lưu) trong `monitor_profiles`; khóa là `tên thiết bị|RộngxCao`.

```
controller.refresh_monitor()   (lúc mở app, lúc bấm BẮT ĐẦU, khi bấm Xem trên màn hình)
  ├─► màn hình cần dùng: chứa cửa sổ game → (game chưa chạy) màn hình đã cấu hình gần nhất → màn hình chứa vùng Shop → màn hình chính
  ├─► đã có bộ cho màn hình đó      → dùng luôn (chỉ sắp xếp lại màn hình: dịch cả bộ theo độ lệch, chính xác)
  ├─► chưa có bộ, nhưng có bộ khác → GỢI Ý quy đổi (không tự dùng) → trạng thái "chờ xác nhận": KHÔNG cho chạy
  │                                    cho tới khi bấm 'Xem và xác nhận gợi ý' (Enter) hoặc chọn lại ① ②
  └─► chưa có bộ nào                → bước ① ② như lần đầu
```

- **Quy đổi theo tỉ lệ** (`profiles.rescale`): giao diện game co giãn theo CHIỀU CAO màn hình và neo ở giữa-đáy, nên vùng được co theo
  tỉ lệ chiều cao quanh điểm giữa-đáy (màn 21:9 giữ shop ở giữa, không bị kéo giãn), rồi kẹp vào trong màn hình mới. Đây chỉ là ƯỚC
  LƯỢNG, vì thế luôn phải được người dùng xác nhận.
- Đổi độ phân giải của cùng một màn hình ra khóa khác → cũng cần xác nhận. Đổi % scale của Windows (không đổi pixel vật lý) thì không đổi gì.
- Cấu hình cũ (có `shop_region` nhưng chưa có bộ nào) tự được gắn với màn hình chứa vùng đó.
- Game ở chế độ cửa sổ (không toàn màn hình/borderless) thì vị trí shop còn phụ thuộc vị trí cửa sổ: tool chỉ biết màn hình, không biết
  cửa sổ nằm ở đâu trong màn hình — hãy chọn lại nếu dời cửa sổ game.

## 5. Luồng chọn tướng

```
Người dùng bấm thẻ / Space trên thẻ / gõ tên
  │
  └─► ui/champion_view.py → controller.set_selected()  → phản hồi ngay: thẻ viền xanh, chip 'n tướng đang chọn',
        │                                                danh sách 'Sẵn sàng chạy?' tính lại
        ├─► selected_names()      → từ thẻ đã tick (chưa tải được danh sách thì dùng lựa chọn đã lưu)
        ├─► parsed_manual_names() → từ ô gõ tay (tuỳ chọn)
        └─► target_names()        → gộp 2 nguồn trên (không trùng)
```

### Danh sách tướng: mọi mùa, hai ngôn ngữ (`core/champions.py`)

Data Dragon chỉ giữ dữ liệu tướng TFT từ patch 13.x trở đi, và **mùa cũ nằm ở các patch cũ** (patch mới nhất chỉ có vài mùa gần
đây; các patch trước 13.x trả HTTP 403). Vì vậy app quét từng patch rồi gộp lại:

```
load_all_champions(locale, on_update)        (luồng nền; mỗi bước gọi on_update để giao diện hiện sớm)
  ├─► 1. data/champions_catalog.json (nếu có)          → hiện NGAY, dùng được cả khi offline
  ├─► 2. versions.json → patch mới nhất (vi_VN + en_US) → hiện các mùa gần đây
  └─► 3. các patch cũ chưa quét (từ 13.x), 8 luồng song song → bổ sung mùa cũ, lưu lại catalog
        (lần đầu ~12 giây cho ~94 patch; các lần sau chỉ tải patch MỚI; patch lỗi mạng được thử lại lần mở sau;
         patch HTTP 403/404 được ghi nhận là "không có dữ liệu" để không hỏi lại)
```

- **Catalog**: mỗi tướng (theo id Data Dragon) lưu tên cả hai ngôn ngữ, cost, mùa, tên ảnh và patch mới nhất chứa nó (patch mới
  hơn luôn thắng). Ảnh dùng URL của chính patch đó nên ảnh mùa cũ vẫn tải được.
- **Mỗi TÊN một thẻ** (`merge_champions`): tướng ở nhiều mùa chỉ hiện một thẻ, ghi mọi mùa của nó (`M18 · M17 +2`, đủ ở tooltip);
  cost và ảnh lấy từ mùa mới nhất. Tên viết hơi khác ('RekSai' ở bản sự kiện, "Rek'Sai" ở bản mùa) được gộp. Tướng chỉ có ở tutorial/sự
  kiện vẫn hiện ở **Tất cả**, nhãn 'Sự kiện', và biến mất khi chọn một mùa cụ thể.
- **Chọn mùa**: thay nút 'Mùa cũ' bằng hàng chip **Tất cả · M18 · M17 …** (tự lấy từ dữ liệu nên mùa mới ra tự có chip; chọn nhiều
  mùa được = hợp của các mùa; bỏ mùa cuối cùng thì về Tất cả). Mặc định Tất cả. Lưu ở `season_filter`.
- **Tìm kiếm luôn tìm trong MỌI mùa**, bỏ qua chip mùa (xóa ô tìm thì chip mùa áp dụng lại). Khớp chuỗi con trên tên tiếng Việt hoặc tên
  tiếng Anh, không phân biệt hoa/thường, dấu tiếng Việt, dấu nháy và khoảng trắng ('khazix' ra Kha'Zix). Cost và 'Đã chọn' vẫn áp dụng.
- Lựa chọn (tick) được giữ nguyên qua mọi lần nạp lại danh sách và khi đổi chip mùa; tướng đã chọn nhưng đang bị chip mùa ẩn vẫn được bắt.
- `data/champions_cache.json` (tên + alias cho so khớp OCR) cũng được ghi từ catalog nên chứa tên của mọi mùa.

Bộ lọc danh sách (`controller.filtered()`): tìm kiếm tức thì, chip mùa, chip Cost 1g–5g (cost không có thì mờ), 'Đã chọn'; chuyển giữa
thẻ có ảnh và danh sách chữ gọn bằng nút 'Dạng chữ'. Đổi bộ lọc chỉ nạp lại dữ liệu của model, không dựng/hủy widget nào. Chọn tất cả /
Bỏ chọn tác động đúng các tướng đang hiển thị (kết quả tìm kiếm thì gồm cả các mùa khác).

Khi bấm **Upload ảnh** (cần đúng 1 tướng được tick):

```
ui/main_window.py → _upload() → controller.upload_template()
  └─► copy ảnh → data/templates/custom_{TênTướng}.png
  └─► core/config.py → save_config()  → custom_templates
```

---

## 6. Luồng bắt tướng (F8 / BẮT ĐẦU)

Đây là luồng chính khi đang chơi game:

```
Người dùng bấm F8 hoặc "BẮT ĐẦU"
  │
  └─► controller.toggle()                 (bỏ qua nếu đang chuẩn bị nền)
        └─► start()
              ├─► _validate_start()       (requirements(): thiếu gì thì phát sự kiện 'blocked' → giao diện dẫn tới bước đó)
              ├─► [thread nền] core/ocr_check.py → check_ocr()   (khi bắt theo tên: vẽ chữ mẫu rồi đọc thử;
              │                                                   OCR hỏng → chặn, hoặc chạy bằng ảnh nếu có ảnh mẫu)
              ├─► [thread nền] core/champions.py → download_template()  (tải ảnh nếu chưa có)
              └─► _finish_start()         (lại trên luồng giao diện, qua post)
                    ├─► core/scanner.py → build_templates()  (chuẩn bị ảnh mẫu)
                    └─► core/scanner.py → ShopScanner(...)   (tạo engine quét)
                          └─► scanner.start()
                                └─► thread nền: scanner._loop()   ← chạy liên tục
```

Trong lúc quét, mỗi vòng OCR: lỗi OCR (ngoại lệ, quá hạn, thiếu engine) được ghi lại và báo 1 lần cho mỗi nội dung;
nếu ≥ 4/5 ô đọc rỗng liên tục 30 giây khi game ở foreground thì cảnh báo 1 lần (vùng Shop lệch hoặc OCR hỏng),
và báo 1 lần khi đọc lại được. Nhãn 'OCR: ...' dưới nút BẮT ĐẦU phản ánh tình trạng này.

OCR 5 ô chạy song song trên 5 luồng DAEMON (`core/ocr_pool.py`) với MỘT hạn chung 2 giây cho cả đợt (bình thường
~10 ms). Đợt quá hạn thì ô chưa xong coi như rỗng, báo "OCR bị kẹt" 1 lần, và các lượt sau BỎ QUA OCR (không dồn việc
vào pool đang kẹt) cho tới khi luồng kẹt trả về — lúc đó tự dùng lại và báo "đã hồi phục". Bắt theo ảnh vẫn chạy.
Bấm DỪNG được kiểm tra mỗi 50 ms trong lúc chờ OCR. Luồng là daemon vì ThreadPoolExecutor làm tiến trình KHÔNG thoát
được khi một lần OCR treo (và tiến trình còn sống sẽ giữ khóa một-bản-chạy).

Chu kỳ quét thực được đo và hiển thị dưới ô 'Chu kỳ quét tối thiểu' (cập nhật mỗi giây, và 1 dòng tổng kết trong
Nhật ký khi dừng: số vòng, trung bình, p95, chậm nhất). Ô chỉ là mức TỐI THIỂU: vòng không bao giờ nhanh hơn thời
gian chụp màn hình (~7 ms trên máy thử, gần như không đổi theo kích thước vùng), nên các giá trị 0–7 ms cho kết quả
gần như giống nhau; từ khoảng 10 ms trở lên mới thấy rõ (30 ms cho đúng ~30 ms/vòng). Bắt theo tên còn có các đợt OCR
(mỗi `name_scan_interval_ms`) làm vài vòng chậm 25–75 ms.

Mỗi lần mua (`_buy_batch`), scanner kiểm tra: game đang ở foreground (`core/game_window.py`) → chụp lại shop **một lần cho cả
loạt ô trúng** và so từng ô với khung đã nhận diện (shop chưa roll) → ô chưa bị khóa → mới gửi lệnh click cho luồng click
(`core/buyer.py`), luồng này click cả loạt liên tiếp rồi trả chuột về MỘT lần (không chặn luồng quét).

### Tối ưu tốc độ khi roll liên tục

Đo thật trên máy thử (vùng 1200x200): chụp bằng `mss` mất **~11 ms mỗi lần bất kể vùng lớn hay nhỏ** (chụp 8x8 vẫn ~8 ms),
OCR 5 ô ~13 ms, so khớp ảnh 5 ô ~4 ms, chữ ký 5 ô ~1 ms. Từ đó:

| Khâu | Trước | Nay |
| ---- | ----- | --- |
| Chụp mỗi vòng và chụp xác nhận trước click | `mss` ~11 ms, xác nhận chụp lại **mỗi ô** | DXGI ~1 ms (`core/capture.py`), xác nhận **một lần** cho cả loạt |
| Click | chặn luồng quét 30 ms (chờ trả chuột) | luồng click riêng, trả chuột một lần sau cả loạt |
| OCR | mỗi 50 ms cả 5 ô, chen vào vòng quét | chỉ ô VỪA ĐỔI thẻ (ngay lập tức), ô còn đang ổn định (0,6 s, chữ hiện dần) theo chu kỳ, và quét cả 5 ô mỗi 0,5 s làm lưới an toàn |
| Nhánh ảnh | chờ OCR xong mới mua | mua ngay sau khi so khớp, trước OCR |
| Shop đứng yên | xử lý lại mọi khung | khung y hệt khung trước thì bỏ qua chữ ký và so khớp ảnh (CPU giảm khoảng 3 lần trong phép đo) |

**Chụp DXGI với dự phòng mss.** `capture_backend: auto` (mặc định) thử DXGI trước: chọn đúng màn hình/adapter chứa vùng Shop
(theo tọa độ desktop), đổi sang tọa độ cục bộ, rồi **so khung DXGI với ảnh `mss` của cùng vùng**; khác hoặc đen (thường do game
fullscreen độc quyền) thì không dùng DXGI. Khi chạy còn đối chiếu định kỳ mỗi 3 giây, lệch 2 lần liên tiếp thì tự quay về `mss`.
Lý do được ghi vào Nhật ký: `Chụp màn hình: DXGI (...)` hoặc `Chụp màn hình: mss — không dùng được DXGI: ...`. Đặt
`capture_backend: mss` (mục Nâng cao) để luôn dùng `mss`.

**Phím roll.** `roll_key` (mặc định `d`, cho đổi ở Nâng cao, rỗng = tắt): bấm thì scanner không chờ chu kỳ OCR và vòng quét
không nghỉ thêm trong 0,5 giây. Phím vẫn tới game (không chặn). Trong mô phỏng thì phím này chưa cho lợi ích đo được vì phát hiện
thay đổi bằng chữ ký đã nhanh, nên chỉ giữ như một tùy chọn.

**Đo và chẩn đoán trong Nhật ký.** Mỗi lần mua có thêm một dòng
`↳ Vex ô 3: 31 ms từ lúc thẻ hiện (nhận diện 14 + xác nhận 12 + xử lý 2)`; "lúc thẻ hiện" là khung ĐẦU TIÊN thấy thẻ đổi
(các khung hiệu ứng liên tiếp cách nhau dưới 80 ms được coi là cùng một lần hiện). Khi dừng có tổng kết
`Độ trễ mua (thẻ hiện → click): n lần, trung bình ..., p95 ..., chậm nhất ...`. Mỗi lần **bỏ click vì thẻ đã đổi giữa lúc nhận
diện và xác nhận** hoặc không chụp lại được shop đều có một dòng kèm lý do (cùng lý do chỉ ghi tối đa mỗi giây, kèm số lần bị
nén). Cooldown và ô đã khóa là việc bình thường nên không ghi.

### Chi tiết vòng lặp `_loop()` trong `scanner.py`

```
scanner._loop()  (lặp liên tục cho đến khi F8 dừng)
  │
  ├─► _grab_shop()
  │     └─► mss chụp 1 lần cả vùng shop (từ config shop_region)
  │
  ├─► Cắt ảnh thành 5 ô shop
  │
  ├─► [Bắt theo ảnh]  _match_image_fast() cho từng ô
  │     └─► OpenCV so khớp portrait với ảnh mẫu (templates)
  │
  ├─► [Bắt theo tên]  _scan_names_parallel()
  │     └─► core/name_matcher.py
  │           ├─► extract_name_region()  → cắt vùng chữ tên
  │           ├─► read_name_from_slot()  → OCR (winocr Windows)
  │           └─► NameMatcher.match()    → so với TOÀN BỘ tên tướng trong game, chỉ mua khi
  │                                       khớp tốt nhất LÀ một tướng đã chọn (không nhầm Gragas ↔ Graves)
  │
  └─► Nếu khớp → _try_buy()
        └─► core/buyer.py → buy_slot_async()
              └─► Win32 API click chuột tại slot_centers[i]
                    └─► controller.on_match → Nhật ký (hiện "✓ Mua ... ở ô ...")
```

---

## 7. Luồng dừng tool

```
F8 lần nữa / bấm DỪNG / đóng cửa sổ
  │
  └─► controller.toggle() hoặc controller.close()
        └─► scanner.stop()
              └─► _running = False  → thread _loop() kết thúc
```

---

## 8. Bảng tóm tắt: file nào làm gì

| File                    | Chức năng                                     |
| ----------------------- | --------------------------------------------- |
| `run.bat`               | Khởi chạy tool trên Windows                   |
| `main.py`               | Điểm vào mỏng (`--selftest` hoặc mở giao diện) |
| `core/controller.py`    | Điều phối: chọn tướng, điều kiện chạy, bắt đầu/dừng, preview (không import Qt) |
| `ui/`                   | Giao diện Qt: cửa sổ chính, danh sách tướng, overlay, theme, hộp thoại nhập Key |
| `core/license.py`       | Key ký số offline gắn mã máy, hạn nhập 24h, dùng một lần, lưu DPAPI |
| `core/config.py`        | Đọc/ghi `data/config.json`                    |
| `core/monitors.py`      | Liệt kê màn hình (pixel vật lý) và tìm màn hình chứa game |
| `core/profiles.py`      | Bộ vùng Shop + điểm click theo màn hình, dịch chỗ, quy đổi tỉ lệ, chọn bộ gần nhất |
| `core/champions.py`     | Tải danh sách tướng + ảnh từ Riot API         |
| `core/scanner.py`       | Quét shop, nhận diện, quyết định mua          |
| `core/buyer.py`         | Click chuột mua tướng                         |
| `core/name_matcher.py`  | OCR đọc tên tướng trong shop                  |
| `core/preview.py`       | Chụp + hiển thị ảnh xem trước vùng shop       |
| `data/config.json`      | Lưu vùng shop, điểm click, tướng đã chọn      |
| `data/templates/`       | Ảnh mẫu tướng (tải tự động hoặc upload)       |
| `data/shop_capture.png` | Ảnh chụp vùng shop SẠCH (tự sinh, xem mục 10) |

---

## 9. Luồng nhanh mỗi ngày chơi

```
run.bat
  → main.py (mở giao diện)
  → bấm thẻ chọn tướng (xem chip 'Sẵn sàng')
  → F8 bật
  → scanner.py quét liên tục
  → buyer.py click khi thấy tướng
  → F8 tắt khi xong
```

**Không cần chạy lại** bước cấu hình shop: mỗi màn hình nhớ bộ riêng và tool tự nhận màn hình đang chứa game. Chỉ khi gặp màn hình/độ
phân giải mới thì xác nhận gợi ý quy đổi (hoặc chọn lại ① ②) một lần.

---

## 10. Thư mục `data/` — có dùng không?

**Có — thư mục `data/` đang được dùng. Không xóa.**

Tool tự tạo thư mục này qua `core/config.py → ensure_dirs()` khi chạy lần đầu.

```
data/
├── config.json           ← BẮT BUỘC — đọc/ghi mỗi khi mở tool hoặc lưu cấu hình
├── config.json.bak       ← tự sinh: bản lưu lần trước, dùng để khôi phục khi config.json hỏng
├── app.log               ← tự sinh: log và lỗi (xoay vòng) — gửi file này khi cần debug
├── champions_catalog.json ← tự sinh: mọi tướng của mọi patch đã quét (tên 2 ngôn ngữ, cost, mùa, ảnh, patch); lần sau chỉ tải patch mới, dùng được khi offline
├── champions_cache.json  ← tự sinh sau mỗi lần tải danh sách tướng: mọi tên (2 ngôn ngữ, mọi mùa) + cặp alias, để so OCR khi offline
├── templates/            ← Dùng khi bật "Bắt theo ảnh"
│   ├── Aatrox__TFT18_Aatrox.png ← ảnh tải tự động từ Data Dragon (tên file kèm tên ảnh gốc → mỗi mùa một ảnh riêng)
│   └── custom_Aatrox.png ← ảnh upload thủ công (nhận diện chính xác hơn)
└── shop_capture.png      ← Tuỳ chọn — ảnh chụp vùng shop (sạch, không viền/chấm); chấm đỏ vẽ lúc hiển thị
```

### Khi nào file trong `data/` được dùng?

| File               | Đọc khi                       | Ghi khi                                               |
| ------------------ | ----------------------------- | ----------------------------------------------------- |
| `config.json`      | Mở tool (`load_config_with_notes`)       | Chọn shop, đặt click, F8 bật, upload ảnh, đổi cài đặt |
| `templates/*.png`  | F8 bật + bật **Bắt theo ảnh** | Lần đầu chọn tướng / upload ảnh                       |
| `shop_capture.png` | Mở tool / sau cấu hình shop   | Sau "Chọn vùng Shop" hoặc "Làm mới ảnh"               |

### `config.json` lưu những gì?

Mọi key dưới đây đều có trong `DEFAULT_CONFIG` (trừ `coords_version`); `tests/test_build_files.py` bắt nếu thêm key mới
mà quên ghi vào bảng này.

| Key                                  | Nội dung (mặc định, khoảng hợp lệ)                                                                 |
| ------------------------------------ | -------------------------------------------------------------------------------------------------- |
| `shop_region`                        | Tọa độ vùng 5 ô shop `{left, top, width, height}` (pixel vật lý); `null` = chưa chọn                |
| `slot_centers`                       | 5 điểm click mua tướng `[[x, y], ...]`, phải nằm trong `shop_region`                                |
| `monitor_profiles`                   | Bộ vùng Shop + 5 điểm click riêng cho từng màn hình: `{khóa màn hình: {name, monitor, shop_region, slot_centers}}` (mặc định `{}`) |
| `active_monitor`                     | Khóa màn hình mà `shop_region`/`slot_centers` đang áp dụng (`""` = chưa gắn)                      |
| `coords_version`                     | Hệ tọa độ của hai key trên (hiện là 2 = pixel vật lý). Config cũ không có key này thì xem bên dưới |
| `selected_champions`                 | Tướng đã tick checkbox                                                                              |
| `manual_names`                       | Tên tướng gõ tay (cách nhau bằng dấu phẩy hoặc xuống dòng)                                          |
| `custom_templates`                   | Đường dẫn ảnh upload cho từng tướng (tương đối so với `data/`)                                      |
| `detect_by_image` / `detect_by_name` | Bật bắt theo ảnh / theo tên (mặc định cả hai bật)                                                   |
| `match_threshold`                    | Ngưỡng khớp ảnh (0.72; 0.5–0.95)                                                                    |
| `name_match_threshold`               | Ngưỡng khớp tên OCR (0.80; 0.5–0.95; nên ≥ 0.75)                                                    |
| `scan_interval_ms`                   | Chu kỳ quét tối thiểu khi bắt theo ảnh (3; 0–100 ms, nhỏ = quét nhanh hơn)                          |
| `name_scan_interval_ms`              | Chu kỳ quét tối thiểu khi bắt theo tên (50; 0–2000 ms)                                              |
| `buy_delay_ms`                       | Chờ trước khi click mua (0; 0–2000 ms)                                                              |
| `buy_cooldown_ms`                    | Nghỉ giữa hai lần mua cùng một ô (90; 0–5000 ms)                                                    |
| `card_same_corr`                     | Hệ số tương quan để coi hai khung hình là CÙNG một thẻ (0.80; 0.5–0.99); dùng để chặn khung cũ và khóa ô vừa mua |
| `require_game_foreground`            | Chỉ click khi cửa sổ game đang ở trước (true). Tắt thì mua cả khi đang ở app khác                    |
| `game_process_names`                 | Tên tiến trình game để kiểm tra ở trên (`["League of Legends.exe"]`)                                |
| `hotkey_toggle`                      | Phím bật/tắt toàn cục (`f8`); sai thì dùng F8 và báo trong Nhật ký                                  |
| `roll_key`                           | Phím roll trong game (`d`): bấm thì app quét dày ~0,5 giây; rỗng = tắt; trùng phím bật/tắt thì bỏ qua |
| `capture_backend`                    | Cách chụp màn hình: `auto` (thử DXGI ~1 ms/khung, tự quay về mss nếu không dùng được) hoặc `mss` (~11 ms) |
| `champion_locale`                    | Ngôn ngữ danh sách tướng (`vi_VN` mặc định hoặc `en_US`); tên ngôn ngữ kia luôn được khớp OCR       |
| `season_filter`                      | Các mùa đang lọc trong danh sách tướng, vd `[18, 17]` (mặc định `[]` = tất cả các mùa). Thay cho `show_old_sets` cũ (khóa cũ nếu còn trong file thì bị bỏ qua) |
| `theme`                              | Giao diện: `auto` (theo chế độ sáng/tối của Windows), `light` hoặc `dark` (mục Nâng cao)             |

**Config cũ (không có `coords_version`) → phải chọn lại vùng.** Config lưu từ bản cũ có thể chứa tọa độ ở hệ ảo của scale
125%/150%, vốn lệch so với ảnh chụp và vị trí click. Vì vậy lúc mở, tool xóa `shop_region` và `slot_centers`, ghi
`coords_version = 2`, báo một hộp thoại và nhắc bấm 'Chọn vùng Shop' rồi 'Đặt 5 điểm click'. Các key khác giữ nguyên.
Từ nay đổi màn hình/độ phân giải/cách sắp xếp màn hình KHÔNG cần làm lại từ đầu: xem mục "Nhiều màn hình" ở trên.

### Luồng đọc/ghi `data/` trong code

```
Mở tool:
  controller → core/config.py → load_config_with_notes() → đọc data/config.json
  controller.start_up() → request_preview(capture_live=False) → đọc data/shop_capture.png (nếu có)

Cấu hình shop:
  controller → save_config() → ghi data/config.json
  core/preview.py → build_shop_preview() → ghi data/shop_capture.png (nguyên tử, ảnh sạch)

Bật F8 (bắt theo ảnh):
  core/champions.py → download_template() → ghi data/templates/{Tên}.png
  core/scanner.py → build_templates() → đọc ảnh từ data/templates/

Upload ảnh tướng:
  controller.upload_template() → copy → data/templates/custom_{Tên}.png
```

### Lưu ý

- **Preview vùng Shop:** đĩa chỉ giữ ảnh chụp SẠCH (`shop_capture.png`); viền xanh và chấm đỏ được vẽ mỗi lần hiển thị theo
  điểm click hiện tại nên không thể còn chấm cũ. Ghi file nguyên tử (có thử lại khi Windows đang khóa file), mỗi yêu cầu
  chụp có số thứ tự (kết quả cũ về muộn bị bỏ), nút 'Làm mới ảnh' mờ đi khi đang chụp. Chụp lỗi thì hiện ảnh lần trước kèm
  ghi chú; ảnh của vùng shop có kích thước khác thì không hiển thị. File `shop_preview.png` kiểu cũ (đã vẽ chấm) bị xóa.
- **Kiểm tra chất lượng mã:** `ruff.toml` chỉ bật rule bắt lỗi thật (import/biến thừa, tên biến mơ hồ, bare except, lỗi
  cú pháp, khoảng trắng thừa), không ép độ dài dòng hay phong cách. Chạy `ruff check .` hoặc `pytest` (có
  `tests/test_lint.py`, tự bỏ qua nếu chưa cài ruff: `pip install -r requirements-dev.txt`).
- **Chạy test và đo độ phủ:** `python -m pytest -q` (cần `pip install -r requirements-dev.txt`). Đo độ phủ:
  `python -m pytest -q --cov=core --cov=ui --cov-report=term-missing`. Test giao diện chạy Qt ở chế độ offscreen (không cần màn hình) và overlay chọn
  vùng thoáng hiện trong tích tắc; test bị bỏ qua nếu máy không có màn hình. Không có test nào click chuột thật vào game.
- **Sửa tay `config.json`:** lưu kiểu UTF-8 có hay không có BOM đều đọc được. Giá trị sai được tự xử lý khi mở app
  và báo trong 1 hộp thoại: chuỗi số (`"5"`, `"0,8"`) và `"true"/"false"` được đổi đúng kiểu; chuỗi đơn cho danh sách
  (`game_process_names`) thành danh sách 1 phần tử; số ngoài khoảng được kẹp vào biên (ngưỡng khớp 0.5–0.95,
  `scan_interval_ms` 0–100...); giá trị không đoán được thì dùng mặc định; `shop_region`/`slot_centers` sai thì bỏ và
  phải chọn lại. Khóa lạ được giữ nguyên. Phím tắt (`hotkey_toggle`) sai thì dùng F8 và báo trong Nhật ký.
  File chỉ được ghi lại khi app lưu cấu hình lần sau, và sẽ là bản đã sửa.
- **Ô số trên giao diện** (Chu kỳ quét tối thiểu): trống, chữ, số thập phân hoặc ngoài khoảng thì báo rõ ô nào sai và không bắt đầu.
- **Xóa `data/`** → mất hết cấu hình shop, phải setup lại từ đầu.
- **Chỉ bật "Bắt theo tên"** → `templates/` ít dùng hơn, nhưng `config.json` vẫn bắt buộc.
- **Setup 1 lần** → `config.json` giữ nguyên, mỗi ngày chỉ cần `run.bat` → F8.
- File test (vd: `test_shop_capture.png`) **không thuộc** luồng chính — có thể xóa an toàn.
