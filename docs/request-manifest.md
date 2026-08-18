# 当前活跃 Request 清单

基线日期：2026-08-18。此清单已同步 `CR-021` 的 local/test 百炼 Embedding Profile、`CR-022 / option-A / event-policy-v2 / USD-CNY-only / no-fx`、BOSS 确认的 Windows 本机 Local MVP Profile、`CR-023` 的全局 `auth-password-v2`、`CR-024` 的全局 HTTP 入口、`CR-025` 的四项 Local MVP AC 口径，以及 `CR-026` 的 local/test 批量检索评测证据；只校验 `Request/` 根目录的当前开发规格，归档文档不参与现行行为解释。

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `IMPLEMENTATION_PLAN.md` | 70952 | `D151101455751604D7643B62B4ED7883E846D94EE11CFF137CBD615857980AB8` |
| `PRODUCT_REQUIREMENTS.md` | 40630 | `37E06DE415AEF12CB20252343EE03794A368D593FB4E214675D7900164ECD463` |
| `README.md` | 8733 | `6E7AE9E61CED4E681B24F38FC89FB8DFCAF9094A6CBC1D36EA3C0AF0C914ED66` |
| `TECHNICAL_SPEC.md` | 139073 | `3BE0A839B15E3B8523B1D5FD887B7BADAE696A54FB5D128DFC4BD271EA06665F` |

复核命令：

```powershell
Get-ChildItem .\Request -File -Filter *.md | Get-FileHash -Algorithm SHA256
.\scripts\verify-baseline.ps1
```

旧版九份文档的原始字节身份保留在 `docs/baseline-manifest.md`，文件保存在 `Request/archive/legacy-v1/`。历史清单已被批准制品绑定，保持原字节不变；它不是当前开发清单。
