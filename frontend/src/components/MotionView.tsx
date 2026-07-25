import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import type { ReactNode } from 'react'

interface MotionViewProps {
  children: ReactNode
  viewKey: string
}

export function MotionView({ children, viewKey }: MotionViewProps) {
  const reduceMotion = useReducedMotion()

  return (
    <AnimatePresence initial={false} mode="popLayout">
      <motion.div
        key={viewKey}
        className="motion-view"
        initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -6 }}
        transition={{
          duration: reduceMotion ? 0.08 : 0.22,
          ease: [0.22, 1, 0.36, 1],
        }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  )
}
