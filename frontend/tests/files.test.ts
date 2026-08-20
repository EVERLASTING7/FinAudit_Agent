import { describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/services/api'
import {
  FileApi,
  decodeFileBatch,
  decodeFileList,
  decodeFileListItem,
  decodeFileTextPreview,
  decodeFileUpload,
} from '@/services/files'

const fileId = '41000000-0000-4000-8000-000000000001'
const jobId = '41000000-0000-4000-8000-000000000002'
const traceId = '41000000-0000-4000-8000-000000000003'
const base = {
  file_id: fileId,
  original_name: 'invoice.pdf',
  status: 'uploaded',
  security_scan_status: 'pending',
  reused: false,
  intended_business_type: 'invoice',
  target_knowledge_base_id: null,
  auto_process_requested: true,
  job_id: jobId,
  job_status: 'queued',
  job_scope: 'full',
  next_stage: 'scan',
  row_version: '1',
} as const
const item = {
  ...base,
  job: {
    id: jobId,
    status: 'succeeded',
    stage: 'markdown',
    attempt_no: 1,
    max_attempts: 3,
    row_version: '4',
    retryable: false,
  },
  size_bytes: '128',
  created_at: '2026-08-14T08:00:00+00:00',
}

function success(data: unknown, status = 200): Response {
  return new Response(
    JSON.stringify({
      code: 'OK',
      message: 'success',
      data,
      trace_id: traceId,
      timestamp: '2026-08-14T08:00:00Z',
    }),
    { status, headers: { 'Content-Type': 'application/json' } },
  )
}

describe('文件 API 合同', () => {
  it('严格解码上传、列表项和分页', () => {
    expect(decodeFileUpload(base)).toMatchObject({ fileId, jobId, jobScope: 'full' })
    expect(decodeFileListItem(item)).toMatchObject({ fileId, sizeBytes: '128' })
    expect(
      decodeFileList({ items: [item], page_size: 20, next_cursor: null }),
    ).toMatchObject({ pageSize: 20, nextCursor: null })
  })

  it.each([
    [{ ...base, unexpected: true }],
    [{ ...base, intended_business_type: 'policy' }],
    [{ ...base, auto_process_requested: false }],
    [{ ...base, row_version: 1 }],
  ])('拒绝越界上传响应 %#', (value) => {
    expect(() => decodeFileUpload(value)).toThrow(TypeError)
  })

  it('发送浏览器 multipart、幂等键与精确意图字段', async () => {
    let request: { input: RequestInfo | URL; init?: RequestInit } | undefined
    const client = new ApiClient({
      fetcher: async (input, init) => {
        request = { input, init }
        return success(base)
      },
    })
    const api = new FileApi(client)
    const payload = new File(['%PDF-1.7'], 'invoice.pdf', { type: 'application/pdf' })

    const result = await api.upload(
      {
        file: payload,
        intendedBusinessType: 'invoice',
        autoProcessRequested: true,
      },
      'file-upload.unit-001',
    )

    expect(request?.input).toBe('/api/v1/files')
    const headers = new Headers(request?.init?.headers)
    expect(headers.get('Idempotency-Key')).toBe('file-upload.unit-001')
    expect(headers.has('Content-Type')).toBe(false)
    const body = request?.init?.body as FormData
    expect(body.get('file')).toBe(payload)
    expect(body.get('intended_business_type')).toBe('invoice')
    expect(body.get('auto_process_requested')).toBe('true')
    expect(result).toEqual({ record: expect.objectContaining({ fileId, jobId }), traceId })
  })

  it('严格解码批量逐项结果与有界文本预览', () => {
    expect(
      decodeFileBatch({
        items: [
          {
            index: 0,
            original_name: 'invoice.pdf',
            outcome: 'accepted',
            http_status: 202,
            replayed: false,
            data: base,
            error: null,
          },
          {
            index: 1,
            original_name: 'bad.pdf',
            outcome: 'rejected',
            http_status: 400,
            replayed: false,
            data: null,
            error: { code: 'FILE_SIGNATURE_MISMATCH', message: '文件签名不匹配' },
          },
        ],
        accepted_count: 1,
        rejected_count: 1,
      }),
    ).toMatchObject({ acceptedCount: 1, rejectedCount: 1 })
    expect(
      decodeFileTextPreview({
        file_id: fileId,
        markdown_version_id: '41000000-0000-4000-8000-000000000004',
        content_sha256: 'a'.repeat(64),
        markdown_text: '# 发票',
        char_count: 4,
        truncated: false,
      }),
    ).toMatchObject({ fileId, markdownText: '# 发票' })
  })

  it('批量上传保留重复 files part，并以 JSON 执行归档和原 Job 重试', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        success(
          {
            items: [
              {
                index: 0,
                original_name: 'invoice.pdf',
                outcome: 'accepted',
                http_status: 202,
                replayed: false,
                data: base,
                error: null,
              },
            ],
            accepted_count: 1,
            rejected_count: 0,
          },
          207,
        ),
      )
      .mockResolvedValueOnce(success(item))
      .mockResolvedValueOnce(success(item))
    const api = new FileApi(new ApiClient({ fetcher }))
    const files = [
      new File(['%PDF-1.7'], 'invoice.pdf', { type: 'application/pdf' }),
      new File(['%PDF-1.7'], 'invoice-2.pdf', { type: 'application/pdf' }),
    ]

    await api.uploadBatch(
      {
        files,
        intendedBusinessType: 'invoice',
        autoProcessRequested: true,
      },
      'file-batch.unit-001',
    )
    await api.archive(fileId, '1', '测试文件归档', 'file-archive.unit-001')
    await api.retry(fileId, '1', jobId, '4', '测试任务重试', 'file-retry.unit-001')

    const batchBody = fetcher.mock.calls[0]?.[1]?.body as FormData
    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/v1/files/batch')
    expect(batchBody.getAll('files')).toEqual(files)
    expect(new Headers(fetcher.mock.calls[0]?.[1]?.headers).has('Content-Type')).toBe(false)
    expect(fetcher.mock.calls[1]?.[0]).toBe(`/api/v1/files/${fileId}/archive`)
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      row_version: '1',
      reason: '测试文件归档',
    })
    expect(fetcher.mock.calls[2]?.[0]).toBe(`/api/v1/files/${fileId}/retry`)
    expect(JSON.parse(String(fetcher.mock.calls[2]?.[1]?.body))).toEqual({
      file_row_version: '1',
      reason: '测试任务重试',
      job_id: jobId,
      job_row_version: '4',
    })
  })

  it('原文件预览校验文件身份、字节数和响应摘要', async () => {
    const bytes = new Uint8Array(128)
    bytes.set(new TextEncoder().encode('%PDF-1.7'))
    const hash = Array.from(
      new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
      (byte) => byte.toString(16).padStart(2, '0'),
    ).join('')
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(bytes, {
        status: 200,
        headers: {
          'Content-Type': 'application/pdf',
          'Content-Disposition': `inline; filename="file-${fileId}.pdf"; filename*=UTF-8''invoice.pdf`,
          ETag: `"${hash}"`,
          'X-File-Id': fileId,
          'X-File-Status': 'stored',
        },
      }),
    )
    const api = new FileApi(new ApiClient({ fetcher }))

    const artifact = await api.previewOriginal(decodeFileListItem(item))

    expect(artifact.body.size).toBe(128)
    expect(artifact.status).toBe('stored')
  })

  it('列表与详情只使用同源 canonical 路径', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(success({ items: [item], page_size: 20, next_cursor: null }))
      .mockResolvedValueOnce(success(item))
    const api = new FileApi(new ApiClient({ fetcher }))

    await api.list(20)
    await api.get(fileId)

    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/v1/files?page_size=20')
    expect(fetcher.mock.calls[1]?.[0]).toBe(`/api/v1/files/${fileId}`)
  })
})
