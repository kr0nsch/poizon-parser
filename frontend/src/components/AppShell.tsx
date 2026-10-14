import { BookmarkCheck, ExternalLink, Footprints, Search } from 'lucide-react'
import { motion } from 'motion/react'
import { useState, type ReactNode } from 'react'

import { getInitialTheme, type Theme } from '../lib/storage'
import { ThemeToggle } from './ThemeToggle'

export type AppView = 'search' | 'picks'

interface AppShellProps {
  activeView: AppView
  children: ReactNode
  description: string
  onViewChange: (view: AppView) => void
  picksCount: number
  title: string
}

interface NavigationProps {
  activeView: AppView
  onViewChange: (view: AppView) => void
  picksCount: number
  mobile?: boolean
}

function BrandLockup() {
  return (
    <div className="app-brand" aria-label="POIZON Size Finder">
      <span className="app-brand__mark" aria-hidden="true">
        <Footprints size={20} strokeWidth={1.8} />
      </span>
      <span>
        <span className="app-brand__eyebrow">thepoizon.ru</span>
        <span className="app-brand__name">Size Finder</span>
      </span>
    </div>
  )
}

function Navigation({
  activeView,
  mobile = false,
  onViewChange,
  picksCount,
}: NavigationProps) {
  return (
    <nav
      className={mobile ? 'mobile-header__nav' : 'app-nav'}
      aria-label="Основная навигация"
    >
      <motion.button
        className="app-nav__button"
        type="button"
        aria-current={activeView === 'search' ? 'page' : undefined}
        whileHover={mobile ? { y: -1 } : { x: 3 }}
        whileTap={{ scale: 0.98 }}
        onClick={() => onViewChange('search')}
      >
        {activeView === 'search' ? (
          <motion.span
            className="app-nav__active"
            layoutId={mobile ? 'mobile-nav-active' : 'sidebar-nav-active'}
            aria-hidden="true"
          />
        ) : null}
        <span className="app-nav__content">
          <Search size={17} aria-hidden="true" />
          Поиск
        </span>
      </motion.button>
      <motion.button
        className="app-nav__button"
        type="button"
        aria-current={activeView === 'picks' ? 'page' : undefined}
        whileHover={mobile ? { y: -1 } : { x: 3 }}
        whileTap={{ scale: 0.98 }}
        onClick={() => onViewChange('picks')}
      >
        {activeView === 'picks' ? (
          <motion.span
            className="app-nav__active"
            layoutId={mobile ? 'mobile-nav-active' : 'sidebar-nav-active'}
            aria-hidden="true"
          />
        ) : null}
        <span className="app-nav__content">
          <BookmarkCheck size={17} aria-hidden="true" />
          Итоги
          <motion.span
            key={picksCount}
            className="app-nav__count"
            aria-label={`Сохранено: ${picksCount}`}
            initial={{ scale: 0.75, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
          >
            {picksCount}
          </motion.span>
        </span>
      </motion.button>
    </nav>
  )
}

export function AppShell({
  activeView,
  children,
  description,
  onViewChange,
  picksCount,
  title,
}: AppShellProps) {
  // Одно состояние на оба переключателя темы: скрытый CSS-ом не должен
  // отставать от видимого после смены ширины окна.
  const [theme, setTheme] = useState<Theme>(getInitialTheme)

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <BrandLockup />
        <p className="app-sidebar__copy">
          Находит обувь в наличии под длину стопы и переводит размер по сетке
          бренда.
        </p>
        <Navigation
          activeView={activeView}
          onViewChange={onViewChange}
          picksCount={picksCount}
        />
        <div className="app-sidebar__footer">
          <a
            className="app-sidebar__source"
            href="https://thepoizon.ru"
            target="_blank"
            rel="noreferrer"
          >
            Открыть POIZON
            <ExternalLink size={13} aria-hidden="true" />
          </a>
          <ThemeToggle theme={theme} onThemeChange={setTheme} />
        </div>
      </aside>

      <main className="app-main">
        <header className="mobile-header">
          <div className="mobile-header__top">
            <BrandLockup />
            <ThemeToggle theme={theme} onThemeChange={setTheme} />
          </div>
          <Navigation
            mobile
            activeView={activeView}
            onViewChange={onViewChange}
            picksCount={picksCount}
          />
        </header>

        <header className="page-heading">
          <div>
            <p className="page-heading__eyebrow">
              {activeView === 'search' ? 'Подбор по стопе' : 'Личная подборка'}
            </p>
            <h1 className="page-heading__title">{title}</h1>
            <p className="page-heading__copy">{description}</p>
          </div>
        </header>

        <div className="app-content">{children}</div>
      </main>
    </div>
  )
}
