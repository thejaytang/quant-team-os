from __future__ import annotations

import asyncio
import logging
import os
import time

from activities import ACTIVITY_TYPES
from workflows import WORKFLOW_TYPES

TASK_QUEUE = "quant-team-os"

logging.basicConfig(
    level=os.getenv("WORKER_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("qto.worker")


def start_metrics_server() -> bool:
    try:
        from prometheus_client import Gauge, start_http_server
    except ImportError:
        return False

    port = int(os.getenv("WORKER_METRICS_PORT", "9002"))
    gauge = Gauge("qto_worker_up", "Quant Team OS worker process is running")
    gauge.set(1)
    start_http_server(port)
    return True


def configure_worker_observability() -> str:
    from app.services.observability import configure_otel

    return configure_otel()


def configured_activities():
    return ACTIVITY_TYPES


def configured_workflows():
    return WORKFLOW_TYPES


async def run_worker() -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    client = await Client.connect(address, namespace=namespace)
    worker = Worker(client, task_queue=TASK_QUEUE, workflows=configured_workflows(), activities=configured_activities())
    await worker.run()


def main() -> None:
    address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    otel_status = configure_worker_observability()
    metrics_started = start_metrics_server()
    logger.info("Temporal worker target: %s, task queue: %s", address, TASK_QUEUE)
    logger.info("worker otel: %s", otel_status)
    logger.info("worker metrics: %s", "enabled" if metrics_started else "disabled")
    if os.getenv("WORKER_ONCE") == "1":
        logger.info(
            "registered workflows: %d, activities: %d",
            len(configured_workflows()),
            len(configured_activities()),
        )
        return
    try:
        asyncio.run(run_worker())
    except ImportError as exc:
        logger.warning("temporalio unavailable, keeping worker container alive: %s", exc)
        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
