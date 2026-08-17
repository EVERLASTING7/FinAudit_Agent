const environmentLabels = {
  local: '开发环境',
  test: '测试环境',
  demo: '演示环境',
  staging: '预发布环境',
  prod: '生产环境',
  production: '生产环境',
} as const

export interface EnvironmentPresentation {
  label: string
  status: 'active' | 'pending'
}

export function getEnvironmentPresentation(value: unknown): EnvironmentPresentation {
  if (typeof value === 'string' && value in environmentLabels) {
    return {
      label: environmentLabels[value as keyof typeof environmentLabels],
      status: 'active',
    }
  }

  return { label: '环境未配置', status: 'pending' }
}
