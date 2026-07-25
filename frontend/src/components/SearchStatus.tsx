import {
  Activity,
  AlertTriangle,
  ExternalLink,
  Pause,
  Play,
  ShieldAlert,
  Square,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import type { SearchSnapshot } from '../api'
import { formatActivityAge, formatDuration } from '../lib/format'
import { Badge, Button, Card, CardContent, Progress } from './ui'

interface SearchStatusProps {
  actionPending: boolean
  job: SearchSnapshot
  onCancel: () => void
  onPause: () => void
  onResume: () => void
}

function statusCopy(
  job: SearchSnapshot,
  nowSeconds: number,
  cooldownLeft: number,
) {
  const brand = job.brand?.name ?? 'бренда'
  if (job.status === 'running' && job.phase === 'collect') {
    return {
      title: `Собираю каталог ${brand}`,
      meta: `Получено моделей обуви: ${job.collected}`,
    }
  }
  if (job.status === 'running') {
    const spent = nowSeconds - job.started_at
    const estimate =
      job.checked > 0 && job.total > job.checked
        ? (spent / job.checked) * (job.total - job.checked)
        : 0
    const suffix =
      cooldownLeft > 0
        ? ` · пауза ${cooldownLeft} с`
        : estimate > 0
          ? ` · осталось около ${formatDuration(estimate)}`
          : ''
    return {
      title: `Проверяю карточки ${brand}`,
      meta: `${job.checked} из ${job.total}${suffix}`,
    }
  }
  if (job.status === 'captcha') {
    return {
      title: 'Поиск поставлен на паузу',
      meta: 'Пройдите проверку на сайте — найденное и прогресс сохранятся.',
    }
  }
  if (job.status === 'done') {
    const seconds = job.finished_at ? job.finished_at - job.started_at : 0
    return {
      title: 'Поиск завершён',
      meta: `Проверено ${job.checked} из ${job.total}, найдено ${job.found} · ${formatDuration(seconds)}`,
    }
  }
  if (job.status === 'cancelled') {
    return {
      title: 'Поиск остановлен',
      meta: `Проверено ${job.checked} из ${job.total}, найдено ${job.found}`,
    }
  }
  return {
    title: job.stop_reason
      ? `Ошибка: ${job.stop_reason}`
      : 'Поиск завершился с ошибкой',
    meta: job.error || 'Попробуйте изменить параметры и запустить поиск снова.',
  }
}

export function SearchStatus({
  actionPending,
  job,
  onCancel,
  onPause,
  onResume,
}: SearchStatusProps) {
  const [now, setNow] = useState(() => Date.now())
  const active = job.status === 'running' || job.status === 'captcha'

  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [active])

  const nowSeconds = now / 1_000
  const cooldownLeft = Math.max(
    0,
    Math.ceil((job.cooldown_until ?? 0) - nowSeconds),
  )
  const idleSeconds = Math.max(
    job.idle_seconds ?? 0,
    nowSeconds - job.last_activity_at,
  )
  const stalled =
    job.status === 'running' && cooldownLeft === 0 && idleSeconds > 20
  const heartState =
    stalled || idleSeconds > 20
      ? 'stall'
      : cooldownLeft > 0 || idleSeconds > 6
        ? 'slow'
        : 'live'
  const copy = statusCopy(job, nowSeconds, cooldownLeft)
  const progressValue =
    job.phase === 'collect' && active
      ? null
      : job.total > 0
        ? Math.round((job.checked / job.total) * 100)
        : 0
  const logTail = useMemo(() => job.log.slice(-6).join('\n'), [job.log])
  const captchaSeconds = job.captcha?.since
    ? Math.max(0, nowSeconds - job.captcha.since)
    : 0

  return (
    <Card
      className="status-card"
      tone={
        job.status === 'error'
          ? 'danger'
          : job.status === 'captcha'
            ? 'warning'
            : 'system'
      }
      aria-live="polite"
    >
      <CardContent>
        <div className="status-summary">
          <div>
            <p className="status-summary__title">{copy.title}</p>
            <p className="status-summary__meta">{copy.meta}</p>
          </div>
          <Badge
            dot
            tone={
              job.status === 'error'
                ? 'danger'
                : job.status === 'captcha'
                  ? 'warning'
                  : active
                    ? 'system'
                    : 'positive'
            }
          >
            {job.found} найдено
          </Badge>
        </div>

        <Progress
          containerClassName="status-card"
          value={progressValue}
          showValue={progressValue != null}
          label={
            job.phase === 'collect' && active
              ? 'Собираю каталог…'
              : 'Проверка карточек'
          }
          tone={job.status === 'captcha' ? 'warning' : 'system'}
        />

        {active ? (
          <div className="status-monitor">
            <span
              className="status-monitor__dot"
              data-state={heartState}
              aria-hidden="true"
            />
            <Activity size={14} aria-hidden="true" />
            <strong>{job.activity || 'Работаю…'}</strong>
            {job.active_requests ? (
              <span>· запросов: {job.active_requests}</span>
            ) : null}
            <span>· активность {formatActivityAge(idleSeconds)}</span>
            <span className="status-monitor__action">
              {job.status === 'running' ? (
                <Button
                  size="sm"
                  variant="quiet"
                  disabled={Boolean(job.pause_requested)}
                  loading={actionPending}
                  onClick={onPause}
                >
                  <Pause size={14} aria-hidden="true" />
                  {job.pause_requested
                    ? 'Встаю на паузу…'
                    : 'Пауза / пройти проверку'}
                </Button>
              ) : null}
            </span>
          </div>
        ) : null}

        {stalled ? (
          <div className="notice">
            <AlertTriangle size={17} aria-hidden="true" />
            <span>
              Уже {Math.round(idleSeconds)} с нет ответа. Сайт может отвечать
              медленно или показать незамеченную проверку. Поставьте поиск на
              паузу, откройте сайт и продолжите после проверки.
            </span>
          </div>
        ) : null}

        {cooldownLeft > 0 && job.status !== 'captcha' ? (
          <div className="notice">
            <Activity size={17} aria-hidden="true" />
            <span>
              Сайт попросил снизить темп. Жду {cooldownLeft} с и продолжу
              автоматически.
            </span>
          </div>
        ) : null}

        {job.status === 'captcha' ? (
          <div className="captcha-panel">
            <h3>
              <ShieldAlert size={18} aria-hidden="true" />
              {job.captcha?.reason === 'manual'
                ? ' Ручная пауза для проверки'
                : ' Сайт просит пройти проверку'}
            </h3>
            <p>
              Откройте POIZON в новой вкладке, пройдите капчу и вернитесь сюда.
              Задача продолжится с того же места.
            </p>
            <ol>
              <li>Убедитесь, что страница сайта открывается нормально.</li>
              <li>Нажмите «Продолжить» в этом окне.</li>
            </ol>
            <div className="ui-cluster">
              {job.captcha?.url ? (
                <a
                  className="ui-button ui-button--secondary ui-button--sm"
                  href={job.captcha.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Открыть проверку
                  <ExternalLink size={14} aria-hidden="true" />
                </a>
              ) : null}
              <Button size="sm" loading={actionPending} onClick={onResume}>
                <Play size={14} aria-hidden="true" />
                Продолжить
              </Button>
              <Button size="sm" variant="quiet" onClick={onCancel}>
                <Square size={13} aria-hidden="true" />
                Отменить
              </Button>
              <span className="ui-field__hint">
                На паузе {formatDuration(captchaSeconds)}
              </span>
            </div>
          </div>
        ) : null}

        {active && logTail ? <pre className="status-log">{logTail}</pre> : null}

        {job.stats.requests ||
        job.stats.cache_hits ||
        job.prefiltered ||
        job.stats.cooldowns ? (
          <div className="status-stats">
            <span>Запросов к сайту: {job.stats.requests ?? 0}</span>
            {job.stats.cache_hits ? (
              <span>Из кэша: {job.stats.cache_hits}</span>
            ) : null}
            {job.prefiltered ? (
              <span>Отсеяно по цене: {job.prefiltered}</span>
            ) : null}
            {job.stats.cooldowns ? (
              <span>Пауз из-за лимита: {job.stats.cooldowns}</span>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
