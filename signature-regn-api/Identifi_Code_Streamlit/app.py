import streamlit as st
import os, base64, json, datetime, tempfile, platform, subprocess, mimetypes
from uuid import uuid4
from dotenv import load_dotenv
from pdf2image import convert_from_bytes
from openai import AzureOpenAI
from collections import OrderedDict
from spire.doc import Document as SpireDocument
from spire.doc import FileFormat
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient  
import uuid 

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

AZURE_TABLE_CONN_STRING = os.getenv("azure_blob_connection_string")  
TABLE_NAME = "logs"
table_service = TableServiceClient.from_connection_string(conn_str=AZURE_TABLE_CONN_STRING)
table_client = table_service.get_table_client(table_name=TABLE_NAME)

def log_analysis_to_azure_table(file_name, content_type, size_bytes, file_data_base64, result_json):
    try:
        log_entity = {
            "PartitionKey": "DocumentAnalysis",
            "RowKey": str(uuid.uuid4()), 
            "fileName": file_name,
            "contentType": content_type,
            "sizeBytes": size_bytes,
            "inputBase64": file_data_base64[:5000], 
            "outputJson": json.dumps(result_json),
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        table_client.create_entity(entity=log_entity)
        st.info("✅ Analysis log saved to Azure Table Storage.")
    except Exception as e:
        st.error(f"Failed to log analysis to Azure Table Storage: {e}")

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

1. "documentReport": {{
   "fileName": string,
   "documentId": string (generate dummy if unavailable),
   "status_of_Document": "Complete" | "OnHold" | "Error",
   "signature_Zones_count": integer,
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
        "base64Image": string (include only if signed),
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
- Extract emails, signature types, bounding boxes.
- Each page may have multiple signature zones.
- Set `"status": "Signed"` only if signature is clearly present.
- Return `base64Image` only if signed.
- If no signature but zone is visible, mark `Unsigned`.
- Infer signer details using surrounding text, especially near the signature box.
- If no signature zone is detected, return an empty array for `signatureZones`.
- If no signatures are detected, set `status_of_Document` to "OnHold" and `signatures_Completed` to 0.
- If an error occurs, set `status_of_Document` to "Error" and provide a meaningful message.
- Ensure all fields are filled as per the schema.
- Include the Bounding Box coordinates for each signature detected.
- Omit the Bounding box and base64Image if the signature is not detected.
- "document_content_length" refers to the total number of characters present in the document text.
- Confidencescore refers to the AI's certainty about the signature detection, ranging from 0.0 (not sure) to 1.0 (very sure).
- If the status is "Unsigned", always set "confidenceScore": 0.0.
- If the signature zone is `Unsigned`, then give the firstName and lastName as empty ("").
- Give all metadata related to all signature zones detected in the document as mentioned in the schema.
- Analyse the total content and signature in the document and provide zoneSetting as "Required" or "AllowSkip" based on the presence of signature zones.
- If there are no signature zones detected, then .
- Give Page wise signature zones metadata as mentioned in the schema.
- Signature Classification:
   - "Handwritten" = A real pen-written or stylus-drawn signature with natural, irregular strokes (scanned or on paper).
   - "Digital" = Any electronically generated signature, including:
        * Signatures represented as text placeholders (e.g., "/s/ John Doe")
        * Typed names
        * Scanned stamps
        * E-signature software generated marks or certificates
   - STRICT RULE: If the signature is shown as "/s/ Name" or looks typed/uniform, ALWAYS classify as "Digital", never "Handwritten".
   - Do not guess. Only classify as "Handwritten" if the visual evidence clearly shows pen strokes.
- Only return the required output — no explanation and don't give hallucinated answers  like ```json```.
"""

    }
    return [prompt] + images

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
    total_zones = 0
    signed_count = 0
    for page in result_json.get("pages", []):
        sig_zones = page.get("signatureZones", [])
        total_zones += len(sig_zones)
        signed_count += sum(1 for zone in sig_zones if zone.get("status") == "Signed")
    if total_zones > 0 and total_zones == signed_count:
        status = "Complete"
    else:
        status = "OnHold"
    result_json["documentReport"]["status_of_Document"] = status

    confidences = [
        zone.get("confidenceScore", 0.0)
        for page in result_json.get("pages", [])
        for zone in page.get("signatureZones", [])
        if isinstance(zone.get("confidenceScore"), (int, float))
    ]
    min_confidence = min(confidences) if confidences else 0.0

    ordered_doc_report = OrderedDict()
    for key, value in result_json["documentReport"].items():
        ordered_doc_report[key] = value
        if key == "document_content_length":
            ordered_doc_report["min_confidence_score"] = min_confidence

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
    total_zones = 0
    signed_count = 0
    for page in result_json.get("pages", []):
        sig_zones = page.get("signatureZones", [])
        total_zones += len(sig_zones)
        signed_count += sum(1 for zone in sig_zones if zone.get("status") == "Signed")

    if total_zones > 0 and total_zones == signed_count:
        status = "Complete"
    else:
        status = "OnHold"

    result_json["documentReport"]["status_of_Document"] = status


    confidences = [
        zone.get("confidenceScore", 0.0)
        for page in result_json.get("pages", [])
        for zone in page.get("signatureZones", [])
        if isinstance(zone.get("confidenceScore"), (int, float))
    ]
    min_confidence = min(confidences) if confidences else 0.0

    ordered_doc_report = OrderedDict()
    for key, value in result_json["documentReport"].items():
        ordered_doc_report[key] = value
        if key == "document_content_length":
            ordered_doc_report["min_confidence_score"] = min_confidence

    result_json["documentReport"] = ordered_doc_report
    return result_json

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
        print(f"Error fetching blob file: {str(e)}")
        return None
    
def file_doc(uploaded_file):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp_docx:
        tmp_docx.write(uploaded_file.read())
        tmp_docx_path = tmp_docx.name
        output_pdf_path = tmp_docx_path.replace(".docx", ".pdf")

    try:
        if system_platform in ["Windows", "Darwin"]:
            spire_doc = SpireDocument()
            spire_doc.LoadFromFile(tmp_docx_path)
            spire_doc.SaveToFile(output_pdf_path, FileFormat.PDF)
            spire_doc.Close()
        elif system_platform == "Linux":
            subprocess.run([
                "soffice", "--headless", "--convert-to", "pdf",
                "--outdir", os.path.dirname(tmp_docx_path),
                tmp_docx_path
            ], check=True)
    except Exception as e:
        st.error(f"Error converting DOCX to PDF: {e}")
        
    return output_pdf_path

def handle_blob_url(blob_url: str):
    try:
        file_bytes = fetch_blob_file(blob_url)
        filename = blob_url.split("/")[-1]
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        if filename.lower().endswith((".png", ".jpg", ".jpeg")):
            return openai_call_img(file_bytes, content_type, filename)

        elif filename.lower().endswith(".pdf"):
            return openai_call_pdf(file_bytes, content_type, filename)

        elif filename.lower().endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp_docx:
                tmp_docx.write(file_bytes)
                tmp_docx_path = tmp_docx.name
            output_pdf_path = file_doc(open(tmp_docx_path, "rb"))
            with open(output_pdf_path, "rb") as f:
                pdf_bytes = f.read()
            return openai_call_pdf(pdf_bytes, "application/pdf", filename)

        else:
            st.error("❌ Unsupported file type from Blob.")
            return None

    except Exception as e:
        st.error(f"Error fetching or processing blob: {str(e)}")
        return None
    
    
if "result_json" not in st.session_state:
    st.session_state.result_json = None
if "last_input_id" not in st.session_state:
    st.session_state.last_input_id = None
if "last_input_method" not in st.session_state:
    st.session_state.last_input_method = None
    
st.set_page_config(
    page_title="Signature Identifier",
    page_icon="✍️",
    layout="wide"
)

st.markdown(
    """
    <div style="text-align: center; padding: 1rem; background: linear-gradient(90deg, #648880, #293f50); border-radius: 12px; margin-bottom: 2rem;">
        <h1 style="color: white; margin: 0;">✍️ Document Signature Recognition</h1>
        <p style="color: white; font-size: 1.1rem;">Upload your document or provide a Blob URL and let the AI find all signatures for you</p>
    </div>
    """,
    unsafe_allow_html=True
)

st.divider()

input_method = st.selectbox(
    "Select your Input Method",
    ["select an input way","Upload a File", "Provide Blob URL","Upload base64"]
)

if st.session_state.last_input_method != input_method:
    st.session_state.result_json = None
st.session_state.last_input_method = input_method

uploaded_file = None
blob_url = None
base64_json = None
result_json = None
threshold = None

if input_method == "Upload a File":
    uploaded_file = st.file_uploader(
        "📂 **Upload a PDF, DOCX, or Image**",
        type=["pdf", "docx", "png", "jpg", "jpeg"],
        help="Drag & drop or browse your file"
    )
    threshold = st.slider(
        "📉 Set your confidence threshold",
        min_value=0.0,
        max_value=1.0,
        value=0.7,
        step=0.01
    )

elif input_method == "Provide Blob URL":
    blob_url = st.text_input(
        "🔗 Enter Blob URL",
        placeholder="https://<storage-account>.blob.core.windows.net/<container>/<filename>"
    )

    threshold = st.slider(
        "📉 Set your confidence threshold",
        min_value=0.0,
        max_value=1.0,
        value=0.7,
        step=0.01
    )
elif input_method == "Upload base64":
    base64_json = st.text_area(
        "📄 **Provide fileName, contentType, sizeBytes and fileData in json format**",
        placeholder="""{
  "fileName": "string",
  "contentType": "string",
  "sizeBytes": 0,
  "fileData": "base64 string"
}""",
        height=200
    )
    threshold = st.slider(
        "📉 Set your confidence threshold",
        min_value=0.0,
        max_value=1.0,
        value=0.7,
        step=0.01
    )

if input_method == "Upload a File" and uploaded_file:
    file_id = uploaded_file.name + str(uploaded_file.size)
    if st.session_state.get("last_input_id") != file_id:
        st.session_state.result_json = None
        st.session_state.last_input_id = file_id

if input_method == "Provide Blob URL" and blob_url:
    if st.session_state.get("last_input_id") != blob_url:
        st.session_state.result_json = None
        st.session_state.last_input_id = blob_url

if input_method == "Upload base64" and base64_json:
    try:
        base64_data = json.loads(base64_json)
        if st.session_state.get("last_input_id") != base64_json:
            st.session_state.result_json = None
            st.session_state.last_input_id = base64_json
        if "fileData" in base64_data and "fileName" in base64_data and "contentType" in base64_data:
            file_bytes = base64.b64decode(base64_data["fileData"])
            content_type = base64_data["contentType"]
            filename = base64_data["fileName"]
        else:
            st.error("❌ Invalid JSON format. Please provide valid keys: fileName, contentType, sizeBytes, fileData.")
    except json.JSONDecodeError:
        st.error("❌ Invalid JSON format. Please check your input.")

analyze_button = st.button("🔍 Analyze for Signatures", key="analyze_button")

filename = ""
if analyze_button:
    st.session_state.result_json = None  

    if input_method == "Upload a File" and uploaded_file:
        filename = uploaded_file.name
        content_type = get_file_type(uploaded_file)
        uploaded_file.seek(0)
        file_bytes = uploaded_file.read()
        file_data_base64 = base64.b64encode(file_bytes).decode("utf-8")
        size_bytes = len(file_bytes)

        with st.spinner("🔍 Identifying the signatures... Please wait"):
            if filename.lower().endswith((".png", ".jpg", ".jpeg")):
                st.session_state.result_json = openai_call_img(file_bytes, content_type, filename)
            elif filename.lower().endswith(".pdf"):
                st.session_state.result_json = openai_call_pdf(file_bytes, content_type, filename)
            elif filename.lower().endswith(".docx"):
                uploaded_file.seek(0)
                output_pdf_path = file_doc(uploaded_file)
                with open(output_pdf_path, "rb") as f:
                    pdf_bytes = f.read()
                st.session_state.result_json = openai_call_pdf(pdf_bytes, "application/pdf", filename)
            else:
                st.error("❌ Unsupported file type.")
                st.stop()

    elif input_method == "Provide Blob URL" and blob_url:
        with st.spinner("🔍 Fetching and detecting signatures... Please wait"):
            filename = blob_url.split("/")[-1]
            st.session_state.result_json = handle_blob_url(blob_url)
        file_bytes = fetch_blob_file(blob_url)
        file_data_base64 = base64.b64encode(file_bytes).decode("utf-8") if file_bytes else ""
        size_bytes = len(file_bytes) if file_bytes else 0
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    elif input_method == "Upload base64" and base64_json:
        try:
            base64_data = json.loads(base64_json)
            file_bytes = base64.b64decode(base64_data["fileData"])
            content_type = base64_data["contentType"]
            filename = base64_data["fileName"]
            file_data_base64 = base64_data["fileData"]
            size_bytes = base64_data.get("sizeBytes", len(file_bytes))
            with st.spinner("🔍 Detecting signatures... Please wait"):
                if content_type.startswith("image/"):
                    st.session_state.result_json = openai_call_img(file_bytes, content_type, filename)
                elif content_type == "application/pdf":
                    st.session_state.result_json = openai_call_pdf(file_bytes, content_type, filename)
                else:
                    st.error("❌ Unsupported file type for base64 input.")
                    st.stop()
            if st.session_state.result_json:
                log_analysis_to_azure_table(filename, content_type, size_bytes, file_data_base64, st.session_state.result_json)
        except json.JSONDecodeError:
            st.error("❌ Invalid JSON format. Please check your input.")
    else:
        st.warning("⚠️ Please upload a file or enter a valid Blob URL.")

if st.session_state.result_json:
    result_json = st.session_state.result_json

    st.divider()

    confidences = [
        zone.get("confidenceScore", 0.0)
        for page in result_json.get("pages", [])
        for zone in page.get("signatureZones", [])
        if isinstance(zone.get("confidenceScore"), (int, float))
    ]

    min_confidence = min(confidences) if confidences else 0.0

    doc_report = result_json.get("documentReport", {})
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📄 Pages", doc_report.get("page_Count", 0))
    col2.metric("✍️ Signatures Found", doc_report.get("signatures_Completed", 0))
    col3.metric("🔒 Min Confidence", f"{doc_report.get('min_confidence_score', 0)*100:.1f}%")
    col4.metric("🕒 Status of Document", doc_report.get("status_of_Document", "Incomplete"))

    st.subheader("📉 Confidence Score Review")
    st.write(f"🔎 **Minimum Confidence Score:** {min_confidence}")

    if threshold <= min_confidence:
        st.success("✅ Confidence level is acceptable.")
    else:
        st.warning("⚠️ Confidence is below the threshold value. Please review manually.")

    st.subheader("📊 Signature Detection Report")
    st.json(result_json)

    st.divider()
    json_bytes = json.dumps(result_json, indent=2).encode("utf-8")
    st.download_button(
        label="⬇️ Download JSON Report",
        data=json_bytes,
        file_name=f"{filename}_signature_report.json",
        mime="application/json"
    )