import frappe

def get_customer_mobile_no(doc, method):
    user_id = frappe.db.get_value("Customer", doc.customer, "akd_user")

    if user_id:
        mobile_no = frappe.db.get_value("User", user_id, "mobile_no")
        doc.custom_mobile_no = mobile_no or None
    else:
        doc.custom_mobile_no = None