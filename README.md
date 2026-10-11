# 🎬 AniStory AI — Autonomous Animation Studio Agent

> **Turn any idea into a fully-rendered, narrated, 2D animated short film in minutes.**

AniStory AI is an agentic animation system built with Python, FastAPI, Edge-TTS, and FFmpeg that coordinates a multi-agent team to storyboard, illustrate, narrate, and composite animated videos with dynamic camera motion and subtitles.

---

## 🚀 Key Features

* **🎭 Multi-Agent Creative Workflow**:
  * **Screenwriter Agent**: Transforms rough ideas into structured 3-act narrative storyboards (acts, characters, visual scene prompts, and voice scripts).
  * **Visual Artist Agent**: Crafts cohesive visual prompts and renders high-definition keyframes via Pollinations AI (FLUX model) with zero API keys required, plus offline procedural fallbacks.
  * **Voice Actor Agent**: Synthesizes natural, human-like voiceovers in English, Vietnamese, Japanese, French, and Spanish via Microsoft Edge-TTS with microsecond timestamp alignment.
  * **Cinematographer & Compositor Engine**: Applies cinematic 2.5D Ken Burns camera motions (zoom-in, zoom-out, pan-left, pan-right), burns high-contrast subtitles, synthesizes ambient musical chords, and exports a broadcast-ready `.mp4` video.
* **🎨 Multiple Animation Art Styles**:
  * 🍃 **Studio Ghibli 2D Anime** (Warm watercolor, lush whimsical aesthetic)
  * 🧸 **3D Pixar / Disney** (Soft volumetric lighting, 3D character design)
  * 📖 **Classic Storybook Fairy Tale** (Delicate ink line art, gouache textures)
  * ✨ **Cinematic Shonen / Makoto Shinkai** (Breathtaking skies, lens flares)
  * 🏙️ **Cyberpunk Neon Sci-Fi** (Futuristic holographic glows, rain reflections)
  * 💥 **Graphic Novel / Comic** (Bold inked outlines, dynamic comic framing)
* **💻 Interactive Director's Web UI**:
  * Glassmorphism dark-mode interface built with Vanilla CSS and Google Fonts.
  * Live scene editing (tweak visual prompts, rewrite narration, change camera movements).
  * Scene illustration re-roll button.
  * Real-time agent status tracker and progress bar.
  * Integrated Cinema Theatre video player with 1-click MP4 download.
* **⚡ 100% Free & Open Tech Stack**:
  * No expensive subscriptions or required API tokens to run.
  * Self-contained FFmpeg engine (pre-configured for Windows).

---

## 🛠️ Quick Start

### 1. Launch the Studio
In the project directory, run:
```bash
python run.py
```
This starts the local FastAPI server and opens your browser at `http://localhost:8088`.
*(You can also pass a custom port: `python run.py 8888`)*

### 2. Create Your First Film
1. **Enter an Idea**: Type any premise or pick a quick spark.
2. **Choose Art Style & Narrator**: Select your favorite visual style and voice actor.
3. **Generate Storyboard**: Click **Generate Storyboard & Scenes**.
4. **Direct & Customize**: Review your scene cards, tweak dialogue, or re-paint any illustration.
5. **Render Full Film**: Click **Render Full Film 🚀** to watch the agents generate speech, apply camera motion, and mix the soundtrack.
6. **Download & Share**: Play the finished animation in the Cinema player and download your `.mp4` file!

---

## 📂 Project Architecture

```
f:\AI\agents\
├── backend/
│   ├── config.py             # Voice models, art style presets, FFmpeg resolution
│   ├── agents/
│   │   ├── script_agent.py   # Screenwriting & narrative structure agent
│   │   └── voice_agent.py    # Edge-TTS speech synthesis & SRT generator
│   ├── services/
│   │   ├── image_service.py  # Pollinations FLUX generator & procedural fallback
│   │   ├── music_service.py  # Ambient procedural acoustic musical tracks
│   │   └── video_engine.py   # FFmpeg Ken Burns camera motions & video rendering
│   ├── pipeline.py           # Master Pipeline Orchestrator Agent
│   └── app.py                # FastAPI REST API & static server
├── static/
│   ├── index.html            # Glassmorphism studio interface
│   ├── css/style.css         # Styling system & responsive layout
│   └── js/app.js             # Client workflow and polling logic
├── output/                   # Projects, audio files, scene clips, and MP4 outputs
├── run.py                    # One-command launcher
└── requirements.txt
```
