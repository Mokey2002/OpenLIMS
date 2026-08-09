import os
import shutil
from datetime import timedelta
from pathlib import Path

from celery import current_app
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from alignments.models import AlignmentJob
from blast.models import BlastJob
from imports.models import ImportJob


def _check_database():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return "available"
    except Exception:
        return "unavailable"


def _check_redis():
    try:
        key = "openlims:monitoring:probe"
        cache.set(key, "ok", timeout=10)
        return "available" if cache.get(key) == "ok" else "unavailable"
    except Exception:
        return "unavailable"


def _worker_status():
    try:
        inspector = current_app.control.inspect(timeout=0.75)
        pings = inspector.ping() or {}
        active = inspector.active() or {}
        reserved = inspector.reserved() or {}
        queue_depth = sum(len(items or []) for items in reserved.values())
        active_count = sum(len(items or []) for items in active.values())
        return {
            "availability": "available" if pings else "unavailable",
            "workers": len(pings),
            "queue_depth": queue_depth,
            "active_tasks": active_count,
        }
    except Exception:
        return {
            "availability": "unavailable",
            "workers": 0,
            "queue_depth": None,
            "active_tasks": None,
        }


def _job_failures():
    now = timezone.now()
    stuck_before = now - timedelta(hours=1)
    recent_since = now - timedelta(days=7)
    try:
        return {
            "imports": {
                "recent_failed": ImportJob.objects.filter(status="FAILED", created_at__gte=recent_since).count(),
                "stuck": ImportJob.objects.filter(status__in=["RUNNING", "PROCESSING"], created_at__lt=stuck_before).count(),
                "link": "/imports?status=FAILED",
            },
            "blast": {
                "recent_failed": BlastJob.objects.filter(status="FAILED", updated_at__gte=recent_since).count(),
                "stuck": BlastJob.objects.filter(status="RUNNING", updated_at__lt=stuck_before).count(),
                "link": "/blast?status=FAILED",
            },
            "alignments": {
                "recent_failed": AlignmentJob.objects.filter(status="FAILED", updated_at__gte=recent_since).count(),
                "stuck": AlignmentJob.objects.filter(status="RUNNING", updated_at__lt=stuck_before).count(),
                "link": "/alignments?status=FAILED",
            },
        }
    except Exception:
        return {
            "imports": {"recent_failed": None, "stuck": None, "link": "/imports"},
            "blast": {"recent_failed": None, "stuck": None, "link": "/blast"},
            "alignments": {"recent_failed": None, "stuck": None, "link": "/alignments"},
        }


def _storage_status():
    try:
        usage = shutil.disk_usage(settings.MEDIA_ROOT)
        used_percent = round((usage.used / usage.total) * 100, 1) if usage.total else 0
        return {
            "status": "warning" if used_percent >= 85 else "ok",
            "used_percent": used_percent,
            "free_bytes": usage.free,
            "link": "/system-status?check=storage",
        }
    except Exception:
        return {
            "status": "unknown",
            "used_percent": None,
            "free_bytes": None,
            "link": "/system-status?check=storage",
        }


def _backup_status():
    directory = Path(os.getenv("OPENLIMS_BACKUP_DIR", str(settings.BASE_DIR / "backups")))
    try:
        backups = [path for path in directory.glob("*") if path.is_file()]
        if not backups:
            return {"status": "missing", "latest_age_hours": None, "link": "/system-status?check=backups"}
        latest = max(backups, key=lambda path: path.stat().st_mtime)
        age_hours = round((timezone.now().timestamp() - latest.stat().st_mtime) / 3600, 1)
        return {"status": "stale" if age_hours > 24 else "ok", "latest_age_hours": age_hours, "link": "/system-status?check=backups"}
    except Exception:
        return {"status": "unknown", "latest_age_hours": None, "link": "/system-status?check=backups"}


def build_admin_monitoring_status():
    database = _check_database()
    redis = _check_redis()
    workers = _worker_status()
    jobs = _job_failures()
    storage = _storage_status()
    backup = _backup_status()
    warnings = []
    checks = [
        (database != "available", "Database connectivity failed", "/system-status?check=database"),
        (redis != "available", "Redis is unavailable", "/system-status?check=redis"),
        (workers["availability"] != "available", "No Celery worker responded", "/system-status?check=workers"),
        (storage["status"] == "warning", "Storage use is above 85%", storage["link"]),
        (backup["status"] in ["missing", "stale", "unknown"], f"Backup status is {backup['status']}", backup["link"]),
    ]
    for key, values in jobs.items():
        if values["recent_failed"] or values["stuck"]:
            warnings.append({"code": f"{key.upper()}_TASKS", "message": f"{key.title()} has {values['recent_failed']} recent failure(s) and {values['stuck']} stuck task(s)", "diagnostic_url": values["link"]})
    for failed, message, link in checks:
        if failed:
            warnings.append({"code": message.upper().replace(" ", "_")[:48], "message": message, "diagnostic_url": link})
    return {
        "status": "degraded" if warnings else "ok",
        "read_only": True,
        "api_health": "available",
        "database_connectivity": database,
        "redis_availability": redis,
        "worker_availability": workers["availability"],
        "worker_count": workers["workers"],
        "queue_depth": workers["queue_depth"],
        "active_tasks": workers["active_tasks"],
        "failed_or_stuck_tasks": jobs,
        "storage": storage,
        "backup": backup,
        "warnings": warnings,
        "generated_at": timezone.now().isoformat(),
    }


def route_system_monitoring(message, user, context=None):
    del context
    lower = str(message or "").lower()
    if not any(phrase in lower for phrase in ["system status", "system monitoring", "api health", "worker availability", "queue depth"]):
        return None
    if not (user.is_superuser or user.groups.filter(name="admin").exists()):
        return {
            "answer": "System monitoring details are available only to authorized administrators.",
            "links": [],
            "skip_llm": True,
        }
    status = build_admin_monitoring_status()
    jobs = status["failed_or_stuck_tasks"]
    lines = [
        f"OpenLIMS system status: {status['status']}",
        f"API health: {status['api_health']}",
        f"Database connectivity: {status['database_connectivity']}",
        f"Redis availability: {status['redis_availability']}",
        f"Worker availability: {status['worker_availability']} ({status['worker_count']} worker(s))",
        f"Queue depth: {status['queue_depth'] if status['queue_depth'] is not None else 'unknown'}",
        f"Active tasks: {status['active_tasks'] if status['active_tasks'] is not None else 'unknown'}",
        f"Recent import failures/stuck: {jobs['imports']['recent_failed']}/{jobs['imports']['stuck']}",
        f"Recent BLAST failures/stuck: {jobs['blast']['recent_failed']}/{jobs['blast']['stuck']}",
        f"Recent alignment failures/stuck: {jobs['alignments']['recent_failed']}/{jobs['alignments']['stuck']}",
        f"Storage: {status['storage']['status']} ({status['storage']['used_percent']}% used)",
        f"Backup: {status['backup']['status']}",
        "Monitoring is read-only; no repair action was executed.",
    ]
    return {
        "answer": "\n".join(lines),
        "links": [{"label": warning["message"], "url": warning["diagnostic_url"]} for warning in status["warnings"]],
        "monitoring": status,
        "skip_llm": True,
    }
