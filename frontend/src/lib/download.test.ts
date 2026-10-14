import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { downloadText, rowsToCsv } from './download'

describe('rowsToCsv', () => {
  it('writes numbers with a decimal comma for Russian Excel', () => {
    expect(rowsToCsv([['Модель', 26.5, 25.8, 42.5, 42, -3.5]])).toBe(
      '﻿"Модель";26,5;25,8;42,5;42;-3,5',
    )
  })

  it('quotes text, escapes quotes and keeps empty cells', () => {
    expect(
      rowsToCsv([
        ['Air "Max"', null, undefined, true],
        ['a;b', Number.NaN, 'Доставка 5–7 дней'],
      ]),
    ).toBe('﻿"Air ""Max""";"";"";"true"\r\n"a;b";;"Доставка 5–7 дней"')
  })

  it('neutralises cells that Excel would run as formulas', () => {
    const csv = rowsToCsv([
      [
        '=HYPERLINK("https://evil.test","Nike")',
        '+7 (999)',
        '-2+3',
        '@SUM(A1)',
        '\tcmd',
        '\rcmd',
        'Nike = Air',
      ],
    ])

    expect(csv.slice(1).split(';')).toEqual([
      '"\'=HYPERLINK(""https://evil.test"",""Nike"")"',
      '"\'+7 (999)"',
      '"\'-2+3"',
      '"\'@SUM(A1)"',
      '"\'\tcmd"',
      '"\'\rcmd"',
      '"Nike = Air"',
    ])
  })

  it('does not mangle real negative numbers', () => {
    expect(rowsToCsv([[-1, '-1']])).toBe('﻿-1;"\'-1"')
  })
})

describe('downloadText', () => {
  const originalCreate = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
  const originalRevoke = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
  const createObjectURL = vi.fn(() => 'blob:poizon/1')
  const revokeObjectURL = vi.fn()

  beforeEach(() => {
    vi.useFakeTimers()
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: createObjectURL,
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: revokeObjectURL,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    createObjectURL.mockClear()
    revokeObjectURL.mockClear()
    if (originalCreate) {
      Object.defineProperty(URL, 'createObjectURL', originalCreate)
    } else {
      Reflect.deleteProperty(URL, 'createObjectURL')
    }
    if (originalRevoke) {
      Object.defineProperty(URL, 'revokeObjectURL', originalRevoke)
    } else {
      Reflect.deleteProperty(URL, 'revokeObjectURL')
    }
  })

  it('clicks a temporary link and revokes the blob URL only later', () => {
    const clicked: HTMLAnchorElement[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      expect(this.isConnected).toBe(true)
      clicked.push(this)
    })

    downloadText('poizon.csv', 'a;b', 'text/csv;charset=utf-8')

    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(clicked).toHaveLength(1)
    expect(clicked[0]?.download).toBe('poizon.csv')
    expect(clicked[0]?.getAttribute('href')).toBe('blob:poizon/1')
    expect(clicked[0]?.isConnected).toBe(false)
    expect(revokeObjectURL).not.toHaveBeenCalled()

    vi.runAllTimers()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:poizon/1')
  })
})
