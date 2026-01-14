import frappe
import tempfile
import os
import base64
from playwright.sync_api import sync_playwright

def generate_qr_card(template_name: str, context: dict):
    html = frappe.render_template(template_name, context)
    
    # Set default output for testing
    output_dir = "/home/akwad/nest-bench/apps/frappe_whatsapp/frappe_whatsapp/templates"
    output_path = os.path.join(output_dir, "test_qr_card.png")
 

    png_bytes = None

    # Create temporary HTML file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as f:
        f.write(html.encode("utf-8"))
        html_path = f.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )

            page = browser.new_page(
                viewport={"width": 360, "height": 640},
                device_scale_factor=2
            )

            page.goto(f"file://{html_path}", wait_until="networkidle")
            png_bytes = page.screenshot(type="png")
            # for testing
            page.screenshot(path=output_path)

            browser.close()

    except Exception:
        frappe.log_error(title= "QR Card Generation Failed", message = frappe.get_traceback())
        raise

    finally:
        os.unlink(html_path)

    if not png_bytes:
        raise RuntimeError("Failed to generate QR card image")

    print(f"PNG generated: {output_path}")

    return base64.b64encode(png_bytes).decode("utf-8")
