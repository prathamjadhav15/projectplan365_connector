"""Microsoft Planner bucket operations via Microsoft Graph."""

import frappe
import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


@frappe.whitelist()
def update_bucket(token: str, bucket_id: str, new_name: str):
	"""Rename a Microsoft Planner bucket.

	Fetches the bucket's current @odata.etag first since Planner requires
	a fresh If-Match header on every write, then PATCHes the name.
	"""
	headers = {"Authorization": f"Bearer {token}"}

	get_resp = requests.get(f"{GRAPH_BASE}/planner/buckets/{bucket_id}", headers=headers, timeout=15)
	get_resp.raise_for_status()
	etag = get_resp.json()["@odata.etag"]

	patch_headers = {
		"Authorization": f"Bearer {token}",
		"If-Match": etag,
		"Content-Type": "application/json",
	}
	patch_resp = requests.patch(
		f"{GRAPH_BASE}/planner/buckets/{bucket_id}",
		headers=patch_headers,
		json={"name": new_name},
		timeout=15,
	)

	if patch_resp.status_code == 204:
		return {"success": True}

	frappe.throw(f"Error {patch_resp.status_code}: {patch_resp.text}")
