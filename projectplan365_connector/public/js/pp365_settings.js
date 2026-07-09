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
	},
});
