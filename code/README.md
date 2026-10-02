# Web Agent System

A hybrid web automation system with two collaborating agents:
1. **Site Learner (Agent 1)** - Maps website structure and builds a knowledge base
2. **Action Executor (Agent 2)** - Executes user commands using the learned knowledge

## 🏗️ Architecture

```
┌─────────────────────┐
│  1. Site Learner    │  Runs once/periodically
│  - Crawls site      │  
│  - Maps structure   │  
│  - Builds schemas   │  
└──────────┬──────────┘
           │
           ↓ (Saves to)
┌─────────────────────┐
│  2. Knowledge Base  │  Persistent storage
│  - Page schemas     │  
│  - Action patterns  │  
│  - Element selectors│  
└──────────┬──────────┘
           │
           ↓ (Queries)
┌─────────────────────┐
│  3. Action Agent    │  Interactive execution
│  - Interprets cmds  │  
│  - Executes actions │  
│  - Self-corrects    │  
└─────────────────────┘
```

## 📋 Prerequisites

- Python 3.8+
- pip
- A website with login credentials that you want to automate

## 🚀 Installation

### 1. Clone or download this system

```bash
cd web_agent_system
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright browsers

```bash
playwright install chromium
```

### 4. Set up credentials

**Option A: Using credentials.md file (Recommended)**

```bash
cp credentials.md.template credentials.md
# Edit credentials.md with your site details
```

**Option B: Using environment variables**

```bash
cp .env.example .env
# Edit .env with your credentials
```

**Option C: Pass directly via command line**

You can pass credentials directly when running commands (see usage below).

## 📖 Usage

### Step 1: Learn a Website (Agent 1)

This runs the **Site Learner** to map the website structure.

**Using credentials file:**
```bash
python main.py learn --credentials credentials.md
```

**Using environment variables:**
```bash
# Make sure .env is configured
python main.py learn
```

**Using direct parameters:**
```bash
python main.py learn \
  --site-url https://example.com \
  --username myuser \
  --password mypass \
  --max-depth 2
```

**What happens:**
- Browser opens (non-headless by default)
- Agent logs into the site
- Crawls and maps pages
- Identifies interactive elements
- Saves knowledge base to `knowledge/schemas/`

### Step 2: Execute Commands (Agent 2)

This runs the **Action Executor** in interactive mode.

First, list available sites:
```bash
python main.py list
```

Then execute commands on a learned site:
```bash
python main.py execute --site-id example_com --credentials credentials.md
```

**Interactive mode:**
```
🤖 INTERACTIVE MODE
Enter commands to execute on the site.
Type 'quit' or 'exit' to stop.

💬 Your command: search for products
✅ Searched for: search for products

💬 Your command: click the login button
✅ Clicked login button

💬 Your command: quit
👋 Goodbye!
```

## 🔧 Configuration

### Credentials Priority

The system loads credentials in this priority order (highest to lowest):
1. **Direct command-line arguments** (`--site-url`, `--username`, `--password`)
2. **Markdown file** (`credentials.md`)
3. **Environment variables** (`.env`)

### API Key for LLM

For better command interpretation, set up Claude API:

```bash
# Add to .env file
ANTHROPIC_API_KEY=your_api_key_here
```

Without an API key, the system uses basic pattern matching for command interpretation.

## 📁 Project Structure

```
web_agent_system/
├── main.py                 # CLI interface
├── requirements.txt        # Dependencies
├── .env.example           # Environment template
├── credentials.md.template # Credentials template
├── knowledge/             # Knowledge base module
│   ├── models.py         # Data models
│   ├── storage.py        # Save/load knowledge
│   ├── credentials.py    # Credential management
│   └── schemas/          # Saved knowledge bases
├── learner/              # Agent 1: Site Learner
│   └── site_mapper.py    # Website mapping logic
├── executor/             # Agent 2: Action Executor
│   └── action_agent.py   # Command execution logic
└── tests/                # Unit tests
    ├── test_knowledge.py
    ├── test_credentials.py
    ├── test_learner.py
    └── test_executor.py
```

## 🧪 Running Tests

Run all tests:
```bash
pytest
```

Run specific test file:
```bash
pytest tests/test_knowledge.py
```

Run with verbose output:
```bash
pytest -v
```

Run only non-async tests:
```bash
pytest -m "not asyncio"
```

## 💡 Examples

### Example 1: Learn a website with deep crawling

```bash
python main.py learn \
  --credentials credentials.md \
  --max-depth 3
```

### Example 2: Execute specific commands

```bash
# Start interactive session
python main.py execute --site-id example_com --credentials credentials.md

# In the interactive prompt:
💬 Your command: search for "red shoes"
💬 Your command: click the first result
💬 Your command: add to cart
```

### Example 3: Re-learn an updated website

```bash
# The site structure changed, so re-learn it
python main.py learn --credentials credentials.md

# Then continue using the updated knowledge
python main.py execute --site-id example_com --credentials credentials.md
```

## 🎯 How to Set Up Agent 1 (Site Learner)

### Question 1: How and where can I set up the first agent with site URL and credentials?

**Method 1: Using credentials.md (Recommended)**

1. Create your credentials file:
```bash
cp credentials.md.template credentials.md
```

2. Edit `credentials.md`:
```markdown
# Site Credentials

- **Site URL**: https://your-site.com
- **Login Page**: https://your-site.com/login
- **Application Name**: your_app_name
- **Username**: your_username
- **Password**: your_password
```

3. Run the learner:
```bash
python main.py learn --credentials credentials.md
```

**Method 2: Using .env file**

1. Create your .env file:
```bash
cp .env.example .env
```

2. Edit `.env`:
```
SITE_URL=https://your-site.com
SITE_USERNAME=your_username
SITE_PASSWORD=your_password
```

3. Run the learner:
```bash
python main.py learn
```

**Method 3: Direct command line**

```bash
python main.py learn \
  --site-url https://your-site.com \
  --username your_username \
  --password your_password
```

## 🎮 How to Pass Commands to Agent 2 (Action Executor)

### Question 2: How can the user pass commands to the second agent?

**Interactive Mode (Default):**

```bash
python main.py execute --site-id your_site_id --credentials credentials.md
```

This opens an interactive prompt where you type commands:
```
💬 Your command: search for laptops
✅ Searched for: laptops

💬 Your command: click the first result
✅ Clicked element

💬 Your command: add to cart
✅ Added to cart

💬 Your command: quit
```

**Commands the agent can understand:**
- `search for [query]` - Performs a search
- `click [element name]` - Clicks a button or link
- `fill [field] with [value]` - Fills an input field
- Natural language commands (if ANTHROPIC_API_KEY is set)

**With LLM (Claude API):**

Set `ANTHROPIC_API_KEY` in your `.env` file for more sophisticated command interpretation:

```bash
ANTHROPIC_API_KEY=sk-ant-xxxxx
```

Then you can use more natural language:
- "Find all products under $50"
- "Navigate to my account settings"
- "Download the last invoice"

The LLM interprets your intent and maps it to the learned site structure.

## 🔍 Troubleshooting

### Issue: "No knowledge base found"
**Solution:** Run the learner first: `python main.py learn --credentials credentials.md`

### Issue: "Element not found"
**Solution:** The site structure may have changed. Re-run the learner.

### Issue: "Missing required credentials"
**Solution:** Check that credentials.md or .env file has all required fields:
- Site URL
- Application Name (optional, used as the saved site-id)
- Username
- Password

### Issue: Browser doesn't open
**Solution:** Make sure Playwright is installed: `playwright install chromium`

### Issue: "ANTHROPIC_API_KEY not found"
**Solution:** This is optional. The agent will work with basic command interpretation. For better results, set the API key in `.env`.

## 🚨 Security Notes

⚠️ **IMPORTANT:**
- Never commit `credentials.md` or `.env` to version control
- The `.gitignore` file already excludes these
- Store credentials securely
- Use environment-specific credentials
- Consider using a secrets manager for production

## 🛠️ Advanced Usage

### Custom Knowledge Base Location

```python
from knowledge.storage import KnowledgeBase

kb = KnowledgeBase(storage_dir='my/custom/path')
```

### Programmatic Usage

```python
import asyncio
from knowledge.storage import KnowledgeBase
from learner.site_mapper import SiteLearner
from executor.action_agent import ActionAgent

async def main():
    kb = KnowledgeBase()
    
    # Learn a site
    learner = SiteLearner(kb)
    knowledge = await learner.learn_site(
        site_url='https://example.com',
        credentials={'username': 'user', 'password': 'pass'}
    )
    kb.save(knowledge, 'example_com')
    
    # Execute commands
    kb.load('example_com')
    agent = ActionAgent(kb)
    await agent.start_session(credentials)
    result = await agent.execute_command('search for products')
    print(result)
    await agent.close_session()

asyncio.run(main())
```

## 📊 Knowledge Base Format

The knowledge base is stored as JSON in `knowledge/schemas/`:

```json
{
  "site_url": "https://example.com",
  "pages": {
    "login": {
      "url_pattern": "https://example.com/login",
      "elements": {
        "username": {
          "selectors": {
            "primary": "#username",
            "fallbacks": ["input[name='user']"]
          }
        }
      }
    }
  },
  "workflows": {
    "login": {
      "steps": ["enter_username", "enter_password", "submit"]
    }
  }
}
```

## 🤝 Contributing

This is a standalone system, but you can extend it:
- Add new action types in `executor/action_agent.py`
- Improve element detection in `learner/site_mapper.py`
- Add vision-based recovery in error handling
- Support for more complex workflows

## 📝 License

This code is provided as-is for educational and automation purposes.

## 🙋 FAQ

**Q: Can it handle dynamic websites (React, Vue, etc.)?**  
A: Yes, Playwright waits for network idle by default. For heavy SPAs, you may need to adjust wait conditions.

**Q: Does it work with 2FA?**  
A: Currently no. You'll need to handle 2FA manually or extend the code to support it.

**Q: Can I automate multiple sites?**  
A: Yes! Learn each site separately, they'll each get their own knowledge base.

**Q: How often should I re-learn a site?**  
A: When the site structure changes significantly, or on a schedule (e.g., weekly).

**Q: Can this run headless in production?**  
A: Yes, change `headless=False` to `headless=True` in the browser launch calls.

## 📞 Support

For issues or questions, refer to:
- Playwright docs: https://playwright.dev/python/
- Anthropic Claude API: https://docs.anthropic.com/
