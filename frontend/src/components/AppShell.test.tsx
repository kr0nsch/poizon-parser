import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { THEME_STORAGE_KEY } from '../lib/storage'
import { AppShell } from './AppShell'

describe('AppShell', () => {
  beforeEach(() => {
    localStorage.setItem(THEME_STORAGE_KEY, 'light')
  })

  afterEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove('dark')
    delete document.documentElement.dataset.theme
  })

  it('keeps the sidebar and mobile theme toggles in sync', async () => {
    const user = userEvent.setup()
    render(
      <AppShell
        activeView="search"
        title="Найдите свой размер"
        description="Описание"
        picksCount={0}
        onViewChange={vi.fn()}
      >
        <p>Контент</p>
      </AppShell>,
    )

    const toggles = screen.getAllByRole('button', {
      name: 'Включить тёмную тему',
    })
    expect(toggles).toHaveLength(2)

    // Переключаем тему в боковой панели — мобильная кнопка должна сразу
    // показать то же состояние, а её первое нажатие вернуть светлую тему.
    await user.click(toggles[0]!)
    expect(
      screen.getAllByRole('button', { name: 'Включить светлую тему' }),
    ).toHaveLength(2)
    expect(document.documentElement).toHaveClass('dark')

    await user.click(toggles[1]!)
    expect(
      screen.getAllByRole('button', { name: 'Включить тёмную тему' }),
    ).toHaveLength(2)
    expect(document.documentElement).not.toHaveClass('dark')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
  })
})
