"""
Site Learner Agent (Agent 1)
Builds a lightweight navigation tree by recursively expanding sidebar menus.
No CSS selectors — only label hierarchy is stored.
"""

import asyncio
import re
from typing import Dict, List, Optional, Set
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright, Page

from knowledge.models import SiteNavMap, NavNode, SelectorStrategy, PageElement, PageSchema
from knowledge.storage import KnowledgeBase


# Returns ALL visible short-text elements within the sidebar X range and below minY.
# params = {left, right, minY}
_JS_GET_NAV_LABELS = """
(params) => {
  const leftBound = params.left;
  const rightBound = params.right;
  const minY = params.minY;
  const results = [];
  const seen = new Set();
  const els = document.querySelectorAll(
    'nu-nav-entry, [class*="nu-nav"], ' +
    'a, button, li, span, div, [role="menuitem"], [role="button"], ' +
    '[role="treeitem"], [tabindex]:not([tabindex="-1"])'
  );
  for (const el of els) {
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height) continue;
    if (box.top < minY) continue;
    if (box.left < leftBound - 10 || box.right > rightBound + 10) continue;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) < 0.1) continue;
    const text = (el.getAttribute('aria-label') || el.innerText || '')
                   .replace(/\\s+/g, ' ').trim();
    if (text && text.length >= 2 && text.length <= 60 && !seen.has(text)) {
      seen.add(text);
      results.push(text);
    }
  }
  return results;
}
"""

# Returns sidebar bounds. Falls back to left 40% if no container found.
_JS_SIDEBAR_BOUNDS = """
() => {
  const vw = window.innerWidth || document.documentElement.clientWidth;
  const vh = window.innerHeight || document.documentElement.clientHeight;
  const sels = [
    'nav', 'aside', '[role="navigation"]', '[role="menubar"]', '[role="tree"]',
    '[class*="sidebar" i]', '[class*="side-bar" i]', '[class*="side-nav" i]',
    '[class*="sidenav" i]', '[class*="navigation" i]', '[class*="left-nav" i]',
    '[class*="leftnav" i]', '[class*="left-panel" i]', '[class*="nav-menu" i]',
    '[class*="app-nav" i]', '[class*="main-menu" i]', '[class*="mainmenu" i]',
    '[class*="navbar" i]', '[class*="navpane" i]', '[class*="nav-pane" i]',
    '[class*="menu-wrap" i]', '[class*="menuwrap" i]'
  ];
  for (const s of sels) {
    for (const el of document.querySelectorAll(s)) {
      const box = el.getBoundingClientRect();
      if (box.width > 40 && box.width < vw * 0.55 && box.height > vh * 0.25) {
        return { left: box.left, right: box.right, top: box.top, source: s };
      }
    }
  }
  return { left: 0, right: vw * 0.40, top: 0, source: 'fallback-40pct' };
}
"""

# Diagnostic: returns raw info about all left-side visible elements (no filtering).
_JS_DIAGNOSE = """
() => {
  const vw = window.innerWidth || document.documentElement.clientWidth;
  const maxX = vw * 0.45;
  const items = [];
  const sel = 'nu-nav-entry, [class*="nu-nav"], a, button, li, ' +
              '[role="menuitem"], [role="treeitem"], [tabindex]:not([tabindex="-1"])';
  for (const el of document.querySelectorAll(sel)) {
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height || box.right > maxX) continue;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const text = (el.getAttribute('aria-label') || el.innerText || '').replace(/\\s+/g,' ').trim();
    if (text && text.length >= 2 && text.length <= 60) {
      items.push({ text, x: Math.round(box.left), y: Math.round(box.top),
                   w: Math.round(box.width), tag: el.tagName.toLowerCase() });
    }
  }
  // Deduplicate by text
  const seen = new Set();
  return items.filter(i => { if (seen.has(i.text)) return false; seen.add(i.text); return true; });
}
"""

# Detects labels in a horizontal top navigation bar.
# Strategy 1: items inside a wide, short container near the top.
# Strategy 2: fallback - any visible element in the top 15% of the viewport.
_JS_TOPNAV_LABELS = """
() => {
  const vh = window.innerHeight || document.documentElement.clientHeight;
  const vw = window.innerWidth || document.documentElement.clientWidth;
  const maxY = vh * 0.15;
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
  const directText = el => norm(
    el.getAttribute('aria-label') ||
    [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('') ||
    el.innerText || ''
  );
  const isVisible = el => {
    const s = window.getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && parseFloat(s.opacity || 1) > 0.1;
  };
  const results = [];
  const seen = new Set();

  // Pass 1: items inside wide, short containers at the top of the page
  for (const c of document.querySelectorAll(
    'nav, [role="menubar"], [role="navigation"], header, ' +
    '[class*="menu" i], [class*="topnav" i], [class*="top-nav" i], ' +
    '[class*="topbar" i], [class*="toolbar" i], [class*="navbar" i]')) {
    const cb = c.getBoundingClientRect();
    if (cb.top > maxY || cb.height > vh * 0.25 || cb.width < vw * 0.3) continue;
    if (!isVisible(c)) continue;
    for (const el of c.querySelectorAll(
        'a, button, li, span, div, [role="menuitem"], [role="tab"]')) {
      const box = el.getBoundingClientRect();
      if (!box.width || !box.height || box.height > 80) continue;
      if (!isVisible(el)) continue;
      const text = directText(el);
      if (text && text.length >= 2 && text.length <= 30 && !seen.has(text)) {
        seen.add(text);
        results.push(text);
      }
    }
  }
  if (results.length) return results;

  // Pass 2: any visible element whose top edge is within the top 15% of the viewport
  for (const el of document.querySelectorAll(
    'a, button, li, span, div, [role="menuitem"], [role="tab"], [tabindex]:not([tabindex="-1"])')) {
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height) continue;
    if (box.top < 0 || box.top >= maxY || box.height > 80) continue;
    if (box.width >= vw * 0.5) continue;
    if (!isVisible(el)) continue;
    const text = directText(el);
    if (text && text.length >= 2 && text.length <= 30 && !seen.has(text)) {
      seen.add(text);
      results.push(text);
    }
  }
  return results;
}
"""

# Clicks a label in the top navigation bar and returns its center coordinates.
_JS_CLICK_TOPNAV_ITEM = """
(label) => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
  const directText = el => norm(
    el.getAttribute('aria-label') ||
    [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('') ||
    el.innerText || ''
  );
  const vh = window.innerHeight || document.documentElement.clientHeight;
  const vw = window.innerWidth || document.documentElement.clientWidth;
  const maxY = vh * 0.15;

  for (const el of document.querySelectorAll(
    'a, button, li, span, div, [role="menuitem"], [role="tab"], [tabindex]:not([tabindex="-1"])')) {
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height) continue;
    if (box.top < 0 || box.top >= maxY || box.height > 80) continue;
    if (box.width >= vw * 0.5) continue;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    if (directText(el) === label) {
      el.click();
      return { x: box.left + box.width / 2, y: box.top + box.height / 2 };
    }
  }
  return null;
}
"""

# Clicks the first visible element matching label, scoped to left side of page.
_JS_CLICK_NAV = """
(params) => {
  const label = params.label;
  const rightBound = params.right;

  const tryClick = (el) => {
    const style = window.getComputedStyle(el);
    const box = el.getBoundingClientRect();
    if (style.display === 'none' || style.visibility === 'hidden' || !box.width) return false;
    const text = (el.getAttribute('aria-label') || el.innerText || '')
                   .replace(/\\s+/g, ' ').trim();
    if (text === label) { el.click(); return true; }
    return false;
  };

  // Pass 1: Fortinet's custom nav elements (nu-nav-entry) — highest priority
  for (const el of document.querySelectorAll('nu-nav-entry, [class*="nu-nav"]')) {
    if (tryClick(el)) return true;
  }

  // Pass 2: standard nav container children
  const containerSel = [
    'nav', 'aside', '[role="navigation"]', '[role="menubar"]', '[role="menu"]', '[role="tree"]',
    '[class*="sidebar" i]', '[class*="side-nav" i]', '[class*="sidenav" i]',
    '[class*="navigation" i]', '[class*="navbar" i]', '[class*="left-nav" i]',
    '[class*="leftnav" i]', '[class*="left-panel" i]', '[class*="nav-menu" i]',
    '[class*="app-nav" i]', '[class*="main-menu" i]', '[class*="mainmenu" i]',
    '[class*="menu-wrap" i]'
  ].join(',');
  for (const c of document.querySelectorAll(containerSel)) {
    for (const el of c.querySelectorAll(
        'a, button, li, span, div, [role="menuitem"], [role="treeitem"]')) {
      if (tryClick(el)) return true;
    }
  }

  // Pass 3: any visible element on the left side of the page
  for (const el of document.querySelectorAll(
      'a, button, li, [role="menuitem"], [role="button"], [role="treeitem"],' +
      '[tabindex]:not([tabindex="-1"])')) {
    const box = el.getBoundingClientRect();
    if (box.right <= rightBound + 10 && box.left >= 0 && tryClick(el)) return true;
  }
  return false;
}
"""


class SiteLearner:
    """
    Agent 1: Builds a lightweight nav-tree for a site.
    Recursively expands every sidebar menu item to capture the full hierarchy.
    """

    MAX_DEPTH = 6
    EXPAND_WAIT = 1.2
    COLLAPSE_WAIT = 0.4

    def __init__(self, knowledge_base: KnowledgeBase):
        self.kb = knowledge_base

    async def learn_site(self,
                         site_url: str,
                         credentials: Dict,
                         max_depth: int = MAX_DEPTH) -> SiteNavMap:
        print(f"🔍 Starting nav-tree learning for {site_url}")

        navmap = SiteNavMap(
            site_url=site_url,
            site_name=self._get_site_identifier(
                credentials.get('application_name') or site_url
            )
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            page.set_default_timeout(15000)

            try:
                print("📋 Logging in...")
                await self._learn_login_page(
                    page,
                    credentials.get('login_page', site_url),
                    credentials
                )
                await asyncio.sleep(2)
                await self._wait_for_page_ready(page, "post-login")

                # Handle Fortinet's "view-only" / "prompt" interstitial pages
                await self._bypass_prompt_pages(page, site_url)

                # Wait for Angular SPA to render its components
                await self._wait_for_angular(page)
                print(f"✅ On main dashboard: {page.url}")

                # Save screenshot + HTML snapshot for inspection
                screenshot_path = 'debug_after_login.png'
                html_path = 'debug_page.html'
                await page.screenshot(path=screenshot_path, full_page=False)
                html = await page.content()
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(html)
                print(f"📸 Screenshot → {screenshot_path}")
                print(f"📄 Page HTML  → {html_path}  ({len(html):,} chars)")

                # Detect sidebar bounds
                bounds = await page.evaluate(_JS_SIDEBAR_BOUNDS)
                min_y = bounds['top'] + 40
                sidebar_params = {'left': bounds['left'], 'right': bounds['right'], 'minY': min_y}
                print(f"🔍 Sidebar detected via '{bounds.get('source')}': "
                      f"x=[{bounds['left']:.0f}–{bounds['right']:.0f}] minY={min_y:.0f}")

                # Diagnostic dump — shows raw left-side elements before any filtering
                diag = await page.evaluate(_JS_DIAGNOSE)
                print(f"🔍 Diagnostic: {len(diag)} left-side elements found")
                for item in diag[:20]:
                    print(f"    {item['tag']:6} ({item['x']:4},{item['y']:4}) {item['text']!r}")

                # Initial probe with sidebar params
                probe = await page.evaluate(_JS_GET_NAV_LABELS, sidebar_params)
                print(f"🔍 Nav probe (with bounds): {len(probe)} items → {probe[:15]}")

                # If bounds were too strict, fall back to left 45% with no Y minimum
                if len(probe) == 0:
                    print("⚠️  No items with sidebar bounds — widening to left 45% of viewport")
                    vw = await page.evaluate("() => window.innerWidth")
                    sidebar_params = {'left': 0, 'right': vw * 0.45, 'minY': 0}
                    probe = await page.evaluate(_JS_GET_NAV_LABELS, sidebar_params)
                    print(f"🔍 Nav probe (widened): {len(probe)} items → {probe[:15]}")

                print("📋 Building navigation tree (this may take a while)...")
                global_visited: Set[str] = set()
                navmap.nav_tree = await self._build_nav_tree(
                    page, parent_path=[], global_visited=global_visited,
                    sidebar_params=sidebar_params, click_right=sidebar_params['right'],
                    depth=0, max_depth=max_depth
                )

                # Navigate back to home, then discover horizontal top-nav bar (e.g. PaloAlto)
                await page.goto(navmap.site_url, wait_until='domcontentloaded')
                await asyncio.sleep(2)
                topnav_raw = await page.evaluate(_JS_TOPNAV_LABELS)
                print(f"🔍 Top-nav raw ({len(topnav_raw)} items): {topnav_raw[:20]}")
                topnav_labels = [l for l in topnav_raw if self._is_nav_label(l)]
                print(f"🔍 Top-nav filtered: {len(topnav_labels)} items → {topnav_labels[:15]}")
                if topnav_labels:
                    topnav_tree = await self._learn_topnav_tree(
                        page, topnav_labels, max_depth
                    )
                    for label, node in topnav_tree.items():
                        navmap.nav_tree[label] = node

            finally:
                await browser.close()

        total = self._count_nodes(navmap.nav_tree)
        print(f"✅ Nav-tree learning complete! Mapped {total} navigation items")
        return navmap

    # ------------------------------------------------------------------
    # Recursive nav-tree builder
    # ------------------------------------------------------------------

    async def _build_nav_tree(self,
                               page: Page,
                               parent_path: List[str],
                               global_visited: Set[str],
                               sidebar_params: Dict,
                               click_right: float,
                               depth: int,
                               max_depth: int) -> Dict[str, NavNode]:
        if depth >= max_depth:
            return {}

        before: Set[str] = set(await page.evaluate(_JS_GET_NAV_LABELS, sidebar_params))
        current_labels = [l for l in before
                          if l not in global_visited and self._is_nav_label(l)]

        tree: Dict[str, NavNode] = {}
        original_url = page.url

        for label in current_labels:
            if label in global_visited:
                continue
            global_visited.add(label)

            node_path = parent_path + [label]
            print(f"{'  ' * depth}▶ {label}")

            snap_before: Set[str] = set(await page.evaluate(_JS_GET_NAV_LABELS, sidebar_params))

            clicked = await page.evaluate(_JS_CLICK_NAV, {'label': label, 'right': click_right})
            if not clicked:
                print(f"{'  ' * depth}  (could not click — saved as leaf)")
                tree[label] = NavNode(label=label, path=node_path)
                continue

            await asyncio.sleep(self.EXPAND_WAIT)

            if page.url != original_url:
                await page.go_back()
                await self._wait_for_page_ready(page, label)
                tree[label] = NavNode(label=label, path=node_path)
                continue

            snap_after: Set[str] = set(await page.evaluate(_JS_GET_NAV_LABELS, sidebar_params))
            new_labels = {l for l in snap_after - snap_before if self._is_nav_label(l)}

            if new_labels:
                print(f"{'  ' * depth}  → {len(new_labels)} children: {list(new_labels)[:8]}")
                children = await self._build_nav_tree(
                    page, node_path, global_visited, sidebar_params,
                    click_right, depth + 1, max_depth
                )
                tree[label] = NavNode(label=label, path=node_path, children=children)
            else:
                tree[label] = NavNode(label=label, path=node_path)

            await page.keyboard.press('Escape')
            await asyncio.sleep(self.COLLAPSE_WAIT)

        return tree

    # ------------------------------------------------------------------
    # Top navigation bar discovery (horizontal nav like PaloAlto)
    # ------------------------------------------------------------------

    async def _learn_topnav_tree(self,
                                  page: Page,
                                  topnav_labels: List[str],
                                  max_depth: int) -> Dict[str, 'NavNode']:
        """Click each item in a horizontal top-nav bar and record the sidebar items that appear.

        Sidebar bounds are re-detected after each click because different sections
        (e.g. NETWORK vs MONITOR) may render completely different left-sidebar layouts.
        """
        print(f"📋 Learning top-nav sections: {topnav_labels}")
        original_url = page.url
        tree: Dict[str, NavNode] = {}
        topnav_set: Set[str] = set(topnav_labels)

        for label in topnav_labels:
            node_path = [label]
            print(f"▶ [top-nav] {label}")

            clicked = await page.evaluate(_JS_CLICK_TOPNAV_ITEM, label)
            if not clicked:
                print(f"  (could not click '{label}')")
                tree[label] = NavNode(label=label, path=node_path)
                continue

            await asyncio.sleep(self.EXPAND_WAIT)

            if page.url != original_url:
                await page.go_back()
                await self._wait_for_page_ready(page, label)
                tree[label] = NavNode(label=label, path=node_path)
                continue

            # Re-detect sidebar bounds: each section may have a different left sidebar
            bounds = await page.evaluate(_JS_SIDEBAR_BOUNDS)
            section_params = {'left': bounds['left'], 'right': bounds['right'],
                              'minY': bounds['top'] + 40}
            probe = await page.evaluate(_JS_GET_NAV_LABELS, section_params)
            if not probe:
                vw = await page.evaluate("() => window.innerWidth")
                section_params = {'left': 0, 'right': vw * 0.45, 'minY': 0}
            print(f"  sidebar via '{bounds.get('source')}': "
                  f"x=[{bounds['left']:.0f}–{bounds['right']:.0f}]  "
                  f"probe={len(probe)} items")

            # Fresh visited set per section so the same label can appear under multiple sections
            section_visited: Set[str] = set(topnav_set)
            children = await self._build_nav_tree(
                page, node_path, section_visited, section_params,
                click_right=section_params['right'], depth=1, max_depth=max_depth
            )
            tree[label] = NavNode(label=label, path=node_path, children=children)
            print(f"  → {len(children)} sidebar items under '{label}'")

            await page.keyboard.press('Escape')
            await asyncio.sleep(self.COLLAPSE_WAIT)

        return tree

    # ------------------------------------------------------------------
    # Post-login navigation helpers
    # ------------------------------------------------------------------

    async def _bypass_prompt_pages(self, page: Page, site_url: str):
        """
        Fortinet shows interstitial prompt pages (viewOnly, concurrent session)
        before the real dashboard. Click through them if present.
        Does NOT navigate if already on the right page.
        """
        for _ in range(5):
            url = page.url
            if 'prompt' not in url and 'login' not in url.lower():
                return  # Already on the real application

            print(f"  ⚠️  Prompt page detected, attempting to click through...")

            clicked = False
            for btn in ['Continue', 'Read Only', 'Read-Only', 'OK',
                        'Proceed', 'Login Anyway', 'Force Login']:
                try:
                    await page.click(f'button:has-text("{btn}")', timeout=2000)
                    await asyncio.sleep(2)
                    clicked = True
                    print(f"  ✅ Clicked '{btn}'")
                    break
                except Exception:
                    continue

            if not clicked:
                # No button found — navigate to root and let Fortinet redirect
                print(f"  ↗ No button found, navigating to site root")
                await page.goto(site_url.rstrip('/') + '/', wait_until='domcontentloaded')
                await asyncio.sleep(3)

        print(f"  ℹ️  URL after bypass: {page.url}")

    async def _wait_for_angular(self, page: Page, timeout: int = 30000):
        """
        Wait until the Fortinet sidebar has actually rendered.
        We wait for a meaningful number of <a href> elements to appear —
        these are the sidebar navigation links.
        Does NOT navigate. Just waits.
        """
        print("  ⏳ Waiting for sidebar navigation links to appear...")
        try:
            await page.wait_for_function(
                "document.querySelectorAll('a[href]').length > 8",
                timeout=timeout
            )
            count = await page.evaluate("document.querySelectorAll('a[href]').length")
            print(f"  ✅ Sidebar ready ({count} links found)")
        except PlaywrightTimeoutError:
            count = await page.evaluate("document.querySelectorAll('a[href]').length")
            print(f"  ⚠️  Timeout waiting for sidebar — only {count} links, continuing anyway")

        # Extra buffer for Angular's lazy-rendered components
        await asyncio.sleep(2)

    # ------------------------------------------------------------------
    # Login (unchanged)
    # ------------------------------------------------------------------

    async def _learn_login_page(self, page: Page, login_url: str, credentials: Dict) -> PageSchema:
        await page.goto(login_url)
        await self._wait_for_page_ready(page, "login page")
        username_sel = await self._find_input_field(page, ['username', 'email', 'user', 'login'])
        password_sel = await self._find_input_field(page, ['password', 'pass', 'pwd'])
        submit_sel = await self._find_submit_button(page)
        schema = PageSchema(
            url_pattern=login_url,
            title=await page.title(),
            elements={
                'username': PageElement(name='username', selectors=username_sel, element_type='input', required=True),
                'password': PageElement(name='password', selectors=password_sel, element_type='input', required=True),
                'submit':   PageElement(name='submit',   selectors=submit_sel,   element_type='button', required=True),
            },
            actions=['login']
        )
        await self._perform_login(page, schema, credentials)
        return schema

    async def _perform_login(self, page: Page, schema: PageSchema, credentials: Dict):
        for selector in [schema.elements['username'].selectors.primary] + schema.elements['username'].selectors.fallbacks:
            try:
                await page.fill(selector, credentials['username']); break
            except: continue
        for selector in [schema.elements['password'].selectors.primary] + schema.elements['password'].selectors.fallbacks:
            try:
                await page.fill(selector, credentials['password']); break
            except: continue
        submitted = False
        for selector in [schema.elements['submit'].selectors.primary] + schema.elements['submit'].selectors.fallbacks:
            try:
                print(f"  Submitting login with selector: {selector}")
                await page.click(selector)
                submitted = True
                break
            except: continue
        if not submitted:
            # Universal fallback
            for sel in ['input[type="password"]', 'input[name*="password" i]']:
                try:
                    await page.press(sel, 'Enter')
                    print("  Submitted login via Enter on password field")
                    break
                except: continue
        await self._wait_for_page_ready(page, "post-login page")
        await asyncio.sleep(2)

    async def _find_input_field(self, page: Page, keywords: List[str]) -> SelectorStrategy:
        selectors = []
        for keyword in keywords:
            for strategy in [
                f'input[name*="{keyword}" i]', f'input[id*="{keyword}" i]',
                f'input[placeholder*="{keyword}" i]', f'input[type="text"][name*="{keyword}" i]',
                f'input[type="email"][name*="{keyword}" i]',
            ]:
                try:
                    if await page.query_selector(strategy):
                        selectors.append(strategy); break
                except: continue
            if selectors: break
        if not selectors:
            selectors = ['input[type="text"]', 'input[type="email"]']
        return SelectorStrategy(primary=selectors[0], fallbacks=selectors[1:])

    async def _find_submit_button(self, page: Page) -> SelectorStrategy:
        selectors = []
        for strategy in [
            'button[type="submit"]', 'input[type="submit"]',
            'button:has-text("Login")', 'button:has-text("Log In")',
            'button:has-text("Sign in")', '.btn-login', '.login-button',
        ]:
            try:
                if await page.query_selector(strategy):
                    selectors.append(strategy)
            except: continue
        if not selectors:
            selectors = ['button[type="submit"]']
        return SelectorStrategy(primary=selectors[0], fallbacks=selectors[1:])

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    _NON_NAV_PREFIXES = ('add ', 'create ', 'new ', 'edit ', 'delete ', 'remove ',
                         'import ', 'export ', 'upload ', 'download ', 'save ', 'cancel ')
    _NON_NAV_EXACT = {'add widget', 'add', 'ok', 'yes', 'no', 'close', 'apply',
                      'reset', 'submit', 'confirm', 'back', 'next', 'finish', 'skip'}

    @classmethod
    def _is_nav_label(cls, label: str) -> bool:
        lower = label.lower().strip()
        if lower in cls._NON_NAV_EXACT:
            return False
        if any(lower.startswith(p) for p in cls._NON_NAV_PREFIXES):
            return False
        return True

    async def _wait_for_page_ready(self, page: Page, label: str, timeout: int = 15000):
        try:
            await page.wait_for_load_state('domcontentloaded', timeout=timeout)
        except PlaywrightTimeoutError:
            print(f"  Warning: timed out waiting for {label}; continuing.")
            return
        try:
            await page.wait_for_load_state('networkidle', timeout=3000)
        except PlaywrightTimeoutError:
            pass

    def _count_nodes(self, tree: Dict[str, NavNode]) -> int:
        total = len(tree)
        for node in tree.values():
            total += self._count_nodes(node.children)
        return total

    @staticmethod
    def _get_site_identifier(url: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        source = parsed.netloc if parsed.netloc else url
        source = source.replace('.json', '')
        return re.sub(r'_+', '_', re.sub(r'[^a-zA-Z0-9]+', '_', source)).strip('_').lower()

    @staticmethod
    def _slugify(value: str) -> str:
        return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', value.lower())).strip('_')[:40]
