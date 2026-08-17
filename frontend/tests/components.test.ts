import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import AuditTaskExecutionStatuses from '@/components/AuditTaskExecutionStatuses.vue'
import ContractStatuses from '@/components/ContractStatuses.vue'
import DecimalAmount from '@/components/DecimalAmount.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import FileLifecycleStatuses from '@/components/FileLifecycleStatuses.vue'
import InvoiceStatuses from '@/components/InvoiceStatuses.vue'
import JobStageIndicator from '@/components/JobStageIndicator.vue'
import PageTabs from '@/components/PageTabs.vue'
import PolicyPipelineStatuses from '@/components/PolicyPipelineStatuses.vue'
import QaAnswerStatuses from '@/components/QaAnswerStatuses.vue'
import ReportOutdatedNotice from '@/components/ReportOutdatedNotice.vue'
import RiskReviewStatuses from '@/components/RiskReviewStatuses.vue'
import SkeletonBlock from '@/components/SkeletonBlock.vue'
import StatusTag from '@/components/StatusTag.vue'
import TraceIdCopy from '@/components/TraceIdCopy.vue'
import { getEnvironmentPresentation } from '@/config/environment'

const formalStatusLabels = [
  ['queued', '已排队'],
  ['running', '进行中'],
  ['succeeded', '已成功'],
  ['failed', '失败'],
  ['cancel_requested', '正在请求取消'],
  ['cancelled', '已取消'],
  ['uploaded', '已上传'],
  ['validating', '校验中'],
  ['stored', '已存储'],
  ['rejected', '已拒绝'],
  ['archived', '已归档'],
  ['manual_review_required', '需要人工纠错'],
  ['active', '有效'],
  ['superseded', '已被替代'],
  ['converting', '转换中'],
  ['review_required', '待复核'],
  ['ready', '质量通过，待激活'],
  ['building', '构建中'],
  ['quality_review', '质量复核中'],
  ['blocked', '已阻断'],
  ['consistency_check', '一致性检查中'],
  ['evaluation_pending', '待评测'],
  ['approved', '已批准'],
  ['draft', '草稿'],
  ['pending_business_review', '待业务审批'],
  ['published', '已发布'],
  ['revoked', '已撤销'],
  ['pending_finance_review', '待财务复核'],
  ['pending_audit_review', '待审计复核'],
  ['returned_for_correction', '已退回修正'],
  ['completed', '已完成'],
  ['outdated', '已过期'],
  ['none', '无风险'],
  ['notice', '提示风险'],
  ['low', '低风险'],
  ['medium', '中风险'],
  ['high', '高风险'],
  ['pending', '待处理'],
  ['pending_confirmation', '待确认'],
  ['unconfirmed', '未确认'],
  ['confirmed', '已确认'],
  ['dismissed', '已驳回'],
  ['adjusted', '已调整'],
  ['not_checked', '尚未检测'],
  ['unique', '未发现重复'],
  ['suspected', '疑似重复'],
  ['confirmed_duplicate', '已确认重复'],
  ['exception_approved', '已批准例外'],
  ['clean', '安全检查通过'],
  ['infected', '检出恶意内容'],
  ['scan_failed', '安全检查失败'],
  ['unsupported', '不支持扫描'],
  ['not_configured', '未配置扫描器'],
  ['candidate', '候选'],
  ['suggested', '已建议'],
  ['confirmed_primary', '已确认主合同'],
  ['open', '未完成'],
  ['passed', '通过'],
  ['not_applicable', '不适用'],
  ['error', '错误'],
  ['generating', '生成中'],
  ['disabled', '已停用'],
  ['locked', '已锁定'],
  ['expired', '已过期'],
] as const

const formalJobStageLabels = [
  ['security_scan', '正在进行文件安全检查'],
  ['parsing', '正在解析文档'],
  ['ocr', '正在执行 OCR 识别'],
  ['field_extraction', '正在提取业务字段'],
  ['markdown_converting', '正在转换 Markdown'],
  ['markdown_validating', '正在校验 Markdown'],
  ['chunk_building', '正在生成文档分块'],
  ['embedding', '正在生成向量'],
  ['index_consistency_check', '正在校验索引一致性'],
  ['retrieval_evaluation', '正在执行检索评测'],
  ['snapshot_building', '正在冻结审核快照'],
  ['rule_execution', '正在执行审核规则'],
  ['policy_retrieval', '正在检索制度证据'],
  ['risk_explanation', '正在生成风险解释'],
  ['report_generating', '正在生成审核报告'],
] as const

const formalJobStatusLabels = [
  ['queued', '已排队'],
  ['running', '进行中'],
  ['succeeded', '已成功'],
  ['failed', '失败'],
  ['cancel_requested', '正在请求取消'],
  ['cancelled', '已取消'],
] as const

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('环境标识', () => {
  it('不把未配置或未知环境误报为生产环境', () => {
    expect(getEnvironmentPresentation(undefined)).toEqual({
      label: '环境未配置',
      status: 'pending',
    })
    expect(getEnvironmentPresentation('staging-typo')).toEqual({
      label: '环境未配置',
      status: 'pending',
    })
    expect(getEnvironmentPresentation('production')).toEqual({
      label: '生产环境',
      status: 'active',
    })
    expect(getEnvironmentPresentation('prod')).toEqual({
      label: '生产环境',
      status: 'active',
    })
    expect(getEnvironmentPresentation('staging')).toEqual({
      label: '预发布环境',
      status: 'active',
    })
  })
})

describe('页面标签键盘操作', () => {
  it('只让活动标签进入 Tab 顺序，并支持方向键与 Home/End 循环切换焦点', async () => {
    const wrapper = mount(PageTabs, {
      attachTo: document.body,
      props: {
        items: [
          { id: 'overview', label: '概览' },
          { id: 'policies', label: '制度' },
          { id: 'index', label: '索引' },
        ],
        modelValue: 'overview',
        label: '知识库详情标签',
      },
    })

    try {
      const tabs = wrapper.findAll<HTMLButtonElement>('[role="tab"]')
      const [firstTab, secondTab, thirdTab] = tabs
      if (!firstTab || !secondTab || !thirdTab) {
        throw new Error('页面标签测试夹具必须渲染三个标签。')
      }
      expect(wrapper.attributes('aria-orientation')).toBe('horizontal')
      expect(tabs.map((tab) => tab.attributes('tabindex'))).toEqual(['0', '-1', '-1'])

      await firstTab.trigger('keydown', { key: 'ArrowLeft' })
      expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['index'])
      expect(document.activeElement).toBe(thirdTab.element)

      await thirdTab.trigger('keydown', { key: 'Home' })
      expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['overview'])
      expect(document.activeElement).toBe(firstTab.element)

      await firstTab.trigger('keydown', { key: 'End' })
      expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['index'])
      expect(document.activeElement).toBe(thirdTab.element)

      await wrapper.setProps({ modelValue: 'index' })
      expect(tabs.map((tab) => tab.attributes('tabindex'))).toEqual(['-1', '-1', '0'])
    } finally {
      wrapper.unmount()
    }
  })
})

describe('通用状态组件', () => {
  it.each(formalStatusLabels)('将正式状态 %s 渲染为简体中文', (status, label) => {
    const wrapper = mount(StatusTag, { props: { status } })

    expect(wrapper.text()).toContain(label)
    expect(wrapper.attributes('aria-label')).toBe(`状态：${label}`)
  })

  it('未知状态保留原始 code 且不伪造翻译', () => {
    const wrapper = mount(StatusTag, { props: { status: 'future_status' } })

    expect(wrapper.text()).toContain('future_status')
    expect(wrapper.attributes('aria-label')).toBe('状态：future_status')
  })

  it('按文字和标识渲染状态标签快照', () => {
    const wrapper = mount(StatusTag, {
      props: { status: 'manual_review_required' },
    })

    expect(wrapper.html()).toMatchSnapshot()
    expect(wrapper.text()).toContain('需要人工纠错')
    expect(wrapper.attributes('aria-label')).toBe('状态：需要人工纠错')
  })

  it('渲染脱敏错误结构和 Trace ID 快照', () => {
    const wrapper = mount(ErrorState, {
      props: {
        title: '保存失败',
        message: '该对象已被其他用户修改。',
        code: 'RESOURCE_VERSION_CONFLICT',
        suggestion: '请查看最新数据后重新提交。',
        traceId: '90000000-0000-0000-0000-000000000001',
      },
    })

    expect(wrapper.html()).toMatchSnapshot()
    expect(wrapper.text()).toContain('RESOURCE_VERSION_CONFLICT')
    expect(wrapper.text()).toContain('Trace ID')
  })

  it('提供空状态和可访问的骨架屏', () => {
    const empty = mount(EmptyState)
    const skeleton = mount(SkeletonBlock, { props: { rows: 2 } })

    expect(empty.text()).toContain('暂无数据')
    expect(skeleton.findAll('.skeleton-line')).toHaveLength(2)
    expect(skeleton.attributes('role')).toBe('status')
  })
})

describe('文件生命周期状态', () => {
  const completeProps = {
    fileStatus: 'stored',
    securityScanStatus: 'clean',
    parseStatus: 'active',
    markdownStatus: 'ready',
  } as const

  it('将四类状态作为具名语义项独立展示', () => {
    const wrapper = mount(FileLifecycleStatuses, { props: completeProps })
    const items = wrapper.findAll('[data-status-kind]')

    expect(wrapper.attributes('aria-label')).toBe('文件生命周期状态')
    expect(items).toHaveLength(4)
    expect(items.map((item) => item.attributes('data-status-kind'))).toEqual([
      'file',
      'security-scan',
      'parse',
      'markdown',
    ])
    expect(items.map((item) => item.get('dt').text())).toEqual([
      '文件状态',
      '安全扫描状态',
      '解析状态',
      'Markdown 状态',
    ])
    expect(items.map((item) => item.get('dd').text())).toEqual([
      '● 已存储',
      '● 安全检查通过',
      '● 有效',
      '● 质量通过，待激活',
    ])
    expect(wrapper.findAll('.status-tag')).toHaveLength(4)
    expect(wrapper.findAll('.status-dot')).toHaveLength(4)
    expect(wrapper.findAll('.status-dot').every((dot) => dot.attributes('aria-hidden') === 'true')).toBe(
      true,
    )
  })

  it('同时保留解析成功和 Markdown 失败的部分成功事实', () => {
    const wrapper = mount(FileLifecycleStatuses, {
      props: {
        ...completeProps,
        parseStatus: 'succeeded',
        markdownStatus: 'failed',
      },
    })

    expect(wrapper.get('[data-status-kind="parse"] dd').text()).toContain('已成功')
    expect(wrapper.get('[data-status-kind="markdown"] dd').text()).toContain('失败')
    expect(wrapper.text()).not.toContain('处理状态')
  })

  it.each([
    ['pending', '待处理'],
    ['clean', '安全检查通过'],
    ['infected', '检出恶意内容'],
    ['scan_failed', '安全检查失败'],
    ['unsupported', '不支持扫描'],
    ['not_configured', '未配置扫描器'],
  ] as const)('独立展示安全扫描状态 %s', (securityScanStatus, label) => {
    const wrapper = mount(FileLifecycleStatuses, {
      props: { ...completeProps, securityScanStatus },
    })
    const item = wrapper.get('[data-status-kind="security-scan"]')

    expect(item.get('dt').text()).toBe('安全扫描状态')
    expect(item.get('.status-tag').text()).toContain(label)
    expect(item.get('.status-tag').attributes('aria-label')).toBe(`状态：${label}`)
  })

  it.each([
    [null, 'active', ['—', '● 有效'], 3],
    ['active', null, ['● 有效', '—'], 3],
    [null, null, ['—', '—'], 2],
  ] as const)(
    '解析状态为 %s 且 Markdown 状态为 %s 时不臆造缺失状态',
    (parseStatus, markdownStatus, expectedText, expectedTagCount) => {
      const wrapper = mount(FileLifecycleStatuses, {
        props: { ...completeProps, parseStatus, markdownStatus },
      })

      expect(wrapper.get('[data-status-kind="parse"] dd').text()).toBe(expectedText[0])
      expect(wrapper.get('[data-status-kind="markdown"] dd').text()).toBe(expectedText[1])
      expect(wrapper.findAll('.status-tag')).toHaveLength(expectedTagCount)
      expect(wrapper.text()).not.toContain('待处理')
    },
  )
})

describe('制度与技术处理状态', () => {
  it('按固定顺序将四类状态作为具名语义项独立展示', () => {
    const wrapper = mount(PolicyPipelineStatuses, {
      props: {
        policyStatus: 'published',
        markdownStatus: 'failed',
        chunkSetStatus: 'blocked',
        indexVersionStatus: 'active',
      },
    })
    const items = wrapper.findAll('[data-status-kind]')

    expect(wrapper.attributes('aria-label')).toBe('制度与技术处理状态')
    expect(items.map((item) => item.attributes('data-status-kind'))).toEqual([
      'policy',
      'markdown',
      'chunk-set',
      'index-version',
    ])
    expect(items.map((item) => item.get('dt').text())).toEqual([
      '制度业务状态',
      'Markdown 状态',
      '分块集合状态',
      '知识库索引状态',
    ])
    expect(items.map((item) => item.get('dd').text())).toEqual([
      '● 已发布',
      '● 失败',
      '● 已阻断',
      '● 有效',
    ])
    expect(items.map((item) => item.get('.status-tag').attributes('aria-label'))).toEqual([
      '状态：已发布',
      '状态：失败',
      '状态：已阻断',
      '状态：有效',
    ])
    expect(wrapper.find('[aria-live]').exists()).toBe(false)
  })

  it('派生版本缺失时显示空值且不臆造待处理状态', () => {
    const wrapper = mount(PolicyPipelineStatuses, {
      props: {
        policyStatus: 'draft',
        markdownStatus: null,
        chunkSetStatus: null,
        indexVersionStatus: null,
      },
    })

    expect(wrapper.get('[data-status-kind="policy"] dd').text()).toBe('● 草稿')
    expect(wrapper.get('[data-status-kind="markdown"] dd').text()).toBe('—')
    expect(wrapper.get('[data-status-kind="chunk-set"] dd').text()).toBe('—')
    expect(wrapper.get('[data-status-kind="index-version"] dd').text()).toBe('—')
    expect(wrapper.findAll('.status-tag')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('待处理')
  })
})

describe('AI 问答状态', () => {
  it('按固定顺序把回答状态和证据充分性作为具名语义项独立展示', () => {
    const wrapper = mount(QaAnswerStatuses, {
      props: {
        answerStatus: 'answered',
        evidenceSufficiency: 'sufficient',
      },
    })
    const items = wrapper.findAll('[data-status-kind]')

    expect(wrapper.attributes('aria-label')).toBe('AI 问答状态')
    expect(items.map((item) => item.attributes('data-status-kind'))).toEqual([
      'answer',
      'evidence',
    ])
    expect(items.map((item) => item.get('dt').text())).toEqual(['回答状态', '证据充分性'])
    expect(items.map((item) => item.get('dd').text())).toEqual(['● 已回答', '● 证据充分'])
    expect(items.map((item) => item.get('.status-tag').attributes('aria-label'))).toEqual([
      '状态：已回答',
      '状态：证据充分',
    ])
    expect(wrapper.find('[aria-live]').exists()).toBe(false)
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it.each([
    ['answered', '已回答'],
    ['refused', '已拒答'],
    ['error', '系统错误'],
    ['degraded', '服务降级'],
  ] as const)('展示回答状态 %s 的精确文案和无障碍名称', (answerStatus, label) => {
    const wrapper = mount(QaAnswerStatuses, {
      props: { answerStatus, evidenceSufficiency: 'unknown' },
    })
    const status = wrapper.get('[data-status-kind="answer"] .status-tag')

    expect(status.text()).toContain(label)
    expect(status.attributes('aria-label')).toBe(`状态：${label}`)
  })

  it.each([
    ['sufficient', '证据充分'],
    ['insufficient', '证据不足'],
    ['conflicting', '证据冲突'],
    ['unknown', '证据充分性未知'],
  ] as const)(
    '展示证据充分性 %s 的精确文案和无障碍名称',
    (evidenceSufficiency, label) => {
      const wrapper = mount(QaAnswerStatuses, {
        props: { answerStatus: 'refused', evidenceSufficiency },
      })
      const status = wrapper.get('[data-status-kind="evidence"] .status-tag')

      expect(status.text()).toContain(label)
      expect(status.attributes('aria-label')).toBe(`状态：${label}`)
    },
  )
})

describe('合同确认状态与合同状态', () => {
  it('按固定顺序把两个状态作为具名语义项独立展示', () => {
    const wrapper = mount(ContractStatuses, {
      props: {
        confirmationStatus: 'confirmed',
        contractStatus: 'active',
      },
    })
    const items = wrapper.findAll('[data-status-kind]')

    expect(wrapper.attributes('aria-label')).toBe('合同确认状态与合同状态')
    expect(items.map((item) => item.attributes('data-status-kind'))).toEqual([
      'confirmation',
      'contract',
    ])
    expect(items.map((item) => item.get('dt').text())).toEqual(['确认状态', '合同状态'])
    expect(items.map((item) => item.get('dd').text())).toEqual(['● 已确认', '● 有效'])
    expect(items.map((item) => item.get('.status-tag').attributes('aria-label'))).toEqual([
      '状态：已确认',
      '状态：有效',
    ])
    expect(wrapper.find('[aria-live]').exists()).toBe(false)
  })

  it.each([
    ['unconfirmed', '未确认'],
    ['confirmed', '已确认'],
    ['rejected', '已拒绝'],
  ] as const)('展示确认状态 %s 的精确文案和无障碍名称', (confirmationStatus, label) => {
    const wrapper = mount(ContractStatuses, {
      props: { confirmationStatus, contractStatus: 'draft' },
    })
    const status = wrapper.get('[data-status-kind="confirmation"] .status-tag')

    expect(status.text()).toContain(label)
    expect(status.attributes('aria-label')).toBe(`状态：${label}`)
  })

  it.each([
    ['draft', '草稿'],
    ['active', '有效'],
    ['expired', '到期'],
    ['terminated', '终止'],
    ['archived', '归档'],
  ] as const)('展示合同状态 %s 的精确文案和无障碍名称', (contractStatus, label) => {
    const wrapper = mount(ContractStatuses, {
      props: { confirmationStatus: 'unconfirmed', contractStatus },
    })
    const status = wrapper.get('[data-status-kind="contract"] .status-tag')

    expect(status.text()).toContain(label)
    expect(status.attributes('aria-label')).toBe(`状态：${label}`)
  })
})

describe('发票确认状态与重复状态', () => {
  it('按固定顺序把两个状态作为具名语义项独立展示', () => {
    const wrapper = mount(InvoiceStatuses, {
      props: {
        confirmationStatus: 'confirmed',
        duplicateStatus: 'confirmed_duplicate',
      },
    })
    const items = wrapper.findAll('[data-status-kind]')

    expect(wrapper.attributes('aria-label')).toBe('发票确认状态与重复状态')
    expect(items).toHaveLength(2)
    expect(items.map((item) => item.attributes('data-status-kind'))).toEqual([
      'confirmation',
      'duplicate',
    ])
    expect(items.map((item) => item.get('dt').text())).toEqual(['确认状态', '重复状态'])
    expect(items.map((item) => item.get('dd').text())).toEqual(['● 已确认', '● 已确认重复'])
    expect(items.map((item) => item.get('.status-tag').attributes('aria-label'))).toEqual([
      '状态：已确认',
      '状态：已确认重复',
    ])
    expect(wrapper.find('[aria-live]').exists()).toBe(false)
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it.each([
    ['unconfirmed', '未确认'],
    ['confirmed', '已确认'],
    ['rejected', '已拒绝'],
  ] as const)('展示确认状态 %s 的精确文案和无障碍名称', (confirmationStatus, label) => {
    const wrapper = mount(InvoiceStatuses, {
      props: { confirmationStatus, duplicateStatus: 'not_checked' },
    })
    const status = wrapper.get('[data-status-kind="confirmation"] .status-tag')

    expect(status.text()).toContain(label)
    expect(status.attributes('aria-label')).toBe(`状态：${label}`)
  })

  it.each([
    ['not_checked', '尚未检测'],
    ['unique', '当前未发现重复'],
    ['suspected', '疑似重复，需要人工处理'],
    ['confirmed_duplicate', '已确认重复'],
    ['exception_approved', '已批准例外'],
  ] as const)('展示重复状态 %s 的精确文案和无障碍名称', (duplicateStatus, label) => {
    const wrapper = mount(InvoiceStatuses, {
      props: { confirmationStatus: 'unconfirmed', duplicateStatus },
    })
    const status = wrapper.get('[data-status-kind="duplicate"] .status-tag')

    expect(status.text()).toContain(label)
    expect(status.attributes('aria-label')).toBe(`状态：${label}`)
  })
})

describe('十进制金额展示', () => {
  it.each([
    ['100000.00', '100,000.00'],
    ['-1000.00', '-1,000.00'],
    ['+1000.00', '+1,000.00'],
    ['9999999999999999.99', '9,999,999,999,999,999.99'],
    ['0.10', '0.10'],
    ['12.3400', '12.3400'],
    ['001000.00', '001,000.00'],
  ] as const)('仅对规范十进制字面量 %s 插入千分位且保留精度', (amount, expected) => {
    const wrapper = mount(DecimalAmount, { props: { amount } })

    expect(wrapper.text()).toBe(expected)
  })

  it('将空值明确显示为破折号', () => {
    const wrapper = mount(DecimalAmount, { props: { amount: null } })

    expect(wrapper.text()).toBe('—')
  })

  it.each(['1e3', '1.', '.5', '1,000.00', '<script>alert("amount")</script>'] as const)(
    '将非规范输入 %s 仅作为惰性文本原样显示',
    (amount) => {
      const wrapper = mount(DecimalAmount, { props: { amount } })

      expect(wrapper.text()).toBe(amount)
      expect(wrapper.find('script').exists()).toBe(false)
    },
  )

  it('属性更新后重新格式化并能切换为空值', async () => {
    const wrapper = mount(DecimalAmount, { props: { amount: '1000.00' } })

    expect(wrapper.text()).toBe('1,000.00')

    await wrapper.setProps({ amount: '-2000000.3400' })
    expect(wrapper.text()).toBe('-2,000,000.3400')

    await wrapper.setProps({ amount: null })
    expect(wrapper.text()).toBe('—')
  })
})

describe('Job 阶段指示器', () => {
  it.each(formalJobStatusLabels)('将 Job 状态 %s 渲染为简体中文', (status, label) => {
    const wrapper = mount(JobStageIndicator, {
      props: { status, stage: null, attemptNo: 1, maxAttempts: 3 },
    })

    expect(wrapper.get('.status-tag').text()).toContain(label)
    expect(wrapper.get('.status-tag').attributes('aria-label')).toBe(`状态：${label}`)
  })

  it.each(formalJobStageLabels)('将正式阶段 %s 渲染为简体中文', (stage, label) => {
    const wrapper = mount(JobStageIndicator, {
      props: { status: 'running', stage, attemptNo: 1, maxAttempts: 3 },
    })

    expect(wrapper.get('.job-stage-label').text()).toBe(label)
  })

  it('stage 为 null 时不臆造阶段文案', () => {
    const wrapper = mount(JobStageIndicator, {
      props: { status: 'queued', stage: null, attemptNo: 1, maxAttempts: 3 },
    })

    expect(wrapper.find('.job-stage-label').exists()).toBe(false)
    expect(wrapper.text()).toContain('已排队')
    expect(wrapper.text()).toContain('第 1 次尝试（最多 3 次）')
  })

  it('未知阶段 code 仅作为文本渲染', () => {
    const unknownStage = '<script>alert("sensitive")</script>'
    const wrapper = mount(JobStageIndicator, {
      props: { status: 'running', stage: unknownStage, attemptNo: 1, maxAttempts: 3 },
    })

    expect(wrapper.get('.job-stage-label').text()).toBe(unknownStage)
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.html()).toContain('&lt;script&gt;')
  })

  it('精确展示尝试次数且不伪造进度百分比', () => {
    const wrapper = mount(JobStageIndicator, {
      props: { status: 'running', stage: 'parsing', attemptNo: 2, maxAttempts: 5 },
    })

    expect(wrapper.get('.job-stage-attempt').text()).toBe('第 2 次尝试（最多 5 次）')
    expect(wrapper.text()).not.toContain('%')
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
    expect(wrapper.find('progress').exists()).toBe(false)
  })

  it('属性更新时公告最新阶段和尝试次数', async () => {
    const wrapper = mount(JobStageIndicator, {
      props: { status: 'running', stage: 'parsing', attemptNo: 1, maxAttempts: 3 },
    })

    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.attributes('aria-live')).toBe('polite')
    expect(wrapper.attributes('aria-atomic')).toBe('true')

    await wrapper.setProps({
      status: 'succeeded',
      stage: 'report_generating',
      attemptNo: 2,
      maxAttempts: 3,
    })

    expect(wrapper.get('.status-tag').text()).toContain('已成功')
    expect(wrapper.get('.job-stage-label').text()).toBe('正在生成审核报告')
    expect(wrapper.get('.job-stage-attempt').text()).toBe('第 2 次尝试（最多 3 次）')
    expect(wrapper.text()).not.toContain('正在解析文档')
  })
})

describe('风险等级与复核状态', () => {
  it('按固定顺序把三个事实作为具名语义项独立展示', () => {
    const wrapper = mount(RiskReviewStatuses, {
      props: {
        originalLevel: 'high',
        effectiveLevel: 'medium',
        reviewStatus: 'adjusted',
      },
    })
    const items = wrapper.findAll('[data-risk-kind]')

    expect(wrapper.attributes('aria-label')).toBe('风险等级与复核状态')
    expect(items.map((item) => item.attributes('data-risk-kind'))).toEqual([
      'original',
      'effective',
      'review',
    ])
    expect(items.map((item) => item.get('dt').text())).toEqual([
      '原始等级',
      '有效等级',
      '复核状态',
    ])
    expect(items.map((item) => item.get('dd').text())).toEqual([
      '● 高风险',
      '● 中风险',
      '● 已调整',
    ])
    expect(items.map((item) => item.get('.status-tag').attributes('aria-label'))).toEqual([
      '状态：高风险',
      '状态：中风险',
      '状态：已调整',
    ])
    expect(wrapper.find('[aria-live]').exists()).toBe(false)
  })

  it.each([
    ['pending', '待处理'],
    ['confirmed', '已确认'],
    ['dismissed', '已驳回'],
    ['adjusted', '已调整'],
  ] as const)('展示复核状态 %s 的可见文字和无障碍名称', (reviewStatus, label) => {
    const wrapper = mount(RiskReviewStatuses, {
      props: {
        originalLevel: 'none',
        effectiveLevel: 'none',
        reviewStatus,
      },
    })
    const review = wrapper.get('[data-risk-kind="review"] .status-tag')

    expect(review.text()).toContain(label)
    expect(review.attributes('aria-label')).toBe(`状态：${label}`)
  })
})

describe('审核任务与当前执行状态', () => {
  it('按固定顺序把稳定任务和当前执行作为两个具名语义项独立展示', () => {
    const wrapper = mount(AuditTaskExecutionStatuses, {
      props: {
        taskStatus: 'open',
        executionStatus: 'pending_audit_review',
      },
    })
    const items = wrapper.findAll('[data-status-kind]')

    expect(wrapper.attributes('aria-label')).toBe('审核任务与当前执行状态')
    expect(items.map((item) => item.attributes('data-status-kind'))).toEqual([
      'task',
      'execution',
    ])
    expect(items.map((item) => item.get('dt').text())).toEqual(['任务状态', '当前执行状态'])
    expect(items.map((item) => item.get('dd').text())).toEqual(['● 未完成', '● 待审计复核'])
    expect(items.map((item) => item.get('.status-tag').attributes('aria-label'))).toEqual([
      '状态：未完成',
      '状态：待审计复核',
    ])
    expect(wrapper.find('[aria-live]').exists()).toBe(false)
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it.each([
    ['open', '未完成'],
    ['completed', '已完成'],
    ['archived', '已归档'],
  ] as const)('展示稳定任务状态 %s 的精确文字和无障碍名称', (taskStatus, label) => {
    const wrapper = mount(AuditTaskExecutionStatuses, {
      props: { taskStatus, executionStatus: null },
    })
    const status = wrapper.get('[data-status-kind="task"] .status-tag')

    expect(status.text()).toContain(label)
    expect(status.attributes('aria-label')).toBe(`状态：${label}`)
  })

  it.each([
    ['draft', '草稿'],
    ['validating', '校验中'],
    ['queued', '已排队'],
    ['running', '进行中'],
    ['pending_finance_review', '待财务复核'],
    ['pending_audit_review', '待审计复核'],
    ['returned_for_correction', '已退回修正'],
    ['completed', '已完成'],
    ['failed', '失败'],
    ['cancelled', '已取消'],
    ['outdated', '已过期'],
  ] as const)(
    '展示当前执行状态 %s 的精确文字和无障碍名称',
    (executionStatus, label) => {
      const wrapper = mount(AuditTaskExecutionStatuses, {
        props: { taskStatus: 'open', executionStatus },
      })
      const status = wrapper.get('[data-status-kind="execution"] .status-tag')

      expect(status.text()).toContain(label)
      expect(status.attributes('aria-label')).toBe(`状态：${label}`)
    },
  )

  it('当前执行为空时明确表示尚无版本且不伪造待处理状态', () => {
    const wrapper = mount(AuditTaskExecutionStatuses, {
      props: { taskStatus: 'open', executionStatus: null },
    })
    const execution = wrapper.get('[data-status-kind="execution"] dd')

    expect(execution.text()).toBe('—')
    expect(execution.get('span').attributes('aria-label')).toBe('暂无当前执行版本')
    expect(wrapper.findAll('.status-tag')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('待处理')
  })
})

describe('过期报告提示', () => {
  it('仅为过期报告展示冻结文案和完整无障碍公告', () => {
    const wrapper = mount(ReportOutdatedNotice, { props: { status: 'outdated' } })
    const alert = wrapper.get('[role="alert"]')

    expect(alert.classes()).toContain('notice-banner')
    expect(alert.attributes('aria-atomic')).toBe('true')
    expect(alert.text()).toBe('报告已过期：该报告基于旧事实版本，仅供历史追溯')
  })

  it.each(['queued', 'generating', 'ready', 'failed', 'archived'] as const)(
    '报告状态 %s 不渲染过期提示',
    (status) => {
      const wrapper = mount(ReportOutdatedNotice, { props: { status } })

      expect(wrapper.find('[role="alert"]').exists()).toBe(false)
      expect(wrapper.text()).toBe('')
    },
  )
})

describe('Trace ID 复制反馈', () => {
  const traceId = '90000000-0000-0000-0000-000000000001'

  it('只写入 Trace ID 并公告成功结果', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = mount(TraceIdCopy, { props: { traceId } })

    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledOnce()
    expect(writeText).toHaveBeenCalledWith(traceId)
    expect(wrapper.get('button').text()).toBe('已复制')
    expect(wrapper.get('[aria-live="polite"]').text()).toBe('Trace ID 已复制')
  })

  it('剪贴板拒绝时不抛出也不回显错误详情', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('sensitive clipboard detail'))
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = mount(TraceIdCopy, { props: { traceId } })

    await expect(wrapper.get('button').trigger('click')).resolves.toBeUndefined()
    await flushPromises()

    expect(wrapper.get('button').text()).toBe('复制失败')
    expect(wrapper.get('[aria-live="polite"]').text()).toBe('Trace ID 复制失败')
    expect(wrapper.text()).not.toContain('sensitive clipboard detail')
  })

  it('剪贴板不可用时稳定显示失败反馈', async () => {
    vi.stubGlobal('navigator', {})
    const wrapper = mount(TraceIdCopy, { props: { traceId } })

    await expect(wrapper.get('button').trigger('click')).resolves.toBeUndefined()

    expect(wrapper.get('button').text()).toBe('复制失败')
    expect(wrapper.get('[aria-live="polite"]').text()).toBe('Trace ID 复制失败')
  })

  it('复制中拒绝并发重复点击，下一次尝试以新结果覆盖旧状态', async () => {
    let resolveFirst!: () => void
    const firstAttempt = new Promise<void>((resolve) => {
      resolveFirst = resolve
    })
    const writeText = vi
      .fn()
      .mockReturnValueOnce(firstAttempt)
      .mockRejectedValueOnce(new Error('second attempt rejected'))
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = mount(TraceIdCopy, { props: { traceId } })
    const button = wrapper.get('button')

    await button.trigger('click')
    expect(button.attributes('disabled')).toBeDefined()
    expect(button.text()).toBe('复制中')

    await button.trigger('click')
    expect(writeText).toHaveBeenCalledTimes(1)

    resolveFirst()
    await flushPromises()
    expect(button.text()).toBe('已复制')

    await button.trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledTimes(2)
    expect(button.text()).toBe('复制失败')
    expect(wrapper.text()).not.toContain('second attempt rejected')
  })

  it('Trace ID 更新后清除旧复制成功状态', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = mount(TraceIdCopy, { props: { traceId } })

    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.get('button').text()).toBe('已复制')

    await wrapper.setProps({ traceId: '90000000-0000-0000-0000-000000000002' })

    expect(wrapper.get('button').text()).toBe('复制')
    expect(wrapper.get('[aria-live="polite"]').text()).toBe('')
  })

  it('Trace ID 更新后忽略仍在等待的旧复制结果', async () => {
    let resolveFirst!: () => void
    const firstAttempt = new Promise<void>((resolve) => {
      resolveFirst = resolve
    })
    const nextTraceId = '90000000-0000-0000-0000-000000000002'
    const writeText = vi.fn().mockReturnValueOnce(firstAttempt).mockResolvedValueOnce(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = mount(TraceIdCopy, { props: { traceId } })

    await wrapper.get('button').trigger('click')
    await wrapper.setProps({ traceId: nextTraceId })
    resolveFirst()
    await flushPromises()

    expect(wrapper.get('button').text()).toBe('复制')
    expect(wrapper.get('[aria-live="polite"]').text()).toBe('')

    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenNthCalledWith(1, traceId)
    expect(writeText).toHaveBeenNthCalledWith(2, nextTraceId)
    expect(wrapper.get('button').text()).toBe('已复制')
  })
})
