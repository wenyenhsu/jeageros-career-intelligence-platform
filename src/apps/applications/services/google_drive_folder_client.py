from pathlib import Path
from urllib.parse import urlparse


class GoogleDriveFolderClient:
    FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
    SCOPES = ("https://www.googleapis.com/auth/drive",)

    def __init__(self, credentials_file="", parent_folder_id=""):
        self.credentials_file = (credentials_file or "").strip()
        self.parent_folder_id = (parent_folder_id or "").strip()

    def is_configured(self):
        return bool(
            self.credentials_file
            and self.parent_folder_id
            and Path(self.credentials_file).is_file()
        )

    def create_folder(self, name):
        if not self.is_configured():
            return ""
        created = (
            self._build_service()
            .files()
            .create(
                body={
                    "name": name,
                    "mimeType": self.FOLDER_MIME_TYPE,
                    "parents": [self.parent_folder_id],
                },
                fields="id, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        folder_id = created.get("id") or ""
        return created.get("webViewLink") or (
            f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else ""
        )

    def delete_folder(self, url):
        folder_id = self.folder_id_from_url(url)
        if not folder_id or not self.is_configured():
            return False
        self._build_service().files().update(
            fileId=folder_id,
            body={"trashed": True},
            supportsAllDrives=True,
        ).execute()
        return True

    @staticmethod
    def folder_id_from_url(url):
        parsed = urlparse(str(url or "").strip())
        host = parsed.netloc.casefold()
        if host.startswith("www."):
            host = host[4:]
        if host != "drive.google.com":
            return ""
        parts = [part for part in parsed.path.split("/") if part]
        if "folders" not in parts:
            return ""
        index = parts.index("folders")
        if index + 1 >= len(parts):
            return ""
        return parts[index + 1]

    def _build_service(self):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            self.credentials_file,
            scopes=self.SCOPES,
        )
        return build("drive", "v3", credentials=credentials, cache_discovery=False)
