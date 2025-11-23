import logging
from src.article_queue import _load as _load_queue
from src.logging_setup import setup_logging


def run():
    setup_logging()
    logger = logging.getLogger("inspect_queue")

    queue = _load_queue()
    logger.info("inspect_queue: found %d items in queue", len(queue))

    print("\n=== QUEUE CONTENTS (Top is next to pop) ===\n")
    # Queue is LIFO, so the end of the list is the next item to pop.
    # We'll print from end to start to show "Next up" first.

    for i, item in enumerate(reversed(queue)):
        headline = item.get("headline") or item.get("title") or "No Title"
        url = item.get("url") or "No URL"
        date = item.get("date") or item.get("source_date") or "No Date"
        print(f"{i+1}. {headline}")
        print(f"   URL: {url}")
        print(f"   Date: {date}")
        print("-" * 40)


if __name__ == "__main__":
    run()
