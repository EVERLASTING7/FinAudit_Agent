import { describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/services/api'
import {
  ReportApi,
  decodeAuditReport,
  decodeAuditReportList,
} from '@/services/reports'

const reportId = '51000000-0000-4000-8000-000000000001'
const taskId = '51000000-0000-4000-8000-000000000002'
const executionId = '51000000-0000-4000-8000-000000000003'
const jobId = '51000000-0000-4000-8000-000000000004'
const userId = '51000000-0000-4000-8000-000000000005'
const traceId = '51000000-0000-4000-8000-000000000006'
const pdfBytes = new TextEncoder().encode('%PDF-1.7\nformal-report')
const xlsxBytes = new TextEncoder().encode('PK\u0003\u0004formal-report-workbook')
const xlsxMime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

async function digest(payload: Uint8Array): Promise<string> {
  const result = await crypto.subtle.digest('SHA-256', toArrayBuffer(payload))
  return Array.from(new Uint8Array(result), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function toArrayBuffer(payload: Uint8Array): ArrayBuffer {
  const buffer = new ArrayBuffer(payload.byteLength)
  new Uint8Array(buffer).set(payload)
  return buffer
}

async function readyPayload(): Promise<Record<string, unknown>> {
  return {
    id: reportId,
    audit_task_id: taskId,
    execution_id: executionId,
    report_version: 2,
    status: 'ready',
    payload_sha256: 'a'.repeat(64),
    generator_version: 'formal-report-generator-v2',
    pdf_sha256: await digest(pdfBytes),
    pdf_size_bytes: pdfBytes.byteLength,
    pdf_mime_type: 'application/pdf',
    xlsx_sha256: await digest(xlsxBytes),
    xlsx_size_bytes: xlsxBytes.byteLength,
    xlsx_mime_type: xlsxMime,
    job_id: jobId,
    failure_code: null,
    row_version: '3',
    created_by: userId,
    created_at: '2026-08-14T08:00:00+00:00',
    generated_at: '2026-08-14T08:01:00+00:00',
    outdated_at: null,
    archived_at: null,
    is_outdated: false,
    ai_draft_status: 'succeeded',
    ai_draft_sha256: 'd'.repeat(64),
    ai_draft: {
      executive_summary: '执行摘要',
      scope_summary: '范围摘要',
      risk_summary: '风险摘要',
      recommendations: ['由人工复核风险事实。'],
      warnings: ['AI 草稿不替代人工结论。'],
    },
  }
}

function envelope(data: unknown, status = 200): Response {
  return new Response(
    JSON.stringify({
      code: status < 400 ? 'OK' : 'AUTH_FORBIDDEN',
      message: status < 400 ? 'success' : '无权执行此操作',
      data,
      trace_id: traceId,
      timestamp: '2026-08-14T08:02:00Z',
    }),
    { status, headers: { 'Content-Type': 'application/json' } },
  )
}

function artifact(
  payload: Uint8Array,
  mimeType: string,
  disposition: string,
  sha256: string,
): Response {
  return new Response(toArrayBuffer(payload), {
    status: 200,
    headers: {
      'Content-Type': mimeType,
      'Content-Disposition': disposition,
      ETag: `"${sha256}"`,
      'X-Report-Outdated': 'false',
      'X-Report-Status': 'ready',
      'X-Trace-ID': traceId,
    },
  })
}

describe('正式报告 API 合同', () => {
  it('严格解码元数据和执行报告列表', async () => {
    const payload = await readyPayload()
    expect(decodeAuditReport(payload)).toMatchObject({
      id: reportId,
      reportVersion: 2,
      status: 'ready',
      isOutdated: false,
      aiDraftStatus: 'succeeded',
      aiDraft: { executiveSummary: '执行摘要' },
    })
    expect(
      decodeAuditReportList({ execution_id: executionId, items: [payload] }),
    ).toMatchObject({ executionId, items: [{ id: reportId }] })
  })

  it('拒绝额外字段、半成品 locator 投影和状态矛盾', async () => {
    const payload = await readyPayload()
    const invalid = [
      { ...payload, unexpected: true },
      { ...payload, pdf_size_bytes: null },
      { ...payload, status: 'outdated', outdated_at: null, is_outdated: false },
      { ...payload, failure_code: 'UNEXPECTED' },
      { ...payload, ai_draft_status: 'degraded' },
      { ...payload, ai_draft_sha256: null },
    ]
    for (const value of invalid) {
      expect(() => decodeAuditReport(value)).toThrow(TypeError)
    }
  })

  it('使用授权 GET 获取 PDF/XLSX，并在浏览器端复核 MIME、大小、ETag 和 SHA-256', async () => {
    const payload = await readyPayload()
    const report = decodeAuditReport(payload)
    const pdfSha256 = String(payload.pdf_sha256)
    const xlsxSha256 = String(payload.xlsx_sha256)
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(envelope(payload))
      .mockResolvedValueOnce(
        artifact(
          pdfBytes,
          'application/pdf',
          `inline; filename="audit-report-${reportId}-v2.pdf"`,
          pdfSha256,
        ),
      )
      .mockResolvedValueOnce(
        artifact(
          xlsxBytes,
          xlsxMime,
          `attachment; filename="audit-report-${reportId}-v2-risks.xlsx"`,
          xlsxSha256,
        ),
      )
    const api = new ReportApi(
      new ApiClient({ fetcher, getAccessToken: () => 'report-session-token' }),
    )

    expect(await api.get(reportId)).toEqual(report)
    expect((await api.previewPdf(report)).body.size).toBe(pdfBytes.byteLength)
    expect((await api.downloadXlsx(report)).filename).toBe(
      `audit-report-${reportId}-v2-risks.xlsx`,
    )

    expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
      `/api/v1/audit-reports/${reportId}`,
      `/api/v1/audit-reports/${reportId}/preview`,
      `/api/v1/audit-reports/${reportId}/download`,
    ])
    expect(new Headers(fetcher.mock.calls[1]?.[1]?.headers).get('Accept')).toBe(
      'application/pdf',
    )
    expect(new Headers(fetcher.mock.calls[2]?.[1]?.headers).get('Accept')).toBe(xlsxMime)
    expect(new Headers(fetcher.mock.calls[1]?.[1]?.headers).get('Authorization')).toBe(
      'Bearer report-session-token',
    )
  })

  it('拒绝篡改后的二进制响应且保留 JSON 权限错误', async () => {
    const payload = await readyPayload()
    const report = decodeAuditReport(payload)
    const tampered = new TextEncoder().encode('%PDF-1.7\ntampered')
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        artifact(
          tampered,
          'application/pdf',
          `inline; filename="audit-report-${reportId}-v2.pdf"`,
          String(payload.pdf_sha256),
        ),
      )
      .mockResolvedValueOnce(envelope(null, 403))
    const api = new ReportApi(new ApiClient({ fetcher }))

    await expect(api.previewPdf(report)).rejects.toThrow(TypeError)
    await expect(api.downloadXlsx(report)).rejects.toMatchObject({
      code: 'AUTH_FORBIDDEN',
      status: 403,
      traceId,
    })
  })
})
