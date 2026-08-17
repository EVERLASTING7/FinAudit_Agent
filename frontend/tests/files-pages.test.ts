import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import { createAppRouter } from '@/router'
import { ApiError } from '@/services/api'
import type { PermissionCode } from '@/services/auth'
import { fileApi, type FileListItem, type FileRecordData } from '@/services/files'
import { useAuthStore } from '@/stores/auth'
import FileDetailView from '@/views/FileDetailView.vue'
import FileListView from '@/views/FileListView.vue'

const fileId = '41000000-0000-4000-8000-000000000001'
const jobId = '41000000-0000-4000-8000-000000000002'
const traceId = '41000000-0000-4000-8000-000000000003'
const uploadResult: FileRecordData = {
  fileId,
  originalName: 'invoice.pdf',
  status: 'uploaded',
  securityScanStatus: 'pending',
  reused: false,
  intendedBusinessType: 'invoice',
  targetKnowledgeBaseId: null,
  autoProcessRequested: true,
  jobId,
  jobStatus: 'queued',
  jobScope: 'full',
  nextStage: 'scan',
  rowVersion: '1',
}
const fileItem: FileListItem = {
  ...uploadResult,
  status: 'stored',
  securityScanStatus: 'clean',
  jobStatus: 'succeeded',
  rowVersion: '2',
  sizeBytes: '128',
  createdAt: '2026-08-14T08:00:00+00:00',
}

let wrapper: VueWrapper | undefined

function authenticate(canUpload = true, canManage = false): ReturnType<typeof createPinia> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const permissions: PermissionCode[] = ['files.read']
  if (canUpload) permissions.push('files.upload')
  if (canManage) permissions.push('files.manage')
  permissions.sort()
  useAuthStore(pinia).setAuthenticatedSession(
    {
      id: '90000000-0000-4000-8000-000000000001',
      displayName: '文件测试用户',
      roles: ['finance_reviewer'],
      permissions,
    },
    'test-token',
  )
  return pinia
}

beforeEach(() => {
  vi.spyOn(fileApi, 'list').mockResolvedValue({ items: [], pageSize: 20, nextCursor: null })
  vi.spyOn(fileApi, 'previewOriginal').mockResolvedValue({
    body: new Blob(['preview'], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }),
    mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    status: 'stored',
  })
  vi.spyOn(fileApi, 'textPreview').mockResolvedValue({
    fileId,
    markdownVersionId: '41000000-0000-4000-8000-000000000004',
    contentSha256: 'a'.repeat(64),
    markdownText: '# 发票预览',
    charCount: 6,
    truncated: false,
  })
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:file-preview')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('文件页面真实接口接线', () => {
  it('未知上传失败后使用同一幂等键重试，并在成功后刷新列表', async () => {
    const pinia = authenticate()
    const upload = vi
      .spyOn(fileApi, 'upload')
      .mockRejectedValueOnce(
        new ApiError({ code: 'NETWORK_ERROR', message: 'raw', status: 0, traceId: '' }),
      )
      .mockResolvedValueOnce({ record: uploadResult, traceId })
    wrapper = mount(FileListView, { global: { plugins: [pinia], stubs: { RouterLink: true } } })
    await flushPromises()

    const input = wrapper.get('#upload-file').element as HTMLInputElement
    const selected = new File(['%PDF-1.7'], 'invoice.pdf', { type: 'application/pdf' })
    Object.defineProperty(input, 'files', { configurable: true, value: [selected] })
    await wrapper.get('#upload-file').trigger('change')
    await wrapper.get('#file-business-type').setValue('invoice')

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('文件上传失败')
    expect(upload).toHaveBeenCalledTimes(1)

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(upload).toHaveBeenCalledTimes(2)
    expect(upload.mock.calls[1]?.[1]).toBe(upload.mock.calls[0]?.[1])
    expect(wrapper.text()).toContain('文件已受理')
    expect(wrapper.text()).toContain(`Trace ID：${traceId}`)
    expect(fileApi.list).toHaveBeenCalledTimes(2)
  })

  it('无上传权限时保持读取能力并禁用上传输入', async () => {
    const pinia = authenticate(false)
    wrapper = mount(FileListView, { global: { plugins: [pinia], stubs: { RouterLink: true } } })
    await flushPromises()

    expect(wrapper.get('#upload-file').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('当前账号只有读取权限')
    expect(fileApi.list).toHaveBeenCalledWith(20, undefined, expect.any(AbortSignal))
  })

  it('多个文件通过批量接口提交并逐项显示受理与拒绝结果', async () => {
    const pinia = authenticate()
    const uploadBatch = vi.spyOn(fileApi, 'uploadBatch').mockResolvedValue({
      data: {
        items: [
          {
            index: 0,
            originalName: 'invoice.pdf',
            outcome: 'accepted',
            httpStatus: 202,
            replayed: false,
            data: uploadResult,
            error: null,
          },
          {
            index: 1,
            originalName: 'bad.pdf',
            outcome: 'rejected',
            httpStatus: 400,
            replayed: false,
            data: null,
            error: { code: 'FILE_SIGNATURE_MISMATCH', message: '文件签名不匹配' },
          },
        ],
        acceptedCount: 1,
        rejectedCount: 1,
      },
      traceId,
    })
    wrapper = mount(FileListView, { global: { plugins: [pinia], stubs: { RouterLink: true } } })
    await flushPromises()

    const input = wrapper.get('#upload-file').element as HTMLInputElement
    const files = [
      new File(['%PDF-1.7'], 'invoice.pdf', { type: 'application/pdf' }),
      new File(['invalid'], 'bad.pdf', { type: 'application/pdf' }),
    ]
    Object.defineProperty(input, 'files', { configurable: true, value: files })
    await wrapper.get('#upload-file').trigger('change')
    await wrapper.get('#file-business-type').setValue('invoice')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(uploadBatch).toHaveBeenCalledWith(
      expect.objectContaining({ files, intendedBusinessType: 'invoice' }),
      expect.stringMatching(/^file-upload\./),
      expect.any(AbortSignal),
    )
    expect(wrapper.text()).toContain('受理 1 个，拒绝 1 个')
    expect(wrapper.text()).toContain('FILE_SIGNATURE_MISMATCH')
  })

  it('详情按 canonical 路由 ID 读取持久化字段且不再展示演示数据', async () => {
    const pinia = authenticate()
    const get = vi.spyOn(fileApi, 'get').mockResolvedValue(fileItem)
    const router = createAppRouter(createMemoryHistory())
    await router.push(`/files/${fileId}`)
    await router.isReady()

    wrapper = mount(FileDetailView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(get).toHaveBeenCalledWith(fileId, expect.any(AbortSignal))
    expect(wrapper.get('h1').text()).toBe('invoice.pdf')
    expect(wrapper.text()).toContain(jobId)
    expect(wrapper.text()).toContain('原文与解析预览')
    expect(wrapper.text()).toContain('# 发票预览')
    expect(wrapper.text()).not.toContain('合成')
  })

  it('无效路由 ID 不发请求且显示可恢复的安全错误', async () => {
    const pinia = authenticate()
    const get = vi.spyOn(fileApi, 'get')
    const router = createAppRouter(createMemoryHistory())
    await router.push('/files/not-a-uuid')
    await router.isReady()

    wrapper = mount(FileDetailView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(get).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('文件 ID 格式无效')
  })

  it('失败文件以原 Job 重试并显示权威排队状态', async () => {
    const pinia = authenticate(true, true)
    const failedItem: FileListItem = {
      ...fileItem,
      status: 'validating',
      securityScanStatus: 'scan_failed',
      jobStatus: 'failed',
      rowVersion: '3',
    }
    vi.spyOn(fileApi, 'get').mockResolvedValue(failedItem)
    const retry = vi.spyOn(fileApi, 'retry').mockResolvedValue({
      ...failedItem,
      securityScanStatus: 'pending',
      jobStatus: 'queued',
      rowVersion: '4',
    })
    const router = createAppRouter(createMemoryHistory())
    await router.push(`/files/${fileId}`)
    await router.isReady()
    wrapper = mount(FileDetailView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.get('#file-retry-reason').setValue('依赖已恢复，人工重试')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(retry).toHaveBeenCalledWith(
      fileId,
      '3',
      jobId,
      '依赖已恢复，人工重试',
      expect.stringMatching(/^file-retry\./),
      expect.any(AbortSignal),
    )
    expect(wrapper.text()).toContain('没有创建第二个文件或 Job')
  })

  it('归档要求显式确认并保留更新后的归档状态', async () => {
    const pinia = authenticate(true, true)
    vi.spyOn(fileApi, 'get').mockResolvedValue(fileItem)
    const archive = vi.spyOn(fileApi, 'archive').mockResolvedValue({
      ...fileItem,
      status: 'archived',
      rowVersion: '3',
    })
    const router = createAppRouter(createMemoryHistory())
    await router.push(`/files/${fileId}`)
    await router.isReady()
    wrapper = mount(FileDetailView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.get('#file-archive-reason').setValue('业务材料已完成归档')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(archive).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请再次确认')

    await wrapper.get('button.button-danger').trigger('click')
    await flushPromises()

    expect(archive).toHaveBeenCalledWith(
      fileId,
      '2',
      '业务材料已完成归档',
      expect.stringMatching(/^file-archive\./),
      expect.any(AbortSignal),
    )
    expect(wrapper.text()).toContain('历史引用和原文件保持可查')
  })
})
