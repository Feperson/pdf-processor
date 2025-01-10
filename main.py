from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import httpx
from docling.document_converter import DocumentConverter
import json
from datetime import datetime
import os

app = FastAPI()

class ProcessRequest(BaseModel):
    file_url: str
    user_id: str
    attachment_id: str
    queue_item_id: str

class SupabaseClient:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip('/')
        self.key = key
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }

    async def update_queue_status(self, item_id: str, status: str, error_message: Optional[str] = None):
        async with httpx.AsyncClient() as client:
            data = {
                "status": status,
                "error_message": error_message
            }
            response = await client.patch(
                f"{self.url}/rest/v1/processing_queue?id=eq.{item_id}",
                headers=self.headers,
                json=data
            )
            return response.status_code == 200

    async def update_attachment_status(self, attachment_id: str, status: str, error: Optional[str] = None):
        async with httpx.AsyncClient() as client:
            data = {
                "processing_status": status,
                "processing_error": error,
                "processed": status == "completed"
            }
            response = await client.patch(
                f"{self.url}/rest/v1/email_attachments?id=eq.{attachment_id}",
                headers=self.headers,
                json=data
            )
            return response.status_code == 200

    async def create_invoice(self, invoice_data: dict):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.url}/rest/v1/invoices",
                headers=self.headers,
                json=invoice_data
            )
            return response.status_code == 201

@app.post("/process")
async def process_pdf(request: ProcessRequest):
    supabase = SupabaseClient(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    )
    
    try:
        # Update status to processing
        await supabase.update_queue_status(request.queue_item_id, "processing")
        await supabase.update_attachment_status(request.attachment_id, "processing")

        # Process PDF with Doclin
        converter = DocumentConverter()
        result = converter.convert(request.file_url)
        extracted_data = result.document.export_to_dict()

        # Map the extracted data to invoice structure
        invoice_data = {
            "user_id": request.user_id,
            "vendor_name": extracted_data.get("vendor_name", "Unknown Vendor"),
            "invoice_number": extracted_data.get("invoice_number", ""),
            "invoice_date": extracted_data.get("invoice_date", datetime.now().isoformat()),
            "due_date": extracted_data.get("due_date"),
            "amount": float(extracted_data.get("total_amount", 0)),
            "status": "pending"
        }

        # Create invoice
        await supabase.create_invoice(invoice_data)

        # Update statuses to completed
        await supabase.update_queue_status(request.queue_item_id, "completed")
        await supabase.update_attachment_status(request.attachment_id, "completed")

        return {"status": "success", "invoice_data": invoice_data}

    except Exception as e:
        error_message = str(e)
        await supabase.update_queue_status(request.queue_item_id, "error", error_message)
        await supabase.update_attachment_status(request.attachment_id, "error", error_message)
        raise HTTPException(status_code=500, detail=error_message)