# Quick Start Guide

Get up and running in 5 minutes!

## Step 1: Install (2 minutes)

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium
```

## Step 2: Configure Credentials (1 minute)

**Option A: Use credentials.md file**

```bash
# Copy template
cp credentials.md.template credentials.md

# Edit with your text editor
nano credentials.md  # or vim, code, etc.
```

Replace the placeholders:
```markdown
- **Site URL**: https://your-actual-site.com
- **Login Page**: https://your-actual-site.com/login
- **Application Name**: your_app_name
- **Username**: your_real_username
- **Password**: your_real_password
```

**Option B: Use .env file**

```bash
cp .env.example .env
# Edit .env with your credentials
```

## Step 3: Learn Your Site (1 minute)

```bash
python main.py learn --credentials credentials.md
```

This will:
- ✅ Open a browser
- ✅ Log into your site
- ✅ Map the structure
- ✅ Save knowledge to `knowledge/schemas/`

**Watch it work!** The browser will open and you'll see the agent navigate your site.

## Step 4: Execute Commands (1 minute)

```bash
# First, check what site was learned
python main.py list

# Then execute commands on it (use the site ID from the list)
python main.py execute --site-id your_site_id --credentials credentials.md
```

Now type commands in the interactive prompt:

```
💬 Your command: search for products
💬 Your command: click the first result
💬 Your command: quit
```

## That's it! 🎉

You now have a working web automation agent.

## Next Steps

### 1. Make it smarter with Claude AI

Add to your `.env` file:
```bash
ANTHROPIC_API_KEY=your_api_key_here
```

Now you can use natural language:
- "Find all items under $50"
- "Navigate to settings and change my email"

### 2. Automate more sites

Just repeat the process:
```bash
# Learn another site
python main.py learn --site-url https://another-site.com --username user2 --password pass2

# Execute on it
python main.py list  # See all learned sites
python main.py execute --site-id another_site_com --credentials credentials.md
```

### 3. Run tests to verify everything works

```bash
pytest
```

## Troubleshooting

### Browser doesn't open?
```bash
playwright install chromium
```

### "No knowledge base found"?
```bash
# Make sure you ran the learner first
python main.py learn --credentials credentials.md
```

### Can't find the site ID?
```bash
python main.py list
```

### Need to re-learn after site changes?
```bash
python main.py learn --credentials credentials.md
```

## Common Commands Cheat Sheet

```bash
# Learn a site
python main.py learn --credentials credentials.md

# Learn with max depth
python main.py learn --credentials credentials.md --max-depth 3

# List learned sites
python main.py list

# Execute commands
python main.py execute --site-id SITE_ID --credentials credentials.md

# Run tests
pytest

# Run specific test
pytest tests/test_knowledge.py -v
```

## File Structure Quick Reference

```
web_agent_system/
├── main.py                    # Run this!
├── credentials.md             # Your credentials (create from template)
├── .env                       # Optional: API keys
├── knowledge/schemas/         # Learned sites saved here
├── README.md                  # Full documentation
└── QUICKSTART.md             # This file
```

## Get Help

- Read full docs: `README.md`
- Check examples in: `README.md` Examples section
- Run tests: `pytest -v`

Happy automating! 🤖
