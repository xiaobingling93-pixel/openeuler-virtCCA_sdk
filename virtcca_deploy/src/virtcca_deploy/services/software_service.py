# Copyright (c) Huawei Technologies Co., Ltd., 2026. All rights reserved.

"""
Software service for managing software uploads and processing
Handles file validation, storage, and special processing for specific file types
"""

import hashlib
import logging
import os
import re
from typing import Dict, Tuple, Optional

from virtcca_deploy.common.constants import ValidationError
from virtcca_deploy.services.db_service import VmSoftware
from virtcca_deploy.services.network_config_service import get_network_config_service
from virtcca_deploy.services.dao import get_dao_registry
from virtcca_deploy.common.constants import CVM_MANAGER_SOFTWARE_PATH

logger = logging.getLogger(__name__)


class SoftwareService:
    """
    Service for managing software uploads
    Handles file validation, storage, and special processing for specific file types
    """

    def __init__(self):
        self._lock = __import__('gevent').lock.RLock()
        self.network_config_service = get_network_config_service()
        self._vm_software_dao = get_dao_registry().vm_software_dao

    def upload_software(self, upload_file, file_name: str, file_hash: str, 
                       file_size_str: str, signature: Optional[str] = None) -> Tuple[bool, str, Optional[Dict]]:
        """
        Upload and process software file
        
        :param upload_file: File object from Flask request
        :param file_name: Name of the file
        :param file_hash: Expected hash of the file
        :param file_size_str: Size of the file as string
        :param signature: Optional signature of the file
        :return: (success, message, data)
        """
        with self._lock:
            try:
                # Validate required fields
                if not file_name or not file_hash or not file_size_str:
                    return False, "Missing required fields: file_name, file_hash, file_size", None
                
                # Validate file name format
                if not re.match(r'^[a-zA-Z0-9._\-:]{1,128}$', file_name):
                    return False, "Invalid file_name: must be 1-128 characters, only letters, numbers, and ._-: allowed", None
                
                # Validate file size
                try:
                    file_size = int(file_size_str)
                except ValueError:
                    return False, "Invalid file_size: must be an integer", None
                
                # Validate file
                if upload_file.filename == '':
                    return False, "No selected file", None
                
                # Prevent path traversal attack, keep only the filename part
                original_filename = os.path.basename(upload_file.filename)
                file_type = original_filename.split('.')[-1] if '.' in original_filename else 'Unknown'
                
                logger.info("Received upload software request: file_name=%s, file_type=%s, file_size=%sKB", 
                           file_name, file_type, file_size)

                # Create save directory
                os.makedirs(CVM_MANAGER_SOFTWARE_PATH, exist_ok=True)
                filepath = os.path.join(CVM_MANAGER_SOFTWARE_PATH, file_name)

                # Save file and compute hash
                upload_file.save(filepath)
                
                # Calculate SHA-256 hash of the saved file
                sha256_hash = hashlib.sha256()
                with open(filepath, "rb") as f:
                    # Read file in chunks for hash calculation
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha256_hash.update(byte_block)
                computed_hash = "sha256:" + sha256_hash.hexdigest()
                
                # Verify hash
                if computed_hash != file_hash:
                    os.remove(filepath)  # Delete file
                    return False, f"File hash mismatch: computed_hash={computed_hash}, expected_hash={file_hash}", None
                
                # Special processing for network_config.yaml
                if file_name == 'network_config.yaml':
                    success, error_msg = self._process_network_config(filepath)
                    if not success:
                        os.remove(filepath)
                        return False, f"Network config processing failed: {error_msg}", None
                
                # Check if software with same name already exists
                existing_software = self._vm_software_dao.get_by_file_name(file_name)
                if existing_software:
                    # Update existing record
                    existing_software.file_hash = file_hash
                    existing_software.file_size = file_size
                    existing_software.file_type = file_type
                    existing_software.signature = signature
                    self._vm_software_dao.update(existing_software)
                else:
                    # Create new record
                    new_software = VmSoftware(
                        file_name=file_name,
                        file_hash=file_hash,
                        file_size=file_size,
                        file_type=file_type,
                        signature=signature
                    )
                    self._vm_software_dao.create(new_software)
                
                return True, "", None
                
            except ValidationError as e:
                error_msg = f"Validation error: {str(e)}"
                logger.error(error_msg)
                # Clean up uploaded file if exists
                if 'filepath' in locals() and os.path.exists(filepath):
                    os.remove(filepath)
                return False, error_msg, None
            except Exception as e:
                error_msg = f"Error processing software upload: {str(e)}"
                logger.error(error_msg)
                # Clean up uploaded file if exists
                if 'filepath' in locals() and os.path.exists(filepath):
                    os.remove(filepath)
                return False, error_msg, None

    def get_software_list(self) -> Tuple[bool, str, Optional[Dict]]:
        """
        Get list of uploaded software packages
        
        :return: (success, message, data)
        """
        try:
            # Get all software packages from database
            software_list = self._vm_software_dao.get_all()
            
            # Build response data
            data = {}
            for software in software_list:
                data[software.file_name] = {
                    "file_size": software.file_size,
                    "file_type": software.file_type
                }
            
            return True, "", data
        except Exception as e:
            error_msg = f"Error querying software packages: {str(e)}"
            logger.error(error_msg)
            return False, error_msg, None

    def delete_software(self, file_names: list) -> Tuple[bool, str, Optional[list]]:
        """
        Delete software packages
        
        :param file_names: List of file names to delete
        :return: (success, message, deleted_files)
        """
        
        try:
            deleted_files = []
            not_found_files = []
            
            for fname in file_names:
                # Check if file exists
                software = self._vm_software_dao.get_by_file_name(fname)
                if software:
                    # Delete local file
                    filepath = os.path.join(CVM_MANAGER_SOFTWARE_PATH, fname)
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except Exception as e:
                            logger.error("Error deleting local file %s: %s", fname, e)
                    
                    # Delete from database
                    try:
                        self._vm_software_dao.delete_by_file_name(fname)
                        deleted_files.append(fname)
                    except Exception as e:
                        logger.error("Error deleting software %s from database: %s", fname, e)
                        not_found_files.append(fname)
                else:
                    not_found_files.append(fname)
            
            # Build response
            if not_found_files:
                return False, f"No such software {' '.join(not_found_files)} found", None
            
            return True, "", deleted_files
            
        except Exception as e:
            error_msg = f"Error deleting software: {str(e)}"
            logger.error(error_msg)
            return False, error_msg, None

    def _process_network_config(self, filepath: str) -> Tuple[bool, str]:
        """
        Process network_config.yaml file by validating and storing in database
        
        :param filepath: Path to the network config file
        :return: (success, error_message)
        """
        try:
            logger.info(f"Processing network config file: {filepath}")
            
            # Validate and store the network configuration
            success, error_msg = self.network_config_service.validate_and_store_yaml(filepath)
            
            if success:
                logger.info("Network configuration processed successfully")
            else:
                logger.error(f"Failed to process network configuration: {error_msg}")
            
            return success, error_msg
            
        except Exception as e:
            error_msg = f"Error processing network config: {str(e)}"
            logger.error(error_msg)
            return False, error_msg


# Global instance
_g_software_service = None


def get_software_service() -> SoftwareService:
    """Get or create the global software service instance"""
    global _g_software_service
    if _g_software_service is None:
        _g_software_service = SoftwareService()
    return _g_software_service


def init_software_service():
    """Initialize the software service"""
    global _g_software_service
    _g_software_service = SoftwareService()
    logger.info("Software service initialized")