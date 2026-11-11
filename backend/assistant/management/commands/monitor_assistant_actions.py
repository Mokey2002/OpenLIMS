"""Run without Celery so a worker outage cannot disable queue-stall alerts."""
import signal
from threading import Event

from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, ProgrammingError, close_old_connections, connection
from assistant.job_health import scan_action_health


class Command(BaseCommand):
    help = "Check assistant jobs once, or continuously with --interval SECONDS."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=0)
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        interval, batch = options["interval"], options["batch_size"]
        if interval < 0 or batch < 1 or batch > 5000:
            raise CommandError("Use a nonnegative interval and a batch size between 1 and 5000.")
        stopped = Event()
        previous = {}
        if interval:
            for sig in (signal.SIGTERM, signal.SIGINT):
                previous[sig] = signal.signal(sig, lambda *_: stopped.set())
        cursor = None
        try:
            while not stopped.is_set():
                if not connection.in_atomic_block:
                    close_old_connections()
                try:
                    result = scan_action_health(limit=batch, after_id=cursor)
                    cursor = result["cursor"]
                    self.stdout.write(f"Assistant monitor: {result['checked']} checked; {result['delivered']} alerts delivered.")
                    self.stdout.flush()
                except (OperationalError, ProgrammingError):
                    if not interval:
                        raise CommandError("The assistant monitor database/schema is unavailable. Apply migrations and check connectivity.") from None
                    self.stderr.write("Assistant monitor database/schema unavailable; check migrations and connectivity. Will retry.")
                if not interval:
                    break
                stopped.wait(interval)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
