from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from assistant.models import AssistantChatRequest


class Command(BaseCommand):
    help = "Remove terminal assistant request state older than seven days; stop stale requests older than one hour."

    def handle(self, *args, **options):
        now = timezone.now()
        AssistantChatRequest.objects.filter(status="RUNNING", created_at__lt=now - timedelta(hours=1)).update(cancel_requested=True, status="CANCELLED", finished_at=now)
        count, _ = AssistantChatRequest.objects.exclude(status="RUNNING").filter(created_at__lt=now - timedelta(days=7)).delete()
        self.stdout.write(f"Removed {count} expired request records.")
