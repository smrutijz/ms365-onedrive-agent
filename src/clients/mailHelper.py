import requests
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class MailClient:
    """Microsoft Graph API client covering core Outlook/Hotmail mail operations."""

    def __init__(self, access_token: str, timeout: int = 30):
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        })
        self.timeout = timeout

    # ── Folders ────────────────────────────────────────────────────────────────

    def list_mail_folders(self) -> List[Dict[str, Any]]:
        """List the user's mail folders (Inbox, Sent Items, Drafts, etc.)."""
        try:
            resp = self.session.get(f"{self.base_url}/me/mailFolders", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to list mail folders: {e}")
            return []

    def list_folder_messages(self, folder_id: str, top: int = 25) -> List[Dict[str, Any]]:
        """List messages in a specific mail folder."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/mailFolders/{folder_id}/messages",
                params={"$top": top, "$orderby": "receivedDateTime desc"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to list messages in folder '{folder_id}': {e}")
            return []

    # ── Messages ───────────────────────────────────────────────────────────────

    def list_messages(self, top: int = 25) -> List[Dict[str, Any]]:
        """List messages across the mailbox, most recent first."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/messages",
                params={"$top": top, "$orderby": "receivedDateTime desc"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to list messages: {e}")
            return []

    def get_message(self, message_id: str) -> Dict[str, Any]:
        """Get full metadata and body for a message by its ID."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/messages/{message_id}", timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get message '{message_id}': {e}")
            return {}

    def update_message(self, message_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update message properties, e.g. {'isRead': True}."""
        try:
            resp = self.session.patch(
                f"{self.base_url}/me/messages/{message_id}", json=fields, timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to update message '{message_id}': {e}")
            return None

    def delete_message(self, message_id: str) -> bool:
        """Permanently delete a message."""
        try:
            resp = self.session.delete(
                f"{self.base_url}/me/messages/{message_id}", timeout=self.timeout
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to delete message '{message_id}': {e}")
            return False

    def move_message(self, message_id: str, destination_folder_id: str) -> Optional[Dict[str, Any]]:
        """Move a message to a different mail folder."""
        try:
            resp = self.session.post(
                f"{self.base_url}/me/messages/{message_id}/move",
                json={"destinationId": destination_folder_id},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to move message '{message_id}': {e}")
            return None

    # ── Search ─────────────────────────────────────────────────────────────────

    def search_messages(self, query: str, top: int = 25) -> List[Dict[str, Any]]:
        """Search messages across the mailbox matching the query string."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/messages",
                params={"$search": f'"{query}"', "$top": top},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to search messages for '{query}': {e}")
            return []

    # ── Send / Reply / Forward ─────────────────────────────────────────────────

    @staticmethod
    def _recipients(addresses: Optional[List[str]]) -> List[Dict[str, Any]]:
        return [{"emailAddress": {"address": addr}} for addr in (addresses or [])]

    def send_mail(
        self,
        to: List[str],
        subject: str,
        body: str,
        body_type: str = "HTML",
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> bool:
        """Compose and send a new email."""
        message = {
            "subject": subject,
            "body": {"contentType": body_type, "content": body},
            "toRecipients": self._recipients(to),
            "ccRecipients": self._recipients(cc),
            "bccRecipients": self._recipients(bcc),
        }
        try:
            resp = self.session.post(
                f"{self.base_url}/me/sendMail",
                json={"message": message, "saveToSentItems": True},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to send mail: {e}")
            return False

    def reply_to_message(self, message_id: str, comment: str) -> bool:
        """Reply to the sender of a message."""
        try:
            resp = self.session.post(
                f"{self.base_url}/me/messages/{message_id}/reply",
                json={"comment": comment},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to reply to message '{message_id}': {e}")
            return False

    def reply_all_to_message(self, message_id: str, comment: str) -> bool:
        """Reply to all recipients of a message."""
        try:
            resp = self.session.post(
                f"{self.base_url}/me/messages/{message_id}/replyAll",
                json={"comment": comment},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to reply-all to message '{message_id}': {e}")
            return False

    def forward_message(self, message_id: str, to: List[str], comment: str = "") -> bool:
        """Forward a message to new recipients."""
        try:
            resp = self.session.post(
                f"{self.base_url}/me/messages/{message_id}/forward",
                json={"comment": comment, "toRecipients": self._recipients(to)},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to forward message '{message_id}': {e}")
            return False

    # ── Attachments ────────────────────────────────────────────────────────────

    def list_attachments(self, message_id: str) -> List[Dict[str, Any]]:
        """List attachments on a message."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/messages/{message_id}/attachments", timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to list attachments for message '{message_id}': {e}")
            return []

    def get_attachment(self, message_id: str, attachment_id: str) -> Dict[str, Any]:
        """Get a single attachment (includes base64 contentBytes for files)."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/messages/{message_id}/attachments/{attachment_id}",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get attachment '{attachment_id}': {e}")
            return {}


class DomainScopedMailClient(MailClient):
    """MailClient restricted to messages whose sender domain is in allowed_domains.

    List operations filter out non-matching senders.
    Single-message operations (get, update, delete, move, reply, forward,
    attachments) raise PermissionError when the sender domain is not allowed.
    """

    def __init__(self, access_token: str, allowed_domains: List[str], timeout: int = 30):
        super().__init__(access_token, timeout)
        self.allowed_domains = [d.lower().lstrip("@") for d in allowed_domains]

    def _sender_allowed(self, message: Dict[str, Any]) -> bool:
        address = message.get("from", {}).get("emailAddress", {}).get("address", "")
        if "@" not in address:
            return False
        domain = address.split("@", 1)[1].lower()
        return domain in self.allowed_domains

    def _check_message_domain(self, message_id: str) -> None:
        msg = super().get_message(message_id)
        if msg and not self._sender_allowed(msg):
            raise PermissionError(
                f"Access denied — sender domain is not in the allowed list: {self.allowed_domains}"
            )

    # ── Filtered list operations ───────────────────────────────────────────────

    def list_messages(self, top: int = 25) -> List[Dict[str, Any]]:
        return [m for m in super().list_messages(top) if self._sender_allowed(m)]

    def list_folder_messages(self, folder_id: str, top: int = 25) -> List[Dict[str, Any]]:
        return [m for m in super().list_folder_messages(folder_id, top) if self._sender_allowed(m)]

    def search_messages(self, query: str, top: int = 25) -> List[Dict[str, Any]]:
        return [m for m in super().search_messages(query, top) if self._sender_allowed(m)]

    # ── Domain-gated single-message operations ─────────────────────────────────

    def get_message(self, message_id: str) -> Dict[str, Any]:
        msg = super().get_message(message_id)
        if msg and not self._sender_allowed(msg):
            raise PermissionError(
                f"Access denied — sender domain is not in the allowed list: {self.allowed_domains}"
            )
        return msg

    def update_message(self, message_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self._check_message_domain(message_id)
        return super().update_message(message_id, fields)

    def delete_message(self, message_id: str) -> bool:
        self._check_message_domain(message_id)
        return super().delete_message(message_id)

    def move_message(self, message_id: str, destination_folder_id: str) -> Optional[Dict[str, Any]]:
        self._check_message_domain(message_id)
        return super().move_message(message_id, destination_folder_id)

    def reply_to_message(self, message_id: str, comment: str) -> bool:
        self._check_message_domain(message_id)
        return super().reply_to_message(message_id, comment)

    def reply_all_to_message(self, message_id: str, comment: str) -> bool:
        self._check_message_domain(message_id)
        return super().reply_all_to_message(message_id, comment)

    def forward_message(self, message_id: str, to: List[str], comment: str = "") -> bool:
        self._check_message_domain(message_id)
        return super().forward_message(message_id, to, comment)

    def list_attachments(self, message_id: str) -> List[Dict[str, Any]]:
        self._check_message_domain(message_id)
        return super().list_attachments(message_id)

    def get_attachment(self, message_id: str, attachment_id: str) -> Dict[str, Any]:
        self._check_message_domain(message_id)
        return super().get_attachment(message_id, attachment_id)
