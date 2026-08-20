import { describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/services/api'
import {
  DocumentCorrectionApi,
  decodeDocumentCorrectionBlockPage,
  decodeDocumentCorrectionAccepted,
  decodeDocumentParseActivation,
} from '@/services/documentCorrections'

const blockId = '61000000-0000-4000-8000-000000000001'
const sourceParseId = '61000000-0000-4000-8000-000000000002'
const resultParseId = '61000000-0000-4000-8000-000000000003'
const correctionId = '61000000-0000-4000-8000-000000000004'
const jobId = '61000000-0000-4000-8000-000000000005'
const traceId = '61000000-0000-4000-8000-000000000006'
const fileId = '61000000-0000-4000-8000-000000000007'

function success(data: unknown, status = 200): Response {
  return new Response(
    JSON.stringify({
      code: 'OK',
      message: 'success',
      data,
      trace_id: traceId,
      timestamp: '2026-08-18T08:00:00Z',
    }),
    { status, headers: { 'Content-Type': 'application/json' } },
  )
}

describe('文档纠错 API 合同', () => {
  it('严格解码候选与独立激活响应', () => {
    expect(
      decodeDocumentCorrectionAccepted({
        correction_id: correctionId,
        result_parse_version_id: resultParseId,
        job_id: jobId,
        status: 'queued',
      }),
    ).toEqual({ correctionId, resultParseVersionId: resultParseId, jobId, status: 'queued' })
    expect(
      decodeDocumentParseActivation({
        id: resultParseId,
        status: 'active',
        superseded_version_id: sourceParseId,
        activated_at: '2026-08-18T08:00:00Z',
      }),
    ).toEqual({
      id: resultParseId,
      status: 'active',
      supersededVersionId: sourceParseId,
      activatedAt: '2026-08-18T08:00:00Z',
    })
  })

  it('严格解码绑定活动 Parse 的文本块分页并发送只读请求', async () => {
    const rawPage = {
      file_id: fileId,
      business_type: 'policy',
      parse_version_id: sourceParseId,
      items: [
        {
          block_id: blockId,
          page_no: 1,
          block_index: 0,
          block_type: 'paragraph',
          text_content: '合成制度条款',
          reading_order: 0,
          bbox: null,
        },
      ],
      page_size: 1,
      next_cursor: 'next_cursor_1',
    }
    expect(decodeDocumentCorrectionBlockPage(rawPage)).toMatchObject({
      fileId,
      businessType: 'policy',
      parseVersionId: sourceParseId,
      pageSize: 1,
    })
    expect(() =>
      decodeDocumentCorrectionBlockPage({
        ...rawPage,
        items: [
          { ...rawPage.items[0], block_index: 2 },
          { ...rawPage.items[0], block_id: jobId, block_index: 1 },
        ],
        page_size: 2,
        next_cursor: null,
      }),
    ).toThrow(TypeError)

    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(success(rawPage))
    const api = new DocumentCorrectionApi(new ApiClient({ fetcher }))
    await api.listBlocks(fileId, 1, 'current_cursor_1')

    expect(String(fetcher.mock.calls[0]?.[0])).toBe(
      `/api/v1/files/${fileId}/document-correction-blocks?page_size=1&cursor=current_cursor_1`,
    )
    expect(fetcher.mock.calls[0]?.[1]?.method).toBe('GET')
  })

  it.each([
    {
      correction_id: correctionId,
      result_parse_version_id: resultParseId,
      job_id: jobId,
      status: 'queued',
      unexpected: true,
    },
    {
      correction_id: correctionId,
      result_parse_version_id: resultParseId,
      job_id: jobId,
      status: 'running',
    },
  ])('拒绝越界候选响应 %#', (value) => {
    expect(() => decodeDocumentCorrectionAccepted(value)).toThrow(TypeError)
  })

  it('发送精确纠错请求，且激活必须由第二次显式调用触发', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        success(
          {
            correction_id: correctionId,
            result_parse_version_id: resultParseId,
            job_id: jobId,
            status: 'queued',
          },
          202,
        ),
      )
      .mockResolvedValueOnce(
        success({
          id: resultParseId,
          status: 'active',
          superseded_version_id: sourceParseId,
          activated_at: '2026-08-18T08:00:00Z',
        }),
      )
    const api = new DocumentCorrectionApi(new ApiClient({ fetcher }))

    await api.correctBlock(
      blockId,
      {
        fieldName: 'text_content',
        afterValue: '修正后的合成文本',
        reason: '人工复核',
        sourceParseVersionId: sourceParseId,
      },
      'document-correction.unit-001',
    )
    expect(fetcher).toHaveBeenCalledTimes(1)
    await api.activateParse(resultParseId, '人工复核通过', 'document-activation.unit-001')

    expect(fetcher.mock.calls[0]?.[0]).toBe(`/api/v1/document-blocks/${blockId}/correct`)
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      field_name: 'text_content',
      after_value: '修正后的合成文本',
      reason: '人工复核',
      source_parse_version_id: sourceParseId,
    })
    expect(new Headers(fetcher.mock.calls[0]?.[1]?.headers).get('Idempotency-Key')).toBe(
      'document-correction.unit-001',
    )
    expect(fetcher.mock.calls[1]?.[0]).toBe(
      `/api/v1/document-parse-versions/${resultParseId}/activate`,
    )
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      reason: '人工复核通过',
    })
  })

  it('在发送前拒绝非规范 ID、空文本和带首尾空白的原因', async () => {
    const api = new DocumentCorrectionApi(new ApiClient({ fetcher: vi.fn<typeof fetch>() }))
    await expect(
      api.correctBlock(
        'bad',
        {
          fieldName: 'text_content',
          afterValue: '',
          reason: ' 原因',
          sourceParseVersionId: sourceParseId,
        },
        'document-correction.unit-002',
      ),
    ).rejects.toThrow(TypeError)
  })
})
