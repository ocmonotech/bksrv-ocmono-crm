"""
Helpers for activity logging. Set request.state.activity_description in create/update/delete
routes so the ActivityLogMiddleware records a specific description (e.g. what was updated).
"""
from fastapi import Request


def set_activity_description(request: Request, description: str) -> None:
    """Set a custom activity description for this request. Middleware will use it when writing ActivityLog."""
    if len(description) > 255:
        description = description[:252] + "..."
    request.state.activity_description = description


def describe_created(resource: str, identifier: str = None, detail: str = None) -> str:
    """Build description for create: e.g. 'Created assignment ASG-5' or 'Created lead: John'."""
    parts = [f"Created {resource}"]
    if identifier:
        parts.append(identifier)
    if detail:
        parts.append(f"- {detail}")
    return " ".join(parts)


def describe_updated(resource: str, identifier: str = None, details: str = None) -> str:
    """Build description for update: e.g. 'Updated assignment #5 - status → Completed'."""
    parts = [f"Updated {resource}"]
    if identifier:
        parts.append(identifier)
    if details:
        parts.append(f"- {details}")
    return " ".join(parts)


def describe_deleted(resource: str, identifier: str = None, detail: str = None) -> str:
    """Build description for delete: e.g. 'Deleted client Acme Corp'."""
    parts = [f"Deleted {resource}"]
    if identifier and detail:
        parts.append(f"{identifier} - {detail}")
    elif identifier or detail:
        parts.append(identifier or detail)
    return " ".join(parts)
