# 正式报告制品兼容性门禁

状态：2026-08-17 本地兼容性切片已通过；LibreOffice、production 与正式 AC 仍为 `NOT_RUN`

## 1. 目的和边界

`scripts/verify-report-artifact-compatibility.ps1` 使用固定合成正式报告负载，分别在 Backend 宿主虚拟环境和指定的本地 Backend 镜像中生成 PDF/XLSX，再比较可观察语义并调用宿主阅读器实际打开制品。门禁不读取 `.env`、不调用 Provider、不访问网络，也不使用真实业务数据。

该门禁只证明当前固定报告在两种 Python 运行边界中的内容兼容性；它不签署生产镜像、Office 全版本矩阵、业务数据代表性、UAT、AC-014 或任何正式 AC。

## 2. 可复现命令

先构建或取得待验证的本地 Backend 镜像，再运行：

```powershell
.\scripts\verify-report-artifact-compatibility.ps1 `
  -BackendImage finaudit-backend-local:compat-023 `
  -RequireExcel
```

脚本只接受本地唯一镜像 ID，固定 `--pull never`，并以 `network none`、只读根文件系统、`cap-drop ALL` 和 `no-new-privileges` 运行容器。未指定 `-KeepArtifactsAt` 时，临时制品会在退出路径清理。

## 3. 2026-08-17 实际结果

- 当前本地镜像 ID：`sha256:44b77246577e3d2d8ba1877fdfe03dc05afeba5f71e8e68bfedfeb1b399d1e11`。
- 宿主与容器均为 Python `3.10.20`。
- PDF 为 3 页，宿主与容器字节相同；固定正文指纹相同，未发现活动 Catalog 项，Poppler 两份均成功渲染。三页人工视觉检查未见文字裁切、重叠或缺页。
- XLSX 均包含且只包含 `Summary`、`Rules`、`Risks`；规范化单元格内容指纹相同。压缩包原始字节不同，因此不声明跨运行环境字节一致。
- Microsoft Excel 以禁用宏、禁用事件、只读方式实际打开宿主和容器两份 XLSX，并核对工作表和关键单元格：`PASS`。
- LibreOffice 未安装：`NOT_RUN`。
- 最终输出：`REPORT_ARTIFACT_CROSS_IMAGE_SEMANTICS=PASS`、`PDF_POPPLER_RENDER=PASS`、`REPORT_ARTIFACT_COMPATIBILITY=PASS`。

## 4. 自动化回归

`backend/tests/unit/test_report_artifact_compatibility.py` 固定生成器、PDF 语义检查、XLSX 工作表/单元格语义指纹和同环境确定性。该单元测试不替代上面的容器、Poppler 或 Excel 实际打开门禁。

## 5. 剩余完成条件

- 在受控 LibreOffice 版本中实际打开两份 XLSX，并记录版本、退出码和关键工作表检查。
- 由发布候选镜像而不是临时本地标签重跑，并关联可复现 Git revision、SBOM 和镜像签名。
- 使用批准的代表性报告数据执行正式 AC-014/UAT；人工确认分页、字体、长文本、公式前缀安全和导出内容。
