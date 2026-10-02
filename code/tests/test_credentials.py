"""
Unit tests for credential management
"""

import pytest
import os
import tempfile
from pathlib import Path

from knowledge.credentials import CredentialManager


class TestCredentialManager:
    """Test credential loading from various sources"""
    
    def test_load_from_markdown(self):
        """Test loading credentials from markdown file"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("""# Site Credentials

## - **Site URL**: https://example.com
## - **Login Page**: https://example.com/login
## - **Username**: your_username_here
## - **Password**: your_password_here

- **Site URL**: https://test.example.com
- **Login Page**: https://test.example.com/login
- **Application Name**: Test App
- **Username**: testuser
- **Password**: testpass123
""")
            filepath = f.name
        
        try:
            manager = CredentialManager()
            creds = manager.load_from_markdown(filepath)
            
            assert creds['site_url'] == 'https://test.example.com'
            assert creds['login_page'] == 'https://test.example.com/login'
            assert creds['application_name'] == 'Test App'
            assert creds['username'] == 'testuser'
            assert creds['password'] == 'testpass123'
        finally:
            os.unlink(filepath)

    def test_load_from_env(self, monkeypatch):
        """Test loading credentials from environment variables"""
        monkeypatch.setenv('SITE_URL', 'https://env.example.com')
        monkeypatch.setenv('APPLICATION_NAME', 'Env App')
        monkeypatch.setenv('SITE_USERNAME', 'envuser')
        monkeypatch.setenv('SITE_PASSWORD', 'envpass')
        
        manager = CredentialManager()
        creds = manager.load_from_env()
        
        assert creds['site_url'] == 'https://env.example.com'
        assert creds['application_name'] == 'Env App'
        assert creds['username'] == 'envuser'
        assert creds['password'] == 'envpass'
    
    def test_priority_direct_params(self):
        """Test that direct parameters have highest priority"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("""# Site Credentials

- **Site URL**: https://file.example.com
- **Username**: fileuser
- **Password**: filepass
""")
            filepath = f.name
        
        try:
            manager = CredentialManager()
            creds = manager.load_credentials(
                filepath=filepath,
                site_url='https://direct.example.com',  # Should override file
                username='directuser'  # Should override file
                # password not provided, should come from file
            )
            
            assert creds['site_url'] == 'https://direct.example.com'
            assert creds['username'] == 'directuser'
            assert creds['password'] == 'filepass'
        finally:
            os.unlink(filepath)
    
    def test_missing_credentials_error(self):
        """Test that missing credentials raise an error"""
        manager = CredentialManager()
        
        with pytest.raises(ValueError, match='Missing required credentials'):
            manager.load_credentials(
                site_url='https://example.com'
                # Missing username and password
            )
    
    def test_create_template(self):
        """Test creating a credentials template"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / 'creds.md'
            
            CredentialManager.create_template(str(filepath))
            
            assert filepath.exists()
            content = filepath.read_text()
            assert 'Site URL' in content
            assert 'Application Name' in content
            assert 'Username' in content
            assert 'Password' in content


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
