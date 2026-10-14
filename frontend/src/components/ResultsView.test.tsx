import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { SearchMatch } from '../api'
import {
  DEFAULT_RESULTS_FILTERS,
  ResultsView,
  type ResultsFilters,
} from './ResultsView'

const MATCH: SearchMatch = {
  spu_id: 1,
  sku_id: 10,
  title: 'Nike Air Max',
  article: 'A1',
  brand: 'Nike',
  url: 'https://www.thepoizon.ru/product/1',
  requested_size: 26.5,
  requested_scale: 'CM',
  converted_eu: 42,
  converted_cm: 26.5,
  converted_foot: 26.5,
  exact_conversion: true,
  conversion_source: 'brand',
  conversion_note: '',
  matched_scale: 'EU',
  size: '42',
  sizes: { EU: '42' },
  price: 9000,
  price_text: '9 000 ₽',
  currency: 'RUB',
  in_stock: true,
  delivery: '5-7 дней',
  variant: '',
  inventory_no: '',
  labels: [],
  product_min_price: 9000,
  size_tip: '',
  image: '',
}

function Harness({
  onCreateReport,
}: {
  onCreateReport: (matches: SearchMatch[], embed: boolean) => void
}) {
  const [filters, setFilters] = useState<ResultsFilters>(
    DEFAULT_RESULTS_FILTERS,
  )
  return (
    <ResultsView
      brand="Nike"
      filters={filters}
      matches={[MATCH]}
      picks={[]}
      reporting={false}
      savingKeys={new Set()}
      onFiltersChange={setFilters}
      onPick={vi.fn()}
      onCreateReport={onCreateReport}
    />
  )
}

describe('ResultsView', () => {
  it('disables report and exports when filters leave nothing', async () => {
    const user = userEvent.setup()
    const onCreateReport = vi.fn()
    render(<Harness onCreateReport={onCreateReport} />)

    const report = screen.getByRole('button', { name: /HTML-отчёт/ })
    expect(report).toBeEnabled()

    await user.type(screen.getByLabelText('Фильтр по названию'), 'zzz')

    expect(report).toBeDisabled()
    expect(screen.getByRole('button', { name: /CSV/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /JSON/ })).toBeDisabled()
    await user.click(report)
    expect(onCreateReport).not.toHaveBeenCalled()
  })

  it('reports exactly the filtered rows', async () => {
    const user = userEvent.setup()
    const onCreateReport = vi.fn()
    render(<Harness onCreateReport={onCreateReport} />)

    await user.type(screen.getByLabelText('Фильтр по названию'), 'air')
    await user.click(screen.getByRole('button', { name: /HTML-отчёт/ }))

    expect(onCreateReport).toHaveBeenCalledWith([MATCH], false)
  })
})
