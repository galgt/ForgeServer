"""
Knowledge base storage and retrieval.
Handles saving/loading site nav-maps to/from JSON files.
"""

import json
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

from knowledge.models import SiteNavMap, NavNode, SiteKnowledge, PageSchema, Workflow


class KnowledgeBase:
    """Manages persistent storage of site nav-maps."""

    def __init__(self, storage_dir: str = "knowledge/schemas"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.current_navmap: Optional[SiteNavMap] = None

    # ------------------------------------------------------------------
    # Nav-map (current architecture)
    # ------------------------------------------------------------------

    def save_navmap(self, navmap: SiteNavMap, site_id: str) -> str:
        site_id = site_id.removesuffix(".json")
        filepath = self.storage_dir / f"{site_id}.json"
        data = navmap.model_dump()
        data['last_updated'] = navmap.last_updated.isoformat()
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"✅ Nav-map saved to {filepath}")
        return str(filepath)

    def load_navmap(self, site_id: str) -> Optional[SiteNavMap]:
        site_id = site_id.removesuffix(".json")
        filepath = self.storage_dir / f"{site_id}.json"
        if not filepath.exists():
            print(f"⚠️  No nav-map found for {site_id}")
            return None
        with open(filepath, 'r') as f:
            data = json.load(f)
        if data.get('version', '1.0') == '1.0':
            print(f"⚠️  '{site_id}' uses the old schema format. Re-run the learner to build a nav-map.")
            return None
        if 'last_updated' in data:
            data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        navmap = SiteNavMap(**data)
        self.current_navmap = navmap
        print(f"✅ Loaded nav-map from {filepath}")
        return navmap

    def navmap_to_text(self, navmap: SiteNavMap) -> str:
        """Render the nav tree as indented text for the LLM prompt."""
        lines = ["Main menu:"]

        def _render(nodes: dict, indent: int):
            for label, node in nodes.items():
                lines.append("  " * indent + label)
                if node.children:
                    _render(node.children, indent + 1)

        _render(navmap.nav_tree, 1)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Legacy helpers (kept so old code doesn't hard-fail)
    # ------------------------------------------------------------------

    def save(self, knowledge: SiteKnowledge, site_identifier: str):
        filepath = self.storage_dir / f"{site_identifier}.json"
        data = knowledge.model_dump()
        data['last_updated'] = knowledge.last_updated.isoformat()
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"✅ Knowledge base saved to {filepath}")
        return filepath

    def load(self, site_identifier: str) -> Optional[SiteKnowledge]:
        filepath = self.storage_dir / f"{site_identifier}.json"
        if not filepath.exists():
            return None
        with open(filepath, 'r') as f:
            data = json.load(f)
        if 'last_updated' in data:
            data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        return SiteKnowledge(**data)

    def get_page(self, page_identifier: str) -> Optional[PageSchema]:
        return None

    def list_available(self) -> list:
        return [f.stem for f in self.storage_dir.glob("*.json")]
