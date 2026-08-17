export function resolveEnvDir(offlineQualityFlag: string | undefined): false | undefined {
  return offlineQualityFlag === '1' ? false : undefined
}
