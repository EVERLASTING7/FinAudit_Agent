# Chrome 本地键盘路径证据 v1

状态：login + authenticated shell/dashboard 局部运行通过；正式可访问性验收未完成。
日期：2026-08-17

在可丢弃 PostgreSQL 和 `report-browser-gate-v1` 上，通过已连接的 Chrome `151.0.7922.138` 发送真实原生按键：

- 登录页：`username → password → remember_me_checkbox → login_button`；在登录按钮按 Enter 后进入 `/dashboard`。
- 工作台初始焦点为 `BODY`，连续 Tab 顺序为 `skip_to_main → logout → dashboard → users → operation_logs → knowledge_bases → qa → BODY`。
- 在 `skip_to_main` 按 Enter 后，URL hash 为 `#main-content`，活动元素为 `MAIN#main-content`，主标题为“工作台”。
- 本次增量的浏览器 console warning/error 为 0；门禁正常关闭并输出 `REPORT_BROWSER_GATE=PASS`，专用 PostgreSQL 容器清理完成。

机器证据位于 `tests/evaluation/browser-keyboard-chrome-local-v1.json`。

本文件只记录 2026-08-17 的历史局部证据；当时 Edge、屏幕阅读器和全 P0 路由矩阵均为 `NOT_RUN`。这些 local/test 技术缺口已由 2026-08-21 的 `tests/evaluation/local-p2-experience-compatibility-v1.json` 取代并关闭；production、残障用户人工验收和正式可访问性签署仍未运行。因此不能单独用本文件或后继技术证据标记正式 AC accepted。
