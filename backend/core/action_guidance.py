"""Explain existing permissions without granting or changing capabilities."""
from .permissions import application_roles


def serializer_actor_roles(serializer):
    request = serializer.context.get("request")
    user = request.user if request else None
    identifier = user.pk if user else None
    cached = serializer.context.get("_action_guidance_actor")
    if cached is None or cached[0] != identifier:
        cached = (identifier, set(application_roles(user)))
        serializer.context["_action_guidance_actor"] = cached
    return user, cached[1]


def guidance(allowed, code="ALLOWED", reason="", next_step="", href=None):
    return {"allowed": bool(allowed), "reason_code": code, "reason": reason, "next_step": next_step, "href": href}


def sample_modification_guidance(sample, user, roles, allowed):
    if allowed:
        return guidance(True)
    if not user or not user.is_authenticated:
        return guidance(False, "SIGN_IN", "Sign in to check your editing access.")
    if not roles.intersection({"admin", "tech"}):
        return guidance(False, "EDIT_ROLE_REQUIRED", "Editing samples requires a technician or administrator role.",
                        "Request the appropriate role or ask an administrator.", "/access-requests")
    if sample.project_id:
        return guidance(False, "PRIMARY_PROJECT_REQUIRED", "Your current access does not include editing this sample's primary project.",
                        "Join the primary project using its membership controls." if "admin" in roles else "Request membership in the sample's primary project.",
                        "/projects" if "admin" in roles else "/access-requests")
    return guidance(False, "SAMPLE_OWNER_REQUIRED", "Only the creator or an administrator can edit this unassigned sample.",
                    "Ask its creator or an administrator to make the change or assign a primary project.")


def work_update_guidance(work, user, roles, allowed):
    if allowed:
        return guidance(True)
    if not user or not user.is_authenticated:
        return guidance(False, "SIGN_IN", "Sign in to check your editing access.")
    if not roles.intersection({"admin", "tech"}):
        return guidance(False, "WORK_ROLE_REQUIRED", "Updating work requires a technician or administrator role.",
                        "Request the appropriate role or ask an administrator.", "/access-requests")
    if work.sample.project_id is None:
        return guidance(False, "WORK_OWNER_REQUIRED", "Reading this unassigned sample does not permit changing its work.",
                        "Ask the sample's creator or an administrator to manage this work.")
    return guidance(False, "WORK_ACCESS_REQUIRED", "Your current access does not permit updating this work.",
                    "Refresh the record and review your project membership.", "/me")
