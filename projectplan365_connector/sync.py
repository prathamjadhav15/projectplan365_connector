"""Scheduled bidirectional sync between ERPNext Projects/Tasks and the
shared Google Drive folder that ProjectPlan365 Online reads/writes."""

import hashlib

import frappe
from frappe.utils import cint, now_datetime, time_diff_in_seconds

from projectplan365_connector import drive, mspdi


def _log(project, direction, status, drive_file_id=None, error=None):
	frappe.get_doc(
		{
			"doctype": "PP365 Sync Log",
			"project": project,
			"direction": direction,
			"status": status,
			"drive_file_id": drive_file_id,
			"error": error,
		}
	).insert(ignore_permissions=True)


def _hash(content: bytes) -> str:
	return hashlib.sha256(content).hexdigest()


def sync_all():
	settings = frappe.get_single("PP365 Settings")
	if not settings.enable or not settings.authorized or not settings.drive_folder_id:
		return

	interval_seconds = cint(settings.poll_frequency or 15) * 60
	if settings.last_run_on and time_diff_in_seconds(now_datetime(), settings.last_run_on) < interval_seconds:
		return

	frappe.db.set_value("PP365 Settings", None, "last_run_on", now_datetime())
	frappe.db.commit()

	service = drive.get_drive_service()
	folder_id = settings.drive_folder_id

	_sync_outbound(service, folder_id)
	_sync_inbound(service, folder_id)


def _sync_outbound(service, folder_id):
	projects = frappe.get_all(
		"Project",
		fields=["name", "project_name", "custom_pp365_drive_file_id", "custom_pp365_last_synced_hash"],
	)
	for p in projects:
		try:
			xml_bytes = mspdi.build_project_xml(p.name)
			content_hash = _hash(xml_bytes)
			if content_hash == p.custom_pp365_last_synced_hash:
				continue

			filename = f"{p.project_name or p.name}.xml"
			file = drive.upload_or_update_file(
				service, folder_id, p.custom_pp365_drive_file_id, filename, xml_bytes
			)

			frappe.db.set_value(
				"Project",
				p.name,
				{
					"custom_pp365_drive_file_id": file["id"],
					"custom_pp365_last_synced_hash": content_hash,
					"custom_pp365_last_synced_on": now_datetime(),
				},
			)
			_log(p.name, "Outbound", "Success", drive_file_id=file["id"])
		except Exception:
			frappe.db.rollback()
			_log(p.name, "Outbound", "Failed", error=frappe.get_traceback())
		finally:
			frappe.db.commit()


def _sync_inbound(service, folder_id):
	files = drive.list_folder_files(service, folder_id)
	projects_by_file_id = {
		p.custom_pp365_drive_file_id: p.name
		for p in frappe.get_all(
			"Project", filters={"custom_pp365_drive_file_id": ["is", "set"]}, fields=["name", "custom_pp365_drive_file_id"]
		)
	}
	synced_hashes = {
		p.name: p.custom_pp365_last_synced_hash
		for p in frappe.get_all("Project", fields=["name", "custom_pp365_last_synced_hash"])
	}

	for f in files:
		project_name = projects_by_file_id.get(f["id"])
		try:
			content = drive.download_file(service, f["id"])
			content_hash = _hash(content)

			if project_name and content_hash == synced_hashes.get(project_name):
				continue  # unchanged since our last sync (including our own last export)

			parsed = mspdi.parse_project_xml(content)
			result_project = mspdi.apply_import(parsed, project=project_name)

			frappe.db.set_value(
				"Project",
				result_project,
				{
					"custom_pp365_drive_file_id": f["id"],
					"custom_pp365_last_synced_hash": content_hash,
					"custom_pp365_last_synced_on": now_datetime(),
				},
			)
			_log(result_project, "Inbound", "Success", drive_file_id=f["id"])
		except Exception:
			frappe.db.rollback()
			_log(project_name, "Inbound", "Failed", drive_file_id=f["id"], error=frappe.get_traceback())
		finally:
			frappe.db.commit()
