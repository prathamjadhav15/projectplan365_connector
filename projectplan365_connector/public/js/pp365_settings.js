frappe.ui.form.on("PP365 Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Connect to Google Drive"), () => {
			frappe.call({
				method: "projectplan365_connector.projectplan365_connector.doctype.pp365_settings.pp365_settings.authorize_access",
				args: { reauthorize: 1 },
				callback: (r) => {
					if (r.message && r.message.url) {
						window.location.href = r.message.url;
					}
				},
			});
		});

		if (frm.doc.authorized) {
			frm.dashboard.set_headline_alert(
				`<div class="row"><div class="col-xs-12"><span class="indicator green">${__(
					"Connected to Google Drive"
				)}</span></div></div>`
			);
		}

		const token_field = {
			fieldname: "token",
			fieldtype: "Small Text",
			label: __("Microsoft Graph Access Token"),
			description: __("Access tokens are long (1000+ characters) — the Password field type caps at 140 characters, so this uses Small Text instead."),
			reqd: 1,
		};

		frm.add_custom_button(__("Update Planner Bucket"), () => {
			frappe.prompt(
				[
					token_field,
					{
						fieldname: "bucket_id",
						fieldtype: "Data",
						label: __("Bucket ID"),
						reqd: 1,
					},
					{
						fieldname: "new_name",
						fieldtype: "Data",
						label: __("New Bucket Name"),
						reqd: 1,
					},
				],
				(values) => {
					frappe.call({
						method: "projectplan365_connector.planner.update_bucket",
						args: {
							token: values.token,
							bucket_id: values.bucket_id,
							new_name: values.new_name,
						},
						freeze: true,
						freeze_message: __("Updating bucket..."),
						callback: () => {
							frappe.show_alert({ message: __("Bucket updated successfully"), indicator: "green" });
						},
					});
				},
				__("Update Planner Bucket"),
				__("Update")
			);
		});

		frm.add_custom_button(__("Update Planner Task"), () => {
			frappe.prompt(
				[
					token_field,
					{
						fieldname: "task_id",
						fieldtype: "Data",
						label: __("Task ID"),
						reqd: 1,
					},
					{
						fieldname: "updates",
						fieldtype: "Code",
						options: "JSON",
						label: __("Updates (JSON)"),
						default: '{\n\t"percentComplete": 100\n}',
						reqd: 1,
					},
				],
				(values) => {
					frappe.call({
						method: "projectplan365_connector.planner.patch_task",
						args: {
							token: values.token,
							task_id: values.task_id,
							updates: values.updates,
						},
						freeze: true,
						freeze_message: __("Updating task..."),
						callback: () => {
							frappe.show_alert({ message: __("Task updated successfully"), indicator: "green" });
						},
					});
				},
				__("Update Planner Task"),
				__("Update")
			);
		});
	},
});
