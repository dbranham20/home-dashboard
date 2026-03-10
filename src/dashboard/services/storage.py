# services/storage.py
from typing import Dict, List, Optional

class MemoryStore:
    """
    Dev-only in-memory store. One process only. Wipes on restart.
    """
    def __init__(self):
        self._tokens_by_user: Dict[str, List[str]] = {}
        self._cursor_by_token: Dict[str, str] = {}
        self._item_to_token: Dict[str, str] = {}

    # Access tokens
    def add_access_token(self, user_id: str, access_token: str) -> None:
        self._tokens_by_user.setdefault(user_id, []).append(access_token)

    def get_access_tokens(self, user_id: str) -> List[str]:
        return self._tokens_by_user.get(user_id, [])

    def remove_access_token(self, user_id: str, access_token: str) -> None:
        if user_id in self._tokens_by_user:
            self._tokens_by_user[user_id] = [t for t in self._tokens_by_user[user_id] if t != access_token]
        self._cursor_by_token.pop(access_token, None)

    # Cursor per access token (transactions sync)
    def get_cursor(self, access_token: str) -> Optional[str]:
        return self._cursor_by_token.get(access_token)

    def set_cursor(self, access_token: str, cursor: str) -> None:
        self._cursor_by_token[access_token] = cursor

    # Map item_id -> access_token (for webhooks)
    def upsert_item_map(self, item_id: str, access_token: str) -> None:
        self._item_to_token[item_id] = access_token

    def token_from_item(self, item_id: str) -> Optional[str]:
        return self._item_to_token.get(item_id)

STORE = MemoryStore()
