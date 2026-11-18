"""
TFT Auto Buy - Tool tự động bắt tướng khi roll
Chạy: python main.py (cần quyền Admin để dùng phím tắt global)
"""

import shutil
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import keyboard
from PIL import Image, ImageTk

from core.champions import download_template, fetch_champion_list, load_template_image
from core.config import SHOP_PREVIEW_PATH, TEMPLATES_DIR, load_config, save_config
from core.preview import build_shop_preview
from core.scanner import ShopScanner, build_templates


class TFTAutoBuyApp:
    """Giao diện chính: chọn tướng, cấu hình shop, bật/tắt quét bằng F8."""

    def __init__(self):
        """Khởi tạo cửa sổ, load config, dựng UI và đăng ký phím tắt."""
        self.root = tk.Tk()
        self.root.title("TFT Auto Buy - Bắt tướng tự động")
        self.root.geometry("920x880")
        self.root.minsize(800, 600)

        self.config = load_config()
        self.champions: list[dict] = []
        self.champion_vars: dict[str, tk.BooleanVar] = {}
        self.scanner: ShopScanner | None = None
        self.ddragon_paths: dict[str, Path] = {}
        self._hotkey_handle = None
        self._preview_photo = None

        self._build_ui()
        self.root.after(100, self._load_champions_async)
        self.root.after(200, self._load_shop_preview_from_disk)
        self._register_hotkey()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        """Dựng toàn bộ giao diện: danh sách tướng, cấu hình shop, cài đặt, nút bắt đầu."""
        style = ttk.Style()
        style.theme_use("clam")

        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        ttk.Label(top, text="TFT Auto Buy", font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="Sẵn sàng")
        ttk.Label(top, textvariable=self.status_var, foreground="#2563eb").pack(side=tk.RIGHT)

        main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left = ttk.Frame(main, padding=4)
        main.add(left, weight=2)

        ttk.Label(left, text="Chọn tướng cần bắt", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        search_frame = ttk.Frame(left)
        search_frame.pack(fill=tk.X, pady=4)
        ttk.Label(search_frame, text="Tìm:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._filter_champions())
        ttk.Entry(search_frame, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.champ_canvas = tk.Canvas(list_frame, highlightthickness=0, bg="#f5f5f5")
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.champ_canvas.yview)
        self.champ_inner = ttk.Frame(self.champ_canvas)

        self._champ_window_id = self.champ_canvas.create_window((0, 0), window=self.champ_inner, anchor=tk.NW)
        self.champ_canvas.configure(yscrollcommand=scrollbar.set)

        self.champ_inner.bind(
            "<Configure>",
            lambda e: self.champ_canvas.configure(scrollregion=self.champ_canvas.bbox("all")),
        )
        self.champ_canvas.bind("<Configure>", self._on_champ_canvas_resize)

        self.champ_canvas.bind("<Enter>", self._bind_champ_mousewheel)
        self.champ_canvas.bind("<Leave>", self._unbind_champ_mousewheel)

        self.champ_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._champ_list_cols = 3

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=4)
        ttk.Button(btn_row, text="Chọn tất cả", command=self._select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Bỏ chọn", command=self._deselect_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Upload ảnh tướng", command=self._upload_template).pack(side=tk.LEFT, padx=2)

        name_frame = ttk.LabelFrame(left, text="Bắt theo tên tướng (OCR)", padding=6)
        name_frame.pack(fill=tk.X, pady=6)
        ttk.Label(
            name_frame,
            text="Gõ tên tướng (phẩy hoặc xuống dòng). VD: Aatrox, Yasuo, Jinx",
            wraplength=400,
        ).pack(anchor=tk.W)
        self.manual_names_text = tk.Text(name_frame, height=3, font=("Segoe UI", 9))
        self.manual_names_text.pack(fill=tk.X, pady=4)
        self.manual_names_text.insert("1.0", self.config.get("manual_names", ""))

        mode_row = ttk.Frame(name_frame)
        mode_row.pack(fill=tk.X)
        self.detect_image_var = tk.BooleanVar(value=self.config.get("detect_by_image", True))
        self.detect_name_var = tk.BooleanVar(value=self.config.get("detect_by_name", True))
        ttk.Checkbutton(mode_row, text="Bắt theo ảnh", variable=self.detect_image_var).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(mode_row, text="Bắt theo tên", variable=self.detect_name_var).pack(side=tk.LEFT, padx=4)

        right = ttk.Frame(main, padding=4)
        main.add(right, weight=1)

        cal = ttk.LabelFrame(right, text="Cấu hình vùng Shop", padding=8)
        cal.pack(fill=tk.X, pady=4)
        ttk.Label(
            cal,
            text="1. 'Chọn vùng Shop' → kéo khung CHỈ hàng 5 thẻ tướng (không gồm vàng/nút)\n"
            "2. 'Đặt điểm click' → click vào ẢNH tướng (giữa portrait), không click trait",
            wraplength=320,
        ).pack(anchor=tk.W)
        ttk.Button(cal, text="Chọn vùng Shop", command=self._calibrate_region).pack(fill=tk.X, pady=4)
        ttk.Button(cal, text="Đặt điểm click (5 ô)", command=self._calibrate_clicks).pack(fill=tk.X, pady=2)
        self.region_label = ttk.Label(cal, text=self._region_text())
        self.region_label.pack(anchor=tk.W, pady=4)

        preview_box = ttk.LabelFrame(cal, text="Xem trước vùng Shop", padding=4)
        preview_box.pack(fill=tk.X, pady=4)
        self.preview_label = ttk.Label(
            preview_box,
            text="Chưa có ảnh — chọn vùng Shop để xem preview",
            anchor=tk.CENTER,
            wraplength=300,
        )
        self.preview_label.pack(fill=tk.X)
        ttk.Button(preview_box, text="Làm mới ảnh (chụp lại màn hình)", command=self._refresh_shop_preview).pack(
            fill=tk.X, pady=4
        )

        settings = ttk.LabelFrame(right, text="Tùy chỉnh", padding=8)
        settings.pack(fill=tk.X, pady=4)

        self.threshold_var = tk.DoubleVar(value=self.config.get("match_threshold", 0.72))
        self._add_threshold_scale(settings, "Độ khớp ảnh (0.5 - 0.95):", self.threshold_var)

        ttk.Label(settings, text="Tốc độ quét (ms, 0 = nhanh nhất):").pack(anchor=tk.W, pady=(8, 0))
        self.interval_var = tk.IntVar(value=self.config.get("scan_interval_ms", 3))
        ttk.Spinbox(settings, from_=0, to=100, textvariable=self.interval_var, width=8).pack(anchor=tk.W)

        self.name_threshold_var = tk.DoubleVar(value=self.config.get("name_match_threshold", 0.65))
        self._add_threshold_scale(settings, "Độ khớp tên OCR (0.5 - 0.95):", self.name_threshold_var, pady=(8, 0))

        ttk.Label(settings, text=f"Phím bật/tắt: {self.config.get('hotkey_toggle', 'f8').upper()}").pack(anchor=tk.W, pady=(8, 0))

        ctrl = ttk.Frame(right)
        ctrl.pack(fill=tk.X, pady=8)
        self.toggle_btn = ttk.Button(ctrl, text="▶ BẮT ĐẦU (F8)", command=self._toggle_scan)
        self.toggle_btn.pack(fill=tk.X, ipady=8)

        log_frame = ttk.LabelFrame(self.root, text="Nhật ký", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=False, padx=8, pady=8, ipady=4)
        self.log_text = tk.Text(log_frame, height=8, state=tk.DISABLED, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _add_threshold_scale(self, parent, label: str, var: tk.DoubleVar, pady: tuple = (0, 0)):
        """Thanh trượt ngưỡng khớp kèm số hiển thị realtime (vd: 65%)."""
        block = ttk.Frame(parent)
        block.pack(fill=tk.X, pady=pady)

        header = ttk.Frame(block)
        header.pack(fill=tk.X)
        ttk.Label(header, text=label).pack(side=tk.LEFT)
        value_label = ttk.Label(header, text="", foreground="#2563eb", font=("Segoe UI", 10, "bold"))
        value_label.pack(side=tk.RIGHT)

        def refresh(*_):
            value_label.config(text=f"{var.get():.0%}")

        var.trace_add("write", refresh)
        ttk.Scale(block, from_=0.5, to=0.95, variable=var, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(2, 0))
        refresh()

    def _region_text(self) -> str:
        """Text hiển thị trạng thái cấu hình shop (tọa độ + số điểm click)."""
        r = self.config.get("shop_region")
        c = self.config.get("slot_centers", [])
        if r:
            return f"Shop: ({r['left']}, {r['top']}) {r['width']}x{r['height']} | Click: {len(c)}/5 ô"
        return "Chưa cấu hình shop"

    def _log(self, msg: str):
        """Ghi dòng log có timestamp vào khung Nhật ký phía dưới."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _load_champions_async(self):
        """Tải danh sách tướng từ API trong thread nền (không block UI)."""
        self.status_var.set("Đang tải danh sách tướng...")
        threading.Thread(target=self._fetch_champions, daemon=True).start()

    def _fetch_champions(self):
        """Gọi API Data Dragon lấy list tướng, cập nhật UI khi xong."""
        try:
            champs = fetch_champion_list()
            self.root.after(0, lambda: self._populate_champions(champs))
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"Lỗi tải tướng: {e}"))

    def _populate_champions(self, champs: list[dict]):
        """Điền danh sách tướng vào checkbox, khôi phục tướng đã chọn từ config."""
        self.champions = champs
        selected = set(self.config.get("selected_champions", []))
        for c in champs:
            var = tk.BooleanVar(value=c["name"] in selected)
            self.champion_vars[c["name"]] = var
        self._render_champion_list()
        self.status_var.set(f"Đã tải {len(champs)} tướng")

    def _on_champ_canvas_resize(self, event):
        """Khi khung danh sách đổi kích thước → tự chia thêm/bớt cột tướng."""
        self.champ_canvas.itemconfig(self._champ_window_id, width=event.width)
        cols = max(2, event.width // 180)
        if cols != self._champ_list_cols:
            self._champ_list_cols = cols
            self._render_champion_list()

    def _bind_champ_mousewheel(self, _event=None):
        """Bật cuộn chuột khi chuột vào danh sách tướng."""
        self.champ_canvas.bind_all("<MouseWheel>", self._on_champ_mousewheel)

    def _unbind_champ_mousewheel(self, _event=None):
        """Tắt cuộn chuột khi chuột rời khỏi danh sách tướng."""
        self.champ_canvas.unbind_all("<MouseWheel>")

    def _on_champ_mousewheel(self, event):
        """Xử lý sự kiện lăn chuột để cuộn danh sách tướng."""
        self.champ_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _render_champion_list(self):
        """Vẽ lại danh sách tướng dạng nhiều cột, nhóm theo cost gold."""
        for w in self.champ_inner.winfo_children():
            w.destroy()

        query = self.search_var.get().lower().strip()
        filtered = [
            c for c in self.champions if not query or query in c["name"].lower()
        ]

        cols = self._champ_list_cols
        for col in range(cols):
            self.champ_inner.columnconfigure(col, weight=1, uniform="champ")

        row_idx = 0
        by_tier: dict[int, list] = {}
        for c in filtered:
            by_tier.setdefault(c["tier"], []).append(c)

        for tier in sorted(by_tier.keys()):
            ttk.Label(
                self.champ_inner,
                text=f"── Cost {tier} gold ──",
                font=("Segoe UI", 9, "bold"),
                foreground="#2563eb",
            ).grid(row=row_idx, column=0, columnspan=cols, sticky=tk.W, padx=4, pady=(10, 2))
            row_idx += 1

            for i, c in enumerate(by_tier[tier]):
                r = row_idx + i // cols
                col = i % cols
                var = self.champion_vars.get(c["name"])
                if var is None:
                    var = tk.BooleanVar()
                    self.champion_vars[c["name"]] = var
                ttk.Checkbutton(
                    self.champ_inner,
                    text=c["name"],
                    variable=var,
                    width=18,
                ).grid(row=r, column=col, sticky=tk.W, padx=6, pady=2)

            row_idx += (len(by_tier[tier]) + cols - 1) // cols

        if not filtered:
            ttk.Label(self.champ_inner, text="Không tìm thấy tướng", foreground="#888").grid(
                row=0, column=0, padx=8, pady=8
            )

    def _filter_champions(self):
        """Lọc danh sách tướng theo ô tìm kiếm."""
        self._render_champion_list()

    def _select_all(self):
        """Tick chọn tất cả tướng trong danh sách."""
        for var in self.champion_vars.values():
            var.set(True)

    def _deselect_all(self):
        """Bỏ tick tất cả tướng."""
        for var in self.champion_vars.values():
            var.set(False)

    def _upload_template(self):
        """Upload ảnh portrait tùy chỉnh cho 1 tướng (nhận diện chính xác hơn)."""
        names = [n for n, v in self.champion_vars.items() if v.get()]
        if len(names) != 1:
            messagebox.showinfo("Upload ảnh", "Chọn đúng 1 tướng (tick checkbox) rồi upload ảnh portrait của tướng đó.")
            return
        name = names[0]
        path = filedialog.askopenfilename(
            title=f"Chọn ảnh tướng {name}",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp"), ("All", "*.*")],
        )
        if not path:
            return
        dest = TEMPLATES_DIR / f"custom_{name}.png"
        shutil.copy(path, dest)
        custom = self.config.setdefault("custom_templates", {})
        custom[name] = str(dest)
        save_config(self.config)
        self._log(f"Đã upload ảnh cho {name}")
        messagebox.showinfo("OK", f"Đã lưu ảnh tướng {name}")

    def _show_preview_image(self, pil_img: Image.Image):
        """Hiển thị ảnh preview shop trong khung xem trước."""
        max_w = 320
        w, h = pil_img.size
        if w > max_w:
            scale = max_w / w
            pil_img = pil_img.resize((max_w, int(h * scale)), Image.Resampling.LANCZOS)
        self._preview_photo = ImageTk.PhotoImage(pil_img)
        self.preview_label.configure(image=self._preview_photo, text="")

    def _load_shop_preview_from_disk(self):
        """Load ảnh preview đã lưu lần trước khi mở tool."""
        if SHOP_PREVIEW_PATH.exists():
            try:
                self._show_preview_image(Image.open(SHOP_PREVIEW_PATH))
            except Exception:
                pass

    def _update_shop_preview(self, capture_live: bool = True):
        """Chụp/lấy ảnh vùng shop và cập nhật preview (chạy trong thread nền)."""
        region = self.config.get("shop_region")
        if not region:
            return
        centers = self.config.get("slot_centers", [])
        slot_centers = centers if len(centers) == 5 else None

        def work():
            pil = build_shop_preview(region, slot_centers, capture_live=capture_live)
            if pil:
                self.root.after(0, lambda: self._show_preview_image(pil))

        threading.Thread(target=work, daemon=True).start()

    def _refresh_shop_preview(self):
        """Nút 'Làm mới ảnh' — chụp lại màn hình vùng shop hiện tại."""
        if not self.config.get("shop_region"):
            messagebox.showinfo("Preview", "Chọn vùng Shop trước.")
            return
        self._log("Đang chụp lại vùng shop...")
        self._update_shop_preview(capture_live=True)

    def _calibrate_region(self):
        """Overlay toàn màn hình: kéo khung chọn vùng 5 ô shop."""
        self.root.iconify()
        self._log("Kéo khung chọn vùng 5 ô shop (Esc để hủy)...")
        overlay = tk.Toplevel()
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-alpha", 0.25)
        overlay.configure(bg="black")
        overlay.attributes("-topmost", True)

        canvas = tk.Canvas(overlay, cursor="cross", highlightthickness=0, bg="black")
        canvas.pack(fill=tk.BOTH, expand=True)
        start = {"x": 0, "y": 0}
        rect_id = None

        def on_press(e):
            nonlocal rect_id
            start["x"], start["y"] = e.x, e.y
            if rect_id:
                canvas.delete(rect_id)
            rect_id = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#22c55e", width=2)

        def on_drag(e):
            if rect_id:
                canvas.coords(rect_id, start["x"], start["y"], e.x, e.y)

        def on_release(e):
            x1, y1 = start["x"], start["y"]
            x2, y2 = e.x, e.y
            left, top = min(x1, x2), min(y1, y2)
            width, height = abs(x2 - x1), abs(y2 - y1)
            if width > 50 and height > 30:
                self.config["shop_region"] = {
                    "left": left,
                    "top": top,
                    "width": width,
                    "height": height,
                }
                save_config(self.config)
                self.region_label.configure(text=self._region_text())
                self._log(f"Đã lưu vùng shop: {left},{top} {width}x{height}")
                overlay.destroy()
                self.root.deiconify()
                self.root.after(400, lambda: self._update_shop_preview(capture_live=True))
                return
            overlay.destroy()
            self.root.deiconify()

        def on_escape(_=None):
            overlay.destroy()
            self.root.deiconify()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", on_escape)

    def _calibrate_clicks(self):
        """Overlay toàn màn hình: click giữa 5 ô shop để lưu điểm mua tướng."""
        region = self.config.get("shop_region")
        if not region:
            messagebox.showwarning("Cảnh báo", "Hãy chọn vùng Shop trước.")
            return

        self.root.iconify()
        centers: list[tuple[int, int]] = []

        overlay = tk.Toplevel()
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-alpha", 0.15)
        overlay.configure(bg="black")
        overlay.attributes("-topmost", True)

        hint = tk.StringVar(value="Click vào ẢNH tướng ô 1/5 (Esc hủy)")
        lbl = tk.Label(
            overlay,
            textvariable=hint,
            font=("Segoe UI", 16, "bold"),
            fg="#22c55e",
            bg="black",
        )
        lbl.place(relx=0.5, rely=0.05, anchor=tk.N)

        def on_click(e):
            centers.append((e.x_root, e.y_root))
            n = len(centers)
            if n >= 5:
                self.config["slot_centers"] = centers
                save_config(self.config)
                self.region_label.configure(text=self._region_text())
                self._log(f"Đã lưu 5 điểm click: {centers}")
                overlay.destroy()
                self.root.deiconify()
                self.root.after(400, lambda: self._update_shop_preview(capture_live=True))
                return
            hint.set(f"Click vào ẢNH tướng ô {n + 1}/5 (Esc hủy)")

        def on_escape(_=None):
            overlay.destroy()
            self.root.deiconify()

        overlay.bind("<Button-1>", on_click)
        overlay.bind("<Escape>", on_escape)
        self._log("Click lần lượt giữa 5 ô shop...")

    def _get_manual_names(self) -> list[str]:
        """Lấy tên tướng từ ô gõ tay (phân cách bằng phẩy hoặc xuống dòng)."""
        raw = self.manual_names_text.get("1.0", tk.END)
        parts = raw.replace("\n", ",").split(",")
        return [p.strip() for p in parts if p.strip()]

    def _get_all_target_names(self) -> list[str]:
        """Gộp tên tướng từ checkbox + ô gõ tay (không trùng)."""
        names = list(self._get_selected_names())
        for n in self._get_manual_names():
            if n not in names:
                names.append(n)
        return names

    def _get_selected_names(self) -> list[str]:
        """Lấy danh sách tướng đang được tick checkbox."""
        return [n for n, v in self.champion_vars.items() if v.get()]

    def _prepare_scanner(self) -> ShopScanner | None:
        """Tải ảnh mẫu, validate cấu hình và tạo ShopScanner sẵn sàng quét."""
        names = self._get_all_target_names()
        detect_image = self.detect_image_var.get()
        detect_name = self.detect_name_var.get()

        if not names:
            messagebox.showwarning("Cảnh báo", "Chọn tướng (checkbox) hoặc gõ tên tướng.")
            return None
        if not detect_image and not detect_name:
            messagebox.showwarning("Cảnh báo", "Bật ít nhất 1 chế độ: 'Bắt theo ảnh' hoặc 'Bắt theo tên'.")
            return None

        region = self.config.get("shop_region")
        centers = self.config.get("slot_centers", [])
        if not region or len(centers) != 5:
            messagebox.showwarning("Cảnh báo", "Cấu hình vùng Shop và 5 điểm click trước.")
            return None

        if detect_name and self.name_threshold_var.get() > 0.75:
            self._log("Cảnh báo: Độ khớp tên > 75% — nên hạ xuống ~0.55–0.65")
        if detect_image and self.threshold_var.get() > 0.75:
            self._log("Cảnh báo: Độ khớp ảnh > 75% — ảnh Data Dragon khó khớp in-game, nên hạ ~0.60–0.70")
        if not detect_image and detect_name:
            self._log("Gợi ý: Bật thêm 'Bắt theo ảnh' để mua chính xác hơn")

        templates = {}
        if detect_image:
            self.status_var.set("Đang tải ảnh tướng...")
            self.root.update()

            ddragon_paths = {}
            for c in self.champions:
                if c["name"] not in names:
                    continue
                path = download_template(c["name"], c["image_url"])
                if path:
                    ddragon_paths[c["name"]] = path

            custom = self.config.get("custom_templates", {})
            templates = build_templates(names, custom, ddragon_paths)
            if not templates:
                if not detect_name:
                    messagebox.showerror("Lỗi", "Không tải được ảnh tướng. Bật 'Bắt theo tên' hoặc upload ảnh.")
                    return None
                self._log("Không có ảnh — chỉ dùng bắt theo tên")

        self.config["selected_champions"] = self._get_selected_names()
        self.config["manual_names"] = self.manual_names_text.get("1.0", tk.END).strip()
        self.config["detect_by_image"] = detect_image
        self.config["detect_by_name"] = detect_name
        self.config["match_threshold"] = self.threshold_var.get()
        self.config["name_match_threshold"] = self.name_threshold_var.get()
        self.config["scan_interval_ms"] = self.interval_var.get()
        save_config(self.config)

        scanner = ShopScanner(
            shop_region=region,
            slot_centers=[tuple(c) for c in centers],
            templates=templates,
            target_names=names,
            threshold=self.threshold_var.get(),
            name_threshold=self.name_threshold_var.get(),
            detect_by_image=detect_image,
            detect_by_name=detect_name,
            scan_interval_ms=self.interval_var.get(),
            name_scan_interval_ms=self.config.get("name_scan_interval_ms", 50),
            buy_cooldown_ms=self.config.get("buy_cooldown_ms", 90),
            buy_delay_ms=self.config.get("buy_delay_ms", 0),
            on_match=lambda name, slot, score, method: self.root.after(
                0,
                lambda n=name, s=slot, sc=score, m=method: self._log(
                    f"✓ Mua {n} ở ô {s} ({m} {sc:.0%})"
                ),
            ),
            on_status=lambda s: self.root.after(0, lambda: self.status_var.set(s)),
        )
        modes = []
        if detect_image and templates:
            modes.append("ảnh")
        if detect_name:
            modes.append("tên")
        self._log(f"Sẵn sàng bắt {len(names)} tướng [{', '.join(modes)}]: {', '.join(names)}")
        return scanner

    def _toggle_scan(self):
        """Bật/tắt quét shop — gọi bởi nút BẮT ĐẦU hoặc phím F8."""
        if self.scanner and self.scanner.is_running:
            self.scanner.stop()
            self.scanner = None
            self.toggle_btn.configure(text="▶ BẮT ĐẦU (F8)")
            self.status_var.set("Đã dừng")
            return

        scanner = self._prepare_scanner()
        if not scanner:
            return
        self.scanner = scanner
        self.scanner.start()
        self.toggle_btn.configure(text="⏹ DỪNG (F8)")
        self._log("Bắt đầu quét — bạn chỉ cần roll (D) trong game!")

    def _register_hotkey(self):
        """Đăng ký phím tắt F8 (global) để bật/tắt tool khi đang trong game."""
        hk = self.config.get("hotkey_toggle", "f8")

        def on_hotkey():
            self.root.after(0, self._toggle_scan)

        try:
            keyboard.add_hotkey(hk, on_hotkey, suppress=False)
        except Exception:
            self._log("Không đăng ký phím tắt — chạy app bằng quyền Admin")

    def _on_close(self):
        """Dọn dẹp khi đóng app: dừng scanner, hủy phím tắt, unbind chuột."""
        if self.scanner:
            self.scanner.stop()
        try:
            self._unbind_champ_mousewheel()
        except Exception:
            pass
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        """Chạy vòng lặp giao diện Tkinter."""
        self.root.mainloop()


if __name__ == "__main__":
    try:
        TFTAutoBuyApp().run()
    except Exception:
        import traceback

        err = traceback.format_exc()
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("TFT Auto Buy — Lỗi", err)
            root.destroy()
        except Exception:
            raise
