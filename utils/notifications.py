import anyio
from typing import Dict, List, Set, Optional
from fastapi import WebSocket
from models.NotificationModel import Notification


class NotificationConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, Set[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        conns = self.active_connections.get(user_id)
        if not conns:
            return
        conns.discard(websocket)
        if not conns:
            self.active_connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, payload: dict):
        conns = list(self.active_connections.get(user_id, set()))
        if not conns:
            return
        stale: List[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(user_id, ws)


notification_manager = NotificationConnectionManager()


def serialize_notification(n: Notification) -> dict:
    return {
        "id": n.id,
        "user_id": n.user_id,
        "message": n.message,
        "type": n.type,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "is_read": bool(n.is_read),
        "target_url": n.target_url,
        "entity_id": n.entity_id,
    }


def create_notification(
    db,
    user_id: int,
    message: str,
    *,
    notif_type: Optional[str] = None,
    target_url: Optional[str] = None,
    entity_id: Optional[int] = None,
) -> Notification:
    notif = Notification(
        user_id=user_id,
        message=message[:500],
        type=(notif_type or "general")[:50],
        is_read=False,
        target_url=(target_url or None),
        entity_id=entity_id,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    payload = serialize_notification(notif)
    payload["event"] = "notification_created"
    try:
        anyio.from_thread.run(notification_manager.send_to_user, user_id, payload)
    except Exception:
        # If websocket context is unavailable, keep DB write successful.
        pass
    return notif
