"""
Action Agent (Agent 2)
Interprets user commands using the nav-tree and executes them via Playwright
semantic locators — no CSS selectors, no schema positions.
"""

import asyncio
import json
import re
from typing import Dict, List, Optional
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright, Page, Browser

from knowledge.models import SiteNavMap
from knowledge.storage import KnowledgeBase


# Returns ALL center coordinates for nav items matching a label (multiple matches possible).
_JS_GET_ALL_NAV_CENTERS = """
(label) => {
  const norm = (s) => (s || '').replace(/\\s+/g,' ').trim();
  const results = [];
  const vw = window.innerWidth || document.documentElement.clientWidth;
  const maxX = vw * 0.45;

  // Pass 1: nu-nav-entry elements (Fortinet)
  for (const el of document.querySelectorAll('nu-nav-entry, [class*="nu-nav"]')) {
    const style = window.getComputedStyle(el);
    const box = el.getBoundingClientRect();
    if (style.display === 'none' || style.visibility === 'hidden' || !box.width || !box.height) continue;
    if (norm(el.getAttribute('aria-label') || el.innerText || '') === label)
      results.push({ x: box.left + box.width / 2, y: box.top + box.height / 2 });
  }
  if (results.length) return results;

  // Pass 2: left-side fallback
  for (const el of document.querySelectorAll(
      'a, button, li, span, [role="menuitem"], [tabindex]:not([tabindex="-1"])')) {
    const box = el.getBoundingClientRect();
    if (box.right > maxX + 10 || box.left < 0 || !box.width || !box.height) continue;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    if (norm(el.getAttribute('aria-label') || el.innerText || '') === label)
      results.push({ x: box.left + box.width / 2, y: box.top + box.height / 2 });
  }

  // Pass 3: horizontal top navigation bar (e.g. PaloAlto DASHBOARD/NETWORK/etc.)
  if (!results.length) {
    const vh = window.innerHeight || document.documentElement.clientHeight;
    const maxTopY = vh * 0.15;
    for (const el of document.querySelectorAll(
        'a, button, li, span, div, [role="menuitem"], [role="tab"], [tabindex]:not([tabindex="-1"])')) {
      const box = el.getBoundingClientRect();
      if (!box.width || !box.height) continue;
      if (box.top < 0 || box.top >= maxTopY || box.height > 80) continue;
      if (box.width >= vw * 0.5) continue;
      const style = window.getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') continue;
      if (norm(el.getAttribute('aria-label') || el.innerText || '') === label)
        results.push({ x: box.left + box.width / 2, y: box.top + box.height / 2 });
    }
  }
  return results;
}
"""

# Returns the center coordinates of a nav item by label, for use with page.mouse.click().
# Checks nu-nav-entry first (Fortinet), then falls back to left-side elements.
_JS_GET_NAV_CENTER = """
(label) => {
  const norm = (s) => (s || '').replace(/\\s+/g,' ').trim();
  const vw = window.innerWidth || document.documentElement.clientWidth;
  const maxX = vw * 0.45;

  const match = (el) => {
    const style = window.getComputedStyle(el);
    const box = el.getBoundingClientRect();
    if (style.display === 'none' || style.visibility === 'hidden' || !box.width || !box.height) return null;
    const text = norm(el.getAttribute('aria-label') || el.innerText || '');
    if (text === label) return { x: box.left + box.width / 2, y: box.top + box.height / 2 };
    return null;
  };

  // Pass 1: Fortinet custom nav elements
  for (const el of document.querySelectorAll('nu-nav-entry, [class*="nu-nav"]')) {
    const pos = match(el); if (pos) return pos;
  }

  // Pass 2: any left-side visible element
  for (const el of document.querySelectorAll(
      'a, button, li, span, [role="menuitem"], [tabindex]:not([tabindex="-1"])')) {
    const box = el.getBoundingClientRect();
    if (box.right > maxX + 10 || box.left < 0) continue;
    const pos = match(el); if (pos) return pos;
  }

  // Pass 3: horizontal top navigation bar (e.g. PaloAlto DASHBOARD/NETWORK/etc.)
  const vh3 = window.innerHeight || document.documentElement.clientHeight;
  const maxTopY3 = vh3 * 0.15;
  for (const el of document.querySelectorAll(
      'a, button, li, span, div, [role="menuitem"], [role="tab"], [tabindex]:not([tabindex="-1"])')) {
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height) continue;
    if (box.top < 0 || box.top >= maxTopY3 || box.height > 80) continue;
    if (box.width >= (window.innerWidth || document.documentElement.clientWidth) * 0.5) continue;
    const pos = match(el); if (pos) return pos;
  }
  return null;
}
"""


class ActionAgent:
    """
    Agent 2: Executes user commands via nav-tree path resolution.
    The LLM maps commands to navigation paths; Playwright walks those paths.
    """

    def __init__(self,
                 navmap: SiteNavMap,
                 provider: Optional[str] = None,
                 api_key: Optional[str] = None):
        self.navmap = navmap
        self.llm_provider = provider
        self.llm_client = None

        if provider == 'anthropic' and api_key:
            from anthropic import Anthropic
            self.llm_client = Anthropic(api_key=api_key)
            print("🤖 LLM provider: Anthropic")
        elif provider == 'gemini' and api_key:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self.llm_client = genai.GenerativeModel('gemini-2.0-flash')
            print("🤖 LLM provider: Gemini")

        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.credentials: Optional[Dict[str, str]] = None
        self.pending_paths: List[List[str]] = []
        self._pending_action: Optional[Dict] = None

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def start_session(self, credentials: Dict[str, str]):
        print("🚀 Starting browser session...")
        self.credentials = credentials
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=False)
        context = await self.browser.new_context(ignore_https_errors=True)
        self.page = await context.new_page()
        self.page.set_default_timeout(15000)
        await self._login()
        print("✅ Session started and logged in")

    async def close_session(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        print("🛑 Session closed")

    # ------------------------------------------------------------------
    # Main command entry point
    # ------------------------------------------------------------------

    async def execute_command(self, command: str) -> str:
        if not self.page:
            return "❌ No active session. Call start_session() first."

        print(f"\n💬 User command: {command}")

        # Pending disambiguation: user typed a number
        if self.pending_paths and command.strip().isdigit():
            idx = int(command.strip()) - 1
            if 0 <= idx < len(self.pending_paths):
                path = self.pending_paths[idx]
                pending_action = self._pending_action
                self.pending_paths = []
                self._pending_action = None
                nav_result = await self._execute_path(path)
                if pending_action and not nav_result.startswith("❌"):
                    await asyncio.sleep(1.0)
                    action_result = await self._execute_action(pending_action)
                    return f"{nav_result}\n{action_result}"
                return nav_result
            return f"❌ Choose between 1 and {len(self.pending_paths)}"
        self.pending_paths = []
        self._pending_action = None

        # Diagnostics
        if command.strip().lower() in ('list fields', 'dump fields', 'what fields', 'fields'):
            return await self._dump_page_fields()
        if command.strip().lower() in ('dump rows', 'dump table', 'list rows'):
            return await self._dump_table_rows()
        if command.strip().lower() in ('dump dropdown', 'dump list', 'dump options'):
            return await self._dump_dropdown_options()

        # Direct coordinate click: "click at X Y"
        coord_match = re.match(r'^click\s+at\s+(\d+)\s+(\d+)$', command.strip(), re.IGNORECASE)
        if coord_match:
            x, y = int(coord_match.group(1)), int(coord_match.group(2))
            await self.page.mouse.move(x, y)
            await asyncio.sleep(0.15)
            await self.page.mouse.down()
            await asyncio.sleep(0.05)
            await self.page.mouse.up()
            await asyncio.sleep(0.5)
            return f"✅ Clicked at ({x}, {y})"

        # Explicit row selection: "select row N" / "select row containing X"
        row_num_match = re.match(r'^(?:select|click)?\s*row\s+(\d+)$', command.strip(), re.IGNORECASE)
        if row_num_match:
            return await self._select_table_row(int(row_num_match.group(1)))

        row_text_match = re.match(
            r'^(?:select|click)\s+row\s+(?:containing|with(?:\s+text)?)\s+(.+)$',
            command.strip(), re.IGNORECASE)
        if row_text_match:
            return await self._select_table_row_by_text(row_text_match.group(1).strip().strip("'\""))

        # "click X in/near/inside Y" — click element X scoped near field label Y
        near_match = re.match(
            r'^click\s+(.+?)\s+(?:in|near|inside|within)\s+(?:the\s+|a\s+)?(.+)$',
            command.strip(), re.IGNORECASE)
        if near_match:
            btn_text = near_match.group(1).strip().strip("'\"")
            field_label = near_match.group(2).strip().strip("'\"").lstrip("'\"")
            return await self._click_near_label(btn_text, field_label)

        try:
            result = await self._interpret_command(command)

            if result.get('type') == 'navigate':
                paths = result.get('paths', [])
                if len(paths) == 1:
                    return await self._execute_path(paths[0])
                elif len(paths) > 1:
                    self.pending_paths = paths
                    return self._format_path_clarification(paths)
                return "❌ Could not find a matching navigation path for that command."

            elif result.get('type') == 'navigate_and_act':
                paths = result.get('paths', [])
                if len(paths) > 1:
                    self.pending_paths = paths
                    self._pending_action = result  # save action for after disambiguation
                    return self._format_path_clarification(paths)
                path = paths[0] if paths else []
                if path:
                    nav_result = await self._execute_path(path)
                    if nav_result.startswith("❌"):
                        return nav_result
                    await asyncio.sleep(1.0)
                return await self._execute_action(result)

            elif result.get('type') == 'action':
                return await self._execute_action(result)

            return "❌ Could not interpret command."

        except Exception as e:
            print(f"❌ Error executing command: {e}")
            return f"❌ Error: {e}"

    # ------------------------------------------------------------------
    # Command interpretation
    # ------------------------------------------------------------------

    async def _interpret_command(self, command: str) -> Dict:
        if self.llm_client:
            return await self._interpret_with_llm(command)
        return self._interpret_basic(command)

    async def _interpret_with_llm(self, command: str) -> Dict:
        kb = KnowledgeBase()
        nav_text = kb.navmap_to_text(self.navmap)

        # Snapshot what's currently visible on the page so the LLM can
        # distinguish navigation commands from field-editing commands
        page_fields = await self._get_page_fields_summary()

        prompt = f"""You are a web automation assistant controlling a web UI.

Navigation tree (sidebar menu):
{nav_text}

Current page fields/inputs (what you can fill or click right now):
{page_fields if page_fields else "(none detected)"}

User command: "{command}"

Rules:
1. If the user says "update/set/change/fill the field X" or "update X to Y" where X is a field name (not a menu item) → ALWAYS use "action/fill". Never navigate for field-update commands.
2. If the user says "go to", "navigate to", "open", "click" a menu item → "navigate".
   List ALL matching paths if the same label appears under multiple parents.
3. Navigate to a page AND THEN update a field (e.g. "set X on the DNS page", "in Policy Routes set Gateway address to Y") → "navigate_and_act".
4. Click a button already visible on the current page → "action/click".

Key distinction:
- Navigation tree items are EXACT labels listed above (e.g. "DNS", "Network", "Interfaces", "Policy Routes").
- If the user says "click X" and X does NOT EXACTLY match a label in the Navigation tree → always use "action/click", never "navigate". Partial matches (e.g. "Interface" vs "Interfaces") do NOT count.
- Field names on a form (e.g. "Gateway address", "Comments") → always "action/fill".
- Dropdown menu items that appear after clicking a button (e.g. "Interface", "Zone") → "action/click".

Respond with ONLY valid JSON — no markdown, no explanation.

Pure navigation:
{{
  "type": "navigate",
  "paths": [["Network", "DNS"]],
  "interpretation": "short description"
}}

Fill a text field already visible on the current page:
{{
  "type": "action",
  "action": "fill",
  "target": "exact field label or placeholder text",
  "value": "new value to enter"
}}

Select a value from a dropdown/list on the current page:
{{
  "type": "action",
  "action": "select",
  "target": "dropdown field label (e.g. Type, Interface, Protocol)",
  "value": "option to select (e.g. VLAN, port1, TCP)"
}}

Click a button already visible on the current page:
{{
  "type": "action",
  "action": "click",
  "target": "button label or text"
}}

Navigate to a page then fill a field on that page:
{{
  "type": "navigate_and_act",
  "paths": [["Network", "DNS"]],
  "action": "fill",
  "target": "exact field label or placeholder text",
  "value": "new value to enter",
  "interpretation": "short description"
}}"""

        try:
            response_text = self._call_llm(prompt)
            return self._extract_json(response_text)
        except Exception as e:
            print(f"  ⚠️  LLM unavailable ({type(e).__name__}: {e}); falling back to basic interpretation.")
            return self._interpret_basic(command)

    def _interpret_basic(self, command: str) -> Dict:
        """Fallback: keyword matching when no LLM is available."""
        lower = command.lower()
        if 'search' in lower:
            return {'type': 'action', 'action': 'search', 'target': command}
        if 'fill' in lower or 'enter' in lower or 'type' in lower:
            return {'type': 'action', 'action': 'fill', 'target': command, 'value': ''}

        # Try to match against known nav labels
        all_paths = self._all_paths(self.navmap.nav_tree)
        command_words = set(lower.split())
        best_paths = []
        for path in all_paths:
            label = path[-1].lower()
            if label in lower or any(w in label for w in command_words if len(w) > 2):
                best_paths.append(path)

        if best_paths:
            return {'type': 'navigate', 'paths': best_paths[:5], 'interpretation': command}

        return {'type': 'navigate', 'paths': [], 'interpretation': command}

    # ------------------------------------------------------------------
    # Path execution
    # ------------------------------------------------------------------

    async def _get_visible_nav_labels(self) -> set:
        """Return the set of currently visible nu-nav-entry text labels."""
        labels = await self.page.evaluate("""
            () => {
              const norm = s => (s||'').replace(/\\s+/g,' ').trim();
              const result = [];
              for (const el of document.querySelectorAll('nu-nav-entry, [class*="nu-nav"]')) {
                const style = window.getComputedStyle(el);
                const box = el.getBoundingClientRect();
                if (style.display==='none'||style.visibility==='hidden'||!box.width) continue;
                const t = norm(el.getAttribute('aria-label')||el.innerText||'');
                if (t) result.push(t);
              }
              return result;
            }
        """)
        return set(labels)

    async def _execute_path(self, path: List[str]) -> str:
        """
        Execute a navigation path step by step.

        Disambiguation strategy:
        - Multi-step path: after each click verify the next label appeared; if not,
          retry the next DOM match for the same label.
        - Single-step path (no next label to verify): if multiple DOM positions exist,
          look up the navmap for all paths ending with that label and offer the user
          a numbered choice instead of guessing.
        """
        print(f"📋 Navigating: {' → '.join(path)}")

        for i, label in enumerate(path):
            next_label = path[i + 1] if i + 1 < len(path) else None
            before = await self._get_visible_nav_labels()

            positions = await self.page.evaluate(_JS_GET_ALL_NAV_CENTERS, label)

            if not positions:
                try:
                    loc = self.page.locator('nu-nav-entry, [class*="nu-nav"]').filter(has_text=label)
                    if await loc.count() > 0:
                        await loc.first.click(timeout=3000)
                        await asyncio.sleep(1.5)
                        continue
                except Exception:
                    pass
                return f"❌ Could not find '{label}' in the navigation menu"

            # Multiple matches with no next label to verify → offer disambiguation
            if len(positions) > 1 and next_label is None:
                nav_paths = [p for p in self._all_paths(self.navmap.nav_tree)
                             if p[-1].lower() == label.lower()]
                if len(nav_paths) > 1:
                    prefix = path[:i]
                    self.pending_paths = [prefix + p if prefix else p for p in nav_paths]
                    return self._format_path_clarification(self.pending_paths)

            # Click each position until the next label appears (or single match)
            clicked_ok = False
            for pos in positions:
                await self.page.mouse.click(pos['x'], pos['y'])
                print(f"  🖱  Clicked '{label}' at ({pos['x']:.0f}, {pos['y']:.0f})")
                await asyncio.sleep(1.5)

                if next_label is None:
                    clicked_ok = True
                    break

                after = await self._get_visible_nav_labels()
                new_labels = after - before
                if any(l.lower().strip() == next_label.lower().strip() for l in new_labels):
                    clicked_ok = True
                    break

                print(f"  ⚠️  '{next_label}' didn't appear — trying next '{label}' match")
                await self.page.keyboard.press('Escape')
                await asyncio.sleep(0.5)

            if not clicked_ok and next_label:
                print(f"  ⚠️  Could not confirm '{next_label}' appeared; continuing anyway")

        return f"✅ Navigated to {' → '.join(path)}"

    async def _mouse_click_nav(self, label: str) -> bool:
        """Single nav click via mouse (used for non-path ad-hoc clicks)."""
        pos = await self.page.evaluate(_JS_GET_NAV_CENTER, label)
        if pos:
            await self.page.mouse.click(pos['x'], pos['y'])
            print(f"  🖱  Clicked '{label}' at ({pos['x']:.0f}, {pos['y']:.0f})")
            return True
        try:
            loc = self.page.locator('nu-nav-entry, [class*="nu-nav"]').filter(has_text=label)
            if await loc.count() > 0:
                await loc.first.click(timeout=3000)
                return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Non-navigation actions
    # ------------------------------------------------------------------

    async def _execute_action(self, result: Dict) -> str:
        action = result.get('action', '')
        target = result.get('target', '')
        value = result.get('value', '')

        if action == 'fill':
            return await self._fill_field(target, value)
        elif action == 'select':
            return await self._select_field_option(target, value)
        elif action == 'search':
            return await self._perform_search(target)
        elif action == 'click':
            return await self._click_page_element(target)
        return f"❌ Unknown action: {action}"

    async def _fill_field(self, target: str, value: str) -> str:
        """Fill an input field on the current page using multiple strategies."""
        # Strategy 1: Playwright semantic locators
        for factory in [
            lambda: self.page.get_by_label(target, exact=False),
            lambda: self.page.get_by_placeholder(target, exact=False),
            lambda: self.page.get_by_role('textbox', name=target, exact=False),
        ]:
            try:
                loc = factory()
                if await loc.count() > 0:
                    await loc.first.clear()
                    await loc.first.fill(value)
                    await loc.first.press('Tab')
                    return f"✅ Filled '{target}' with '{value}'"
            except Exception:
                continue

        # Strategy 2: find label element first, then walk forward to its input
        field_center = await self.page.evaluate("""
            (target) => {
              const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
              const t = norm(target);
              const inpSel = [
                'input:not([type=hidden]):not([type=submit]):not([type=button])',
                'textarea','select','[contenteditable=true]',
                '[formcontrolname]','[ng-model]',
                '[role=textbox]','[role=spinbutton]','[role=combobox]'
              ].join(',');

              const isVisible = el => {
                const b = el.getBoundingClientRect();
                if (!b.width||!b.height) return false;
                const s = window.getComputedStyle(el);
                return s.display!=='none' && s.visibility!=='hidden';
              };

              const firstInput = root => {
                if (root.matches && root.matches(inpSel) && isVisible(root)) return root;
                return root.querySelector
                  ? [...root.querySelectorAll(inpSel)].find(isVisible) : null;
              };

              // Strategy A: find the label element whose OWN text matches,
              // then walk forward (next siblings / parent's next sibling) for its input.
              for (const lbl of document.querySelectorAll('label,span,div,td,th,p')) {
                if (!isVisible(lbl)) continue;
                // Use only direct text nodes to avoid matching parent containers
                const ownText = norm([...lbl.childNodes]
                  .filter(n=>n.nodeType===3).map(n=>n.textContent).join(' ')
                  || lbl.innerText || '');
                if (!ownText || ownText.length > 60 || !ownText.includes(t)) continue;

                // Walk next siblings
                let sib = lbl.nextElementSibling;
                for (let i=0; i<5 && sib; i++, sib=sib.nextElementSibling) {
                  const inp = firstInput(sib);
                  if (inp) { const b=inp.getBoundingClientRect(); return {x:b.left+b.width/2,y:b.top+b.height/2}; }
                }
                // Walk parent's next siblings
                if (lbl.parentElement) {
                  let psib = lbl.parentElement.nextElementSibling;
                  for (let i=0; i<3 && psib; i++, psib=psib.nextElementSibling) {
                    const inp = firstInput(psib);
                    if (inp) { const b=inp.getBoundingClientRect(); return {x:b.left+b.width/2,y:b.top+b.height/2}; }
                  }
                }
              }

              // Strategy B: input whose direct attributes match
              for (const inp of document.querySelectorAll(inpSel)) {
                if (!isVisible(inp)) continue;
                const attrs = [
                  inp.getAttribute('aria-label'), inp.getAttribute('placeholder'),
                  inp.getAttribute('name'), inp.getAttribute('formcontrolname'),
                  inp.id ? (document.querySelector('label[for="'+inp.id+'"]')||{}).innerText : null
                ];
                if (attrs.some(a => a && norm(a).includes(t))) {
                  const b = inp.getBoundingClientRect();
                  return {x:b.left+b.width/2, y:b.top+b.height/2};
                }
              }
              return null;
            }
        """, target)

        if field_center:
            await self.page.mouse.click(field_center['x'], field_center['y'])
            await asyncio.sleep(0.3)
            await self.page.keyboard.press('Control+a')  # select all text
            await self.page.keyboard.type(value)          # type replacement
            await self.page.keyboard.press('Tab')         # trigger Angular binding
            return f"✅ Filled '{target}' with '{value}'"

        return f"❌ Could not find field '{target}' on the current page"

    async def _select_field_option(self, target: str, value: str) -> str:
        """Select a value from a dropdown field (native <select> or custom Angular dropdown)."""
        # Strategy 1: native <select> via Playwright select_option
        # Find the <select> whose label matches target
        select_pos = await self.page.evaluate("""
            ([target, value]) => {
              const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
              const t = norm(target);
              const isVisible = el => {
                const b = el.getBoundingClientRect();
                return b.width && b.height &&
                  window.getComputedStyle(el).display !== 'none';
              };
              // Find label element, then nearest <select>
              for (const lbl of document.querySelectorAll('label,span,div,td,th,p')) {
                if (!isVisible(lbl)) continue;
                const ownText = norm([...lbl.childNodes]
                  .filter(n=>n.nodeType===3).map(n=>n.textContent).join(' ')
                  || lbl.innerText || '');
                if (!ownText || ownText.length>60 || !ownText.includes(t)) continue;
                // Walk forward for a <select>
                let sib = lbl.nextElementSibling;
                for (let i=0; i<5 && sib; i++, sib=sib.nextElementSibling) {
                  const sel = sib.tagName==='SELECT' ? sib : sib.querySelector('select');
                  if (sel && isVisible(sel)) {
                    const b = sel.getBoundingClientRect();
                    return { type: 'native', x: b.left+b.width/2, y: b.top+b.height/2,
                             options: [...sel.options].map(o=>o.text.trim()) };
                  }
                }
                if (lbl.parentElement) {
                  let psib = lbl.parentElement.nextElementSibling;
                  for (let i=0; i<3 && psib; i++, psib=psib.nextElementSibling) {
                    const sel = psib.tagName==='SELECT' ? psib : psib.querySelector('select');
                    if (sel && isVisible(sel)) {
                      const b = sel.getBoundingClientRect();
                      return { type: 'native', x: b.left+b.width/2, y: b.top+b.height/2,
                               options: [...sel.options].map(o=>o.text.trim()) };
                    }
                  }
                }
              }
              return null;
            }
        """, [target, value])

        if select_pos and select_pos.get('type') == 'native':
            try:
                await self.page.mouse.click(select_pos['x'], select_pos['y'])
                await asyncio.sleep(0.3)
                # Try select_option on focused element
                await self.page.keyboard.press('Escape')
                # Directly select by evaluating
                result = await self.page.evaluate("""
                    ([tx, ty, value]) => {
                      const el = document.elementFromPoint(tx, ty);
                      const sel = el && el.tagName==='SELECT' ? el : el && el.closest('select');
                      if (!sel) return false;
                      const norm = s => (s||'').toLowerCase().trim();
                      const v = norm(value);
                      for (const opt of sel.options) {
                        if (norm(opt.text).includes(v) || norm(opt.value).includes(v)) {
                          sel.value = opt.value;
                          sel.dispatchEvent(new Event('change', {bubbles:true}));
                          return opt.text;
                        }
                      }
                      return false;
                    }
                """, [select_pos['x'], select_pos['y'], value])
                if result:
                    return f"✅ Selected '{result}' in '{target}'"
            except Exception as e:
                print(f"  ⚠️  Native select failed: {e}")

        # Strategy 2: custom Angular dropdown — click to open, then click the option
        # First find the dropdown trigger (div/button near the label)
        dropdown_pos = await self.page.evaluate("""
            (target) => {
              const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
              const t = norm(target);
              const isVisible = el => {
                const b = el.getBoundingClientRect();
                return b.width && b.height &&
                  window.getComputedStyle(el).display !== 'none' &&
                  window.getComputedStyle(el).visibility !== 'hidden';
              };
              const dropdownSel = 'select,[role=listbox],[role=combobox],[class*=dropdown],[class*=select]';
              for (const lbl of document.querySelectorAll('label,span,div,td,th,p')) {
                if (!isVisible(lbl)) continue;
                const ownText = norm([...lbl.childNodes]
                  .filter(n=>n.nodeType===3).map(n=>n.textContent).join(' ')
                  || lbl.innerText || '');
                if (!ownText || ownText.length>60 || !ownText.includes(t)) continue;
                let sib = lbl.nextElementSibling;
                for (let i=0; i<5 && sib; i++, sib=sib.nextElementSibling) {
                  const dd = sib.matches(dropdownSel) ? sib : sib.querySelector(dropdownSel);
                  if (dd && isVisible(dd)) {
                    const b = dd.getBoundingClientRect();
                    return { x: b.left+b.width/2, y: b.top+b.height/2 };
                  }
                }
                if (lbl.parentElement) {
                  let psib = lbl.parentElement.nextElementSibling;
                  for (let i=0; i<3 && psib; i++, psib=psib.nextElementSibling) {
                    const dd = psib.matches(dropdownSel) ? psib : psib.querySelector(dropdownSel);
                    if (dd && isVisible(dd)) {
                      const b = dd.getBoundingClientRect();
                      return { x: b.left+b.width/2, y: b.top+b.height/2 };
                    }
                  }
                }
              }
              return null;
            }
        """, target)

        if dropdown_pos:
            await self.page.mouse.click(dropdown_pos['x'], dropdown_pos['y'])
            print(f"  🖱  Opened dropdown '{target}' at ({dropdown_pos['x']:.0f},{dropdown_pos['y']:.0f})")
            await asyncio.sleep(0.5)
            # Click the option in the now-open dropdown list
            option_clicked = await self._click_dropdown_option(value)
            if option_clicked:
                return f"✅ Selected '{value}' in '{target}'"

        return f"❌ Could not find dropdown '{target}' or option '{value}'"

    async def _click_dropdown_option(self, value: str) -> bool:
        """Click a visible option in an open dropdown/popover (Angular CDK overlay aware)."""
        # Strategy 1: Playwright locators — handle shadow DOM, Angular overlays natively
        for loc in [
            self.page.get_by_role('option', name=value, exact=False),
            self.page.get_by_role('listitem').filter(has_text=value),
            self.page.locator('f-omniselect-entry').filter(has_text=value),
            self.page.locator('[class*="cdk-overlay"]').get_by_text(value, exact=False),
            self.page.locator('[class*="omniselect"]').filter(has_text=value),
            self.page.get_by_text(value, exact=True),
        ]:
            try:
                count = await loc.count()
                if count > 0:
                    await loc.first.click(timeout=2000)
                    print(f"  🖱  Clicked option '{value}' via Playwright locator")
                    await asyncio.sleep(0.3)
                    return True
            except Exception:
                continue

        # Strategy 2: JS text-node walker — finds text regardless of element type
        pos = await self.page.evaluate("""
            (value) => {
              const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
              const v = norm(value);
              // Walk all text nodes in the document
              const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
              let node;
              while ((node = walker.nextNode())) {
                const text = norm(node.textContent || '');
                if (!text || text.length > 80) continue;
                if (text !== v && !text.startsWith(v)) continue;
                const el = node.parentElement;
                if (!el) continue;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                const b = el.getBoundingClientRect();
                if (!b.width && !b.height) continue;
                return { x: b.left + b.width/2, y: b.top + b.height/2 };
              }
              return null;
            }
        """, value)

        if pos:
            await self.page.mouse.click(pos['x'], pos['y'])
            print(f"  🖱  Clicked option '{value}' at ({pos['x']:.0f},{pos['y']:.0f})")
            await asyncio.sleep(0.3)
            return True
        return False

    async def _click_page_element(self, target: str) -> str:
        """Click a button or link on the current page (not in the nav sidebar)."""
        # Strategy 1: Playwright semantic locators
        for factory in [
            lambda: self.page.get_by_role('button', name=target, exact=False),
            lambda: self.page.get_by_text(target, exact=True),
            lambda: self.page.get_by_role('link', name=target, exact=False),
        ]:
            try:
                loc = factory()
                if await loc.count() > 0:
                    await loc.first.click(timeout=3000)
                    return f"✅ Clicked '{target}'"
            except Exception:
                continue

        # JS fallback: search entire visible page including dropdowns and list items
        pos = await self.page.evaluate("""
            (target) => {
              const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
              const t = norm(target);
              // Include dropdown/menu items — broader selector than nav click
              const sel = [
                'button', 'a', '[role="button"]', '[role="menuitem"]', '[role="option"]',
                'input[type="submit"]', 'input[type="button"]',
                'li', '[class*="dropdown"] *', '[class*="menu-item" i]',
                '[class*="popover"] *', '[class*="overlay"] *'
              ].join(',');
              for (const el of document.querySelectorAll(sel)) {
                const box = el.getBoundingClientRect();
                if (!box.width||!box.height) continue;
                const style = window.getComputedStyle(el);
                if (style.display==='none'||style.visibility==='hidden') continue;
                const text = norm(el.getAttribute('aria-label')||el.innerText||
                                  el.getAttribute('value')||'');
                if (text===t) return {x:box.left+box.width/2, y:box.top+box.height/2};
              }
              return null;
            }
        """, target)

        if pos:
            await self.page.mouse.click(pos['x'], pos['y'])
            return f"✅ Clicked '{target}'"

        return f"❌ Could not find '{target}' on the current page"

    async def _get_page_fields_summary(self) -> str:
        """Return a short text list of visible input fields on the current page."""
        fields = await self.page.evaluate("""
            () => {
              const norm = s => (s||'').replace(/\\s+/g,' ').trim();
              const seen = new Set();
              const items = [];
              const sel = [
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"])',
                'textarea', 'select', '[contenteditable="true"]',
                '[formcontrolname]', '[ng-model]', '[data-model]',
                '[role="textbox"]', '[role="spinbutton"]', '[role="combobox"]'
              ].join(',');
              for (const el of document.querySelectorAll(sel)) {
                const box = el.getBoundingClientRect();
                if (!box.width||!box.height) continue;
                const style = window.getComputedStyle(el);
                if (style.display==='none'||style.visibility==='hidden') continue;
                // Try to find a nearby label
                let labelText = norm(
                  el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
                  el.getAttribute('name') || el.getAttribute('formcontrolname') ||
                  (el.id ? (document.querySelector('label[for="'+el.id+'"]')||{}).innerText : '')
                );
                if (!labelText) {
                  // Check previous siblings / parent's previous sibling for label
                  let prev = el.previousElementSibling || (el.parentElement||{}).previousElementSibling;
                  if (prev) labelText = norm(prev.innerText||'').split('\\n')[0];
                }
                if (!labelText) labelText = el.getAttribute('type') || 'input';
                if (!seen.has(labelText)) { seen.add(labelText); items.push(labelText); }
              }
              return items.slice(0, 20);
            }
        """)
        return ', '.join(fields) if fields else ''

    async def _select_table_row(self, row_number: int) -> str:
        """Click the Nth data row in the main content table (1-based)."""
        pos = await self.page.evaluate("""
            (n) => {
              const vw = window.innerWidth;
              const minX = vw * 0.2;
              const dataRows = [];

              // Primary: Fortinet grid uses div.row-cell.first-cell per row
              for (const el of document.querySelectorAll(
                  '[class*="row-cell"][class*="first-cell"], [class*="row-cell first-cell"]')) {
                const box = el.getBoundingClientRect();
                if (box.left < minX - 10 || !box.width || !box.height) continue;
                const style = window.getComputedStyle(el);
                if (style.display==='none'||style.visibility==='hidden') continue;
                dataRows.push({ x: box.left + box.width / 2, y: box.top + box.height / 2 });
              }

              // Fallback: standard table rows
              if (dataRows.length === 0) {
                for (const tr of document.querySelectorAll('tbody tr, [role="row"]')) {
                  const box = tr.getBoundingClientRect();
                  if (box.left < minX - 10 || !box.width || !box.height) continue;
                  const style = window.getComputedStyle(tr);
                  if (style.display==='none'||style.visibility==='hidden') continue;
                  dataRows.push({ x: box.left + box.width / 2, y: box.top + box.height / 2 });
                }
              }

              // Sort top-to-bottom so row 1 = topmost
              dataRows.sort((a, b) => a.y - b.y);

              if (dataRows.length === 0) return { error: 'No table rows found in main content area' };
              if (n < 1 || n > dataRows.length) return { error: `Row ${n} out of range (table has ${dataRows.length} rows)` };
              return dataRows[n - 1];
            }
        """, row_number)

        if pos.get('error'):
            return f"❌ {pos['error']}"

        await self.page.mouse.click(pos['x'], pos['y'])
        print(f"  🖱  Clicked row {row_number} at ({pos['x']:.0f}, {pos['y']:.0f})")
        await asyncio.sleep(0.5)
        return f"✅ Selected row {row_number}"

    async def _dump_dropdown_options(self) -> str:
        """Diagnostic: dump visible text nodes — works regardless of element type or overlay."""
        items = await self.page.evaluate("""
            () => {
              const norm = s => (s||'').replace(/\\s+/g,' ').trim();
              const results = [];
              const seen = new Set();
              const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
              let node;
              while ((node = walker.nextNode())) {
                const text = norm(node.textContent || '');
                if (!text || text.length > 100 || text.length < 2) continue;
                if (seen.has(text.toLowerCase())) continue;
                seen.add(text.toLowerCase());
                const el = node.parentElement;
                if (!el) continue;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                if (parseFloat(style.opacity) < 0.05) continue;
                const b = el.getBoundingClientRect();
                const cls = (typeof el.className === 'string' ? el.className : '').slice(0,50);
                results.push({
                  tag: el.tagName.toLowerCase(), cls,
                  role: el.getAttribute('role')||'', text,
                  x: Math.round(b.left), y: Math.round(b.top)
                });
              }
              results.sort((a,b) => a.y - b.y);
              return results.slice(0, 60);
            }
        """)
        if not items:
            return "❌ No visible option-like elements found"
        lines = [f"🔍 {len(items)} visible small elements (potential dropdown options):\n"]
        for it in items:
            lines.append(f"  <{it['tag']}> role='{it['role']}' cls='{it['cls']}' text='{it['text']}' pos=({it['x']},{it['y']}) size={it['w']}x{it['h']}")
        return "\n".join(lines)

    async def _select_table_row_by_text(self, text: str) -> str:
        """Click the first row in the main content area whose text contains the given string."""
        # Try Playwright locator first — most reliable
        try:
            vw = await self.page.evaluate("() => window.innerWidth")
            min_x = vw * 0.2

            # Find a row-cell (Fortinet grid) or tr that contains the text
            for loc in [
                self.page.locator('[class*="row-cell"]').filter(has_text=text),
                self.page.locator('tr').filter(has_text=text),
                self.page.locator('[class*="list-item"]').filter(has_text=text),
            ]:
                count = await loc.count()
                if count > 0:
                    # Pick the one on the right side (not sidebar)
                    for i in range(count):
                        item = loc.nth(i)
                        box = await item.bounding_box()
                        if box and box['x'] >= min_x:
                            await self.page.mouse.click(
                                box['x'] + box['width'] / 2,
                                box['y'] + box['height'] / 2
                            )
                            print(f"  🖱  Clicked row containing '{text}'")
                            await asyncio.sleep(0.5)
                            return f"✅ Selected row containing '{text}'"
        except Exception as e:
            print(f"  ⚠️  Playwright row-by-text failed: {e}")

        # JS fallback: walk text nodes, find one matching, click its row ancestor
        pos = await self.page.evaluate("""
            ([text, minX]) => {
              const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
              const t = norm(text);
              const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
              let node;
              while ((node = walker.nextNode())) {
                if (!norm(node.textContent).includes(t)) continue;
                // Walk up to find a row-like ancestor
                let el = node.parentElement;
                for (let i = 0; i < 8 && el; i++, el = el.parentElement) {
                  const cls = typeof el.className === 'string' ? el.className : '';
                  const isRow = cls.includes('row') || el.tagName === 'TR' ||
                                el.getAttribute('role') === 'row';
                  if (!isRow) continue;
                  const b = el.getBoundingClientRect();
                  if (b.left < minX - 10 || !b.width || !b.height) continue;
                  return { x: b.left + b.width / 2, y: b.top + b.height / 2 };
                }
              }
              return null;
            }
        """, [text, min_x if 'min_x' in dir() else 250])

        if pos:
            await self.page.mouse.click(pos['x'], pos['y'])
            print(f"  🖱  Clicked row containing '{text}' at ({pos['x']:.0f},{pos['y']:.0f})")
            await asyncio.sleep(0.5)
            return f"✅ Selected row containing '{text}'"

        return f"❌ Could not find a row containing '{text}'"

    async def _click_near_label(self, btn_text: str, field_label: str) -> str:
        """Click a small element (e.g. '+') that appears near/inside a labeled field."""
        # Strategy: find all cursor:pointer elements in Y range near label, try each
        candidates = await self.page.evaluate("""
            ([btnText, fieldLabel]) => {
              const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
              const bt = norm(btnText);
              const fl = norm(fieldLabel);
              const stripSpecial = s => s.replace(/[^a-z0-9 ]/g, '');
              const vw = window.innerWidth;
              const minX = vw * 0.2;

              const isVisible = el => {
                const box = el.getBoundingClientRect();
                return box.width > 0 && box.height > 0 &&
                  window.getComputedStyle(el).display !== 'none' &&
                  window.getComputedStyle(el).visibility !== 'hidden';
              };

              // Find label
              let labelEl = null;
              for (const lbl of document.querySelectorAll(
                  'label,span,div,td,th,p,field-label,[class*="label"]')) {
                if (!isVisible(lbl)) continue;
                const t = stripSpecial(norm(lbl.innerText || ''));
                if (t && t.includes(stripSpecial(fl))) { labelEl = lbl; break; }
              }
              if (!labelEl) return { debug: 'label not found: ' + fl };

              const labelBox = labelEl.getBoundingClientRect();
              const yMin = labelBox.top - 10;
              const yMax = labelBox.bottom + 160;

              // Collect ALL cursor:pointer elements in that Y band on the right side
              // Constrain x: form content is roughly in the middle 60% of the screen
              // Exclude far-right toolbar area (last 20% of viewport)
              const maxX = vw * 0.80;
              const formCenterX = (minX + maxX) / 2;

              const results = [];
              for (const el of document.querySelectorAll('*')) {
                if (!isVisible(el)) continue;
                const box = el.getBoundingClientRect();
                const elMidX = box.left + box.width / 2;
                const elMidY = box.top + box.height / 2;
                if (elMidX < minX || elMidX > maxX) continue;  // skip sidebar & toolbar
                if (elMidY < yMin || elMidY > yMax) continue;
                if (box.width > 400 || box.height > 80) continue;
                const style = window.getComputedStyle(el);
                const tag = el.tagName.toLowerCase();
                const ariaLabel = (el.getAttribute('aria-label')||'').toLowerCase();
                const title = (el.getAttribute('title')||'').toLowerCase();
                const ownText = norm([...el.childNodes]
                  .filter(n=>n.nodeType===3).map(n=>n.textContent).join(''));

                const isClickable = style.cursor === 'pointer' || tag === 'button' ||
                  tag === 'a' || el.getAttribute('role') === 'button';
                if (!isClickable) continue;

                let score = 0;
                if (ownText === '+' || ownText === '⊕' || ownText === '✚') score += 4;
                if (ownText.includes(bt)) score += 3;
                if (ariaLabel.includes('add') || title.includes('add')) score += 3;
                if (tag === 'button' || el.getAttribute('role') === 'button') score += 1;
                // Prefer elements closer to form center X
                const centerScore = 1 - Math.abs(elMidX - formCenterX) / formCenterX;

                // Distance from label bottom — prefer the closest one
                const yDist = Math.abs(elMidY - labelBox.bottom);
                results.push({ x: elMidX, y: elMidY,
                                score, yDist, tag, ownText, ariaLabel });
              }
              if (!results.length) return { debug: 'no pointer elements in Y range', labelY: Math.round(labelBox.top), yMin: Math.round(yMin), yMax: Math.round(yMax) };
              // Sort: higher text/aria score first; among equal scores, pick closest to label
              results.sort((a,b) => b.score - a.score || a.yDist - b.yDist);
              return results.slice(0, 5);
            }
        """, [btn_text, field_label])

        if isinstance(candidates, dict):
            debug = candidates.get('debug', '')
            return f"❌ Could not find '{btn_text}' near '{field_label}'" + (f" ({debug})" if debug else "")

        if candidates:
            for c in candidates:
                print(f"  🖱  Trying '{btn_text}': tag={c['tag']} text='{c['ownText']}' aria='{c['ariaLabel']}' at ({c['x']:.0f},{c['y']:.0f})")
                try:
                    await self.page.mouse.move(c['x'], c['y'])
                    await asyncio.sleep(0.15)
                    await self.page.mouse.down()
                    await asyncio.sleep(0.05)
                    await self.page.mouse.up()
                    await asyncio.sleep(0.6)
                    return f"✅ Clicked '{btn_text}' in '{field_label}'"
                except Exception:
                    pass
                # Fallback: dispatch_event via JS at those coordinates
                try:
                    await self.page.evaluate("""
                        ([x, y]) => {
                          const el = document.elementFromPoint(x, y);
                          if (el) {
                            el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true}));
                            el.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true}));
                            el.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true}));
                          }
                        }
                    """, [c['x'], c['y']])
                    await asyncio.sleep(0.6)
                    return f"✅ Clicked '{btn_text}' in '{field_label}'"
                except Exception as e:
                    print(f"  ⚠️  dispatch_event failed: {e}")

        return f"❌ Could not find '{btn_text}' near '{field_label}'"

    async def _dump_table_rows(self) -> str:
        """Diagnostic: dump what row-like elements exist in the main content area."""
        items = await self.page.evaluate("""
            () => {
              const vw = window.innerWidth;
              const minX = vw * 0.2;
              const norm = s => (s||'').replace(/\\s+/g,' ').trim().slice(0, 80);
              const results = [];
              // Cast wide net — any element that could be a grid row
              const sel = [
                'table tbody tr', 'tr',
                '[role="row"]', '[role="gridcell"]',
                '[class*="row" i]', '[class*="grid-row" i]',
                '[class*="list-item" i]', '[class*="table-row" i]',
                'li[class*="item" i]'
              ].join(',');
              const seen = new Set();
              for (const el of document.querySelectorAll(sel)) {
                const box = el.getBoundingClientRect();
                if (box.left < minX - 10 || !box.width || !box.height) continue;
                const style = window.getComputedStyle(el);
                if (style.display==='none'||style.visibility==='hidden') continue;
                const key = el.tagName + '|' + Math.round(box.top);
                if (seen.has(key)) continue;
                seen.add(key);
                results.push({
                  tag: el.tagName.toLowerCase(),
                  cls: (el.className||'').slice(0,60),
                  role: el.getAttribute('role')||'',
                  text: norm(el.innerText||''),
                  x: Math.round(box.left), y: Math.round(box.top),
                  w: Math.round(box.width), h: Math.round(box.height)
                });
              }
              return results.slice(0, 30);
            }
        """)
        if not items:
            return "❌ No row-like elements found in main content area (right side)"
        lines = [f"🔍 {len(items)} row-like element(s) found:\n"]
        for it in items:
            lines.append(f"  <{it['tag']}> role='{it['role']}' cls='{it['cls']}' text='{it['text']}' pos=({it['x']},{it['y']})")
        return "\n".join(lines)

    async def _dump_page_fields(self) -> str:
        """Diagnostic: dump all visible inputs on the current page."""
        fields = await self.page.evaluate("""
            () => {
              const norm = s => (s||'').replace(/\\s+/g,' ').trim();
              const results = [];
              const sel = [
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"])',
                'textarea', 'select', '[contenteditable="true"]',
                '[formcontrolname]', '[ng-model]', '[role="textbox"]',
                '[role="spinbutton"]', '[role="combobox"]'
              ].join(',');
              for (const el of document.querySelectorAll(sel)) {
                const box = el.getBoundingClientRect();
                if (!box.width||!box.height) continue;
                const style = window.getComputedStyle(el);
                if (style.display==='none'||style.visibility==='hidden') continue;
                const val = norm(el.value||el.innerText||el.getAttribute('value')||'');
                const info = {
                  tag: el.tagName.toLowerCase(),
                  type: el.getAttribute('type')||'',
                  ariaLabel: el.getAttribute('aria-label')||'',
                  placeholder: el.getAttribute('placeholder')||'',
                  name: el.getAttribute('name')||'',
                  formcontrolname: el.getAttribute('formcontrolname')||'',
                  id: el.id||'',
                  value: val.slice(0,40),
                  x: Math.round(box.left), y: Math.round(box.top)
                };
                // Nearby label
                let prev = el.previousElementSibling || (el.parentElement||{}).previousElementSibling;
                info.nearbyLabel = prev ? norm(prev.innerText||'').split('\\n')[0].slice(0,40) : '';
                results.push(info);
              }
              return results;
            }
        """)
        if not fields:
            return "❌ No visible input fields found on current page"
        lines = [f"📋 {len(fields)} field(s) found on current page:\n"]
        for f in fields:
            label = f.get('ariaLabel') or f.get('placeholder') or f.get('name') or f.get('formcontrolname') or f.get('nearbyLabel') or '(no label)'
            lines.append(f"  • [{f['tag']}] label='{label}' value='{f['value']}' pos=({f['x']},{f['y']})")
        return "\n".join(lines)

    async def _perform_search(self, query: str) -> str:
        for selector in [
            'input[type="search"]', 'input[name*="search" i]',
            'input[placeholder*="search" i]', 'input[aria-label*="search" i]',
        ]:
            try:
                el = await self.page.query_selector(selector)
                if el:
                    await el.fill(query)
                    await el.press('Enter')
                    return f"✅ Searched for: {query}"
            except Exception:
                continue
        return f"❌ Could not find a search field"

    # ------------------------------------------------------------------
    # Disambiguation
    # ------------------------------------------------------------------

    def _format_path_clarification(self, paths: List[List[str]]) -> str:
        target = paths[0][-1]
        lines = [f'"{target}" was found in {len(paths)} locations:']
        for i, path in enumerate(paths, 1):
            lines.append(f"{i}. Main menu → {' → '.join(path)}")
        lines.append("Type a number to choose.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def _login(self):
        login_url = self.credentials.get('login_page') or self.navmap.site_url
        await self.page.goto(login_url)
        await self._wait_for_page_ready("login page")

        username = self.credentials.get('username', '')
        password = self.credentials.get('password', '')

        # Fill username
        for selector in [
            'input[name*="username" i]', 'input[id*="username" i]',
            'input[name*="user" i]', 'input[name*="login" i]',
            'input[type="text"]', 'input[type="email"]',
        ]:
            try:
                await self.page.fill(selector, username)
                print(f"  ✅ Filled username with selector: {selector}")
                break
            except Exception:
                continue

        # Fill password
        password_selector_used = None
        for selector in [
            'input[type="password"]', 'input[name*="password" i]',
            'input[name*="pass" i]', 'input[id*="password" i]',
        ]:
            try:
                await self.page.fill(selector, password)
                password_selector_used = selector
                print(f"  ✅ Filled password with selector: {selector}")
                break
            except Exception:
                continue

        # Click submit button — use short per-attempt timeout to avoid 15s waits
        submitted = False
        for selector in [
            'button[type="submit"]', 'input[type="submit"]',
            'button:has-text("Login")', 'button:has-text("Log In")',
            'button:has-text("Log in")', 'button:has-text("Sign in")',
            'button:has-text("Sign In")', '.btn-login', '.login-button',
            '[class*="login" i][type="submit"]', '[class*="login" i] button',
        ]:
            try:
                el = await self.page.query_selector(selector)
                if el:
                    await el.click(timeout=3000)
                    print(f"  ✅ Clicked submit with selector: {selector}")
                    submitted = True
                    break
            except Exception:
                continue

        # Universal fallback: press Enter on the password field
        if not submitted and password_selector_used:
            try:
                await self.page.press(password_selector_used, 'Enter')
                print(f"  ✅ Submitted login via Enter key on password field")
            except Exception as e:
                print(f"  ⚠️ Could not submit login form: {e}")

        await self._wait_for_page_ready("post-login")
        await asyncio.sleep(2)

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def _call_llm(self, prompt: str) -> str:
        if self.llm_provider == 'anthropic':
            response = self.llm_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        elif self.llm_provider == 'gemini':
            response = self.llm_client.generate_content(prompt)
            return response.text
        raise RuntimeError(f"Unknown LLM provider: {self.llm_provider}")

    def _extract_json(self, text: str) -> Dict:
        text = text.strip()
        # Strip markdown fences if present
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError("No JSON found in LLM response")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _all_paths(self, tree: Dict, prefix: List[str] = None) -> List[List[str]]:
        """Flatten the nav tree into a list of all root-to-leaf paths."""
        prefix = prefix or []
        paths = []
        for label, node in tree.items():
            path = prefix + [label]
            paths.append(path)
            if node.children:
                paths.extend(self._all_paths(node.children, path))
        return paths

    async def _wait_for_page_ready(self, label: str, timeout: int = 15000):
        try:
            await self.page.wait_for_load_state('domcontentloaded', timeout=timeout)
        except PlaywrightTimeoutError:
            print(f"  Warning: timed out waiting for {label}; continuing.")
            return
        try:
            await self.page.wait_for_load_state('networkidle', timeout=3000)
        except PlaywrightTimeoutError:
            pass
