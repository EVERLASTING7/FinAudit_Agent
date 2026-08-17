# 当前活跃 Request 清单

基线日期：2026-08-17。此清单只校验 `Request/` 根目录的当前开发规格；归档文档不参与现行行为解释。

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `IMPLEMENTATION_PLAN.md` | 58889 | `4A5684CF5576A0F03C7982100A1F65001558D3CFA0080DC934F1D5AE197741C1` |
| `PRODUCT_REQUIREMENTS.md` | 35886 | `F6A56C60C6F0789B95486870DD6227CC02EB963B85347BAAAA8546F6795B7F8D` |
| `README.md` | 8058 | `7219C2D34A111743DDA777D62C054E63A8C313E9FDE62EEBBE900761BBC71CFE` |
| `TECHNICAL_SPEC.md` | 136960 | `0FFF42374083E5C76D5D867986A9FE29F536B95833A8CB91A6F3AF92DBAEDAF5` |

复核命令：

```powershell
Get-ChildItem .\Request -File -Filter *.md | Get-FileHash -Algorithm SHA256
.\scripts\verify-baseline.ps1
```

旧版九份文档的原始字节身份保留在 `docs/baseline-manifest.md`，文件保存在 `Request/archive/legacy-v1/`。历史清单已被批准制品绑定，保持原字节不变；它不是当前开发清单。
