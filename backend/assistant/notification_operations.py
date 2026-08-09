import hashlib
import re
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from blast.models import BlastJob
from events.models import Event
from inventory.models import InventoryItem, InventoryLot
from notifications.models import Notification
from projects.models import Project
from results.models import Result
from samples.access import get_sample_access_queryset
from samples.models import Sample

from .models import NotificationDelivery, NotificationSubscription


class NotificationOperationError(ValueError):
    pass


def _is_admin(user):
    return user.is_superuser or user.groups.filter(name="admin").exists()


def _resolve_recipient(message, requesting_user):
    lower = message.lower()
    if "notify me" in lower or "tell me" in lower or "alert me" in lower:
        return requesting_user, None
    match = re.search(r"\bnotify\s+([A-Za-z0-9_.@+-]+)", message, re.IGNORECASE)
    if not match:
        return requesting_user, None
    value = match.group(1)
    candidates = list(
        get_user_model().objects.filter(
            Q(username__iexact=value) | Q(first_name__iexact=value) | Q(last_name__iexact=value)
        )[:3]
    )
    if not candidates:
        return None, f"User {value} was not found."
    if len(candidates) > 1:
        return None, f"User {value} is ambiguous; use the exact username."
    return candidates[0], None


def _target(message, user, context):
    lower = message.lower()
    blast_match = re.search(r"\bblast\s+job\s*#?\s*(\d+)", message, re.IGNORECASE)
    if blast_match:
        job = BlastJob.objects.select_related("project").filter(id=int(blast_match.group(1))).first()
        if not job:
            return None, "BLAST job was not found."
        if job.project_id and not (_is_admin(user) or job.project.members.filter(id=user.id).exists()):
            return None, "BLAST job is not accessible."
        return {"trigger": "BLAST_COMPLETED", "target_type": "BlastJob", "target_id": str(job.id), "project": job.project, "threshold": None}, None

    sample_match = re.search(r"\bsample\s+([A-Za-z0-9_-]+)", message, re.IGNORECASE)
    if sample_match and "approved" in lower:
        sample = get_sample_access_queryset(Sample.objects.select_related("project"), user).filter(sample_id__iexact=sample_match.group(1)).first()
        if not sample:
            return None, "Sample was not found or is not accessible."
        return {"trigger": "SAMPLE_APPROVED", "target_type": "Sample", "target_id": str(sample.id), "project": sample.project, "threshold": None}, None

    result_match = re.search(r"\b(?:result|review)\s*#?\s*(\d+)", message, re.IGNORECASE)
    result_id = int(result_match.group(1)) if result_match else context.get("result_id")
    if "qc" in lower and "pending" in lower and result_id:
        result = Result.objects.select_related("work_item__sample__project").filter(id=result_id).first()
        if not result or not get_sample_access_queryset(Sample.objects.filter(id=result.work_item.sample_id), user).exists():
            return None, "QC result was not found or is not accessible."
        return {"trigger": "QC_REMAINS_PENDING", "target_type": "Result", "target_id": str(result.id), "project": result.work_item.sample.project, "threshold": None}, None

    reagent_match = re.search(r"\breagent\s+([A-Za-z0-9_.-]+).*?below\s+([0-9]+(?:\.[0-9]+)?)", message, re.IGNORECASE)
    if reagent_match:
        item = InventoryItem.objects.filter(code__iexact=reagent_match.group(1)).first()
        if not item:
            return None, "Reagent was not found."
        try:
            threshold = Decimal(reagent_match.group(2))
        except InvalidOperation:
            return None, "The inventory threshold is invalid."
        return {"trigger": "INVENTORY_BELOW", "target_type": "InventoryItem", "target_id": str(item.id), "project": None, "threshold": threshold}, None

    return None, "I could not identify a supported notification trigger and target."


def _dedup_key(values):
    raw = "|".join(str(value or "") for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _list_subscriptions(user):
    subscriptions = NotificationSubscription.objects.filter(
        Q(created_by=user) | Q(recipient=user), active=True
    ).select_related("recipient", "project")[:100]
    lines = [f"Active notification subscriptions: {len(subscriptions)}."]
    for item in subscriptions:
        lines.append(
            f"- #{item.id}: {item.trigger} for {item.target_type} {item.target_id} -> {item.recipient.username} via {item.delivery_channel}, {item.frequency}, expires {item.expires_at.isoformat() if item.expires_at else 'never'}"
        )
    return {"answer": "\n".join(lines), "links": [], "skip_llm": True}


def _propose_cancel(message, user):
    match = re.search(r"\bcancel\s+(?:notification|subscription)\s*#?\s*(\d+)", message, re.IGNORECASE)
    if not match:
        return None
    subscription = NotificationSubscription.objects.filter(id=int(match.group(1)), active=True).filter(Q(created_by=user) | Q(recipient=user)).first()
    if not subscription:
        return {"answer": "That active subscription was not found or cannot be cancelled by you.", "links": [], "skip_llm": True}
    preview = {
        "title": "Proposed notification cancellation",
        "operation": "CANCEL_SUBSCRIPTION",
        "project": subscription.project.code if subscription.project else "No project",
        "records_affected": 1,
        "records": [{"id": subscription.id, "label": f"Subscription #{subscription.id}", "current": {"active": True, "trigger": subscription.trigger, "recipient": subscription.recipient.username}, "proposed": {"active": False}}],
        "current_values": {"active": True},
        "proposed_values": {"active": False},
    }
    return {
        "answer": f"Cancel notification subscription #{subscription.id}. Review and confirm.",
        "links": [],
        "skip_llm": True,
        "pending_action": {"type": "NOTIFICATION_MANAGEMENT", "summary": f"Cancel notification subscription #{subscription.id}", "payload": {"operation": "CANCEL", "subscription_id": subscription.id, "preview": preview}},
    }


def route_notification_operations(message, user, context=None):
    context = context or {}
    lower = str(message or "").lower()
    if "list" in lower and any(word in lower for word in ["notification", "subscription"]):
        return _list_subscriptions(user)
    cancelled = _propose_cancel(message, user)
    if cancelled:
        return cancelled
    if not any(word in lower for word in ["notify", "tell me", "alert"]):
        return None
    recipient, recipient_error = _resolve_recipient(message, user)
    if recipient_error:
        return {"answer": recipient_error, "links": [], "skip_llm": True}
    target, target_error = _target(message, user, context)
    if target_error:
        return {"answer": target_error, "links": [], "skip_llm": True}
    project = target["project"]
    if project and not (_is_admin(recipient) or project.members.filter(id=recipient.id).exists()):
        return {"answer": f"{recipient.username} does not have access to the target project.", "links": [], "skip_llm": True}

    channel = NotificationSubscription.CHANNEL_EMAIL if "email" in lower else NotificationSubscription.CHANNEL_IN_APP
    frequency = NotificationSubscription.FREQUENCY_DAILY if any(word in lower for word in ["daily", "summary"]) else NotificationSubscription.FREQUENCY_ONCE
    now = timezone.now()
    next_run = now
    if "tomorrow" in lower:
        next_run = timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=1), time(hour=9)))
    expires_at = now + timedelta(days=30)
    dedup = _dedup_key([target["trigger"], recipient.id, channel, frequency, project.id if project else None, target["target_type"], target["target_id"], target["threshold"]])
    duplicate = NotificationSubscription.objects.filter(deduplication_key=dedup, active=True).first()
    if duplicate:
        return {"answer": f"An identical active notification already exists as subscription #{duplicate.id}.", "links": [], "skip_llm": True}
    values = {
        "trigger": target["trigger"],
        "recipient": recipient.username,
        "delivery_channel": channel,
        "frequency": frequency,
        "expiration_date": expires_at.isoformat(),
        "project_scope": project.code if project else None,
        "target": f"{target['target_type']} {target['target_id']}",
        "threshold": str(target["threshold"]) if target["threshold"] is not None else None,
    }
    preview = {
        "title": "Proposed notification subscription",
        "operation": "CREATE_SUBSCRIPTION",
        "project": project.code if project else "No project",
        "records_affected": 1,
        "records": [{"id": target["target_id"], "label": values["target"], "current": {"subscription": None}, "proposed": values}],
        "current_values": {},
        "proposed_values": values,
    }
    return {
        "answer": "Review the trigger, recipient, delivery channel, frequency, expiration, and project scope before confirming.",
        "links": [],
        "skip_llm": True,
        "pending_action": {
            "type": "NOTIFICATION_MANAGEMENT",
            "summary": f"Notify {recipient.username} when {target['trigger'].lower().replace('_', ' ')}",
            "payload": {
                "operation": "CREATE",
                "trigger": target["trigger"],
                "recipient_id": recipient.id,
                "delivery_channel": channel,
                "frequency": frequency,
                "expires_at": expires_at.isoformat(),
                "next_run_at": next_run.isoformat(),
                "project_id": project.id if project else None,
                "target_type": target["target_type"],
                "target_id": target["target_id"],
                "threshold": str(target["threshold"]) if target["threshold"] is not None else None,
                "deduplication_key": dedup,
                "preview": preview,
            },
        },
    }


@transaction.atomic
def execute_notification_management(action):
    payload = action.payload or {}
    if payload.get("operation") == "CANCEL":
        subscription = NotificationSubscription.objects.select_for_update().filter(id=payload.get("subscription_id"), active=True).first()
        if not subscription or action.requested_by_id not in [subscription.created_by_id, subscription.recipient_id] and not _is_admin(action.requested_by):
            raise NotificationOperationError("Subscription can no longer be cancelled by this user.")
        subscription.active = False
        subscription.cancelled_at = timezone.now()
        subscription.save(update_fields=["active", "cancelled_at"])
        Event.objects.create(entity_type="NotificationSubscription", entity_id=str(subscription.id), action="NOTIFICATION_CANCELLED", actor=action.requested_by, payload={"assistant_action_id": str(action.id)})
        return {"operation": "CANCEL_SUBSCRIPTION", "succeeded_count": 1, "failed_count": 0, "subscription_id": subscription.id}

    recipient = get_user_model().objects.filter(id=payload.get("recipient_id"), is_active=True).first()
    if not recipient:
        raise NotificationOperationError("Recipient is no longer active.")
    project = Project.objects.filter(id=payload.get("project_id")).first() if payload.get("project_id") else None
    if project and not (_is_admin(recipient) or project.members.filter(id=recipient.id).exists()):
        raise NotificationOperationError("Recipient project access changed before confirmation.")
    try:
        subscription = NotificationSubscription.objects.create(
            trigger=payload["trigger"],
            recipient=recipient,
            delivery_channel=payload["delivery_channel"],
            frequency=payload["frequency"],
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            project=project,
            target_type=payload["target_type"],
            target_id=payload["target_id"],
            threshold=Decimal(payload["threshold"]) if payload.get("threshold") else None,
            deduplication_key=payload["deduplication_key"],
            next_run_at=datetime.fromisoformat(payload["next_run_at"]),
            created_by=action.requested_by,
        )
    except IntegrityError as exc:
        raise NotificationOperationError("An identical active notification already exists.") from exc
    Event.objects.create(entity_type="NotificationSubscription", entity_id=str(subscription.id), action="NOTIFICATION_SUBSCRIBED", actor=action.requested_by, payload={"trigger": subscription.trigger, "recipient": recipient.username, "channel": subscription.delivery_channel, "frequency": subscription.frequency, "project_id": subscription.project_id, "assistant_action_id": str(action.id)})
    return {"operation": "CREATE_SUBSCRIPTION", "succeeded_count": 1, "failed_count": 0, "subscription_id": subscription.id}


def _permission_still_allowed(subscription):
    if not subscription.recipient.is_active:
        return False
    if subscription.project_id and not (_is_admin(subscription.recipient) or subscription.project.members.filter(id=subscription.recipient_id).exists()):
        return False
    return True


def _trigger_state(subscription):
    if subscription.trigger == "BLAST_COMPLETED":
        job = BlastJob.objects.filter(id=subscription.target_id).first()
        return bool(job and job.status == "COMPLETED"), f"blast:{subscription.target_id}:completed", f"BLAST job #{subscription.target_id} finished."
    if subscription.trigger == "SAMPLE_APPROVED":
        exists = Event.objects.filter(entity_type="Sample", entity_id=subscription.target_id, action__in=["QC_APPROVED", "SAMPLE_APPROVED"]).exists()
        return exists, f"sample:{subscription.target_id}:approved", f"Sample #{subscription.target_id} was approved."
    if subscription.trigger == "QC_REMAINS_PENDING":
        result = Result.objects.filter(id=subscription.target_id).first()
        pending = bool(result and result.qc_status in [Result.QC_PENDING_REVIEW, Result.QC_REOPENED])
        return pending, f"qc:{subscription.target_id}:pending:{timezone.localdate().isoformat()}", f"QC result #{subscription.target_id} remains pending."
    if subscription.trigger == "INVENTORY_BELOW":
        item = InventoryItem.objects.filter(id=subscription.target_id).first()
        quantity = None
        if item:
            quantity = sum(
                (lot.available_quantity for lot in item.lots.filter(status=InventoryLot.STATUS_ACTIVE)),
                Decimal("0"),
            )
        fired = bool(quantity is not None and subscription.threshold is not None and quantity < subscription.threshold)
        return fired, f"inventory:{subscription.target_id}:below:{subscription.threshold}:{timezone.localdate().isoformat()}", f"{item.code if item else 'Inventory'} is below {subscription.threshold}; current quantity is {quantity}."
    return False, "unsupported", "Unsupported notification trigger."


@transaction.atomic
def dispatch_subscription(subscription, now=None):
    now = now or timezone.now()
    subscription = NotificationSubscription.objects.select_for_update().get(id=subscription.id)
    if not subscription.active or subscription.next_run_at > now or (subscription.expires_at and subscription.expires_at <= now):
        return None
    allowed = _permission_still_allowed(subscription)
    fired, event_key, message = _trigger_state(subscription)
    subscription.last_checked_at = now
    if not allowed:
        delivery, _ = NotificationDelivery.objects.get_or_create(subscription=subscription, event_key=f"permission:{now.date().isoformat()}", defaults={"status": NotificationDelivery.STATUS_SKIPPED, "permission_rechecked": True, "detail": {"reason": "permission denied at delivery"}})
        subscription.active = False
        subscription.save(update_fields=["last_checked_at", "active"])
        Event.objects.create(entity_type="NotificationSubscription", entity_id=str(subscription.id), action="NOTIFICATION_SKIPPED", actor=None, payload={"reason": "permission denied at delivery", "recipient_id": subscription.recipient_id})
        return delivery
    if not fired:
        subscription.next_run_at = now + (timedelta(days=1) if subscription.frequency == NotificationSubscription.FREQUENCY_DAILY else timedelta(minutes=5))
        subscription.save(update_fields=["last_checked_at", "next_run_at"])
        return None
    if subscription.delivery_channel == NotificationSubscription.CHANNEL_EMAIL:
        if not subscription.recipient.email:
            email_sent = False
        else:
            try:
                email_sent = bool(
                    send_mail(
                        "OpenLIMS alert",
                        message,
                        getattr(settings, "DEFAULT_FROM_EMAIL", "openlims@localhost"),
                        [subscription.recipient.email],
                        fail_silently=False,
                    )
                )
            except Exception:
                email_sent = False
        if not email_sent:
            failed_key = f"{event_key}:failed:{now:%Y%m%d%H%M}"
            delivery, _ = NotificationDelivery.objects.get_or_create(
                subscription=subscription,
                event_key=failed_key,
                defaults={
                    "status": NotificationDelivery.STATUS_FAILED,
                    "permission_rechecked": True,
                    "detail": {"reason": "email delivery failed"},
                },
            )
            subscription.next_run_at = now + timedelta(minutes=5)
            subscription.save(update_fields=["last_checked_at", "next_run_at"])
            Event.objects.create(
                entity_type="NotificationSubscription",
                entity_id=str(subscription.id),
                action="NOTIFICATION_FAILED",
                actor=None,
                payload={"recipient_id": subscription.recipient_id, "channel": subscription.delivery_channel},
            )
            return delivery

    delivery, created = NotificationDelivery.objects.get_or_create(subscription=subscription, event_key=event_key, defaults={"status": NotificationDelivery.STATUS_DELIVERED, "permission_rechecked": True, "detail": {"message": message}})
    if not created:
        return delivery
    if subscription.delivery_channel == NotificationSubscription.CHANNEL_IN_APP:
        Notification.objects.create(user=subscription.recipient, title="OpenLIMS alert", message=message, link="/notifications")
    Event.objects.create(entity_type="NotificationSubscription", entity_id=str(subscription.id), action="NOTIFICATION_DELIVERED", actor=None, payload={"recipient_id": subscription.recipient_id, "channel": subscription.delivery_channel, "event_key": event_key})
    if subscription.frequency == NotificationSubscription.FREQUENCY_DAILY:
        subscription.next_run_at = now + timedelta(days=1)
    else:
        subscription.active = False
    subscription.save(update_fields=["last_checked_at", "next_run_at", "active"])
    return delivery
