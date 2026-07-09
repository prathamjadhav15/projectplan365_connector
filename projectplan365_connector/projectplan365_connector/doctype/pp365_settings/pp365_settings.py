# Copyright (c) 2026, ANP Corp and contributors
# For license information, please see license.txt

import frappe
import requests
from frappe import _
from frappe.integrations.google_oauth import GoogleOAuth
from frappe.model.document import Document
from frappe.utils import get_request_site_address

SCOPES = "https://www.googleapis.com/auth/drive"


class PP365Settings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		authorized: DF.Check
		drive_folder_id: DF.Data | None
		enable: DF.Check
		last_run_on: DF.Datetime | None
		poll_frequency: DF.Literal["15", "30", "60"]
		refresh_token: DF.Password | None
	# end: auto-generated types

	def get_access_token(self):
		if not self.refresh_token:
			frappe.throw(
				_("Click on {0} to authorize Google Drive access.").format(
					frappe.bold(_("Connect to Google Drive"))
				)
			)

		google_settings = frappe.get_cached_doc("Google Settings")
		data = {
			"client_id": google_settings.client_id,
			"client_secret": google_settings.get_password(fieldname="client_secret", raise_exception=False),
			"refresh_token": self.get_password(fieldname="refresh_token", raise_exception=False),
			"grant_type": "refresh_token",
			"scope": SCOPES,
		}

		try:
			r = requests.post(GoogleOAuth.OAUTH_URL, data=data, timeout=15).json()
		except requests.exceptions.RequestException:
			frappe.throw(
				_("Something went wrong refreshing the Google Drive access token. Re-authorize via {0}.").format(
					frappe.bold(_("Connect to Google Drive"))
				)
			)

		return r.get("access_token")


def _redirect_uri():
	return (
		f"{get_request_site_address(full_address=True)}"
		f"?cmd={google_callback.__module__}.{google_callback.__qualname__}"
	)


@frappe.whitelist()
def authorize_access(reauthorize: bool = False):
	"""Kick off (or complete) the Google OAuth flow for PP365 Settings."""
	frappe.only_for("System Manager")

	settings = frappe.get_single("PP365 Settings")
	google_settings = frappe.get_cached_doc("Google Settings")

	if not google_settings.enable or not google_settings.client_id or not google_settings.client_secret:
		frappe.throw(_("Enable Google API and set Client Id/Secret in Google Settings first."))

	redirect_uri = _redirect_uri()
	authorization_code = frappe.cache.hget("pp365_settings", "authorization_code")

	if not authorization_code or reauthorize:
		frappe.cache.hset("pp365_settings", "in_progress", 1)
		return {
			"url": (
				"https://accounts.google.com/o/oauth2/v2/auth?"
				f"access_type=offline&response_type=code&prompt=consent&client_id={google_settings.client_id}"
				f"&include_granted_scopes=true&scope={SCOPES}&redirect_uri={redirect_uri}"
			)
		}

	data = {
		"code": authorization_code,
		"client_id": google_settings.client_id,
		"client_secret": google_settings.get_password(fieldname="client_secret", raise_exception=False),
		"redirect_uri": redirect_uri,
		"grant_type": "authorization_code",
	}

	try:
		r = requests.post(GoogleOAuth.OAUTH_URL, data=data, timeout=15).json()
	except Exception as e:
		frappe.throw(str(e))

	if "refresh_token" in r:
		settings.refresh_token = r["refresh_token"]
		settings.authorized = 1
		settings.save()
		frappe.db.commit()  # GET requests aren't auto-committed; this write must persist explicitly
	else:
		frappe.throw(
			_("Google did not return a refresh token: {0}").format(r.get("error_description") or r)
		)

	frappe.cache.hdel("pp365_settings", "authorization_code")

	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = "/app/pp365-settings"

	frappe.msgprint(_("ProjectPlan365 has been connected to Google Drive."), indicator="green")


@frappe.whitelist()
def google_callback(code: str | None = None):
	"""Authorization code is sent here by Google as per the redirect URI."""
	frappe.cache.hset("pp365_settings", "authorization_code", code)
	authorize_access()
