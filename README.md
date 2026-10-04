---
title: Cyber Minecraft AI Mod Builder
emoji: ⚔
colorFrom: blue
colorTo: red
sdk: docker
app_port: 7860
pinned: false
---

# 🤖 CYBER MINECRAFT AI MOD BUILDER

A production-ready platform that empowers players to talk with a Telegram bot in natural language and generate playable, downloadable Minecraft mods:
1. **Minecraft Bedrock Add-ons** (`.mcaddon`)
2. **Minecraft Java Fabric Mods** (`.jar`)

The system uses a **Deterministic Build Engine** coupled with open-source local Hugging Face AI models, conversational mod editing, real-time asset generation, and automatic compilation error repair.

---

## 🚀 ARCHITECTURAL FLOW

```
USER PROMPT (Telegram / Web)
      ↓
AI PLANNER (Local HF Model / Heuristic Parser)
      ↓
VALIDATED JSON MOD SPECIFICATION (Pydantic)
      ↓
ASSET STUDIO (Procedural 16x16 / 32x32 Textures)
      ↓
DETERMINISTIC BUILD ENGINE (Bedrock & Fabric)
      ↓
STRICT VALIDATION (UUIDs, Manifests, Registries)
      ↓
AUTOMATIC REPAIR AGENT (Up to 3 Self-Healing Attempts)
      ↓
FINAL ARTIFACT (.mcaddon or .jar)
```

---

## ⚡ DEPLOYMENT ON HUGGING FACE SPACES

### 1. Create a Telegram Bot
1. Open Telegram and search for `@BotFather`.
2. Send `/newbot` and follow the instructions to set the bot name and username (e.g., `CyberCraftAI_Bot`).
3. Copy the generated **HTTP API Token** (e.g. `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`).

### 2. Create the Hugging Face Space
1. Log in to [Hugging Face](https://huggingface.co).
2. Click **New Space** (`https://huggingface.co/new-space`).
3. Enter Space Name: `cyber-minecraft-ai`.
4. License: `MIT` or `Apache 2.0`.
5. Select Space SDK: **Docker** (Blank template).
6. Hardware: **CPU Basic** (2 vCPU / 16 GB RAM) or optional GPU.

### 3. Configure Secrets
In your Hugging Face Space page:
1. Go to **Settings** → **Variables and secrets**.
2. Under **Secrets**, click **New secret**:
   - `TELEGRAM_BOT_TOKEN`: Paste your token from `@BotFather`.
   - `HF_TOKEN`: Your Hugging Face user access token (Read access).
   - *(Optional)* `ADMIN_TOKEN`: A secret passphrase for private API routes.

### 4. Upload Code & Start
1. Clone your Space repository locally or push this project repository to your Space:
   ```bash
   git remote add space https://huggingface.co/spaces/YOUR_USERNAME/cyber-minecraft-ai
   git push space main
   ```
2. Hugging Face will automatically build the Docker image and start the Space.
3. Check the **App** tab to view the Cyber Control Panel.
4. Verify the health check at `https://YOUR_SPACE.hf.space/health`.

### 5. Chat with the Bot
1. Open your Telegram bot and send `/start`.
2. Tap **Create New Mod** (`/newmod`).
3. Select your edition (**Bedrock** or **Java Fabric**).
4. Describe your mod:
   > *"Create a ruby sword called Blood Ruby Sword. Damage 14. Durability 1800. Create a recipe using diamonds and redstone."*
5. The bot will report genuine build stages and immediately deliver your `.mcaddon` or `.jar`!

---

## 🛠 CONVERSATIONAL MOD EDITOR (`/edit`)

Unlike one-shot generators that rewrite the entire codebase and introduce regressions, Cyber Minecraft AI maintains an immutable version history (`v1`, `v2`, `v3`...):

After building a mod, simply reply with:
- *"Make damage 30"*
- *"Change color from red to blue"*
- *"Add another sword called Sapphire Dagger"*
- *"Make the boss twice as strong"*
- *"Remove explosion ability"*
- *"Add crafting recipe with iron and sticks"*

The planner modifies only the requested attributes, validates against Pydantic schemas, and compiles the new version without destroying previous iterations.

---

## 🧠 LOCAL AI MODEL MANAGER & HARDWARE SPECS

The system defaults to running an open-source model locally without paying for proprietary APIs:

- **Configurable Model**: `LOCAL_MODEL_ID=Qwen/Qwen2.5-Coder-1.5B-Instruct`
- **Dynamic Selection (`AUTO_MODEL=true`)**:
  - `CUDA` with ≥14GB VRAM: `Qwen/Qwen2.5-Coder-7B-Instruct`
  - `CUDA` with ≥6GB VRAM: `Qwen/Qwen2.5-Coder-1.5B-Instruct`
  - `CPU` with ≥12GB RAM: `Qwen/Qwen2.5-Coder-1.5B-Instruct`
  - `CPU` Lightweight: `Qwen/Qwen2.5-Coder-0.5B-Instruct`
- **Supported Providers**: `local`, `huggingface_inference`, `groq`, `openrouter`, `custom_openai`.
- **Standby & Memory Protection**: Models are loaded lazily and can be unloaded via the dashboard or `/api/ai/unload` to free RAM for Gradle compilation.

---

## 🛡 SECURITY & BUILD SANDBOX

To prevent injection attacks from user-provided prompts:
- **No Arbitrary Shell Commands**: All builds use predefined, sanitized commands.
- **Identifier Sanitizer**: Namespaces and IDs are restricted to `[a-z0-9_]+`.
- **Path Traversal Protection**: Relative paths and `../` attempts are rejected.
- **Zip Slip & Bomb Protection**: File counts and decompressed byte sizes are strictly capped.

---

## 📡 REST API & DASHBOARD ENDPOINTS

| Endpoint | Method | Description |
|---|---|---|
| `/` | `GET` | Live Cyberpunk Web Dashboard |
| `/health` | `GET` | Complete system health and database check |
| `/api/health` | `GET` | JSON health diagnostics |
| `/api/projects` | `GET` | List all created mods |
| `/api/jobs/{id}` | `GET` | Inspect status, stages, and compiler logs |
| `/api/system` | `GET` | Real-time CPU, RAM, Disk, and GPU metrics |
| `/api/ai/load` | `POST` | Manually load AI model into memory |
| `/api/ai/unload` | `POST` | Unload AI model to release RAM |
| `/api/download/{uid}/{pid}/{v}` | `GET` | Download compiled `.mcaddon` or `.jar` |

---

## 💻 LOCAL DEVELOPMENT & TESTING

1. Clone and enter directory:
   ```bash
   cd cyber-minecraft-ai
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run automated test suite:
   ```bash
   pytest tests -v
   ```
4. Start local development server:
   ```bash
   python main.py
   ```
   Open `http://localhost:7860` in your browser.
