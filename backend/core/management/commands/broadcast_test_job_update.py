from django.core.management.base import BaseCommand

from core.realtime import broadcast_test_message


class Command(BaseCommand):
    help = "Broadcast a test WebSocket job update."

    def handle(self, *args, **options):
        broadcast_test_message()
        self.stdout.write(
            self.style.SUCCESS("Broadcasted test WebSocket job update.")
        )
