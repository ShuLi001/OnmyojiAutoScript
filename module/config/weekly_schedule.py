from datetime import datetime, time, timedelta


WeeklyRunTimes = tuple[tuple[int, time], ...]
RETRY_WINDOW = timedelta(hours=1)


def next_weekly_run(
    run_times: WeeklyRunTimes,
    now: datetime,
    *,
    retry_delay: timedelta | None = None,
    skip_today: bool = False,
) -> datetime:
    """Find the next configured time or a retry within the current window."""
    candidates = []
    for weekday, run_time in run_times:
        days = (weekday - now.weekday()) % 7
        start = datetime.combine(now.date() + timedelta(days=days), run_time)
        if days == 0 and (skip_today or start <= now):
            retry = now + retry_delay if retry_delay else None
            if (not skip_today and retry is not None
                    and now < retry < start + RETRY_WINDOW and retry.date() == start.date()):
                candidates.append(retry)
                continue
            start += timedelta(weeks=1)
        candidates.append(start)
    return min(candidates)


def resolve_weekly_run(run_times: WeeklyRunTimes, scheduled: datetime, now: datetime) -> datetime:
    """Roll a stale or closed-day timestamp forward before it enters the queue."""
    if scheduled.date() >= now.date():
        if any(day == scheduled.weekday() for day, _ in run_times):
            return scheduled
        return next_weekly_run(run_times, scheduled)

    # An old timestamp can still run if today's configured window is underway.
    today_starts = [
        datetime.combine(now.date(), run_time)
        for day, run_time in run_times
        if day == now.weekday()
    ]
    active = [start for start in today_starts if start <= now < start + RETRY_WINDOW]
    return min(active) if active else next_weekly_run(run_times, now)
