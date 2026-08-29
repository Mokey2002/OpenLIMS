from django.http import JsonResponse

from settings_app.models import SystemSettings


FEATURE_PATH_PREFIXES = {
    "notebook": (
        "/api/notebooks/",
        "/api/experiment-templates/",
        "/api/experiments/",
        "/api/experiment-revisions/",
        "/api/experiment-comments/",
        "/api/v1/notebooks/",
        "/api/v1/experiment-templates/",
        "/api/v1/experiments/",
        "/api/v1/experiment-revisions/",
        "/api/v1/experiment-comments/",
    ),
    "registry": (
        "/api/registry-schemas/",
        "/api/registry-records/",
        "/api/registry-relationships/",
        "/api/v1/registry-schemas/",
        "/api/v1/registry-records/",
        "/api/v1/registry-relationships/",
    ),
}


class FeatureFlagAPIMiddleware:
    """Prevent disabled optional modules from being reached by direct API URLs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        feature = None
        for candidate, prefixes in FEATURE_PATH_PREFIXES.items():
            if any(path.startswith(prefix) for prefix in prefixes):
                feature = candidate
                break

        if feature:
            flags = SystemSettings.load().feature_flags
            if not flags.get(feature, False):
                return JsonResponse(
                    {
                        "detail": f"The {feature} module is disabled by a system feature flag.",
                        "feature": feature,
                    },
                    status=404,
                )

        return self.get_response(request)
