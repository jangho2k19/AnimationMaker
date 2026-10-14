/**
 * AniStory AI — Frontend Application Logic
 */

class AniStoryApp {
  constructor() {
    this.currentProject = null;
    this.config = null;
    this.selectedStyleKey = localStorage.getItem("anistory_cfg_art_style") || "ghibli";
    this.pollInterval = null;

    this.initElements();
    this.restoreCachedProjectSync();
    this.attachEvents();
    this.loadConfig();
  }

  saveActiveProjectState() {
    if (this.currentProject && this.currentProject.id) {
      localStorage.setItem("anistory_active_project_id", this.currentProject.id);
      try {
        sessionStorage.setItem("anistory_cached_project", JSON.stringify(this.currentProject));
      } catch (e) {
        // Safe ignore on heavy quota
      }
    } else {
      localStorage.removeItem("anistory_active_project_id");
      sessionStorage.removeItem("anistory_cached_project");
    }
  }

  clearActiveProjectState() {
    this.currentProject = null;
    localStorage.removeItem("anistory_active_project_id");
    localStorage.removeItem("anistory_active_stage");
    sessionStorage.removeItem("anistory_cached_project");
    if (window.history && typeof window.history.replaceState === "function") {
      try {
        window.history.replaceState({ stage: 1 }, "", window.location.pathname);
      } catch (e) {}
    }
  }

  restoreCachedProjectSync() {
    try {
      const cached = sessionStorage.getItem("anistory_cached_project");
      if (!cached) return;
      const proj = JSON.parse(cached);
      if (!proj || !proj.id) return;
      this.currentProject = proj;

      let targetStage = 1;
      const hashMatch = window.location.hash.match(/#stage([1-4])/);
      if (hashMatch) {
        targetStage = parseInt(hashMatch[1], 10);
      } else {
        const savedStage = localStorage.getItem("anistory_active_stage");
        if (savedStage) {
          targetStage = parseInt(savedStage, 10);
        } else if (proj.status === "completed") {
          targetStage = 4;
        } else if (proj.status === "rendering") {
          targetStage = 3;
        } else {
          targetStage = 2;
        }
      }

      if (targetStage === 4 || (proj.status === "completed" && targetStage >= 3)) {
        this.showCinemaPremiere(false);
      } else if (targetStage === 3) {
        this.renderStoryboardView();
        this.switchStage(3, false);
      } else if (targetStage === 2) {
        this.renderStoryboardView();
        this.switchStage(2, false);
      }
    } catch (e) {
      console.warn("restoreCachedProjectSync error:", e);
    }
  }

  async restoreActiveProject() {
    const savedProjectId = localStorage.getItem("anistory_active_project_id");
    if (!savedProjectId) return;

    try {
      const resp = await fetch(`/api/projects/${encodeURIComponent(savedProjectId)}`);
      if (!resp.ok) {
        this.clearActiveProjectState();
        this.switchStage(1, false);
        return;
      }
      const proj = await resp.json();
      this.currentProject = proj;
      this.saveActiveProjectState();

      let targetStage = 1;
      const hashMatch = window.location.hash.match(/#stage([1-4])/);
      if (hashMatch) {
        targetStage = parseInt(hashMatch[1], 10);
      } else {
        const savedStage = localStorage.getItem("anistory_active_stage");
        if (savedStage) {
          targetStage = parseInt(savedStage, 10);
        } else if (proj.status === "completed") {
          targetStage = 4;
        } else if (proj.status === "rendering") {
          targetStage = 3;
        } else {
          targetStage = 2;
        }
      }

      if (targetStage === 4 || (proj.status === "completed" && targetStage >= 3)) {
        this.showCinemaPremiere(false);
      } else if (targetStage === 3) {
        this.renderStoryboardView();
        this.switchStage(3, false);
        const pct = proj.progress || 35;
        this.renderProgressBar.style.width = `${pct}%`;
        this.renderProgressPercent.textContent = `${pct}%`;
        this.renderStepDetail.textContent = proj.current_step || "Processing animation...";
        this.updateActivityLogs(pct, proj.current_step);
        if (proj.status === "rendering") {
          this.pollRenderProgress();
        }
      } else if (targetStage === 2) {
        this.renderStoryboardView();
        this.switchStage(2, false);
        this.autoGenerateMissingSceneImages();
      } else {
        this.switchStage(1, false);
      }
    } catch (err) {
      console.warn("Could not restore active project:", err);
    }
  }

  initElements() {
    // Stepper tabs
    this.tabs = [
      document.getElementById("stepTab1"),
      document.getElementById("stepTab2"),
      document.getElementById("stepTab3"),
      document.getElementById("stepTab4")
    ];

    // Stage panels
    this.stages = [
      document.getElementById("stage1Idea"),
      document.getElementById("stage2Storyboard"),
      document.getElementById("stage3Rendering"),
      document.getElementById("stage4Cinema")
    ];

    // Form inputs
    this.inputProjectTitle = document.getElementById("inputProjectTitle");
    this.inputIdeaPrompt = document.getElementById("inputIdeaPrompt");
    this.styleOptionsGrid = document.getElementById("styleOptionsGrid");
    this.selectVoice = document.getElementById("selectVoice");
    this.selectSceneCount = document.getElementById("selectSceneCount");
    this.selectLanguage = document.getElementById("selectLanguage");
    this.selectAudience = document.getElementById("selectAudience");
    this.btnGenerateStoryboard = document.getElementById("btnGenerateStoryboard");

    // Storyboard stage elements
    this.storyboardFilmTitle = document.getElementById("storyboardFilmTitle");
    this.storyboardLogline = document.getElementById("storyboardLogline");
    this.storyboardScenesGrid = document.getElementById("storyboardScenesGrid");
    this.btnSaveStoryboardEdits = document.getElementById("btnSaveStoryboardEdits");
    this.btnProceedToRender = document.getElementById("btnProceedToRender");
    this.btnPaintAllImages = document.getElementById("btnPaintAllImages");
    this.btnAnimateAllScenes = document.getElementById("btnAnimateAllScenes");
    this.btnOpenGoogleFlow = document.getElementById("btnOpenGoogleFlow");
    this.inputCharacterConsistency = document.getElementById("inputCharacterConsistency");
    this.btnLockCharacter = document.getElementById("btnLockCharacter");

    // Scene Video Modal & Cinema Clips elements
    this.modalSceneVideo = document.getElementById("modalSceneVideo");
    this.btnCloseSceneVideoModal = document.getElementById("btnCloseSceneVideoModal");
    this.modalSceneVideoPlayer = document.getElementById("modalSceneVideoPlayer");
    this.modalSceneVideoTitle = document.getElementById("modalSceneVideoTitle");
    this.modalSceneVideoMeta = document.getElementById("modalSceneVideoMeta");
    this.modalSceneVideoDownloadBtn = document.getElementById("modalSceneVideoDownloadBtn");
    this.cinemaSceneClipsWrapper = document.getElementById("cinemaSceneClipsWrapper");
    this.cinemaSceneClipsGrid = document.getElementById("cinemaSceneClipsGrid");
    this.cinemaClipsCountBadge = document.getElementById("cinemaClipsCountBadge");
    window.aniStoryApp = this;

    // Rendering stage elements
    this.renderStepDetail = document.getElementById("renderStepDetail");
    this.renderProgressBar = document.getElementById("renderProgressBar");
    this.renderProgressPercent = document.getElementById("renderProgressPercent");
    this.activityLogList = document.getElementById("activityLogList");

    // Cinema stage elements
    this.cinemaMovieTitle = document.getElementById("cinemaMovieTitle");
    this.cinemaMovieLogline = document.getElementById("cinemaMovieLogline");
    this.cinemaVideoPlayer = document.getElementById("cinemaVideoPlayer");
    this.btnDownloadMovie = document.getElementById("btnDownloadMovie");
    this.btnStartNewStory = document.getElementById("btnStartNewStory");
    this.specArtStyle = document.getElementById("specArtStyle");

    // Modals & Extras
    this.modalSettings = document.getElementById("modalSettings");
    this.btnOpenSettings = document.getElementById("btnOpenSettings");
    this.btnCloseSettings = document.getElementById("btnCloseSettings");
    this.btnSaveSettings = document.getElementById("btnSaveSettings");
    this.inputGeminiApiKey = document.getElementById("inputGeminiApiKey");

    this.modalProjects = document.getElementById("modalProjects");
    this.btnOpenProjects = document.getElementById("btnOpenProjects");
    this.btnCloseProjects = document.getElementById("btnCloseProjects");
    this.btnNewFilmFromModal = document.getElementById("btnNewFilmFromModal");
    this.savedProjectsList = document.getElementById("savedProjectsList");

    // Stage 1 Direct Mode Switcher Elements
    this.tabModePrompt = document.getElementById("tabModePrompt");
    this.tabModePaste = document.getElementById("tabModePaste");
    this.panelPromptMode = document.getElementById("panelPromptMode");
    this.panelPasteMode = document.getElementById("panelPasteMode");
    this.inputDirectPasteText = document.getElementById("inputDirectPasteText");
    this.btnCopyGeminiPromptDirect = document.getElementById("btnCopyGeminiPromptDirect");
    this.btnDirectLoadStoryboard = document.getElementById("btnDirectLoadStoryboard");
    this.groupSceneCount = document.getElementById("groupSceneCount");

    // Import from Gemini Modal elements
    this.modalImport = document.getElementById("modalImport");
    this.btnOpenImportModal = document.getElementById("btnOpenImportModal");
    this.btnCloseImport = document.getElementById("btnCloseImport");
    this.btnCopyGeminiPrompt = document.getElementById("btnCopyGeminiPrompt");
    this.inputImportText = document.getElementById("inputImportText");
    this.btnSubmitImport = document.getElementById("btnSubmitImport");

    this.audioAuditionPlayer = document.getElementById("audioAuditionPlayer");
    this.btnAuditionSampleVoice = document.getElementById("btnAuditionSampleVoice");
    this.iconAuditionVoice = document.getElementById("iconAuditionVoice");
    this.auditionPlayerContainer = document.getElementById("auditionPlayerContainer");
    this.auditionVoiceLabel = document.getElementById("auditionVoiceLabel");
    this.auditionSampleText = document.getElementById("auditionSampleText");
    this.btnCloseAuditionPlayer = document.getElementById("btnCloseAuditionPlayer");
    this.voiceSampleStatus = document.getElementById("voiceSampleStatus");
    this.toastNotification = document.getElementById("toastNotification");

    // Global Navigation Elements
    this.brandHomeLink = document.getElementById("brandHomeLink");
    this.btnNavHome = document.getElementById("btnNavHome");
    this.btnBackToHomeFromStage2 = document.getElementById("btnBackToHomeFromStage2");
    this.btnNewStoryFromStage2 = document.getElementById("btnNewStoryFromStage2");
    this.btnBackToBoardFromStage3 = document.getElementById("btnBackToBoardFromStage3");
    this.btnBackToHomeFromStage3 = document.getElementById("btnBackToHomeFromStage3");
    this.btnCinemaBackToBoard = document.getElementById("btnCinemaBackToBoard");

    // Video Dimensions & Multi-Provider AI Elements
    this.selectAspectRatio = document.getElementById("selectAspectRatio");
    this.badgeStoryboardAspectRatio = document.getElementById("badgeStoryboardAspectRatio");
    this.specResolution = document.getElementById("specResolution");
    this.selectAiProvider = document.getElementById("selectAiProvider");
    this.selectAiModel = document.getElementById("selectAiModel");
    this.inputProviderKey = document.getElementById("inputProviderKey");
    this.groupProviderKey = document.getElementById("groupProviderKey");
    this.btnToggleImageMode = document.getElementById("btnToggleImageMode");
    this.badgeImageMode = document.getElementById("badgeImageMode");
    this.descImageMode = document.getElementById("descImageMode");
    this.iconToggleImageMode = document.getElementById("iconToggleImageMode");
    this.btnToggleImageModeStage2 = document.getElementById("btnToggleImageModeStage2");
    this.iconImageModeStage2 = document.getElementById("iconImageModeStage2");
    this.textImageModeStage2 = document.getElementById("textImageModeStage2");
    this.btnToggleSubtitlesStage2 = document.getElementById("btnToggleSubtitlesStage2");
    this.iconSubtitlesStage2 = document.getElementById("iconSubtitlesStage2");
    this.textSubtitlesStage2 = document.getElementById("textSubtitlesStage2");

    // Modal Settings Extra Keys
    this.selectSettingsImageMode = document.getElementById("selectSettingsImageMode");
    this.inputNeuralLoveApiKey = document.getElementById("inputNeuralLoveApiKey");
    this.inputOpenAiApiKey = document.getElementById("inputOpenAiApiKey");
    this.inputClaudeApiKey = document.getElementById("inputClaudeApiKey");
    this.inputDeepSeekApiKey = document.getElementById("inputDeepSeekApiKey");
    this.inputNvidiaApiKey = document.getElementById("inputNvidiaApiKey");
    this.inputGeminiCookie = document.getElementById("inputGeminiCookie");
    this.inputGeminiCookieTs = document.getElementById("inputGeminiCookieTs");
    this.btnDetectModels = document.getElementById("btnDetectModels");
    this.badgeProviderHint = document.getElementById("badgeProviderHint");
    this.labelProviderKey = document.getElementById("labelProviderKey");

    // Model Explorer Modal elements
    this.modalModelExplorer = document.getElementById("modalModelExplorer");
    this.btnCloseModelExplorer = document.getElementById("btnCloseModelExplorer");
    this.btnDoneModelExplorer = document.getElementById("btnDoneModelExplorer");
    this.tabFilterAll = document.getElementById("tabFilterAll");
    this.tabFilterApi = document.getElementById("tabFilterApi");
    this.tabFilterCookie = document.getElementById("tabFilterCookie");
    this.btnRescanModelsModal = document.getElementById("btnRescanModelsModal");
    this.countAllModels = document.getElementById("countAllModels");
    this.countApiModels = document.getElementById("countApiModels");
    this.countCookieModels = document.getElementById("countCookieModels");
    this.modelsCardsGrid = document.getElementById("modelsCardsGrid");
    this.modelExplorerStatusBar = document.getElementById("modelExplorerStatusBar");
    this.modelExplorerStatusText = document.getElementById("modelExplorerStatusText");
    this.modelExplorerStatusBadge = document.getElementById("modelExplorerStatusBadge");
    this.modelExplorerStatusIcon = document.getElementById("modelExplorerStatusIcon");

    this.detectedModelsData = null;
    this.activeModelFilter = "all";
  }

  attachEvents() {
    // Stage navigation
    this.tabs.forEach((tab, idx) => {
      tab.addEventListener("click", () => {
        if (this.currentProject || idx === 0) {
          this.switchStage(idx + 1);
        } else {
          this.showToast("Create or import a story first to access this stage! 💡");
        }
      });
    });

    // Global Home navigation triggers
    const returnHome = () => this.switchStage(1);

    if (this.brandHomeLink) {
      this.brandHomeLink.addEventListener("click", returnHome);
      this.brandHomeLink.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          returnHome();
        }
      });
    }

    if (this.btnNavHome) {
      this.btnNavHome.addEventListener("click", returnHome);
    }

    if (this.btnBackToHomeFromStage2) {
      this.btnBackToHomeFromStage2.addEventListener("click", returnHome);
    }

    if (this.btnNewStoryFromStage2) {
      this.btnNewStoryFromStage2.addEventListener("click", () => {
        this.clearActiveProjectState();
        if (this.inputProjectTitle) this.inputProjectTitle.value = "";
        this.inputIdeaPrompt.value = "";
        localStorage.removeItem("anistory_draft_prompt");
        this.switchStage(1);
        this.showToast("Ready for a new story concept! 💡");
      });
    }

    if (this.btnBackToBoardFromStage3) {
      this.btnBackToBoardFromStage3.addEventListener("click", () => {
        if (this.currentProject) {
          this.switchStage(2);
        } else {
          this.switchStage(1);
        }
      });
    }

    if (this.btnBackToHomeFromStage3) {
      this.btnBackToHomeFromStage3.addEventListener("click", returnHome);
    }

    if (this.btnCinemaBackToBoard) {
      this.btnCinemaBackToBoard.addEventListener("click", () => {
        if (this.currentProject) {
          this.switchStage(2);
        } else {
          this.switchStage(1);
        }
      });
    }

    // Browser back/forward button history support
    window.addEventListener("popstate", (e) => {
      const targetStage = (e.state && e.state.stage) ? e.state.stage : 1;
      if (targetStage > 1 && !this.currentProject) {
        this.switchStage(1, false);
        return;
      }
      this.switchStage(targetStage, false);
    });

    // Stage 1 Creation Mode Tabs (Prompt vs Direct Paste)
    if (this.tabModePrompt && this.tabModePaste) {
      this.tabModePrompt.addEventListener("click", () => {
        this.tabModePrompt.classList.add("active");
        this.tabModePaste.classList.remove("active");
        if (this.panelPromptMode) this.panelPromptMode.style.display = "block";
        if (this.panelPasteMode) this.panelPasteMode.style.display = "none";
        if (this.btnGenerateStoryboard) this.btnGenerateStoryboard.style.display = "inline-flex";
        if (this.btnDirectLoadStoryboard) this.btnDirectLoadStoryboard.style.display = "none";
        if (this.groupSceneCount) this.groupSceneCount.style.display = "block";
        localStorage.setItem("anistory_cfg_creation_mode", "prompt");
      });

      this.tabModePaste.addEventListener("click", () => {
        this.tabModePaste.classList.add("active");
        this.tabModePrompt.classList.remove("active");
        if (this.panelPromptMode) this.panelPromptMode.style.display = "none";
        if (this.panelPasteMode) this.panelPasteMode.style.display = "block";
        if (this.btnGenerateStoryboard) this.btnGenerateStoryboard.style.display = "none";
        if (this.btnDirectLoadStoryboard) this.btnDirectLoadStoryboard.style.display = "inline-flex";
        if (this.groupSceneCount) this.groupSceneCount.style.display = "block";
        localStorage.setItem("anistory_cfg_creation_mode", "paste");
      });
    }

    // Persist configuration controls to localStorage
    const bindSelectPersistence = (el, key) => {
      if (!el) return;
      const save = () => localStorage.setItem(key, el.value);
      el.addEventListener("change", save);
      el.addEventListener("input", save);
    };

    bindSelectPersistence(this.selectSceneCount, "anistory_cfg_scene_count");
    bindSelectPersistence(this.selectAspectRatio, "anistory_cfg_aspect_ratio");
    bindSelectPersistence(this.selectLanguage, "anistory_cfg_language");
    bindSelectPersistence(this.selectAudience, "anistory_cfg_audience");
    bindSelectPersistence(this.selectVoice, "anistory_cfg_voice");

    if (this.inputIdeaPrompt) {
      this.inputIdeaPrompt.addEventListener("input", () => {
        localStorage.setItem("anistory_draft_prompt", this.inputIdeaPrompt.value);
      });
    }

    // Direct Copy Prompt for Gemini Pro
    if (this.btnCopyGeminiPromptDirect) {
      this.btnCopyGeminiPromptDirect.addEventListener("click", () => {
        const promptText = this.buildGeminiPrompt();
        navigator.clipboard.writeText(promptText);
        const count = this.selectSceneCount ? this.selectSceneCount.value : 4;
        this.showToast(`Prompt for ${count} scenes copied to clipboard! Paste it into Gemini Pro 📑`);
      });
    }

    // Direct Load Into Director's Board button
    if (this.btnDirectLoadStoryboard) {
      this.btnDirectLoadStoryboard.addEventListener("click", () => {
        const text = this.inputDirectPasteText?.value?.trim();
        if (!text) {
          this.showToast("Please paste Gemini's output into the box first! 📋", true);
          this.inputDirectPasteText?.focus();
          return;
        }
        this.handleImportFromText(text, this.btnDirectLoadStoryboard);
      });
    }

    // Quick Sparks inspiration buttons
    document.querySelectorAll(".inspire-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        const text = chip.getAttribute("data-prompt");
        this.inputIdeaPrompt.value = text;
        this.showToast("Inspiration prompt loaded! ✨");
      });
    });

    // Story generation
    this.btnGenerateStoryboard.addEventListener("click", () => this.handleGenerateStoryboard());

    // Storyboard Actions
    this.btnSaveStoryboardEdits.addEventListener("click", () => this.saveStoryboardEdits(true));
    this.btnProceedToRender.addEventListener("click", () => this.startRenderingProcess());
    if (this.btnPaintAllImages) {
      this.btnPaintAllImages.addEventListener("click", () => this.paintAllSceneImages(true));
    }
    if (this.btnAnimateAllScenes) {
      this.btnAnimateAllScenes.addEventListener("click", () => this.animateAllSceneVideos());
    }
    if (this.btnOpenGoogleFlow) {
      this.btnOpenGoogleFlow.addEventListener("click", () => this.openGoogleFlowBrowser());
    }
    if (this.btnLockCharacter) {
      this.btnLockCharacter.addEventListener("click", () => this.saveCharacterConsistency());
    }
    if (this.btnCloseSceneVideoModal) {
      this.btnCloseSceneVideoModal.addEventListener("click", () => this.closeSceneVideoModal());
    }
    if (this.modalSceneVideo) {
      this.modalSceneVideo.addEventListener("click", (e) => {
        if (e.target === this.modalSceneVideo) this.closeSceneVideoModal();
      });
    }

    // Cinema restart
    this.btnStartNewStory.addEventListener("click", () => {
      this.clearActiveProjectState();
      if (this.inputProjectTitle) this.inputProjectTitle.value = "";
      this.inputIdeaPrompt.value = "";
      localStorage.removeItem("anistory_draft_prompt");
      this.switchStage(1);
    });

    // Settings Modal
    this.btnOpenSettings.addEventListener("click", () => {
      this.inputGeminiApiKey.value = localStorage.getItem("anistory_key_gemini") || localStorage.getItem("anistory_gemini_key") || "";
      if (this.inputGeminiCookie) {
        this.inputGeminiCookie.value = localStorage.getItem("anistory_gemini_cookie_psid") || localStorage.getItem("anistory_key_gemini_cookie") || "";
      }
      if (this.inputGeminiCookieTs) {
        this.inputGeminiCookieTs.value = localStorage.getItem("anistory_gemini_cookie_psidts") || "";
      }
      if (this.inputNeuralLoveApiKey) this.inputNeuralLoveApiKey.value = localStorage.getItem("anistory_key_neural_love") || "";
      if (this.inputOpenAiApiKey) this.inputOpenAiApiKey.value = localStorage.getItem("anistory_key_openai") || "";
      if (this.inputClaudeApiKey) this.inputClaudeApiKey.value = localStorage.getItem("anistory_key_claude") || "";
      if (this.inputDeepSeekApiKey) this.inputDeepSeekApiKey.value = localStorage.getItem("anistory_key_deepseek") || "";
      if (this.inputNvidiaApiKey) this.inputNvidiaApiKey.value = localStorage.getItem("anistory_key_nvidia") || "";
      if (this.selectSettingsImageMode) this.selectSettingsImageMode.value = this.imageMode || "server";
      this.modalSettings.classList.add("active");
    });
    this.btnCloseSettings.addEventListener("click", () => this.modalSettings.classList.remove("active"));
    this.btnSaveSettings.addEventListener("click", () => {
      const geminiVal = this.inputGeminiApiKey.value.trim();
      localStorage.setItem("anistory_key_gemini", geminiVal);
      localStorage.setItem("anistory_gemini_key", geminiVal);

      if (this.inputGeminiCookie) {
        const psid = this.inputGeminiCookie.value.trim();
        const psidts = this.inputGeminiCookieTs ? this.inputGeminiCookieTs.value.trim() : "";
        localStorage.setItem("anistory_gemini_cookie_psid", psid);
        localStorage.setItem("anistory_gemini_cookie_psidts", psidts);
        const combined = psidts ? `${psid}|${psidts}` : psid;
        localStorage.setItem("anistory_key_gemini_cookie", combined);
      }

      if (this.inputNeuralLoveApiKey) localStorage.setItem("anistory_key_neural_love", this.inputNeuralLoveApiKey.value.trim());
      if (this.inputOpenAiApiKey) localStorage.setItem("anistory_key_openai", this.inputOpenAiApiKey.value.trim());
      if (this.inputClaudeApiKey) localStorage.setItem("anistory_key_claude", this.inputClaudeApiKey.value.trim());
      if (this.inputDeepSeekApiKey) localStorage.setItem("anistory_key_deepseek", this.inputDeepSeekApiKey.value.trim());
      if (this.inputNvidiaApiKey) localStorage.setItem("anistory_key_nvidia", this.inputNvidiaApiKey.value.trim());
      if (this.selectSettingsImageMode) {
        this.setImageMode(this.selectSettingsImageMode.value);
      }
      if (this.selectAiProvider && this.inputProviderKey) {
        const curP = this.selectAiProvider.value;
        if (curP === "gemini_cookie") {
          this.inputProviderKey.value = localStorage.getItem("anistory_key_gemini_cookie") || "";
        } else {
          this.inputProviderKey.value = localStorage.getItem(`anistory_key_${curP}`) || (curP === "gemini" ? geminiVal : "");
        }
      }

      // Sync credentials to server
      fetch("/api/save-credentials", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          gemini_api_key: geminiVal,
          gemini_cookie_psid: this.inputGeminiCookie ? this.inputGeminiCookie.value.trim() : "",
          gemini_cookie_psidts: this.inputGeminiCookieTs ? this.inputGeminiCookieTs.value.trim() : "",
          neural_love_key: this.inputNeuralLoveApiKey ? this.inputNeuralLoveApiKey.value.trim() : "",
          openai_api_key: this.inputOpenAiApiKey ? this.inputOpenAiApiKey.value.trim() : "",
          claude_api_key: this.inputClaudeApiKey ? this.inputClaudeApiKey.value.trim() : "",
          deepseek_api_key: this.inputDeepSeekApiKey ? this.inputDeepSeekApiKey.value.trim() : "",
          nvidia_api_key: this.inputNvidiaApiKey ? this.inputNvidiaApiKey.value.trim() : ""
        })
      }).catch(err => console.warn("Credential sync notice:", err));

      this.modalSettings.classList.remove("active");
      this.showToast("Settings & API keys saved successfully! ⚙️");
      // Auto-detect Gemini models if key or cookie was updated
      if (this.selectAiProvider && (this.selectAiProvider.value === "gemini" || this.selectAiProvider.value === "gemini_cookie")) {
        this.detectGeminiModels(true);
      }
    });

    // Image Painting Mode Toggles (Server API vs Neural.love vs Gemini Imagen 3 vs Puter.js In-Browser)
    const toggleImageModeHandler = () => {
      const modes = ["server", "neural_love", "gemini", "puter"];
      const currentIdx = Math.max(0, modes.indexOf(this.imageMode));
      const nextMode = modes[(currentIdx + 1) % modes.length];
      this.setImageMode(nextMode);
      const label = nextMode === "gemini" ? "✨ Google Gemini / Imagen 3" : (nextMode === "neural_love" ? "💖 Neural.love AI Art" : (nextMode === "puter" ? "🖌️ In-Browser Puter.js" : "🌐 Free Neural AI"));
      this.showToast(`Switched Image Mode to: ${label}`);
    };

    if (this.btnDetectModels) {
      this.btnDetectModels.addEventListener("click", () => this.openModelExplorer());
    }
    if (this.btnCloseModelExplorer) {
      this.btnCloseModelExplorer.addEventListener("click", () => this.modalModelExplorer?.classList.remove("active"));
    }
    if (this.btnDoneModelExplorer) {
      this.btnDoneModelExplorer.addEventListener("click", () => this.modalModelExplorer?.classList.remove("active"));
    }
    if (this.btnRescanModelsModal) {
      this.btnRescanModelsModal.addEventListener("click", () => this.detectGeminiModels(false));
    }
    if (this.tabFilterAll) {
      this.tabFilterAll.addEventListener("click", () => this.setModelFilter("all"));
    }
    if (this.tabFilterApi) {
      this.tabFilterApi.addEventListener("click", () => this.setModelFilter("api"));
    }
    if (this.tabFilterCookie) {
      this.tabFilterCookie.addEventListener("click", () => this.setModelFilter("cookie"));
    }

    if (this.btnToggleImageMode) {
      this.btnToggleImageMode.addEventListener("click", toggleImageModeHandler);
    }
    if (this.btnToggleImageModeStage2) {
      this.btnToggleImageModeStage2.addEventListener("click", toggleImageModeHandler);
    }

    // Toggle Subtitles in Stage 2
    if (this.btnToggleSubtitlesStage2) {
      this.btnToggleSubtitlesStage2.addEventListener("click", async () => {
        if (!this.currentProject) return;
        try {
          const resp = await fetch(`/api/projects/${this.currentProject.id}/toggle-subtitles`, { method: "POST" });
          if (resp.ok) {
            const data = await resp.json();
            this.currentProject.enable_subtitles = data.enable_subtitles;
            this.updateSubtitlesUI(this.currentProject.enable_subtitles);
            this.showToast(data.enable_subtitles ? "💬 Captions enabled" : "🔇 Captions disabled (clean video)");
          }
        } catch (e) {
          console.error(e);
        }
      });
    }

    // Projects Modal
    this.btnOpenProjects.addEventListener("click", () => this.openProjectsModal());
    this.btnCloseProjects.addEventListener("click", () => this.modalProjects.classList.remove("active"));
    if (this.btnNewFilmFromModal) {
      this.btnNewFilmFromModal.addEventListener("click", () => {
        this.modalProjects.classList.remove("active");
        this.clearActiveProjectState();
        if (this.inputProjectTitle) this.inputProjectTitle.value = "";
        this.inputIdeaPrompt.value = "";
        this.switchStage(1);
        this.showToast("Ready to create a new animated story! 🎬");
      });
    }

    // Audition sample voice
    if (this.btnAuditionSampleVoice && this.audioAuditionPlayer) {
      const resetAuditionUI = () => {
        if (this.iconAuditionVoice) this.iconAuditionVoice.textContent = "🔊";
        if (this.btnAuditionSampleVoice) {
          this.btnAuditionSampleVoice.title = "Click to listen to sample audio";
          this.btnAuditionSampleVoice.disabled = false;
        }
        if (this.voiceSampleStatus) this.voiceSampleStatus.textContent = "Audition Ready";
      };

      this.audioAuditionPlayer.addEventListener("ended", resetAuditionUI);
      this.audioAuditionPlayer.addEventListener("pause", () => {
        if (this.audioAuditionPlayer.currentTime === 0 || this.audioAuditionPlayer.ended) {
          resetAuditionUI();
        }
      });
      this.audioAuditionPlayer.addEventListener("error", () => {
        resetAuditionUI();
        this.showToast("Audio playback error occurred", true);
      });

      if (this.btnCloseAuditionPlayer) {
        this.btnCloseAuditionPlayer.addEventListener("click", () => {
          this.audioAuditionPlayer.pause();
          this.audioAuditionPlayer.currentTime = 0;
          if (this.auditionPlayerContainer) this.auditionPlayerContainer.style.display = "none";
          resetAuditionUI();
        });
      }

      if (this.selectVoice) {
        this.selectVoice.addEventListener("change", () => {
          if (!this.audioAuditionPlayer.paused) {
            this.audioAuditionPlayer.pause();
            this.audioAuditionPlayer.currentTime = 0;
            resetAuditionUI();
          }
        });
      }

      this.btnAuditionSampleVoice.addEventListener("click", async (e) => {
        e.preventDefault();

        // If audio is already actively playing, toggle pause/stop
        if (!this.audioAuditionPlayer.paused && this.audioAuditionPlayer.currentTime > 0) {
          this.audioAuditionPlayer.pause();
          this.audioAuditionPlayer.currentTime = 0;
          resetAuditionUI();
          this.showToast("Audio preview stopped ⏹️");
          return;
        }

        const selectedVoice = this.selectVoice ? this.selectVoice.value : "en-US-ChristopherNeural";
        const selectedLang = this.selectLanguage ? this.selectLanguage.value : "en";
        const curProvider = this.selectAiProvider?.value || "gemini";
        const curKey = this.getEffectiveApiKey(curProvider);

        this.btnAuditionSampleVoice.disabled = true;
        if (this.iconAuditionVoice) this.iconAuditionVoice.textContent = "⏳";
        if (this.voiceSampleStatus) this.voiceSampleStatus.textContent = "Synthesizing voice...";
        this.showToast(`Synthesizing preview: ${selectedVoice}... 🎙️`);

        try {
          const resp = await fetch("/api/audition-voice", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              voice: selectedVoice,
              language: selectedLang,
              api_key: curKey
            })
          });

          if (!resp.ok) {
            let errMsg = "Voice audition failed";
            try {
              const err = await resp.json();
              errMsg = err.detail || errMsg;
            } catch {}
            throw new Error(errMsg);
          }

          const data = await resp.json();
          if (data.audio_url) {
            if (this.auditionPlayerContainer) {
              this.auditionPlayerContainer.style.display = "block";
            }
            if (this.auditionVoiceLabel) {
              if (data.is_fallback) {
                this.auditionVoiceLabel.textContent = `🔊 ${selectedVoice} (⚡ Matched: ${data.effective_voice})`;
              } else {
                this.auditionVoiceLabel.textContent = `🔊 ${selectedVoice}`;
              }
            }
            if (this.auditionSampleText) {
              this.auditionSampleText.textContent = `"${data.sample_text || ''}"`;
            }
            if (this.voiceSampleStatus) {
              this.voiceSampleStatus.textContent = data.is_fallback ? `🔊 Playing (${data.effective_voice})...` : "🔊 Playing sample...";
            }

            this.audioAuditionPlayer.src = `${data.audio_url}?t=${Date.now()}`;
            this.audioAuditionPlayer.volume = 1.0;
            this.audioAuditionPlayer.muted = false;

            if (this.iconAuditionVoice) this.iconAuditionVoice.textContent = "⏹️";
            this.btnAuditionSampleVoice.title = "Click to stop playing";
            this.btnAuditionSampleVoice.disabled = false;

            try {
              await this.audioAuditionPlayer.play();
              if (data.is_fallback) {
                this.showToast(`Gemini quota limit reached (10/day). Playing matched neural voice: ${data.effective_voice} 🎙️`, false);
              } else {
                this.showToast(`Playing sample: ${selectedVoice} 🔊`);
              }
            } catch (playErr) {
              console.warn("Direct play rejected by browser policy, native controls are ready:", playErr);
              this.showToast(`Preview loaded! Click Play on the player below 🎧`, false);
              resetAuditionUI();
            }
          }
        } catch (e) {
          console.error("Audition error:", e);
          this.showToast(e.message || "Failed to generate voice sample", true);
          resetAuditionUI();
        }
      });
    }

    // Import from Gemini Modal Events
    if (this.btnOpenImportModal) {
      this.btnOpenImportModal.addEventListener("click", () => {
        this.modalImport.classList.add("active");
      });
    }
    if (this.btnCloseImport) {
      this.btnCloseImport.addEventListener("click", () => {
        this.modalImport.classList.remove("active");
      });
    }
    if (this.btnCopyGeminiPrompt) {
      this.btnCopyGeminiPrompt.addEventListener("click", () => {
        const promptText = this.buildGeminiPrompt();
        navigator.clipboard.writeText(promptText);
        const count = this.selectSceneCount ? this.selectSceneCount.value : 4;
        this.showToast(`Prompt for ${count} scenes copied to clipboard! Paste it into Gemini Pro 📑`);
      });
    }
    if (this.btnSubmitImport) {
      this.btnSubmitImport.addEventListener("click", () => this.handleImportStory());
    }
  }

  async loadConfig() {
    try {
      const resp = await fetch("/api/config");
      this.config = await resp.json();
      this.renderStyles(this.config.art_styles);
      this.renderVoices(this.config.voices);
      this.setupAiProviders(this.config.ai_providers);
      this.initImageMode();
      this.restoreSavedConfig();
      await this.loadServerCredentials();
      await this.restoreActiveProject();
    } catch (e) {
      console.error("Config load error:", e);
      this.showToast("Failed to connect to backend engine", true);
    }
  }

  async loadServerCredentials() {
    try {
      const resp = await fetch("/api/credentials");
      if (resp.ok) {
        const creds = await resp.json();
        if (creds.neural_love_key && !localStorage.getItem("anistory_key_neural_love")) {
          localStorage.setItem("anistory_key_neural_love", creds.neural_love_key);
          if (this.inputNeuralLoveApiKey) this.inputNeuralLoveApiKey.value = creds.neural_love_key;
        }
        if (creds.gemini_cookie_psid && !localStorage.getItem("anistory_gemini_cookie_psid")) {
          localStorage.setItem("anistory_gemini_cookie_psid", creds.gemini_cookie_psid);
          if (creds.gemini_cookie_psidts) {
            localStorage.setItem("anistory_gemini_cookie_psidts", creds.gemini_cookie_psidts);
            localStorage.setItem("anistory_key_gemini_cookie", `${creds.gemini_cookie_psid}|${creds.gemini_cookie_psidts}`);
          }
        }
      }
    } catch (e) {
      // ignore
    }
  }

  restoreSavedConfig() {
    // 1. Number of Scenes
    const savedScenes = localStorage.getItem("anistory_cfg_scene_count");
    if (savedScenes && this.selectSceneCount) {
      this.selectSceneCount.value = savedScenes;
    }

    // 3. Aspect Ratio / Framing
    const savedRatio = localStorage.getItem("anistory_cfg_aspect_ratio");
    if (savedRatio && this.selectAspectRatio) {
      this.selectAspectRatio.value = savedRatio;
    }

    // 4. Narration Language
    const savedLang = localStorage.getItem("anistory_cfg_language");
    if (savedLang && this.selectLanguage) {
      this.selectLanguage.value = savedLang;
    }

    // 5. Tone & Audience
    const savedAudience = localStorage.getItem("anistory_cfg_audience");
    if (savedAudience && this.selectAudience) {
      this.selectAudience.value = savedAudience;
    }

    // 6. Draft Story Idea
    const savedPrompt = localStorage.getItem("anistory_draft_prompt");
    if (savedPrompt && this.inputIdeaPrompt && !this.inputIdeaPrompt.value) {
      this.inputIdeaPrompt.value = savedPrompt;
    }

    // 7. Creation Mode (Prompt vs Direct Paste tab)
    const savedMode = localStorage.getItem("anistory_cfg_creation_mode");
    if (savedMode === "paste" && this.tabModePaste) {
      this.tabModePaste.click();
    } else if (savedMode === "prompt" && this.tabModePrompt) {
      this.tabModePrompt.click();
    }
  }

  initImageMode() {
    this.imageMode = localStorage.getItem("anistory_image_mode") || "server";
    this.applyImageModeUI(this.imageMode);
  }

  setImageMode(mode) {
    this.imageMode = mode;
    localStorage.setItem("anistory_image_mode", mode);
    this.applyImageModeUI(mode);
  }

  applyImageModeUI(mode) {
    if (this.badgeImageMode) {
      if (mode === "gemini") {
        this.badgeImageMode.textContent = "✨ Google Gemini / Imagen 3";
        this.badgeImageMode.style.background = "rgba(245, 158, 11, 0.2)";
        this.badgeImageMode.style.color = "#fbbf24";
      } else if (mode === "neural_love") {
        this.badgeImageMode.textContent = "💖 Neural.love AI Art";
        this.badgeImageMode.style.background = "rgba(236, 72, 153, 0.2)";
        this.badgeImageMode.style.color = "#f472b6";
      } else if (mode === "puter") {
        this.badgeImageMode.textContent = "🖌️ In-Browser Puter.js";
        this.badgeImageMode.style.background = "rgba(16, 185, 129, 0.2)";
        this.badgeImageMode.style.color = "#34d399";
      } else {
        this.badgeImageMode.textContent = "🌐 Free Neural AI (Flux / SDXL)";
        this.badgeImageMode.style.background = "rgba(139, 92, 246, 0.2)";
        this.badgeImageMode.style.color = "#c4b5fd";
      }
    }
    if (this.descImageMode) {
      if (mode === "gemini") {
        this.descImageMode.textContent = "High-fidelity Google Imagen 3 visuals powered by your Gemini API Key or Web Cookie";
      } else if (mode === "neural_love") {
        this.descImageMode.textContent = "High-fidelity artistic anime & fantasy illustrations via your Neural.love API Key";
      } else if (mode === "puter") {
        this.descImageMode.textContent = "In-browser Puter.js AI Paint (subject to Puter balance/quota)";
      } else {
        this.descImageMode.textContent = "Free unlimited Neural AI generation (Flux / SDXL) with zero quota limits";
      }
    }
    if (this.btnToggleImageMode) {
      if (mode === "server") {
        this.btnToggleImageMode.innerHTML = `<span>💖</span> Switch to Neural.love AI Art`;
      } else if (mode === "neural_love") {
        this.btnToggleImageMode.innerHTML = `<span>✨</span> Switch to Google Gemini Imagen 3`;
      } else if (mode === "gemini") {
        this.btnToggleImageMode.innerHTML = `<span>🖌️</span> Switch to In-Browser Puter.js`;
      } else {
        this.btnToggleImageMode.innerHTML = `<span>🌐</span> Switch to Free Neural AI (Flux)`;
      }
    }
    if (this.selectSettingsImageMode) {
      this.selectSettingsImageMode.value = mode;
    }
    if (this.textImageModeStage2 && this.iconImageModeStage2) {
      if (mode === "gemini") {
        this.iconImageModeStage2.textContent = "✨";
        this.textImageModeStage2.textContent = "Paint: Gemini Imagen 3";
      } else if (mode === "neural_love") {
        this.iconImageModeStage2.textContent = "💖";
        this.textImageModeStage2.textContent = "Paint: Neural.love AI";
      } else if (mode === "puter") {
        this.iconImageModeStage2.textContent = "🖌️";
        this.textImageModeStage2.textContent = "Paint: In-Browser Puter";
      } else {
        this.iconImageModeStage2.textContent = "🌐";
        this.textImageModeStage2.textContent = "Paint: Free Neural AI";
      }
    }
  }

  updateSubtitlesUI(enabled) {
    if (this.textSubtitlesStage2 && this.iconSubtitlesStage2) {
      this.iconSubtitlesStage2.textContent = enabled ? "💬" : "🔇";
      this.textSubtitlesStage2.textContent = enabled ? "Captions: ON" : "Captions: OFF";
    }
  }

  buildGeminiPrompt() {
    const idea = this.inputIdeaPrompt?.value?.trim() || "A humble, gentle youth protected by a magical golden carp";
    const numScenes = this.selectSceneCount ? (parseInt(this.selectSceneCount.value, 10) || 4) : 4;
    const targetSceneSec = 15;
    const targetDuration = targetSceneSec * numScenes;
    const aspectRatio = this.selectAspectRatio ? this.selectAspectRatio.value : "16:9";
    const audience = this.selectAudience ? this.selectAudience.value : "General";
    const isVi = this.selectLanguage?.value?.startsWith("vi");
    const langStr = isVi ? "Tiếng Việt" : "English";
    const targetWords = Math.floor(targetSceneSec * 2.5);

    const styleInfo = this.config?.art_styles?.[this.selectedStyleKey];
    const styleName = styleInfo ? styleInfo.name : "Studio Ghibli 2D";

    const motionCycles = ["zoom_in", "pan_right", "pan_left", "subtle_drift", "zoom_out"];
    const scenesSkeleton = [];
    for (let i = 1; i <= numScenes; i++) {
      const motion = motionCycles[(i - 1) % motionCycles.length];
      scenesSkeleton.push(`    {
      "scene_number": ${i},
      "title": "Scene ${i} Title in ${langStr}",
      "visual_prompt": "Ultra-detailed visual image description for an AI artist in ${styleName}, ${aspectRatio} cinematic framing",
      "narration": "Evocative voiceover narration in ${langStr} (~${targetWords} words, paced for ~${targetSceneSec} seconds)",
      "camera_motion": "${motion}"
    }`);
    }

    return `Please act as an award-winning animation director at Pixar and Studio Ghibli.
Create a rich, emotionally captivating animated short film screenplay based on this premise:
Idea: "${idea}"

Film Specifications:
- Number of Scenes: EXACTLY ${numScenes} SCENES (Must have all scenes 1 through ${numScenes}).
- Target Total Duration: ${targetDuration} seconds (~${targetSceneSec} seconds per scene).
- Language: Titles and Narration MUST be written in ${langStr}.
- Visual Art Style: ${styleName}.
- Framing: ${aspectRatio} cinematic aspect ratio for all visual prompts.
- Target Audience: ${audience}.
- Narration Pacing: Approximately ${targetWords} words per scene in ${langStr}.

Return ONLY valid JSON matching this exact structure:
{
  "title": "Creative Film Title in ${langStr}",
  "logline": "1-sentence synopsis in ${langStr}",
  "characters": "Brief character description",
  "scenes": [
${scenesSkeleton.join(",\n")}
  ]
}

CRITICAL: You MUST include exactly ${numScenes} scenes in the "scenes" array. Do not stop at 4. Return raw valid JSON only.`;
  }

  openModelExplorer() {
    if (this.modalModelExplorer) {
      this.modalModelExplorer.classList.add("active");
      this.detectGeminiModels(true);
    }
  }

  setModelFilter(filter) {
    this.activeModelFilter = filter;
    if (this.tabFilterAll) this.tabFilterAll.className = `glass-btn ${filter === "all" ? "primary-btn" : "secondary-btn"}`;
    if (this.tabFilterApi) this.tabFilterApi.className = `glass-btn ${filter === "api" ? "primary-btn" : "secondary-btn"}`;
    if (this.tabFilterCookie) this.tabFilterCookie.className = `glass-btn ${filter === "cookie" ? "primary-btn" : "secondary-btn"}`;
    this.renderModelCards();
  }

  renderModelCards() {
    if (!this.modelsCardsGrid) return;
    this.modelsCardsGrid.innerHTML = "";

    const data = this.detectedModelsData;
    const apiList = data?.api_models || [];
    const cookieList = data?.cookie_models || [];

    let combined = [];
    if (this.activeModelFilter === "all") {
      combined = [...apiList, ...cookieList];
    } else if (this.activeModelFilter === "api") {
      combined = [...apiList];
    } else if (this.activeModelFilter === "cookie") {
      combined = [...cookieList];
    }

    if (this.countAllModels) this.countAllModels.textContent = apiList.length + cookieList.length;
    if (this.countApiModels) this.countApiModels.textContent = apiList.length;
    if (this.countCookieModels) this.countCookieModels.textContent = cookieList.length;

    const currentSelectedModel = this.selectAiModel ? this.selectAiModel.value : "";

    if (combined.length === 0) {
      this.modelsCardsGrid.innerHTML = `
        <div style="grid-column: 1 / -1; text-align:center; padding: 30px; color: var(--text-muted);">
          <span style="font-size:32px; display:block; margin-bottom:8px;">🔍</span>
          No models detected for this category yet. Click <strong>"Re-scan Live Models"</strong> above.
        </div>
      `;
      return;
    }

    combined.forEach(m => {
      const isSelected = m.id === currentSelectedModel;
      const isCookie = m.category === "cookie";
      const card = document.createElement("div");
      card.className = "model-explorer-card";
      card.style.cssText = `
        background: ${isSelected ? "rgba(139, 92, 246, 0.2)" : "rgba(255, 255, 255, 0.04)"};
        border: 1px solid ${isSelected ? "var(--primary)" : "var(--border-subtle)"};
        border-radius: var(--radius-md);
        padding: 14px 16px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        gap: 10px;
        transition: all 0.2s ease;
        cursor: pointer;
      `;

      card.innerHTML = `
        <div>
          <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6px; gap:8px;">
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="font-size:16px;">${isCookie ? "🍪" : "✨"}</span>
              <strong style="font-size:14px; color:var(--text-main); font-family:'Outfit',sans-serif;">${m.name}</strong>
            </div>
            <span style="font-size:10px; padding:2px 8px; border-radius:10px; background:${isCookie ? "rgba(245,158,11,0.2)" : "rgba(139,92,246,0.25)"}; color:${isCookie ? "#fbbf24" : "#c4b5fd"}; font-weight:700; white-space:nowrap;">
              ${m.badge || (isCookie ? "Web Cookie" : "API")}
            </span>
          </div>
          <div style="font-size:11px; font-family:monospace; color:var(--text-muted); margin-bottom:6px;">
            ID: <code style="color:#a78bfa;">${m.id}</code>
          </div>
          <p style="font-size:12px; color:var(--text-muted); line-height:1.4; margin:0;">
            ${m.description || "General purpose screenplay generation."}
          </p>
        </div>
        <div style="display:flex; justify-content:flex-end; align-items:center; margin-top:4px;">
          <button type="button" class="glass-btn ${isSelected ? "primary-btn" : "secondary-btn"}" style="padding:4px 12px; font-size:12px; pointer-events:none;">
            ${isSelected ? "✓ Active Model" : "Select Model 🚀"}
          </button>
        </div>
      `;

      card.addEventListener("click", () => {
        this.selectModelById(m.id, isCookie);
      });

      this.modelsCardsGrid.appendChild(card);
    });
  }

  selectModelById(modelId, isCookie = false) {
    if (this.selectAiProvider) {
      if (isCookie && this.selectAiProvider.value !== "gemini_cookie") {
        this.selectAiProvider.value = "gemini_cookie";
        localStorage.setItem("anistory_cfg_provider", "gemini_cookie");
        this.selectAiProvider.dispatchEvent(new Event("change"));
      } else if (!isCookie && this.selectAiProvider.value === "gemini_cookie") {
        this.selectAiProvider.value = "gemini";
        localStorage.setItem("anistory_cfg_provider", "gemini");
        this.selectAiProvider.dispatchEvent(new Event("change"));
      }
    }

    if (this.selectAiModel) {
      let optionExists = false;
      for (let i = 0; i < this.selectAiModel.options.length; i++) {
        if (this.selectAiModel.options[i].value === modelId) {
          this.selectAiModel.selectedIndex = i;
          optionExists = true;
          break;
        }
      }
      if (!optionExists) {
        const opt = document.createElement("option");
        opt.value = modelId;
        opt.textContent = `${modelId} [Custom/Detected]`;
        opt.selected = true;
        this.selectAiModel.appendChild(opt);
      }
      localStorage.setItem("anistory_model_gemini", modelId);
      localStorage.setItem("anistory_cfg_model", modelId);
    }

    if (this.modalModelExplorer) {
      this.modalModelExplorer.classList.remove("active");
    }

    this.showToast(`Selected Gemini model: ${modelId} 🚀`);
  }

  renderModelDropdown(data, currentSelected = null) {
    if (!this.selectAiModel) return;
    const provider = this.selectAiProvider ? this.selectAiProvider.value : "gemini";
    const savedModel = localStorage.getItem("anistory_cfg_model") || localStorage.getItem("anistory_model_gemini");
    const selected = currentSelected || savedModel || this.selectAiModel.value || (provider === "gemini_cookie" ? "gemini-pro-advanced" : "gemini-2.5-flash");

    if (provider !== "gemini" && provider !== "gemini_cookie") return;

    this.selectAiModel.innerHTML = "";

    const apiModels = (data && data.api_models && data.api_models.length > 0) ? data.api_models : [
      { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash", badge: "✨ Recommended / Fast" },
      { id: "gemini-2.5-pro", name: "Gemini 2.5 Pro", badge: "🧠 Deep Reasoning" },
      { id: "gemini-2.0-flash", name: "Gemini 2.0 Flash", badge: "⚡ High Throughput" },
      { id: "gemini-2.0-flash-lite", name: "Gemini 2.0 Flash-Lite", badge: "💨 Ultra Fast" },
      { id: "gemini-1.5-pro", name: "Gemini 1.5 Pro", badge: "📚 Long Context" },
      { id: "gemini-1.5-flash", name: "Gemini 1.5 Flash", badge: "⚡ Standard Flash" }
    ];

    const cookieModels = (data && data.cookie_models && data.cookie_models.length > 0) ? data.cookie_models : [
      { id: "gemini-pro-advanced", name: "Gemini 2.5 Pro Advanced (Web Cookie)", badge: "🧠 Pro Reasoning" },
      { id: "gemini-flash-advanced", name: "Gemini 2.0 Flash Advanced (Web Cookie)", badge: "⚡ Fast Pro" },
      { id: "gemini-pro", name: "Gemini Pro (Standard Web)", badge: "🍪 Web Standard" },
      { id: "gemini-flash", name: "Gemini Flash (Standard Web)", badge: "💨 Fast Web" },
      { id: "default", name: "Gemini Default Web Model", badge: "🍪 Default" }
    ];

    // Optgroup 1: Official API Models
    const groupApi = document.createElement("optgroup");
    groupApi.label = data?.has_live_api ? `✨ Official API Models (${apiModels.length} Live Detected)` : "✨ Google Gemini API Models";
    apiModels.forEach(m => {
      const id = typeof m === "string" ? m : m.id;
      const name = typeof m === "string" ? m : m.name;
      const badge = m.badge ? ` [${m.badge}]` : "";
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = `${name}${badge}`;
      if (id === selected) opt.selected = true;
      groupApi.appendChild(opt);
    });
    this.selectAiModel.appendChild(groupApi);

    // Optgroup 2: Cookie Web Models
    const groupCookie = document.createElement("optgroup");
    groupCookie.label = `🍪 Gemini Pro Web Models (Cookies - ${cookieModels.length} Available)`;
    cookieModels.forEach(m => {
      const id = typeof m === "string" ? m : m.id;
      const name = typeof m === "string" ? m : m.name;
      const badge = m.badge ? ` [${m.badge}]` : "";
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = `${name}${badge}`;
      if (id === selected) opt.selected = true;
      groupCookie.appendChild(opt);
    });
    this.selectAiModel.appendChild(groupCookie);

    // Optgroup 3: Custom Model
    const groupCustom = document.createElement("optgroup");
    groupCustom.label = "➕ Custom / Experimental";
    const optCustom = document.createElement("option");
    optCustom.value = "__custom__";
    optCustom.textContent = "➕ Enter Custom Model ID...";
    groupCustom.appendChild(optCustom);
    this.selectAiModel.appendChild(groupCustom);

    if (!this.selectAiModel.value) {
      if (provider === "gemini_cookie") {
        this.selectAiModel.value = "gemini-pro-advanced";
      } else {
        this.selectAiModel.value = "gemini-2.5-flash";
      }
    }
  }

  async detectGeminiModels(silent = false) {
    const provider = this.selectAiProvider ? this.selectAiProvider.value : "gemini";
    let apiKey = this.inputProviderKey ? this.inputProviderKey.value.trim() : "";
    let cookieVal = localStorage.getItem("anistory_key_gemini_cookie") || localStorage.getItem("anistory_gemini_cookie_psid") || "";

    if (!apiKey) {
      apiKey = localStorage.getItem("anistory_key_gemini") || localStorage.getItem("anistory_gemini_key") || "";
    }

    if (this.btnDetectModels) {
      this.btnDetectModels.disabled = true;
      this.btnDetectModels.innerHTML = `<span>⏳ Detecting...</span>`;
    }

    try {
      const resp = await fetch("/api/gemini/detect-models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey, cookie: cookieVal, provider: provider })
      });
      const data = await resp.json();
      if (data && data.status === "ok") {
        this.detectedModelsData = data;
        this.renderModelDropdown(data);
        this.renderModelCards();

        if (this.modelExplorerStatusText && this.modelExplorerStatusBadge) {
          if (data.has_live_api) {
            this.modelExplorerStatusText.textContent = `✅ Live connected to Google AI Studio (${data.total_api} API models detected)`;
            this.modelExplorerStatusBadge.textContent = "API Live";
            this.modelExplorerStatusBadge.style.background = "rgba(16, 185, 129, 0.2)";
            this.modelExplorerStatusBadge.style.color = "#34d399";
          } else if (data.has_cookie) {
            this.modelExplorerStatusText.textContent = `🍪 Connected via Web Cookies (${data.total_cookie} Cookie models available)`;
            this.modelExplorerStatusBadge.textContent = "Cookies Ready";
            this.modelExplorerStatusBadge.style.background = "rgba(245, 158, 11, 0.2)";
            this.modelExplorerStatusBadge.style.color = "#fbbf24";
          } else {
            this.modelExplorerStatusText.textContent = `💡 Curated models loaded. Enter an API key or cookie to query live accounts.`;
            this.modelExplorerStatusBadge.textContent = "Curated";
          }
        }

        localStorage.setItem("anistory_gemini_detected_payload", JSON.stringify(data));
        if (!silent) {
          const total = (data.api_models?.length || 0) + (data.cookie_models?.length || 0);
          this.showToast(`Found ${total} available models (API & Cookies)! ✨`);
        }
      }
    } catch (e) {
      console.error("Model detection error:", e);
      if (!silent) this.showToast("Failed to query live models, using curated list.", true);
    } finally {
      if (this.btnDetectModels) {
        this.btnDetectModels.disabled = false;
        this.btnDetectModels.innerHTML = `<span>🔄 Detect & Select</span>`;
      }
    }
  }

  setupAiProviders(providers) {
    if (!providers || !this.selectAiProvider) return;

    const savedProvider = localStorage.getItem("anistory_cfg_provider");
    if (savedProvider) {
      for (let i = 0; i < this.selectAiProvider.options.length; i++) {
        if (this.selectAiProvider.options[i].value === savedProvider) {
          this.selectAiProvider.selectedIndex = i;
          break;
        }
      }
    }

    const updateModelsAndKey = () => {
      const pKey = this.selectAiProvider.value;
      const isGeminiFamily = pKey === "gemini" || pKey === "gemini_cookie";

      if (this.btnDetectModels) {
        this.btnDetectModels.style.display = isGeminiFamily ? "inline-flex" : "none";
      }

      if (pKey === "builtin") {
        if (this.groupProviderKey) this.groupProviderKey.style.display = "none";
        if (this.selectAiModel) {
          this.selectAiModel.innerHTML = "<option value='story_architect'>Genre-Aware Story Architect (Offline/Free)</option>";
        }
        return;
      }

      if (this.groupProviderKey) this.groupProviderKey.style.display = "block";

      if (isGeminiFamily) {
        if (this.labelProviderKey && this.badgeProviderHint) {
          if (pKey === "gemini_cookie") {
            this.labelProviderKey.textContent = "Gemini Cookie";
            this.badgeProviderHint.textContent = "🍪 Pro Account Session";
          } else {
            this.labelProviderKey.textContent = "Gemini API Key";
            this.badgeProviderHint.textContent = "🔑 AIzaSy...";
          }
        }

        // Load cached detected data if present
        let cachedData = this.detectedModelsData;
        if (!cachedData) {
          try {
            const raw = localStorage.getItem("anistory_gemini_detected_payload");
            if (raw) cachedData = JSON.parse(raw);
          } catch (e) {}
        }
        const savedModel = localStorage.getItem("anistory_cfg_model") || localStorage.getItem("anistory_model_gemini");
        this.renderModelDropdown(cachedData, savedModel);
      } else {
        if (this.labelProviderKey && this.badgeProviderHint) {
          this.labelProviderKey.textContent = "API Key";
          this.badgeProviderHint.textContent = "";
        }
        const pInfo = providers[pKey];
        if (pInfo && this.selectAiModel) {
          this.selectAiModel.innerHTML = "";
          const savedModel = localStorage.getItem(`anistory_model_${pKey}`) || localStorage.getItem("anistory_cfg_model");
          pInfo.models.forEach(m => {
            const opt = document.createElement("option");
            opt.value = m;
            opt.textContent = m;
            if (savedModel ? (m === savedModel) : (m === pInfo.default_model)) {
              opt.selected = true;
            }
            this.selectAiModel.appendChild(opt);
          });
        }
      }

      const pInfo = providers[pKey];
      if (this.inputProviderKey) {
        if (pKey === "gemini_cookie") {
          this.inputProviderKey.placeholder = "Paste __Secure-1PSID or full Cookie string...";
          this.inputProviderKey.value = localStorage.getItem("anistory_key_gemini_cookie") || localStorage.getItem("anistory_gemini_cookie_psid") || "";
        } else {
          this.inputProviderKey.placeholder = pInfo?.placeholder || "Enter API Key...";
          this.inputProviderKey.value = localStorage.getItem(`anistory_key_${pKey}`) || (pKey === "gemini" ? (localStorage.getItem("anistory_gemini_key") || "") : "");
        }
      }
    };

    this.selectAiProvider.addEventListener("change", () => {
      localStorage.setItem("anistory_cfg_provider", this.selectAiProvider.value);
      updateModelsAndKey();
      const pKey = this.selectAiProvider.value;
      if (pKey === "gemini" || pKey === "gemini_cookie") {
        this.detectGeminiModels(true);
      }
    });

    if (this.selectAiModel) {
      this.selectAiModel.addEventListener("change", () => {
        const val = this.selectAiModel.value;
        const curProvider = this.selectAiProvider ? this.selectAiProvider.value : "gemini";
        if (val === "__custom__") {
          const customName = prompt("Enter custom Gemini model ID (e.g. gemini-2.0-flash-thinking-exp):");
          if (customName && customName.trim()) {
            const trimmed = customName.trim();
            const opt = document.createElement("option");
            opt.value = trimmed;
            opt.textContent = `${trimmed} [Custom]`;
            opt.selected = true;
            this.selectAiModel.appendChild(opt);
            localStorage.setItem("anistory_model_gemini", trimmed);
            localStorage.setItem("anistory_cfg_model", trimmed);
            this.showToast(`Custom model set to: ${trimmed} 🎯`);
          } else {
            this.selectAiModel.value = "gemini-2.5-flash";
          }
        } else {
          // If a cookie model was chosen under gemini API provider, prompt or auto-switch
          if (val.includes("advanced") || val === "default") {
            if (this.selectAiProvider && this.selectAiProvider.value === "gemini") {
              const hasCookie = localStorage.getItem("anistory_key_gemini_cookie");
              if (hasCookie) {
                this.selectAiProvider.value = "gemini_cookie";
                localStorage.setItem("anistory_cfg_provider", "gemini_cookie");
                updateModelsAndKey();
                this.selectAiModel.value = val;
                this.showToast("Switched to Gemini Web Cookies session for this model 🍪");
              }
            }
          }
          localStorage.setItem("anistory_cfg_model", val);
          localStorage.setItem(`anistory_model_${curProvider}`, val);
          if (curProvider === "gemini" || curProvider === "gemini_cookie") {
            localStorage.setItem("anistory_model_gemini", val);
          }
        }
      });
    }

    if (this.inputProviderKey) {
      this.inputProviderKey.addEventListener("input", () => {
        const pKey = this.selectAiProvider.value;
        const val = this.inputProviderKey.value.trim();
        localStorage.setItem(`anistory_key_${pKey}`, val);
        if (pKey === "gemini") localStorage.setItem("anistory_gemini_key", val);
        if (pKey === "gemini_cookie") {
          if (val.includes("|") || val.includes("__Secure-1PSIDTS") || val.startsWith("{")) {
            localStorage.setItem("anistory_key_gemini_cookie", val);
          } else {
            const savedTs = localStorage.getItem("anistory_gemini_cookie_psidts") || "";
            const combined = savedTs ? `${val}|${savedTs}` : val;
            localStorage.setItem("anistory_key_gemini_cookie", combined);
          }
          localStorage.setItem("anistory_gemini_cookie_psid", val.split("|")[0].trim());
        }
      });
    }

    updateModelsAndKey();
    if (this.selectAiProvider.value === "gemini" || this.selectAiProvider.value === "gemini_cookie") {
      this.detectGeminiModels(true);
    }
  }

  renderStyles(styles) {
    this.styleOptionsGrid.innerHTML = "";
    const savedStyle = localStorage.getItem("anistory_cfg_art_style") || this.selectedStyleKey || "ghibli";
    this.selectedStyleKey = savedStyle;
    Object.entries(styles).forEach(([key, info]) => {
      const card = document.createElement("div");
      card.className = "style-card-item" + (key === this.selectedStyleKey ? " selected" : "");
      card.innerHTML = `
        <div class="style-card-header">
          <span class="style-card-icon">${info.icon || "🎨"}</span>
          <span class="style-card-name">${info.name}</span>
        </div>
        <div class="style-card-desc">${info.description}</div>
      `;
      card.addEventListener("click", () => {
        document.querySelectorAll(".style-card-item").forEach(c => c.classList.remove("selected"));
        card.classList.add("selected");
        this.selectedStyleKey = key;
        localStorage.setItem("anistory_cfg_art_style", key);
      });
      this.styleOptionsGrid.appendChild(card);
    });
  }

  renderVoices(voices) {
    this.selectVoice.innerHTML = "";
    const savedVoice = localStorage.getItem("anistory_cfg_voice");
    voices.forEach(v => {
      const opt = document.createElement("option");
      opt.value = v.id;
      opt.textContent = `${v.name} (${v.gender})`;
      if (savedVoice ? (v.id === savedVoice) : (v.id === "gemini-Aoede" || v.id === "en-US-ChristopherNeural")) {
        opt.selected = true;
      }
      this.selectVoice.appendChild(opt);
    });
  }

  switchStage(stageNum, pushState = true) {
    this.stages.forEach((panel, i) => {
      panel.classList.toggle("active", i === stageNum - 1);
    });
    this.tabs.forEach((tab, i) => {
      tab.classList.toggle("active", i === stageNum - 1);
      tab.classList.toggle("completed", i < stageNum - 1);
    });
    localStorage.setItem("anistory_active_stage", String(stageNum));
    if (pushState && window.history && typeof window.history.pushState === "function") {
      try {
        window.history.pushState({ stage: stageNum }, "", `#stage${stageNum}`);
      } catch (e) {
        // ignore state serialization errors
      }
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  showToast(message, isError = false) {
    this.toastNotification.textContent = message;
    this.toastNotification.style.borderColor = isError ? "#ef4444" : "var(--primary)";
    this.toastNotification.classList.add("show");
    setTimeout(() => {
      this.toastNotification.classList.remove("show");
    }, 3200);
  }

  getEffectiveApiKey(provider) {
    if (provider === "gemini_cookie") {
      const psid = localStorage.getItem("anistory_gemini_cookie_psid") || "";
      const psidts = localStorage.getItem("anistory_gemini_cookie_psidts") || "";
      const combined = localStorage.getItem("anistory_key_gemini_cookie") || "";
      
      const inputVal = this.inputProviderKey ? this.inputProviderKey.value.trim() : "";
      if (inputVal) {
        if (inputVal.includes("|") || inputVal.includes("__Secure-1PSIDTS") || inputVal.startsWith("{")) {
          return inputVal;
        }
        if (psidts) {
          return `${inputVal}|${psidts}`;
        }
        return inputVal;
      }

      if (combined && (combined.includes("|") || combined.includes("__Secure-1PSIDTS") || combined.startsWith("{"))) {
        return combined;
      }
      if (psid && psidts) {
        return `${psid}|${psidts}`;
      }
      return combined || psid;
    }
    const inputVal = this.inputProviderKey ? this.inputProviderKey.value.trim() : "";
    if (inputVal) return inputVal;
    if (provider === "gemini") {
      return localStorage.getItem("anistory_key_gemini") || localStorage.getItem("anistory_gemini_key") || "";
    }
    return localStorage.getItem(`anistory_key_${provider}`) || "";
  }

  async handleGenerateStoryboard() {
    const idea = this.inputIdeaPrompt.value.trim();
    if (!idea) {
      this.showToast("Please enter a story idea or choose a quick spark! 💡", true);
      this.inputIdeaPrompt.focus();
      return;
    }

    this.btnGenerateStoryboard.disabled = true;
    this.btnGenerateStoryboard.innerHTML = `
      <span class="btn-text">Brainstorming Storyboard...</span>
      <span class="btn-arrow">⏳</span>
    `;

    try {
      const provider = this.selectAiProvider ? this.selectAiProvider.value : "gemini";
      const model = this.selectAiModel ? this.selectAiModel.value : "";
      let apiKey = this.getEffectiveApiKey(provider);

      if (provider === "gemini_cookie" && !apiKey) {
        this.showToast("Please paste your Gemini __Secure-1PSID cookie in Settings ⚙️ first! 🍪", true);
        this.btnGenerateStoryboard.disabled = false;
        this.btnGenerateStoryboard.innerHTML = `<span class="btn-text">Generate Storyboard</span><span class="btn-arrow">✨</span>`;
        return;
      }
      const numScenes = parseInt(this.selectSceneCount.value, 10);
      const targetDuration = this.selectTargetDuration ? parseInt(this.selectTargetDuration.value, 10) : (numScenes * 15);
      const aspectRatio = this.selectAspectRatio ? this.selectAspectRatio.value : "16:9";
      const projectTitle = this.inputProjectTitle ? this.inputProjectTitle.value.trim() : "";

      // Persist active configuration choices
      localStorage.setItem("anistory_cfg_art_style", this.selectedStyleKey);
      if (this.selectVoice) localStorage.setItem("anistory_cfg_voice", this.selectVoice.value);
      if (this.selectSceneCount) localStorage.setItem("anistory_cfg_scene_count", this.selectSceneCount.value);
      if (this.selectAspectRatio) localStorage.setItem("anistory_cfg_aspect_ratio", this.selectAspectRatio.value);
      if (this.selectLanguage) localStorage.setItem("anistory_cfg_language", this.selectLanguage.value);
      if (this.selectAudience) localStorage.setItem("anistory_cfg_audience", this.selectAudience.value);
      if (this.selectAiProvider) localStorage.setItem("anistory_cfg_provider", provider);
      if (model) localStorage.setItem("anistory_cfg_model", model);

      const payload = {
        title: projectTitle,
        idea: idea,
        art_style: this.selectedStyleKey,
        voice: this.selectVoice.value,
        num_scenes: numScenes,
        target_duration: targetDuration,
        aspect_ratio: aspectRatio,
        language: this.selectLanguage.value,
        audience: this.selectAudience.value,
        ai_provider: provider,
        ai_model: model,
        api_key: apiKey,
        image_mode: this.imageMode || "server"
      };

      const resp = await fetch("/api/create-story", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!resp.ok) {
        let msg = "Failed to create story";
        try {
          const err = await resp.json();
          msg = err.detail || msg;
        } catch {
          const raw = await resp.text();
          if (raw) msg = raw.slice(0, 200);
        }
        throw new Error(msg);
      }

      this.currentProject = await resp.json();
      this.saveActiveProjectState();
      this.renderStoryboardView();
      this.switchStage(2);
      const titleDisplay = this.currentProject.title ? `"${this.currentProject.title}"` : `${this.currentProject.scenes.length} scenes`;
      this.showToast(`✨ Generated ${titleDisplay} (${this.currentProject.scenes.length} scenes) with ${provider.toUpperCase()}!`);
      // Display and generate scene artwork immediately after response
      this.autoGenerateMissingSceneImages();
    } catch (e) {
      console.error(e);
      this.showToast(e.message, true);
    } finally {
      this.btnGenerateStoryboard.disabled = false;
      this.btnGenerateStoryboard.innerHTML = `
        <span class="btn-glow-layer"></span>
        <span class="btn-text">Generate Storyboard with AI</span>
        <span class="btn-arrow">✨</span>
      `;
    }
  }

  async handleImportStory() {
    const text = this.inputImportText?.value?.trim();
    if (!text) {
      this.showToast("Please paste your Gemini storyboard text first! 📋", true);
      this.inputImportText?.focus();
      return;
    }
    await this.handleImportFromText(text, this.btnSubmitImport);
  }

  async handleImportFromText(text, btnEl) {
    if (btnEl) {
      btnEl.disabled = true;
      btnEl.innerHTML = `<span>Loading Scenes...</span> <span>⏳</span>`;
    }

    try {
      const apiKey = localStorage.getItem("anistory_gemini_key") || null;
      const aspectRatio = this.selectAspectRatio ? this.selectAspectRatio.value : "16:9";
      const projectTitle = this.inputProjectTitle ? this.inputProjectTitle.value.trim() : "";
      const resp = await fetch("/api/import-story", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: projectTitle,
          text: text,
          art_style: this.selectedStyleKey,
          voice: this.selectVoice.value,
          aspect_ratio: aspectRatio,
          api_key: apiKey,
          image_mode: this.imageMode || "server"
        })
      });

      if (!resp.ok) {
        let msg = "Failed to parse storyboard";
        try {
          const err = await resp.json();
          msg = err.detail || msg;
        } catch {
          const raw = await resp.text();
          if (raw) msg = raw.slice(0, 200);
        }
        throw new Error(msg);
      }

      this.currentProject = await resp.json();
      this.saveActiveProjectState();
      if (this.modalImport) this.modalImport.classList.remove("active");
      if (this.inputImportText) this.inputImportText.value = "";
      if (this.inputDirectPasteText) this.inputDirectPasteText.value = "";
      this.renderStoryboardView();
      this.switchStage(2);
      this.showToast("AI Storyboard loaded! Review your scenes and render. 🎬");
      // Display and generate scene artwork immediately after response
      this.autoGenerateMissingSceneImages();
    } catch (e) {
      console.error(e);
      this.showToast(e.message, true);
    } finally {
      if (btnEl) {
        btnEl.disabled = false;
        btnEl.innerHTML = `<span class="btn-glow-layer"></span><span class="btn-text">Load Into Director's Board</span><span class="btn-arrow">🚀</span>`;
      }
    }
  }

  getInstantPreviewUrl(scene, idx) {
    const artStyle = this.currentProject?.art_style || this.selectedStyleKey || "ghibli";
    const styleInfo = this.config?.art_styles?.[artStyle] || {};
    const suffix = styleInfo.prompt_suffix || ", anime illustration";
    const basePrompt = (scene?.visual_prompt || scene?.title || "cinematic animated short film scene").trim();
    const cleanPrompt = basePrompt.replace(/[\n\r]/g, " ").slice(0, 320);
    const fullPrompt = `${cleanPrompt}${suffix}`;
    const encoded = encodeURIComponent(fullPrompt.slice(0, 350));

    const ar = this.currentProject?.aspect_ratio || "16:9";
    const dim = this.config?.video_dimensions?.[ar] || { width: 1280, height: 720 };
    const w = dim.width || 1280;
    const h = dim.height || 720;
    const projSeed = this.currentProject?.id ? (this.currentProject.id.charCodeAt(0) * 100) : 500;
    const seed = Math.abs((scene?.scene_number || idx + 1) * 31415 + projSeed);

    return `https://image.pollinations.ai/prompt/${encoded}?width=${w}&height=${h}&seed=${seed}&nologo=true`;
  }

  renderStoryboardView() {
    if (!this.currentProject) return;

    this.storyboardFilmTitle.textContent = this.currentProject.title || "Animated Short Film";
    this.storyboardLogline.textContent = this.currentProject.logline || "";
    if (this.inputCharacterConsistency) {
      this.inputCharacterConsistency.value = this.currentProject.characters || "";
    }
    this.storyboardScenesGrid.innerHTML = "";

    // Set aspect ratio CSS variable on the scenes grid
    const ar = this.currentProject.aspect_ratio || "16:9";
    const dim = this.config?.video_dimensions?.[ar] || {
      name: `${ar} Format`,
      ratio_css: ar.replace(":", " / "),
      width: this.currentProject.video_width || 1280,
      height: this.currentProject.video_height || 720
    };
    const ratioCss = dim.ratio_css || ar.replace(":", " / ");
    this.storyboardScenesGrid.style.setProperty("--project-aspect-ratio", ratioCss);

    if (this.badgeStoryboardAspectRatio) {
      const w = dim.width || this.currentProject.video_width || 1280;
      const h = dim.height || this.currentProject.video_height || 720;
      this.badgeStoryboardAspectRatio.textContent = `📐 ${ar} (${w}x${h})`;
    }

    this.updateSubtitlesUI(this.currentProject.enable_subtitles !== false);

    const scenes = this.currentProject.scenes || [];
    scenes.forEach((scene, idx) => {
      const card = document.createElement("div");
      card.className = "scene-card";
      card.dataset.index = idx;

      // Image & Video source
      const hasSavedImage = Boolean(scene.image_path);
      const instantSrc = this.getInstantPreviewUrl(scene, idx);
      const imgSrc = hasSavedImage ? `/media/${scene.image_path}?t=${Date.now()}` : instantSrc;
      const hasVideo = Boolean(scene.video_path);
      const videoSrc = hasVideo ? `/media/${scene.video_path}?t=${Date.now()}` : "";

      card.innerHTML = `
        <div class="scene-card-header">
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
            <span class="scene-badge">Scene ${scene.scene_number || idx + 1}</span>
            <span class="scene-status-pill ${hasSavedImage ? 'ready' : 'pending'}" id="sceneStatusPill_${idx}">
              ${hasSavedImage ? '✓ Ready' : '🎨 AI Painting...'}
            </span>
            <span class="scene-status-pill ready" id="sceneVideoPill_${idx}" style="${hasVideo ? '' : 'display:none;'}">
              🎬 Video Ready
            </span>
          </div>
          <span class="scene-card-title">${scene.title || "Scene " + (idx + 1)}</span>
        </div>
        <div class="scene-preview-container">
          <img src="${imgSrc}" class="scene-preview-img" alt="Scene ${idx + 1} Preview" id="sceneImg_${idx}" loading="lazy">
          <video class="scene-preview-video" id="sceneVideo_${idx}" src="${videoSrc}" controls playsinline preload="metadata" style="display:none;"></video>
          <button class="scene-play-overlay-btn" id="btnPlayOverlay_${idx}" data-idx="${idx}" title="Play scene animation video" style="${hasVideo ? 'display:flex;' : 'display:none;'}">▶️</button>
          <div class="scene-img-actions">
            <button class="scene-action-pill btn-reroll-img" data-idx="${idx}">🎨 AI Paint</button>
            <button class="scene-action-pill btn-upload-img" data-idx="${idx}">📁 Image</button>
            <button class="scene-action-pill btn-generate-veo" data-idx="${idx}" style="color:#6ee7b7; border-color:rgba(16,185,129,0.4);" title="Auto-render acting video via Google Veo & FlowKit bridge">⚡ Veo Auto</button>
            <button class="scene-action-pill btn-upload-acting" data-idx="${idx}" style="color:#93c5fd; border-color:rgba(59,130,246,0.4);" title="Upload acting video clip from Google Flow (Veo)">✨ Flow Video</button>
            <button class="scene-action-pill ${hasVideo ? 'video-ready' : ''} btn-toggle-video" id="btnToggleVideo_${idx}" data-idx="${idx}" style="${hasVideo ? '' : 'display:none;'}">▶️ Play Clip</button>
            <a class="scene-action-pill btn-download-scene-clip" id="btnDownloadClip_${idx}" href="/api/projects/${this.currentProject.id}/download-scene-video/${idx}" download title="Download Scene MP4" style="${hasVideo ? '' : 'display:none;'}">⬇️ MP4</a>
            <input type="file" accept="image/*" class="scene-file-input" style="display:none;" id="fileInput_${idx}">
            <input type="file" accept="video/mp4,video/*" class="scene-acting-file-input" style="display:none;" id="actingFileInput_${idx}">
          </div>
        </div>
        <div class="scene-card-body">
          <div>
            <label class="field-label">🎙️ Voiceover Narration</label>
            <textarea class="scene-narration-input" id="narration_${idx}">${scene.narration || ""}</textarea>
          </div>
          <div>
            <label class="field-label">🖼️ Visual Description (AI Prompt)</label>
            <input type="text" class="styled-input" id="prompt_${idx}" value="${scene.visual_prompt || ""}">
          </div>
          <div class="scene-controls-row">
            <select class="styled-select camera-motion-select" id="motion_${idx}">
              <option value="zoom_in" ${scene.camera_motion === "zoom_in" ? "selected" : ""}>🔍 Camera Zoom In</option>
              <option value="zoom_out" ${scene.camera_motion === "zoom_out" ? "selected" : ""}>🔭 Camera Zoom Out</option>
              <option value="pan_left" ${scene.camera_motion === "pan_left" ? "selected" : ""}>⬅️ Pan Left</option>
              <option value="pan_right" ${scene.camera_motion === "pan_right" ? "selected" : ""}>➡️ Pan Right</option>
              <option value="subtle_drift" ${scene.camera_motion === "subtle_drift" ? "selected" : ""}>✨ Subtle Drift</option>
            </select>
            <button class="btn-animate-scene" id="btnAnimateScene_${idx}" data-idx="${idx}" title="Render animation video clip for this scene">
              🎬 ${hasVideo ? 'Re-animate' : 'Animate Scene'}
            </button>
          </div>
        </div>
      `;

      // Event listener for re-rolling scene image
      const btnReroll = card.querySelector(".btn-reroll-img");
      btnReroll.addEventListener("click", () => this.rerollSceneImage(idx, btnReroll));

      // Event listener for Veo Auto generation via FlowKit
      const btnVeo = card.querySelector(".btn-generate-veo");
      if (btnVeo) {
        btnVeo.addEventListener("click", () => this.generateVeoSceneVideo(idx, btnVeo));
      }

      // Event listener for uploading custom scene image
      const btnUpload = card.querySelector(".btn-upload-img");
      const fileInput = card.querySelector(".scene-file-input");
      btnUpload.addEventListener("click", () => fileInput.click());
      fileInput.addEventListener("change", async (e) => {
        if (e.target.files && e.target.files[0]) {
          await this.uploadCustomSceneImage(idx, e.target.files[0]);
        }
      });

      // Event listener for uploading custom acting video (from Google Flow)
      const btnUploadActing = card.querySelector(".btn-upload-acting");
      const actingFileInput = card.querySelector(".scene-acting-file-input");
      if (btnUploadActing && actingFileInput) {
        btnUploadActing.addEventListener("click", () => actingFileInput.click());
        actingFileInput.addEventListener("change", async (e) => {
          if (e.target.files && e.target.files[0]) {
            await this.uploadCustomActingVideo(idx, e.target.files[0]);
          }
        });
      }

      // Event listener for animating single scene video
      const btnAnimate = card.querySelector(`#btnAnimateScene_${idx}`);
      if (btnAnimate) {
        btnAnimate.addEventListener("click", () => this.animateSingleSceneVideo(idx, btnAnimate));
      }

      // Event listeners for opening video modal player
      const btnOverlay = card.querySelector(`#btnPlayOverlay_${idx}`);
      if (btnOverlay) {
        btnOverlay.addEventListener("click", () => this.openSceneVideoModal(idx));
      }
      const btnToggleVideo = card.querySelector(`#btnToggleVideo_${idx}`);
      if (btnToggleVideo) {
        btnToggleVideo.addEventListener("click", () => this.openSceneVideoModal(idx));
      }

      this.storyboardScenesGrid.appendChild(card);
    });
  }

  async autoGenerateMissingSceneImages() {
    await this.paintAllSceneImages(false);
  }

  async paintAllSceneImages(forceAll = false) {
    if (!this.currentProject || !this.currentProject.scenes) return;
    const projectId = this.currentProject.id;
    const scenesToPaint = [];

    this.currentProject.scenes.forEach((scene, idx) => {
      if (forceAll || !scene.image_path) {
        scenesToPaint.push(idx);
      }
    });

    if (scenesToPaint.length === 0) {
      if (forceAll) this.showToast("All scenes already have illustrations! ✨");
      return;
    }

    if (this.btnPaintAllImages) {
      this.btnPaintAllImages.disabled = true;
      this.btnPaintAllImages.textContent = "Painting 1-by-1... ⏳";
    }

    this.showToast(`Painting ${scenesToPaint.length} scene(s) one by one with character consistency... 🎨`);

    // Strictly generate images ONE BY ONE to preserve character consistency & prevent API clashes
    for (let i = 0; i < scenesToPaint.length; i++) {
      const sceneIdx = scenesToPaint[i];
      if (!this.currentProject || this.currentProject.id !== projectId) break;

      const btn = document.querySelector(`.btn-reroll-img[data-idx="${sceneIdx}"]`);
      const statusPill = document.getElementById(`sceneStatusPill_${sceneIdx}`);
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Painting... ⏳";
      }
      if (statusPill) {
        statusPill.className = "scene-status-pill pending";
        statusPill.textContent = `🎨 Painting ${i + 1}/${scenesToPaint.length}...`;
      }

      try {
        const curProvider = this.currentProject?.ai_provider || this.selectAiProvider?.value || "gemini";
        const curKey = this.getEffectiveApiKey(curProvider);
        const resp = await fetch(`/api/projects/${projectId}/regenerate-image/${sceneIdx}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ api_key: curKey, ai_provider: curProvider })
        });

        if (resp.ok) {
          const updatedProject = await resp.json();
          if (this.currentProject && this.currentProject.id === projectId) {
            if (updatedProject.scenes && updatedProject.scenes[sceneIdx]) {
              this.currentProject.scenes[sceneIdx] = updatedProject.scenes[sceneIdx];
            }
            const updatedScene = this.currentProject.scenes[sceneIdx];
            const imgEl = document.getElementById(`sceneImg_${sceneIdx}`);
            if (imgEl && updatedScene && updatedScene.image_path) {
              imgEl.src = `/media/${updatedScene.image_path}?t=${Date.now()}`;
            }
            if (statusPill) {
              statusPill.className = "scene-status-pill ready";
              statusPill.textContent = "✓ Ready";
            }
          }
        } else {
          let errDetail = "Generation error";
          try {
            const errJson = await resp.json();
            errDetail = errJson.detail || errDetail;
          } catch {}
          if (statusPill) {
            statusPill.className = "scene-status-pill error";
            statusPill.textContent = "⚠️ Error";
          }
          console.warn(`Scene ${sceneIdx + 1} paint issue:`, errDetail);
        }
      } catch (err) {
        console.warn(`Sequential paint scene ${sceneIdx + 1} error:`, err);
        if (statusPill) {
          statusPill.className = "scene-status-pill error";
          statusPill.textContent = "⚠️ Error";
        }
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = "🎨 AI Paint";
        }
      }

      // Pacing delay between sequential scenes for smooth visual updates and socket stability
      if (i < scenesToPaint.length - 1) {
        await new Promise(r => setTimeout(r, 600));
      }
    }

    if (this.btnPaintAllImages) {
      this.btnPaintAllImages.disabled = false;
      this.btnPaintAllImages.textContent = "🎨 Paint All (1-by-1)";
    }
    this.showToast("Sequential scene painting completed with consistent characters! 🎬✨");
  }

  async animateSingleSceneVideo(sceneIdx, buttonEl) {
    if (!this.currentProject) return;
    const projectId = this.currentProject.id;
    const scene = this.currentProject.scenes?.[sceneIdx];
    if (!scene) return;

    // Save pending edits (narration, prompt, camera motion) first
    await this.saveStoryboardEdits(false);

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.textContent = "Animating... ⏳";
    }

    const videoPill = document.getElementById(`sceneVideoPill_${sceneIdx}`);
    if (videoPill) {
      videoPill.style.display = "";
      videoPill.className = "scene-status-pill pending";
      videoPill.textContent = "🎬 Rendering video...";
    }

    this.showToast(`Rendering animated video for Scene ${sceneIdx + 1}... 🎬`);

    try {
      const curProvider = this.currentProject?.ai_provider || this.selectAiProvider?.value || "gemini";
      const curKey = this.getEffectiveApiKey(curProvider);

      const resp = await fetch(`/api/projects/${projectId}/render-scene-video/${sceneIdx}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          api_key: curKey,
          ai_provider: curProvider,
          force_revoice: false,
          force_repaint: false
        })
      });

      if (resp.ok) {
        const resData = await resp.json();
        const updatedProject = resData.project || this.currentProject;
        if (this.currentProject && this.currentProject.id === projectId) {
          if (updatedProject.scenes?.[sceneIdx]) {
            this.currentProject.scenes[sceneIdx] = updatedProject.scenes[sceneIdx];
          }
          const upScene = this.currentProject.scenes[sceneIdx];

          // Update image if refreshed
          const imgEl = document.getElementById(`sceneImg_${sceneIdx}`);
          if (imgEl && upScene.image_path) {
            imgEl.src = `/media/${upScene.image_path}?t=${Date.now()}`;
          }

          // Update video pill
          if (videoPill) {
            videoPill.className = "scene-status-pill ready";
            videoPill.textContent = "🎬 Video Ready";
          }

          // Update video player
          const vidEl = document.getElementById(`sceneVideo_${sceneIdx}`);
          if (vidEl && upScene.video_path) {
            vidEl.src = `/media/${upScene.video_path}?t=${Date.now()}`;
          }

          // Show overlay and action buttons
          const overlayBtn = document.getElementById(`btnPlayOverlay_${sceneIdx}`);
          if (overlayBtn) overlayBtn.style.display = "flex";

          const toggleBtn = document.getElementById(`btnToggleVideo_${sceneIdx}`);
          if (toggleBtn) {
            toggleBtn.style.display = "";
            toggleBtn.className = "scene-action-pill video-ready btn-toggle-video";
          }

          const dlBtn = document.getElementById(`btnDownloadClip_${sceneIdx}`);
          if (dlBtn && upScene.video_path) {
            dlBtn.style.display = "";
            dlBtn.href = `/api/projects/${projectId}/download-scene-video/${sceneIdx}`;
          }

          this.saveActiveProjectState();
          this.showToast(`Scene ${sceneIdx + 1} animation video ready! 🎬✨`);
        }
      } else {
        let errDetail = "Render error";
        try {
          const errJson = await resp.json();
          errDetail = errJson.detail || errDetail;
        } catch {}
        if (videoPill) {
          videoPill.className = "scene-status-pill error";
          videoPill.textContent = "⚠️ Render Error";
        }
        this.showToast(`Failed to render Scene ${sceneIdx + 1}: ${errDetail}`, true);
      }
    } catch (err) {
      console.error(`Error rendering scene ${sceneIdx + 1} video:`, err);
      if (videoPill) {
        videoPill.className = "scene-status-pill error";
        videoPill.textContent = "⚠️ Error";
      }
      this.showToast(`Render failed: ${err.message}`, true);
    } finally {
      if (buttonEl) {
        buttonEl.disabled = false;
        buttonEl.textContent = "🎬 Re-animate";
      }
    }
  }

  async animateAllSceneVideos() {
    if (!this.currentProject || !this.currentProject.scenes) return;
    const projectId = this.currentProject.id;
    const totalScenes = this.currentProject.scenes.length;
    if (totalScenes === 0) return;

    await this.saveStoryboardEdits(false);

    if (this.btnAnimateAllScenes) {
      this.btnAnimateAllScenes.disabled = true;
      this.btnAnimateAllScenes.textContent = "Animating 1-by-1... ⏳";
    }

    this.showToast(`Creating animation videos for all ${totalScenes} scenes sequentially... 🎬✨`);

    for (let idx = 0; idx < totalScenes; idx++) {
      if (!this.currentProject || this.currentProject.id !== projectId) break;

      if (this.btnAnimateAllScenes) {
        this.btnAnimateAllScenes.textContent = `🎬 Animating ${idx + 1}/${totalScenes}... ⏳`;
      }

      const sceneBtn = document.getElementById(`btnAnimateScene_${idx}`);
      await this.animateSingleSceneVideo(idx, sceneBtn);

      if (idx < totalScenes - 1) {
        await new Promise(r => setTimeout(r, 600));
      }
    }

    if (this.btnAnimateAllScenes) {
      this.btnAnimateAllScenes.disabled = false;
      this.btnAnimateAllScenes.textContent = "🎬 Animate All Scenes";
    }
    this.showToast("All scene animation videos successfully created! 🎬🚀");
  }

  openSceneVideoModal(sceneIdx) {
    if (!this.currentProject || !this.modalSceneVideo) return;
    const scene = this.currentProject.scenes?.[sceneIdx];
    if (!scene || !scene.video_path) {
      this.showToast("Video clip has not been rendered yet. Click 'Animate Scene' first! 🎬", true);
      return;
    }

    const videoUrl = `/media/${scene.video_path}?t=${Date.now()}`;
    if (this.modalSceneVideoTitle) {
      this.modalSceneVideoTitle.textContent = `🎬 Scene ${scene.scene_number || sceneIdx + 1}: ${scene.title || 'Animation Clip'}`;
    }
    if (this.modalSceneVideoMeta) {
      const motionName = (scene.camera_motion || "zoom_in").replace("_", " ").toUpperCase();
      const dur = scene.duration ? `${scene.duration.toFixed(1)}s` : "Dynamic";
      this.modalSceneVideoMeta.textContent = `Motion: ${motionName} • Duration: ${dur} • Burnt Captions: ${this.currentProject.enable_subtitles !== false ? 'ON' : 'OFF'}`;
    }
    if (this.modalSceneVideoDownloadBtn) {
      this.modalSceneVideoDownloadBtn.href = `/api/projects/${this.currentProject.id}/download-scene-video/${sceneIdx}`;
    }
    if (this.modalSceneVideoPlayer) {
      this.modalSceneVideoPlayer.src = videoUrl;
      this.modalSceneVideoPlayer.load();
      this.modalSceneVideoPlayer.play().catch(() => {});
    }

    this.modalSceneVideo.classList.add("active");
  }

  closeSceneVideoModal() {
    if (this.modalSceneVideoPlayer) {
      this.modalSceneVideoPlayer.pause();
      this.modalSceneVideoPlayer.removeAttribute("src");
      this.modalSceneVideoPlayer.load();
    }
    if (this.modalSceneVideo) {
      this.modalSceneVideo.classList.remove("active");
    }
  }

  async rerollSceneImage(sceneIdx, buttonEl) {
    if (!this.currentProject) return;
    buttonEl.disabled = true;
    buttonEl.textContent = "Painting... ⏳";

    try {
      // First save any prompt edits
      await this.saveStoryboardEdits(false);

      let painted = false;

      // Only attempt browser Puter.js if imageMode is "puter"
      if (this.imageMode === "puter") {
        if (window.puter && window.puter.ai && typeof window.puter.ai.txt2img === "function") {
          try {
            const scene = this.currentProject.scenes[sceneIdx];
            const imgEl = await window.puter.ai.txt2img(scene.visual_prompt || scene.title);
            if (imgEl && imgEl.src) {
              const bResp = await fetch(imgEl.src);
              const blob = await bResp.blob();
              const formData = new FormData();
              formData.append("file", blob, `scene_${sceneIdx + 1}.jpg`);
              const upResp = await fetch(`/api/projects/${this.currentProject.id}/upload-image/${sceneIdx}`, {
                method: "POST",
                body: formData
              });
              if (upResp.ok) {
                this.currentProject = await upResp.json();
                this.saveActiveProjectState();
                painted = true;
                this.showToast(`Scene ${sceneIdx + 1} painted using In-Browser Puter AI! 🖌️`);
              }
            }
          } catch (pErr) {
            console.warn("Puter browser AI fallback:", pErr);
            this.setImageMode("server");
            this.showToast("Puter credits depleted. Auto-switched to Free Neural AI Engine (Flux)! 🌐", true);
          }
        } else {
          this.setImageMode("server");
          this.showToast("Puter.js not available in browser, generating with Server Neural AI...", false);
        }
      }

      if (!painted) {
        const curProvider = this.currentProject?.ai_provider || this.selectAiProvider?.value || "gemini";
        const curKey = this.getEffectiveApiKey(curProvider);
        const resp = await fetch(`/api/projects/${this.currentProject.id}/regenerate-image/${sceneIdx}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ api_key: curKey, ai_provider: curProvider })
        });
        if (!resp.ok) {
          let errDetail = "Image re-roll failed";
          try {
            const errJson = await resp.json();
            errDetail = errJson.detail || errDetail;
          } catch {}
          throw new Error(errDetail);
        }
        this.currentProject = await resp.json();
        this.saveActiveProjectState();
        const modeLabel = (curProvider === "gemini_cookie" || curProvider === "gemini") ? "Google Imagen 3" : "Free Neural AI";
        this.showToast(`Scene ${sceneIdx + 1} painted with ${modeLabel}! 🎨✨`);
      }

      const updatedScene = this.currentProject.scenes[sceneIdx];
      const imgEl = document.getElementById(`sceneImg_${sceneIdx}`);
      if (imgEl && updatedScene.image_path) {
        // Cache bust
        imgEl.src = `/media/${updatedScene.image_path}?t=${Date.now()}`;
      }
      const statusPill = document.getElementById(`sceneStatusPill_${sceneIdx}`);
      if (statusPill) {
        statusPill.className = "scene-status-pill ready";
        statusPill.textContent = "✓ Ready";
      }
    } catch (e) {
      console.error(e);
      this.showToast(e.message || "Failed to regenerate image", true);
    } finally {
      buttonEl.disabled = false;
      buttonEl.textContent = "🎨 AI Paint";
    }
  }

  async uploadCustomSceneImage(sceneIdx, file) {
    if (!this.currentProject) return;

    const formData = new FormData();
    formData.append("file", file);

    try {
      this.showToast(`Uploading custom art for Scene ${sceneIdx + 1}... ⏳`);
      const resp = await fetch(`/api/projects/${this.currentProject.id}/upload-image/${sceneIdx}`, {
        method: "POST",
        body: formData
      });

      if (!resp.ok) throw new Error("Image upload failed");

      this.currentProject = await resp.json();
      this.saveActiveProjectState();
      const updatedScene = this.currentProject.scenes[sceneIdx];
      const imgEl = document.getElementById(`sceneImg_${sceneIdx}`);
      if (imgEl && updatedScene.image_path) {
        imgEl.src = `/media/${updatedScene.image_path}?t=${Date.now()}`;
      }
      const statusPill = document.getElementById(`sceneStatusPill_${sceneIdx}`);
      if (statusPill) {
        statusPill.className = "scene-status-pill ready";
        statusPill.textContent = "✓ Custom Art";
      }
      this.showToast(`Custom illustration applied to Scene ${sceneIdx + 1}! 🖼️`);
    } catch (e) {
      console.error(e);
      this.showToast("Upload failed: " + e.message, true);
    }
  }

  async openGoogleFlowBrowser() {
    this.showToast("Opening signed-in Google Flow in Chromium... 🎬");
    try {
      const resp = await fetch("/api/flow/open", { method: "POST" });
      const data = await resp.json();
      if (resp.ok) {
        this.showToast("Google Flow opened! Create your Veo clips and download them. 🚀");
      } else {
        this.showToast("Could not launch browser: " + (data.detail || "Error"), true);
      }
    } catch (err) {
      console.error(err);
      this.showToast("Error opening Flow browser: " + err.message, true);
    }
  }

  async uploadCustomActingVideo(sceneIdx, file) {
    if (!this.currentProject) return;

    const formData = new FormData();
    formData.append("file", file);

    try {
      this.showToast(`Importing Flow acting video for Scene ${sceneIdx + 1} & syncing subtitles... ⏳`);
      const resp = await fetch(`/api/projects/${this.currentProject.id}/upload-acting-clip/${sceneIdx}`, {
        method: "POST",
        body: formData
      });

      if (!resp.ok) throw new Error("Acting video upload failed");

      const data = await resp.json();
      this.currentProject = data.project;
      this.saveActiveProjectState();

      // Refresh scene card video
      const videoEl = document.getElementById(`sceneVideo_${sceneIdx}`);
      if (videoEl && data.clip_url) {
        videoEl.src = `${data.clip_url}?t=${Date.now()}`;
      }
      const videoPill = document.getElementById(`sceneVideoPill_${sceneIdx}`);
      if (videoPill) {
        videoPill.style.display = "";
        videoPill.textContent = "🎬 Flow Video Ready";
      }
      const btnOverlay = document.getElementById(`btnPlayOverlay_${sceneIdx}`);
      if (btnOverlay) btnOverlay.style.display = "flex";
      const btnToggle = document.getElementById(`btnToggleVideo_${sceneIdx}`);
      if (btnToggle) {
        btnToggle.style.display = "";
        btnToggle.classList.add("video-ready");
      }
      const btnDownload = document.getElementById(`btnDownloadClip_${sceneIdx}`);
      if (btnDownload) btnDownload.style.display = "";

      this.showToast(`🎉 Scene ${sceneIdx + 1} acting video synced with speech & subtitles!`);
    } catch (e) {
      console.error(e);
      this.showToast("Upload failed: " + e.message, true);
    }
  }

  async generateVeoSceneVideo(sceneIdx, buttonEl) {
    if (!this.currentProject) return;

    buttonEl.disabled = true;
    const oldText = buttonEl.textContent;
    buttonEl.textContent = "⚡ Rendering...";

    try {
      this.showToast(`Submitting Scene ${sceneIdx + 1} to Google Veo via FlowKit... 🎬`);
      const resp = await fetch(`/api/projects/${this.currentProject.id}/generate-flowkit-video/${sceneIdx}`, {
        method: "POST"
      });

      if (!resp.ok) {
        let errMessage = "Veo generation failed";
        try {
          const errData = await resp.json();
          errMessage = errData.detail || errMessage;
        } catch {}
        throw new Error(errMessage);
      }

      const data = await resp.json();
      this.currentProject = data.project;
      this.saveActiveProjectState();

      // Refresh scene card video
      const videoEl = document.getElementById(`sceneVideo_${sceneIdx}`);
      if (videoEl && data.clip_url) {
        videoEl.src = `${data.clip_url}?t=${Date.now()}`;
      }
      const videoPill = document.getElementById(`sceneVideoPill_${sceneIdx}`);
      if (videoPill) {
        videoPill.style.display = "";
        videoPill.textContent = "⚡ Veo Video Ready";
      }
      const btnOverlay = document.getElementById(`btnPlayOverlay_${sceneIdx}`);
      if (btnOverlay) btnOverlay.style.display = "flex";
      const btnToggle = document.getElementById(`btnToggleVideo_${sceneIdx}`);
      if (btnToggle) {
        btnToggle.style.display = "";
        btnToggle.classList.add("video-ready");
      }
      const btnDownload = document.getElementById(`btnDownloadClip_${sceneIdx}`);
      if (btnDownload) btnDownload.style.display = "";

      this.showToast(`🎉 Scene ${sceneIdx + 1} rendered with Google Veo acting motion!`);
    } catch (e) {
      console.error(e);
      this.showToast(e.message, true);
    } finally {
      buttonEl.disabled = false;
      buttonEl.textContent = oldText;
    }
  }

  async saveCharacterConsistency() {
    if (!this.currentProject) return;
    if (this.inputCharacterConsistency) {
      this.currentProject.characters = this.inputCharacterConsistency.value.trim();
    }
    await this.saveStoryboardEdits(false);
    this.showToast("Character consistency anchor locked! 🔒👥");
  }

  async saveStoryboardEdits(notify = true) {
    if (!this.currentProject) return;

    if (this.inputCharacterConsistency) {
      this.currentProject.characters = this.inputCharacterConsistency.value.trim();
    }

    const scenes = this.currentProject.scenes || [];
    scenes.forEach((scene, idx) => {
      const narEl = document.getElementById(`narration_${idx}`);
      const promptEl = document.getElementById(`prompt_${idx}`);
      const motionEl = document.getElementById(`motion_${idx}`);

      if (narEl) scene.narration = narEl.value;
      if (promptEl) scene.visual_prompt = promptEl.value;
      if (motionEl) scene.camera_motion = motionEl.value;
    });

    try {
      const resp = await fetch(`/api/projects/${this.currentProject.id}/scenes`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenes,
          characters: this.currentProject.characters,
          title: this.currentProject.title,
          logline: this.currentProject.logline
        })
      });
      if (resp.ok) {
        this.currentProject = await resp.json();
        this.saveActiveProjectState();
        if (notify) this.showToast("Script changes saved! 💾");
      }
    } catch (e) {
      console.error("Save error:", e);
    }
  }

  async startRenderingProcess() {
    if (!this.currentProject) return;
    await this.saveStoryboardEdits(false);

    this.switchStage(3);

    // Initial progress display
    this.renderProgressBar.style.width = "30%";
    this.renderProgressPercent.textContent = "30%";
    this.renderStepDetail.textContent = "Starting AI rendering engine...";
    this.activityLogList.innerHTML = `
      <div class="log-row done"><span class="log-check">✓</span> Scriptwriter Agent generated storyboard</div>
      <div class="log-row active"><span class="log-spinner">⏳</span> Visual Artist Agent painting frames...</div>
    `;

    try {
      const curProvider = this.currentProject?.ai_provider || this.selectAiProvider?.value || "gemini";
      const curKey = this.getEffectiveApiKey(curProvider);
      const resp = await fetch(`/api/projects/${this.currentProject.id}/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: this.currentProject.id,
          api_key: curKey,
          ai_provider: curProvider
        })
      });

      if (!resp.ok) throw new Error("Render trigger failed");

      // Start polling
      this.pollRenderProgress();
    } catch (e) {
      console.error(e);
      this.showToast(e.message, true);
    }
  }

  pollRenderProgress() {
    if (this.pollInterval) clearInterval(this.pollInterval);

    this.pollInterval = setInterval(async () => {
      try {
        const resp = await fetch(`/api/projects/${this.currentProject.id}`);
        if (!resp.ok) return;

        const proj = await resp.json();
        this.currentProject = proj;
        this.saveActiveProjectState();

        const pct = proj.progress || 35;
        this.renderProgressBar.style.width = `${pct}%`;
        this.renderProgressPercent.textContent = `${pct}%`;
        this.renderStepDetail.textContent = proj.current_step || "Processing...";

        // Update activity log
        this.updateActivityLogs(pct, proj.current_step);

        if (proj.status === "completed") {
          clearInterval(this.pollInterval);
          this.pollInterval = null;
          this.showCinemaPremiere();
        } else if (proj.status === "error") {
          clearInterval(this.pollInterval);
          this.pollInterval = null;
          this.showToast("Rendering error occurred: " + proj.current_step, true);
        }
      } catch (e) {
        console.error("Poll error:", e);
      }
    }, 1500);
  }

  updateActivityLogs(pct, stepMsg) {
    let logsHtml = `
      <div class="log-row done"><span class="log-check">✓</span> Scriptwriter Agent created story structure</div>
    `;

    if (pct >= 50) {
      logsHtml += `<div class="log-row done"><span class="log-check">✓</span> Visual Artist generated scene illustrations</div>`;
    } else {
      logsHtml += `<div class="log-row active"><span class="log-spinner">⏳</span> Visual Artist painting keyframes...</div>`;
      this.activityLogList.innerHTML = logsHtml;
      return;
    }

    if (pct >= 70) {
      logsHtml += `<div class="log-row done"><span class="log-check">✓</span> Voice Agent recorded narration & subtitles</div>`;
    } else {
      logsHtml += `<div class="log-row active"><span class="log-spinner">⏳</span> Recording narration & word timestamps...</div>`;
      this.activityLogList.innerHTML = logsHtml;
      return;
    }

    if (pct >= 90) {
      logsHtml += `<div class="log-row done"><span class="log-check">✓</span> Video Engine rendered Ken Burns camera motion & subtitles</div>`;
      logsHtml += `<div class="log-row done"><span class="log-check">✓</span> Sound Designer mixed ambient music</div>`;
    } else {
      logsHtml += `<div class="log-row active"><span class="log-spinner">⏳</span> Applying 2.5D camera motions & burning subtitles...</div>`;
      this.activityLogList.innerHTML = logsHtml;
      return;
    }

    if (pct >= 100) {
      logsHtml += `<div class="log-row done"><span class="log-check">✓</span> Final MP4 master file ready for premiere!</div>`;
    }
    this.activityLogList.innerHTML = logsHtml;
  }

  showCinemaPremiere(notify = true) {
    if (!this.currentProject) return;
    this.cinemaMovieTitle.textContent = this.currentProject.title || "My Animated Film";
    this.cinemaMovieLogline.textContent = this.currentProject.logline || "";

    if (this.currentProject.video_path) {
      this.cinemaVideoPlayer.src = `/media/${this.currentProject.video_path}?t=${Date.now()}`;
      this.btnDownloadMovie.href = `/api/download/${this.currentProject.id}`;
    }

    const ar = this.currentProject.aspect_ratio || "16:9";
    const dim = this.config?.video_dimensions?.[ar] || {
      width: this.currentProject.video_width || 1280,
      height: this.currentProject.video_height || 720,
      name: `${ar} Widescreen`,
      ratio_css: ar.replace(":", " / ")
    };
    const ratioCss = dim.ratio_css || ar.replace(":", " / ");
    if (this.cinemaVideoPlayer?.parentElement) {
      this.cinemaVideoPlayer.parentElement.style.setProperty("--project-aspect-ratio", ratioCss);
    }

    if (this.specResolution) {
      const w = dim.width || this.currentProject.video_width || 1280;
      const h = dim.height || this.currentProject.video_height || 720;
      this.specResolution.textContent = `${w} x ${h} (${ar})`;
    }

    const styleInfo = this.config?.art_styles?.[this.currentProject.art_style];
    this.specArtStyle.textContent = styleInfo ? styleInfo.name : this.currentProject.art_style;

    // Populate Individual Scene Clips Gallery
    if (this.cinemaSceneClipsGrid) {
      this.cinemaSceneClipsGrid.innerHTML = "";
      const scenes = this.currentProject.scenes || [];
      let clipsReady = 0;

      scenes.forEach((sc, idx) => {
        if (sc.video_path) clipsReady++;
        const card = document.createElement("div");
        card.className = "cinema-scene-clip-card";
        const hasVid = Boolean(sc.video_path);
        const vidSrc = hasVid ? `/media/${sc.video_path}?t=${Date.now()}` : "";
        const imgSrc = sc.image_path ? `/media/${sc.image_path}?t=${Date.now()}` : this.getInstantPreviewUrl(sc, idx);

        card.innerHTML = `
          <div class="cinema-clip-video-box">
            ${hasVid 
              ? `<video src="${vidSrc}" controls playsinline preload="metadata"></video>` 
              : `<img src="${imgSrc}" style="width:100%;height:100%;object-fit:cover;" alt="Scene ${idx + 1}">`
            }
          </div>
          <div class="cinema-clip-info">
            <div class="cinema-clip-title">
              <span>Scene ${idx + 1}: ${sc.title || "Scene " + (idx + 1)}</span>
              ${hasVid 
                ? `<span class="tag-badge" style="background:rgba(16,185,129,0.2);color:#34d399;font-size:10px;">✓ Clip Ready</span>` 
                : `<span class="tag-badge" style="background:rgba(245,158,11,0.2);color:#fbbf24;font-size:10px;">Still Only</span>`
              }
            </div>
            <p class="cinema-clip-narration">${sc.narration || ""}</p>
            <div class="cinema-clip-actions">
              ${hasVid 
                ? `<a href="/api/projects/${this.currentProject.id}/download-scene-video/${idx}" download class="glass-btn secondary-btn" style="padding:6px 12px;font-size:11px;display:inline-flex;align-items:center;gap:4px;">⬇️ Download MP4</a>` 
                : `<button class="glass-btn secondary-btn" id="btnCinemaRenderScene_${idx}" style="padding:6px 12px;font-size:11px;display:inline-flex;align-items:center;gap:4px;">🎬 Animate Clip</button>`
              }
            </div>
          </div>
        `;

        if (!hasVid) {
          const btnRen = card.querySelector(`#btnCinemaRenderScene_${idx}`);
          if (btnRen) {
            btnRen.addEventListener("click", async () => {
              await this.animateSingleSceneVideo(idx, btnRen);
              this.showCinemaPremiere(false);
            });
          }
        }

        this.cinemaSceneClipsGrid.appendChild(card);
      });

      if (this.cinemaClipsCountBadge) {
        this.cinemaClipsCountBadge.textContent = `${clipsReady} / ${scenes.length} clips ready`;
      }
    }

    this.switchStage(4);
    if (notify) {
      this.showToast("🎉 Your animated movie is ready to watch!");
    }
  }

  async openProjectsModal() {
    this.modalProjects.classList.add("active");
    this.savedProjectsList.innerHTML = "<p>Loading films...</p>";

    try {
      const resp = await fetch("/api/projects");
      const list = await resp.json();

      if (!list || list.length === 0) {
        this.savedProjectsList.innerHTML = "<p style='color:var(--text-muted)'>No films created yet. Start with your first idea!</p>";
        return;
      }

      this.savedProjectsList.innerHTML = "";
      list.forEach(p => {
        const item = document.createElement("div");
        item.className = "project-item-card";
        const dateStr = new Date(p.created_at * 1000).toLocaleDateString();
        item.innerHTML = `
          <div class="project-card-title">${p.title || p.idea.substring(0, 30)}</div>
          <div class="project-card-date">Created ${dateStr} • ${p.scenes?.length || 0} scenes</div>
          <div style="font-size:12px; color: ${p.status === 'completed' ? '#34d399' : '#a78bfa'}">
            ● ${p.status.toUpperCase()}
          </div>
        `;
        item.addEventListener("click", () => {
          this.currentProject = p;
          this.saveActiveProjectState();
          this.modalProjects.classList.remove("active");
          if (p.status === "completed") {
            this.showCinemaPremiere();
          } else {
            this.renderStoryboardView();
            this.switchStage(2);
            this.autoGenerateMissingSceneImages();
          }
        });
        this.savedProjectsList.appendChild(item);
      });
    } catch (e) {
      console.error(e);
      this.savedProjectsList.innerHTML = "<p style='color:#ef4444'>Failed to load projects</p>";
    }
  }
}

// Instantiate on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  window.aniStoryApp = new AniStoryApp();
});
