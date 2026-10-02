"""Read/write Google Sheets via service account (Sheets API) or public CSV export."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
SETTINGS_KEY = "app_sheets_service_account_json"


def extract_sheet_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    return match.group(1) if match else None


def extract_gid_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    match = re.search(r"[#&?]gid=([0-9]+)", url)
    return match.group(1) if match else None


def col_letter(index: int) -> str:
    """0-based column index to A1 letter."""
    n = index + 1
    result = ""
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def a1_range(sheet_name: str, start_col: int = 0, start_row: int = 1, end_col: Optional[int] = None, end_row: Optional[int] = None) -> str:
    quoted = f"'{sheet_name}'" if re.search(r"[^\w]", sheet_name or "") or not sheet_name else sheet_name
    start = f"{col_letter(start_col)}{start_row}"
    if end_col is None and end_row is None:
        return f"{quoted}!{start}"
    end_c = col_letter(end_col if end_col is not None else start_col)
    end_r = end_row if end_row is not None else start_row
    return f"{quoted}!{start}:{end_c}{end_r}"


def row_checksum(data: Dict[str, Any]) -> str:
    payload = json.dumps(data or {}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def parse_service_account_json(raw: str) -> Dict[str, Any]:
    if not raw or not str(raw).strip():
        raise ValueError("Service account JSON is empty")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Service account JSON is not valid JSON") from exc
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise ValueError("JSON must be a Google service account key (type=service_account)")
    if not info.get("client_email") or not info.get("private_key"):
        raise ValueError("Service account JSON is missing client_email or private_key")
    return info


def load_service_account_info(db=None) -> Optional[Dict[str, Any]]:
    env_json = os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON")
    if env_json:
        return parse_service_account_json(env_json)

    env_file = os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE")
    if env_file and os.path.isfile(env_file):
        with open(env_file, "r", encoding="utf-8") as fh:
            return parse_service_account_json(fh.read())

    if db is not None:
        from models.SettingsModel import Settings
        setting = db.query(Settings).filter(Settings.key == SETTINGS_KEY).first()
        if setting and setting.value:
            return parse_service_account_json(setting.value)
    return None


def service_account_email(db=None) -> Optional[str]:
    try:
        info = load_service_account_info(db)
        return (info or {}).get("client_email")
    except Exception:
        return None


def is_write_ready(db=None) -> bool:
    try:
        return load_service_account_info(db) is not None
    except Exception:
        return False


def _access_token(info: Dict[str, Any]) -> str:
    now = int(time.time())
    claims = {
        "iss": info["client_email"],
        "scope": SHEETS_SCOPE,
        "aud": TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    assertion = None
    try:
        from jose import jwt
        assertion = jwt.encode(claims, info["private_key"], algorithm="RS256")
    except Exception:
        assertion = None

    if not assertion:
        try:
            from google.oauth2 import service_account
            import google.auth.transport.requests
            creds = service_account.Credentials.from_service_account_info(info, scopes=[SHEETS_SCOPE])
            creds.refresh(google.auth.transport.requests.Request())
            return creds.token
        except Exception as exc:
            raise RuntimeError(
                "Could not sign Google service account JWT. Install cryptography or google-auth."
            ) from exc

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"Google auth failed: {response.text[:400]}")
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("Google auth did not return an access token")
    return token


def _api(method: str, url: str, token: str, **kwargs) -> Any:
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    if not response.ok:
        detail = response.text[:800]
        raise RuntimeError(f"Google Sheets API error ({response.status_code}): {detail}")
    if response.content:
        return response.json()
    return {}


def list_worksheet_titles(sheet_id: str, db=None) -> List[str]:
    info = load_service_account_info(db)
    if not info:
        return []
    token = _access_token(info)
    data = _api(
        "GET",
        f"{SHEETS_API}/{sheet_id}",
        token,
        params={"fields": "sheets.properties.title"},
    )
    titles = []
    for sheet in data.get("sheets") or []:
        title = (sheet.get("properties") or {}).get("title")
        if title:
            titles.append(title)
    return titles


def _values_to_records(values: List[List[Any]]) -> Tuple[List[str], List[Dict[str, str]]]:
    if not values:
        return [], []
    headers = [str(h).strip() if h is not None else "" for h in values[0]]
    used = {}
    unique_headers = []
    for idx, header in enumerate(headers):
        name = header or f"Column {col_letter(idx)}"
        if name in used:
            used[name] += 1
            name = f"{name} ({used[name]})"
        else:
            used[name] = 1
        unique_headers.append(name)
    records = []
    for row in values[1:]:
        record = {}
        empty = True
        for idx, header in enumerate(unique_headers):
            value = ""
            if idx < len(row) and row[idx] is not None:
                value = str(row[idx])
            record[header] = value
            if value.strip():
                empty = False
        if empty:
            continue
        records.append(record)
    return unique_headers, records


def fetch_sheet_records(sheet_id: str, sheet_name: str, gid: Optional[str] = None, db=None) -> Tuple[List[str], List[Dict[str, str]], bool]:
    """
    Returns (headers, records, via_api).
    Prefers Sheets API when credentials exist so private sheets work.
    Falls back to public CSV export.
    """
    info = None
    try:
        info = load_service_account_info(db)
    except Exception:
        info = None

    if info:
        token = _access_token(info)
        quoted = quote(f"'{sheet_name}'" if sheet_name else "Sheet1", safe="")
        data = _api(
            "GET",
            f"{SHEETS_API}/{sheet_id}/values/{quoted}",
            token,
            params={"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "FORMATTED_STRING"},
        )
        headers, records = _values_to_records(data.get("values") or [])
        return headers, records, True

    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
    if sheet_name:
        csv_url += f"&sheet={quote(sheet_name)}"
    elif gid:
        csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

    response = requests.get(csv_url, timeout=30)
    response.raise_for_status()
    reader = csv.reader(io.StringIO(response.text))
    values = list(reader)
    headers, records = _values_to_records(values)
    return headers, records, False


def update_sheet_row(sheet_id: str, sheet_name: str, row_number: int, headers: List[str], values: Dict[str, Any], db=None) -> None:
    info = load_service_account_info(db)
    if not info:
        raise RuntimeError(
            "Google write is not configured. Add a service account JSON and share the sheet as Editor."
        )
    token = _access_token(info)
    row_values = ["" if values.get(h) is None else str(values.get(h)) for h in headers]
    end_col = max(len(headers) - 1, 0)
    range_a1 = a1_range(sheet_name, 0, row_number, end_col, row_number)
    encoded = quote(range_a1, safe="")
    _api(
        "PUT",
        f"{SHEETS_API}/{sheet_id}/values/{encoded}",
        token,
        params={"valueInputOption": "USER_ENTERED"},
        json={"range": range_a1, "majorDimension": "ROWS", "values": [row_values]},
    )


def append_sheet_row(sheet_id: str, sheet_name: str, headers: List[str], values: Dict[str, Any], db=None) -> int:
    info = load_service_account_info(db)
    if not info:
        raise RuntimeError(
            "Google write is not configured. Add a service account JSON and share the sheet as Editor."
        )
    token = _access_token(info)
    row_values = ["" if values.get(h) is None else str(values.get(h)) for h in headers]
    quoted_tab = f"'{sheet_name}'" if re.search(r"[^\w]", sheet_name or "") else sheet_name
    encoded = quote(quoted_tab, safe="")
    data = _api(
        "POST",
        f"{SHEETS_API}/{sheet_id}/values/{encoded}:append",
        token,
        params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
        json={"values": [row_values]},
    )
    updated_range = ((data.get("updates") or {}).get("updatedRange")) or ""
    match = re.search(r"!([A-Za-z]+)(\d+)", updated_range)
    if match:
        return int(match.group(2))
    return 0
