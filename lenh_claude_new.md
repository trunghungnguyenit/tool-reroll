Đây là bộ **ClaudeKit** — một toolkit khá đầy đủ với khoảng 60 lệnh `/...`, được tổ chức theo nhóm chức năng (namespace bằng thư mục con) của Thư mục **.claude**. Phân tích công dụng từng lệnh theo nhóm:

**1. Khởi tạo / Bootstrap dự án**
| Lệnh | Công dụng |
|---|---|
| `/bootstrap` | Khởi tạo dự án mới, làm từng bước có xác nhận |
| `/bootstrap/auto` | Khởi tạo dự án mới tự động (ít hỏi lại) |
| `/bootstrap/auto/fast` | Khởi tạo nhanh, tự động, ít bước nhất |
| `/bootstrap/auto/parallel` | Khởi tạo dự án, chạy song song nhiều tác vụ |
| `/new` | Scaffold nhanh dự án fullstack (Next.js + Hono backend) |

**2. Lập kế hoạch (Plan)**
| Lệnh | Công dụng |
|---|---|
| `/plan` | Tạo plan thông minh, tự làm rõ yêu cầu trước khi lập kế hoạch |
| `/plan/hard` | Nghiên cứu kỹ + phân tích + lập plan chi tiết (việc khó) |
| `/plan/fast` | Bỏ qua nghiên cứu, lập plan nhanh |
| `/plan/two` | Nghiên cứu và đưa ra **2 phương án** để chọn |
| `/plan/parallel` | Lập plan chia thành các phase chạy song song được |
| `/plan/ci` | Phân tích log GitHub Actions, lập plan sửa lỗi CI |
| `/plan/cro` | Lập plan tối ưu chuyển đổi (Conversion Rate Optimization) cho nội dung |

**3. Code / Triển khai tính năng**
| Lệnh | Công dụng |
|---|---|
| `/cook` | Implement tính năng theo từng bước, có xác nhận |
| `/cook/auto` | Tự implement toàn bộ ("trust me bro" — ít hỏi lại) |
| `/cook/auto/fast` | Bỏ qua nghiên cứu, chỉ scout + plan + code nhanh |
| `/cook/auto/parallel` | Chia phase song song, giao cho nhiều agent `fullstack-developer` |
| `/code` | Bắt đầu code + test theo plan đã có |
| `/code/no-test` | Code theo plan, **không** chạy test |
| `/code/parallel` | Thực thi các phase song song/tuần tự tùy cấu trúc plan |
| `/feature` | Lập plan **và** implement luôn một tính năng mới |

**4. Thiết kế / UI — nhóm quan trọng nhất cho nhu cầu của bạn**
| Lệnh | Công dụng |
|---|---|
| `/design/good` | Tạo thiết kế UI chỉn chu, "immersive" (chất lượng cao, chậm hơn) |
| `/design/fast` | Tạo thiết kế nhanh (ít chi tiết hơn) |
| `/design/describe` | Mô tả lại một thiết kế dựa trên ảnh chụp màn hình / video |
| `/design/screenshot` | Tạo thiết kế dựa theo ảnh chụp màn hình cho trước |
| `/design/video` | Tạo thiết kế dựa theo video tham khảo |
| `/design/3d` | Tạo thiết kế 3D tương tác bằng Three.js |
| `/fix/ui` | Phân tích và **sửa các lỗi UI** cụ thể |

**5. Sửa lỗi (Fix)**
| Lệnh | Công dụng |
|---|---|
| `/fix` | Phân tích & sửa lỗi, tự định tuyến cách xử lý phù hợp |
| `/fix/fast` | Sửa lỗi nhỏ, nhanh |
| `/fix/hard` | Dùng subagent để lập plan rồi sửa lỗi khó |
| `/fix/parallel` | Sửa lỗi song song bằng nhiều agent |
| `/fix/logs` | Phân tích log ứng dụng để tìm & sửa lỗi |
| `/fix/ci` | Phân tích log GitHub Actions và sửa |
| `/fix/test` | Chạy bộ test và sửa lỗi phát sinh |
| `/fix/types` | Sửa lỗi type (TypeScript...) |
| `/quick-fix` | Sửa nhanh lỗi nhỏ (tương tự `/fix/fast`) |

**6. Nội dung / Copywriting**
| Lệnh | Công dụng |
|---|---|
| `/content/good` | Viết nội dung/copy chất lượng cao |
| `/content/fast` | Viết nội dung nhanh |
| `/content/enhance` | Phân tích & cải thiện nội dung hiện có |
| `/content/cro` | Tối ưu nội dung để tăng tỉ lệ chuyển đổi |

**7. Tài liệu (Docs)**
| Lệnh | Công dụng |
|---|---|
| `/docs/init` | Phân tích codebase, tạo tài liệu ban đầu |
| `/docs/update` | Cập nhật tài liệu theo thay đổi codebase |
| `/docs/summarize` | Tóm tắt nhanh & cập nhật docs |

**8. Git**
| Lệnh | Công dụng |
|---|---|
| `/git/cm` | Stage toàn bộ file và tạo commit |
| `/git/cp` | Stage, commit, push code lên branch hiện tại |
| `/git/pr` | Tạo pull request |
| `/git/merge` | Merge code giữa 2 branch (⚠️ cần cẩn thận) |

**9. Quản lý Skill (mở rộng khả năng Claude)**
| Lệnh | Công dụng |
|---|---|
| `/skill/create` | Tạo một skill (agent skill) mới |
| `/skill/add` | Thêm file tham khảo/script vào skill có sẵn |
| `/skill/optimize` | Tối ưu lại một skill đã có |
| `/skill/optimize/auto` | Tối ưu skill tự động |
| `/skill/fix-logs` | Sửa skill dựa theo file `logs.txt` |

**10. Khác**
| Lệnh | Công dụng |
|---|---|
| `/ask` | Hỏi đáp kỹ thuật/kiến trúc, không sửa code |
| `/debug` | Debug và đề xuất giải pháp |
| `/scout` | Rà soát thư mục để trả lời yêu cầu (không sửa code) |
| `/scout/ext` | Rà soát bằng công cụ agent bên ngoài |
| `/review/codebase` | Quét & phân tích toàn bộ codebase |
| `/test` | Chạy test local và phân tích báo cáo |
| `/brainstorm` | Brainstorm ý tưởng tính năng |
| `/journal` | Ghi nhật ký công việc |
| `/watzup` | Tổng kết các thay đổi gần đây, wrap-up công việc |
| `/use-mcp` | Dùng công cụ từ MCP server đã kết nối |
| `/ck-help` | Hướng dẫn dùng ClaudeKit |

Ký hiệu ⚡ ở mô tả gốc thể hiện **độ nhanh/độ sâu**: càng nhiều ⚡ thì công đoạn càng kỹ (nghiên cứu, chia nhỏ phase...), càng ít ⚡ thì càng nhanh nhưng ít phân tích hơn.

---

# PHẦN B — Lệnh built-in của Claude Code (cập nhật 11/11/2026)

Nguồn: docs chính thức `code.claude.com/docs/en/commands` và `code.claude.com/docs/en/cli-reference`. Phần trên là lệnh ClaudeKit (custom command trong `.claude/commands/`); phần này là lệnh có sẵn trong Claude Code, không cần cài thêm.

Quy ước:
- `<arg>` bắt buộc, `[arg]` tùy chọn.
- **[Skill]** = bundled skill (prompt giao cho Claude, tắt được bằng `disableBundledSkills`). **[Workflow]** = bundled dynamic workflow, fan-out nhiều subagent chạy background.
- Không phải lệnh nào cũng hiện trong menu `/`: phụ thuộc platform, plan, môi trường.
- Lệnh chỉ được nhận khi nằm ở đầu message; phần text phía sau là argument.
- Gõ lệnh khi Claude đang trả lời: lệnh được queue đến hết turn. Một số chạy ngay: `/status`, `/tasks`, `/usage`, `/model`, `/effort`, `/fast`, `/permissions`, `/add-dir`, `/bug`.

**11. Session & hội thoại**
| Lệnh | Công dụng |
|---|---|
| `/clear [name]` | Bắt đầu hội thoại mới với context rỗng, giữ project memory. Truyền name để đặt nhãn cho hội thoại cũ trong picker `/resume`. Alias: `/reset`, `/new` |
| `/compact [instructions]` | Tóm tắt hội thoại để giải phóng context, vẫn tiếp tục cùng hội thoại. Có thể truyền chỉ dẫn trọng tâm cho bản tóm tắt |
| `/resume [session]` | Resume hội thoại theo ID/tên, hoặc mở session picker (background session đánh dấu `bg`). Alias: `/continue` |
| `/branch [name]` | Tạo nhánh hội thoại tại điểm hiện tại và chuyển sang nhánh đó; bản gốc giữ nguyên, quay lại bằng `/resume` |
| `/fork [prompt]` | Copy hội thoại sang một background session mới, bạn vẫn làm tiếp ở session hiện tại. Có prompt thì bản copy chạy ngay |
| `/subtask <task>` | Spawn forked subagent chạy background, kế thừa toàn bộ hội thoại; kết quả trả về hội thoại này |
| `/rewind` | Quay hội thoại và/hoặc code về checkpoint trước, hoặc tóm tắt từ một message được chọn. Alias: `/checkpoint`, `/undo` |
| `/rename [name]` | Đổi tên session (hiện trên prompt bar). Không truyền tên thì tự sinh từ lịch sử. Tối đa 200 ký tự |
| `/export [filename]` | Export hội thoại ra plain text; có filename thì ghi thẳng ra file, không thì mở dialog copy/save |
| `/copy [N]` | Copy response gần nhất vào clipboard; `/copy 2` = response áp chót. Có code block thì hiện picker chọn từng block; nhấn `w` để ghi ra file (hữu ích qua SSH) |
| `/recap` | Sinh tóm tắt một dòng của session hiện tại |
| `/btw [question]` | Hỏi câu hỏi phụ về session mà không thêm vào lịch sử hội thoại |
| `/cd <path>` | Chuyển session sang working directory khác, giữ nguyên hội thoại |
| `/add-dir <path>` | Thêm working directory cho session hiện tại. Chỉ cấp quyền truy cập file; phần lớn cấu hình `.claude/` trong thư mục đó không được load |
| `/exit` | Thoát CLI. Trong background session đang attach thì chỉ detach, session vẫn chạy. Alias: `/quit` |

**12. Model, effort, context, memory**
| Lệnh | Công dụng |
|---|---|
| `/model [model]` | Đổi model và lưu làm default cho session mới. Không argument thì mở picker; nhấn `s` để chỉ đổi cho session hiện tại; mũi tên trái/phải chỉnh effort |
| `/effort [level\|auto\|status\|ultracode [on\|off]]` | Đặt effort level: `low` → `xhigh`, `max` (chỉ trong session), `auto`; `status` in mức hiện tại. `ultracode on/off` bật/tắt ultracode cho session (dạng `on`/`off` cần v2.1.284+) |
| `/fast [on\|off]` | Bật/tắt fast mode |
| `/advisor [model\|off]` | Bật/tắt advisor tool: hỏi ý kiến một model thứ hai ở các thời điểm then chốt của task. Nhận `fable`, `opus`, `sonnet` hoặc model ID đầy đủ |
| `/plan [description]` | Vào plan mode; có description thì bắt đầu luôn với task đó, ví dụ `/plan fix the auth bug` |
| `/goal [condition\|clear]` | Đặt goal: Claude làm tiếp qua nhiều turn đến khi điều kiện thỏa. Không argument: xem goal hiện tại. `clear`/`stop`/`off`/`reset`/`none`/`cancel` để hủy |
| `/context [all]` | Hiển thị mức dùng context dạng grid màu kèm gợi ý tối ưu; `all` để mở rộng breakdown từng mục |
| `/autocompact [auto\|<tokens>]` | Đặt ngưỡng auto-compact (ví dụ `500k`, hoặc `auto`), lưu vào user settings. Cần v2.1.221+ |
| `/output-style [style]` | Liệt kê hoặc chuyển output style, ví dụ `/output-style concise`. Cần v2.1.269+ |
| `/memory` | Sửa các file `CLAUDE.md`, bật/tắt auto memory, xem entry của auto memory |
| `/init` | Khởi tạo project với file `CLAUDE.md`. Đặt `CLAUDE_CODE_NEW_INIT=1` để có flow tương tác (skills, hooks, memory cá nhân) |

**13. Background, parallel, agent, schedule**
| Lệnh | Công dụng |
|---|---|
| `/background [prompt]` | Detach session hiện tại thành background agent, giải phóng terminal. Theo dõi bằng `claude agents`. Alias: `/bg` |
| `/tasks` | Xem và quản lý background work của session hiện tại, gồm cả subagent đã xong. Alias: `/bashes` |
| `/stop` | Dừng background session đang attach; transcript và worktree được giữ lại |
| `/agents` | In nhắc nhở: nhờ Claude tạo/quản lý subagent, hoặc sửa trực tiếp `.claude/agents/`, `~/.claude/agents/`. UI tương tác chỉ còn ở v2.1.197 trở về trước |
| `/list-agents` | Liệt kê subagent, teammate của agent team và các session Claude Code khác mà Claude nhắn được. Alias: `/peers`. Cần v2.1.224+ và cross-session messaging được bật |
| `/batch <instruction>` | **[Skill]** Thay đổi quy mô lớn trên codebase chạy song song: research, chia 5–30 unit độc lập, trình plan; duyệt xong thì mỗi unit một background subagent trong worktree riêng. Ví dụ: `/batch migrate src/ from JavaScript to TypeScript` |
| `/loop [interval] [prompt]` | **[Skill]** Chạy lặp một prompt khi session còn mở. Bỏ interval thì Claude tự chọn nhịp. Ví dụ: `/loop 5m check if the deploy finished`. Alias: `/proactive` |
| `/schedule [description]` | Tạo, sửa, liệt kê, chạy routine (thực thi trên cloud). Alias: `/routines` |
| `/workflows` | Mở màn hình tiến độ workflow: xem, pause, resume, save |
| `/workflow-authoring` | **[Skill]** Load reference để viết script dynamic workflow. Cần v2.1.248+ |
| `/deep-research <question>` | **[Workflow]** Fan-out web search, fetch và đối chiếu nguồn, tổng hợp thành report có citation. Chỉ chạy khi bạn gọi |

**14. Review, verify, ship**
| Lệnh | Công dụng |
|---|---|
| `/diff` | Xem thay đổi trong working tree, gồm cả edit Claude đã làm |
| `/code-review [low\|medium\|high\|xhigh\|max\|ultra] [--fix] [--comment] [--max-findings n\|all\|default] [pr#\|branch\|path]` | **[Skill]** Review diff hiện tại (hoặc PR number, branch, path) tìm bug correctness. `--fix` áp dụng findings, `--comment` post lên GitHub PR / GitLab MR, `ultra` chạy cloud review sâu. Alias: `/review` |
| `/review ...` | Alias của `/code-review`, cùng level và flag, ví dụ `/review 1234`. Trước v2.1.223 là lệnh riêng review PR single-pass |
| `/ultrareview [PR or branch]` | Alias của `/code-review ultra`: review multi-agent trong cloud sandbox. Pro/Max có 3 lượt free, sau đó cần usage credits |
| `/security-review` | Phân tích diff giữa branch hiện tại và default branch của origin để tìm lỗ hổng bảo mật (injection, auth, data exposure). Cần remote `origin` |
| `/simplify [target]` | **[Skill]** Review code đã đổi để dọn dẹp và tự apply fix; 4 review agent chạy song song (reuse, simplification, efficiency, abstraction). Không tìm bug correctness |
| `/run` | **[Skill]** Launch và điều khiển app của project để thấy thay đổi chạy thật, không chỉ pass test |
| `/verify` | **[Skill]** Xác nhận thay đổi đúng bằng cách build, chạy app và quan sát kết quả. Chỉ chạy khi bạn gọi |
| `/run-skill-generator` | **[Skill]** Viết skill riêng cho project để dạy `/run` và `/verify` cách build, launch, điều khiển app |
| `/debug [description]` | **[Skill]** Bật debug logging cho session và troubleshoot bằng cách đọc debug log |
| `/autofix-pr [prompt]` | Spawn cloud session theo dõi PR của branch hiện tại, tự push fix khi CI fail hoặc reviewer comment. Cần `gh` CLI và quyền dùng cloud session |

**15. Cloud, remote, app khác**
| Lệnh | Công dụng |
|---|---|
| `/teleport` | Kéo cloud session về terminal này (fetch branch + hội thoại). Alias: `/tp`. Cần claude.ai subscription |
| `/remote-control` | Cho phép điều khiển session local này từ claude.ai / thiết bị khác. Alias: `/rc` |
| `/remote-env` | Chọn cloud environment mặc định cho cloud session khởi tạo từ CLI |
| `/web-setup` | Kết nối tài khoản GitHub cho cloud session bằng credential `gh` CLI local |
| `/desktop` | Tiếp tục session trong app Claude Code Desktop. Chỉ macOS và Windows x64, cần Claude subscription. Alias: `/app` |
| `/mobile` | Hiện QR code tải app Claude mobile. Alias: `/ios`, `/android` |
| `/chrome` | Cấu hình Claude in Chrome |
| `/claude-in-chrome [task]` | **[Skill]** Giao Claude làm task trong browser (test page, điền form, đọc console log) qua Claude in Chrome |
| `/ide` | Quản lý IDE integration và xem status |

**16. Artifact, design, slides, API**
| Lệnh | Công dụng |
|---|---|
| `/artifacts` | Liệt kê artifact của bạn hoặc được share; attach vào session, mở trong browser, hoặc copy link. Cần v2.1.208+ |
| `/artifact-capabilities` | **[Skill]** Load reference về runtime capability của artifact đã publish (gọi connector, cho download file...) |
| `/artifact-diagramming` | **[Skill]** Load hướng dẫn vẽ diagram trong artifact (inline SVG, đọc được ở light/dark theme). Cần v2.1.221+ |
| `/design [brief]` | **[Skill]** Dựng UI mockup, screen flow, landing page, poster thành artboard trên một canvas, publish dạng Claude Design artifact; export PNG/PDF từng artboard. Cần v2.1.265+. Không có trên Bedrock, Google Cloud Agent Platform, Microsoft Foundry |
| `/design-login` | Cấp quyền truy cập design system cho `/design-sync` bằng tài khoản claude.ai |
| `/design-sync [hint]` | **[Skill]** Convert React design system của repo và upload lên Claude Design để design dùng đúng component thật. Lần sync đầu có thể mất vài giờ với repo lớn |
| `/slides [brief]` | **[Skill]** Tạo presentation dạng Claude Slides artifact từ brief. Cần v2.1.265+ |
| `/dataviz [request]` | **[Skill]** Hướng dẫn thiết kế chart, graph, dashboard: chọn dạng chart, gán màu theo vai trò, validate palette (colorblind, contrast) |
| `/claude-api [migrate\|upgrade\|managed-agents-onboard\|prompt-audit\|cost-optimize\|build-eval\|hillclimb\|preserved-thinking-migration]` | **[Skill]** Load reference Claude API và Managed Agents theo ngôn ngữ của project. Tự kích hoạt khi code import `anthropic` hoặc `@anthropic-ai/sdk` |

**17. Cấu hình, permission, giao diện**
| Lệnh | Công dụng |
|---|---|
| `/config [key=value ...]` | Mở Settings (theme, model, output style...). Truyền `key=value` để set trực tiếp, ví dụ `/config theme=dark`; `/config --help` liệt kê key. Alias: `/settings` |
| `/update-config [request]` | **[Skill]** Mô tả thay đổi setting (allow command, env var, hook) để Claude sửa đúng file `settings.json` |
| `/permissions` | Quản lý rule allow/ask/deny cho tool, working directory, xem auto mode denial gần đây. Alias: `/allowed-tools` |
| `/fewer-permission-prompts` | **[Skill]** Quét transcript tìm Bash/MCP call read-only hay gặp, thêm allowlist vào `.claude/settings.json` của project |
| `/auto-mode-setup` | Draft entry `autoMode.environment` từ project và session gần đây, review rồi lưu vào user settings. Cần plan Pro/Max/Team, v2.1.228+ (Windows native: v2.1.233+) |
| `/sandbox` | Bật/tắt sandbox mode (chỉ trên platform hỗ trợ) |
| `/hooks` | Xem cấu hình hook |
| `/keybindings` | Mở file keyboard shortcut |
| `/statusline` | Cấu hình status line; mô tả mong muốn, hoặc để trống để tự cấu hình theo shell prompt |
| `/theme` | Đổi color theme (auto, light/dark, daltonized, ANSI, custom theme trong `~/.claude/themes/`) |
| `/color [color\|default]` | Đặt màu prompt bar cho session: `red`, `blue`, `green`, `yellow`, `purple`, `orange`, `pink`, `cyan`; `default` để reset |
| `/tui [default\|fullscreen]` | Chọn terminal UI renderer và relaunch, giữ nguyên hội thoại. `fullscreen` = alt-screen renderer không flicker |
| `/focus` | Bật/tắt focus view: chỉ hiện prompt cuối, tóm tắt tool call một dòng và response cuối. Chỉ có ở fullscreen rendering |
| `/scroll-speed` | Chỉnh tốc độ cuộn chuột. Chỉ fullscreen rendering, không có ở JetBrains terminal |
| `/terminal-setup` | Cài keybinding Shift+Enter xuống dòng cho VS Code, Cursor, Devin Desktop, Alacritty, Zed; cấu hình tương ứng cho Apple Terminal, iTerm2 |
| `/voice [hold\|tap\|off]` | Bật/tắt voice dictation. Cần tài khoản Claude.ai |
| `/privacy-settings` | Xem và sửa privacy settings. Chỉ cho Pro và Max |

**18. MCP, plugin, skill, tích hợp**
| Lệnh | Công dụng |
|---|---|
| `/mcp [reconnect (<server>\|all)\|enable\|disable [<server>\|all]]` | Quản lý kết nối MCP server và OAuth. Không argument: mở danh sách tương tác. `reconnect all` thử lại mọi server lỗi hoặc cần auth |
| `/plugin [subcommand]` | Quản lý plugin; subcommand `list`, `install`, `enable`, `disable` |
| `/reload-plugins [--force]` | Reload plugin đang active để áp dụng thay đổi mà không restart |
| `/plugin-authoring` | Load reference để viết mod (skill từ built-in plugin). Cần v2.1.287+ |
| `/skills` | Liệt kê skill; lọc theo tên/mô tả/nguồn; `t` sort theo token, `Space`/`Enter` đổi visibility |
| `/reload-skills` | Quét lại thư mục skill và command để nhận skill mới/đã sửa mà không restart |
| `/skill-doctor` | Xem mỗi skill tốn bao nhiêu context và được dùng thường xuyên thế nào. Cần v2.1.252+ |
| `/import [codex\|gemini\|cursor] [--dry-run] [--yes]` | Import cấu hình từ OpenAI Codex, Gemini CLI, Cursor: instruction file, MCP server, command, subagent, skill. `--dry-run` xem trước |
| `/install-github-app` | Cài Claude GitHub App cho repo, tùy chọn setup GitHub Actions. Chỉ github.com |
| `/install-slack-app` | Cài Claude Slack app (OAuth qua browser) |

**19. Tài khoản, usage, chẩn đoán, trợ giúp**
| Lệnh | Công dụng |
|---|---|
| `/login` | Đăng nhập tài khoản Anthropic |
| `/logout` | Đăng xuất |
| `/status` | Mở Settings ở tab Status: version, model, account, connectivity |
| `/usage` | Xem session cost, plan usage limit, activity stats. Alias: `/cost`, `/stats` (`/stats` mở tab Stats) |
| `/usage-credits` | Cấu hình usage credits, hoặc gửi yêu cầu cho admin khi chạm limit. Tên cũ: `/extra-usage` |
| `/rate-limit-options` | Các cách làm tiếp khi bị usage limit chặn: chờ và tự continue khi reset, thêm usage credits, upgrade plan |
| `/upgrade` | Mở trang upgrade plan (không hiện trên Enterprise) |
| `/passes` | Tặng bạn bè một tuần Claude Code free. Chỉ hiện khi account đủ điều kiện |
| `/insights` | Sinh HTML report phân tích session gần đây trên máy. Không có ở cloud session |
| `/team-onboarding` | Sinh onboarding guide cho team từ lịch sử dùng Claude Code 30 ngày gần nhất |
| `/doctor [prompt-audit [path]]` | **[Skill]** Checkup cài đặt, settings, extension, `CLAUDE.md` và đề xuất fix (apply sau khi bạn xác nhận). Alias: `/checkup` |
| `/feedback [report]` | Gửi feedback về Claude Code (cùng dialog với `/bug`) |
| `/bug [report]` | Báo bug hoặc share hội thoại; chọn lượng history gửi kèm và xác nhận consent trước khi gửi. Alias: `/share` |
| `/heapdump` | Ghi JS heap snapshot + memory breakdown để chẩn đoán memory cao. Ẩn khỏi menu, phải gõ đủ tên. Không share file `.heapsnapshot` (chứa hội thoại và credential) |
| `/release-notes` | Xem changelog theo version |
| `/help` | Hiện help và lệnh khả dụng |
| `/powerup` | Học tính năng Claude Code qua bài tương tác ngắn có demo |
| `/setup-bedrock` | Wizard cấu hình Amazon Bedrock. Ẩn đến khi đặt `CLAUDE_CODE_USE_BEDROCK=1` |
| `/setup-vertex` | Wizard cấu hình Google Cloud Agent Platform. Ẩn đến khi đặt `CLAUDE_CODE_USE_VERTEX=1` |
| `/radio` | Mở Claude FM lo-fi radio trong browser |
| `/stickers` | Đặt sticker Claude Code |

**20. Lệnh đã bị gỡ**
| Lệnh | Thay thế |
|---|---|
| `/pr-comments [PR]` | Gỡ từ v2.1.91. Nhờ Claude trực tiếp xem PR comment |
| `/vim` | Gỡ từ v2.1.92. Dùng `/config` → Editor mode |
| `/ultraplan <prompt>` | Đã gỡ. Dùng plan mode (`/plan`) |

**21. Lưu ý khi dùng chung với ClaudeKit**
- Cú pháp namespace: file trong thư mục con của `.claude/commands/` được gọi bằng dấu `:`. `.claude/commands/plan/hard.md` → `/plan:hard`. Các lệnh ở phần ClaudeKit ghi dạng `/plan/hard` là đường dẫn file; khi gõ dùng `/plan:hard`, `/cook:auto:fast`, `/fix:ci`, `/git:cm`, `/design:good`...
- Trùng tên: custom skill/command thay thế bundled skill và built-in command cùng tên trong local terminal session. Với bộ này, `/plan` và `/debug` của ClaudeKit che `/plan`, `/debug` built-in.
- `/new` của ClaudeKit trùng với alias `/new` của `/clear`; docs không nói rõ trường hợp này, kiểm tra trong menu `/` xem bản nào chạy.
- Alias không bị thay thế theo: skill tên `code-review` thay `/code-review`, nhưng `/review` vẫn chạy bản built-in.
- Skill và command file trùng tên thì skill thắng. `.claude/commands/` vẫn được hỗ trợ.
- ClaudeKit engineer 1.3.0+ gộp nhiều lệnh biến thể thành skill kèm flag (ví dụ `/ck:plan --hard`); chạy `/ck-help` để xem bản đang cài dùng cú pháp nào.

**22. CLI — lệnh `claude` gõ ngoài shell**
| Lệnh | Công dụng |
|---|---|
| `claude` | Mở interactive session |
| `claude "query"` | Mở interactive session với prompt ban đầu |
| `claude -p "query"` | Query non-interactive rồi thoát |
| `cat file \| claude -p "query"` | Xử lý nội dung pipe vào |
| `claude -c` | Tiếp tục hội thoại gần nhất trong thư mục hiện tại |
| `claude -c -p "query"` | Tiếp tục ở chế độ non-interactive |
| `claude -r "<session>" "query"` | Resume session theo ID hoặc tên |
| `claude update` | Update lên bản mới nhất |
| `claude install [version]` | Cài/cài lại native binary; nhận version cụ thể, `stable` hoặc `latest` |
| `claude doctor` | In chẩn đoán cài đặt và settings (read-only), không mở session |
| `claude auth login` | Đăng nhập; `--email`, `--sso`, `--console` (billing theo API usage) |
| `claude auth logout` | Đăng xuất |
| `claude auth status` | In trạng thái auth dạng JSON (`--text` cho dạng đọc được); exit code 0 nếu đã login, 1 nếu chưa |
| `claude setup-token` | Sinh OAuth token dài hạn cho CI/script. Cần Claude subscription |
| `claude agents` | Mở agent view để theo dõi và dispatch background session song song; `--json` in danh sách session |
| `claude attach <id\|name>` | Attach vào background session |
| `claude logs <id\|name>` | In output gần đây của background session |
| `claude stop <id>` | Dừng background session. Cũng nhận `claude kill` |
| `claude respawn <id>` | Restart background session, giữ hội thoại; `--all` cho mọi session đang chạy |
| `claude rm <id>` | Xóa background session khỏi danh sách (transcript vẫn còn trên máy) |
| `claude daemon status` | In state, version, socket directory, worker count của supervisor |
| `claude daemon logs` | Theo dõi log của supervisor (`~/.claude/daemon.log`) |
| `claude daemon run` | Chạy supervisor ở foreground |
| `claude daemon stop --any` | Dừng supervisor và các session nó host; `--keep-workers` để giữ session chạy |
| `claude mcp` | Cấu hình MCP server |
| `claude mcp login <name>` | Chạy OAuth flow của MCP server; `--no-browser` khi qua SSH |
| `claude mcp logout <name>` | Xóa OAuth credential đã lưu của MCP server |
| `claude plugin` | Quản lý plugin. Alias: `claude plugins` |
| `claude import [source]` | Mở session chạy `/import`; nhận `--dry-run`, `--yes` |
| `claude purge [path]` | Xóa toàn bộ state local của Claude Code cho một project (transcript, task list, debug log, file-edit history...). Chạy `--dry-run` trước; `--all` áp dụng cho mọi project |
| `claude remote-control` | Chạy Remote Control server (server mode, không có interactive session local) |
| `claude ultrareview [target]` | Chạy ultrareview non-interactive, in findings ra stdout; `--json`, `--timeout <minutes>`, `--post` |
| `claude auto-mode defaults` | In rule classifier mặc định của auto mode dạng JSON; `claude auto-mode config` xem config hiệu lực |
| `claude auto-mode reset` | Khôi phục cấu hình auto mode mặc định (xóa section `autoMode` trong user settings) |
| `claude gateway` | Chạy Claude apps gateway self-hosted (cho admin); cần `--config gateway.yaml` |
| `claude self-hosted-runner` | Chạy runner đăng ký máy/container với self-hosted environment; subcommand `setup`, `doctor`, `orchestrator` |
