"""
Video meeting module (Google Meet–like).
- HTTP: create room, get room info, STUN/config.
- WebSocket: signaling for WebRTC (offer/answer/ICE), join/leave, chat, host mute.
No frontend; clients use WebRTC with this server as signaling only.
"""
import json
import uuid
import asyncio
import time
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models.MeetingRoomModel import MeetingRoom
from models.UsersModel import User
from routers.auth import get_current_user, SECRET_KEY, ALGORITHM
from pydantic import BaseModel
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError

router = APIRouter(prefix="/meetings", tags=["Meetings"])

# ---------- STUN configuration (for frontend RTCPeerConnection) ----------
# Default STUN servers; frontend can override. TURN can be added for strict NATs.
DEFAULT_STUN_SERVERS = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"},
]


# ---------- In-memory connection manager (room_id -> list of peers) ----------
class Peer:
    def __init__(self, ws: WebSocket, user_id: int, username: str, is_host: bool):
        self.ws = ws
        # Unique per-connection ID (multiple tabs/devices per user supported)
        self.peer_id = uuid.uuid4().hex
        self.user_id = user_id
        self.username = username
        self.is_host = is_host

    def to_info(self) -> dict:
        return {"peer_id": self.peer_id, "user_id": self.user_id, "username": self.username, "is_host": self.is_host}


class RoomState:
    def __init__(self, owner_user_id: int):
        self.owner_user_id = owner_user_id
        self.current_host_user_id: int = owner_user_id
        self.active_peers: List[Peer] = []
        self.waiting_peers: List[Peer] = []
        # user_id -> "active" | "waiting"
        self.user_status: Dict[int, str] = {}
        # user_id -> unix timestamp until admitted rejoin is preserved
        self.active_grace_until: Dict[int, float] = {}


# room_id (str) -> room state
_rooms: Dict[str, RoomState] = {}
_rooms_lock = asyncio.Lock()
ACTIVE_REJOIN_GRACE_SECONDS = 30


def _get_or_create_room_state(room_id: str, owner_user_id: int) -> RoomState:
    state = _rooms.get(room_id)
    if state is None:
        state = RoomState(owner_user_id=owner_user_id)
        _rooms[room_id] = state
    return state


def _remove_peer_from_list(peers: List[Peer], target: Peer) -> bool:
    try:
        peers.remove(target)
        return True
    except ValueError:
        return False


def _find_peer(peers: List[Peer], peer_id: str) -> Optional[Peer]:
    for p in peers:
        if p.peer_id == peer_id:
            return p
    return None


def _set_peer_host_flag(state: RoomState) -> None:
    for p in state.active_peers:
        p.is_host = p.user_id == state.current_host_user_id
    for p in state.waiting_peers:
        p.is_host = p.user_id == state.current_host_user_id


def _active_participants_payload(state: RoomState) -> List[dict]:
    return [p.to_info() for p in state.active_peers]


def _waiting_participants_payload(state: RoomState) -> List[dict]:
    return [p.to_info() for p in state.waiting_peers]


def _should_restore_active(state: RoomState, user_id: int) -> bool:
    if state.user_status.get(user_id) != "active":
        return False
    expiry = state.active_grace_until.get(user_id)
    return bool(expiry and expiry >= time.time())


def _clear_expired_grace(state: RoomState) -> None:
    now = time.time()
    expired = [uid for uid, until in state.active_grace_until.items() if until < now]
    for uid in expired:
        state.active_grace_until.pop(uid, None)
        if not any(p.user_id == uid for p in state.active_peers):
            state.user_status.pop(uid, None)


def _resolve_room(db: Session, raw_room_id: str) -> Optional[MeetingRoom]:
    """
    Resolve room by UUID room_id first, with numeric id fallback for clients
    that may still send database primary key in the URL.
    """
    room_key = (raw_room_id or "").strip()
    if not room_key:
        return None

    room = db.query(MeetingRoom).filter(MeetingRoom.room_id == room_key).first()
    if room:
        return room

    if room_key.isdigit():
        return db.query(MeetingRoom).filter(MeetingRoom.id == int(room_key)).first()
    return None


async def _add_peer(room_id: str, peer: Peer) -> None:
    # Kept for backward compatibility with older codepaths.
    async with _rooms_lock:
        state = _rooms.get(room_id)
        if state is None:
            return
        state.active_peers.append(peer)


async def _remove_peer(room_id: str, peer: Peer) -> None:
    async with _rooms_lock:
        state = _rooms.get(room_id)
        if state is None:
            return
        removed_active = _remove_peer_from_list(state.active_peers, peer)
        removed_waiting = _remove_peer_from_list(state.waiting_peers, peer)
        if removed_active:
            has_same_user_active = any(p.user_id == peer.user_id for p in state.active_peers)
            if not has_same_user_active:
                state.active_grace_until[peer.user_id] = time.time() + ACTIVE_REJOIN_GRACE_SECONDS
        if removed_waiting and not any(p.user_id == peer.user_id for p in state.waiting_peers):
            state.user_status[peer.user_id] = "waiting"
        _clear_expired_grace(state)
        if not state.active_peers and not state.waiting_peers:
            del _rooms[room_id]


async def _broadcast(room_id: str, message: dict, exclude_peer: Optional[Peer] = None) -> None:
    state = _rooms.get(room_id)
    if not state:
        return
    peers = state.active_peers
    dead = []
    for p in peers:
        if p is exclude_peer:
            continue
        try:
            await p.ws.send_json(message)
        except Exception:
            dead.append(p)
    for p in dead:
        await _remove_peer(room_id, p)


async def _send_to_peer(room_id: str, user_id: int, message: dict) -> bool:
    state = _rooms.get(room_id)
    if not state:
        return False
    peers = state.active_peers + state.waiting_peers
    for p in peers:
        if p.user_id == user_id:
            try:
                await p.ws.send_json(message)
                return True
            except Exception:
                return False
    return False


async def _send_to_peer_id(room_id: str, peer_id: str, message: dict) -> bool:
    state = _rooms.get(room_id)
    if not state:
        return False
    peers = state.active_peers + state.waiting_peers
    for p in peers:
        if p.peer_id == peer_id:
            try:
                await p.ws.send_json(message)
                return True
            except Exception:
                return False
    return False


async def _send_participant_list_to_active(room_id: str) -> None:
    state = _rooms.get(room_id)
    if not state:
        return
    payload = {
        "type": "participant_list",
        "participants": _active_participants_payload(state),
        "room_id": room_id,
    }
    dead = []
    for p in state.active_peers:
        try:
            await p.ws.send_json(payload)
        except Exception:
            dead.append(p)
    for p in dead:
        await _remove_peer(room_id, p)


async def _send_waiting_list_to_host(room_id: str) -> None:
    state = _rooms.get(room_id)
    if not state:
        return
    host_peers = [p for p in state.active_peers if p.user_id == state.current_host_user_id]
    payload = {
        "type": "waiting_participants",
        "room_id": room_id,
        "participants": _waiting_participants_payload(state),
    }
    for hp in host_peers:
        try:
            await hp.ws.send_json(payload)
        except Exception:
            await _remove_peer(room_id, hp)


async def _send_waiting_event_to_host(room_id: str, event_type: str, participant: Peer) -> None:
    state = _rooms.get(room_id)
    if not state:
        return
    host_peers = [p for p in state.active_peers if p.user_id == state.current_host_user_id]
    payload = {
        "type": event_type,
        "room_id": room_id,
        "participant": participant.to_info(),
    }
    for hp in host_peers:
        try:
            await hp.ws.send_json(payload)
        except Exception:
            await _remove_peer(room_id, hp)


async def _send_error(ws: WebSocket, code: str, message: str) -> None:
    try:
        await ws.send_json({"type": "error", "code": code, "message": message})
    except Exception:
        pass


def _get_user_from_token(token: str) -> Optional[User]:
    if not token:
        return None
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            return None
    except (ExpiredSignatureError, JWTError):
        return None
    db = SessionLocal()
    try:
        return db.query(User).filter(User.username == username, User.is_deleted == False).first()
    finally:
        db.close()


# ---------- HTTP: room creation & info ----------
class RoomCreate(BaseModel):
    title: Optional[str] = None


class RoomOut(BaseModel):
    room_id: str
    title: Optional[str] = None
    created_by_id: int
    created_at: Optional[str] = None


@router.post("/rooms", response_model=dict)
def create_room(
    body: Optional[RoomCreate] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a meeting room. Returns room_id for join link."""
    room_id = str(uuid.uuid4())
    title = body.title.strip() if (body and body.title) else None
    room = MeetingRoom(
        room_id=room_id,
        title=title,
        created_by_id=current_user.id,
        is_active=True,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return {
        "room_id": room_id,
        "title": room.title,
        "created_by_id": room.created_by_id,
        "created_at": room.created_at.isoformat() if room.created_at else None,
    }


@router.get("/rooms/{room_id}", response_model=dict)
def get_room(
    room_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get room info (for validation before join)."""
    room = _resolve_room(db, room_id)
    if not room or room.is_active is False:
        raise HTTPException(status_code=404, detail="Room not found")
    return {
        "room_id": room.room_id,
        "title": room.title,
        "created_by_id": room.created_by_id,
        "created_at": room.created_at.isoformat() if room.created_at else None,
    }


@router.get("/config")
def get_webrtc_config():
    """Return STUN (and optional TURN) config for frontend RTCPeerConnection."""
    return {
        "iceServers": DEFAULT_STUN_SERVERS,
        "iceTransportPolicy": "all",
    }


# ---------- WebSocket: signaling ----------
@router.websocket("/ws/{room_id}")
async def meeting_ws(websocket: WebSocket, room_id: str):
    """
    Signaling WebSocket for room_id.
    Query param: token (JWT) for auth.
    Messages (JSON): join (implicit on connect), offer, answer, ice_candidate, chat, leave, host_mute.
    """
    await websocket.accept()
    # Accept both token names used across different frontend builds.
    token = (
        websocket.query_params.get("token")
        or websocket.query_params.get("access_token")
    )
    user = _get_user_from_token(token) if token else None
    if not user:
        await _send_error(websocket, "UNAUTHORIZED", "Invalid or missing token")
        await websocket.close()
        return

    # Verify room exists in DB
    db = SessionLocal()
    try:
        room = _resolve_room(db, room_id)
        if not room or room.is_active is False:
            await _send_error(websocket, "ROOM_NOT_FOUND", "Room not found")
            await websocket.close()
            return
        owner_user_id = room.created_by_id
    finally:
        db.close()

    peer = Peer(websocket, user.id, user.username or "", False)
    peer_state = "waiting"
    async with _rooms_lock:
        state = _get_or_create_room_state(room_id, owner_user_id)
        _clear_expired_grace(state)

        if user.id == state.owner_user_id:
            state.current_host_user_id = user.id

        if user.id == state.current_host_user_id:
            peer_state = "active"
        elif _should_restore_active(state, user.id):
            peer_state = "active"

        if peer_state == "active":
            state.active_peers.append(peer)
            state.user_status[user.id] = "active"
            state.active_grace_until.pop(user.id, None)
        else:
            state.waiting_peers.append(peer)
            state.user_status[user.id] = "waiting"

        _set_peer_host_flag(state)
        peer.is_host = user.id == state.current_host_user_id

    try:
        if peer_state == "active":
            await websocket.send_json({
                "type": "admitted",
                "room_id": room_id,
                "peer_id": peer.peer_id,
                "user_id": user.id,
                "is_host": peer.is_host,
            })
            await _send_participant_list_to_active(room_id)
            await _broadcast(room_id, {
                "type": "user_joined",
                "room_id": room_id,
                "peer_id": peer.peer_id,
                "user_id": user.id,
                "username": peer.username,
                "is_host": peer.is_host,
            }, exclude_peer=peer)
            if peer.is_host:
                await _send_waiting_list_to_host(room_id)
        else:
            await websocket.send_json({
                "type": "join_pending",
                "room_id": room_id,
                "peer_id": peer.peer_id,
                "user_id": user.id,
                "username": peer.username,
                "is_host": False,
            })
            # Frontend compatibility alias
            await websocket.send_json({
                "type": "waiting_room",
                "room_id": room_id,
                "peer_id": peer.peer_id,
                "user_id": user.id,
            })
            await _send_waiting_event_to_host(room_id, "waiting_user_joined", peer)
            await _send_waiting_list_to_host(room_id)

        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(websocket, "INVALID_JSON", "Invalid JSON")
                continue

            msg_type = data.get("type")
            if not msg_type:
                continue

            state = _rooms.get(room_id)
            is_currently_active = bool(state and any(p is peer for p in state.active_peers))

            # waiting users cannot participate in media/chat until admitted.
            if not is_currently_active and msg_type in {
                "offer", "answer", "ice_candidate", "chat", "host_mute", "admit_participant", "reject_participant"
            }:
                await _send_error(websocket, "JOIN_PENDING", "You are still in waiting room")
                continue

            if msg_type == "join_request":
                # Idempotent status sync for clients that explicitly send join_request.
                if is_currently_active:
                    await websocket.send_json({
                        "type": "admitted",
                        "room_id": room_id,
                        "peer_id": peer.peer_id,
                        "user_id": user.id,
                        "is_host": peer.is_host,
                    })
                    await _send_participant_list_to_active(room_id)
                else:
                    await websocket.send_json({
                        "type": "join_pending",
                        "room_id": room_id,
                        "peer_id": peer.peer_id,
                        "user_id": user.id,
                        "username": peer.username,
                        "is_host": False,
                    })
                    await websocket.send_json({
                        "type": "waiting_room",
                        "room_id": room_id,
                        "peer_id": peer.peer_id,
                        "user_id": user.id,
                    })
                continue

            if msg_type == "offer":
                to_peer_id = data.get("to_peer_id")
                sdp = data.get("sdp")
                if to_peer_id is not None and sdp is not None:
                    target_peer_id = str(to_peer_id)
                    state = _rooms.get(room_id)
                    if not state or _find_peer(state.active_peers, target_peer_id) is None:
                        await _send_error(websocket, "PARTICIPANT_NOT_ACTIVE", "Target participant is not active")
                        continue
                    await _send_to_peer_id(room_id, target_peer_id, {
                        "type": "offer",
                        "from_peer_id": peer.peer_id,
                        "from_user_id": user.id,
                        "username": peer.username,
                        "sdp": sdp,
                    })

            elif msg_type == "answer":
                to_peer_id = data.get("to_peer_id")
                sdp = data.get("sdp")
                if to_peer_id is not None and sdp is not None:
                    target_peer_id = str(to_peer_id)
                    state = _rooms.get(room_id)
                    if not state or _find_peer(state.active_peers, target_peer_id) is None:
                        await _send_error(websocket, "PARTICIPANT_NOT_ACTIVE", "Target participant is not active")
                        continue
                    await _send_to_peer_id(room_id, target_peer_id, {
                        "type": "answer",
                        "from_peer_id": peer.peer_id,
                        "from_user_id": user.id,
                        "username": peer.username,
                        "sdp": sdp,
                    })

            elif msg_type == "ice_candidate":
                to_peer_id = data.get("to_peer_id")
                candidate = data.get("candidate")
                if to_peer_id is not None and candidate is not None:
                    target_peer_id = str(to_peer_id)
                    state = _rooms.get(room_id)
                    if not state or _find_peer(state.active_peers, target_peer_id) is None:
                        await _send_error(websocket, "PARTICIPANT_NOT_ACTIVE", "Target participant is not active")
                        continue
                    await _send_to_peer_id(room_id, target_peer_id, {
                        "type": "ice_candidate",
                        "from_peer_id": peer.peer_id,
                        "from_user_id": user.id,
                        "candidate": candidate,
                    })

            elif msg_type == "chat":
                message = data.get("message", "")
                await _broadcast(room_id, {
                    "type": "chat",
                    "room_id": room_id,
                    "from_peer_id": peer.peer_id,
                    "from_user_id": user.id,
                    "username": peer.username,
                    "message": message[:2000],
                }, exclude_peer=None)  # include sender so their UI can show it if needed

            elif msg_type == "leave":
                break

            elif msg_type == "host_mute":
                state = _rooms.get(room_id)
                if not state or user.id != state.current_host_user_id:
                    await _send_error(websocket, "NOT_HOST", "Only host can mute participants")
                    continue
                target_peer_id = data.get("target_peer_id")
                if target_peer_id is not None:
                    target_peer_id = str(target_peer_id)
                    if _find_peer(state.active_peers, target_peer_id) is None:
                        await _send_error(websocket, "PARTICIPANT_NOT_ACTIVE", "Target participant is not active")
                        continue
                    await _send_to_peer_id(room_id, target_peer_id, {
                        "type": "host_mute_request",
                    })

            elif msg_type == "admit_participant":
                target_peer_id = str(data.get("target_peer_id") or "")
                async with _rooms_lock:
                    state = _rooms.get(room_id)
                    if not state:
                        await _send_error(websocket, "ROOM_NOT_FOUND", "Room not found")
                        continue
                    if user.id != state.current_host_user_id:
                        await _send_error(websocket, "NOT_HOST", "Only host can admit participants")
                        continue
                    waiting_peer = _find_peer(state.waiting_peers, target_peer_id)
                    if waiting_peer is None:
                        if _find_peer(state.active_peers, target_peer_id):
                            await _send_error(websocket, "ALREADY_ADMITTED", "Participant is already admitted")
                        else:
                            await _send_error(websocket, "PARTICIPANT_NOT_WAITING", "Participant is not in waiting room")
                        continue
                    _remove_peer_from_list(state.waiting_peers, waiting_peer)
                    state.active_peers.append(waiting_peer)
                    state.user_status[waiting_peer.user_id] = "active"
                    state.active_grace_until.pop(waiting_peer.user_id, None)
                    _set_peer_host_flag(state)
                await _send_to_peer_id(room_id, waiting_peer.peer_id, {
                    "type": "admitted",
                    "room_id": room_id,
                    "peer_id": waiting_peer.peer_id,
                    "user_id": waiting_peer.user_id,
                    "is_host": waiting_peer.is_host,
                })
                await _send_participant_list_to_active(room_id)
                await _broadcast(room_id, {
                    "type": "user_joined",
                    "room_id": room_id,
                    "peer_id": waiting_peer.peer_id,
                    "user_id": waiting_peer.user_id,
                    "username": waiting_peer.username,
                    "is_host": waiting_peer.is_host,
                }, exclude_peer=waiting_peer)
                await _send_waiting_list_to_host(room_id)

            elif msg_type == "reject_participant":
                target_peer_id = str(data.get("target_peer_id") or "")
                reason = (data.get("reason") or "Host denied your join request").strip()
                async with _rooms_lock:
                    state = _rooms.get(room_id)
                    if not state:
                        await _send_error(websocket, "ROOM_NOT_FOUND", "Room not found")
                        continue
                    if user.id != state.current_host_user_id:
                        await _send_error(websocket, "NOT_HOST", "Only host can reject participants")
                        continue
                    waiting_peer = _find_peer(state.waiting_peers, target_peer_id)
                    if waiting_peer is None:
                        if _find_peer(state.active_peers, target_peer_id):
                            await _send_error(websocket, "ALREADY_ADMITTED", "Participant is already admitted")
                        else:
                            await _send_error(websocket, "PARTICIPANT_NOT_WAITING", "Participant is not in waiting room")
                        continue
                    _remove_peer_from_list(state.waiting_peers, waiting_peer)
                    if not any(p.user_id == waiting_peer.user_id for p in state.waiting_peers):
                        state.user_status.pop(waiting_peer.user_id, None)
                await _send_to_peer_id(room_id, waiting_peer.peer_id, {
                    "type": "rejected",
                    "room_id": room_id,
                    "reason": reason,
                })
                try:
                    await waiting_peer.ws.close()
                except Exception:
                    pass
                await _send_waiting_list_to_host(room_id)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        peer_was_active = False
        waiting_left_event = False
        host_changed = False
        async with _rooms_lock:
            state = _rooms.get(room_id)
            if state:
                peer_was_active = _remove_peer_from_list(state.active_peers, peer)
                if peer_was_active:
                    # preserve admitted state for short reconnect window.
                    if not any(p.user_id == peer.user_id for p in state.active_peers):
                        state.active_grace_until[peer.user_id] = time.time() + ACTIVE_REJOIN_GRACE_SECONDS
                else:
                    waiting_left_event = _remove_peer_from_list(state.waiting_peers, peer)
                # Host transfer: owner on reconnect preferred; otherwise oldest active peer.
                if peer.user_id == state.current_host_user_id and not any(p.user_id == peer.user_id for p in state.active_peers):
                    if state.active_peers:
                        state.current_host_user_id = state.active_peers[0].user_id
                        host_changed = True
                _set_peer_host_flag(state)
                _clear_expired_grace(state)
                if not state.active_peers and not state.waiting_peers:
                    del _rooms[room_id]

        if peer_was_active:
            await _broadcast(room_id, {
                "type": "user_left",
                "room_id": room_id,
                "peer_id": peer.peer_id,
                "user_id": user.id,
                "username": peer.username,
            }, exclude_peer=peer)
            await _send_participant_list_to_active(room_id)
            if host_changed:
                await _broadcast(room_id, {
                    "type": "host_changed",
                    "room_id": room_id,
                    "host_user_id": _rooms.get(room_id).current_host_user_id if _rooms.get(room_id) else None,
                }, exclude_peer=None)
                await _send_waiting_list_to_host(room_id)
        elif waiting_left_event:
            await _send_waiting_event_to_host(room_id, "waiting_user_left", peer)
            await _send_waiting_list_to_host(room_id)

        try:
            await websocket.close()
        except Exception:
            pass
