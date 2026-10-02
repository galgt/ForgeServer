"""
Unit tests for knowledge base models and storage
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime

from knowledge.models import (
    SelectorStrategy, PageElement, PageSchema, 
    Workflow, SiteKnowledge
)
from knowledge.storage import KnowledgeBase


class TestModels:
    """Test knowledge base data models"""
    
    def test_selector_strategy_creation(self):
        """Test creating a selector strategy"""
        selector = SelectorStrategy(
            primary='#username',
            fallbacks=['input[name="username"]', 'input[type="text"]']
        )
        assert selector.primary == '#username'
        assert len(selector.fallbacks) == 2
    
    def test_page_element_creation(self):
        """Test creating a page element"""
        element = PageElement(
            name='username',
            selectors=SelectorStrategy(primary='#username'),
            element_type='input',
            required=True
        )
        assert element.name == 'username'
        assert element.required is True
    
    def test_page_schema_creation(self):
        """Test creating a page schema"""
        page = PageSchema(
            url_pattern='https://example.com/login',
            title='Login Page',
            elements={
                'username': PageElement(
                    name='username',
                    selectors=SelectorStrategy(primary='#username'),
                    element_type='input'
                )
            },
            actions=['login']
        )
        assert page.url_pattern == 'https://example.com/login'
        assert 'username' in page.elements
        assert 'login' in page.actions
    
    def test_workflow_creation(self):
        """Test creating a workflow"""
        workflow = Workflow(
            name='login',
            description='Login to the site',
            steps=['navigate', 'fill_credentials', 'submit'],
            required_pages=['login']
        )
        assert workflow.name == 'login'
        assert len(workflow.steps) == 3
    
    def test_site_knowledge_creation(self):
        """Test creating site knowledge"""
        knowledge = SiteKnowledge(
            site_url='https://example.com',
            site_name='example_com'
        )
        assert knowledge.site_url == 'https://example.com'
        assert knowledge.site_name == 'example_com'
        assert isinstance(knowledge.last_updated, datetime)


class TestKnowledgeBase:
    """Test knowledge base storage"""
    
    def test_save_and_load(self):
        """Test saving and loading knowledge"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            
            # Create knowledge
            knowledge = SiteKnowledge(
                site_url='https://example.com',
                site_name='test_site',
                pages={
                    'login': PageSchema(
                        url_pattern='https://example.com/login',
                        title='Login'
                    )
                }
            )
            
            # Save
            filepath = kb.save(knowledge, 'test_site')
            assert filepath.exists()
            
            # Load
            loaded = kb.load('test_site')
            assert loaded is not None
            assert loaded.site_url == 'https://example.com'
            assert 'login' in loaded.pages
    
    def test_get_page(self):
        """Test retrieving a specific page"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            
            knowledge = SiteKnowledge(
                site_url='https://example.com',
                pages={
                    'login': PageSchema(
                        url_pattern='https://example.com/login',
                        title='Login'
                    )
                }
            )
            
            kb.save(knowledge, 'test')
            kb.load('test')
            
            page = kb.get_page('login')
            assert page is not None
            assert page.title == 'Login'
    
    def test_update_page(self):
        """Test updating a page schema"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            
            knowledge = SiteKnowledge(site_url='https://example.com')
            kb.save(knowledge, 'test')
            kb.load('test')
            
            # Add a new page
            new_page = PageSchema(
                url_pattern='https://example.com/dashboard',
                title='Dashboard'
            )
            kb.update_page('dashboard', new_page)
            
            # Verify
            page = kb.get_page('dashboard')
            assert page is not None
            assert page.title == 'Dashboard'
    
    def test_list_available(self):
        """Test listing available knowledge bases"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            
            # Create multiple knowledge bases
            for i in range(3):
                knowledge = SiteKnowledge(site_url=f'https://example{i}.com')
                kb.save(knowledge, f'site_{i}')
            
            # List them
            sites = kb.list_available()
            assert len(sites) == 3
            assert 'site_0' in sites


@pytest.mark.asyncio
class TestIntegration:
    """Integration tests for the full system"""
    
    def test_knowledge_persistence(self):
        """Test that knowledge persists across saves and loads"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            
            # Create complex knowledge structure
            knowledge = SiteKnowledge(
                site_url='https://example.com',
                site_name='example_com',
                pages={
                    'login': PageSchema(
                        url_pattern='https://example.com/login',
                        elements={
                            'username': PageElement(
                                name='username',
                                selectors=SelectorStrategy(
                                    primary='#username',
                                    fallbacks=['input[name="user"]']
                                ),
                                element_type='input'
                            )
                        }
                    )
                },
                workflows={
                    'login': Workflow(
                        name='login',
                        description='Login workflow',
                        steps=['enter_username', 'enter_password', 'submit']
                    )
                }
            )
            
            # Save
            kb.save(knowledge, 'example_com')
            
            # Create new KB instance and load
            kb2 = KnowledgeBase(storage_dir=tmpdir)
            loaded = kb2.load('example_com')
            
            # Verify everything persisted
            assert loaded.site_url == knowledge.site_url
            assert 'login' in loaded.pages
            assert 'username' in loaded.pages['login'].elements
            assert loaded.pages['login'].elements['username'].selectors.primary == '#username'
            assert 'login' in loaded.workflows


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
