import uuid
from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.responses import JSONResponse
import os, base64, json, datetime, tempfile
from uuid import uuid4
from dotenv import load_dotenv
from pdf2image import convert_from_bytes
from openai import AzureOpenAI
from pydantic import BaseModel
from azure.storage.blob import BlobServiceClient
from collections import OrderedDict
import mimetypes
import platform
import subprocess
import io
import tempfile
from spire.doc import Document as SpireDocument
from spire.doc import FileFormat

from azure.data.tables import TableServiceClient

app = FastAPI()

load_dotenv()

system_platform = platform.system()

openai_endpoint = os.getenv("azureopenai_endpoint")
openai_key = os.getenv("azure_openai_key")
api_version = os.getenv("api_version")
DEPLOYMENT_NAME = os.getenv("azureopenai_deployment")

client = AzureOpenAI(
    api_key=openai_key,
    api_version=api_version,
    azure_endpoint=openai_endpoint
)

AZURE_BLOB_CONNECTION_STRING = os.getenv("azure_blob_connection_string")
blob_service_client = BlobServiceClient.from_connection_string(AZURE_BLOB_CONNECTION_STRING)

def convert_to_base64_images(file_bytes):

    images = convert_from_bytes(file_bytes, dpi=200)
    base64_images = []
    for img in images:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            img.save(tmp_path, format="PNG")
            with open(tmp_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
                base64_images.append(f"data:image/png;base64,{b64}")
        finally:
            os.remove(tmp_path)
    return base64_images

def get_file_type(file) -> str:
    return mimetypes.guess_type(file.name)[0] or "application/octet-stream"

def build_prompt_with_images(image_base64_urls, context):

    images = [{"type": "image_url", "image_url": {"url": url}} for url in image_base64_urls]
    prompt = {
        "type": "text",
        "text": f"""
You are a *Signature Detection Expert AI*.

Analyze the uploaded document images and return a well-structured JSON in the schema format provided below. Use this **context** to enrich your response:

Context:
{context}

----------------------
📌 JSON Output Schema
----------------------
# 
1. "documentReport": {{
    "fileName": string,
    "documentId": string (generate dummy if unavailable without word "dummy"),
    "status_of_Document": "Complete" | "OnHold" | "Error",
    "signature_zones_count": integer,
    "signatures_Completed": integer,
    "page_Count": integer,
    "workflow_Id": string,
    "Timestamp": string, ((YYYY-MM-DD HH:MM:SS) format),
    "document_content_length" : integer,
}}

2. "pages": [
  {{
    "pageNumber": integer,
    "signatureZones": [
      {{
        "status": "Signed" | "Unsigned" | "Skipped",
        "base64Image": string (include complete string only if signed),
        "confidenceScore": float (0.0 - 1.0),
        "signedDate": string | null (YYYY-MM-DD),
        "firstName": string,
        "lastName": string,
        "email": string, (Provide only if it presents in the document)
        "Signature_type" : string (Handwritten/Stamped/Digital),
        "Bounding_box" (only provide if signature is detected) :{{
        "x": Integer,
        "y": Integer,
        "width": Integer,
        "height": Integer
      }} 
        "zoneSetting": "Required" | "AllowSkip",
        "signerNumber": int,
      }}
    ]
  }}
]

----------------------
📌 Instructions
----------------------
- Detect all signature zones and analyze visually from the image.
- Analye the Signature zones and identify whether they are signed or not. But do not use prior knowledge or assumptions to decide whether they are signed or not.
- Extract all the metadata as per the schema and only from the document images provided.
- Extract the Names (lastName and firstName) of the signers from the Signatures.
- Extract the email address of the signers if it is present in the document but do not assume them(like if name is chris jordan, don't give chris.jordan@example.com -> Only provice it they are present).
- Give the signature zones count and signatures completed count correctly.
- Each page may have multiple signature zones.
- Set `"status": "Signed"` only if signature is clearly present.
- Return `base64Image` only if signed.
- If no signature but zone is visible, mark `Unsigned`.
- Infer signer details using surrounding text, especially near the signature box.
- If no signature zone is detected, return an empty array for `signatureZones`.
-If signature_zones_count == signatures_Completed, set status_of_Document to "Complete".
-Else, set status_of_Document to "OnHold".
-If no signatures are detected, set status_of_Document to "Complete" and signatures_Completed = 0.
-If an error occurs, set status_of_Document to "Error" and provide a meaningful message.
- Ensure all fields are filled as per the schema.
- Include the Bounding Box coordinates for each signature detected. Signature detection and coordinates must be accurate and **based on a resolution of 200 DPI**.
    - All `boundingBox` coordinates (`x`, `y`, `width`, `height`) must correspond to the 200 DPI resolution of the image.
    - Ensure bounding boxes visually match actual locations when overlaid on the converted image.
- Omit the Bounding box and base64Image if the signature is not detected.
- "document_content_length" refers to the total number of characters present in the document text.
- Confidencescore refers to the AI's certainty about the signature detection, ranging from 0.0 (not sure) to 1.0 (very sure).
- If the signature zone is `Unsigned`, then give the firstName and lastName as empty ("").
- If the status is "Unsigned", always set "confidenceScore": 0.0.
- Give all metadata related to all signature zones detected in the document as mentioned in the schema.
- Analyse the total content and signature in the document and provide zoneSetting as "Required" or "AllowSkip" based on the presence of signature zones.(Example- For loan approval, Primary Account holder's and one of the witness's signature zones are required, so set zoneSetting as "Required". For a document with multiple signers, if one of the signers is not mandatory, then set zoneSetting as "AllowSkip" for that signer.)
- If there are no signature zones detected, then give the confidence score as 0.
- Give Page wise signature zones metadata as mentioned in the schema.
- If you think that there is a signature zone or a signature but it is not clearly visible, then try to extract the signature text as much as you can with moderate confidence score and give the status as 'Unclear'.
- If the signature zone is required to be signed but it is unsigned, then set the status of the document as 'Incomplete'.

- Signature Classification:
   - "Handwritten" = A real pen-written or stylus-drawn signature with natural, irregular strokes (scanned or on paper).
   - "Digital" = Any electronically generated signature, including:
        * Signatures represented as text placeholders (e.g., "/s/ John Doe")
        * Typed names
        * Scanned stamps
        * E-signature software generated marks or certificates
   - STRICT RULE: If the signature is shown as "/s/ Name" or looks typed/uniform, ALWAYS classify as "Digital", never "Handwritten".
   - Do not guess. Only classify as "Handwritten" if the visual evidence clearly shows pen strokes.
   
- Only return the required well-structured JSON Output — no explanation and don't give hallucinated answers  like ```json```.
"""
    }
    return [prompt] + images

def fetch_blob_file(blob_url: str) -> bytes:
    try:
        from urllib.parse import urlparse
        
        parsed_url = urlparse(blob_url)
        container_name = parsed_url.path.split('/')[1]
        blob_name = parsed_url.path.split('/', 2)[2] 

        container_client = blob_service_client.get_container_client(container_name)
        blob_client = container_client.get_blob_client(blob_name)
        
        stream = blob_client.download_blob()
        return stream.readall()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch blob: {str(e)}")
    
class BlobData(BaseModel):
    blob_url: str

def openai_call_pdf(filebytes, content_type, filename):
    image_urls = convert_to_base64_images(filebytes)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    workflow_id = f"workflow_{uuid4().hex[:8]}"
    document_id = f"doc_{uuid4().hex[:8]}"
    document_content_length = len(filebytes)
    
    context = f"""
Document Name: {filename}
File Type: {content_type}
workflow ID: {workflow_id}
Document ID: {document_id}
Uploaded at: {timestamp}
Document Content Length: {document_content_length}
"""

    messages = [
        {"role": "system", "content": "You are a document signature detection assistant."},
        {"role": "user", "content": build_prompt_with_images(image_urls, context)}
    ]

    response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=messages,
        temperature=0.1,
        max_tokens=4096
    )

    result_text = response.choices[0].message.content.strip()
    result_json = json.loads(result_text)
    signature_fields = []
    for page in result_json.get("pages", []):
        for zone in page.get("signatureZones", []):
            signature_fields.append(zone)

    confidences = [
    zone.get("confidenceScore", 0.0)
    for page in result_json.get("pages", [])
    for zone in page.get("signatureZones", [])
    if isinstance(zone.get("confidenceScore"), (int, float))
    ]

    min_confidence = min(confidences) if confidences else 0.0
    
    doc_report = result_json["documentReport"]
    ordered_doc_report = OrderedDict()
    for key, value in doc_report.items():
        ordered_doc_report[key] = value
        if key == "document_content_length":
            ordered_doc_report["min_confidence_score"] = min_confidence

    sig_zones = ordered_doc_report.get('signature_zones_count', 0)
    sig_completed = ordered_doc_report.get('signatures_Completed', 0)
    if sig_zones == 0:
        ordered_doc_report['status_of_Document'] = "Complete"
    elif sig_zones == sig_completed:
        ordered_doc_report['status_of_Document'] = "Complete"
    else:
        ordered_doc_report['status_of_Document'] = "OnHold"
    
    result_json["documentReport"] = ordered_doc_report
    return result_json


def openai_call_img(filebytes, content_type, filename):
    
    base64_img = base64.b64encode(filebytes).decode("utf-8")
    mime = 'image/png'
    image_urls= [f"data:{mime};base64,{base64_img}"]
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    workflow_id = f"workflow_{uuid4().hex[:8]}"
    document_id = f"doc_{uuid4().hex[:8]}"
    document_content_length = len(filebytes)
    
    context = f"""
Document Name: {filename}
File Type: {content_type}
workflow ID: {workflow_id}
Document ID: {document_id}
Uploaded at: {timestamp}
Document Content Length: {document_content_length}
"""

    messages = [
        {"role": "system", "content": "You are a document signature detection assistant."},
        {"role": "user", "content": build_prompt_with_images(image_urls, context)}
    ]

    response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=messages,
        temperature=0.1,
        max_tokens=4096
    )

    result_text = response.choices[0].message.content.strip()
    result_json = json.loads(result_text)
    
    signature_fields = []
    for page in result_json.get("pages", []):
        for zone in page.get("signatureZones", []):
            signature_fields.append(zone)

    confidences = [
    zone.get("confidenceScore", 0.0)
    for page in result_json.get("pages", [])
    for zone in page.get("signatureZones", [])
    if isinstance(zone.get("confidenceScore"), (int, float))
    ]

    min_confidence = min(confidences) if confidences else 0.0
    
    doc_report = result_json["documentReport"]
    ordered_doc_report = OrderedDict()

    for key, value in doc_report.items():
        ordered_doc_report[key] = value
        if key == "document_content_length":
            ordered_doc_report["min_confidence_score"] = min_confidence
            
    sig_zones = ordered_doc_report.get('signature_zones_count', 0)
    sig_completed = ordered_doc_report.get('signatures_Completed', 0)
    if sig_zones == 0:
        ordered_doc_report['status_of_Document'] = "Complete"
    elif sig_zones == sig_completed:
        ordered_doc_report['status_of_Document'] = "Complete"
    else:
        ordered_doc_report['status_of_Document'] = "OnHold"
    
    result_json["documentReport"] = ordered_doc_report
    return result_json

def file_doc(uploaded_file):
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp_docx:
        tmp_docx.write(uploaded_file.read())
        tmp_docx_path = tmp_docx.name
        output_pdf_path = tmp_docx_path.replace(".docx", ".pdf")

    try:
        if system_platform == "Windows" or system_platform == "Darwin":
            spire_doc = SpireDocument()
            spire_doc.LoadFromFile(tmp_docx_path)
            spire_doc.SaveToFile(output_pdf_path, FileFormat.PDF)
            spire_doc.Close()
            
        elif system_platform == "Linux":
            subprocess.run([
                "soffice",
                "--headless",
                "--convert-to", "pdf",
                "--outdir", os.path.dirname(tmp_docx_path),
                tmp_docx_path
            ], check=True)
            
        else:
            print("Not supported")

    except Exception as e:
        print(e)
        
    return output_pdf_path

@app.post("/analyze/upload-file", summary="Analyze a document from a file upload")
async def analyze_document_from_file(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        filename = file.filename
        content_type = file.content_type

        if not filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg",".docx")):
            raise HTTPException(status_code=400, detail="Only PDF or image files are supported.")
        
        if filename.lower().endswith((".png", ".jpg", ".jpeg")):
            result_json = openai_call_img(file_bytes,content_type, filename)
        elif filename.lower().endswith((".pdf")):
            result_json = openai_call_pdf(file_bytes,content_type, filename)
        else:
            file_like = io.BytesIO(file_bytes)
            file_like.name = filename
            output_pdf_path = file_doc(file_like)
            with open(output_pdf_path, "rb") as f:
                file_bytes = f.read()
            result_json = openai_call_pdf(file_bytes,content_type, filename)

        return JSONResponse(content=result_json)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/blob-url", summary="Analyze a document from a blob URL")
async def analyze_document_from_url(blob_data: BlobData = Body(...)):
    try:
        file_bytes = fetch_blob_file(blob_data.blob_url)
        filename = blob_data.blob_url.split("/")[-1]
        
        if filename.lower().endswith(".pdf"):
            content_type = "application/pdf"
        elif filename.lower().endswith(".docx"):
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif filename.lower().endswith((".png", ".jpg", ".jpeg")):
            content_type = "image/png"
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type.")
                
        if filename.lower().endswith((".png", ".jpg", ".jpeg")):
            result_json = openai_call_img(file_bytes,content_type, filename)
        elif filename.lower().endswith((".pdf")):
            result_json = openai_call_pdf(file_bytes,content_type, filename)
        else:
            file_like = io.BytesIO(file_bytes)
            file_like.name = filename
            output_pdf_path = file_doc(file_like)
            with open(output_pdf_path, "rb") as f:
                file_bytes = f.read()
            result_json = openai_call_pdf(file_bytes,content_type, filename)

        return JSONResponse(content=result_json)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

AZURE_TABLE_CONN_STRING = os.getenv("azure_blob_connection_string")
TABLE_NAME = "logs"

table_service = TableServiceClient.from_connection_string(conn_str=AZURE_TABLE_CONN_STRING)
table_client = table_service.get_table_client(table_name=TABLE_NAME)

SUPPORTED_CONTENT_TYPES = [
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
]

class FileUploadRequest(BaseModel):
    fileName: str
    contentType: str
    sizeBytes: int
    fileData: str 
    
@app.post("/analyze/upload-base64", summary="Analyze a document from a base64 string")
async def analyze_document_from_base64(file_req: FileUploadRequest):
    try:
        content_type = file_req.contentType.lower()

        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Only these formats are supported: {', '.join(SUPPORTED_CONTENT_TYPES)}"
            )

        try:
            file_bytes = base64.b64decode(file_req.fileData, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 string")

        if content_type == "application/pdf":
            if not file_bytes.startswith(b"%PDF"):
                raise HTTPException(status_code=400, detail="Decoded file is not a valid PDF")
            result_json = openai_call_pdf(file_bytes, content_type, file_req.fileName)

        elif content_type.startswith("image/"):
            result_json = openai_call_img(file_bytes, content_type, file_req.fileName)

        log_entity = {
            "PartitionKey": "DocumentAnalysis",
            "RowKey": str(uuid.uuid4()),  
            "fileName": file_req.fileName,
            "contentType": file_req.contentType,
            "sizeBytes": file_req.sizeBytes,
            "inputBase64": file_req.fileData[:5000],
            "outputJson": json.dumps(result_json),
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

        table_client.create_entity(entity=log_entity)
        print("Log stored in Azure Table successfully.")

        return JSONResponse(content=result_json)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))