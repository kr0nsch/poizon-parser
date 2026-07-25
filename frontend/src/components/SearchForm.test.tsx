import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { DEFAULT_SEARCH_FORM } from '../lib/storage'
import { SearchForm } from './SearchForm'

describe('SearchForm', () => {
  it('submits valid brand and foot length and exposes measuring help', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const onSubmit = vi.fn()

    render(
      <SearchForm
        active={false}
        brands={[{ id: 1, name: 'Nike', slug: 'nike', url: '/nike' }]}
        brandsLoading={false}
        conversionLoading={false}
        form={{ ...DEFAULT_SEARCH_FORM, brand: 'Nike', size: '26.5' }}
        onCancel={vi.fn()}
        onChange={onChange}
        onSubmit={onSubmit}
        starting={false}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Как измерить' }))
    expect(screen.getByText('Как измерить стопу')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Найти' }))
    expect(onSubmit).toHaveBeenCalledOnce()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('shows the long-catalog warning', () => {
    render(
      <SearchForm
        active={false}
        brands={[]}
        brandsLoading={false}
        conversionLoading={false}
        form={{ ...DEFAULT_SEARCH_FORM, depth: '0' }}
        onCancel={vi.fn()}
        onChange={vi.fn()}
        onSubmit={vi.fn()}
        starting={false}
      />,
    )

    expect(screen.getByText(/может занять десятки минут/i)).toBeInTheDocument()
  })
})
