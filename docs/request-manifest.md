# 当前活跃 Request 清单

基线日期：2026-08-21。此清单已同步当前 accepted Alembic head `20260818_027`、58/58 张物理表与既有 `CR-005-R2`、`CR-010-R2`、`CR-021～031` 的 Local MVP/local-test 决策和工程证据；只校验 `Request/` 根目录的当前开发规格，归档文档不参与现行行为解释。业务代表性 85%/95% 与重复/风险标准答案已移出当前 Local MVP Goal，但仍未运行或未通过，不得据此升级正式质量；production、远程发布和 production 真实数据迁移也仍未运行。

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `IMPLEMENTATION_PLAN.md` | 85226 | `35BD3F6C95EF664C30A0498B994FD325EF3D62AC8941D5D94A6D1EBFA04C4FA4` |
| `PRODUCT_REQUIREMENTS.md` | 45543 | `4C05ABC1517B32A12E09830C071EE1161FD5509A5D5AD330072CC51DC30B96D3` |
| `README.md` | 8778 | `3206AF69F170311997933C94DAC7AC286124389C4BEF33026ED8F754F6100928` |
| `TECHNICAL_SPEC.md` | 156232 | `510679DC4081B609206B9463D3E3CA28F5CDB823E8AAA8C4C973BFF55A77D013` |

复核命令：

```powershell
Get-ChildItem .\Request -File -Filter *.md | Get-FileHash -Algorithm SHA256
.\scripts\verify-baseline.ps1
```

旧版九份文档的原始字节身份保留在 `docs/baseline-manifest.md`，文件保存在 `Request/archive/legacy-v1/`。历史清单已被批准制品绑定，保持原字节不变；它不是当前开发清单。
