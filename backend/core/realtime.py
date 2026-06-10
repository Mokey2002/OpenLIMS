from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


JOB_UPDATES_GROUP = "job_updates"


def broadcast_job_update(payload):
    channel_layer = get_channel_layer()

    if channel_layer is None:
        return

    async_to_sync(channel_layer.group_send)(
        JOB_UPDATES_GROUP,
        {
            "type": "job.update",
            "payload": payload,
        },
    )


def broadcast_test_message():
    broadcast_job_update(
        {
            "type": "test_message",
            "message": "OpenLIMS real-time job updates are working.",
        }
    )
