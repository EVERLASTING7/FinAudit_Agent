# Chrome 本地键盘路径证据 v1

状态：login + authenticated shell/dashboard 局部运行通过；正式可访问性验收未完成。
日期：2026-08-17

在可丢弃 PostgreSQL 和 `report-browser-gate-v1` 上，通过已连接的 Chrome `151.0.7922.138` 发送真实原生按键：

- 登录页：`username → password → remember_me_checkbox → login_button`；在登录按钮按 Enter 后进入 `/dashboard`。
- 工作台初始焦点为 `BODY`，连续 Tab 顺序为 `skip_to_main → logout → dashboard → users → operation_logs → knowledge_bases → qa → BODY`。
- 在 `skip_to_main` 按 Enter 后，URL hash 为 `#main-content`，活动元素为 `MAIN#main-content`，主标题为“工作台”。
- 本次增量的浏览器 console warning/error 为 0；门禁正常关闭并输出 `REPORT_BROWSER_GATE=PASS`，专用 PostgreSQL 容器清理完成。

机器证据位于 `tests/evaluation/browser-keyboard-chrome-local-v1.json`。

以下内容仍为 `NOT_RUN`：Edge 原生键盘（本机 Edge `151.0.4129.86` 已安装，但当前没有可控 Edge 浏览器连接）、屏幕阅读器、所有 P0 路由的完整键盘矩阵、production 和正式可访问性签署。因此 FE/TEST/AC 状态保持 `partial`，不能用本证据标记 accepted。
