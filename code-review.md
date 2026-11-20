# Review cuối: TFT Auto Buy

Phạm vi: toàn bộ `main.py`, `core/*`, `tests/*`, `requirements*`, `TFT_Auto_Buy.spec`, các file `.bat`, `.gitignore`, `LUONG_CHAY.md`.
Cách làm: đọc hết mã, rồi **chạy thật** để kiểm chứng (chụp màn hình bằng mss, OCR của Windows, Data Dragon, test lặp 6 lần). Mục nào chưa kiểm chứng được thì ghi rõ ở cuối.
Chế độ: chỉ báo cáo, **không sửa gì**.

## Kết luận

15 lỗi của lượt review trước đã sửa và có test bảo vệ (81 test, chạy 6 lần đều đạt, không flaky). Vòng quét, chống mua theo khung cũ, khóa ô, chặn khi game không ở foreground, DPI, ghi config nguyên tử đều chạy đúng khi thử.

Rủi ro lớn nhất còn lại nằm ở **độ chính xác của bộ khớp tên**: nó vẫn mua nhầm tướng khác dù OCR đọc đúng hoàn toàn. Tiếp theo là danh sách tướng bị lẫn nhiều mùa và quái PvE.

| Mức        | Số mục |
| ---------- | ------ |
| Cao        | 1      |
| Trung bình | 3      |
| Thấp       | 8      |

---

## Cao

### 1. Bộ khớp tên nhận nhầm tướng thật khác nhau, kể cả khi OCR đọc đúng 100%

[name_matcher.py:144-165](core/name_matcher.py#L144-L165), mặc định ngưỡng 0.65 ở [config.py:40](core/config.py#L40) và [main.py:209](main.py#L209).

Tôi lấy 177 tên tướng thật từ Data Dragon (gộp các biến thể Lux), đưa từng tên vào như thể OCR đọc hoàn hảo, rồi hỏi: "nếu bạn chọn tướng khác, nó có bị mua không?"

| Ngưỡng khớp tên         | Số cặp bị nhận nhầm | Trong đó do luật chuỗi con (điểm 1.0) |
| ----------------------- | ------------------- | ------------------------------------- |
| 0.65 (mặc định)         | 113                 | 20                                    |
| 0.7524 (config của bạn) | 27                  | 20                                    |
| 0.80                    | 25                  | 20                                    |
| 0.95                    | 20                  | 20                                    |

- Với ngưỡng mặc định 0.65, chọn **Graves** sẽ mua nhầm **Draven** và **Gragas**; chọn **Vex** sẽ mua nhầm **T-Hex**. Ba tướng bạn đang chọn (Graves, Vex, Tryndamere) chỉ an toàn nhờ bạn đã tự nâng ngưỡng lên 0.7524.
- 20 cặp **không phụ thuộc ngưỡng**, vì luật chuỗi con và luật "từ ≥ 3 ký tự":
  - `Kai'Sa` bị mua khi chọn `Maokai` hoặc `Mordekaiser`
  - `Lee Sin` bị mua khi chọn `Nidalee` hoặc `Singed`
  - `Sivir`, `Viego`, `Viktor`, `Anivia` bị mua khi chọn `Vi` (bạn đã chấp nhận giới hạn này)
  - `Lucian & Senna`, `Kobuko & Yuumi` lẫn với từng tên thành phần
- Nguyên nhân gốc: hàm chỉ so OCR với **các tướng bạn chọn**, không so với **toàn bộ tướng trong game**. Nên "Draven" gần giống "Graves" hơn mọi mục tiêu còn lại là đủ để mua.
- Hàm cũng trả về mục tiêu đầu tiên khớp, không phải mục tiêu khớp nhất.

**Trạng thái: đã sửa.** `NameMatcher` ([name_matcher.py](core/name_matcher.py)) so OCR với toàn bộ tên tướng (cache ở `data/champions_cache.json` khi offline), chỉ mua khi khớp tốt nhất là một mục tiêu; mặc định ngưỡng 0.80 (giá trị bạn đã lưu được giữ). Đo lại sau khi sửa:

|                                                                              | Trước    | Sau        |
| ---------------------------------------------------------------------------- | -------- | ---------- |
| Cặp bị nhận nhầm, OCR hoàn hảo, ngưỡng 0.65 / 0.7524                         | 113 / 27 | 0 / 0      |
| Cặp mua nhầm với OCR **thật** của Windows (26.406 cặp), ngưỡng 0.65 / 0.7524 | 103 / 25 | 0 (ở 0.80) |
| Mua đúng khi chọn đúng tướng, OCR thật, ngưỡng 0.7524                        | 90,2%    | 90,2%      |
| Mua khi shop **không có** mục tiêu, OCR nhiễu 12% (mô phỏng)                 | 0,30%    | 0,05%      |

Đánh đổi: với OCR nhiễu nặng (mô phỏng, 12–20% ký tự sai) tỷ lệ mua đúng thấp hơn khoảng 1–2 điểm phần trăm. Đổi lại, mua nhầm gần như biến mất.

Phần dưới là mô tả lỗi gốc, giữ lại để đối chiếu.

Hướng sửa:

1. So OCR với toàn bộ danh sách tên tướng, chỉ mua nếu khớp tốt nhất **là một mục tiêu** và hơn khớp nhì một khoảng rõ rệt.
2. Khớp nguyên từ trước (so cả cụm), fuzzy chỉ dùng khi không còn cách nào khác.
3. Nâng mặc định ngưỡng lên ít nhất 0.80.

---

## Trung bình

### 2. Danh sách tướng bị lẫn nhiều mùa, quái PvE và bản tutorial

[champions.py:29-58](core/champions.py#L29-L58)

**Trạng thái: đã sửa.** `fetch_champion_list` giờ trả toàn bộ mục kèm tên hai ngôn ngữ; `playable_champions` bỏ tutorial/sự kiện, `strip()` tên, gộp trùng tên và giữ bản của mùa mới nhất. Giao diện chỉ hiện mùa mới nhất (74 tướng thay vì 201), có ô "Hiện mùa cũ" (183 tướng, nhãn "(mùa N)"). Chọn tất cả chỉ tác động tướng đang hiển thị. Khôi phục lựa chọn theo tên chuẩn hóa và alias (cấu hình cũ lưu `"Mel "` vẫn tick đúng). Tên tiếng Việt lẫn tiếng Anh đều được khớp OCR. Ảnh mẫu được lưu theo tên ảnh gốc nên không còn dùng nhầm nghệ thuật mùa cũ. Đo trên dữ liệu thật: 344 mục, 183 chọn được, 74 mùa mới nhất, 0 tên trùng, 0 cặp mua nhầm trên 38.586 cặp (hai ngôn ngữ).

Phần dưới là mô tả lỗi gốc, giữ lại để đối chiếu.

- `tft-champion.json` có 344 mục; app hiển thị **201 mục**, gồm Set 15, 16, 17, 18, tutorial, quái PvE (`Gromp`, `Krug`, `Sentinel`...) và mục "Enemy"/"FakeUnit". Mùa mới nhất (Set 18) có 74 mục trong dữ liệu gốc, trong đó vẫn còn quái PvE và 10 biến thể Lux; còn lại là mùa cũ.
- 16 tên bị trùng vì khoảng trắng thừa ở cuối (`'Graves '` cạnh `'Graves'`): chương trình khử trùng theo tên thô, chưa `strip()`. Trong config của bạn đã có `"Tryndamere "`.
- Danh sách tải theo `vi_VN` ([champions.py:14](core/champions.py#L14)). Có 27 tên khác bản `en_US`, ví dụ `Ngộ Không` so với `Wukong`. Nếu client game của bạn dùng tiếng Anh, tướng đó sẽ không bao giờ khớp OCR.
- "Chọn tất cả" tải 201 ảnh, phần lớn vô ích.

Hướng sửa: lọc theo mùa mới nhất (số trong đường dẫn `TFTSet{N}` của id), `strip()` tên, và cho phép chọn ngôn ngữ danh sách (`en_US` hoặc `vi_VN`) khớp với ngôn ngữ client.

### 3. Không chặn chạy hai bản app cùng lúc

**Trạng thái: đã sửa.** [single_instance.py](core/single_instance.py) giữ mutex `Local\TFTAutoBuy.SingleInstance` (một bản mỗi phiên đăng nhập, mọi thư mục). Bản thứ hai đưa cửa sổ cũ lên trước (khôi phục nếu đang thu nhỏ, chờ tối đa 3 s nếu bản kia đang khởi động) rồi thoát với mã 0; không tìm thấy cửa sổ thì hiện hộp thoại giải thích. Bản thứ hai không bật logging nên không đụng `app.log`. Thử bằng hai tiến trình thật: bản hai thoát sau ~0,5 s, cửa sổ thu nhỏ được khôi phục, chỉ có 1 cửa sổ; 6 bản khởi động đồng thời (3 vòng) luôn còn đúng 1 bản; kill bản đầu thì mở được bản mới.

Phần dưới là mô tả lỗi gốc, giữ lại để đối chiếu.

Không có cơ chế mutex hay khóa file nào (đã grep). Mở exe hai lần (exe giải nén chậm nên rất dễ bấm lần hai) thì:

- hai scanner cùng click một ô,
- hai bản cùng ghi `config.json.tmp`,
- xoay vòng `app.log` bị lỗi trên Windows vì file đang mở.

Hướng sửa: mutex đặt tên (`CreateMutexW`) khi khởi động; bản thứ hai hiện thông báo rồi thoát.

### 4. OCR hỏng thì không báo gì

[name_matcher.py:56-58](core/name_matcher.py#L56-L58), [name_matcher.py:119-120](core/name_matcher.py#L119-L120)

Mọi lỗi OCR đều bị nuốt và trả chuỗi rỗng. Người dùng không phân biệt được "OCR chết" với "shop chưa có tướng mục tiêu". Số liệu thật trên máy này:

- Pack OCR `vi-VN` **chưa cài**: `winocr` ném `AssertionError`, bị bỏ qua. Nhánh dự phòng `vi-VN` vô dụng trên máy này.
- Với ảnh chữ tự vẽ, 31/40 lần đọc đúng; 9 lần trả chuỗi rỗng, rải rác (ví dụ `Ekko` hụt ở 3/4 cỡ chữ). Đây là ảnh tổng hợp, chưa đại diện khung game thật, nhưng cho thấy đọc hụt thất thường là có thật.

Hướng sửa: tự kiểm OCR một lần khi bấm BẮT ĐẦU (vẽ chữ mẫu rồi đọc), ghi vào Nhật ký backend và ngôn ngữ đang dùng; đếm số lần OCR rỗng liên tiếp ở từng ô và báo khi bất thường.

---

## Thấp

5. **`mss.mss()` đã bị đánh dấu deprecated** ở bản 10.2.0 đang ghim (`DeprecationWarning: use mss.MSS instead`), tại [scanner.py:141](core/scanner.py#L141) và [preview.py:14](core/preview.py#L14). Ghim phiên bản nên chưa vỡ, nhưng nâng mss là hỏng. Test đang vá `sc.mss.mss` nên phải đổi theo.
6. **Config sửa tay dễ làm hỏng im lặng.** Chỉ là rủi ro thấp, nhưng hậu quả khó nhận ra.
   - File lưu từ Notepad kiểu "UTF-8 with BOM" bị coi là hỏng (`JSONDecodeError`), rồi bị đổi tên `.bad` ([config.py:108](core/config.py#L108) đọc bằng `utf-8` thay vì `utf-8-sig`). Đã kiểm chứng.
   - `game_process_names` là chuỗi thay vì list sẽ thành tập ký tự (13 phần tử), nên scanner **không bao giờ click** ([scanner.py:133](core/scanner.py#L133)). Đã kiểm chứng.
   - Ô số trống (Spinbox) làm `IntVar.get()` ném `TclError` ở [main.py:629](main.py#L629): bấm BẮT ĐẦU không có phản hồi nào ngoài một dòng "Lỗi giao diện" trong Nhật ký. Đã kiểm chứng.
     **Trạng thái: đã sửa cả ba.** `config.json` đọc bằng `utf-8-sig` nên file có BOM không còn bị đổi tên `.bad`. [config.py](core/config.py) có `sanitize_config` chạy khi tải (kể cả khi khôi phục từ `.bak`): tự đổi kiểu khi rõ ý (`"5"`→5, `"0,8"`→0.8, `"true"`→True, chuỗi đơn→danh sách), kẹp số ngoài khoảng vào biên, dùng mặc định khi không đoán được, bỏ `shop_region`/`slot_centers` sai kèm hướng dẫn chọn lại, giữ nguyên khóa lạ; mọi thay đổi có 1 dòng trong hộp thoại lúc mở. Ô "Tốc độ quét" trống/chữ/`5.5`/ngoài 0–100 giờ báo rõ ô sai và không bắt đầu (trước là `TclError` im lặng). Tìm thêm một lỗi cùng loại: phím tắt sai bị báo nhầm là "chạy bằng quyền Admin" và nút luôn ghi "F8"; giờ [hotkey.py](core/hotkey.py) phân biệt phím sai (dùng F8, báo rõ) với thiếu quyền, và nhãn/nút theo phím đang hiệu lực. Đã thử trên app thật với `config.json` có BOM và nhiều giá trị sai.
7. **Nhãn "0 = nhanh nhất ≈ 1 ms/vòng" ([main.py:205](main.py#L205)) không đúng.** Một lần chụp mss mất ~6,3 ms trên vùng 640×200 (đo thật); verify trước khi click ~7 ms. Mỗi vòng thực tế khoảng 7 ms trở lên. Nhãn này do chính tôi viết ở lượt trước.
   **Trạng thái: đã sửa.** Đo thật trên máy thử: một lần chụp mss ~7 ms (gần như không đổi theo kích thước vùng), nên ở cài đặt 0 ms vòng quét chạy ~6,9 ms/vòng (≈144 vòng/giây), còn 30 ms cho đúng 30,4 ms. Ô đổi tên thành "Chu kỳ quét tối thiểu (ms, 0 = nhanh nhất có thể)" (đúng bản chất: số nhỏ = nhanh hơn, và là mức tối thiểu chứ không phải tốc độ). Nhãn không còn ghi con số cố định. [scanner.py](core/scanner.py) đo chu kỳ thực (`LoopStats`, tính cả phần nghỉ, chụp và các đợt OCR chậm) và giao diện hiện dòng "Thực tế: 6.9 ms/vòng (≈ 144 vòng/giây), chậm nhất 8 ms" cập nhật mỗi giây dưới ô số; dừng thì giữ "Lần quét trước: …", và Nhật ký ghi 1 dòng tổng kết (số vòng, trung bình, p95, chậm nhất). Thử trên app thật với scanner thật ở 0 ms và 30 ms.
8. **Chờ OCR tối đa 5 × 8 s.** [scanner.py:368](core/scanner.py#L368) chờ tuần tự từng ô. Nếu OCR treo, vòng lặp có thể kẹt tới 40 s, và bấm DỪNG chỉ có tác dụng sau đó (không click nhờ có `_running`, nhưng scanner cũ còn sống).
   **Trạng thái: đã sửa.** Đợt OCR giờ có MỘT hạn chung 2 giây (đo thật: một lần OCR ~7 ms, cả 5 ô ~10 ms) thay cho 5 lần chờ tuần tự 8 giây. Bấm DỪNG được kiểm tra mỗi 50 ms trong lúc chờ, nên scanner thoát trong vài ms thay vì tới 40 s. Ô nào chưa xong khi hết hạn coi như rỗng; báo "OCR bị kẹt" đúng 1 lần; các lượt sau bỏ qua OCR (không dồn việc vào pool đang kẹt, không tính là "đọc rỗng") trong khi bắt theo ảnh vẫn chạy, và tự dùng lại kèm báo "đã hồi phục" khi luồng kẹt trả về. Nâng số luồng OCR từ 3 lên 5 (cả 5 ô một đợt: 10,5 ms thay vì 16,8 ms). Phát hiện thêm: `ThreadPoolExecutor` có luồng không-daemon nên một lần OCR treo vĩnh viễn làm **tiến trình không thoát được** kể cả sau `shutdown(wait=False)` (đã kiểm chứng), và tiến trình còn sống sẽ giữ mutex của mục 3, chặn việc mở lại app. Thay bằng [ocr_pool.py](core/ocr_pool.py) (luồng daemon). Thử với scanner thật và OCR treo vĩnh viễn: 1 cảnh báo sau 2 giây, bắt theo ảnh vẫn chạy, dừng sau 3 ms, tiến trình thoát bình thường.
9. **`preview.py` chưa nhất quán.** Ghi `shop_preview.png` không nguyên tử và có thể ghi đồng thời từ hai thread (bấm "Làm mới ảnh" hai lần liền); khi chụp lỗi thì vẽ đè lên ảnh cũ nên các chấm đỏ chồng dần; [preview.py:41](core/preview.py#L41) vẫn dùng `cv2.imread` nên đường dẫn có dấu sẽ thất bại, trong khi phần template đã đọc qua numpy.
   **Trạng thái: đã sửa.** _Đính chính:_ ý cuối ở trên (`cv2.imread` hỏng với đường dẫn có dấu) **sai** với OpenCV 4.10 đang dùng: đã thử và đọc bình thường, nên không phải sửa. Hai ý còn lại là thật và đã tái hiện: chụp lỗi sau khi đổi điểm click thì ảnh có cả hai bộ chấm rồi bị ghi đè lại, và 2 thread ghi cùng file cho 77/600 lần đọc gặp ảnh ghi dở. [preview.py](core/preview.py) viết lại: đĩa chỉ giữ ảnh chụp **sạch** (`shop_capture.png`), viền và chấm vẽ lúc hiển thị theo điểm click hiện tại; ghi nguyên tử với file tạm riêng từng thread; chụp lỗi thì hiện ảnh lần trước kèm ghi chú (ảnh của vùng shop kích thước khác thì không hiển thị); ảnh `shop_preview.png` kiểu cũ bị xóa. Giao diện: nút "Làm mới ảnh" mờ khi đang chụp, mỗi yêu cầu có số thứ tự nên kết quả cũ về muộn không đè ảnh mới, lỗi bất ngờ hiện ra thay vì làm nút kẹt, thêm dòng ghi chú (giờ chụp / cảnh báo ảnh cũ). Tìm thêm 2 lỗi trong lúc làm, cả hai đã sửa: trên Windows `os.replace` ném `PermissionError` khi luồng khác đang mở file đích (cả phía ghi lẫn phía đọc cần thử lại), và `cv2.imdecode` ném `cv2.error` với file rỗng.
10. **Mã chết và lỗi trình bày.**
    - `buy_slot` ([buyer.py:33](core/buyer.py#L33)) không có ai gọi.
    - `self.ddragon_paths` và `self._hotkey_handle` ([main.py:53-54](main.py#L53-L54)) không được dùng.
    - [main.py:46](main.py#L46) thiếu dấu cách: `needs_save =self.config...`.
      **Trạng thái: đã sửa.** _Hiện trạng khác báo cáo gốc một chút:_ `_hotkey_handle` đã biến mất từ mục 6, nhưng `buy_slot`, `self.ddragon_paths` và dòng `needs_save =self…` còn nên đã xóa/sửa. Quét lại bằng `ruff` và `vulture` (cài trong môi trường ảo tạm) tìm thêm: 3 hàm trong mã sản phẩm chỉ có test gọi (`config.load_config`, `name_matcher.match_name_in_text`, `scanner._match_name_fast`) đã xóa, test chuyển sang API thật (`load_config_with_notes`, `NameMatcher`, `_ocr_slot`); `InstanceLock.release` **giữ lại** vì test mutex cần nhả khóa để chứng minh không rò tay cầm (Windows tự nhả khi thoát nên app thật không gọi). Lint: 2 import thừa, 1 so sánh `is` với literal luôn đúng (test Barrier nay khẳng định thật `[0..4]`), 9 tên biến `l`, 1 `noqa` thừa. Không đụng 31 dòng dài và các gợi ý phong cách thuần túy (theo lựa chọn). Chốt chặn: [ruff.toml](ruff.toml) chỉ bật rule bắt lỗi thật, `ruff` trong requirements-dev, và [test_lint.py](tests/test_lint.py) chạy ruff trên toàn dự án kèm các test chứng minh cấu hình bắt được import/biến thừa, tên mơ hồ, bare except, `is` với literal.
11. **Vệ sinh repo và bản build.**
    - `data/config.json` được git theo dõi và chứa cấu hình cá nhân (`C:\Users\Admin\...`, tướng đã chọn).
    - `lenh_claude_new.md` vẫn được theo dõi dù có trong `.gitignore`.
    - **`dist/TFT_Auto_Buy.exe` có ngày 2026-07-13, cũ hơn mọi bản sửa**: chạy nó là chạy bản có đủ lỗi cũ. Cần `build.bat` lại.
      **Trạng thái: đã sửa.** _Git:_ đã `git rm --cached` `data/config.json`, `data/templates/*` (17 ảnh) và `lenh_claude_new.md` (file vẫn còn trên đĩa, **chưa commit**, chỉ đổi index); `.gitignore` nay ignore cả `data/` và `core/_build_stamp.py`. _Exe:_ dựng lại từ mã hiện tại (PyInstaller 6.22.3), `dist/TFT_Auto_Buy.exe` từ 82 MB (2026-07-13) còn 68 MB (2026-11-19); `dist/data` (config và ảnh chụp cũ) đã xóa. Đã chạy thử exe trong thư mục tạm: `--selftest` đạt 7/7 (module, thư viện, mss, OCR, mutex, data), cửa sổ hiện ra, bản thứ hai thoát sau 2,5 s mà bản đầu vẫn sống, đóng cửa sổ thì thoát sạch, không sót tiến trình, `app.log` có dòng `Phiên bản: build ...`. _Chống tái phát:_ (1) mỗi lần đóng gói spec ghi `core/_build_stamp.py` (giờ build + mã commit, thêm `+` nếu còn thay đổi chưa commit) và app in dòng `Phiên bản:` vào Nhật ký, exe cũ không có dòng này nên nhận ra được; (2) `build.bat` cài `requirements-build.txt` (ghim `pyinstaller==6.22.3`), **chạy pytest và dừng nếu hỏng** trước khi đóng gói, rồi chạy `exe --selftest` và in báo cáo; (3) `TFT_Auto_Buy.exe --selftest` (không mở giao diện, ghi `%TEMP%\TFT_Auto_Buy_selftest.txt`) bắt lỗi thiếu module ẩn/DLL sau khi đóng gói. Test mới: `test_build_files.py` (mọi `core/*.py` phải có trong hiddenimports và `selftest.CORE_MODULES`, build.bat chạy pytest trước PyInstaller, `.gitignore`, `git ls-files data` rỗng), `test_build_info.py`, `test_selftest.py`.
12. **Tài liệu và test còn khoảng trống.**
    - [LUONG_CHAY.md](LUONG_CHAY.md) chưa liệt kê key mới của config (`coords_version`, `card_same_corr`, `require_game_foreground`, `game_process_names`) và chưa ghi "đổi scale màn hình" là lý do phải chọn lại vùng.
    - Test chưa phủ phần điều phối giao diện (`_start_scan`, `_finish_start`, khôi phục config, migrate tọa độ); tôi chỉ chạy tay các phần này.
    - Chưa có test cho `buyer.click` (khôi phục con trỏ), `dpi`, `logging_setup`, `preview`, `read_name_from_slot`, `fetch_champion_list`.
    - Một assertion yếu: `test_grab_after_close_returns_none_instead_of_raising` có `or s._last_grab_error`, nên gần như luôn đúng.
      **Trạng thái: đã sửa.** Đo độ phủ thật bằng `pytest-cov` (đã thêm vào `requirements-dev.txt`): trước 82% tổng, `main.py` 60%, `logging_setup` 34%, `buyer` 53%, `dpi` 65%; sau **96% tổng, `main.py` 98%, `buyer`/`dpi`/`logging_setup` 100%** (654 → 774 test). _Tài liệu:_ bảng key của [LUONG_CHAY.md](LUONG_CHAY.md) nay đủ cả 19 key của `DEFAULT_CONFIG` kèm mặc định và khoảng hợp lệ, cộng `coords_version` và mục "đổi scale màn hình / config cũ thì phải chọn lại vùng"; `test_flow_doc_lists_every_config_key` bắt nếu thêm key mà quên ghi. _Test mới:_ `test_buyer.py` (thứ tự di chuyển, click, chờ, trả chuột; không đọc được vị trí thì không trả; tọa độ âm của màn hình phụ; **một test chạy thật** đọc/đặt chuột Windows với `mouse_event` bị chặn nên không click), `test_dpi.py` (chuỗi dự phòng 3 tầng và lỗi từng API; kiểm tra tiến trình thật không còn ở chế độ UNAWARE), `test_logging_setup.py` (một handler, xoay vòng thật, hook lỗi chưa bắt của luồng chính và luồng nền, thư mục chỉ đọc), `test_ocr_backend.py` (chọn engine winocr → rapidocr → none, nhánh RapidOCR, cắt dải tên), `test_app_flow.py` (72 test trên app Tk thật: `_validate_start`, `_start_scan` → `_prepare_background` → `_finish_start` với OCR hỏng/ảnh thiếu/tải lỗi/đóng giữa chừng, khôi phục config hỏng và migrate tọa độ lúc mở, danh sách tướng/tìm kiếm/mùa cũ/tải lại, upload ảnh, chọn vùng và 5 điểm click bằng sự kiện chuột thật vào overlay, `_on_close`, `run_app`). Assertion yếu của `test_grab_after_close_returns_none_instead_of_raising` nay yêu cầu đúng `AttributeError: ... NoneType`. Phá thử 17 hành vi (không trả chuột, bỏ chờ, thứ tự DPI, handler trùng, không chuyển lỗi cho hook mặc định, OCR hỏng vẫn bắt tên, không báo reset tọa độ, bấm lần hai khi đang chuẩn bị, nhận điểm ngoài vùng, nhận khung quá nhỏ, ROI rỗng, ...): **15/17 bị bắt ngay; 2 lọt lưới** (callback tốc độ đến muộn, `_post_to_ui` ném lỗi khi cửa sổ đóng) nên đã thêm test rồi phá lại, nay bắt được. _Lỗi thật tìm được khi viết test:_ đóng app khi đang tải danh sách tướng làm thread nền chết kèm `RuntimeError: main thread is not in main loop` (vào `app.log` mức CRITICAL); đã thêm `_post_to_ui` bỏ qua khi cửa sổ không còn. Một test cũ (`test_on_status_and_on_match`) thỉnh thoảng đỏ vì hẹn giờ tải tướng 100 ms chen vào, đã tắt hẹn giờ đó trong fixture. Chạy 3 lần liên tiếp đều đạt, không còn cảnh báo thread.

---

## Đã kiểm chứng là đúng

- **Chụp màn hình thật**: mss → numpy (mảng không liên tục) → cv2 chạy đúng, kể cả cắt ô và tính chữ ký. Tiến trình đã DPI-aware (`enable_dpi_awareness()` trả `True`).
- **OCR thật** (`winocr`, en-US) đọc đúng ảnh chữ tự vẽ; 5 ô song song mất ~20 ms.
- **Đính chính lượt trước:** tôi từng ước OCR mất "hàng chục đến hàng trăm ms". Đo thực tế ~7–24 ms mỗi ô trên ảnh nhỏ. Cửa sổ rủi ro của khung cũ hẹp hơn tôi nói, nhưng vẫn có thật, và bước kiểm tra lại trước khi click là đúng để giữ.
- **Test**: 774 đạt, độ phủ 96% (`main.py` 98%), chạy 3 lần liên tiếp đều đạt và không có cảnh báo. Phá thử nhiều đợt (đợt cuối 17 hành vi ở mục 12 cộng các đợt trước: khớp tên ngắn, so sánh thẻ, ghi nguyên tử, chặn foreground, bảo vệ `.bak`...) thì test đều bắt được sau khi bổ sung các test còn lọt lưới.

## Chưa kiểm chứng được

- Toàn bộ hành vi **trong game thật**: ngưỡng `card_same_corr = 0.80`, tên process `League of Legends.exe`, việc trả chuột về sau khi click, vị trí dải tên trên thẻ cho OCR.
- OCR trên **ảnh game thật** (tôi chỉ có ảnh chữ tự vẽ).
- Overlay chọn vùng trên **nhiều màn hình** (máy này chỉ có 1 màn hình). Trên 1 màn hình, kéo chuột, 5 lần click và phím `Esc` đã được test bằng sự kiện Tk gửi vào overlay thật; chưa thử bằng tay trên màn hình phụ hay scale khác 125%.
- Giao diện ở các mức scale khác ngoài 125%.

---

## Nâng cấp giao diện (UX/UI) — đã làm theo phỏng vấn

- **Kiến trúc:** logic điều phối tách khỏi giao diện vào [core/controller.py](core/controller.py) (không import Qt, 100 test); giao diện mới bằng PySide6 trong [ui/](ui/). Bản Tk cũ đã được thay hoàn toàn (không giữ chế độ cũ).
- **Bố cục:** thanh điều khiển cố định (BẮT ĐẦU/DỪNG, chip sẵn sàng/OCR/tốc độ/số tướng), thân hai vùng khi rộng và một cột + tab dưới khi hẹp (không cuộn ngang), Nhật ký luôn hiện. Sáng/tối theo Windows.
- **Tương tác:** nút BẮT ĐẦU luôn bấm được; thiếu điều kiện thì nói rõ thiếu gì và dẫn tới đúng bước. Mọi thay đổi cập nhật danh sách 'Sẵn sàng chạy?' ngay.
- **Danh sách tướng:** tìm kiếm tức thì, lọc Cost / 'Đã chọn' / 'Mùa cũ', thẻ có ảnh chân dung (tải ngầm) hoặc chữ gọn. Gõ tìm kiếm không dựng lại widget (bản Tk dựng lại cả lưới mỗi phím).
- **Overlay:** chụp sẵn màn hình làm nền, có kính lúp và kích thước trực tiếp, hỗ trợ nhiều màn hình, Backspace lùi điểm; lưu tọa độ vật lý bằng `GetCursorPos`.
- **Kiểm chứng:** 837 test (độ phủ `controller` 99%, `main_window` 98%), phá thử 20 hành vi thì bắt được hết (2 cái lọt đã bổ sung test); chụp ảnh giao diện sáng/tối × rộng/hẹp; exe dựng lại (97 MB), `--selftest` đạt, chạy thật hiện đúng cửa sổ tối theo Windows với 74 tướng và ảnh chân dung.
- **Chưa kiểm chứng bằng tay:** overlay trên màn hình phụ/khác scale, nhiều DPI trộn lẫn, và hành vi trong game thật.

---

## Tối ưu tốc độ click khi roll liên tục — đã làm theo phỏng vấn

**Đo thật (máy thử, vùng 1200×200, 87 ảnh mẫu):** chụp `mss` ~11,8 ms (**cố định, chụp 8×8 vẫn ~8 ms; cờ `CAPTUREBLT` không phải nguyên nhân**), so khớp ảnh 5 ô ~3,7 ms, OCR 5 ô ~13 ms, chữ ký ~1,2 ms, và `buyer.click` chặn luồng quét 30 ms sau mỗi click. Mỗi lần mua còn chụp lại cả vùng (~12 ms). _Đính chính:_ tôi từng đề xuất "chỉ chụp đúng ô cần mua" để xác nhận rẻ hơn; đo cho thấy với `mss` cách đó không tiết kiệm gì, nên đã thay bằng DXGI.

**Đã sửa:** (1) luồng click riêng, click cả loạt rồi trả chuột một lần (hết chờ 30 ms); (2) mua cả loạt với MỘT lần chụp xác nhận; (3) nhánh ảnh mua ngay không chờ OCR; (4) OCR theo thay đổi (ô vừa đổi OCR ngay, ô đang ổn định theo chu kỳ, lưới an toàn 0,5 s) thay vì mỗi 50 ms cả 5 ô; (5) bỏ qua xử lý khung giống hệt khung trước; (6) chụp DXGI (`dxcam`) ~1 ms với tự kiểm tra, đối chiếu định kỳ và tự quay về `mss`; (7) đo độ trễ "thẻ hiện → click" và ghi lý do mỗi lần bỏ click vào Nhật ký; (8) phím roll (mặc định `d`).

**Kết quả mô phỏng đầu-cuối** (cửa sổ vẽ 5 thẻ giả đổi như roll, scanner thật chụp + OCR thật, click chỉ ghi lại, 25 lần mỗi kiểu, tính từ lúc vẽ xong): bắt theo ảnh 27 → 22 ms; ảnh + tên 35 → 19 ms; độ trễ nội bộ của scanner (thẻ hiện → click) 17 → 4 ms. Phần còn lại là độ trễ hiển thị/compositor của Windows, nằm ngoài tầm kiểm soát. Không bỏ sót, không click nhầm ô ở cả 25/25 lần (ảnh và ảnh + tên). CPU khi shop đứng yên giảm khoảng 3 lần nhờ bỏ qua khung tĩnh.

**Phát hiện thêm, chưa sửa:** bắt theo _tên_ bỏ sót ở các tên ngắn (trong mô phỏng: "Ahri" đọc ra rỗng, "Alune" đọc thành "Nune"; 18/25 lần thay vì 25/25 khi chỉ bật OCR). Đây là lỗi đọc chữ của Windows OCR, không phải độ trễ. Thử 8 cách tiền xử lý ảnh trên 24 tên ở 3 cỡ chữ cho thấy độ chính xác dao động mạnh theo cỡ chữ và không có cách nào thắng ở mọi cỡ (baseline ×3 đọc đúng 14–19/24; mỗi biến thể tốt nhất 19–22/24 ở một cỡ). Phông chữ thật trong game khác phông tôi vẽ, nên cần ảnh chụp shop thật để chỉnh; bật cả "Bắt theo ảnh" thì không bị bỏ sót (25/25).

**Chưa kiểm chứng:** hành vi trong game thật (DXGI có thể trả khung đen nếu game ở fullscreen độc quyền, khi đó app tự dùng `mss` và ghi lý do), và liệu game có bỏ qua cú click quá ngắn (hiện không có độ trễ giữa nhấn và nhả; chưa gặp vấn đề nhưng chưa thử trong game).
