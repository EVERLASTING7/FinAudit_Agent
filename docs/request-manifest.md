# 当前活跃 Request 清单

基线日期：2026-08-19。此清单已同步 `CR-005-R2` 文档纠错、`CR-010-R2` 隔离 fixed_test Scanner Profile、`CR-027-R1` Job HTTP 双版本、`CR-028-R1` 制度撤销、`CR-029-R1` 通用纠错来源读取、`CR-030-R1` 撤销待执行读取合同、`local-knowledge-performance-v5`、`local-document-correction-crash-recovery-v1` 和 INV-004 single-statement/native-browser 当前工程证据，以及既有 `CR-021～026` local/test/Local MVP 决策；只校验 `Request/` 根目录的当前开发规格，归档文档不参与现行行为解释。Provider、production、真实数据迁移、提交和推送不在本次同步授权内。

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `IMPLEMENTATION_PLAN.md` | 75748 | `62F9092066990370A8D7703F3C3E332A740A0054DC67FBB2E212574BDAC80BD5` |
| `PRODUCT_REQUIREMENTS.md` | 45504 | `DA094135578155D23F46133C8BB1B500ABD9DB8521A68B36C9766ACEFFDB19CB` |
| `README.md` | 8733 | `6E7AE9E61CED4E681B24F38FC89FB8DFCAF9094A6CBC1D36EA3C0AF0C914ED66` |
| `TECHNICAL_SPEC.md` | 155111 | `4E5CEA80F665A6FCCBF38245A5D65A1EA30C3130908988BC435F293C4B5661F8` |

复核命令：

```powershell
Get-ChildItem .\Request -File -Filter *.md | Get-FileHash -Algorithm SHA256
.\scripts\verify-baseline.ps1
```

旧版九份文档的原始字节身份保留在 `docs/baseline-manifest.md`，文件保存在 `Request/archive/legacy-v1/`。历史清单已被批准制品绑定，保持原字节不变；它不是当前开发清单。
