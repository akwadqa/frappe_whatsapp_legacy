import frappe

def execute():
    """Backfill custom_mobile_no in Customer from linked User mobile number."""
    customers = frappe.get_all("Customer", fields=["name", "akd_user"])

    for c in customers:
        if not c.akd_user:
            continue

        mobile = frappe.db.get_value("User", c.akd_user, "mobile_no")
        if mobile:
            frappe.db.set_value("Customer", c.name, "custom_mobile_no", mobile)
    frappe.db.commit()