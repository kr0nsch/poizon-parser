export type CsvCell = string | number | boolean | null | undefined

// Excel не исполняет ячейку как формулу, если она начинается с апострофа.
// Кавычки CSV от этого не защищают, а названия моделей приходят со стороннего
// сайта, поэтому такие строки обезвреживаем (OWASP: CSV injection).
const FORMULA_START = /^[=+\-@\t\r]/

// Blob читается браузером уже после click(): Firefox и Safari теряют загрузку,
// если ссылку отозвать сразу. Держим её с запасом, как FileSaver.js.
const REVOKE_DELAY_MS = 40_000

function formatCell(value: CsvCell): string {
  if (typeof value === 'number') {
    // Русская локаль Excel читает «26.5» как дату, а «42.5» — как текст;
    // с десятичной запятой число остаётся числом. Поля разделены «;».
    return Number.isFinite(value) ? String(value).replace('.', ',') : ''
  }
  const text = String(value ?? '')
  const safe = FORMULA_START.test(text) ? `'${text}` : text
  return `"${safe.replaceAll('"', '""')}"`
}

export function rowsToCsv(rows: readonly (readonly CsvCell[])[]): string {
  return `﻿${rows.map((row) => row.map(formatCell).join(';')).join('\r\n')}`
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
  anchor.style.display = 'none'
  // Старые Firefox скачивают только по ссылке, вставленной в документ.
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS)
}
