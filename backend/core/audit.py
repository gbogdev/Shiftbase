from .models import AuditLog


def record(actor, action, target=None, org=None, **detail):
    org = org or getattr(actor, "organization", None) or getattr(target, "organization", None)
    return AuditLog.objects.create(
        organization=org,
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        target_type=type(target).__name__ if target is not None else "",
        target_id=str(target.pk) if target is not None else "",
        detail=detail,
    )
