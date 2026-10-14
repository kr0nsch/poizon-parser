import { clsx, type ClassValue } from 'clsx'
import { useCallback, useLayoutEffect, useRef } from 'react'

export function cn(...values: ClassValue[]): string {
  return clsx(values)
}

type FocusTarget = () => HTMLElement | null | undefined

/** Элементы, на которые фокус можно перенести клавиатурой. */
const FOCUSABLE =
  'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

/** Последний переданный fallback — без пересоздания ref-колбэка. */
function useLatest(fallback: FocusTarget) {
  const fallbackRef = useRef(fallback)
  useLayoutEffect(() => {
    fallbackRef.current = fallback
  })
  return fallbackRef
}

/**
 * Переносит фокус после коммита: запасная цель к этому моменту уже
 * смонтирована и не disabled. Если фокус уже где-то на странице (его
 * переставил сам пользователь или другой обработчик), не трогаем его.
 */
function restoreFocusLater(pickTarget: FocusTarget) {
  queueMicrotask(() => {
    const current = document.activeElement
    if (current && current !== document.body && current.isConnected) {
      return
    }
    const target = pickTarget()
    if (target?.isConnected) target.focus()
  })
}

/**
 * Ref-колбэк для элемента, который может исчезнуть, пока на нём фокус
 * («Стоп» после отмены, «Пауза» после перехода в капчу). Если исчезнувший
 * элемент был в фокусе, фокус уходит на fallback(): иначе браузер сбрасывает
 * его на <body>, и клавиатура со скринридером теряют место на странице.
 */
export function useFocusRescue<T extends HTMLElement>(
  fallback: FocusTarget,
): (node: T | null) => (() => void) | undefined {
  const fallbackRef = useLatest(fallback)

  return useCallback(
    (node: T | null) => {
      if (!node) return undefined
      // React снимает ref до удаления узла из DOM, так что фокус ещё на нём.
      return () => {
        if (document.activeElement !== node) return
        restoreFocusLater(() => fallbackRef.current())
      }
    },
    [fallbackRef],
  )
}

/**
 * То же для элементов списка (карточек), внутри которых может быть фокус:
 * «Убрать» в итогах, смена фильтров в результатах. Фокус переходит на то же
 * по счёту действие соседа — следующего, а если его нет, предыдущего; когда
 * соседей не осталось, — на fallback().
 */
export function useListFocusRescue<T extends HTMLElement>(
  fallback: FocusTarget,
): (node: T | null) => (() => void) | undefined {
  const fallbackRef = useLatest(fallback)

  return useCallback(
    (node: T | null) => {
      if (!node) return undefined
      return () => {
        const focused = document.activeElement
        if (!focused || !node.contains(focused)) return
        // Соседей и место фокуса запоминаем сейчас: после коммита узла в DOM
        // уже нет. Сначала следующие элементы, затем предыдущие, ближние
        // раньше дальних.
        const actionIndex = Array.from(
          node.querySelectorAll(FOCUSABLE),
        ).indexOf(focused)
        const siblings = Array.from(node.parentElement?.children ?? [])
        const index = siblings.indexOf(node)
        const neighbours = [
          ...siblings.slice(index + 1),
          ...siblings.slice(0, index).reverse(),
        ]
        restoreFocusLater(() => {
          for (const neighbour of neighbours) {
            // Сосед мог уйти в том же коммите (например, «Очистить всё»).
            if (!neighbour.isConnected) continue
            const actions = neighbour.querySelectorAll<HTMLElement>(FOCUSABLE)
            const target = actions[actionIndex] ?? actions[0]
            if (target) return target
          }
          return fallbackRef.current()
        })
      }
    },
    [fallbackRef],
  )
}
