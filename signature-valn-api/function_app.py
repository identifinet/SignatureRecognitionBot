import azure.functions as func
import json
import logging
from src.main import app as fastapi_app, process_signature_validation
from src.models import SignatureValidationRequest, SignatureValidationResponse
from azure.storage.queue import QueueClient
import os
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    json.JSONDecodeError: "Invalid queue message: The message format is not valid JSON.",
    ValueError: "Invalid queue message: The message could not be processed.",
    Exception: "Unexpected error: An unknown issue occurred during processing."
}

def get_error_message(exception, status_code=None):
    """Return a human-readable error message based on exception type and status code."""
    if isinstance(exception, httpx.HTTPStatusError) and status_code:
        return ERROR_MESSAGES.get(httpx.HTTPStatusError, {}).get(status_code, ERROR_MESSAGES[httpx.HTTPStatusError]["default"])
    return ERROR_MESSAGES.get(type(exception), ERROR_MESSAGES[Exception])

# Initialize Azure Function App
function_app = func.FunctionApp()

# HTTP-triggered Azure Function
@function_app.function_name(name="HttpTrigger")
@function_app.route(route="{*route}", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    try:
        # Extract taskId from request body for POST requests
        task_id = "unknown"
        if req.method == "POST":
            try:
                req_body = await req.get_json()
                task_id = req_body.get("taskId", "unknown")
            except ValueError:
                logger.warning("taskId=unknown: Failed to parse request body for taskId")
        
        logger.info(f"taskId={task_id}: Received HTTP request: method={req.method}, url={req.url}, route={req.route_params.get('route', '')}")
        response = await func.AsgiMiddleware(fastapi_app).handle_async(req)
        logger.info(f"taskId={task_id}: HTTP response: status={response.status_code}, body={response.get_body().decode('utf-8')}")
        return response
    
    except Exception as e:
        error_message = get_error_message(e)
        logger.error(f"taskId={task_id}: Error processing HTTP request: {error_message}")
        return func.HttpResponse(
            f"Error: {error_message}",
            status_code=500
        )

# Queue-triggered Azure Function
@function_app.queue_trigger(
    arg_name="msg",
    queue_name="signature-validation",
    connection="AzureWebJobsStorage"
)
async def queue_trigger(msg: func.QueueMessage) -> None:
    task_id = "unknown"
    try:
        # Parse queue message
        message_body = msg.get_body().decode('utf-8')
        logger.info(f"taskId={task_id}: Received queue message: {message_body}")
        
        # Convert JSON message to SignatureValidationRequest
        try:
            message_data = json.loads(message_body)
            task_id = message_data.get("taskId", "unknown")
            # Skip completed messages to prevent infinite loops
            if message_data.get("status") == "completed":
                logger.info(f"taskId={task_id}: Skipping completed message")
                return
            request = SignatureValidationRequest(**message_data)
        except (json.JSONDecodeError, ValueError) as e:
            error_message = get_error_message(e)
            logger.error(f"taskId={task_id}: Invalid queue message format: {error_message}")
            # Send failed response
            try:
                queue_client = QueueClient.from_connection_string(
                    conn_str=os.getenv("AzureWebJobsStorage"),
                    queue_name="signature-validation"
                )
                response_message = {
                    "taskId": task_id,
                    "source": "Identifi Signature Validator",
                    "status": "Failed",
                    "message": error_message,
                    "sourceFiles": 0,
                    "stored": 0,
                    "errored": 0,
                    "unknown": 0
                }
                queue_client.send_message(json.dumps(response_message))
                logger.info(f"taskId={task_id}: Sent failed response message to queue: {json.dumps(response_message)}")
            except Exception as send_e:
                error_message = get_error_message(send_e)
                logger.error(f"taskId={task_id}: Failed to send failed message to queue: {error_message}")
            return

        # Process the request using the shared logic from main.py
        results = await process_signature_validation(request)
        logger.info(f"taskId={task_id}: Queue processing completed: results_count={len(results)}")

        logger.info(f"taskId={task_id}: Results: {results}")
        # Log results
        for result in results:
            logger.info(f"taskId={task_id}: Processed taskId={result.taskId}, status={result.status}, message={result.message}")

        # Send results back to the queue
        try:
            queue_client = QueueClient.from_connection_string(
                conn_str=os.getenv("AzureWebJobsStorage"),
                queue_name="signature-validation"
            )
            for result in results:
                response_message = {
                    "taskId": result.taskId,
                    "source": result.source,
                    "status": result.status,
                    "message": result.message,
                    "sourceFiles": result.sourceFiles,
                    "stored": result.stored,
                    "errored": result.errored,
                    "unknown": result.unknown
                }
                queue_client.send_message(json.dumps(response_message))
                logger.info(f"taskId={task_id}: Sent response message to queue: {json.dumps(response_message)}")
        except Exception as e:
            error_message = get_error_message(e)
            logger.error(f"taskId={task_id}: Failed to send message to queue: {error_message}")

    except Exception as e:
        error_message = get_error_message(e)
        logger.error(f"taskId={task_id}: Error processing queue message: {error_message}")
        # Send failed response if possible
        try:
            task_id = request.taskId if 'request' in locals() else message_data.get("taskId", "unknown") if 'message_data' in locals() else task_id
            queue_client = QueueClient.from_connection_string(
                conn_str=os.getenv("AzureWebJobsStorage"),
                queue_name="signature-validation"
            )
            response_message = {
                "taskId": task_id,
                "source": "Identifi Signature Validator",
                "status": "Failed",
                "message": error_message,
                "sourceFiles": 0,
                "stored": 0,
                "errored": 0,
                "unknown": 0
            }
            queue_client.send_message(json.dumps(response_message))
            logger.info(f"taskId={task_id}: Sent failed response message to queue: {json.dumps(response_message)}")
        except Exception as send_e:
            error_message = get_error_message(send_e)
            logger.error(f"taskId={task_id}: Failed to send failed message to queue: {error_message}")