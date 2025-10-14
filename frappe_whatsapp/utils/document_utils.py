import re
from frappe.model.document import Document
import frappe

def get_value_from_childtable(doc, fieldname):
    """
    Retrieve a field value from a Frappe Document or dict.
    Supports:
        - Child table fields: "items[0].against_sales_order"

    Args:
        doc (Document | dict): The Frappe document or dictionary
        fieldname (str): Field path, e.g., 'items[0].against_sales_order'

    Returns:
        Value of the field if found, else None
    """
    path_parts = re.split(r'\.(?![^\[]*\])', fieldname)  # e.g., ['items[0]', 'against_sales_order']

    current_value = doc

    for segment in path_parts:
        list_match = re.match(r'(\w+)\[(\d+)\]$', segment) # items[0]
        if list_match:
            table_fieldname, row_index = list_match.groups()  # table_fieldname -> 'items', row_index -> '0'
            row_index = int(row_index)

            # Get the child table list
            child_rows = getattr(current_value, table_fieldname, None)
            if child_rows is None and isinstance(current_value, dict):
                child_rows = current_value.get(table_fieldname)

            # If the child table exists and index is valid, move to that row
            if isinstance(child_rows, list) and len(child_rows) > row_index:
                current_value = child_rows[row_index]
            else:
                return None  # invalid index or missing child table
        else:
            # Regular field in the child row (or top-level document)
            if isinstance(current_value, Document):
                current_value = current_value.get(segment)
            elif isinstance(current_value, dict):
                current_value = current_value.get(segment)
            else:
                return None  # invalid type
    
    return current_value
