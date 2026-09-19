# START HERE — Codex Development Pack

Mục tiêu: xây Telegram bot tín hiệu chứng khoán Việt Nam theo từng phase, KHÔNG code toàn bộ hệ thống trong một lần. Mặc định hoàn thành trọn phase đang mở trong một lượt; chỉ chia nhỏ phase khi gặp sự cố, blocker, phụ thuộc bên ngoài chưa giải quyết được hoặc rủi ro kỹ thuật/an toàn đáng kể.

## Quy tắc quan trọng nhất

Codex phải:
1. Đọc `AGENTS.md`.
2. Đọc `TASKS.md`.
3. Đọc `PROJECT_CONTEXT.md`.
4. Chỉ làm đúng phase đang được mở; mặc định triển khai và kiểm thử trọn phase trong một lượt. Chỉ chia thành các nhóm task nhỏ sau khi gặp một vấn đề cụ thể khiến không thể hoàn thành phase an toàn, và phải ghi rõ lý do trong `PROJECT_CONTEXT.md`.
5. Không tự chuyển sang phase tiếp theo nếu phase hiện tại chưa PASS, trừ khi
   phase đó chỉ bị chặn bởi điều kiện runtime bên ngoài như thị trường đóng cửa
   và người dùng đã cho phép rõ ràng. Không được đánh dấu PASS khi chưa có bằng chứng.
6. Sau mỗi bước có ý nghĩa:
   - chạy test,
   - ghi PASS/FAIL,
   - cập nhật `PROJECT_CONTEXT.md`,
   - cập nhật checkbox trong `TASKS.md`.
7. Không được báo "xong" nếu chưa chạy test.
8. Không được code toàn bộ bot trong một lần.

## Scope hiện tại

Chỉ làm Phase 0–1 trước:
- kiểm tra repository;
- dựng Vietcap market-data foundation;
- test realtime FPT + ACB + VNINDEX.

Telegram, strategy, scanner, backtest sẽ làm ở các phase sau.

## Cách bắt đầu với Codex

Dán prompt trong `CODEX_INITIAL_PROMPT.md`.

Sau mỗi phiên Codex mới, dùng prompt:

> Read `AGENTS.md`, `TASKS.md`, and `PROJECT_CONTEXT.md` first. Verify the
> repository against the recorded context. Continue from the active implementation
> phase and complete that phase end-to-end by default. Split it into smaller task
> groups only after a concrete failure, blocker, unresolved external dependency, or
> material technical/safety risk is encountered, and record the reason. A phase
> awaiting external live validation may remain pending while the next
> phase is developed only with explicit user authorization. Never fabricate live
> acceptance evidence. Run tests and update both context files before stopping.
