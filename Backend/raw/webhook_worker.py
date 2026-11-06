"""Run this process in production to retry failed/pending webhook deliveries.

Example: ``python -m raw.webhook_worker``
For a first deployment, run it beside Uvicorn.  Later this can be replaced by
a proper job queue such as Celery, RQ, or an infrastructure scheduler.
"""

import time

from .webhook import deliver_due_webhooks


if __name__ == "__main__":
    while True:
        deliver_due_webhooks()
        # Do not make the loop busy-spin while no retries are waiting.
        time.sleep(10)
