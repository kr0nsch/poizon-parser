export type CsvCell = string | number | boolean | null | undefined

function escapeCsv(value: CsvCell): string {
  return `"${String(value ?? '').replaceAll('"', '""')}"`
}

export function rowsToCsv(rows: readonly (readonly CsvCell[])[]): string {
  return `\uFEFF${rows.map((row) => row.map(escapeCsv).join(';')).join('\r\n')}`
}

export function downloadText(
  filename: string,
  content: string,
  type: string,
): void {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
