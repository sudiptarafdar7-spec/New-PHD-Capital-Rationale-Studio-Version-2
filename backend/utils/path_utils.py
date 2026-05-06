"""
Shared path utilities for resolving job folder paths and uploaded file paths
"""
import os


def get_workspace_root():
    """
    Get the workspace root directory.
    Works consistently across Replit and VPS deployments.
    
    Returns:
        Absolute path to workspace root
    """
    current_file = os.path.abspath(__file__)
    utils_dir = os.path.dirname(current_file)  # backend/utils/
    backend_dir = os.path.dirname(utils_dir)   # backend/
    workspace_root = os.path.dirname(backend_dir)  # workspace/
    return workspace_root


def resolve_job_folder_path(folder_path):
    """
    Resolve job folder path to absolute path.
    Handles both relative paths (backend/job_files/...) and absolute paths.
    Fixes the double "backend" issue when Flask runs from backend/ directory.
    
    Args:
        folder_path: Path to resolve (e.g., 'backend/job_files/premium-xxx')
    
    Returns:
        Absolute path to the folder
    """
    if not folder_path:
        return None
    
    # If already absolute, return as-is
    if os.path.isabs(folder_path):
        return folder_path
    
    return os.path.join(get_workspace_root(), folder_path)


def resolve_uploaded_file_path(file_path):
    """
    Resolve uploaded file path to absolute path.
    Handles paths that may have been stored with different root directories
    (e.g., Replit vs VPS deployment).
    
    This function extracts the relative path from any absolute path and
    resolves it relative to the current workspace root.
    
    Args:
        file_path: Path to resolve (absolute or relative)
    
    Returns:
        Absolute path that exists on current system, or None if not found
    """
    if not file_path:
        return None
    
    workspace_root = get_workspace_root()
    
    # If already absolute, check if it exists
    if os.path.isabs(file_path):
        if os.path.exists(file_path):
            return file_path
        
        # Path doesn't exist - likely from a different deployment
        # Try to extract the relative portion and resolve locally
        # Common patterns: /home/runner/workspace/backend/... or /home/user/project/backend/...
        
        # Look for 'backend/' in the path and extract from there
        if 'backend/' in file_path:
            idx = file_path.find('backend/')
            relative_path = file_path[idx:]  # e.g., 'backend/uploaded_files/xxx.csv'
            local_path = os.path.join(workspace_root, relative_path)
            if os.path.exists(local_path):
                return local_path
        
        # Try just the filename in the uploaded_files directory
        filename = os.path.basename(file_path)
        fallback_path = os.path.join(workspace_root, 'backend', 'uploaded_files', filename)
        if os.path.exists(fallback_path):
            return fallback_path
        
        # Return the reconstructed path even if it doesn't exist (for error messages)
        if 'backend/' in file_path:
            idx = file_path.find('backend/')
            return os.path.join(workspace_root, file_path[idx:])
        
        return file_path
    
    # Relative path handling
    # Case 1: Path starts with 'backend/' - resolve directly
    if file_path.startswith('backend/'):
        resolved = os.path.join(workspace_root, file_path)
        if os.path.exists(resolved):
            return resolved
        return resolved
    
    # Case 2: Path starts with 'uploaded_files/' - prepend 'backend/'
    if file_path.startswith('uploaded_files/'):
        resolved = os.path.join(workspace_root, 'backend', file_path)
        if os.path.exists(resolved):
            return resolved
        return resolved
    
    # Case 3: Just a filename - look in backend/uploaded_files/
    if '/' not in file_path:
        resolved = os.path.join(workspace_root, 'backend', 'uploaded_files', file_path)
        if os.path.exists(resolved):
            return resolved
        return resolved
    
    # Case 4: Other relative paths - try multiple locations
    # First try as-is from workspace root
    resolved = os.path.join(workspace_root, file_path)
    if os.path.exists(resolved):
        return resolved
    
    # Try prepending 'backend/'
    resolved_with_backend = os.path.join(workspace_root, 'backend', file_path)
    if os.path.exists(resolved_with_backend):
        return resolved_with_backend
    
    # Try just the filename in uploaded_files
    filename = os.path.basename(file_path)
    fallback = os.path.join(workspace_root, 'backend', 'uploaded_files', filename)
    if os.path.exists(fallback):
        return fallback
    
    # Return the most likely path for error messages
    return resolved
