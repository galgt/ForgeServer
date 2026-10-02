"""
Unit tests for Site Learner agent
Uses mocking to avoid real browser automation in tests
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from knowledge.models import PageSchema, SelectorStrategy
from knowledge.storage import KnowledgeBase
from learner.site_mapper import SiteLearner


class TestSiteLearner:
    """Test the Site Learner agent"""
    
    def test_get_site_identifier(self):
        """Test extracting site identifier from URL"""
        assert SiteLearner._get_site_identifier('https://example.com') == 'example_com'
        assert SiteLearner._get_site_identifier('https://test.example.com:8080') == 'test_example_com_8080'
        assert SiteLearner._get_site_identifier('https://sub.domain.com') == 'sub_domain_com'
        assert SiteLearner._get_site_identifier('Fortinet AWS') == 'fortinet_aws'
        assert SiteLearner._get_site_identifier('fortinet_aws.json') == 'fortinet_aws'
    
    @pytest.mark.asyncio
    async def test_find_input_field(self):
        """Test finding input field selectors"""
        kb = KnowledgeBase()
        learner = SiteLearner(kb)
        
        # Mock page with query_selector
        mock_page = AsyncMock()
        mock_element = Mock()
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        
        # Test finding username field
        strategy = await learner._find_input_field(mock_page, ['username', 'user'])
        
        assert strategy.primary is not None
        assert 'username' in strategy.primary.lower() or 'user' in strategy.primary.lower()
    
    @pytest.mark.asyncio
    async def test_find_submit_button(self):
        """Test finding submit button selectors"""
        kb = KnowledgeBase()
        learner = SiteLearner(kb)
        
        # Mock page
        mock_page = AsyncMock()
        mock_button = Mock()
        mock_page.query_selector = AsyncMock(return_value=mock_button)
        
        strategy = await learner._find_submit_button(mock_page)
        
        assert strategy.primary is not None
        assert 'submit' in strategy.primary.lower() or 'button' in strategy.primary.lower()

    @pytest.mark.asyncio
    async def test_extract_interactive_elements_with_context(self):
        """Test learner stores duplicate labels with hierarchy/context metadata."""
        kb = KnowledgeBase()
        learner = SiteLearner(kb)
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[
            {
                'index': 0,
                'tag': 'a',
                'role': 'link',
                'text': 'Network',
                'label': 'Network',
                'context': 'Dashboard submenu',
                'parent_label': 'Dashboard',
                'hierarchy_path': ['sidebar', 'Dashboard'],
                'attributes': {'href': '/dashboard/network'},
                'position': {'x': 1, 'y': 100, 'width': 80, 'height': 20, 'order': 0}
            },
            {
                'index': 1,
                'tag': 'a',
                'role': 'link',
                'text': 'Network',
                'label': 'Network',
                'context': 'main sidebar',
                'parent_label': 'sidebar',
                'hierarchy_path': ['sidebar'],
                'attributes': {'href': '/network'},
                'position': {'x': 1, 'y': 500, 'width': 80, 'height': 20, 'order': 1}
            },
            {
                'index': 2,
                'tag': 'button',
                'role': 'button',
                'text': '',
                'label': '',
                'context': 'DNS Settings form',
                'parent_label': 'DNS Settings',
                'hierarchy_path': ['main', 'DNS Settings'],
                'attributes': {'title': 'Add'},
                'position': {'x': 100, 'y': 200, 'width': 20, 'height': 20, 'order': 2}
            }
        ])

        elements = await learner._extract_interactive_elements(mock_page, 'main')

        networks = [element for element in elements.values() if element.name == 'Network']
        assert len(networks) == 2
        assert {element.context for element in networks} == {'Dashboard submenu', 'main sidebar'}
        assert any(element.element_type == 'icon_button' for element in elements.values())
    
    def test_identify_workflows(self):
        """Test workflow identification"""
        kb = KnowledgeBase()
        learner = SiteLearner(kb)
        
        from knowledge.models import SiteKnowledge, PageElement
        
        # Create mock knowledge with search elements
        knowledge = SiteKnowledge(
            site_url='https://example.com',
            pages={
                'main': PageSchema(
                    url_pattern='https://example.com/main',
                    elements={
                        'search': PageElement(
                            name='search box',
                            selectors=SelectorStrategy(primary='#search'),
                            element_type='input'
                        )
                    }
                )
            }
        )
        
        workflows = learner._identify_workflows(knowledge)
        
        # Should always have login workflow
        assert 'login' in workflows
        
        # Should detect search workflow
        assert 'search' in workflows
        assert len(workflows['search'].steps) > 0


@pytest.mark.asyncio
class TestSiteLearnerIntegration:
    """Integration tests for learner with mocked browser"""
    
    async def test_learn_login_page_structure(self):
        """Test that learner correctly structures login page data"""
        kb = KnowledgeBase()
        learner = SiteLearner(kb)
        
        # Create a more realistic mock
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.title = AsyncMock(return_value='Login Page')
        mock_page.fill = AsyncMock()
        mock_page.click = AsyncMock()
        
        # Mock element finding
        mock_element = Mock()
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        
        credentials = {
            'username': 'testuser',
            'password': 'testpass'
        }
        
        schema = await learner._learn_login_page(
            mock_page,
            'https://example.com/login',
            credentials
        )
        
        # Verify schema structure
        assert schema.url_pattern == 'https://example.com/login'
        assert 'username' in schema.elements
        assert 'password' in schema.elements
        assert 'submit' in schema.elements
        assert 'login' in schema.actions
        
        # Verify elements are properly configured
        assert schema.elements['username'].required is True
        assert schema.elements['password'].required is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
