"""Bound failed credential attempts while reserving concurrent checks atomically."""
from contextlib import contextmanager

from fastapi import HTTPException


@contextmanager
def limited_attempts(state, lock, limits, now, *, seconds=300, status_code=429,
                     detail='Muitas tentativas. Aguarde 5 minutos.'):
    """Count failures and in-flight checks, releasing successful reservations.

    Keys supplied by the caller include database realm, account type and origin.
    A success releases only its own slot, so it cannot erase concurrent failures.
    These counters are process-local; multi-worker deployments need a shared
    limiter with the same key and reservation semantics.
    """
    with lock:
        for key in [key for key, (_, until) in state.items() if until <= now]:
            del state[key]
        if any(state.get(key, (0, 0))[0] >= maximum for key, maximum in limits):
            raise HTTPException(status_code, detail, headers={'Retry-After': str(seconds)})
        reservations = []
        for key, _ in limits:
            count, until = state.get(key, (0, now + seconds))
            state[key] = (count + 1, until)
            reservations.append((key, until))
    failed = False
    try:
        yield
    except HTTPException as exc:
        failed = exc.status_code in (400, 401, 404)
        raise
    finally:
        if not failed:
            with lock:
                for key, until in reservations:
                    current = state.get(key)
                    if current is None or current[1] != until:
                        continue
                    if current[0] > 1:
                        state[key] = (current[0] - 1, until)
                    else:
                        del state[key]
