import {
  createContext,
  useCallback,
  useContext,
  useId,
  useMemo,
  useState,
  type ComponentPropsWithRef,
  type KeyboardEvent,
} from 'react'

import { cn } from '../../lib/utils'

type TabsOrientation = 'horizontal' | 'vertical'
type TabsActivationMode = 'automatic' | 'manual'

interface TabsContextValue {
  activationMode: TabsActivationMode
  baseId: string
  orientation: TabsOrientation
  setValue: (value: string) => void
  value: string
}

const TabsContext = createContext<TabsContextValue | null>(null)

function useTabsContext(componentName: string): TabsContextValue {
  const context = useContext(TabsContext)

  if (!context) {
    throw new Error(`${componentName} must be rendered inside <Tabs>.`)
  }

  return context
}

function idPart(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]+/g, '-') || 'item'
}

interface TabsCommonProps extends Omit<
  ComponentPropsWithRef<'div'>,
  'defaultValue' | 'onChange'
> {
  activationMode?: TabsActivationMode
  orientation?: TabsOrientation
}

interface ControlledTabsProps {
  defaultValue?: never
  onValueChange: (value: string) => void
  value: string
}

interface UncontrolledTabsProps {
  defaultValue: string
  onValueChange?: (value: string) => void
  value?: never
}

export type TabsProps = TabsCommonProps &
  (ControlledTabsProps | UncontrolledTabsProps)

export function Tabs({
  activationMode = 'automatic',
  children,
  className,
  defaultValue,
  id,
  onValueChange,
  orientation = 'horizontal',
  value: controlledValue,
  ...props
}: TabsProps) {
  const generatedId = useId()
  const baseId = id ?? `tabs-${generatedId}`
  const [uncontrolledValue, setUncontrolledValue] = useState(defaultValue ?? '')
  const value = controlledValue ?? uncontrolledValue

  const setValue = useCallback(
    (nextValue: string) => {
      if (controlledValue === undefined) {
        setUncontrolledValue(nextValue)
      }
      onValueChange?.(nextValue)
    },
    [controlledValue, onValueChange],
  )

  const context = useMemo<TabsContextValue>(
    () => ({ activationMode, baseId, orientation, setValue, value }),
    [activationMode, baseId, orientation, setValue, value],
  )

  return (
    <TabsContext.Provider value={context}>
      <div
        {...props}
        id={baseId}
        className={cn('ui-tabs', className)}
        data-orientation={orientation}
      >
        {children}
      </div>
    </TabsContext.Provider>
  )
}

export type TabListProps = ComponentPropsWithRef<'div'>

export function TabList({ className, onKeyDown, ...props }: TabListProps) {
  const { activationMode, orientation } = useTabsContext('TabList')

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown?.(event)
    if (event.defaultPrevented) return

    const horizontal = orientation === 'horizontal'
    const previousKey = horizontal ? 'ArrowLeft' : 'ArrowUp'
    const nextKey = horizontal ? 'ArrowRight' : 'ArrowDown'
    const handledKeys = [previousKey, nextKey, 'Home', 'End']

    if (!handledKeys.includes(event.key)) return

    const tabs = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>(
        '[role="tab"]:not(:disabled)',
      ),
    )
    if (tabs.length === 0) return

    const activeIndex = tabs.indexOf(
      document.activeElement as HTMLButtonElement,
    )
    let nextIndex = activeIndex < 0 ? 0 : activeIndex

    if (event.key === 'Home') nextIndex = 0
    if (event.key === 'End') nextIndex = tabs.length - 1
    if (event.key === previousKey) {
      nextIndex = (nextIndex - 1 + tabs.length) % tabs.length
    }
    if (event.key === nextKey) {
      nextIndex = (nextIndex + 1) % tabs.length
    }

    const nextTab = tabs[nextIndex]
    if (!nextTab) return

    event.preventDefault()
    nextTab.focus()
    if (activationMode === 'automatic') nextTab.click()
  }

  return (
    <div
      {...props}
      role="tablist"
      aria-orientation={orientation}
      className={cn('ui-tabs__list', className)}
      onKeyDown={handleKeyDown}
    />
  )
}

export interface TabProps extends Omit<
  ComponentPropsWithRef<'button'>,
  'value'
> {
  value: string
}

export function Tab({
  className,
  disabled,
  onClick,
  value,
  ...props
}: TabProps) {
  const context = useTabsContext('Tab')
  const active = context.value === value
  const part = idPart(value)

  return (
    <button
      {...props}
      id={`${context.baseId}-tab-${part}`}
      type="button"
      role="tab"
      className={cn('ui-tabs__tab', className)}
      disabled={disabled}
      tabIndex={active ? 0 : -1}
      aria-controls={`${context.baseId}-panel-${part}`}
      aria-selected={active}
      onClick={(event) => {
        onClick?.(event)
        if (!event.defaultPrevented) context.setValue(value)
      }}
    />
  )
}

export interface TabPanelProps extends ComponentPropsWithRef<'div'> {
  value: string
}

export function TabPanel({
  children,
  className,
  tabIndex = 0,
  value,
  ...props
}: TabPanelProps) {
  const context = useTabsContext('TabPanel')
  const active = context.value === value
  const part = idPart(value)

  return (
    <div
      {...props}
      id={`${context.baseId}-panel-${part}`}
      role="tabpanel"
      className={cn('ui-tabs__panel', className)}
      tabIndex={tabIndex}
      aria-labelledby={`${context.baseId}-tab-${part}`}
      hidden={!active}
    >
      {children}
    </div>
  )
}
