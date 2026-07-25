import { Moon, Sun } from 'lucide-react'
import { useState } from 'react'

import { Button } from './ui'
import { applyTheme, getInitialTheme, type Theme } from '../lib/storage'

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)

  function toggleTheme() {
    const nextTheme = theme === 'dark' ? 'light' : 'dark'
    applyTheme(nextTheme)
    setTheme(nextTheme)
  }

  const label =
    theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'

  return (
    <Button
      aria-label={label}
      title={label}
      variant="quiet"
      size="icon"
      onClick={toggleTheme}
    >
      {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
    </Button>
  )
}
