"""
Run event stream: generator.py (and query.py's background retrieval step)
publish events here; backend/api/query.py's GET /query/{run_id}/stream
consumes them and turns them into SSE.

Uses a Redis Stream (XADD/XREAD), not pub/sub, deliberately: pub/sub only
delivers to subscribers that are already connected when a message is
published, and POST /query returns run_id before the client has had a
chance to open the GET stream connection — with pub/sub, retrieval_start
(and possibly more) would be published and lost before anyone's
listening. A stream persists events, so a client connecting even a moment
late still replays everything from the beginning (last_id="0").
"""
import json
import logging

logger = logging.getLogger("neuroflow.generation.events")

STREAM_KEY_TEMPLATE = "run:{run_id}:events"
STREAM_TTL_SECONDS = 600  # cleanup window after a run finishes
DEFAULT_KEEPALIVE_INTERVAL_MS = 15_000  # task spec: keepalive every 15s
TERMINAL_EVENT_TYPES = {"done", "error"}


def _stream_key(run_id: str) -> str:
    return STREAM_KEY_TEMPLATE.format(run_id=run_id)


async def publish_event(redis_client, run_id: str, event: dict) -> None:
    key = _stream_key(run_id)
    await redis_client.xadd(key, {"data": json.dumps(event)}, maxlen=2000, approximate=True)
    if event.get("type") in TERMINAL_EVENT_TYPES:
        # Bound how long a finished run's event log sticks around in
        # Redis — without this, every run leaks a stream key forever.
        await redis_client.expire(key, STREAM_TTL_SECONDS)


async def consume_events(redis_client, run_id: str, keepalive_interval_ms: int = DEFAULT_KEEPALIVE_INTERVAL_MS):
    """Yields every event published for `run_id`, from the start of its
    stream. Yields a synthetic {"type": "keepalive"} event whenever
    `keepalive_interval_ms` passes with nothing new (task spec: prevent
    client-side connection timeout on long generations). Stops after
    yielding a "done" or "error" event.
    """
    key = _stream_key(run_id)
    last_id = "0"

    while True:
        response = await redis_client.xread({key: last_id}, block=keepalive_interval_ms, count=50)
        if not response:
            yield {"type": "keepalive"}
            continue

        for _stream_name, entries in response:
            for entry_id, fields in entries:
                last_id = entry_id
                try:
                    event = json.loads(fields["data"])
                except (KeyError, json.JSONDecodeError):
                    logger.warning("skipping malformed event on stream %s: %r", key, fields)
                    continue
                yield event
                if event.get("type") in TERMINAL_EVENT_TYPES:
                    return
