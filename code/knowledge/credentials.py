"""
Utilities for managing credentials and configuration.
Supports loading from .env files, credentials.md, or direct parameters.
"""

import os
import re
from typing import Dict, Optional
from pathlib import Path
from dotenv import load_dotenv


class CredentialManager:
    """Manages site credentials from various sources"""
    
    def __init__(self):
        load_dotenv()
    
    def load_from_env(self) -> Dict[str, str]:
        """Load credentials from environment variables"""
        return {
            'application_name': os.getenv('APPLICATION_NAME', ''),
            'site_url': os.getenv('SITE_URL', ''),
            'username': os.getenv('SITE_USERNAME', ''),
            'password': os.getenv('SITE_PASSWORD', '')
        }
    
    def load_from_markdown(self, filepath: str = 'credentials.md') -> Dict[str, str]:
        """Load credentials from a markdown file"""
        if not Path(filepath).exists():
            raise FileNotFoundError(f"Credentials file not found: {filepath}")
        
        with open(filepath, 'r') as f:
            content = f.read()
        
        credentials = {}
        
        # Parse markdown for credential fields
        patterns = {
            'application_name': r'^\s*-\s*\*\*Application Name\*\*:\s*(.+)',
            'site_url': r'^\s*-\s*\*\*Site URL\*\*:\s*(.+)',
            'login_page': r'^\s*-\s*\*\*Login Page\*\*:\s*(.+)',
            'username': r'^\s*-\s*\*\*Username\*\*:\s*(.+)',
            'password': r'^\s*-\s*\*\*Password\*\*:\s*(.+)',
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, content, re.MULTILINE)
            if match:
                credentials[key] = match.group(1).strip()
        
        # Use site_url as login_page if not specified
        if 'site_url' in credentials and 'login_page' not in credentials:
            credentials['login_page'] = credentials['site_url']
        
        return credentials
    
    def load_credentials(self, 
                        filepath: Optional[str] = None,
                        site_url: Optional[str] = None,
                        username: Optional[str] = None,
                        password: Optional[str] = None) -> Dict[str, str]:
        """
        Load credentials with priority: direct params > markdown file > env vars
        """
        credentials = {}
        
        # Start with env vars as base
        credentials.update(self.load_from_env())
        
        # Override with markdown file if provided
        if filepath:
            try:
                credentials.update(self.load_from_markdown(filepath))
            except FileNotFoundError:
                print(f"⚠️  Credentials file {filepath} not found, using env vars")
        
        # Override with direct parameters if provided
        if site_url:
            credentials['site_url'] = site_url
        if username:
            credentials['username'] = username
        if password:
            credentials['password'] = password
        
        # Validate required fields
        required = ['site_url', 'username', 'password']
        missing = [field for field in required if not credentials.get(field)]
        
        if missing:
            raise ValueError(f"Missing required credentials: {', '.join(missing)}")
        
        return credentials
    
    @staticmethod
    def create_template(filepath: str = 'credentials.md'):
        """Create a credentials template file"""
        template = """# Site Credentials

**IMPORTANT**: Add this file to your `.gitignore`!

---

## Target Site Information

- **Site URL**: https://example.com
- **Login Page**: https://example.com/login
- **Application Name**: example_app
- **Username**: your_username_here
- **Password**: your_password_here

## Additional Notes

Add any special instructions about the login process or site navigation here.
"""
        with open(filepath, 'w') as f:
            f.write(template)
        
        print(f"✅ Created credentials template at {filepath}")
        print("Please edit this file with your actual credentials")
