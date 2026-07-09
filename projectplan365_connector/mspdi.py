"""Build and parse Microsoft Project Data Interchange (MSPDI) XML for
syncing ERPNext Project/Task records with ProjectPlan365 Online.
"""

import re
from xml.etree import ElementTree as ET

import frappe
from frappe.utils import cint, cstr, get_datetime

NS = "http://schemas.microsoft.com/project"
ET.register_namespace("", NS)


def _tag(name):
	return f"{{{NS}}}{name}"


def _duration_to_iso(days):
	"""ERPNext Task.duration is a day count. MSPDI wants an ISO-8601-ish duration."""
	hours = cint(days) * 8
	return f"PT{hours}H0M0S"


def _iso_to_days(duration):
	if not duration:
		return 0
	match = re.search(r"PT(\d+)H", duration)
	hours = int(match.group(1)) if match else 0
	return max(1, hours // 8)


def _dt(value):
	if not value:
		return ""
	return get_datetime(value).strftime("%Y-%m-%dT%H:%M:%S")


def _outline_level(task_name, task_by_name, cache):
	if task_name in cache:
		return cache[task_name]
	parent = task_by_name.get(task_name).get("parent_task")
	level = 1 if not parent else 1 + _outline_level(parent, task_by_name, cache)
	cache[task_name] = level
	return level


def _next_uid(existing_uids):
	used = {cint(u) for u in existing_uids if u}
	uid = 1
	while uid in used:
		uid += 1
	return uid


def build_project_xml(project_name: str) -> bytes:
	"""Generate MSPDI XML for a Project and all of its Tasks.

	Assigns a stable custom_pp365_uid to any Task that doesn't have one yet
	(persisted back to the DB) so re-exports/re-imports round-trip cleanly.
	"""
	project = frappe.get_doc("Project", project_name)
	tasks = frappe.get_all(
		"Task",
		filters={"project": project_name},
		fields=[
			"name",
			"subject",
			"parent_task",
			"is_group",
			"is_milestone",
			"exp_start_date",
			"exp_end_date",
			"duration",
			"progress",
			"custom_pp365_uid",
		],
		order_by="lft asc",
	)
	task_by_name = {t.name: t for t in tasks}

	existing_uids = [t.custom_pp365_uid for t in tasks]
	for t in tasks:
		if not t.custom_pp365_uid:
			uid = _next_uid(existing_uids)
			existing_uids.append(uid)
			t.custom_pp365_uid = cstr(uid)
			frappe.db.set_value("Task", t.name, "custom_pp365_uid", t.custom_pp365_uid)

	depends_on = frappe.get_all(
		"Task Depends On", filters={"parent": ["in", list(task_by_name)]}, fields=["parent", "task"]
	)
	predecessors = {}
	for row in depends_on:
		predecessors.setdefault(row.parent, []).append(row.task)

	outline_cache = {}

	root = ET.Element(_tag("Project"))
	ET.SubElement(root, _tag("Name")).text = project.project_name or project.name
	if project.expected_start_date:
		ET.SubElement(root, _tag("StartDate")).text = _dt(project.expected_start_date)
	if project.expected_end_date:
		ET.SubElement(root, _tag("FinishDate")).text = _dt(project.expected_end_date)

	tasks_el = ET.SubElement(root, _tag("Tasks"))
	for idx, t in enumerate(tasks, start=1):
		task_el = ET.SubElement(tasks_el, _tag("Task"))
		ET.SubElement(task_el, _tag("UID")).text = cstr(t.custom_pp365_uid)
		ET.SubElement(task_el, _tag("ID")).text = cstr(idx)
		ET.SubElement(task_el, _tag("Name")).text = t.subject or t.name
		ET.SubElement(task_el, _tag("OutlineLevel")).text = cstr(
			_outline_level(t.name, task_by_name, outline_cache)
		)
		if t.exp_start_date:
			ET.SubElement(task_el, _tag("Start")).text = _dt(t.exp_start_date)
		if t.exp_end_date:
			ET.SubElement(task_el, _tag("Finish")).text = _dt(t.exp_end_date)
		ET.SubElement(task_el, _tag("Duration")).text = _duration_to_iso(t.duration)
		ET.SubElement(task_el, _tag("PercentComplete")).text = cstr(cint(t.progress))
		ET.SubElement(task_el, _tag("Milestone")).text = "1" if t.is_milestone else "0"
		ET.SubElement(task_el, _tag("Summary")).text = "1" if t.is_group else "0"

		for dep_task in predecessors.get(t.name, []):
			dep = task_by_name.get(dep_task)
			if not dep or not dep.custom_pp365_uid:
				continue
			link_el = ET.SubElement(task_el, _tag("PredecessorLink"))
			ET.SubElement(link_el, _tag("PredecessorUID")).text = cstr(dep.custom_pp365_uid)
			ET.SubElement(link_el, _tag("Type")).text = "1"

	return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")


def parse_project_xml(xml_bytes: bytes) -> dict:
	"""Parse MSPDI XML into a plain dict: project fields + ordered task list."""
	root = ET.fromstring(xml_bytes)

	def find(el, name):
		found = el.find(_tag(name))
		return found.text if found is not None else None

	project_name = find(root, "Name")
	tasks = []
	tasks_el = root.find(_tag("Tasks"))
	if tasks_el is not None:
		for task_el in tasks_el.findall(_tag("Task")):
			predecessor_uids = [
				find(link, "PredecessorUID") for link in task_el.findall(_tag("PredecessorLink"))
			]
			tasks.append(
				{
					"uid": find(task_el, "UID"),
					"name": find(task_el, "Name"),
					"outline_level": cint(find(task_el, "OutlineLevel")) or 1,
					"start": find(task_el, "Start"),
					"finish": find(task_el, "Finish"),
					"duration_days": _iso_to_days(find(task_el, "Duration")),
					"percent_complete": cint(find(task_el, "PercentComplete")),
					"milestone": find(task_el, "Milestone") == "1",
					"summary": find(task_el, "Summary") == "1",
					"predecessor_uids": [u for u in predecessor_uids if u],
				}
			)

	return {
		"project_name": project_name,
		"start_date": find(root, "StartDate"),
		"finish_date": find(root, "FinishDate"),
		"tasks": tasks,
	}


def apply_import(parsed: dict, project: str | None = None) -> str:
	"""Upsert an ERPNext Project + Tasks from a parsed MSPDI structure.

	Matches existing Tasks by custom_pp365_uid so repeated inbound syncs
	update in place instead of duplicating.
	"""
	if project:
		project_doc = frappe.get_doc("Project", project)
	else:
		project_doc = frappe.new_doc("Project")
		project_doc.project_name = parsed.get("project_name") or "ProjectPlan365 Import"
		project_doc.company = frappe.db.get_single_value(
			"Global Defaults", "default_company"
		) or frappe.db.get_value("Company", {}, "name")

	if parsed.get("start_date"):
		project_doc.expected_start_date = get_datetime(parsed["start_date"]).date()
	if parsed.get("finish_date"):
		project_doc.expected_end_date = get_datetime(parsed["finish_date"]).date()
	project_doc.save(ignore_permissions=True)

	existing_tasks = frappe.get_all(
		"Task", filters={"project": project_doc.name}, fields=["name", "custom_pp365_uid"]
	)
	task_by_uid = {t.custom_pp365_uid: t.name for t in existing_tasks if t.custom_pp365_uid}

	# outline_level -> most recently created Task name at that level, used to resolve parent_task
	last_at_level = {}
	uid_to_task_name = dict(task_by_uid)

	for row in parsed["tasks"]:
		parent_task = last_at_level.get(row["outline_level"] - 1)

		task_name = task_by_uid.get(row["uid"])
		task_doc = frappe.get_doc("Task", task_name) if task_name else frappe.new_doc("Task")
		task_doc.project = project_doc.name
		task_doc.subject = row["name"]
		task_doc.parent_task = parent_task
		task_doc.is_group = 1 if row["summary"] else 0
		task_doc.is_milestone = 1 if row["milestone"] else 0
		task_doc.progress = row["percent_complete"]
		task_doc.duration = row["duration_days"]
		if row.get("start"):
			task_doc.exp_start_date = get_datetime(row["start"])
		if row.get("finish"):
			task_doc.exp_end_date = get_datetime(row["finish"])
		task_doc.custom_pp365_uid = row["uid"]
		task_doc.save(ignore_permissions=True)

		uid_to_task_name[row["uid"]] = task_doc.name
		last_at_level[row["outline_level"]] = task_doc.name

	for row in parsed["tasks"]:
		if not row["predecessor_uids"]:
			continue
		task_doc = frappe.get_doc("Task", uid_to_task_name[row["uid"]])
		wanted = {uid_to_task_name[u] for u in row["predecessor_uids"] if u in uid_to_task_name}
		current = {d.task for d in task_doc.depends_on}
		if wanted != current:
			task_doc.set("depends_on", [])
			for dep_name in wanted:
				task_doc.append("depends_on", {"task": dep_name})
			task_doc.save(ignore_permissions=True)

	return project_doc.name
