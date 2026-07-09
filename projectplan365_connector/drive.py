"""Thin wrapper around the Google Drive v3 API, authenticated using the
refresh token stored on PP365 Settings."""

import io

import frappe
import httplib2
from google_auth_httplib2 import AuthorizedHttp
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

REQUEST_TIMEOUT = 30

from projectplan365_connector.projectplan365_connector.doctype.pp365_settings.pp365_settings import (
	SCOPES,
)

OAUTH_URL = "https://oauth2.googleapis.com/token"
XML_MIME = "text/xml"


def get_drive_service():
	settings = frappe.get_single("PP365 Settings")
	google_settings = frappe.get_cached_doc("Google Settings")

	credentials = Credentials(
		token=settings.get_access_token(),
		refresh_token=settings.get_password(fieldname="refresh_token", raise_exception=False),
		token_uri=OAUTH_URL,
		client_id=google_settings.client_id,
		client_secret=google_settings.get_password(fieldname="client_secret", raise_exception=False),
		scopes=[SCOPES],
	)
	http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=REQUEST_TIMEOUT))
	return build("drive", "v3", http=http, static_discovery=True)


def list_folder_files(service, folder_id: str) -> list[dict]:
	files = []
	page_token = None
	query = f"'{folder_id}' in parents and trashed = false and name contains '.xml'"
	while True:
		response = (
			service.files()
			.list(
				q=query,
				spaces="drive",
				fields="nextPageToken, files(id, name, modifiedTime)",
				pageToken=page_token,
			)
			.execute()
		)
		files.extend(response.get("files", []))
		page_token = response.get("nextPageToken")
		if not page_token:
			break
	return files


def download_file(service, file_id: str) -> bytes:
	request = service.files().get_media(fileId=file_id)
	buffer = io.BytesIO()
	downloader = MediaIoBaseDownload(buffer, request)
	done = False
	while not done:
		_, done = downloader.next_chunk()
	return buffer.getvalue()


def upload_or_update_file(
	service, folder_id: str, file_id: str | None, filename: str, content: bytes
) -> dict:
	media = MediaIoBaseUpload(io.BytesIO(content), mimetype=XML_MIME, resumable=False)

	if file_id:
		file = (
			service.files()
			.update(
				fileId=file_id,
				body={"mimeType": XML_MIME},
				media_body=media,
				fields="id, modifiedTime",
			)
			.execute()
		)
	else:
		metadata = {"name": filename, "parents": [folder_id], "mimeType": XML_MIME}
		file = (
			service.files()
			.create(body=metadata, media_body=media, fields="id, modifiedTime")
			.execute()
		)

	return file
