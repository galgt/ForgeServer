"""
Unit tests for Action Executor agent
Uses mocking to avoid real browser automation in tests
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import json
import tempfile

from knowledge.models import (
    SiteKnowledge, PageSchema, PageElement, 
    SelectorStrategy
)
from knowledge.storage import KnowledgeBase
from executor.action_agent import ActionAgent


class TestActionAgent:
    """Test the Action Executor agent"""
    
    def test_find_element_by_name_exact(self):
        """Test finding element by exact name match"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            agent = ActionAgent(kb)
            
            # Create page schema
            page = PageSchema(
                url_pattern='https://example.com',
                elements={
                    'search_box': PageElement(
                        name='search',
                        selectors=SelectorStrategy(primary='#search'),
                        element_type='input'
                    )
                }
            )
            
            # Find by exact match
            element = agent._find_element_by_name(page, 'search_box')
            assert element is not None
            assert element.name == 'search'
    
    def test_find_element_by_name_fuzzy(self):
        """Test finding element by fuzzy name match"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            agent = ActionAgent(kb)
            
            page = PageSchema(
                url_pattern='https://example.com',
                elements={
                    'button_1': PageElement(
                        name='Submit Form',
                        selectors=SelectorStrategy(primary='#submit'),
                        element_type='button'
                    )
                }
            )
            
            # Find by fuzzy match
            element = agent._find_element_by_name(page, 'submit')
            assert element is not None
            assert 'submit' in element.name.lower()
    
    def test_get_knowledge_summary(self):
        """Test generating knowledge summary for LLM"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            
            knowledge = SiteKnowledge(
                site_url='https://example.com',
                pages={
                    'login': PageSchema(url_pattern='https://example.com/login'),
                    'main': PageSchema(url_pattern='https://example.com/main')
                }
            )
            
            kb.save(knowledge, 'test')
            kb.load('test')
            
            agent = ActionAgent(kb)
            summary = agent._get_knowledge_summary()
            
            assert 'example.com' in summary
            assert 'Pages: 2' in summary
            assert 'login' in summary
    
    @pytest.mark.asyncio
    async def test_interpret_basic_search(self):
        """Test basic command interpretation for search"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            agent = ActionAgent(kb)
            
            plan = await agent._interpret_basic('search for products')
            
            assert plan['interpretation'] == 'perform a search'
            assert len(plan['steps']) > 0
            assert plan['steps'][0]['action'] == 'navigate' or plan['steps'][0]['action'] == 'search'
    
    @pytest.mark.asyncio
    async def test_interpret_basic_click(self):
        """Test basic command interpretation for click"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            agent = ActionAgent(kb)
            
            plan = await agent._interpret_basic('click the submit button')
            
            assert 'click' in plan['interpretation'].lower()
            assert plan['steps'][0]['action'] == 'click'

    @pytest.mark.asyncio
    async def test_interpret_basic_click_plus_count(self):
        """Test basic command interpretation for plus icon clicks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            agent = ActionAgent(kb)

            plan = await agent._interpret_basic('click the 2 plus buttons')

            assert plan['steps'][0]['action'] == 'click_plus'
            assert plan['steps'][0]['count'] == 2

    @pytest.mark.asyncio
    async def test_interpret_basic_click_context_and_ordinal(self):
        """Test extracting click target context and ordinal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            agent = ActionAgent(kb)

            plan = await agent._interpret_basic('click the second Network in main menu')

            assert plan['steps'][0]['target'] == 'Network'
            assert plan['steps'][0]['context'] == 'in main menu'
            assert plan['steps'][0]['ordinal'] == 2


@pytest.mark.asyncio
class TestActionAgentWithMock:
    """Test executor with mocked browser"""
    
    async def test_fill_element_with_fallback(self):
        """Test filling element with fallback selectors"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            agent = ActionAgent(kb)
            
            # Mock page
            mock_page = AsyncMock()
            agent.page = mock_page
            
            # First selector fails, second succeeds
            mock_page.fill = AsyncMock(side_effect=[
                Exception("First selector failed"),
                None  # Second selector succeeds
            ])
            
            element = PageElement(
                name='test',
                selectors=SelectorStrategy(
                    primary='#primary',
                    fallbacks=['#fallback']
                ),
                element_type='input'
            )
            
            await agent._fill_element(element, 'test value')
            
            # Should have tried both selectors
            assert mock_page.fill.call_count == 2
    
    async def test_click_element_with_fallback(self):
        """Test clicking element with fallback selectors"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            agent = ActionAgent(kb)
            
            # Mock page
            mock_page = AsyncMock()
            agent.page = mock_page
            
            # First selector fails, second succeeds
            mock_page.click = AsyncMock(side_effect=[
                Exception("First selector failed"),
                None  # Second selector succeeds
            ])
            
            element = PageElement(
                name='test',
                selectors=SelectorStrategy(
                    primary='#primary',
                    fallbacks=['#fallback']
                ),
                element_type='button'
            )
            
            await agent._click_element(element)
            
            # Should have tried both selectors
            assert mock_page.click.call_count == 2
    
    async def test_perform_search(self):
        """Test performing a search"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            agent = ActionAgent(kb)
            
            # Mock page
            mock_page = AsyncMock()
            agent.page = mock_page
            mock_page.fill = AsyncMock()
            mock_page.press = AsyncMock()
            
            await agent._perform_search('test query')
            
            # Should have filled and pressed Enter
            assert mock_page.fill.called
            assert mock_page.press.called
            
            # Check that Enter was pressed
            call_args = mock_page.press.call_args
            assert 'Enter' in str(call_args)

    async def test_click_action_when_not_element(self):
        """Test clicking a learned action that was not stored as an element."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            knowledge = SiteKnowledge(
                site_url='https://example.com',
                pages={
                    'main': PageSchema(
                        url_pattern='https://example.com/main',
                        actions=['Assets']
                    )
                }
            )
            kb.save(knowledge, 'test')
            kb.load('test')

            agent = ActionAgent(kb)
            mock_page = AsyncMock()
            agent.page = mock_page
            mock_page.click = AsyncMock()
            mock_page.wait_for_load_state = AsyncMock()

            plan = {
                'interpretation': 'click on Assets',
                'steps': [
                    {'action': 'click', 'target': 'Assets', 'page': 'main'}
                ]
            }

            result = await agent._execute_plan(plan)

            assert 'Clicked Assets' in result
            mock_page.click.assert_called()

    async def test_click_live_text_when_not_in_schema(self):
        """Test clicking visible text that was not learned in the schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            knowledge = SiteKnowledge(
                site_url='https://example.com',
                pages={
                    'main': PageSchema(url_pattern='https://example.com/main')
                }
            )
            kb.save(knowledge, 'test')
            kb.load('test')

            agent = ActionAgent(kb)
            mock_page = AsyncMock()
            agent.page = mock_page
            mock_page.click = AsyncMock()
            mock_page.wait_for_load_state = AsyncMock()

            plan = {
                'interpretation': 'click on Folders',
                'steps': [
                    {'action': 'click', 'target': 'Folders', 'page': 'main'}
                ]
            }

            result = await agent._execute_plan(plan)

            assert 'Clicked Folders' in result
            mock_page.click.assert_called()

    async def test_execute_click_plus_plan(self):
        """Test executing a plus-button click plan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            agent = ActionAgent(kb)
            agent._click_plus_buttons = AsyncMock(return_value=2)

            plan = {
                'interpretation': 'click 2 plus buttons',
                'steps': [
                    {'action': 'click_plus', 'count': 2}
                ]
            }

            result = await agent._execute_plan(plan)

            assert 'Clicked 2 plus button' in result
            agent._click_plus_buttons.assert_awaited_once_with(2)

    async def test_click_ambiguous_target_returns_clarification(self):
        """Test ambiguous duplicate labels ask for clarification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            knowledge = SiteKnowledge(
                site_url='https://example.com',
                pages={
                    'main': PageSchema(
                        url_pattern='https://example.com/main',
                        elements={
                            'network_1': PageElement(
                                name='Network',
                                label='Network',
                                context='Dashboard submenu',
                                hierarchy_path=['sidebar', 'Dashboard'],
                                selectors=SelectorStrategy(primary='#dashboard-network'),
                                element_type='link'
                            ),
                            'network_2': PageElement(
                                name='Network',
                                label='Network',
                                context='main sidebar',
                                hierarchy_path=['sidebar'],
                                selectors=SelectorStrategy(primary='#main-network'),
                                element_type='link'
                            )
                        }
                    )
                }
            )
            kb.save(knowledge, 'test')
            kb.load('test')

            agent = ActionAgent(kb)
            agent.page = AsyncMock()

            result = await agent._execute_plan({
                'interpretation': 'click Network',
                'steps': [{'action': 'click', 'target': 'Network', 'page': 'main'}]
            })

            assert 'I found 2 matches for "Network"' in result
            assert len(agent.pending_candidates) == 2

    async def test_pending_number_choice_clicks_candidate(self):
        """Test selecting a numbered clarification candidate executes it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            agent = ActionAgent(kb)
            mock_page = AsyncMock()
            agent.page = mock_page
            second = PageElement(
                name='Network',
                selectors=SelectorStrategy(primary='#main-network'),
                element_type='link'
            )
            agent.pending_candidates = [
                {'kind': 'element', 'label': 'Network', 'element': PageElement(name='Network', selectors=SelectorStrategy(primary='#dash-network'), element_type='link')},
                {'kind': 'element', 'label': 'Network', 'element': second}
            ]

            result = await agent.execute_command('2')

            assert 'Clicked Network' in result
            mock_page.click.assert_called_with('#main-network')

    async def test_click_context_resolves_main_menu(self):
        """Test context words resolve the intended duplicate target."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            knowledge = SiteKnowledge(
                site_url='https://example.com',
                pages={
                    'main': PageSchema(
                        url_pattern='https://example.com/main',
                        elements={
                            'network_1': PageElement(
                                name='Network',
                                label='Network',
                                context='Dashboard submenu',
                                hierarchy_path=['sidebar', 'Dashboard'],
                                selectors=SelectorStrategy(primary='#dashboard-network'),
                                element_type='link'
                            ),
                            'network_2': PageElement(
                                name='Network',
                                label='Network',
                                context='main sidebar',
                                hierarchy_path=['sidebar'],
                                selectors=SelectorStrategy(primary='#main-network'),
                                element_type='link'
                            )
                        }
                    )
                }
            )
            kb.save(knowledge, 'test')
            kb.load('test')
            agent = ActionAgent(kb)
            mock_page = AsyncMock()
            agent.page = mock_page

            result = await agent._execute_plan({
                'interpretation': 'click Network in main menu',
                'steps': [{'action': 'click', 'target': 'Network', 'context': 'in main menu', 'page': 'main'}]
            })

            assert 'Clicked Network' in result
            mock_page.click.assert_called_with('#main-network')

    async def test_click_context_resolves_under_dashboard(self):
        """Test parent context resolves the intended duplicate target."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            knowledge = SiteKnowledge(
                site_url='https://example.com',
                pages={
                    'main': PageSchema(
                        url_pattern='https://example.com/main',
                        elements={
                            'network_1': PageElement(
                                name='Network',
                                label='Network',
                                context='Dashboard submenu',
                                parent_label='Dashboard',
                                hierarchy_path=['sidebar', 'Dashboard'],
                                selectors=SelectorStrategy(primary='#dashboard-network'),
                                element_type='link'
                            ),
                            'network_2': PageElement(
                                name='Network',
                                label='Network',
                                context='main sidebar',
                                hierarchy_path=['sidebar'],
                                selectors=SelectorStrategy(primary='#main-network'),
                                element_type='link'
                            )
                        }
                    )
                }
            )
            kb.save(knowledge, 'test')
            kb.load('test')
            agent = ActionAgent(kb)
            mock_page = AsyncMock()
            agent.page = mock_page

            result = await agent._execute_plan({
                'interpretation': 'click Network under Dashboard',
                'steps': [{'action': 'click', 'target': 'Network', 'context': 'under Dashboard', 'page': 'main'}]
            })

            assert 'Clicked Network' in result
            mock_page.click.assert_called_with('#dashboard-network')

    async def test_click_second_network_resolves_by_ordinal(self):
        """Test ordinal targeting resolves duplicate labels."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            knowledge = SiteKnowledge(
                site_url='https://example.com',
                pages={
                    'main': PageSchema(
                        url_pattern='https://example.com/main',
                        elements={
                            'network_1': PageElement(name='Network', selectors=SelectorStrategy(primary='#first'), element_type='link'),
                            'network_2': PageElement(name='Network', selectors=SelectorStrategy(primary='#second'), element_type='link')
                        }
                    )
                }
            )
            kb.save(knowledge, 'test')
            kb.load('test')
            agent = ActionAgent(kb)
            mock_page = AsyncMock()
            agent.page = mock_page

            result = await agent._execute_plan({
                'interpretation': 'click second Network',
                'steps': [{'action': 'click', 'target': 'Network', 'ordinal': 2, 'page': 'main'}]
            })

            assert 'Clicked Network' in result
            mock_page.click.assert_called_with('#second')

    async def test_llm_valid_json_plan_is_parsed(self):
        """Test valid LLM JSON response is used as an executable plan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            agent = ActionAgent(kb)

            class FakeMessages:
                def create(self, **kwargs):
                    return type('Response', (), {
                        'content': [type('Content', (), {
                            'text': json.dumps({
                                'interpretation': 'click assets',
                                'steps': [{'action': 'click', 'target': 'Assets', 'page': 'main'}]
                            })
                        })()]
                    })()

            agent.anthropic_client = type('Client', (), {'messages': FakeMessages()})()

            plan = await agent._interpret_with_llm('click Assets')

            assert plan['steps'][0]['action'] == 'click'
            assert plan['steps'][0]['target'] == 'Assets'

    async def test_llm_invalid_response_falls_back(self):
        """Test invalid LLM output falls back to basic interpretation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            agent = ActionAgent(kb)

            class FakeMessages:
                def create(self, **kwargs):
                    return type('Response', (), {
                        'content': [type('Content', (), {'text': 'not json'})()]
                    })()

            agent.anthropic_client = type('Client', (), {'messages': FakeMessages()})()

            plan = await agent._interpret_with_llm('click Assets')

            assert plan['steps'][0]['action'] == 'click'
            assert plan['steps'][0]['target'] == 'Assets'


@pytest.mark.asyncio
class TestActionAgentIntegration:
    """Integration tests for action agent"""
    
    async def test_execute_plan_with_mock_knowledge(self):
        """Test executing a plan with mocked knowledge base"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_dir=tmpdir)
            
            # Create knowledge
            knowledge = SiteKnowledge(
                site_url='https://example.com',
                pages={
                    'main': PageSchema(
                        url_pattern='https://example.com/main',
                        elements={
                            'test_button': PageElement(
                                name='Test Button',
                                selectors=SelectorStrategy(primary='#test'),
                                element_type='button'
                            )
                        }
                    )
                }
            )
            
            kb.save(knowledge, 'test')
            kb.load('test')
            
            agent = ActionAgent(kb)
            
            # Mock page
            mock_page = AsyncMock()
            agent.page = mock_page
            mock_page.click = AsyncMock()
            
            # Execute a simple click plan
            plan = {
                'interpretation': 'click button',
                'steps': [
                    {'action': 'click', 'element': 'test_button', 'page': 'main'}
                ]
            }
            
            result = await agent._execute_plan(plan)
            
            assert '✅' in result
            assert 'test_button' in result.lower() or 'clicked' in result.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
