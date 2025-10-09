import frappe

def run_notifications(self, method):
        """Run notifications for this method"""
        if (
            (frappe.flags.in_import and frappe.flags.mute_emails)
            or frappe.flags.in_patch
            or frappe.flags.in_install
        ):
            return

        if self.flags.wa_notifications_executed is None:
            self.flags.wa_notifications_executed = []

        from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_notification.whatsapp_notification import whatsapp_evaluate_alert

        if self.flags.wa_notifications is None:

            def _get_notifications():
                """returns enabled notifications for the current doctype"""

                return frappe.get_all(
                    "WhatsApp Notification",
                    fields=["name", "doctype_event"],
                    filters={"disabled": 0, "reference_doctype": self.doctype},
                )

            self.flags.wa_notifications = frappe.cache().hget("wa_notifications", self.doctype, _get_notifications)

        if not self.flags.wa_notifications:
            return

        def _evaluate_alert(alert):
            if alert.name not in self.flags.wa_notifications_executed:
                whatsapp_evaluate_alert(self, alert.name, alert.doctype_event)
                self.flags.wa_notifications_executed.append(alert.name)

        event_map = {
            "on_update": "Save",
            "after_insert": "New",
            "on_submit": "Submit",
            "on_cancel": "Cancel",
        }

        if not self.flags.in_insert and not self.flags.in_delete:
            # value change is not applicable in insert
            event_map["on_change"] = "Value Change"

        for alert in self.flags.wa_notifications:
            frappe.log_error("test notification from whatsapp2" )
            event = event_map.get(method, None)
            if event and alert.doctype_event == event:
                _evaluate_alert(alert)
            