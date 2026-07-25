import { Moon, Sun } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useState } from 'react'

import { Button } from './ui'
import { applyTheme, getInitialTheme, type Theme } from '../lib/storage'

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)
  const reduceMotion = useReducedMotion()

  function toggleTheme() {
    const nextTheme = theme === 'dark' ? 'light' : 'dark'
    const update = () => {
      applyTheme(nextTheme)
      setTheme(nextTheme)
    }
    if (!reduceMotion && typeof document.startViewTransition === 'function') {
      const transition = document.startViewTransition(update)
      void transition.finished.catch(() => undefined)
      return
    }
    update()
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
      <AnimatePresence initial={false} mode="wait">
        <motion.span
          key={theme}
          className="motion-theme-icon"
          initial={
            reduceMotion
              ? { opacity: 0 }
              : { opacity: 0, rotate: -35, scale: 0.65 }
          }
          animate={{ opacity: 1, rotate: 0, scale: 1 }}
          exit={
            reduceMotion
              ? { opacity: 0 }
              : { opacity: 0, rotate: 35, scale: 0.65 }
          }
          transition={{ duration: reduceMotion ? 0.08 : 0.2 }}
        >
          {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
        </motion.span>
      </AnimatePresence>
    </Button>
  )
}
