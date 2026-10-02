"""
Data models for the knowledge base.
Nav-map architecture: stores menu hierarchy only, no CSS selectors.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime


# ---------------------------------------------------------------------------
# Nav-map models (current)
# ---------------------------------------------------------------------------

class NavNode(BaseModel):
    """A single node in the site navigation tree."""
    label: str
    path: List[str]                        # Full path from root, e.g. ["Network", "DNS"]
    children: Dict[str, 'NavNode'] = Field(default_factory=dict)

NavNode.model_rebuild()


class SiteNavMap(BaseModel):
    """Lightweight site knowledge: just the navigation hierarchy."""
    site_url: str
    site_name: Optional[str] = None
    nav_tree: Dict[str, NavNode] = Field(default_factory=dict)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    version: str = "2.0"

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# ---------------------------------------------------------------------------
# Legacy models (kept for backward compatibility with old schema files)
# ---------------------------------------------------------------------------

class SelectorStrategy(BaseModel):
    primary: str
    fallbacks: List[str] = Field(default_factory=list)
    description: Optional[str] = None


class PageElement(BaseModel):
    name: str
    selectors: SelectorStrategy
    element_type: str
    required: bool = False
    id: Optional[str] = None
    label: Optional[str] = None
    text: Optional[str] = None
    role: Optional[str] = None
    context: Optional[str] = None
    parent_label: Optional[str] = None
    hierarchy_path: List[str] = Field(default_factory=list)
    position: Dict[str, Any] = Field(default_factory=dict)
    attributes: Dict[str, Optional[str]] = Field(default_factory=dict)
    confidence: float = 0.5


class PageSchema(BaseModel):
    url_pattern: str
    title: Optional[str] = None
    elements: Dict[str, PageElement] = Field(default_factory=dict)
    actions: List[str] = Field(default_factory=list)
    description: Optional[str] = None


class Workflow(BaseModel):
    name: str
    description: str
    steps: List[str]
    required_pages: List[str] = Field(default_factory=list)


class SiteKnowledge(BaseModel):
    site_url: str
    site_name: Optional[str] = None
    pages: Dict[str, PageSchema] = Field(default_factory=dict)
    workflows: Dict[str, Workflow] = Field(default_factory=dict)
    last_updated: datetime = Field(default_factory=datetime.now)
    version: str = "1.0"

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
