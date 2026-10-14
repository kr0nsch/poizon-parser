import { clsx, type ClassValue } from 'clsx'
import { useCallback, useLayoutEffect, useRef } from 'react'

export function cn(...values: ClassValue[]): string {
  return clsx(values)
}

/**
 * Ref-колбэк для элемента, который может исчезнуть, пока на нём фокус
 * («Стоп» после отмены, «Пауза» после перехода в капчу). Если исчезнувший
 * элемент был в фокусе, фокус уходит на fallback(): иначе браузер сбрасывает
 * его на <body>, и клавиатура со скринридером теряют место на странице.
 */
export function useFocusRescue<T extends HTMLElement>(
  fallback: () => HTMLElement | null | undefined,
): (node: T | null) => (() => void) | undefined {
  const fallbackRef = useRef(fallback)
  useLayoutEffect(() => {
    fallbackRef.current = fallback
  })

  return useCallback((node: T | null) => {
    if (!node) return undefined
    // React снимает ref до удаления узла из DOM, так что фокус ещё на нём.
    return () => {
      if (document.activeElement !== node) return
      // Переносим фокус после коммита: запасная цель к этому моменту уже
      // смонтирована и не disabled.
      queueMicrotask(() => {
        const current = document.activeElement
        if (current && current !== document.body && current.isConnected) {
          return
        }
        const target = fallbackRef.current()
        if (target?.isConnected) target.focus()
      })
    }
  }, [])
}
