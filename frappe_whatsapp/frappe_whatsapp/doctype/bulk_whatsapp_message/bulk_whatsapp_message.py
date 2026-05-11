# Bulk WhatsApp Messaging for Frappe WhatsApp
# bulk_whatsapp_messaging.py

import frappe
from frappe import _
import json
import time
from frappe.utils import cint
from frappe.model.document import Document
from frappe.model.naming import make_autoname

BATCH_SIZE = 200
THROTTLE_DELAY = 0.03  # 30ms


class BulkWhatsAppMessage(Document):
    def autoname(self):
        self.name = make_autoname("BULK-WA-.YYYY.-.#####")

    def validate(self):
        self.validate_recipients()

    def validate_recipients(self):
        if not self.recipients and not self.recipient_list:
            frappe.throw(_("At least one recipient or a recipient list is required"))

        if self.recipient_type == 'Recipient List' and self.recipient_list:
            count = frappe.db.count(
                "WhatsApp Recipient",
                {"parent": self.recipient_list}
            )
            if count == 0:
                frappe.throw(_("Selected recipient list has no recipients"))
            self.recipient_count = count

        elif self.recipients:
            self.recipient_count = len(self.recipients)

    def on_submit(self):
        self.db_set({
            "status": "Queued",
            "sent_count": 0
        })
        self.queue_batches()

    def queue_batches(self):
        recipients = self.get_all_recipients()

        for i in range(0, len(recipients), BATCH_SIZE):
            batch = recipients[i:i + BATCH_SIZE]

            frappe.enqueue_doc(
                self.doctype,
                self.name,
                "process_batch",
                queue="long",
                timeout=600,
                recipients=batch
            )

    def get_all_recipients(self):
        if self.recipient_type == 'Recipient List':
            return frappe.get_all(
                "WhatsApp Recipient",
                filters={"parent": self.recipient_list},
                fields=[
                    "customer",
                    "mobile_number",
                    "recipient_data"
                ]
            )
        else:
            return self.recipients

    def process_batch(self, recipients):
        success = 0
        failed = 0

        for r in recipients:
            try:
                self.create_message_record(r)
                success += 1
            except Exception:
                frappe.log_error(                    
                    "Bulk WhatsApp Batch Error",
                    frappe.get_traceback()
                )
                failed += 1

            time.sleep(THROTTLE_DELAY)

        frappe.db.sql("""
            UPDATE `tabBulk WhatsApp Message`
            SET sent_count = sent_count + %s
            WHERE name = %s
        """, (success, self.name))

        self.update_status()

    def create_message_record(self, recipient):
        wa_message = frappe.new_doc("WhatsApp Message")

        wa_message.to = recipient.get("mobile_number")
        wa_message.message_type = "Text"
        wa_message.status = "Queued"
        wa_message.flags.custom_ref_doc = json.loads(recipient.get("recipient_data", "{}"))
        wa_message.bulk_message_reference = self.name
        wa_message.reference_doctype = "Customer"
        wa_message.reference_name = recipient.get("customer")

        if recipient.get("recipient_data"):
            try:
                wa_message.flags.custom_ref_doc = json.loads(
                    recipient.get("recipient_data", "{}")
                )
            except Exception:
                pass

        if self.use_template:
            wa_message.template = self.template
            wa_message.use_template = 1
            wa_message.message_type = "Template"

            if self.template_variables:
                wa_message.template_variables = self.template_variables

        wa_message.insert(ignore_permissions=True)

    def update_status(self):
        total = self.recipient_count

        sent = frappe.db.count("WhatsApp Message", {
            "bulk_message_reference": self.name,
            "status": ["in", ["sent", "delivered", "read", "Success"]]
        })

        failed = frappe.db.count("WhatsApp Message", {
            "bulk_message_reference": self.name,
            "status": "Failed"
        })

        queued = frappe.db.count("WhatsApp Message", {
            "bulk_message_reference": self.name,
            "status": "Queued"
        })

        if queued > 0:
            status = "In Progress"
        elif failed > 0 and sent > 0:
            status = "Partially Failed"
        elif failed == total:
            status = "Failed"
        else:
            status = "Completed"

        self.db_set("status", status)

    def retry_failed(self):
        failed_messages = frappe.get_all(
            "WhatsApp Message",
            filters={
                "bulk_message_reference": self.name,
                "status": "Failed"
            },
            fields=["name"]
        )

        for msg in failed_messages:
            frappe.enqueue_doc(
                "WhatsApp Message",
                msg.name,
                "send_message",
                queue="long",
                timeout=600
            )

        frappe.msgprint(
            _("{} messages requeued").format(len(failed_messages))
        )

    def get_progress(self):
        total = self.recipient_count

        sent = frappe.db.count("WhatsApp Message", {
            "bulk_message_reference": self.name,
            "status": ["in", ["sent", "delivered", "read", "Success"]]
        })

        failed = frappe.db.count("WhatsApp Message", {
            "bulk_message_reference": self.name,
            "status": "Failed"
        })

        queued = frappe.db.count("WhatsApp Message", {
            "bulk_message_reference": self.name,
            "status": "Queued"
        })

        return {
            "total": total,
            "sent": sent,
            "failed": failed,
            "queued": queued,
            "percent": (sent / total * 100) if total else 0
        }