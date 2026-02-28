import json
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class StateManager:
    """
    Manages persistence of strategy state (e.g., active positions) to JSON files.
    Ensures bot can recover after restart.
    """
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self._ensure_data_dir()
        
    def _ensure_data_dir(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            
    def save_state(self, filename: str, data: Dict[str, Any]) -> bool:
        """Save data to JSON file"""
        filepath = os.path.join(self.data_dir, filename)
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=4, default=str) # default=str handles datetime objects
            return True
        except Exception as e:
            logger.error(f"Failed to save state to {filepath}: {e}")
            return False
            
    def load_state(self, filename: str) -> Optional[Dict[str, Any]]:
        """Load data from JSON file"""
        filepath = os.path.join(self.data_dir, filename)
        if not os.path.exists(filepath):
            return None
            
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load state from {filepath}: {e}")
            return None
            
    def delete_state(self, filename: str) -> bool:
        """Delete state file (e.g. when position closed)"""
        filepath = os.path.join(self.data_dir, filename)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                return True
            except Exception as e:
                logger.error(f"Failed to delete state {filepath}: {e}")
                return False
        return True
