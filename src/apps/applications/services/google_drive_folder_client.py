from pathlib import Path


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

    def _build_service(self):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            self.credentials_file,
            scopes=self.SCOPES,
        )
        return build("drive", "v3", credentials=credentials, cache_discovery=False)
