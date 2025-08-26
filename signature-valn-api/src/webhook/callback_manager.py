"""
Callback manager for handling asynchronous callbacks
"""

import json
import logging
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import asyncio
import threading
import time

logger = logging.getLogger(__name__)

class CallbackManager:
    """Manages asynchronous callbacks to external systems"""
    
    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.pending_callbacks: List[Dict[str, Any]] = []
        self.completed_callbacks: List[Dict[str, Any]] = []
        self.failed_callbacks: List[Dict[str, Any]] = []
        
        # Start background thread for processing callbacks
        self._running = True
        self._callback_thread = threading.Thread(target=self._process_callbacks, daemon=True)
        self._callback_thread.start()
    
    def add_callback(self, callback_url: str, payload: Dict[str, Any], 
                    callback_id: Optional[str] = None) -> str:
        """Add a new callback to the queue"""
        if not callback_id:
            callback_id = f"cb_{int(time.time())}_{len(self.pending_callbacks)}"
        
        callback = {
            'id': callback_id,
            'url': callback_url,
            'payload': payload,
            'status': 'pending',
            'retry_count': 0,
            'created_at': datetime.utcnow().isoformat(),
            'last_attempt': None,
            'error_message': None
        }
        
        self.pending_callbacks.append(callback)
        logger.info(f"Added callback {callback_id} to queue")
        return callback_id
    
    def _process_callbacks(self):
        """Background thread for processing callbacks"""
        while self._running:
            try:
                if self.pending_callbacks:
                    callback = self.pending_callbacks.pop(0)
                    self._execute_callback(callback)
                
                time.sleep(1)  # Check every second
                
            except Exception as e:
                logger.error(f"Error in callback processing thread: {str(e)}")
                time.sleep(5)  # Wait longer on error
    
    def _execute_callback(self, callback: Dict[str, Any]):
        """Execute a single callback"""
        try:
            callback['last_attempt'] = datetime.utcnow().isoformat()
            
            # Make HTTP request
            response = requests.post(
                callback['url'],
                json=callback['payload'],
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            if response.status_code in [200, 201, 202]:
                # Success
                callback['status'] = 'completed'
                callback['completed_at'] = datetime.utcnow().isoformat()
                self.completed_callbacks.append(callback)
                logger.info(f"Callback {callback['id']} completed successfully")
                
            else:
                # Failed - retry if possible
                self._handle_callback_failure(callback, f"HTTP {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            # Network error - retry if possible
            self._handle_callback_failure(callback, f"Network error: {str(e)}")
            
        except Exception as e:
            # Other error - retry if possible
            self._handle_callback_failure(callback, f"Unexpected error: {str(e)}")
    
    def _handle_callback_failure(self, callback: Dict[str, Any], error_message: str):
        """Handle callback failure and determine retry strategy"""
        callback['error_message'] = error_message
        callback['retry_count'] += 1
        
        if callback['retry_count'] <= self.max_retries:
            # Retry after delay
            callback['status'] = 'retrying'
            callback['next_retry'] = (
                datetime.utcnow() + timedelta(seconds=self.retry_delay * callback['retry_count'])
            ).isoformat()
            
            # Add back to pending queue for retry
            self.pending_callbacks.append(callback)
            logger.warning(f"Callback {callback['id']} failed, will retry {callback['retry_count']}/{self.max_retries}")
            
        else:
            # Max retries exceeded
            callback['status'] = 'failed'
            callback['failed_at'] = datetime.utcnow().isoformat()
            self.failed_callbacks.append(callback)
            logger.error(f"Callback {callback['id']} failed after {self.max_retries} retries")
    
    def get_callback_status(self, callback_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific callback"""
        # Check pending callbacks
        for callback in self.pending_callbacks:
            if callback['id'] == callback_id:
                return callback
        
        # Check completed callbacks
        for callback in self.completed_callbacks:
            if callback['id'] == callback_id:
                return callback
        
        # Check failed callbacks
        for callback in self.failed_callbacks:
            if callback['id'] == callback_id:
                return callback
        
        return None
    
    def get_callback_summary(self) -> Dict[str, Any]:
        """Get summary of all callbacks"""
        return {
            'pending': len(self.pending_callbacks),
            'completed': len(self.completed_callbacks),
            'failed': len(self.failed_callbacks),
            'total': len(self.pending_callbacks) + len(self.completed_callbacks) + len(self.failed_callbacks),
            'timestamp': datetime.utcnow().isoformat()
        }
    
    def retry_failed_callback(self, callback_id: str) -> bool:
        """Manually retry a failed callback"""
        failed_callback = None
        
        # Find and remove from failed list
        for i, callback in enumerate(self.failed_callbacks):
            if callback['id'] == callback_id:
                failed_callback = self.failed_callbacks.pop(i)
                break
        
        if not failed_callback:
            logger.warning(f"Failed callback {callback_id} not found")
            return False
        
        # Reset for retry
        failed_callback['status'] = 'pending'
        failed_callback['retry_count'] = 0
        failed_callback['error_message'] = None
        failed_callback['next_retry'] = None
        
        # Add back to pending queue
        self.pending_callbacks.append(failed_callback)
        logger.info(f"Manually retrying failed callback {callback_id}")
        return True
    
    def clear_completed_callbacks(self, max_age_hours: int = 24):
        """Clear old completed callbacks to free memory"""
        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        # Filter out old completed callbacks
        old_callbacks = []
        remaining_callbacks = []
        
        for callback in self.completed_callbacks:
            completed_at = datetime.fromisoformat(callback['completed_at'])
            if completed_at < cutoff_time:
                old_callbacks.append(callback)
            else:
                remaining_callbacks.append(callback)
        
        self.completed_callbacks = remaining_callbacks
        
        if old_callbacks:
            logger.info(f"Cleared {len(old_callbacks)} old completed callbacks")
    
    def shutdown(self):
        """Shutdown the callback manager"""
        self._running = False
        if self._callback_thread.is_alive():
            self._callback_thread.join(timeout=5)
        logger.info("Callback manager shutdown complete")
