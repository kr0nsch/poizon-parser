import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Button } from './Button'

describe('Button', () => {
  it('keeps focus while loading and ignores clicks', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    const { rerender } = render(<Button onClick={onClick}>Пауза</Button>)

    const button = screen.getByRole('button', { name: 'Пауза' })
    button.focus()
    rerender(
      <Button onClick={onClick} loading loadingLabel="Ставлю…">
        Пауза
      </Button>,
    )

    expect(button).toHaveFocus()
    expect(button).toBeEnabled()
    expect(button).toHaveAttribute('aria-disabled', 'true')
    expect(button).toHaveAttribute('aria-busy', 'true')
    expect(button).toHaveTextContent('Ставлю…')

    await user.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('does not submit the form while loading', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn((event: SubmitEvent) => event.preventDefault())
    render(
      <form onSubmit={(event) => onSubmit(event.nativeEvent as SubmitEvent)}>
        <input aria-label="Бренд" />
        <Button type="submit" loading>
          Найти
        </Button>
      </form>,
    )

    await user.click(screen.getByRole('button', { name: 'Найти' }))
    await user.type(screen.getByLabelText('Бренд'), 'Nike{Enter}')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('still honours the native disabled state', () => {
    render(<Button disabled>Найти</Button>)
    expect(screen.getByRole('button', { name: 'Найти' })).toBeDisabled()
  })
})
