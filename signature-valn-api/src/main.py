from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import httpx
from dotenv import load_dotenv
import os
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log, RetryError
from .models import SignatureValidationRequest, SignatureValidationResponse
from datetime import datetime
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Define retry configuration for HTTP requests
retry_config = retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError, httpx.ReadTimeout)),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)

# Human-readable error messages for exceptions
ERROR_MESSAGES = {
    httpx.HTTPStatusError: {
        400: "Bad request: The server could not understand the request due to invalid data.",
        401: "Unauthorized: Invalid API key or authentication credentials.",
        403: "Forbidden: Access to the resource is restricted.",
        404: "Not found: The requested resource (e.g., document or smart folder) does not exist.",
        429: "Too many requests: Rate limit exceeded, please try again later.",
        500: "Server error: The server encountered an internal error.",
        "default": "HTTP error occurred while processing the request."
    },
    httpx.RequestError: "Network error: Failed to connect to the API endpoint.",
    httpx.ReadTimeout: "Timeout: The API request took too long to respond.",
    json.JSONDecodeError: "Invalid response: The API returned data that could not be parsed.",
    KeyError: "Unexpected response: The API response is missing required fields.",
    Exception: "Unexpected error: An unknown issue occurred during processing."
}

def get_error_message(exception, status_code=None):
    """Return a human-readable error message based on exception type and status code."""
    if isinstance(exception, RetryError) and exception.last_attempt.failed:
        # Extract the underlying cause of the RetryError
        cause = exception.last_attempt.exception()
        if isinstance(cause, httpx.HTTPStatusError):
            status_code = getattr(cause, 'response', None).status_code if hasattr(cause, 'response') else None
            return ERROR_MESSAGES.get(httpx.HTTPStatusError, {}).get(status_code, ERROR_MESSAGES[httpx.HTTPStatusError]["default"])
        return ERROR_MESSAGES.get(type(cause), ERROR_MESSAGES[Exception])
    if isinstance(exception, httpx.HTTPStatusError) and status_code:
        return ERROR_MESSAGES.get(httpx.HTTPStatusError, {}).get(status_code, ERROR_MESSAGES[httpx.HTTPStatusError]["default"])
    return ERROR_MESSAGES.get(type(exception), ERROR_MESSAGES[Exception])

def parse_response(sr_response, taskId):
    try:
        sr_response_json = json.loads(sr_response)
        doc = sr_response_json["documentReport"]
        pages = sr_response_json["pages"]
        status = doc["status_of_Document"]
        page_count = doc["page_Count"]
        
        # Base message for both Complete and Incomplete status
        base_message = f"Identifi Signature Validation process checked {page_count} pages in the document and assigned status as {status.lower()}. (Reference#: {taskId})"
        
        if status == "Complete":
            return base_message
        elif status == "Incomplete" or status == "OnHold":
            # Group unsigned signers by page
            page_unsigned = {}
            for page in pages:
                page_num = page["pageNumber"]
                zones = page["signatureZones"]
                unsigned_signers = []
                for zone in zones:
                    if zone["status"] == "Unsigned" and zone["zoneSetting"] == "Required":
                        unsigned_signers.append(str(zone["signerNumber"]))
                if unsigned_signers:
                    page_unsigned[page_num] = unsigned_signers
            
            # Create formatted unsigned messages
            unsigned_messages = []
            for page_num, signers in page_unsigned.items():
                signers_str = ",".join(signers)
                unsigned_messages.append(f"Signer(s) [{signers_str}] on Page {page_num} is unsigned.")
            
            # Combine base message with unsigned info
            if unsigned_messages:
                return f"{base_message}\n" + "  ".join(unsigned_messages)
            return base_message
            
        else:
            raise Exception("Unknown document status")
            
    except (json.JSONDecodeError, KeyError) as e:
        raise Exception(get_error_message(e))

async def process_signature_validation(request: SignatureValidationRequest) -> List[SignatureValidationResponse]:
    logger.info(f"taskId={request.taskId}: Processing request")
    
    # Record start time
    start_time = datetime.now()
    
    # Validate environment variables
    signature_api_key = os.getenv("SIGNATURE_API_KEY")
    signature_recognition_api = os.getenv("SIGNATURE_RECOGNITION_API")
    
    if not request.apiKey:
        logger.error(f"taskId={request.taskId}: apiKey is not provided in the request")
        end_time = datetime.now()
        duration_seconds = (end_time - start_time).total_seconds()
        logger.info(f"taskId={request.taskId}: Total processing time: {duration_seconds} seconds")
        return [SignatureValidationResponse(
            taskId=request.taskId,
            status="Failed",
            message="Identifi API key not provided in request",
            sourceFiles=0,
            stored=0,
            errored=0,
            unknown=0
        )]
    if not signature_api_key:
        logger.error(f"taskId={request.taskId}: SIGNATURE_API_KEY environment variable not set")
        end_time = datetime.now()
        duration_seconds = (end_time - start_time).total_seconds()
        logger.info(f"taskId={request.taskId}: Total processing time: {duration_seconds} seconds")
        return [SignatureValidationResponse(
            taskId=request.taskId,
            status="Failed",
            message="Signature API key not configured",
            sourceFiles=0,
            stored=0,
            errored=0,
            unknown=0
        )]
    if not signature_recognition_api:
        logger.error(f"taskId={request.taskId}: SIGNATURE_RECOGNITION_API environment variable not set")
        end_time = datetime.now()
        duration_seconds = (end_time - start_time).total_seconds()
        logger.info(f"taskId={request.taskId}: Total processing time: {duration_seconds} seconds")
        return [SignatureValidationResponse(
            taskId=request.taskId,
            status="Failed",
            message="Signature Recognition API endpoint not configured",
            sourceFiles=0,
            stored=0,
            errored=0,
            unknown=0
        )]

    try:
        # Initialize counters for response
        source_files = 0
        stored = 0
        errored = 0
        unknown = 0

        # Create httpx client with increased timeout
        async with httpx.AsyncClient(timeout=50.0) as client:
            # Step 1: Call Identifi API to get document IDs and application IDs
            export_ids_url = f"{request.apiEndpoint}api/documents/smart-folder/{request.smartFolderId}/export-ids"
            logger.info(f"taskId={request.taskId}: Making GET request to Identifi API: {export_ids_url}")

            @retry_config
            async def fetch_documents():
                response = await client.get(
                    export_ids_url,
                    headers={"X-API-KEY": request.apiKey}
                )
                response.raise_for_status()
                return response

            try:
                response = await fetch_documents()
                documents = response.json()
                source_files = len(documents)
                logger.info(f"taskId={request.taskId}: Received response from Identifi API: status={response.status_code}, documents_count={source_files}")
            except RetryError as e:
                cause = e.last_attempt.exception()
                status_code = getattr(cause, 'response', None).status_code if isinstance(cause, httpx.HTTPStatusError) else None
                error_message = get_error_message(e, status_code)
                logger.error(f"taskId={request.taskId}: Failed to fetch documents after retries: {error_message} (HTTP Status: {status_code if status_code else 'None'})")
                raise cause  # Re-raise the underlying cause
            except (httpx.RequestError, httpx.ReadTimeout) as e:
                error_message = get_error_message(e)
                logger.error(f"taskId={request.taskId}: Failed to fetch documents: {error_message} (HTTP Status: None)")
                raise

            if not documents:
                logger.info(f"taskId={request.taskId}: No documents found in response")
                end_time = datetime.now()
                duration_seconds = (end_time - start_time).total_seconds()
                logger.info(f"taskId={request.taskId}: Total processing time: {duration_seconds} seconds")
                return [SignatureValidationResponse(
                    taskId=request.taskId,
                    status="Failed",
                    message="No documents found in smart folder",
                    sourceFiles=source_files,
                    stored=stored,
                    errored=errored,
                    unknown=unknown
                )]

            # Step 2: Iterate through documents
            for doc in documents:
                document_id = doc.get("documentId")
                application_id = doc.get("applicationId")

                if not document_id or not application_id:
                    logger.error(f"taskId={request.taskId}: Missing documentId or applicationId in document: {doc}")
                    unknown += 1
                    continue

                # Step 3: Fetch document content
                doc_content_url = f"{request.apiEndpoint}api/document/{application_id}/{document_id}/content"
                logger.info(f"taskId={request.taskId}: Making GET request to Identifi API for document content: {doc_content_url}")

                @retry_config
                async def fetch_document_content():
                    response = await client.get(
                        doc_content_url,
                        headers={"X-API-KEY": request.apiKey}
                    )
                    response.raise_for_status()
                    return response

                try:
                    doc_response = await fetch_document_content()
                    # Extract filename with fallback
                    filename = f"document_{document_id}.pdf"
                    if "Content-Disposition" in doc_response.headers:
                        try:
                            disposition = doc_response.headers["Content-Disposition"]
                            filename = disposition.split(";")[1].split("=")[1].replace('"', "")
                        except (IndexError, KeyError):
                            logger.warning(f"taskId={request.taskId}: Could not parse Content-Disposition header, using fallback filename: {filename}")
                    doc_content = doc_response.content
                    logger.info(f"taskId={request.taskId}: Received document content: status={doc_response.status_code}, content_length={len(doc_content)} bytes, filename={filename}")
                except (RetryError, httpx.RequestError, httpx.ReadTimeout) as e:
                    cause = e.last_attempt.exception() if isinstance(e, RetryError) else e
                    status_code = getattr(cause, 'response', None).status_code if isinstance(cause, httpx.HTTPStatusError) else None
                    logger.error(f"taskId={request.taskId}: Failed to fetch document content after retries: {get_error_message(cause, status_code)} (HTTP Status: {status_code if status_code else 'None'})")
                    errored += 1
                    continue

                # Step 4: Call Signature Recognition API with multipart/form-data
                logger.info(f"taskId={request.taskId}: Making POST request to Signature Recognition API: {signature_recognition_api}, document_id={document_id}, file_size={len(doc_content)} bytes")
                start_time_step4 = datetime.now()

                @retry_config
                async def call_signature_api():
                    response = await client.post(
                        signature_recognition_api,
                        files={
                            "file": (
                                filename,
                                doc_content,
                                "application/pdf"
                            )
                        },
                    )
                    response.raise_for_status()
                    return response.json()

                try:
                    sig_result = await call_signature_api()
                    confidence_score = str(int(sig_result['documentReport']['min_confidence_score']*100))
                    logger.info(f"taskId={request.taskId}: Confidence Score: {confidence_score}")
                    end_time_step4 = datetime.now()
                    logger.info(f"taskId={request.taskId}: Received response from Signature Recognition API: document_id={document_id}, result={sig_result}, duration={(end_time_step4 - start_time_step4).total_seconds()} seconds")
                except (RetryError, httpx.RequestError, httpx.ReadTimeout) as e:
                    cause = e.last_attempt.exception() if isinstance(e, RetryError) else e
                    status_code = getattr(cause, 'response', None).status_code if isinstance(cause, httpx.HTTPStatusError) else None
                    logger.error(f"taskId={request.taskId}: Failed to call Signature Recognition API after retries: document_id={document_id}, error={get_error_message(cause, status_code)} (HTTP Status: {status_code if status_code else 'None'})")
                    errored += 1
                    continue

                # Step 5: Update Validation Result Attributes
                try:
                    # Update docAttributeId with confidence score
                    update_doc_attr_url = f"{request.apiEndpoint}api/document/{application_id}/{document_id}/{request.docAttributeId}"
                    logger.info(f"taskId={request.taskId}: Making PUT request to Identifi API to update docAttributeId: {update_doc_attr_url}")

                    @retry_config
                    async def update_doc_attribute():
                        response = await client.put(
                            update_doc_attr_url,
                            json={"value": confidence_score},
                            headers={"X-API-KEY": request.apiKey}
                        )
                        response.raise_for_status()
                        return response

                    update_doc_response = await update_doc_attribute()
                    logger.info(f"taskId={request.taskId}: Successfully updated docAttributeId {request.docAttributeId}: status={update_doc_response.status_code}")

                    # Update resultAttributeId with 'Y' or 'N' if provided
                    if request.resultAttributeId is not None:
                        result_value = 'Y' if float(confidence_score) / 100 >= request.confidenceLevel else 'N'
                        update_result_attr_url = f"{request.apiEndpoint}api/document/{application_id}/{document_id}/{request.resultAttributeId}"
                        logger.info(f"taskId={request.taskId}: Making PUT request to Identifi API to update resultAttributeId: {update_result_attr_url}")

                        @retry_config
                        async def update_result_attribute():
                            response = await client.put(
                                update_result_attr_url,
                                json={"value": result_value},
                                headers={"X-API-KEY": request.apiKey}
                            )
                            response.raise_for_status()
                            return response

                        update_result_response = await update_result_attribute()
                        logger.info(f"taskId={request.taskId}: Successfully updated resultAttributeId {request.resultAttributeId} with value {result_value}: status={update_result_response.status_code}")
                    else:
                        logger.info(f"taskId={request.taskId}: resultAttributeId not provided, skipping update")
                except (RetryError, httpx.RequestError, httpx.ReadTimeout) as e:
                    cause = e.last_attempt.exception() if isinstance(e, RetryError) else e
                    status_code = getattr(cause, 'response', None).status_code if isinstance(cause, httpx.HTTPStatusError) else None
                    logger.error(f"taskId={request.taskId}: Failed to update attributes after retries: {get_error_message(cause, status_code)} (HTTP Status: {status_code if status_code else 'None'})")
                    errored += 1
                    continue

                # Step 6: Update Notes (Summary and Per-Page)
                try:
                    # Parse Signature Recognition API response for notes
                    notes = parse_response(json.dumps(sig_result), request.taskId)
                    logger.info(f"taskId={request.taskId}: Parsed notes for document_id={document_id}")
                except Exception as e:
                    logger.error(f"taskId={request.taskId}: Failed to parse Signature Recognition API response: document_id={document_id}, error={get_error_message(e)}")
                    errored += 1
                    continue

                # Add summary note
                note_id = 0
                update_notes_url = f"{request.apiEndpoint}api/document/{application_id}/{document_id}/notes"
                logger.info(f"taskId={request.taskId}: Making POST request to Identifi API to add summary note: {update_notes_url}")

                @retry_config
                async def add_summary_note():
                    response = await client.post(
                        update_notes_url,
                        json={"id": 0, "text": notes, "page": 1},
                        headers={"X-API-KEY": request.apiKey}
                    )
                    response.raise_for_status()
                    return response

                try:
                    notes_response = await add_summary_note()
                    logger.info(f"taskId={request.taskId}: Successfully added summary note: document_id={document_id}, note_id={note_id}, status={notes_response.status_code}")
                    # Increment stored only if all steps succeed
                    stored += 1
                except (RetryError, httpx.RequestError, httpx.ReadTimeout) as e:
                    cause = e.last_attempt.exception() if isinstance(e, RetryError) else e
                    status_code = getattr(cause, 'response', None).status_code if isinstance(cause, httpx.HTTPStatusError) else None
                    logger.error(f"taskId={request.taskId}: Failed to add summary note after retries: document_id={document_id}, note_id={note_id}, error={get_error_message(cause, status_code)} (HTTP Status: {status_code if status_code else 'None'})")
                    errored += 1
                    continue

            # Record end time and log duration
            end_time = datetime.now()
            duration_seconds = (end_time - start_time).total_seconds()
            logger.info(f"taskId={request.taskId}: Total processing time: {duration_seconds} seconds")

            # Determine status
            if stored == source_files and source_files > 0 and errored == 0:
                status = "Completed"
                message = f"Successfully processed all {source_files} documents with no errors"
            elif source_files > 0:
                status = "Error"
                message = f"Processed {source_files} documents: {stored} stored, {errored} errored, {unknown} unknown"
            else:
                status = "Failed"
                message = "No documents found in smart folder"

            return [SignatureValidationResponse(
                taskId=request.taskId,
                status=status,
                message=message,
                sourceFiles=source_files,
                stored=stored,
                errored=errored,
                unknown=unknown
            )]

    except RetryError as e:
        cause = e.last_attempt.exception() if e.last_attempt.failed else None
        status_code = getattr(cause, 'response', None).status_code if isinstance(cause, httpx.HTTPStatusError) else None
        error_message = get_error_message(e, status_code)
        logger.error(f"taskId={request.taskId}: Error processing request: {error_message} (HTTP Status: {status_code if status_code else 'None'})")
        end_time = datetime.now()
        duration_seconds = (end_time - start_time).total_seconds()
        logger.info(f"taskId={request.taskId}: Total processing time: {duration_seconds} seconds")
        return [SignatureValidationResponse(
            taskId=request.taskId,
            status="Failed",
            message=error_message,
            sourceFiles=0,
            stored=0,
            errored=0,
            unknown=0
        )]
    except httpx.HTTPStatusError as e:
        status_code = getattr(e, 'response', None).status_code if hasattr(e, 'response') else None
        error_message = get_error_message(e, status_code)
        logger.error(f"taskId={request.taskId}: Error processing request: {error_message} (HTTP Status: {status_code if status_code else 'None'})")
        end_time = datetime.now()
        duration_seconds = (end_time - start_time).total_seconds()
        logger.info(f"taskId={request.taskId}: Total processing time: {duration_seconds} seconds")
        return [SignatureValidationResponse(
            taskId=request.taskId,
            status="Failed",
            message=error_message,
            sourceFiles=0,
            stored=0,
            errored=0,
            unknown=0
        )]
    except Exception as e:
        error_message = get_error_message(e)
        logger.error(f"taskId={request.taskId}: Error processing request: {error_message}")
        end_time = datetime.now()
        duration_seconds = (end_time - start_time).total_seconds()
        logger.info(f"taskId={request.taskId}: Total processing time: {duration_seconds} seconds")
        return [SignatureValidationResponse(
            taskId=request.taskId,
            status="Failed",
            message=error_message,
            sourceFiles=0,
            stored=0,
            errored=0,
            unknown=0
        )]

# FastAPI HTTP endpoints
@app.post("/document/signature/validate", response_model=List[SignatureValidationResponse])
async def signature_validation(request: SignatureValidationRequest):
    logger.info(f"taskId={request.taskId}: Received POST request to /document/signature/validate")
    return await process_signature_validation(request)

@app.get("/sample")
async def index():
    logger.info("Received GET request to /sample")
    return {
        "info": "Try /document/signature/validate for signature validation.",
    }