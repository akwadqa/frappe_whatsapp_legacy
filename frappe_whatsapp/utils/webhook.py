import frappe
import json
import requests
import time
from werkzeug.wrappers import Response
import frappe.utils
import base64, io, json, requests
from PIL import Image
import re
from urllib.parse import unquote, urlparse
from frappe_whatsapp.utils.template_generator import generate_qr_card


@frappe.whitelist(allow_guest=True)
def webhook():
    """Meta webhook."""
    if frappe.request.method == "GET":
        return get()
    return post()


def get():
    """Get."""
    hub_challenge = frappe.form_dict.get("hub.challenge")
    webhook_verify_token = frappe.db.get_single_value(
        "WhatsApp Settings", "webhook_verify_token"
    )

    if frappe.form_dict.get("hub.verify_token") != webhook_verify_token:
        frappe.throw("Verify token does not match")

    return Response(hub_challenge, status=200)

def post():
    """Post."""
    data = frappe.local.form_dict
    frappe.get_doc({
        "doctype": "WhatsApp Notification Log",
        "template": "Webhook",
        "meta_data": json.dumps(data)
    }).insert(ignore_permissions=True)

    messages = []
    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages", [])
    except KeyError:
        messages = data["entry"]["changes"][0]["value"].get("messages", [])
    sender_profile_name = next(
        (
            contact.get("profile", {}).get("name")
            for entry in data.get("entry", [])
            for change in entry.get("changes", [])
            for contact in change.get("value", {}).get("contacts", [])
        ),
        None,
    )


    if messages:
        for message in messages:
            message_id = message['id']
            if frappe.db.exists("WhatsApp Message", {"message_id": message_id}):
                return
            message_type = message['type']
            is_reply = True if message.get('context') else False
            reply_to_message_id = message['context']['id'] if is_reply else None
            if message_type == 'text':
                frappe.get_doc({
                    "doctype": "WhatsApp Message",
                    "type": "Incoming",
                    "from": message['from'],
                    "message": message['text']['body'],
                    "message_id": message['id'],
                    "reply_to_message_id": reply_to_message_id,
                    "is_reply": is_reply,
                    "content_type":message_type,
                    "profile_name":sender_profile_name
                }).insert(ignore_permissions=True)
            elif message_type == 'reaction':
                frappe.get_doc({
                    "doctype": "WhatsApp Message",
                    "type": "Incoming",
                    "from": message['from'],
                    "message": message['reaction']['emoji'],
                    "reply_to_message_id": message['reaction']['message_id'],
                    "message_id": message['id'],
                    "content_type": "reaction",
                    "profile_name":sender_profile_name
                }).insert(ignore_permissions=True)
            elif message_type == 'interactive':
                frappe.get_doc({
                    "doctype": "WhatsApp Message",
                    "type": "Incoming",
                    "from": message['from'],
                    "message": message['interactive']['nfm_reply']['response_json'],
                    "message_id": message['id'],
                    "content_type": "flow",
                    "profile_name":sender_profile_name
                }).insert(ignore_permissions=True)
            elif message_type in ["image", "audio", "video", "document"]:
                settings = frappe.get_doc(
                            "WhatsApp Settings", "WhatsApp Settings",
                        )
                token = settings.get_password("token")
                url = f"{settings.url}/{settings.version}/"


                media_id = message[message_type]["id"]
                headers = {
                    'Authorization': 'Bearer ' + token

                }
                response = requests.get(f'{url}{media_id}/', headers=headers)

                if response.status_code == 200:
                    media_data = response.json()
                    media_url = media_data.get("url")
                    mime_type = media_data.get("mime_type")
                    file_extension = mime_type.split('/')[1]

                    media_response = requests.get(media_url, headers=headers)
                    if media_response.status_code == 200:

                        file_data = media_response.content
                        file_name = f"{frappe.generate_hash(length=10)}.{file_extension}"

                        message_doc = frappe.get_doc({
                            "doctype": "WhatsApp Message",
                            "type": "Incoming",
                            "from": message['from'],
                            "message_id": message['id'],
                            "reply_to_message_id": reply_to_message_id,
                            "is_reply": is_reply,
                            "message": message[message_type].get("caption",f"/files/{file_name}"),
                            "content_type" : message_type,
                            "profile_name":sender_profile_name
                        }).insert(ignore_permissions=True)

                        file = frappe.get_doc(
                            {
                                "doctype": "File",
                                "file_name": file_name,
                                "attached_to_doctype": "WhatsApp Message",
                                "attached_to_name": message_doc.name,
                                "content": file_data,
                                "attached_to_field": "attach"
                            }
                        ).save(ignore_permissions=True)


                        message_doc.attach = file.file_url
                        message_doc.save()
            elif message_type == "button":                
                frappe.get_doc({
                    "doctype": "WhatsApp Message",
                    "type": "Incoming",
                    "from": message['from'],
                    "message": message['button']['text'],
                    "message_id": message['id'],
                    "reply_to_message_id": reply_to_message_id,
                    "is_reply": is_reply,
                    "content_type": message_type,
                    "profile_name":sender_profile_name
                }).insert(ignore_permissions=True)
                update_invitee_rsvp_status(reply_to_message_id, message['button']['text'])
            else:
                frappe.get_doc({
                    "doctype": "WhatsApp Message",
                    "type": "Incoming",
                    "from": message['from'],
                    "message_id": message['id'],
                    "message": message[message_type].get(message_type),
                    "content_type" : message_type,
                    "profile_name":sender_profile_name
                }).insert(ignore_permissions=True)

    else:
        changes = None
        try:
            changes = data["entry"][0]["changes"][0]
        except KeyError:
            changes = data["entry"]["changes"][0]
        update_status(changes)
    return

def update_status(data):
    """Update status hook."""
    if data.get("field") == "message_template_status_update":
        update_template_status(data['value'])

    elif data.get("field") == "messages":
        update_message_status(data['value'])

def update_template_status(data):
    """Update template status."""
    frappe.db.sql(
        """UPDATE `tabWhatsApp Templates`
        SET status = %(event)s
        WHERE id = %(message_template_id)s""",
        data
    )

def update_message_status(data):
    """Update message status + sync Occasion Invitee RSVP status."""
    try:
        statuses = (data or {}).get("statuses") or []
        if not statuses:
            return

        st = statuses[0] or {}
        msg_id = st.get("id")
        status = (st.get("status") or "").lower()
        conversation = (st.get("conversation") or {}).get("id")

        if not msg_id or not status:
            return

        name = frappe.db.get_value("WhatsApp Message", {"message_id": msg_id}, "name")
        if not name:
            return

        msg_doc = frappe.get_doc("WhatsApp Message", name)
        msg_doc.status = status
        if conversation:
            msg_doc.conversation_id = conversation
        msg_doc.save(ignore_permissions=True)

        SUCCESS_STATES = {"sent", "delivered", "read"}
        FAIL_STATES = {"failed", "undelivered"}

        if msg_doc.occasion_invitee and frappe.db.exists("Occasion Invitee", msg_doc.occasion_invitee):
            inv = frappe.get_doc("Occasion Invitee", msg_doc.occasion_invitee)

            if inv.rsvp_status not in ["Confirmed", "Declined"] and not (inv.replied or 0):

                if status in SUCCESS_STATES:
                    if inv.rsvp_status in ["Not Sent", "Failed"]:
                        inv.db_set("rsvp_status", "Pending", update_modified=False)

                elif status in FAIL_STATES:
                    if inv.rsvp_status in ["Not Sent", "Pending"]:
                        inv.db_set("rsvp_status", "Failed", update_modified=False)

        frappe.db.commit()

    except Exception:
        frappe.log_error("error in updating message status", frappe.get_traceback())


def update_invitee_rsvp_status(message_id, reply):
    """Update RSVP status of an Occasion Invitee based on WhatsApp reply."""    
    
    try:
        if not message_id:
            frappe.log_error(
                title="Missing message_id",
                message="update_invitee_rsvp_status was called without a message_id"
            )
            return

        occasion_invitee = frappe.db.get_value(
            "WhatsApp Message",
            filters={"message_id": message_id},
            fieldname="occasion_invitee"
        )
        if not occasion_invitee:
            frappe.log_error(
                title="No invitee found",
                message=f"No invitee found for message_id={message_id}"
            )
            return
        #mapping to allow translation and different templates by senad
        status_map = {
            "تأكيد": "Confirmed",
            "اعتذار": "Declined",
            "موقع المناسبة": "Location",
            "Confirm": "Confirmed",
            "Decline": "Declined",
            "Confirmed": "Confirmed",
            "Declined": "Declined",
            "Location": "Location",
        }
        reply_r = status_map.get(reply)
        allowed = {"Confirmed", "Declined", "Location"}
        new_status = reply_r.strip() if reply_r else None

        if new_status not in allowed:
            frappe.log_error(
                title="Unrecognized reply",
                message=f"Unrecognized reply: {reply}"
            )
            return


        doc = frappe.get_doc("Occasion Invitee", occasion_invitee)
        doc.rsvp_status = new_status if new_status in ["Confirmed" , "Declined"] else doc.rsvp_status

        # Check if QR code is required and generate ticket_id
        requires_qr_code = frappe.db.get_value("Occasion", doc.occasion, "requires_qr_code")
        if requires_qr_code and new_status == "Confirmed" and not doc.ticket_id:
            doc.ticket_id = message_id

        doc.save(ignore_permissions=True)
        frappe.db.commit()


        settings = frappe.get_doc("WhatsApp Settings", "WhatsApp Settings")
        #Language changes by Senad
        language=frappe.db.get_value("Occasion", doc.occasion, "language")
        if language=="Arabic":
            confirm_text = (settings.get("confirm_reply_ar") or "").strip()
            decline_text = (settings.get("decline_reply_ar") or "").strip()
        elif language=="English":
            confirm_text = (settings.get("confirm_reply_en") or "").strip()
            decline_text = (settings.get("decline_reply_en") or "").strip()
        
        # if not confirm_text:
        #     confirm_text = "✅ Confirmed"
        # if not decline_text:
        #     decline_text = "❌ Declined"

        def send_text_message(text):
            frappe.get_doc({
                "doctype": "WhatsApp Message",
                "type": "Outgoing",
                "to": doc.whatsapp_number,
                "occasion_invitee": doc.name,
                "content_type": "text",
                "message_type": "Manual",
                "message": text,
                "reference_doctype": "Occasion Invitee",
                "reference_name": doc.name
            }).insert(ignore_permissions=True)

        def send_qr_image(image_url):
            frappe.get_doc({
                "doctype": "WhatsApp Message",
                "type": "Outgoing",
                "to": doc.whatsapp_number,
                "occasion_invitee": doc.name,
                "content_type": "image",
                "message_type": "Manual",
                "attach": image_url,
                "message": text,
                "reference_doctype": "Occasion Invitee",
                "reference_name": doc.name
            }).insert(ignore_permissions=True)


        if new_status == "Confirmed":
            try:
                if doc.qr_raw_data:
                    # Upload image template to WABA and send with media_id
                    context = {
                        "title": "Personal access card",
                        "subtitle": "Please show code to enter",
                        "subtitle_ar": "يرجى إبراز الكود للدخول",
                        "qr_image_url": doc.qr_raw_data,
                        "brand_en": "KROOT",
                        "brand_ar": "كروت",
                        "guest_count": doc.party_size,
                        "website": "www.kroot.com",
                    }
                    
                    base64_image_tmp = generate_qr_card("frappe_whatsapp/templates/QR_Code_template_Kroot.html", context)
                    doc.media_id = upload_base64_png_to_waba(base64_image_tmp)
                    doc.replied = 1
                    doc.save(ignore_permissions=True)

                    frappe.get_doc( {
                        "doctype": "WhatsApp Message",
                        "type": "Outgoing",
                        "to": doc.whatsapp_number,
                        "occasion_invitee": doc.name,
                        "message_type": "Manual",
                        "reference_doctype": "Occasion Invitee",
                        "reference_name": doc.name,
                        "content_type": "image",
                        "media_id": doc.media_id
                    }).insert(ignore_permissions=True)
                    frappe.db.commit()

            except Exception as e:
                frappe.log_error("error in sending qr image", str(e))

        
        elif new_status == "Declined":
            try:
                send_text_message(decline_text)
                doc.replied = 1
                doc.save(ignore_permissions=True)
                frappe.db.commit()
            except Exception as e:
                frappe.log_error("error in sending decline message", e)    



        elif new_status == "Location":
            location_name = frappe.db.get_value("Occasion", doc.occasion, "location_name")
            location_address = frappe.db.get_value("Occasion", doc.occasion, "location_address")

            lat = frappe.db.get_value("Occasion", doc.occasion, "map_latitude")
            lng = frappe.db.get_value("Occasion", doc.occasion, "map_longitude")

            if lat is None or lng is None:
                frappe.log_error(
                    title="Missing Location Coordinates",
                    message=f"Occasion {doc.occasion} is missing map_latitude/map_longitude"
                )
                return

            try:
                message_data = {
                    "doctype": "WhatsApp Message",
                    "type": "Outgoing",
                    "to": doc.whatsapp_number,
                    "occasion_invitee": doc.name,
                    "content_type": "location",
                    "latitude": float(lat),
                    "longitude": float(lng),
                    "location_name": location_name,
                    "location_address": location_address,
                    "reference_doctype": "Occasion",
                    "reference_name": doc.occasion
                }
                frappe.get_doc(message_data).insert(ignore_permissions=True)
                frappe.db.commit()
            except Exception as e:
                frappe.log_error("send location error", str(e))

            return

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            title="RSVP Update Failed",
            message=f"message_id={message_id}, reply={reply}, error={str(e)}"
        )


def upload_base64_png_to_waba(b64_png: str) -> str:
    """Uploads a PNG to WABA and returns media_id."""
    settings = frappe.get_doc(
            "WhatsApp Settings",
            "WhatsApp Settings",
        )
    token = settings.get_password("token")

    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
    }    
    
    url = f"{settings.url}/{settings.version}/{settings.phone_id}/media"

    png_bytes = normalize_png(b64_png)
    files = {"file": ("qr.png", io.BytesIO(png_bytes), "image/png")}
    data = {"messaging_product": "whatsapp"}
    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.post(url, headers=headers, data=data, files=files, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]

def normalize_png(b64_png: str) -> bytes:
    """Ensure PNG is RGB 8-bit and return clean binary."""
    raw = base64.b64decode(b64_png.split(",", 1)[1] if "," in b64_png else b64_png)
    im = Image.open(io.BytesIO(raw))

    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGB")

    buf = io.BytesIO()
    im.save(buf, format="PNG")   # Pillow will default to 8-bit RGB/ RGBA
    return buf.getvalue()

def extract_google_maps_info(url):
    """
    Extracts latitude, longitude from a Google Maps URL."""   

    # Extract lat/lng from !3dLAT!4dLNG pattern (more accurate than @lat,lng)
    coord_match = re.search(r'!3d([-+]?[0-9]*\.?[0-9]+)!4d([-+]?[0-9]*\.?[0-9]+)', url)
    if coord_match:
        lat = float(coord_match.group(1))
        lng = float(coord_match.group(2))
    else:
        # fallback to @lat,lng pattern
        at_match = re.search(r'@([-+]?[0-9]*\.?[0-9]+),([-+]?[0-9]*\.?[0-9]+)', url)
        if at_match:
            lat = float(at_match.group(1))
            lng = float(at_match.group(2))
        else:
            lat = lng = None

    return {
        "latitude": lat,
        "longitude": lng
    }
        
        
