# Override Document.run_notifications with a wrapper that:
# 1) Calls the existing notifications method (email, FCM, or any previous override)
# 2) Then runs WhatsApp notifications
# This ensures WhatsApp notifications are added without breaking existing notification logic.

from frappe.model.document import Document
from frappe_whatsapp.native_overrides import run_notifications as wa_run

_original_run = Document.run_notifications

def run_notifications_wrapper(self, method):
    if _original_run:
        _original_run(self, method)
    wa_run(self, method)

Document.run_notifications = run_notifications_wrapper