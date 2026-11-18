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

| File | Vai trò |
|------|---------|
| `run.bat` | Script Windows: cài thư viện + gọi Python |
| `requirements.txt` | Danh sách thư viện cần cài |
| `main.py` | Giao diện + điều phối toàn bộ tool |

---

## 2. Khi mở `main.py`

```
main.py
  │
  ├─► core/config.py          load_config()     → đọc data/config.json
  ├─► _build_ui()             → dựng giao diện Tkinter
  ├─► _load_champions_async()
  │     └─► core/champions.py fetch_champion_list()
  │           └─► API Riot Data Dragon (internet)
  ├─► _load_shop_preview_from_disk()
  │     └─► data/shop_preview.png (nếu có)
  └─► _register_hotkey()      → phím F8 (thư viện keyboard)
```

---

## 3. Sơ đồ phụ thuộc giữa các file

```
                    ┌─────────────┐
                    │   run.bat   │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   main.py   │  ← GUI + điều phối
                    └──┬───┬───┬──┘
         ┌─────────────┘   │   └─────────────┐
         │                 │                 │
  ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
  │ config.py   │   │ champions.py│   │ preview.py  │
  └─────────────┘   └─────────────┘   └─────────────┘
         │                 │
         │           ┌───────▼───────┐
         │           │  scanner.py   │  ← quét shop + mua
         │           └───┬───────┬───┘
         │               │       │
         │        ┌──────▼──┐ ┌──▼────────────┐
         │        │ buyer.py│ │ name_matcher.py│
         │        └─────────┘ └────────────────┘
         │
  ┌──────▼──────┐
  │ config.json │  ← lưu cấu hình shop, tướng đã chọn
  │ templates/  │  ← ảnh mẫu tướng
  └─────────────┘
```

---

## 4. Luồng cấu hình Shop (làm 1 lần)

```
Người dùng bấm "Chọn vùng Shop"
  │
  └─► main.py → _calibrate_region()
        ├─► Overlay toàn màn hình (kéo khung)
        ├─► core/config.py → save_config()   → ghi shop_region
        └─► core/preview.py → build_shop_preview() → chụp + hiện preview

Người dùng bấm "Đặt điểm click (5 ô)"
  │
  └─► main.py → _calibrate_clicks()
        ├─► core/config.py → save_config()   → ghi slot_centers (5 tọa độ)
        └─► core/preview.py → build_shop_preview() → vẽ chấm đỏ 1→5
```

**Dữ liệu lưu tại:** `data/config.json`

---

## 5. Luồng chọn tướng

```
Người dùng tick checkbox / gõ tên
  │
  └─► main.py
        ├─► _get_selected_names()    → từ checkbox
        ├─► _get_manual_names()      → từ ô gõ tay (tuỳ chọn)
        └─► _get_all_target_names()  → gộp 2 nguồn trên
```

Khi bấm **Upload ảnh tướng**:

```
main.py → _upload_template()
  └─► copy ảnh → data/templates/custom_{TênTướng}.png
  └─► core/config.py → save_config()  → custom_templates
```

---

## 6. Luồng bắt tướng (F8 / BẮT ĐẦU)

Đây là luồng chính khi đang chơi game:

```
Người dùng bấm F8 hoặc "BẮT ĐẦU"
  │
  └─► main.py → _toggle_scan()
        └─► _prepare_scanner()
              ├─► core/champions.py → download_template()  (tải ảnh nếu chưa có)
              ├─► core/scanner.py   → build_templates()      (chuẩn bị ảnh mẫu)
              └─► core/scanner.py   → ShopScanner(...)       (tạo engine quét)
                    └─► scanner.start()
                          └─► thread nền: scanner._loop()   ← chạy liên tục
```

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
  │           └─► match_name_in_text()   → so với tên tướng đã chọn
  │
  └─► Nếu khớp → _try_buy()
        └─► core/buyer.py → buy_slot_async()
              └─► Win32 API click chuột tại slot_centers[i]
                    └─► main.py → _log()  (hiện "✓ Mua ... ở ô ...")
```

---

## 7. Luồng dừng tool

```
F8 lần nữa / bấm DỪNG / đóng cửa sổ
  │
  └─► main.py → _toggle_scan() hoặc _on_close()
        └─► scanner.stop()
              └─► _running = False  → thread _loop() kết thúc
```

---

## 8. Bảng tóm tắt: file nào làm gì

| File | Chức năng |
|------|-----------|
| `run.bat` | Khởi chạy tool trên Windows |
| `main.py` | Giao diện, phím F8, điều phối mọi thứ |
| `core/config.py` | Đọc/ghi `data/config.json` |
| `core/champions.py` | Tải danh sách tướng + ảnh từ Riot API |
| `core/scanner.py` | Quét shop, nhận diện, quyết định mua |
| `core/buyer.py` | Click chuột mua tướng |
| `core/name_matcher.py` | OCR đọc tên tướng trong shop |
| `core/preview.py` | Chụp + hiển thị ảnh xem trước vùng shop |
| `data/config.json` | Lưu vùng shop, điểm click, tướng đã chọn |
| `data/templates/` | Ảnh mẫu tướng (tải tự động hoặc upload) |
| `data/shop_preview.png` | Ảnh xem trước vùng shop (tự sinh, xem mục 10) |

---

## 9. Luồng nhanh mỗi ngày chơi

```
run.bat
  → main.py (mở giao diện)
  → tick tướng
  → F8 bật
  → scanner.py quét liên tục
  → buyer.py click khi thấy tướng
  → F8 tắt khi xong
```

**Không cần chạy lại** bước cấu hình shop trừ khi đổi màn hình / độ phân giải.

---

## 10. Thư mục `data/` — có dùng không?

**Có — thư mục `data/` đang được dùng. Không xóa.**

Tool tự tạo thư mục này qua `core/config.py → ensure_dirs()` khi chạy lần đầu.

```
data/
├── config.json           ← BẮT BUỘC — đọc/ghi mỗi khi mở tool hoặc lưu cấu hình
├── templates/            ← Dùng khi bật "Bắt theo ảnh"
│   ├── Aatrox.png        ← ảnh tải tự động từ Data Dragon
│   └── custom_Aatrox.png ← ảnh upload thủ công (nhận diện chính xác hơn)
└── shop_preview.png      ← Tuỳ chọn — ảnh xem trước vùng shop trong giao diện
```

### Khi nào file trong `data/` được dùng?

| File | Đọc khi | Ghi khi |
|------|---------|---------|
| `config.json` | Mở tool (`load_config`) | Chọn shop, đặt click, F8 bật, upload ảnh, đổi cài đặt |
| `templates/*.png` | F8 bật + bật **Bắt theo ảnh** | Lần đầu chọn tướng / upload ảnh |
| `shop_preview.png` | Mở tool / sau cấu hình shop | Sau "Chọn vùng Shop" hoặc "Làm mới ảnh" |

### `config.json` lưu những gì?

| Key | Nội dung |
|-----|----------|
| `shop_region` | Tọa độ vùng 5 ô shop (left, top, width, height) |
| `slot_centers` | 5 điểm click mua tướng |
| `selected_champions` | Tướng đã tick checkbox |
| `custom_templates` | Đường dẫn ảnh upload cho từng tướng |
| `detect_by_image` / `detect_by_name` | Bật bắt theo ảnh hay tên |
| `match_threshold`, `name_match_threshold` | Ngưỡng nhận diện |
| `scan_interval_ms`, `name_scan_interval_ms` | Tốc độ quét |

### Luồng đọc/ghi `data/` trong code

```
Mở tool:
  main.py → core/config.py → load_config() → đọc data/config.json
  main.py → _load_shop_preview_from_disk() → đọc data/shop_preview.png (nếu có)

Cấu hình shop:
  main.py → save_config() → ghi data/config.json
  core/preview.py → build_shop_preview() → ghi data/shop_preview.png

Bật F8 (bắt theo ảnh):
  core/champions.py → download_template() → ghi data/templates/{Tên}.png
  core/scanner.py → build_templates() → đọc ảnh từ data/templates/

Upload ảnh tướng:
  main.py → _upload_template() → copy → data/templates/custom_{Tên}.png
```

### Lưu ý

- **Xóa `data/`** → mất hết cấu hình shop, phải setup lại từ đầu.
- **Chỉ bật "Bắt theo tên"** → `templates/` ít dùng hơn, nhưng `config.json` vẫn bắt buộc.
- **Setup 1 lần** → `config.json` giữ nguyên, mỗi ngày chỉ cần `run.bat` → F8.
- File test (vd: `test_shop_capture.png`) **không thuộc** luồng chính — có thể xóa an toàn.
