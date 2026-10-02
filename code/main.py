"""
Main CLI interface for the Web Agent System
Provides commands to run the learner and executor agents.
"""

import asyncio
import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from knowledge.storage import KnowledgeBase
from knowledge.credentials import CredentialManager
from learner.site_mapper import SiteLearner
from executor.action_agent import ActionAgent


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


class WebAgentCLI:
    """Command-line interface for web agent system"""
    
    def __init__(self):
        self.kb = KnowledgeBase()
        self.cred_manager = CredentialManager()

    def _default_credentials_file(self) -> Optional[str]:
        """Find credentials.md in the usual launch locations."""
        candidates = [
            Path.cwd() / "credentials.md",
            Path(__file__).resolve().parent / "credentials.md",
        ]

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        return None
    
    async def run_learner(self, 
                         credentials_file: str = None,
                         site_url: str = None,
                         username: str = None,
                         password: str = None,
                         max_depth: int = 2):
        """
        Run Agent 1: Site Learner
        
        This will map the website structure and save it to the knowledge base.
        """
        print("=" * 60)
        print("AGENT 1: SITE LEARNER")
        print("=" * 60)
        credentials_file = credentials_file or self._default_credentials_file()
        
        # Load credentials
        try:
            credentials = self.cred_manager.load_credentials(
                filepath=credentials_file,
                site_url=site_url,
                username=username,
                password=password
            )
        except Exception as e:
            print(f"❌ Error loading credentials: {e}")
            print("\nPlease provide credentials via:")
            print("  1. credentials.md file")
            print("  2. .env file")
            print("  3. Command line arguments: --site-url, --username, --password")
            return
        
        print(f"\n📍 Target site: {credentials['site_url']}")
        if credentials.get('application_name'):
            print(f"🏷️  Application: {credentials['application_name']}")
        print(f"👤 Username: {credentials['username']}")
        print(f"🔒 Password: {'*' * len(credentials['password'])}")
        print(f"📊 Max depth: {max_depth} levels\n")
        
        # Create learner and build nav-map
        learner = SiteLearner(self.kb)

        try:
            navmap = await learner.learn_site(
                site_url=credentials['site_url'],
                credentials=credentials,
                max_depth=max_depth
            )

            site_id_source = credentials.get('application_name') or credentials['site_url']
            site_id = learner._get_site_identifier(site_id_source)
            filepath = self.kb.save_navmap(navmap, site_id)

            total_nodes = sum(1 for _ in self._iter_nodes(navmap.nav_tree))
            print("\n" + "=" * 60)
            print("✅ LEARNING COMPLETE!")
            print("=" * 60)
            print(f"📊 Summary:")
            print(f"  - Navigation items mapped: {total_nodes}")
            print(f"  - Saved to: {filepath}")
            print(f"\n💡 You can now use Agent 2 to execute commands on this site")
            print(f"   Command: python main.py execute --site-id {site_id}")

        except Exception as e:
            print(f"\n❌ Learning failed: {e}")
            import traceback
            traceback.print_exc()
    
    async def run_executor(self,
                          site_id: str,
                          credentials_file: str = None,
                          site_url: str = None,
                          username: str = None,
                          password: str = None,
                          interactive: bool = True):
        """
        Run Agent 2: Action Executor
        
        This will start a session and execute user commands.
        """
        print("=" * 60)
        print("AGENT 2: ACTION EXECUTOR")
        print("=" * 60)
        credentials_file = credentials_file or self._default_credentials_file()
        
        # Load nav-map
        navmap = self.kb.load_navmap(site_id)
        if not navmap:
            print(f"\n❌ No nav-map found for site: {site_id}")
            print("Please run the learner first:")
            print(f"  python main.py learn --credentials credentials.md")
            return

        print(f"\n✅ Loaded nav-map for: {navmap.site_url}")

        # Load credentials
        try:
            credentials = self.cred_manager.load_credentials(
                filepath=credentials_file,
                site_url=site_url or navmap.site_url,
                username=username,
                password=password
            )
        except Exception as e:
            print(f"❌ Error loading credentials: {e}")
            return

        # Get API key for LLM — use first available key
        anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        gemini_key = os.getenv('GEMINI_API_KEY')

        if anthropic_key:
            llm_provider, llm_api_key = 'anthropic', anthropic_key
        elif gemini_key:
            llm_provider, llm_api_key = 'gemini', gemini_key
        else:
            llm_provider, llm_api_key = None, None
            print("⚠️  No LLM API key found (ANTHROPIC_API_KEY or GEMINI_API_KEY). Using basic command interpretation.")
            print("   For better results, add an API key to .env\n")

        # Create executor
        executor = ActionAgent(navmap, provider=llm_provider, api_key=llm_api_key)
        
        try:
            # Start session and login
            await executor.start_session(credentials)
            
            if interactive:
                # Interactive mode
                print("\n" + "=" * 60)
                print("🤖 INTERACTIVE MODE")
                print("=" * 60)
                print("Enter commands to execute on the site.")
                print("Type 'quit' or 'exit' to stop.\n")
                
                while True:
                    try:
                        command = input("💬 Your command: ").strip()
                        
                        if command.lower() in ['quit', 'exit', 'q']:
                            print("👋 Goodbye!")
                            break
                        
                        if not command:
                            continue
                        
                        # Execute command
                        result = await executor.execute_command(command)
                        print(f"\n{result}\n")
                        
                    except KeyboardInterrupt:
                        print("\n\n👋 Interrupted by user")
                        break
                    except Exception as e:
                        print(f"❌ Error: {e}\n")
            
        finally:
            await executor.close_session()
    
    def list_sites(self):
        """List all available site nav-maps"""
        sites = self.kb.list_available()

        if not sites:
            print("📭 No site nav-maps found.")
            print("Run the learner first to map a site:")
            print("  python main.py learn --credentials credentials.md")
            return

        print("📚 Available site nav-maps:")
        for site in sites:
            navmap = self.kb.load_navmap(site)
            if navmap:
                total = sum(1 for _ in self._iter_nodes(navmap.nav_tree))
                print(f"\n  🌐 {site}")
                print(f"     URL: {navmap.site_url}")
                print(f"     Navigation items: {total}")
                print(f"     Last updated: {navmap.last_updated}")

    @staticmethod
    def _iter_nodes(tree: dict):
        """Yield every NavNode in the tree (depth-first)."""
        for node in tree.values():
            yield node
            yield from WebAgentCLI._iter_nodes(node.children)


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Web Agent System - Learn and automate websites",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  
  1. Learn a website (Agent 1):
     python main.py learn --credentials credentials.md
     
  2. Execute commands (Agent 2):
     python main.py execute --site-id example_com --credentials credentials.md
     
  3. List learned sites:
     python main.py list
     
  4. Learn with direct credentials:
     python main.py learn --site-url https://example.com \\
                          --username myuser --password mypass
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Learn command (Agent 1)
    learn_parser = subparsers.add_parser('learn', help='Run the site learner (Agent 1)')
    learn_parser.add_argument('--credentials', '-c', help='Path to credentials.md file')
    learn_parser.add_argument('--site-url', help='Site URL (overrides file)')
    learn_parser.add_argument('--username', '-u', help='Username (overrides file)')
    learn_parser.add_argument('--password', '-p', help='Password (overrides file)')
    learn_parser.add_argument('--max-depth', type=int, default=2, help='Max crawl depth (default: 2)')
    
    # Execute command (Agent 2)
    exec_parser = subparsers.add_parser('execute', help='Run the action executor (Agent 2)')
    exec_parser.add_argument('--site-id', required=True, help='Site identifier from learning phase')
    exec_parser.add_argument('--credentials', '-c', help='Path to credentials.md file')
    exec_parser.add_argument('--site-url', help='Site URL (overrides file)')
    exec_parser.add_argument('--username', '-u', help='Username (overrides file)')
    exec_parser.add_argument('--password', '-p', help='Password (overrides file)')
    exec_parser.add_argument('--no-interactive', action='store_true', help='Disable interactive mode')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List learned sites')
    
    args = parser.parse_args()
    
    cli = WebAgentCLI()
    
    if args.command == 'learn':
        await cli.run_learner(
            credentials_file=args.credentials,
            site_url=args.site_url,
            username=args.username,
            password=args.password,
            max_depth=args.max_depth
        )
    
    elif args.command == 'execute':
        await cli.run_executor(
            site_id=args.site_id,
            credentials_file=args.credentials,
            site_url=args.site_url,
            username=args.username,
            password=args.password,
            interactive=not args.no_interactive
        )
    
    elif args.command == 'list':
        cli.list_sites()
    
    else:
        parser.print_help()


if __name__ == '__main__':
    asyncio.run(main())
