/**
 * AniStory AI — Frontend Application Logic
 */

class AniStoryApp {
  static async parseErrorResponse(resp, fallbackMsg = "Request failed") {
    try {
      const raw = await resp.text();
      if (!raw) return `${fallbackMsg} (HTTP ${resp.status})`;
      try {
        const parsed = JSON.parse(raw);
        return parsed.detail || parsed.message || parsed.error || raw.slice(0, 300);
      } catch {
        return raw.slice(0, 300);
      }
    } catch {
      return `${fallbackMsg} (HTTP ${resp.status}: ${resp.statusText || 'Error'})`;
    }
  }

  constructor() {
    this.currentProject = null;
    this.config = null;
    this.selectedStyleKey = localStorage.getItem("anistory_cfg_art_style") || "ghibli";
    this.enableVoiceover = localStorage.getItem("anistory_cfg_enable_voiceover") !== "false";
    this.enableMultivoice = localStorage.getItem("anistory_cfg_enable_multivoice") !== "false";
    this.pollInterval = null;

    this.initElements();
    this.updateVoiceoverUI(this.enableVoiceover);
    this.updateMultivoiceUI(this.enableMultivoice);
    this.updateAutoPaintUI(localStorage.getItem("anistory_autopaint") === "true");
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
    const urlParams = new URLSearchParams(window.location.search);
    const paramProjectId = urlParams.get("project") || urlParams.get("load");
    const savedProjectId = paramProjectId || localStorage.getItem("anistory_active_project_id");
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
    this.selectTargetDuration = document.getElementById("selectTargetDuration");
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
    this.btnExportStoryboard = document.getElementById("btnExportStoryboard");
    this.btnExportScript = document.getElementById("btnExportScript");
    this.btnRefineAllPrompts = document.getElementById("btnRefineAllPrompts");
    this.btnSyncDialogues = document.getElementById("btnSyncDialogues");
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
    this.tabModeLoad = document.getElementById("tabModeLoad");
    this.panelPromptMode = document.getElementById("panelPromptMode");
    this.panelPasteMode = document.getElementById("panelPasteMode");
    this.panelLoadMode = document.getElementById("panelLoadMode");
    this.stage1ProjectsList = document.getElementById("stage1ProjectsList");
    this.btnImportProjectJsonStage1 = document.getElementById("btnImportProjectJsonStage1");
    this.inputImportProjectJsonStage1 = document.getElementById("inputImportProjectJsonStage1");
    this.btnRefreshProjectsStage1 = document.getElementById("btnRefreshProjectsStage1");
    this.btnSwitchProject = document.getElementById("btnSwitchProject");
    this.btnImportProjectJsonModal = document.getElementById("btnImportProjectJsonModal");
    this.inputImportProjectJsonModal = document.getElementById("inputImportProjectJsonModal");
    this.inputDirectPasteText = document.getElementById("inputDirectPasteText");
    this.btnCopyGeminiPromptDirect = document.getElementById("btnCopyGeminiPromptDirect");
    this.btnDirectLoadStoryboard = document.getElementById("btnDirectLoadStoryboard");
    this.groupSceneCount = document.getElementById("groupSceneCount");

    // Stage 1 Goods Advertisement Mode Elements
    this.tabModeAd = document.getElementById("tabModeAd");
    this.panelAdMode = document.getElementById("panelAdMode");
    this.inputAdProductName = document.getElementById("inputAdProductName");
    this.inputAdBrand = document.getElementById("inputAdBrand");
    this.selectAdStyle = document.getElementById("selectAdStyle");
    this.selectAdAudience = document.getElementById("selectAdAudience");
    this.textareaAdDesc = document.getElementById("textareaAdDesc");
    this.textareaAdSpecs = document.getElementById("textareaAdSpecs");
    this.inputAdOffer = document.getElementById("inputAdOffer");
    this.inputAdCTA = document.getElementById("inputAdCTA");
    this.dropzoneAdImages = document.getElementById("dropzoneAdImages");
    this.inputAdImages = document.getElementById("inputAdImages");
    this.adImagesPreviewContainer = document.getElementById("adImagesPreviewContainer");
    this.adImagesCountBadge = document.getElementById("adImagesCountBadge");
    this.btnGenerateAdVideo = document.getElementById("btnGenerateAdVideo");
    this.adUploadedFiles = [];

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
    this.badgeStoryboardAdMode = document.getElementById("badgeStoryboardAdMode");
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
    this.btnToggleVoiceoverStage1 = document.getElementById("btnToggleVoiceoverStage1");
    this.iconVoiceoverStage1 = document.getElementById("iconVoiceoverStage1");
    this.textVoiceoverStage1 = document.getElementById("textVoiceoverStage1");
    this.btnToggleMultivoiceStage1 = document.getElementById("btnToggleMultivoiceStage1");
    this.iconMultivoiceStage1 = document.getElementById("iconMultivoiceStage1");
    this.textMultivoiceStage1 = document.getElementById("textMultivoiceStage1");
    this.btnToggleVoiceoverStage2 = document.getElementById("btnToggleVoiceoverStage2");
    this.iconVoiceoverStage2 = document.getElementById("iconVoiceoverStage2");
    this.textVoiceoverStage2 = document.getElementById("textVoiceoverStage2");
    this.btnToggleMultivoiceStage2 = document.getElementById("btnToggleMultivoiceStage2");
    this.iconMultivoiceStage2 = document.getElementById("iconMultivoiceStage2");
    this.textMultivoiceStage2 = document.getElementById("textMultivoiceStage2");
    this.characterVoiceCastingBar = document.getElementById("characterVoiceCastingBar");
    this.characterVoicesList = document.getElementById("characterVoicesList");
    this.btnAutoCastVoices = document.getElementById("btnAutoCastVoices");
    this.selectVoiceStage2 = document.getElementById("selectVoiceStage2");
    this.btnAuditionVoiceStage2 = document.getElementById("btnAuditionVoiceStage2");
    this.iconAuditionVoiceStage2 = document.getElementById("iconAuditionVoiceStage2");
    this.btnToggleSubtitlesStage2 = document.getElementById("btnToggleSubtitlesStage2");
    this.iconSubtitlesStage2 = document.getElementById("iconSubtitlesStage2");
    this.textSubtitlesStage2 = document.getElementById("textSubtitlesStage2");
    this.btnToggleAutoPaint = document.getElementById("btnToggleAutoPaint");
    this.iconAutoPaint = document.getElementById("iconAutoPaint");
    this.textAutoPaint = document.getElementById("textAutoPaint");
    this.checkSettingsAutoPaint = document.getElementById("checkSettingsAutoPaint");

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

    // Quick-Jump Navigation Ribbon & Floating Director Controls
    this.sceneQuickJumpBar = document.getElementById("sceneQuickJumpBar");
    this.floatingDirectorWidget = document.getElementById("floatingDirectorWidget");
    this.btnFloatingScrollTop = document.getElementById("btnFloatingScrollTop");
    this.btnFloatingRenderFilm = document.getElementById("btnFloatingRenderFilm");

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

    // Floating director navigation widget actions
    if (this.btnFloatingScrollTop) {
      this.btnFloatingScrollTop.addEventListener("click", () => {
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    }
    if (this.btnFloatingRenderFilm) {
      this.btnFloatingRenderFilm.addEventListener("click", () => {
        if (this.btnProceedToRender) this.btnProceedToRender.click();
      });
    }

    // Show floating widget only when scrolling past 320px in Stage 2
    window.addEventListener("scroll", () => {
      if (this.floatingDirectorWidget) {
        const isStage2 = this.stages[1] && this.stages[1].classList.contains("active");
        if (isStage2 && window.scrollY > 320) {
          this.floatingDirectorWidget.style.display = "flex";
        } else {
          this.floatingDirectorWidget.style.display = "none";
        }
      }
    }, { passive: true });

    // Browser back/forward button history support
    window.addEventListener("popstate", (e) => {
      const targetStage = (e.state && e.state.stage) ? e.state.stage : 1;
      if (targetStage > 1 && !this.currentProject) {
        this.switchStage(1, false);
        return;
      }
      this.switchStage(targetStage, false);
    });

    // Stage 1 Creation Mode Tabs (Prompt vs Direct Paste vs Load Existing)
    const configGrid = document.querySelector(".config-grid");
    const aiProviderPanel = document.querySelector(".ai-provider-panel");
    const actionFooter = document.querySelector(".action-footer");
    if (this.tabModePrompt) {
      this.tabModePrompt.addEventListener("click", () => {
        this.tabModePrompt.classList.add("active");
        if (this.tabModePaste) this.tabModePaste.classList.remove("active");
        if (this.tabModeLoad) this.tabModeLoad.classList.remove("active");
        if (this.tabModeAd) this.tabModeAd.classList.remove("active");
        if (this.panelPromptMode) this.panelPromptMode.style.display = "block";
        if (this.panelPasteMode) this.panelPasteMode.style.display = "none";
        if (this.panelLoadMode) this.panelLoadMode.style.display = "none";
        if (this.panelAdMode) this.panelAdMode.style.display = "none";
        if (this.btnGenerateStoryboard) this.btnGenerateStoryboard.style.display = "inline-flex";
        if (this.btnDirectLoadStoryboard) this.btnDirectLoadStoryboard.style.display = "none";
        if (this.btnGenerateAdVideo) this.btnGenerateAdVideo.style.display = "none";
        if (this.groupSceneCount) this.groupSceneCount.style.display = "block";
        if (configGrid) configGrid.style.display = "";
        if (aiProviderPanel) aiProviderPanel.style.display = "";
        if (actionFooter) actionFooter.style.display = "";
        localStorage.setItem("anistory_cfg_creation_mode", "prompt");
      });
    }

    if (this.tabModePaste) {
      this.tabModePaste.addEventListener("click", () => {
        this.tabModePaste.classList.add("active");
        if (this.tabModePrompt) this.tabModePrompt.classList.remove("active");
        if (this.tabModeLoad) this.tabModeLoad.classList.remove("active");
        if (this.tabModeAd) this.tabModeAd.classList.remove("active");
        if (this.panelPromptMode) this.panelPromptMode.style.display = "none";
        if (this.panelPasteMode) this.panelPasteMode.style.display = "block";
        if (this.panelLoadMode) this.panelLoadMode.style.display = "none";
        if (this.panelAdMode) this.panelAdMode.style.display = "none";
        if (this.btnGenerateStoryboard) this.btnGenerateStoryboard.style.display = "none";
        if (this.btnDirectLoadStoryboard) this.btnDirectLoadStoryboard.style.display = "inline-flex";
        if (this.btnGenerateAdVideo) this.btnGenerateAdVideo.style.display = "none";
        if (this.groupSceneCount) this.groupSceneCount.style.display = "block";
        if (configGrid) configGrid.style.display = "";
        if (aiProviderPanel) aiProviderPanel.style.display = "";
        if (actionFooter) actionFooter.style.display = "";
        localStorage.setItem("anistory_cfg_creation_mode", "paste");
      });
    }

    if (this.tabModeLoad) {
      this.tabModeLoad.addEventListener("click", () => {
        this.tabModeLoad.classList.add("active");
        if (this.tabModePrompt) this.tabModePrompt.classList.remove("active");
        if (this.tabModePaste) this.tabModePaste.classList.remove("active");
        if (this.tabModeAd) this.tabModeAd.classList.remove("active");
        if (this.panelPromptMode) this.panelPromptMode.style.display = "none";
        if (this.panelPasteMode) this.panelPasteMode.style.display = "none";
        if (this.panelLoadMode) this.panelLoadMode.style.display = "block";
        if (this.panelAdMode) this.panelAdMode.style.display = "none";
        if (this.btnGenerateStoryboard) this.btnGenerateStoryboard.style.display = "none";
        if (this.btnDirectLoadStoryboard) this.btnDirectLoadStoryboard.style.display = "none";
        if (this.btnGenerateAdVideo) this.btnGenerateAdVideo.style.display = "none";
        if (configGrid) configGrid.style.display = "none";
        if (aiProviderPanel) aiProviderPanel.style.display = "none";
        if (actionFooter) actionFooter.style.display = "none";
        localStorage.setItem("anistory_cfg_creation_mode", "load");
        this.loadProjectsIntoContainer(this.stage1ProjectsList);
      });
    }

    if (this.tabModeAd) {
      this.tabModeAd.addEventListener("click", () => {
        this.tabModeAd.classList.add("active");
        if (this.tabModePrompt) this.tabModePrompt.classList.remove("active");
        if (this.tabModePaste) this.tabModePaste.classList.remove("active");
        if (this.tabModeLoad) this.tabModeLoad.classList.remove("active");
        if (this.panelPromptMode) this.panelPromptMode.style.display = "none";
        if (this.panelPasteMode) this.panelPasteMode.style.display = "none";
        if (this.panelLoadMode) this.panelLoadMode.style.display = "none";
        if (this.panelAdMode) this.panelAdMode.style.display = "block";
        if (this.btnGenerateStoryboard) this.btnGenerateStoryboard.style.display = "none";
        if (this.btnDirectLoadStoryboard) this.btnDirectLoadStoryboard.style.display = "none";
        if (this.btnGenerateAdVideo) this.btnGenerateAdVideo.style.display = "inline-flex";
        if (this.groupSceneCount) this.groupSceneCount.style.display = "block";
        if (configGrid) configGrid.style.display = "";
        if (aiProviderPanel) aiProviderPanel.style.display = "";
        if (actionFooter) actionFooter.style.display = "";
        // Auto-select realistic style if none set or if default
        document.querySelectorAll(".style-card-item").forEach(card => {
          if (card.textContent.includes("Realistic") || card.textContent.includes("Photorealistic")) {
            card.click();
          }
        });
        localStorage.setItem("anistory_cfg_creation_mode", "advertisement");
      });
    }

    // Goods Dropzone & Image Selection
    if (this.dropzoneAdImages && this.inputAdImages) {
      this.dropzoneAdImages.addEventListener("click", () => this.inputAdImages.click());
      this.dropzoneAdImages.addEventListener("dragover", (e) => {
        e.preventDefault();
        this.dropzoneAdImages.classList.add("dragover");
      });
      this.dropzoneAdImages.addEventListener("dragleave", () => {
        this.dropzoneAdImages.classList.remove("dragover");
      });
      this.dropzoneAdImages.addEventListener("drop", (e) => {
        e.preventDefault();
        this.dropzoneAdImages.classList.remove("dragover");
        if (e.dataTransfer && e.dataTransfer.files) {
          this.handleAddAdImages(Array.from(e.dataTransfer.files));
        }
      });
      this.inputAdImages.addEventListener("change", (e) => {
        if (e.target.files) {
          this.handleAddAdImages(Array.from(e.target.files));
          this.inputAdImages.value = "";
        }
      });
    }

    // Goods Example Sparks Templates
    const adSparks = {
      headphones: {
        name: "AeroPulse Pro Wireless Headphones",
        brand: "Apex Audio",
        desc: "Ultra-lightweight wireless noise-cancelling headphones crafted from aerospace titanium. Studio-grade acoustic fidelity with all-day cloud comfort.",
        specs: "• 45dB Dual-Processor Hybrid ANC\n• 40-Hour Battery Life + Fast Charge (10min = 5hrs)\n• 40mm Beryllium Acoustic Drivers\n• Ultra-light 185g Titanium Frame • Bluetooth 5.4 Low-Latency",
        offer: "Special Launch Price: $149 (Regular $249 — 40% OFF)",
        cta: "Order now with Free Worldwide Express Shipping! 30-Day Money-Back Guarantee.",
        style: "cinematic_commercial",
        audience: "Tech Enthusiasts & Professionals"
      },
      espresso: {
        name: "BaristaGlow Smart Espresso Machine",
        brand: "AromaCraft",
        desc: "Commercial-grade compact smart espresso machine for cafe-quality coffee at home in under 45 seconds.",
        specs: "• 20-Bar Italian High-Pressure Pump\n• Dual Thermo-Block Heating System\n• Microfoam Steam Wand\n• Smart Touchscreen & Brew App Control",
        offer: "Bundle Deal: Get 2 Free Bags of Artisanal Beans + 20% OFF",
        cta: "Claim your special bundle today! Limited stock available.",
        style: "luxury_macro",
        audience: "Families & Homeowners"
      },
      serum: {
        name: "Lumière Youth Peptide Facial Serum",
        brand: "Éclat Botanicals",
        desc: "Clinically proven anti-aging glow serum infused with 5 bio-active peptides and plant collagen to restore youthful elasticity in 7 days.",
        specs: "• 5-Peptide Multi-Complex + Niacinamide\n• 100% Vegan & Cruelty-Free\n• Dermatologist Tested & Fragrance-Free\n• Visible Firming in 7 Days",
        offer: "Buy 1 Get 1 50% OFF + Free Jade Roller with Code GLOW50",
        cta: "Transform your skincare ritual today. Order now!",
        style: "luxury_macro",
        audience: "Affluent & Luxury Buyers"
      },
      smartwatch: {
        name: "TitanApex Rugged GPS Smartwatch",
        brand: "Vanguard Tech",
        desc: "Military-grade ultra-durable multisport smartwatch engineered for extreme exploration, endurance, and 24/7 biometric health tracking.",
        specs: "• Grade-5 Titanium Bezel & Sapphire Glass\n• 21-Day Battery Life in Smartwatch Mode\n• 100M Water-Resistant (10 ATM)\n• Multi-Band Dual-Frequency GPS & Offline Topo Maps",
        offer: "Early Explorer Discount: $299 (Save $100 This Week Only)",
        cta: "Gear up for your next adventure. Order yours now!",
        style: "spec_breakdown",
        audience: "Fitness & Active Lifestyle"
      },
      shoes: {
        name: "HyperStride Carbon Road Running Shoes",
        brand: "AeroForm Athletics",
        desc: "Super-responsive elite marathon racing shoes featuring full-length carbon fiber propulsion plate and featherlight energy foam.",
        specs: "• Full-Length Curved Carbon Fiber Plate\n• Ultra-Rebound Pebax Supercritical Foam\n• Breathable Monomesh Upper (168g per shoe)\n• Anti-Slip Wet/Dry Continental Rubber Outsole",
        offer: "Free Ergonomic Socks + Free Returns on All Shoe Orders",
        cta: "Feel the speed. Order your size today before stock runs out!",
        style: "viral_reels",
        audience: "Fitness & Active Lifestyle"
      }
    };

    document.querySelectorAll("#adSparksChips button[data-ad]").forEach(btn => {
      btn.addEventListener("click", () => {
        const key = btn.dataset.ad;
        const item = adSparks[key];
        if (!item) return;
        if (this.inputAdProductName) this.inputAdProductName.value = item.name;
        if (this.inputAdBrand) this.inputAdBrand.value = item.brand;
        if (this.textareaAdDesc) this.textareaAdDesc.value = item.desc;
        if (this.textareaAdSpecs) this.textareaAdSpecs.value = item.specs;
        if (this.inputAdOffer) this.inputAdOffer.value = item.offer;
        if (this.inputAdCTA) this.inputAdCTA.value = item.cta;
        if (this.selectAdStyle) this.selectAdStyle.value = item.style;
        if (this.selectAdAudience) this.selectAdAudience.value = item.audience;
        this.showToast(`✨ Pre-filled "${item.name}"!`);
      });
    });

    if (this.btnGenerateAdVideo) {
      this.btnGenerateAdVideo.addEventListener("click", () => this.handleGenerateAdvertisementVideo());
    }

    // Stage 1 existing projects handlers
    if (this.btnRefreshProjectsStage1) {
      this.btnRefreshProjectsStage1.addEventListener("click", () => {
        this.loadProjectsIntoContainer(this.stage1ProjectsList);
      });
    }
    if (this.btnImportProjectJsonStage1 && this.inputImportProjectJsonStage1) {
      this.btnImportProjectJsonStage1.addEventListener("click", () => this.inputImportProjectJsonStage1.click());
      this.inputImportProjectJsonStage1.addEventListener("change", (e) => {
        if (e.target.files && e.target.files[0]) {
          this.importProjectJsonFile(e.target.files[0]);
          e.target.value = "";
        }
      });
    }

    // Stage 2 Switch project button
    if (this.btnSwitchProject) {
      this.btnSwitchProject.addEventListener("click", () => this.openProjectsModal());
    }

    // Modal Import project.json handlers
    if (this.btnImportProjectJsonModal && this.inputImportProjectJsonModal) {
      this.btnImportProjectJsonModal.addEventListener("click", () => this.inputImportProjectJsonModal.click());
      this.inputImportProjectJsonModal.addEventListener("change", (e) => {
        if (e.target.files && e.target.files[0]) {
          this.importProjectJsonFile(e.target.files[0]);
          e.target.value = "";
        }
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
    bindSelectPersistence(this.selectTargetDuration, "anistory_cfg_target_duration");
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
        const count = this.getSceneCountLabel();
        this.showToast(`Prompt for ${count} copied to clipboard! Paste it into Gemini Pro 📑`);
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
    if (this.btnExportStoryboard) {
      this.btnExportStoryboard.addEventListener("click", () => this.exportAllPrompts());
    }
    if (this.btnExportScript) {
      this.btnExportScript.addEventListener("click", () => this.exportFullScript());
    }
    if (this.btnRefineAllPrompts) {
      this.btnRefineAllPrompts.addEventListener("click", () => this.refineAllVideoPrompts(this.btnRefineAllPrompts));
    }
    if (this.btnSyncDialogues) {
      this.btnSyncDialogues.addEventListener("click", () => this.syncStoryDialogues(null, "all", this.btnSyncDialogues));
    }
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
      if (this.selectSettingsImageMode) this.selectSettingsImageMode.value = (this.imageMode === "server" ? "gemini" : (this.imageMode || "gemini"));
      if (this.checkSettingsAutoPaint) {
        this.checkSettingsAutoPaint.checked = localStorage.getItem("anistory_autopaint") === "true";
      }
      this.modalSettings.classList.add("active");
    });
    this.btnCloseSettings.addEventListener("click", () => this.modalSettings.classList.remove("active"));
    this.btnSaveSettings.addEventListener("click", () => {
      if (this.checkSettingsAutoPaint) {
        localStorage.setItem("anistory_autopaint", this.checkSettingsAutoPaint.checked ? "true" : "false");
        this.updateAutoPaintUI(this.checkSettingsAutoPaint.checked);
      }
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

    // Image Painting Mode Toggles (Google Gemini Imagen 3 vs Neural.love vs Puter.js vs Storyboard Only)
    const toggleImageModeHandler = () => {
      const modes = ["gemini", "neural_love", "puter", "manual"];
      const currentIdx = Math.max(0, modes.indexOf(this.imageMode));
      const nextMode = modes[(currentIdx + 1) % modes.length];
      this.setImageMode(nextMode);
      const label = nextMode === "gemini" ? "✨ Google Gemini / Imagen 3" : (nextMode === "neural_love" ? "💖 Neural.love AI Art" : (nextMode === "puter" ? "🖌️ In-Browser Puter.js" : "📝 Storyboard Only (No AI Paint)"));
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

    // Toggle Voiceover in Stage 1
    if (this.btnToggleVoiceoverStage1) {
      this.btnToggleVoiceoverStage1.addEventListener("click", () => {
        this.enableVoiceover = !this.enableVoiceover;
        localStorage.setItem("anistory_cfg_enable_voiceover", this.enableVoiceover ? "true" : "false");
        this.updateVoiceoverUI(this.enableVoiceover);
        this.showToast(this.enableVoiceover ? "🎙️ Voiceover narration enabled" : "🔇 Voiceover narration disabled (instrumental only)");
      });
    }

    // Toggle Voiceover in Stage 2
    if (this.btnToggleVoiceoverStage2) {
      this.btnToggleVoiceoverStage2.addEventListener("click", async () => {
        if (!this.currentProject) return;
        const oldState = this.currentProject.enable_voiceover !== false;
        const newState = !oldState;
        this.updateVoiceoverUI(newState);
        this.showToast(newState ? "🎙️ Enabling voiceover & updating clips... ⏳" : "🔇 Disabling voiceover & updating clips... ⏳");
        try {
          const resp = await fetch(`/api/projects/${this.currentProject.id}/toggle-voiceover`, { method: "POST" });
          if (resp.ok) {
            const data = await resp.json();
            if (data.project) {
              this.currentProject = data.project;
            }
            this.currentProject.enable_voiceover = data.enable_voiceover;
            this.enableVoiceover = data.enable_voiceover;
            localStorage.setItem("anistory_cfg_enable_voiceover", this.enableVoiceover ? "true" : "false");
            this.saveActiveProjectState();
            this.updateVoiceoverUI(this.currentProject.enable_voiceover);
            this.renderStoryboardView();
            this.showToast(data.enable_voiceover ? "🎙️ Voiceover enabled" : "🔇 Voiceover disabled (clips updated with clean audio)");
          }
        } catch (e) {
          console.error(e);
          this.updateVoiceoverUI(oldState);
          this.showToast("Failed to toggle voiceover: " + e.message, true);
        }
      });
    }

    // Toggle Multi-Voice in Stage 1
    if (this.btnToggleMultivoiceStage1) {
      this.btnToggleMultivoiceStage1.addEventListener("click", () => {
        this.enableMultivoice = !this.enableMultivoice;
        localStorage.setItem("anistory_cfg_enable_multivoice", this.enableMultivoice ? "true" : "false");
        this.updateMultivoiceUI(this.enableMultivoice);
        this.showToast(this.enableMultivoice ? "🎭 Multi-Voice enabled (auto-casts character voices)" : "🎙️ Multi-Voice disabled (single narrator reads all)");
      });
    }

    // Toggle Multi-Voice in Stage 2
    if (this.btnToggleMultivoiceStage2) {
      this.btnToggleMultivoiceStage2.addEventListener("click", async () => {
        if (!this.currentProject) return;
        const oldState = this.currentProject.enable_multivoice !== false;
        const newState = !oldState;
        this.updateMultivoiceUI(newState);
        try {
          const resp = await fetch(`/api/projects/${this.currentProject.id}/toggle-multivoice`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enable: newState })
          });
          if (resp.ok) {
            const data = await resp.json();
            if (data.project) {
              this.currentProject = data.project;
            }
            this.currentProject.enable_multivoice = data.enable_multivoice;
            this.enableMultivoice = data.enable_multivoice;
            localStorage.setItem("anistory_cfg_enable_multivoice", this.enableMultivoice ? "true" : "false");
            this.saveActiveProjectState();
            this.updateMultivoiceUI(this.currentProject.enable_multivoice);
            this.renderStoryboardView();
            this.showToast(data.enable_multivoice ? "🎭 Multi-Voice enabled" : "🎙️ Multi-Voice disabled (single narrator)");
          }
        } catch (e) {
          console.error(e);
          this.updateMultivoiceUI(oldState);
          this.showToast("Failed to toggle multi-voice: " + e.message, true);
        }
      });
    }

    // Auto-cast voices button
    if (this.btnAutoCastVoices) {
      this.btnAutoCastVoices.addEventListener("click", async () => {
        if (!this.currentProject) return;
        const btn = this.btnAutoCastVoices;
        btn.disabled = true;
        btn.innerHTML = `<span>⏳ Casting Voices...</span>`;
        try {
          const resp = await fetch(`/api/projects/${this.currentProject.id}/auto-cast-voices`, { method: "POST" });
          if (resp.ok) {
            const data = await resp.json();
            if (data.project) {
              this.currentProject = data.project;
            }
            this.saveActiveProjectState();
            this.renderCharacterVoiceCasting();
            this.showToast("✨ Voices auto-cast successfully!");
          } else {
            const err = await resp.json().catch(() => ({ detail: "Casting failed" }));
            this.showToast(err.detail || "Failed to auto-cast voices", true);
          }
        } catch (e) {
          this.showToast("Auto-cast error: " + e.message, true);
        } finally {
          btn.disabled = false;
          btn.innerHTML = `<span>🤖 Auto-Cast Voices</span>`;
        }
      });
    }

    // Change Narrator Voice in Stage 2
    if (this.selectVoiceStage2) {
      this.selectVoiceStage2.addEventListener("change", async () => {
        const newVoice = this.selectVoiceStage2.value;
        localStorage.setItem("anistory_cfg_voice", newVoice);
        if (this.selectVoice) this.selectVoice.value = newVoice;
        if (!this.currentProject) return;
        try {
          const resp = await fetch(`/api/projects/${this.currentProject.id}/set-voice`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ voice: newVoice })
          });
          if (resp.ok) {
            const data = await resp.json();
            if (data.project) {
              this.currentProject = data.project;
            } else {
              this.currentProject.voice = newVoice;
            }
            this.saveActiveProjectState();
            this.showToast(`🎙️ Đã đổi giọng đọc sang: ${newVoice}. Nhấn Animate Clip hoặc Render Full Film để áp dụng!`);
          }
        } catch (e) {
          console.error(e);
          this.showToast("Không thể đổi giọng đọc: " + e.message, true);
        }
      });
    }

    // Audition Voice in Stage 2
    if (this.btnAuditionVoiceStage2 && this.audioAuditionPlayer) {
      this.btnAuditionVoiceStage2.addEventListener("click", async (e) => {
        e.preventDefault();
        if (!this.audioAuditionPlayer.paused && this.audioAuditionPlayer.currentTime > 0) {
          this.audioAuditionPlayer.pause();
          this.audioAuditionPlayer.currentTime = 0;
          if (this.iconAuditionVoiceStage2) this.iconAuditionVoiceStage2.textContent = "🔊";
          this.showToast("Đã dừng nghe thử ⏹️");
          return;
        }
        const selectedVoice = this.selectVoiceStage2?.value || this.currentProject?.voice || "vi-VN-HoaiMyNeural";
        const selectedLang = this.currentProject?.language || (this.selectLanguage ? this.selectLanguage.value : "vi");
        const curProvider = this.selectAiProvider?.value || "gemini";
        const curKey = this.getEffectiveApiKey(curProvider);

        this.btnAuditionVoiceStage2.disabled = true;
        if (this.iconAuditionVoiceStage2) this.iconAuditionVoiceStage2.textContent = "⏳";
        this.showToast(`Đang tạo mẫu thử giọng: ${selectedVoice}... 🎙️`);
        try {
          const resp = await fetch("/api/audition-voice", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ voice: selectedVoice, language: selectedLang, api_key: curKey })
          });
          if (!resp.ok) throw new Error("Voice audition failed");
          const data = await resp.json();
          if (data.audio_url) {
            this.audioAuditionPlayer.src = `${data.audio_url}?t=${Date.now()}`;
            this.audioAuditionPlayer.volume = 1.0;
            this.audioAuditionPlayer.muted = false;
            if (this.iconAuditionVoiceStage2) this.iconAuditionVoiceStage2.textContent = "⏹️";
            this.btnAuditionVoiceStage2.disabled = false;
            const onEnd = () => {
              if (this.iconAuditionVoiceStage2) this.iconAuditionVoiceStage2.textContent = "🔊";
              this.audioAuditionPlayer.removeEventListener("ended", onEnd);
            };
            this.audioAuditionPlayer.addEventListener("ended", onEnd);
            await this.audioAuditionPlayer.play();
            this.showToast(`Đang phát mẫu giọng: ${selectedVoice} 🔊`);
          }
        } catch (err) {
          console.error(err);
          if (this.iconAuditionVoiceStage2) this.iconAuditionVoiceStage2.textContent = "🔊";
          this.btnAuditionVoiceStage2.disabled = false;
          this.showToast("Không thể nghe thử giọng: " + err.message, true);
        }
      });
    }

    // Toggle Subtitles in Stage 2
    if (this.btnToggleSubtitlesStage2) {
      this.btnToggleSubtitlesStage2.addEventListener("click", async () => {
        if (!this.currentProject) return;
        const oldState = this.currentProject.enable_subtitles !== false;
        const newState = !oldState;
        this.updateSubtitlesUI(newState);
        this.showToast(newState ? "💬 Enabling subtitles & updating clips... ⏳" : "🚫 Disabling subtitles & updating clips... ⏳");
        try {
          const resp = await fetch(`/api/projects/${this.currentProject.id}/toggle-subtitles`, { method: "POST" });
          if (resp.ok) {
            const data = await resp.json();
            if (data.project) {
              this.currentProject = data.project;
            }
            this.currentProject.enable_subtitles = data.enable_subtitles;
            this.enableSubtitles = data.enable_subtitles;
            localStorage.setItem("anistory_cfg_enable_subtitles", this.enableSubtitles ? "true" : "false");
            this.saveActiveProjectState();
            this.updateSubtitlesUI(this.currentProject.enable_subtitles);
            this.renderStoryboardView();
            this.showToast(data.enable_subtitles ? "💬 Captions enabled" : "🔇 Captions disabled (clean video)");
          }
        } catch (e) {
          console.error(e);
          this.updateSubtitlesUI(oldState);
          this.showToast("Failed to toggle subtitles: " + e.message, true);
        }
      });
    }

    // Toggle Auto-Paint in Stage 2 & Settings
    const toggleAutoPaintHandler = () => {
      const current = localStorage.getItem("anistory_autopaint") === "true";
      const next = !current;
      localStorage.setItem("anistory_autopaint", next ? "true" : "false");
      this.updateAutoPaintUI(next);
      this.showToast(next ? "✨ Auto-Paint enabled (Scenes will paint automatically)" : "🚫 Auto-Paint disabled (Manual review mode)");
    };

    if (this.btnToggleAutoPaint) {
      this.btnToggleAutoPaint.addEventListener("click", toggleAutoPaintHandler);
    }
    if (this.checkSettingsAutoPaint) {
      this.checkSettingsAutoPaint.addEventListener("change", (e) => {
        localStorage.setItem("anistory_autopaint", e.target.checked ? "true" : "false");
        this.updateAutoPaintUI(e.target.checked);
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
        const count = this.getSceneCountLabel();
        this.showToast(`Prompt for ${count} copied to clipboard! Paste it into Gemini Pro 📑`);
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

    // 7. Creation Mode (Prompt vs Direct Paste vs Load tab)
    const savedMode = localStorage.getItem("anistory_cfg_creation_mode");
    if (savedMode === "paste" && this.tabModePaste) {
      this.tabModePaste.click();
    } else if (savedMode === "load" && this.tabModeLoad) {
      this.tabModeLoad.click();
    } else if (savedMode === "prompt" && this.tabModePrompt) {
      this.tabModePrompt.click();
    }
  }

  initImageMode() {
    let mode = localStorage.getItem("anistory_image_mode") || "gemini";
    if (mode === "server") mode = "gemini";
    this.imageMode = mode;
    this.applyImageModeUI(this.imageMode);
  }

  setImageMode(mode) {
    if (mode === "server") mode = "gemini";
    this.imageMode = mode;
    localStorage.setItem("anistory_image_mode", mode);
    this.applyImageModeUI(mode);
  }

  applyImageModeUI(mode) {
    if (this.badgeImageMode) {
      if (mode === "manual") {
        this.badgeImageMode.textContent = "📝 Storyboard Only (No AI Painting)";
        this.badgeImageMode.style.background = "rgba(16, 185, 129, 0.2)";
        this.badgeImageMode.style.color = "#6ee7b7";
      } else if (mode === "neural_love") {
        this.badgeImageMode.textContent = "💖 Neural.love AI Art";
        this.badgeImageMode.style.background = "rgba(236, 72, 153, 0.2)";
        this.badgeImageMode.style.color = "#f472b6";
      } else if (mode === "puter") {
        this.badgeImageMode.textContent = "🖌️ In-Browser Puter.js";
        this.badgeImageMode.style.background = "rgba(16, 185, 129, 0.2)";
        this.badgeImageMode.style.color = "#34d399";
      } else {
        this.badgeImageMode.textContent = "✨ Google Gemini / Imagen 3";
        this.badgeImageMode.style.background = "rgba(245, 158, 11, 0.2)";
        this.badgeImageMode.style.color = "#fbbf24";
      }
    }
    if (this.descImageMode) {
      if (mode === "manual") {
        this.descImageMode.textContent = "AI is dedicated exclusively to the storyboard. Scenes use SVG placeholders and user-uploaded media.";
      } else if (mode === "neural_love") {
        this.descImageMode.textContent = "High-fidelity artistic anime & fantasy illustrations via your Neural.love API Key";
      } else if (mode === "puter") {
        this.descImageMode.textContent = "In-browser Puter.js AI Paint (subject to Puter balance/quota)";
      } else {
        this.descImageMode.textContent = "High-fidelity Google Imagen 3 visuals powered by your Gemini API Key or Web Cookie";
      }
    }
    if (this.btnToggleImageMode) {
      if (mode === "gemini") {
        this.btnToggleImageMode.innerHTML = `<span>💖</span> Switch to Neural.love AI Art`;
      } else if (mode === "neural_love") {
        this.btnToggleImageMode.innerHTML = `<span>🖌️</span> Switch to In-Browser Puter.js`;
      } else if (mode === "puter") {
        this.btnToggleImageMode.innerHTML = `<span>📝</span> Switch to Storyboard Only`;
      } else {
        this.btnToggleImageMode.innerHTML = `<span>✨</span> Switch to Google Gemini Imagen 3`;
      }
    }
    if (this.selectSettingsImageMode) {
      this.selectSettingsImageMode.value = (mode === "server") ? "gemini" : mode;
    }
    if (this.textImageModeStage2 && this.iconImageModeStage2) {
      if (mode === "manual") {
        this.iconImageModeStage2.textContent = "📝";
        this.textImageModeStage2.textContent = "Paint: Storyboard Only";
      } else if (mode === "neural_love") {
        this.iconImageModeStage2.textContent = "💖";
        this.textImageModeStage2.textContent = "Paint: Neural.love AI";
      } else if (mode === "puter") {
        this.iconImageModeStage2.textContent = "🖌️";
        this.textImageModeStage2.textContent = "Paint: In-Browser Puter";
      } else {
        this.iconImageModeStage2.textContent = "✨";
        this.textImageModeStage2.textContent = "Paint: Gemini Imagen 3";
      }
    }
  }

  updateSubtitlesUI(enabled) {
    if (this.textSubtitlesStage2 && this.iconSubtitlesStage2) {
      this.iconSubtitlesStage2.textContent = enabled ? "💬" : "🔇";
      this.textSubtitlesStage2.textContent = enabled ? "Captions: ON" : "Captions: OFF";
    }
  }

  updateVoiceoverUI(enabled) {
    // Stage 1 Button
    if (this.btnToggleVoiceoverStage1 && this.iconVoiceoverStage1 && this.textVoiceoverStage1) {
      this.iconVoiceoverStage1.textContent = enabled ? "🎙️" : "🔇";
      this.textVoiceoverStage1.textContent = enabled ? "Voiceover: ON" : "Voiceover: OFF";
      if (enabled) {
        this.btnToggleVoiceoverStage1.style.background = "rgba(16,185,129,0.15)";
        this.btnToggleVoiceoverStage1.style.color = "#34d399";
        this.btnToggleVoiceoverStage1.style.borderColor = "rgba(16,185,129,0.3)";
      } else {
        this.btnToggleVoiceoverStage1.style.background = "rgba(239,68,68,0.15)";
        this.btnToggleVoiceoverStage1.style.color = "#f87171";
        this.btnToggleVoiceoverStage1.style.borderColor = "rgba(239,68,68,0.3)";
      }
    }

    // Dim or enable Stage 1 Voice select
    if (this.selectVoice) {
      this.selectVoice.style.opacity = enabled ? "1" : "0.5";
    }
    if (this.btnAuditionSampleVoice) {
      this.btnAuditionSampleVoice.style.opacity = enabled ? "1" : "0.5";
    }

    // Stage 2 Button
    if (this.textVoiceoverStage2 && this.iconVoiceoverStage2) {
      this.iconVoiceoverStage2.textContent = enabled ? "🎙️" : "🔇";
      this.textVoiceoverStage2.textContent = enabled ? "Voiceover: ON" : "Voiceover: OFF";
      if (this.btnToggleVoiceoverStage2) {
        if (enabled) {
          this.btnToggleVoiceoverStage2.style.borderColor = "rgba(16,185,129,0.4)";
          this.btnToggleVoiceoverStage2.style.color = "#34d399";
        } else {
          this.btnToggleVoiceoverStage2.style.borderColor = "rgba(239,68,68,0.4)";
          this.btnToggleVoiceoverStage2.style.color = "#f87171";
        }
      }
    }
  }

  updateMultivoiceUI(enabled) {
    if (this.btnToggleMultivoiceStage1) {
      if (this.iconMultivoiceStage1) this.iconMultivoiceStage1.textContent = enabled ? "🎭" : "🎙️";
      if (this.textMultivoiceStage1) this.textMultivoiceStage1.textContent = enabled ? "Multi-Voice: ON" : "Multi-Voice: OFF";
      if (enabled) {
        this.btnToggleMultivoiceStage1.style.background = "rgba(139,92,246,0.18)";
        this.btnToggleMultivoiceStage1.style.color = "#c4b5fd";
        this.btnToggleMultivoiceStage1.style.borderColor = "rgba(139,92,246,0.4)";
      } else {
        this.btnToggleMultivoiceStage1.style.background = "rgba(255,255,255,0.05)";
        this.btnToggleMultivoiceStage1.style.color = "var(--text-muted)";
        this.btnToggleMultivoiceStage1.style.borderColor = "rgba(255,255,255,0.1)";
      }
    }

    if (this.btnToggleMultivoiceStage2) {
      if (this.iconMultivoiceStage2) this.iconMultivoiceStage2.textContent = enabled ? "🎭" : "🎙️";
      if (this.textMultivoiceStage2) this.textMultivoiceStage2.textContent = enabled ? "Multi-Voice: ON" : "Multi-Voice: OFF";
      if (enabled) {
        this.btnToggleMultivoiceStage2.style.borderColor = "rgba(139,92,246,0.45)";
        this.btnToggleMultivoiceStage2.style.color = "#c4b5fd";
      } else {
        this.btnToggleMultivoiceStage2.style.borderColor = "rgba(255,255,255,0.12)";
        this.btnToggleMultivoiceStage2.style.color = "var(--text-muted)";
      }
    }

    if (this.characterVoiceCastingBar) {
      this.characterVoiceCastingBar.style.display = enabled ? "block" : "none";
    }
  }

  renderCharacterVoiceCasting() {
    if (!this.characterVoiceCastingBar || !this.characterVoicesList) return;
    if (!this.currentProject) return;

    const isEnabled = this.currentProject.enable_multivoice !== false;
    this.characterVoiceCastingBar.style.display = isEnabled ? "block" : "none";
    if (!isEnabled) return;

    const voicesMap = this.currentProject.character_voices || {};
    const charNames = Object.keys(voicesMap);

    if (charNames.length === 0) {
      voicesMap["Narrator"] = this.currentProject.voice || "vi-VN-HoaiMyNeural-story";
      charNames.push("Narrator");
    }

    this.characterVoicesList.innerHTML = "";
    const allVoices = this.config?.voices || [];

    charNames.forEach((charName) => {
      const currentVoice = voicesMap[charName];
      const card = document.createElement("div");
      card.className = "character-voice-card";

      const isNarrator = charName.toLowerCase() in { "narrator": 1, "người kể chuyện": 1 };
      const icon = isNarrator ? "🎙️" : "🎭";

      let optionsHtml = "";
      allVoices.forEach(v => {
        const isSelected = v.id === currentVoice ? "selected" : "";
        optionsHtml += `<option value="${v.id}" ${isSelected}>${v.name}</option>`;
      });

      card.innerHTML = `
        <div class="char-voice-info" title="${charName}">
          <span>${icon}</span>
          <span class="char-voice-name">${charName}</span>
        </div>
        <select class="char-voice-select styled-select" data-char="${encodeURIComponent(charName)}">
          ${optionsHtml}
        </select>
        <button type="button" class="glass-btn secondary-btn char-audition-btn" data-char="${encodeURIComponent(charName)}" title="Audition this character's voice">
          <span>🔊</span>
        </button>
      `;

      const sel = card.querySelector(".char-voice-select");
      sel.addEventListener("change", async (e) => {
        const newVoiceId = e.target.value;
        try {
          const resp = await fetch(`/api/projects/${this.currentProject.id}/set-character-voice`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ character_name: charName, voice_id: newVoiceId })
          });
          if (resp.ok) {
            const data = await resp.json();
            if (data.project) {
              this.currentProject = data.project;
            }
            if (isNarrator) {
              this.currentProject.voice = newVoiceId;
              if (this.selectVoiceStage2) this.selectVoiceStage2.value = newVoiceId;
            }
            this.showToast(`🎭 ${charName}: assigned voice "${newVoiceId}"`);
          }
        } catch (err) {
          this.showToast("Failed to update voice: " + err.message, true);
        }
      });

      const btnAud = card.querySelector(".char-audition-btn");
      btnAud.addEventListener("click", () => {
        const voiceId = sel.value;
        this.playCharacterVoiceAudition(voiceId, charName);
      });

      this.characterVoicesList.appendChild(card);
    });
  }

  async playCharacterVoiceAudition(voiceId, charName) {
    if (!this.audioAuditionPlayer) return;
    const curProvider = this.selectAiProvider?.value || "gemini";
    const curKey = this.getEffectiveApiKey(curProvider);
    const selectedLang = this.currentProject?.language || (this.selectLanguage ? this.selectLanguage.value : "vi");

    this.showToast(`🎙️ Auditioning voice for [${charName}]... ⏳`);
    try {
      const resp = await fetch("/api/audition-voice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          voice: voiceId,
          language: selectedLang,
          api_key: curKey
        })
      });
      if (!resp.ok) throw new Error("Audition request failed");
      const data = await resp.json();
      if (data.audio_url) {
        this.audioAuditionPlayer.src = `${data.audio_url}?t=${Date.now()}`;
        this.audioAuditionPlayer.volume = 1.0;
        this.audioAuditionPlayer.muted = false;
        await this.audioAuditionPlayer.play();
        this.showToast(`🔊 Playing voice sample for [${charName}]`);
      }
    } catch (e) {
      this.showToast("Audition error: " + e.message, true);
    }
  }

  async revoiceSceneAudio(sceneIdx, btn = null) {
    if (!this.currentProject) return;
    const originalText = btn ? btn.innerHTML : "";
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<span>⏳ Narrating...</span>`;
    }
    this.showToast(`🎙️ Re-voicing Scene ${sceneIdx + 1} with assigned character voices... ⏳`);
    try {
      const resp = await fetch(`/api/projects/${this.currentProject.id}/regenerate-audio/${sceneIdx}`, {
        method: "POST"
      });
      if (resp.ok) {
        const updatedProj = await resp.json();
        if (updatedProj && updatedProj.scenes) {
          this.currentProject = updatedProj;
          this.saveActiveProjectState();
          this.renderStoryboardView();
          this.showToast(`✅ Scene ${sceneIdx + 1} audio re-synthesized successfully! 🎙️`);
        }
      } else {
        const err = await AniStoryApp.parseErrorResponse(resp, "Audio synthesis failed");
        this.showToast(err, true);
      }
    } catch (err) {
      this.showToast("Audio error: " + err.message, true);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = originalText;
      }
    }
  }

  updateAutoPaintUI(enabled) {
    if (this.iconAutoPaint) this.iconAutoPaint.textContent = enabled ? "🎨" : "🚫";
    if (this.textAutoPaint) this.textAutoPaint.textContent = enabled ? "Auto-Paint: ON" : "Auto-Paint: OFF";
    if (this.btnToggleAutoPaint) {
      this.btnToggleAutoPaint.style.borderColor = enabled ? "rgba(16, 185, 129, 0.4)" : "rgba(239, 68, 68, 0.3)";
      this.btnToggleAutoPaint.style.color = enabled ? "#34d399" : "var(--text-muted)";
    }
    if (this.checkSettingsAutoPaint) {
      this.checkSettingsAutoPaint.checked = enabled;
    }
  }

  /** Returns true when the Scenes Count selector is set to "Auto (Agent Decides)". */
  isAutoSceneCount() {
    return !this.selectSceneCount || this.selectSceneCount.value === "auto";
  }

  /**
   * Client-side estimate of the optimal scene count (mirrors ScriptAgent.estimate_optimal_scene_count).
   * Used only for the copy-to-Gemini prompt skeleton; the backend agent decides the final count.
   */
  estimateAutoSceneCount(idea, targetDuration = 0) {
    if (targetDuration && targetDuration > 0) {
      return Math.max(3, Math.min(16, Math.round(targetDuration / 8)));
    }
    const clean = (idea || "").trim();
    if (!clean) return 4;
    const headers = clean.match(/(?:^|\n)\s*(?:Scene|Cảnh|Phân cảnh)\s*\d+/gi) || [];
    if (headers.length >= 2) return Math.max(2, Math.min(24, headers.length));
    const wordCount = clean.split(/\s+/).filter(Boolean).length;
    const paragraphs = clean.split(/\n\s*\n/).filter(p => p.trim().length > 10);
    const sentences = clean.split(/(?<=[.!?…])\s+|\n+/).filter(s => s.trim().length > 8);
    const dialogues = clean.match(/(?:^|\n)\s*[–\-—]\s*[^\n]+|["“][^"”\n]{4,}["”]/g) || [];
    if (wordCount <= 25 && dialogues.length <= 1) return 4;
    if (wordCount <= 45 && dialogues.length <= 2) return 5;
    const est = Math.max(
      4,
      Math.round(wordCount / 20),
      Math.round(sentences.length * 0.75),
      dialogues.length + 2,
      paragraphs.length >= 3 ? paragraphs.length + 1 : 4
    );
    return Math.max(4, Math.min(16, est));
  }

  /** Human-readable scene count label for toasts. */
  getSceneCountLabel() {
    if (this.isAutoSceneCount()) return "an auto-determined number of scenes 🤖";
    const n = parseInt(this.selectSceneCount.value, 10) || 4;
    return `${n} scene${n === 1 ? "" : "s"}`;
  }

  buildGeminiPrompt() {
    const idea = this.inputIdeaPrompt?.value?.trim() || "A humble, gentle youth protected by a magical golden carp";
    const isAutoScenes = this.isAutoSceneCount();
    const numScenes = isAutoScenes
      ? this.estimateAutoSceneCount(idea)
      : (parseInt(this.selectSceneCount.value, 10) || 4);
    const minAuto = Math.max(3, numScenes - 1);
    const maxAuto = Math.min(20, numScenes + 2);
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
    const cameraProseMap = {
      zoom_in: "The camera executes a smooth slow dolly push-in toward the subject at eye level with fluid stabilization.",
      zoom_out: "The camera smoothly dollies out with a steady pedestal pull-back, revealing the expansive atmospheric environment.",
      pan_left: "The camera performs a graceful horizontal tracking pan to the left, following the subject's eyeline.",
      pan_right: "The camera glides in a smooth cinematic tracking pan to the right with fluid stabilization.",
      subtle_drift: "A steady locked-off medium shot with subtle organic handheld drift and shallow depth of field."
    };
    const scenesSkeleton = [];
    for (let i = 1; i <= numScenes; i++) {
      const motion = motionCycles[(i - 1) % motionCycles.length];
      const camSentence = cameraProseMap[motion] || cameraProseMap.zoom_in;
      const dialSample = isVi
        ? `Character says in a clear voice: \\"Lời thoại cảnh ${i}\\" (no subtitles)`
        : `Character says in a calm voice: \\"Dialogue line for scene ${i}\\" (no subtitles)`;
      scenesSkeleton.push(`    {
      "scene_number": ${i},
      "title": "Scene ${i} Title in ${langStr}",
      "archetype": "Establishing Shot / Action Beat / Climax",
      "visual_prompt": "Ultra-detailed static visual image description for an AI artist in ${styleName}: frozen frame composition, character visual anchors (hair, outfit, features), environment, color palette, lighting, ${aspectRatio} cinematic framing. (NO timing, NO camera moves, NO speech bubbles)",
      "acting_prompt": "Medium wide shot of character in setting. ${camSentence} 0-3s: Initial measured movement starting from keyframe pose as ambient wind stirs clothing. 3-6s: Core emotional performance beat / ${dialSample}. 6-8s: The character takes a steady breath as the scene holds composition. Atmospheric volumetric lighting, 35mm depth of field.\\n\\nAudio: natural atmospheric ambient soundscape, gentle ambient breeze, no background music.\\nSFX: subtle realistic footsteps, cloth movement.\\nNegative: subtitles, captions, watermark, text overlay, distorted anatomy, morphing limbs, extra fingers, jittery motion, blurry faces.",
      "narration": "Story-driven voiceover narration in ${langStr} that directly narrates the plot action, character interaction, and key dialogue/punchline of Scene ${i} (~${targetWords} words)",
      "camera_motion": "${motion}"
    }`);
    }

    return `Please act as an award-winning animation director at Pixar and Studio Ghibli.
Create a rich, emotionally captivating animated short film screenplay based on this premise:
Idea: "${idea}"

Film Specifications:
${isAutoScenes
  ? `- Number of Scenes: AUTO — YOU decide the optimal number of scenes (recommended ${minAuto} to ${maxAuto}) based on the story's natural plot beats, setting changes, dialogue exchanges, and final twist/punchline. Give each distinct beat its own 8-second scene; never cram multiple beats into one scene. (The skeleton below shows ${numScenes} scenes as an example — add or remove scenes as the story requires.)`
  : `- Number of Scenes: EXACTLY ${numScenes} SCENES (Must have all scenes 1 through ${numScenes}).`}
- Target Total Duration: ${targetDuration} seconds (~${targetSceneSec} seconds per scene).
- Language: Titles and Narration MUST be written in ${langStr}.
- Visual Art Style: ${styleName}.
- Framing: ${aspectRatio} cinematic aspect ratio for all visual prompts.
- Target Audience: ${audience}.
- Narration Pacing: Approximately ${targetWords} words per scene in ${langStr}.

CRITICAL INSTRUCTION 1 - VOICEOVER NARRATION MUST TIE DIRECTLY TO THE STORY:
- "narration" is the primary storytelling audio and subtitle track of the film.
- Every scene's "narration" MUST directly narrate the concrete plot event, character action, and emotional progression happening in that exact scene.
- When read sequentially from Scene 1 to Scene ${numScenes}, "narration" MUST tell the complete, coherent story from start to finish.
- If the story includes key character dialogue, questions, reveals, or a climactic punchline, "narration" MUST explicitly include/quote those key lines so the listener hears the full story and punchline—never replace key dialogue with vague third-person meta-summaries or disconnected scenery fragments.

CRITICAL INSTRUCTION 2 - SEPARATE PROMPTS FOR IMAGE & VIDEO:
Every scene MUST have TWO SEPARATE, DISTINCT prompts:
1. "visual_prompt" (STILL IMAGE PROMPT for Midjourney / Google Imagen 3 / Puter):
   - Detailed visual description of the frozen single frame in ${styleName} art style.
   - Describe character visual features & outfit consistently, environment setting, color palette, lighting atmosphere, and composition.
   - Do NOT include time ranges (like 0-3s), camera moves, speech text, or negative prompts.
2. "acting_prompt" (PROFESSIONAL CINEMATIC VIDEO PROMPT for Google Flow / Veo 3 / Kling / Sora):
   - Natural director-grade cinematic prose (90-140 words) in ENGLISH only.
   - Dedicated camera sentence (e.g. "The camera executes a smooth slow dolly push-in..."), NEVER "Camera: zoom_in".
   - Grounded, physically reasonable 8-second motion across 3 beats (0-3s initiation, 3-6s core action / concise dialogue, 6-8s steady landing).
   - Dialogue under 5 words: Character says in a [tone] voice: "..." (no subtitles).
   - Complete Audio, SFX, and Negative prompt block for Veo 3.
   - "visual_prompt" and "acting_prompt" MUST NOT be identical!

Return ONLY valid JSON matching this exact structure:
{
  "title": "Creative Film Title in ${langStr}",
  "logline": "1-sentence synopsis in ${langStr}",
  "characters": "Protagonist: [Name & visual traits] | Companion: [Name & visual traits]",
  "scenes": [
${scenesSkeleton.join(",\n")}
  ]
}

${isAutoScenes
  ? `CRITICAL: Choose the scene count that best fits the story (${minAuto}-${maxAuto} recommended), number scenes sequentially from 1, and make sure the final scene delivers the ending/punchline. Return raw valid JSON only.`
  : `CRITICAL: You MUST include exactly ${numScenes} scenes in the "scenes" array. Do not stop at 4. Return raw valid JSON only.`}`;
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
    const selected = currentSelected || savedModel || this.selectAiModel.value || (provider === "gemini_cookie" ? "gemini-flash-advanced" : "gemini-2.5-flash");

    if (provider !== "gemini" && provider !== "gemini_cookie") return;

    this.selectAiModel.innerHTML = "";

    const apiModels = (data && data.api_models && data.api_models.length > 0) ? data.api_models : [
      { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash", badge: "✨ Recommended (~2s)" },
      { id: "gemini-2.0-flash", name: "Gemini 2.0 Flash", badge: "⚡ Ultra Fast (~1.5s)" },
      { id: "gemini-2.0-flash-lite", name: "Gemini 2.0 Flash-Lite", badge: "💨 Sub-Second" },
      { id: "gemini-2.5-pro", name: "Gemini 2.5 Pro", badge: "🧠 Deep Reasoning (~30s)" },
      { id: "gemini-1.5-flash", name: "Gemini 1.5 Flash", badge: "⚡ Standard Flash" },
      { id: "gemini-1.5-pro", name: "Gemini 1.5 Pro", badge: "📚 Long Context" }
    ];

    const cookieModels = (data && data.cookie_models && data.cookie_models.length > 0) ? data.cookie_models : [
      { id: "gemini-flash-advanced", name: "Gemini 2.0 Flash Advanced (Web Cookie)", badge: "⚡ Ultra Fast (~3s)" },
      { id: "gemini-pro-advanced", name: "Gemini 2.5 Pro Advanced (Web Cookie)", badge: "🧠 Deep Reasoning (~35s)" },
      { id: "gemini-flash", name: "Gemini Flash (Standard Web)", badge: "💨 Fast Web (~3s)" },
      { id: "gemini-pro", name: "Gemini Pro (Standard Web)", badge: "🍪 Web Standard" },
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
        this.selectAiModel.value = "gemini-flash-advanced";
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
    const groupLabels = {
      vn_neural: "🇻🇳 Giọng Đọc Việt Nam Chuyên Biệt (14 Giọng)",
      vn_gemini: "✨ Google Gemini Multimodal (10 Giọng Tiếng Việt)",
      vn_gtts: "🌐 Google Voice VN (2 Giọng)",
      intl: "🌍 Giọng Quốc Tế (International)"
    };
    const savedVoice = localStorage.getItem("anistory_cfg_voice");

    const populateSelect = (selectEl, selectedId) => {
      if (!selectEl) return;
      selectEl.innerHTML = "";
      const groups = {};
      voices.forEach(v => {
        const gKey = v.group || (v.id.startsWith("vi-") ? "vn_neural" : (v.id.startsWith("gemini-") ? "vn_gemini" : (v.id.startsWith("gtts-vi") ? "vn_gtts" : "intl")));
        if (!groups[gKey]) groups[gKey] = [];
        groups[gKey].push(v);
      });

      ["vn_neural", "vn_gemini", "vn_gtts", "intl"].forEach(gKey => {
        const list = groups[gKey];
        if (!list || list.length === 0) return;
        const optgroup = document.createElement("optgroup");
        optgroup.label = groupLabels[gKey] || gKey;
        list.forEach(v => {
          const opt = document.createElement("option");
          opt.value = v.id;
          opt.textContent = `${v.name} (${v.gender})`;
          if (selectedId ? (v.id === selectedId) : (v.id === "vi-VN-HoaiMyNeural" || v.id === "gemini-Aoede")) {
            opt.selected = true;
          }
          optgroup.appendChild(opt);
        });
        selectEl.appendChild(optgroup);
      });
    };

    populateSelect(this.selectVoice, savedVoice);
    populateSelect(this.selectVoiceStage2, this.currentProject?.voice || savedVoice);
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
    let elapsedSec = 0;
    this.btnGenerateStoryboard.innerHTML = `
      <span class="btn-text">Brainstorming Storyboard... (0s)</span>
      <span class="btn-arrow">⚡</span>
    `;

    const timerInterval = setInterval(() => {
      elapsedSec++;
      if (!this.btnGenerateStoryboard || !this.btnGenerateStoryboard.disabled) {
        clearInterval(timerInterval);
        return;
      }
      let statusStage = "Brainstorming Storyboard";
      let icon = "⚡";
      if (elapsedSec > 8) {
        statusStage = "Crafting Scene Beats & Acting Prompts";
        icon = "🎬";
      } else if (elapsedSec > 3) {
        statusStage = "Developing Characters & Dialogue";
        icon = "✨";
      }
      this.btnGenerateStoryboard.innerHTML = `
        <span class="btn-text">${statusStage}... (${elapsedSec}s)</span>
        <span class="btn-arrow">${icon}</span>
      `;
    }, 1000);

    try {
      const provider = this.selectAiProvider ? this.selectAiProvider.value : "gemini";
      const model = this.selectAiModel ? this.selectAiModel.value : "";
      let apiKey = this.getEffectiveApiKey(provider);

      if (provider === "gemini_cookie" && !apiKey) {
        clearInterval(timerInterval);
        this.showToast("Please paste your Gemini __Secure-1PSID cookie in Settings ⚙️ first! 🍪", true);
        this.btnGenerateStoryboard.disabled = false;
        this.btnGenerateStoryboard.innerHTML = `<span class="btn-text">Generate Storyboard</span><span class="btn-arrow">✨</span>`;
        return;
      }
      const isAutoScenes = this.isAutoSceneCount();
      const durVal = this.selectTargetDuration ? this.selectTargetDuration.value : "auto_acting";
      const fixedDuration = (durVal === "auto_acting" || !durVal) ? null : parseInt(durVal, 10);
      // num_scenes = 0 tells the backend agent to determine the optimal scene count
      const numScenes = isAutoScenes ? 0 : (parseInt(this.selectSceneCount.value, 10) || 4);
      const targetDuration = fixedDuration || (isAutoScenes ? null : numScenes * 8);
      const aspectRatio = this.selectAspectRatio ? this.selectAspectRatio.value : "16:9";
      const projectTitle = this.inputProjectTitle ? this.inputProjectTitle.value.trim() : "";

      // Persist active configuration choices
      localStorage.setItem("anistory_cfg_art_style", this.selectedStyleKey);
      if (this.selectVoice) localStorage.setItem("anistory_cfg_voice", this.selectVoice.value);
      if (this.selectSceneCount) localStorage.setItem("anistory_cfg_scene_count", this.selectSceneCount.value);
      if (this.selectTargetDuration) localStorage.setItem("anistory_cfg_target_duration", this.selectTargetDuration.value);
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
        video_mode: "acting",
        aspect_ratio: aspectRatio,
        language: this.selectLanguage.value,
        audience: this.selectAudience.value,
        ai_provider: provider,
        ai_model: model,
        api_key: apiKey,
        image_mode: this.imageMode || "server",
        enable_voiceover: this.enableVoiceover !== false,
        enable_subtitles: this.enableSubtitles !== false,
        enable_multivoice: this.enableMultivoice !== false
      };

      const resp = await fetch("/api/create-story", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!resp.ok) {
        const msg = await AniStoryApp.parseErrorResponse(resp, "Failed to create story");
        throw new Error(msg);
      }

      this.currentProject = await resp.json();
      this.saveActiveProjectState();
      this.renderStoryboardView();
      this.switchStage(2);
      const titleDisplay = this.currentProject.title ? `"${this.currentProject.title}"` : `${this.currentProject.scenes.length} scenes`;
      this.showToast(`✨ Generated ${titleDisplay} (${this.currentProject.scenes.length} scenes in ${elapsedSec}s)! Review your script, then click '🎨 Paint All' to paint. 🎬`);
      if (localStorage.getItem("anistory_autopaint") === "true") {
        this.autoGenerateMissingSceneImages();
      }
    } catch (e) {
      console.error(e);
      this.showToast(e.message, true);
    } finally {
      clearInterval(timerInterval);
      this.btnGenerateStoryboard.disabled = false;
      this.btnGenerateStoryboard.innerHTML = `
        <span class="btn-glow-layer"></span>
        <span class="btn-text">Generate Storyboard with AI</span>
        <span class="btn-arrow">✨</span>
      `;
    }
  }

  handleAddAdImages(files) {
    if (!files || !files.length) return;
    const validImages = files.filter(f => f.type.startsWith("image/"));
    if (!validImages.length) {
      this.showToast("Please select valid image files (PNG, JPG, WEBP).", true);
      return;
    }
    validImages.forEach(f => {
      const exists = this.adUploadedFiles.some(existing => existing.name === f.name && existing.size === f.size);
      if (!exists) {
        this.adUploadedFiles.push(f);
      }
    });
    this.renderAdImagesPreviews();
    this.showToast(`📸 Added ${validImages.length} product photo(s)! (${this.adUploadedFiles.length} total)`);
  }

  renderAdImagesPreviews() {
    if (!this.adImagesPreviewContainer || !this.adImagesCountBadge) return;
    const count = this.adUploadedFiles.length;
    this.adImagesCountBadge.textContent = `${count} photo${count === 1 ? '' : 's'} added`;

    if (count === 0) {
      this.adImagesPreviewContainer.style.display = "none";
      this.adImagesPreviewContainer.innerHTML = "";
      return;
    }

    this.adImagesPreviewContainer.style.display = "grid";
    this.adImagesPreviewContainer.innerHTML = "";

    this.adUploadedFiles.forEach((file, idx) => {
      const card = document.createElement("div");
      card.className = "ad-image-card";

      const thumbWrap = document.createElement("div");
      thumbWrap.className = "ad-image-thumb-wrap";

      const img = document.createElement("img");
      img.className = "ad-image-thumb";
      img.alt = file.name;

      const reader = new FileReader();
      reader.onload = (e) => {
        img.src = e.target.result;
      };
      reader.readAsDataURL(file);

      const badge = document.createElement("span");
      badge.className = "ad-image-badge";
      badge.textContent = idx === 0 ? "Hero (Sc 1)" : `Sc ${idx + 1}`;

      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "ad-image-delete-btn";
      deleteBtn.innerHTML = "×";
      deleteBtn.title = "Remove this photo";
      deleteBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this.adUploadedFiles.splice(idx, 1);
        this.renderAdImagesPreviews();
      });

      thumbWrap.appendChild(img);
      thumbWrap.appendChild(badge);
      thumbWrap.appendChild(deleteBtn);

      const footer = document.createElement("div");
      footer.className = "ad-image-footer";
      const sizeKb = Math.round(file.size / 1024);
      footer.textContent = `${file.name.slice(0, 14)} (${sizeKb}KB)`;

      card.appendChild(thumbWrap);
      card.appendChild(footer);
      this.adImagesPreviewContainer.appendChild(card);
    });
  }

  async handleGenerateAdvertisementVideo() {
    const productName = this.inputAdProductName ? this.inputAdProductName.value.trim() : "";
    const description = this.textareaAdDesc ? this.textareaAdDesc.value.trim() : "";

    if (!productName) {
      this.showToast("Please enter the Product / Goods Name! 🏷️", true);
      this.inputAdProductName?.focus();
      return;
    }
    if (!description) {
      this.showToast("Please enter a short product description or key selling points! 📝", true);
      this.textareaAdDesc?.focus();
      return;
    }

    if (!this.btnGenerateAdVideo) return;
    this.btnGenerateAdVideo.disabled = true;
    let elapsedSec = 0;
    this.btnGenerateAdVideo.innerHTML = `
      <span class="btn-text">Writing Commercial Script... (0s)</span>
      <span class="btn-arrow">⚡</span>
    `;

    const timerInterval = setInterval(() => {
      elapsedSec++;
      if (!this.btnGenerateAdVideo || !this.btnGenerateAdVideo.disabled) {
        clearInterval(timerInterval);
        return;
      }
      let statusStage = "Writing Commercial Script";
      let icon = "⚡";
      if (elapsedSec > 8) {
        statusStage = "Formatting Goods Keyframes & Specs";
        icon = "📸";
      } else if (elapsedSec > 4) {
        statusStage = "Composing High-Converting Pitch";
        icon = "🎬";
      }
      this.btnGenerateAdVideo.innerHTML = `
        <span class="btn-text">${statusStage}... (${elapsedSec}s)</span>
        <span class="btn-arrow">${icon}</span>
      `;
    }, 1000);

    try {
      const provider = this.selectAiProvider ? this.selectAiProvider.value : "gemini";
      const model = this.selectAiModel ? this.selectAiModel.value : "";
      const apiKey = this.getEffectiveApiKey(provider);

      const isAutoScenes = this.isAutoSceneCount();
      const durVal = this.selectTargetDuration ? this.selectTargetDuration.value : "auto_acting";
      const fixedDuration = (durVal === "auto_acting" || !durVal) ? null : parseInt(durVal, 10);
      const numScenes = isAutoScenes ? 0 : (parseInt(this.selectSceneCount.value, 10) || 4);
      const targetDuration = fixedDuration || (isAutoScenes ? 0 : numScenes * 8);
      const aspectRatio = this.selectAspectRatio ? this.selectAspectRatio.value : "16:9";
      const voice = this.selectVoice ? this.selectVoice.value : "en-US-ChristopherNeural";
      const language = this.selectLanguage ? this.selectLanguage.value : "en";
      const brand = this.inputAdBrand ? this.inputAdBrand.value.trim() : "";
      const specs = this.textareaAdSpecs ? this.textareaAdSpecs.value.trim() : "";
      const adStyle = this.selectAdStyle ? this.selectAdStyle.value : "cinematic_commercial";
      const audience = this.selectAdAudience ? this.selectAdAudience.value : "General";
      const offer = this.inputAdOffer ? this.inputAdOffer.value.trim() : "";
      const cta = this.inputAdCTA ? this.inputAdCTA.value.trim() : "";

      const formData = new FormData();
      formData.append("product_name", productName);
      formData.append("description", description);
      formData.append("brand", brand);
      formData.append("specs", specs);
      formData.append("target_audience", audience);
      formData.append("ad_style", adStyle);
      formData.append("pricing_offer", offer);
      formData.append("call_to_action", cta);
      formData.append("num_scenes", numScenes.toString());
      formData.append("target_duration", targetDuration.toString());
      formData.append("art_style", this.selectedStyleKey || "realistic");
      formData.append("voice", voice);
      formData.append("aspect_ratio", aspectRatio);
      formData.append("language", language);
      formData.append("ai_provider", provider);
      if (model) formData.append("ai_model", model);
      if (apiKey) formData.append("api_key", apiKey);
      formData.append("image_mode", this.imageMode || "gemini");
      formData.append("video_mode", "acting");
      formData.append("enable_voiceover", (this.enableVoiceover !== false).toString());
      formData.append("enable_subtitles", (this.enableSubtitles !== false).toString());

      // Append uploaded product photos
      this.adUploadedFiles.forEach((file) => {
        formData.append("images", file, file.name);
      });

      const resp = await fetch("/api/advertisement/create", {
        method: "POST",
        body: formData
      });

      if (!resp.ok) {
        const msg = await AniStoryApp.parseErrorResponse(resp, "Failed to create advertisement video");
        throw new Error(msg);
      }

      this.currentProject = await resp.json();
      this.saveActiveProjectState();
      this.renderStoryboardView();
      this.switchStage(2);
      const photoMsg = this.adUploadedFiles.length > 0
        ? ` with ${this.adUploadedFiles.length} product photos ready`
        : "";
      this.showToast(`🛍️ Generated Commercial for "${productName}" (${this.currentProject.scenes.length} scenes${photoMsg})! Click '🎬 Render Film' to produce video.`);
    } catch (e) {
      console.error(e);
      this.showToast(e.message, true);
    } finally {
      clearInterval(timerInterval);
      this.btnGenerateAdVideo.disabled = false;
      this.btnGenerateAdVideo.innerHTML = `
        <span class="btn-glow-layer"></span>
        <span class="btn-text">Generate Advertisement Video</span>
        <span class="btn-arrow">🛍️</span>
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
          image_mode: this.imageMode || "server",
          enable_voiceover: this.enableVoiceover !== false,
          enable_subtitles: this.enableSubtitles !== false,
          enable_multivoice: this.enableMultivoice !== false
        })
      });

      if (!resp.ok) {
        const msg = await AniStoryApp.parseErrorResponse(resp, "Failed to parse storyboard");
        throw new Error(msg);
      }

      this.currentProject = await resp.json();
      this.saveActiveProjectState();
      if (this.modalImport) this.modalImport.classList.remove("active");
      if (this.inputImportText) this.inputImportText.value = "";
      if (this.inputDirectPasteText) this.inputDirectPasteText.value = "";
      this.renderStoryboardView();
      this.switchStage(2);
      this.showToast("AI Storyboard loaded! Review your scenes, then click '🎨 Paint All' to paint. 🎬");
      if (localStorage.getItem("anistory_autopaint") === "true") {
        this.autoGenerateMissingSceneImages();
      }
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

    return this.getPlaceholderSvg(scene?.scene_number || idx + 1);
  }

  getPlaceholderSvg(sceneNumber, text = "Ready for Painting • Click AI Paint or Paint All") {
    const cleanText = (text || "").replace(/['"<>]/g, "");
    const rawSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
      <rect width="100%" height="100%" fill="#131722"/>
      <circle cx="640" cy="300" r="60" fill="#1e293b" stroke="#334155" stroke-width="2"/>
      <text x="640" y="315" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" font-size="40" text-anchor="middle">🎨</text>
      <text x="640" y="415" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" font-size="22" fill="#f1f5f9" text-anchor="middle" font-weight="600">Scene ${sceneNumber}</text>
      <text x="640" y="455" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" font-size="16" fill="#94a3b8" text-anchor="middle">${cleanText}</text>
    </svg>`;
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(rawSvg).replace(/'/g, "%27");
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

    if (this.badgeStoryboardAdMode) {
      if (this.currentProject.project_type === "advertisement") {
        this.badgeStoryboardAdMode.style.display = "inline-flex";
      } else {
        this.badgeStoryboardAdMode.style.display = "none";
      }
    }

    this.updateSubtitlesUI(this.currentProject.enable_subtitles !== false);
    this.updateVoiceoverUI(this.currentProject.enable_voiceover !== false);
    this.updateMultivoiceUI(this.currentProject.enable_multivoice !== false);
    this.renderCharacterVoiceCasting();
    if (this.selectVoiceStage2 && this.currentProject.voice) {
      this.selectVoiceStage2.value = this.currentProject.voice;
    }

    const scenes = this.currentProject.scenes || [];
    this.renderSceneQuickJumpRibbon(scenes);
    scenes.forEach((scene, idx) => {
      const card = document.createElement("div");
      card.className = "scene-card";
      card.id = `sceneCard_${idx}`;
      card.dataset.index = idx;

      // Image & Video source with URL-safe encoding and clean paths
      const cleanImgPath = scene.image_path ? scene.image_path.replace(/\\/g, "/") : "";
      const hasSavedImage = Boolean(cleanImgPath);
      const imgSrc = hasSavedImage ? `/media/${encodeURI(cleanImgPath)}?t=${Date.now()}` : "";
      const cleanVideoPath = scene.video_path ? scene.video_path.replace(/\\/g, "/") : "";
      const hasVideo = Boolean(cleanVideoPath);
      const videoSrc = hasVideo ? `/media/${encodeURI(cleanVideoPath)}?t=${Date.now()}` : "";

      // Ensure visual_prompt (for image) and acting_prompt (for video) are distinctly separated
      let visPrompt = (scene.visual_prompt || "").trim();
      let actPrompt = (scene.acting_prompt || "").trim();

      const cameraProseMap = {
        zoom_in: "The camera executes a smooth slow dolly push-in toward the subject at eye level with fluid stabilization.",
        zoom_out: "The camera smoothly dollies out with a steady pedestal pull-back, revealing the expansive atmospheric environment.",
        pan_left: "The camera performs a graceful horizontal tracking pan to the left, smoothly following the subject's eyeline.",
        pan_right: "The camera glides in a smooth cinematic tracking pan to the right with fluid stabilization.",
        subtle_drift: "A steady locked-off camera with subtle organic handheld drift and shallow depth of field."
      };
      const camMotion = scene.camera_motion || "zoom_in";
      const camSentence = cameraProseMap[camMotion] || cameraProseMap.zoom_in;

      if (!visPrompt && !actPrompt) {
        visPrompt = `${this.config?.art_styles?.[this.selectedStyleKey]?.name || "Studio Ghibli 2D"} art style. ${scene.title || "Scene " + (idx + 1)}. Cinematic composition, rich atmospheric lighting, detailed background.`;
        actPrompt = `Medium shot of character in setting. ${camSentence} 0-3s: The character initiates natural, measured movement as ambient breeze stirs clothing and hair. 3-6s: Core emotional performance beat and focused interaction with the environment. 6-8s: The character takes a steady breath as the scene holds composition. Atmospheric volumetric lighting, 35mm depth of field.\n\nAudio: natural atmospheric ambient soundscape, gentle ambient breeze, no background music.\nSFX: subtle realistic footsteps, cloth movement.\nNegative: subtitles, captions, watermark, text overlay, distorted anatomy, morphing limbs, extra fingers, jittery motion, blurry faces.`;
      } else if (!visPrompt && actPrompt) {
        visPrompt = actPrompt
          .replace(/0-3s:|3-6s:|6-8s:/gi, "")
          .replace(/(?:The\s+)?camera\s+(?:executes|performs|glides|smoothly|slowly)[^.]*\.?/gi, "")
          .replace(/Camera:[^.]*\.?/gi, "")
          .replace(/Lighting:[^.]*\.?/gi, "")
          .replace(/Negative:[^.]*\.?/gi, "")
          .replace(/Audio:[^.]*\.?/gi, "")
          .replace(/SFX:[^.]*\.?/gi, "")
          .replace(/["“][^"”]+["”]/g, "")
          .replace(/\s+/g, " ")
          .trim();
        if (!visPrompt) visPrompt = scene.title || `Scene ${idx + 1}`;
      } else if (!actPrompt && visPrompt) {
        const dialBeat = scene.narration ? `The character delivers expressive performance matching the story moment` : `The character performs a focused, deliberate interaction with the setting`;
        const hasNonAscii = /[^\x00-\x7F]/.test(visPrompt);
        const visSnippet = hasNonAscii ? "the character in the scene setting" : visPrompt.slice(0, 90).replace(/\s+\S*$/, "").replace(/\.+$/, "");
        actPrompt = `Medium shot of ${visSnippet}. ${camSentence} 0-3s: The character initiates natural, measured movement in the environment. 3-6s: ${dialBeat}, eyes steady and expressive. 6-8s: Posture settles into a calm, grounded hold as the camera stabilizes. Volumetric atmospheric lighting, 35mm depth of field.\n\nAudio: natural atmospheric ambient soundscape, gentle ambient breeze, no background music.\nSFX: subtle realistic footsteps, cloth movement.\nNegative: subtitles, captions, watermark, text overlay, distorted anatomy, morphing limbs, extra fingers, jittery motion, blurry faces.`;
      } else if (visPrompt === actPrompt) {
        if (actPrompt.includes("0-3s:") || actPrompt.toLowerCase().includes("negative:")) {
          visPrompt = actPrompt
            .replace(/0-3s:|3-6s:|6-8s:/gi, "")
            .replace(/(?:The\s+)?camera\s+(?:executes|performs|glides|smoothly|slowly)[^.]*\.?/gi, "")
            .replace(/Camera:[^.]*\.?/gi, "")
            .replace(/Lighting:[^.]*\.?/gi, "")
            .replace(/Negative:[^.]*\.?/gi, "")
            .replace(/Audio:[^.]*\.?/gi, "")
            .replace(/SFX:[^.]*\.?/gi, "")
            .replace(/["“][^"”]+["”]/g, "")
            .replace(/\s+/g, " ")
            .trim();
          if (!visPrompt) visPrompt = scene.title || `Scene ${idx + 1}`;
        } else {
          const hasNonAscii = /[^\x00-\x7F]/.test(visPrompt);
          const visSnippet = hasNonAscii ? "the character in the scene setting" : visPrompt.slice(0, 90).replace(/\s+\S*$/, "").replace(/\.+$/, "");
          actPrompt = `Medium shot of ${visSnippet}. ${camSentence} 0-3s: The character initiates natural, measured movement. 3-6s: Core emotional performance beat, interacting deliberately with the scene. 6-8s: The character settles naturally into frame with cinematic poise. Atmospheric volumetric lighting, 35mm depth of field.\n\nAudio: natural atmospheric ambient soundscape, gentle ambient breeze, no background music.\nSFX: subtle realistic footsteps, cloth movement.\nNegative: subtitles, captions, watermark, text overlay, distorted anatomy, morphing limbs, extra fingers, jittery motion, blurry faces.`;
        }
      }
      scene.visual_prompt = visPrompt;
      scene.acting_prompt = actPrompt;

      const isMultiVoiceScene = Boolean(
        this.currentProject.enable_multivoice !== false &&
        scene.dialogues &&
        scene.dialogues.length > 1
      );
      const dialogueBreakdownHtml = (isMultiVoiceScene && scene.dialogues) ? `
        <div class="scene-dialogue-breakdown">
          ${scene.dialogues.map(d => `
            <div class="dialogue-segment-row">
              <span class="dialogue-speaker-pill ${(d.speaker || '').toLowerCase() === 'narrator' ? 'narrator' : ''}">[${d.speaker || 'Narrator'}]</span>
              <span class="dialogue-text-bubble">"${d.text || ''}"</span>
            </div>
          `).join('')}
        </div>
      ` : '';

      card.innerHTML = `
        <div class="scene-card-header">
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
            <span class="scene-badge">Scene ${scene.scene_number || idx + 1}</span>
            ${scene.archetype ? `<span class="scene-badge" style="background:rgba(139,92,246,0.25); color:#c4b5fd; font-weight:600; border:1px solid rgba(139,92,246,0.4);">🎭 ${scene.archetype}</span>` : ''}
            ${isMultiVoiceScene ? `<span class="scene-badge scene-multivoice-badge" title="Multi-Voice Scene: ${scene.dialogues.length} character dialogue segments">🎭 Multi-Voice (${scene.dialogues.length})</span>` : ''}
            ${scene.is_product_photo ? `<span class="scene-badge" style="background:rgba(16,185,129,0.2); color:#6ee7b7; border:1px solid rgba(16,185,129,0.4); font-weight:600;">🛍️ Product Photo</span>` : ''}
            <span class="scene-status-pill ${hasSavedImage ? 'ready' : 'pending'}" id="sceneStatusPill_${idx}">
              ${hasSavedImage ? '✓ Ready' : '⏳ Ready to Paint'}
            </span>
            <span class="scene-status-pill ready" id="sceneVideoPill_${idx}" style="${hasVideo ? '' : 'display:none;'}">
              🎬 Video Ready
            </span>
          </div>
          <span class="scene-card-title">${scene.title || "Scene " + (idx + 1)}</span>
        </div>
        <div class="scene-preview-container">
          <div class="scene-preview-placeholder" id="scenePlaceholder_${idx}" style="${hasSavedImage ? 'display:none;' : ''}">
            <div class="placeholder-icon-circle">🎨</div>
            <div class="placeholder-scene-num">Scene ${scene.scene_number || idx + 1}</div>
            <div class="placeholder-scene-status">Ready to Paint • Click 🎨 AI Paint</div>
          </div>
          <img src="${imgSrc}" class="scene-preview-img" alt="Scene ${idx + 1} Preview" id="sceneImg_${idx}" style="${hasSavedImage ? '' : 'display:none;'}" loading="lazy">
          <video class="scene-preview-video" id="sceneVideo_${idx}" src="${videoSrc}" controls playsinline preload="metadata" style="display:none;"></video>
          <button class="scene-play-overlay-btn" id="btnPlayOverlay_${idx}" data-idx="${idx}" title="Play scene animation video" style="${hasVideo ? 'display:flex;' : 'display:none;'}">▶️</button>
          <div class="scene-img-actions">
            <button class="scene-action-pill btn-copy-image-prompt" data-idx="${idx}" title="1-Click copy Image Prompt (Midjourney / Imagen 3)">🎨 Img Prompt</button>
            <button class="scene-action-pill btn-copy-video-prompt" data-idx="${idx}" title="1-Click copy Acting Video Prompt (Veo 3 / Google Flow / Kling)">🎬 Vid Prompt</button>
            <button class="scene-action-pill btn-refine-video-prompt" data-idx="${idx}" title="Upgrade to director-grade professional cinematic video prompt" style="color:#e0e7ff; border-color:rgba(167,139,250,0.6); background:rgba(139,92,246,0.25); font-weight:600;">✨ Refine</button>
            <button class="scene-action-pill btn-reroll-img" data-idx="${idx}" title="AI Paint image for this scene">🎨 Paint</button>
            <button class="scene-action-pill btn-upload-img" data-idx="${idx}" title="Upload custom image">📁 Art</button>
            ${(this.currentProject.product_images && this.currentProject.product_images.length) ? `<button class="scene-action-pill btn-pick-product-photo" data-idx="${idx}" title="Cycle/choose from uploaded product photos" style="color:#f472b6; border-color:rgba(236,72,153,0.4);">🛍️ Photo</button>` : ''}
            <button class="scene-action-pill btn-generate-veo" data-idx="${idx}" style="color:#6ee7b7; border-color:rgba(16,185,129,0.4);" title="Auto-render acting video via Google Veo & FlowKit bridge">⚡ Veo</button>
            <button class="scene-action-pill btn-upload-acting" data-idx="${idx}" title="Upload local video clip (.mp4) as fallback">📁 Clip</button>
            <a class="scene-action-pill btn-download-scene-clip" id="btnDownloadClip_${idx}" href="/api/projects/${this.currentProject.id}/download-scene-video/${idx}" download title="Download Scene MP4" style="${hasVideo ? '' : 'display:none;'}">⬇️ MP4</a>
            <input type="file" accept="image/*" class="scene-file-input" style="display:none;" id="fileInput_${idx}">
            <input type="file" accept="video/mp4,video/*" class="scene-acting-file-input" style="display:none;" id="actingFileInput_${idx}">
          </div>
        </div>
        <div class="scene-card-body">
          <!-- Voiceover Narration -->
          <div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
              <div style="display:flex; align-items:center; gap:6px;">
                <label class="field-label" style="margin-bottom:0;">🎙️ Voiceover Narration</label>
                <button class="scene-action-pill btn-sync-scene-dialogue" data-idx="${idx}" style="padding:2px 8px; font-size:10px; height:20px; line-height:1; color:#6ee7b7; border-color:rgba(16,185,129,0.45); background:rgba(16,185,129,0.15);" title="Add/sync dialogue from story to Voiceover Narration, Image & Video Clip prompts">💬 +Dialogue</button>
                <button class="scene-action-pill btn-revoice-scene" data-idx="${idx}" style="padding:2px 8px; font-size:10px; height:20px; line-height:1; color:#c4b5fd; border-color:rgba(139,92,246,0.45); background:rgba(139,92,246,0.15);" title="Re-synthesize audio for this scene with assigned character voices">🎙️ Re-Voice</button>
                ${this.currentProject.enable_voiceover === false ? '<span class="tag-badge" style="background:rgba(239,68,68,0.15); color:#f87171; font-size:10px; padding:1px 6px;">🔇 Muted</span>' : ''}
              </div>
              <span class="narration-badge" id="badgeNarr_${idx}" style="font-size:11px; padding:2px 7px; border-radius:12px; font-weight:500;"></span>
            </div>
            <textarea class="scene-narration-input" id="narration_${idx}" placeholder="Concise voiceover narration (<= 16 words to fit 8s video)...">${scene.narration || ""}</textarea>
            ${dialogueBreakdownHtml}
          </div>

          <!-- SEPARATE PROMPT 1: Image Prompt (Still Art / Imagen 3 / Midjourney) -->
          <div class="scene-prompt-section">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
              <div style="display:flex; align-items:center; gap:6px;">
                <label class="field-label" style="margin-bottom:0;">🎨 Image Prompt <span style="font-size:10.5px; color:var(--text-muted); font-weight:normal;">(Midjourney / Imagen 3)</span></label>
                <button class="scene-action-pill btn-copy-image-prompt" data-idx="${idx}" style="padding:2px 8px; font-size:10px; height:20px; line-height:1;" title="Copy image prompt to clipboard">📋 Copy</button>
              </div>
              <span class="prompt-type-badge image-badge">🖼️ Image Art</span>
            </div>
            <textarea class="styled-input scene-visual-input" id="visual_prompt_${idx}" rows="2" style="resize:vertical; min-height:54px; font-size:11.5px; line-height:1.45; font-family:inherit;" placeholder="Detailed still illustration prompt: environment, character clothing & features, art style, framing, lighting...">${scene.visual_prompt || ""}</textarea>
          </div>

          <!-- SEPARATE PROMPT 2: Video Prompt (Acting & Motion / Veo 3 / Google Flow / Kling) -->
          <div class="scene-prompt-section">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
              <div style="display:flex; align-items:center; gap:6px;">
                <label class="field-label" style="margin-bottom:0;">🎬 Video Prompt <span style="font-size:10.5px; color:var(--text-muted); font-weight:normal;">(Veo 3 / Google Flow / Kling)</span></label>
                <button class="scene-action-pill btn-copy-video-prompt" data-idx="${idx}" style="padding:2px 8px; font-size:10px; height:20px; line-height:1;" title="Copy video acting prompt to clipboard">📋 Copy</button>
                <button class="scene-action-pill btn-refine-video-prompt" data-idx="${idx}" style="padding:2px 9px; font-size:10.5px; height:21px; line-height:1; color:#f5f3ff; background:rgba(139,92,246,0.3); border:1px solid rgba(167,139,250,0.6); font-weight:600;" title="Upgrade to director-grade professional cinematic video prompt">✨ Refine</button>
              </div>
              <span class="prompt-type-badge video-badge">⚡ 8s Video</span>
            </div>
            <textarea class="styled-input scene-acting-input" id="acting_prompt_${idx}" rows="2" style="resize:vertical; min-height:54px; font-size:11.5px; line-height:1.45; font-family:inherit;" placeholder="Director-grade cinematic video prompt: [Shot Type & Camera Move] 0-3s: Initial organic motion... 3-6s: Core performance / dialogue... 6-8s: Settle and landing. Lighting... Audio: ... SFX: ... Negative: ...">${scene.acting_prompt || ""}</textarea>
          </div>
        </div>
      `;

      // Real-time voiceover duration calculator for 8s acting video fit
      const narrTextarea = card.querySelector(`#narration_${idx}`);
      const narrBadge = card.querySelector(`#badgeNarr_${idx}`);
      const updateNarrBadge = (text) => {
        if (!narrBadge) return;
        const words = (text || "").trim().split(/\s+/).filter(Boolean).length;
        const estSec = (words / 2.2).toFixed(1);
        if (words === 0) {
          narrBadge.textContent = "0 words";
          narrBadge.style.background = "rgba(255,255,255,0.05)";
          narrBadge.style.color = "var(--text-muted)";
          narrBadge.style.border = "none";
        } else if (words <= 16) {
          narrBadge.textContent = `⏱️ ~${estSec}s (${words}w) ✅ fits 8s video`;
          narrBadge.style.background = "rgba(16,185,129,0.15)";
          narrBadge.style.color = "#34d399";
          narrBadge.style.border = "1px solid rgba(16,185,129,0.3)";
        } else if (words <= 18) {
          narrBadge.textContent = `⏱️ ~${estSec}s (${words}w) ⚠️ near 8s limit`;
          narrBadge.style.background = "rgba(245,158,11,0.15)";
          narrBadge.style.color = "#fbbf24";
          narrBadge.style.border = "1px solid rgba(245,158,11,0.3)";
        } else {
          narrBadge.textContent = `⏱️ ~${estSec}s (${words}w) ⚠️ >8s may repeat`;
          narrBadge.style.background = "rgba(239,68,68,0.15)";
          narrBadge.style.color = "#f87171";
          narrBadge.style.border = "1px solid rgba(239,68,68,0.3)";
        }
      };
      if (narrTextarea) {
        updateNarrBadge(narrTextarea.value);
        narrTextarea.addEventListener("input", (e) => updateNarrBadge(e.target.value));
      }

      // Image fallback handling
      const imgEl = card.querySelector(`#sceneImg_${idx}`);
      const placeholderEl = card.querySelector(`#scenePlaceholder_${idx}`);
      if (imgEl) {
        imgEl.addEventListener("error", () => {
          imgEl.style.display = "none";
          if (placeholderEl) placeholderEl.style.display = "flex";
        });
        imgEl.addEventListener("load", () => {
          if (imgEl.getAttribute("src")) {
            imgEl.style.display = "block";
            if (placeholderEl) placeholderEl.style.display = "none";
          }
        });
      }

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

      // Event listener for cycling/picking product photo
      const btnPickProd = card.querySelector(".btn-pick-product-photo");
      if (btnPickProd) {
        btnPickProd.addEventListener("click", () => this.cycleSceneProductPhoto(idx, btnPickProd));
      }

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

      // Event listeners for opening video modal player via thumbnail play button
      const btnOverlay = card.querySelector(`#btnPlayOverlay_${idx}`);
      if (btnOverlay) {
        btnOverlay.addEventListener("click", () => this.openSceneVideoModal(idx));
      }

      // Event listeners for copying prompts
      card.querySelectorAll(".btn-copy-image-prompt").forEach(btn => {
        btn.addEventListener("click", () => this.copySceneImagePrompt(idx));
      });
      card.querySelectorAll(".btn-copy-video-prompt").forEach(btn => {
        btn.addEventListener("click", () => this.copySceneVideoPrompt(idx));
      });
      card.querySelectorAll(".btn-copy-scene-prompt").forEach(btn => {
        btn.addEventListener("click", () => this.copySceneVideoPrompt(idx));
      });
      card.querySelectorAll(".btn-refine-video-prompt").forEach(btn => {
        btn.addEventListener("click", () => this.refineSceneVideoPrompt(idx, btn));
      });
      card.querySelectorAll(".btn-sync-scene-dialogue").forEach(btn => {
        btn.addEventListener("click", () => this.syncStoryDialogues(idx, "all", btn));
      });
      card.querySelectorAll(".btn-revoice-scene").forEach(btn => {
        btn.addEventListener("click", () => this.revoiceSceneAudio(idx, btn));
      });

      this.storyboardScenesGrid.appendChild(card);
    });
  }

  renderSceneQuickJumpRibbon(scenes) {
    const qjBar = this.sceneQuickJumpBar || document.getElementById("sceneQuickJumpBar");
    if (!qjBar) return;
    qjBar.innerHTML = "";

    if (!scenes || !scenes.length) {
      qjBar.style.display = "none";
      return;
    }
    qjBar.style.display = "flex";

    const label = document.createElement("div");
    label.className = "qj-label";
    label.innerHTML = `<span>🎞️ Jump:</span> <span class="qj-count">(${scenes.length})</span>`;
    qjBar.appendChild(label);

    const pillsWrap = document.createElement("div");
    pillsWrap.className = "qj-pills-wrap";

    scenes.forEach((sc, i) => {
      const cleanImg = sc.image_path ? sc.image_path.replace(/\\/g, "/") : "";
      const cleanVid = sc.video_path ? sc.video_path.replace(/\\/g, "/") : "";
      const hasImg = Boolean(cleanImg);
      const hasVid = Boolean(cleanVid);

      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = `quick-jump-pill ${hasVid ? 'vid-ready' : hasImg ? 'img-ready' : ''}`;
      pill.id = `qjPill_${i}`;
      pill.dataset.idx = i;
      pill.title = `Jump to Scene ${sc.scene_number || (i + 1)}: ${sc.title || ''}`;

      const icon = hasVid ? '🎬' : hasImg ? '✓' : '⏳';
      pill.innerHTML = `<span class="qj-status-icon">${icon}</span> <span class="qj-num">${sc.scene_number || (i + 1)}</span>`;

      pill.addEventListener("click", () => {
        const target = document.getElementById(`sceneCard_${i}`);
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "center" });
          target.classList.add("scene-card-highlighted");
          setTimeout(() => target.classList.remove("scene-card-highlighted"), 1800);
        }
        pillsWrap.querySelectorAll(".quick-jump-pill").forEach(p => p.classList.remove("active-jump"));
        pill.classList.add("active-jump");
      });

      pillsWrap.appendChild(pill);
    });

    qjBar.appendChild(pillsWrap);

    const topBtn = document.createElement("button");
    topBtn.type = "button";
    topBtn.className = "qj-top-btn";
    topBtn.innerHTML = `<span>⬆️ Top</span>`;
    topBtn.title = "Scroll to top of Director's Board";
    topBtn.addEventListener("click", () => {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    qjBar.appendChild(topBtn);
  }

  updateQuickJumpPill(idx, hasImg, hasVid) {
    const pill = document.getElementById(`qjPill_${idx}`);
    if (!pill) return;
    if (hasVid) {
      pill.className = "quick-jump-pill vid-ready";
      pill.innerHTML = `<span class="qj-status-icon">🎬</span> <span class="qj-num">${idx + 1}</span>`;
    } else if (hasImg) {
      pill.className = "quick-jump-pill img-ready";
      pill.innerHTML = `<span class="qj-status-icon">✓</span> <span class="qj-num">${idx + 1}</span>`;
    } else {
      pill.className = "quick-jump-pill";
      pill.innerHTML = `<span class="qj-status-icon">⏳</span> <span class="qj-num">${idx + 1}</span>`;
    }
  }

  copySceneImagePrompt(idx) {
    if (!this.currentProject || !this.currentProject.scenes || !this.currentProject.scenes[idx]) return;
    const scene = this.currentProject.scenes[idx];
    const promptText = (scene.visual_prompt || "").trim();
    if (!promptText) {
      this.showToast("Image prompt is empty!", true);
      return;
    }
    navigator.clipboard.writeText(promptText).then(() => {
      this.showToast(`🎨 Copied Scene ${idx + 1} Image Prompt (Midjourney / Imagen 3)! ✨`);
    }).catch(() => {
      this.showToast("Failed to copy to clipboard", true);
    });
  }

  copySceneVideoPrompt(idx) {
    if (!this.currentProject || !this.currentProject.scenes || !this.currentProject.scenes[idx]) return;
    const scene = this.currentProject.scenes[idx];
    const promptText = (scene.acting_prompt || "").trim();
    if (!promptText) {
      this.showToast("Video acting prompt is empty!", true);
      return;
    }
    navigator.clipboard.writeText(promptText).then(() => {
      this.showToast(`🎬 Copied Scene ${idx + 1} Video Prompt (Veo 3 / Google Flow)! 🚀`);
    }).catch(() => {
      this.showToast("Failed to copy to clipboard", true);
    });
  }

  copyScenePrompt(idx) {
    this.copySceneVideoPrompt(idx);
  }

  async refineSceneVideoPrompt(idx, btn) {
    if (!this.currentProject || !this.currentProject.id) {
      this.showToast("No active project found", true);
      return;
    }
    const origHtml = btn ? btn.innerHTML : "";
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `⏳ Refining...`;
    }
    try {
      await this.saveStoryboardEdits(false);
      const res = await fetch(`/api/projects/${encodeURIComponent(this.currentProject.id)}/scenes/${idx}/refine-video-prompt`, {
        method: "POST"
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to refine video prompt");
      }
      const data = await res.json();
      const refinedPrompt = data.acting_prompt || (data.scene && data.scene.acting_prompt) || "";

      if (this.currentProject.scenes && this.currentProject.scenes[idx]) {
        this.currentProject.scenes[idx].acting_prompt = refinedPrompt;
      }
      this.saveActiveProjectState();

      const textarea = document.getElementById(`acting_prompt_${idx}`);
      if (textarea) {
        textarea.value = refinedPrompt;
        textarea.classList.remove("flash-highlight");
        void textarea.offsetWidth;
        textarea.classList.add("flash-highlight");
      }
      this.showToast(`✨ Upgraded Scene ${idx + 1} Video Prompt to cinematic director grade!`);
    } catch (err) {
      console.error("Refine scene video prompt failed:", err);
      this.showToast(err.message || "Failed to refine prompt", true);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = origHtml;
      }
    }
  }

  async refineAllVideoPrompts(btn) {
    if (!this.currentProject || !this.currentProject.id) {
      this.showToast("No active project found", true);
      return;
    }
    const origHtml = btn ? btn.innerHTML : "";
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `⏳ Refining All...`;
    }
    try {
      await this.saveStoryboardEdits(false);
      const res = await fetch(`/api/projects/${encodeURIComponent(this.currentProject.id)}/refine-all-video-prompts`, {
        method: "POST"
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to refine all video prompts");
      }
      const data = await res.json();
      if (data.scenes && Array.isArray(data.scenes)) {
        this.currentProject.scenes = data.scenes;
        data.scenes.forEach((sc, i) => {
          const textarea = document.getElementById(`acting_prompt_${i}`);
          if (textarea && sc.acting_prompt) {
            textarea.value = sc.acting_prompt;
            textarea.classList.remove("flash-highlight");
            void textarea.offsetWidth;
            textarea.classList.add("flash-highlight");
          }
        });
      }
      if (data.project) {
        this.currentProject = data.project;
      }
      this.saveActiveProjectState();
      this.showToast("✨ All scenes upgraded with director-grade 8s cinematic video prompts! 🎬");
    } catch (err) {
      console.error("Refine all video prompts failed:", err);
      this.showToast(err.message || "Failed to refine prompts", true);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = origHtml;
      }
    }
  }

  async syncStoryDialogues(sceneIdx = null, target = "all", btn = null) {
    if (!this.currentProject || !this.currentProject.id) {
      this.showToast("No active project loaded", true);
      return;
    }
    const origHtml = btn ? btn.innerHTML : "";
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = sceneIdx !== null ? `⏳ Syncing...` : `⏳ Adding Dialogues...`;
    }
    try {
      await this.saveStoryboardEdits(false);
      const res = await fetch(`/api/projects/${encodeURIComponent(this.currentProject.id)}/sync-dialogues`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scene_idx: sceneIdx,
          target: target || "all",
          re_render_clips: true
        })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to sync story dialogues");
      }
      const data = await res.json();
      if (data.project) {
        this.currentProject = data.project;
        this.renderStoryboardUI(data.project);
        this.saveActiveProjectState();
      }
      const count = Array.isArray(data.updated_scenes) ? data.updated_scenes.length : 0;
      if (sceneIdx !== null) {
        this.showToast(`💬 Added story dialogue to Scene ${sceneIdx + 1} Voiceover, Image & Video Clip!`);
      } else if (count > 0) {
        this.showToast(`💬 Added & synced story dialogues across ${count} scene(s) (Voiceover, Image & Video Clips)!`);
      } else {
        this.showToast(`💬 All story dialogues are already synced across Voiceover, Image & Video Clips!`);
      }
    } catch (err) {
      console.error("Sync story dialogues failed:", err);
      this.showToast(err.message || "Failed to sync dialogues", true);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = origHtml;
      }
    }
  }

  exportAllPrompts() {
    if (!this.currentProject || !this.currentProject.scenes || !this.currentProject.scenes.length) {
      this.showToast("No storyboard scenes available to export!", true);
      return;
    }
    const p = this.currentProject;
    let text = `=================================================================\n`;
    text += `🎬 STORYBOARD PROMPTS: ${p.title || "Animated Story"}\n`;
    if (p.logline) text += `📖 Logline: ${p.logline}\n`;
    if (p.characters) text += `👥 Characters: ${p.characters}\n`;
    text += `=================================================================\n\n`;

    p.scenes.forEach((sc, i) => {
      text += `--- SCENE ${sc.scene_number || (i + 1)}: ${sc.title || "Scene " + (i + 1)} ---\n`;
      text += `🎭 Archetype: ${sc.archetype || "Standard"}\n`;
      text += `🎥 Camera Motion: ${sc.camera_motion || "zoom_in"}\n`;
      text += `🎙️ Voiceover: "${sc.narration || ""}"\n`;
      text += `\n🎨 Visual Image Prompt (Midjourney / Imagen 3 / Puter):\n${sc.visual_prompt || ""}\n`;
      text += `\n🎬 Acting Video Prompt (Google Flow / Veo 3 / Kling):\n${sc.acting_prompt || ""}\n`;
      text += `\n\n`;
    });

    navigator.clipboard.writeText(text).then(() => {
      this.showToast("📋 All scene image & video prompts copied to clipboard! 🚀");
    }).catch(() => {
      const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${(p.title || "storyboard").replace(/[^a-zA-Z0-9_-]/g, "_")}_prompts.txt`;
      a.click();
      this.showToast("📄 Exported video and image prompts to text file!");
    });
  }

  exportFullScript() {
    if (!this.currentProject) return;
    const p = this.currentProject;
    let script = `# ${p.title || "Animated Short Film"}\n\n`;
    if (p.logline) script += `**Logline:** ${p.logline}\n\n`;
    if (p.characters) script += `**Characters & Visual Consistency:**\n${p.characters}\n\n`;
    script += `## Storyboard Breakdown (${p.scenes ? p.scenes.length : 0} Scenes)\n\n`;

    (p.scenes || []).forEach((sc, i) => {
      script += `### Scene ${sc.scene_number || (i + 1)}: ${sc.title || "Scene " + (i + 1)}\n`;
      script += `- **Archetype:** ${sc.archetype || "Beat"}\n`;
      script += `- **Narration:** "${sc.narration || ""}"\n`;
      script += `- **Visual Image Prompt:** ${sc.visual_prompt || ""}\n`;
      script += `- **Acting Video Prompt:** ${sc.acting_prompt || ""}\n\n`;
    });

    const blob = new Blob([script], { type: "text/markdown;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(p.title || "script").replace(/[^a-zA-Z0-9_-]/g, "_")}_screenplay.md`;
    a.click();
    this.showToast("📄 Screenplay exported as Markdown! 🎬");
  }

  async autoGenerateMissingSceneImages() {
    if (localStorage.getItem("anistory_autopaint") === "true") {
      await this.paintAllSceneImages(false);
    }
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
            const cleanPath = updatedScene?.image_path ? updatedScene.image_path.replace(/\\/g, "/") : "";
            const imgEl = document.getElementById(`sceneImg_${sceneIdx}`);
            const placeholderEl = document.getElementById(`scenePlaceholder_${sceneIdx}`);
            if (cleanPath) {
              if (imgEl) {
                imgEl.src = `/media/${encodeURI(cleanPath)}?t=${Date.now()}`;
                imgEl.style.display = "block";
              }
              if (placeholderEl) {
                placeholderEl.style.display = "none";
              }
              if (statusPill) {
                statusPill.className = "scene-status-pill ready";
                statusPill.textContent = "✓ Ready";
              }
            } else {
              if (imgEl) imgEl.style.display = "none";
              if (placeholderEl) placeholderEl.style.display = "flex";
              if (statusPill) {
                statusPill.className = "scene-status-pill error";
                statusPill.textContent = "⚠️ No Image";
              }
            }
            this.updateQuickJumpPill(sceneIdx, Boolean(cleanPath), Boolean(updatedScene?.video_path));
            this.saveActiveProjectState();
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
          btn.textContent = "🎨 Paint";
        }
      }

      // Pacing delay between sequential scenes for smooth visual updates and socket stability
      if (i < scenesToPaint.length - 1) {
        await new Promise(r => setTimeout(r, 600));
      }
    }

    this.saveActiveProjectState();
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
            const cleanImg = upScene.image_path.replace(/\\/g, "/");
            imgEl.src = `/media/${encodeURI(cleanImg)}?t=${Date.now()}`;
          }

          // Update video pill
          if (videoPill) {
            videoPill.className = "scene-status-pill ready";
            videoPill.textContent = "🎬 Video Ready";
          }

          // Update video player
          const vidEl = document.getElementById(`sceneVideo_${sceneIdx}`);
          if (vidEl && upScene.video_path) {
            const cleanVid = upScene.video_path.replace(/\\/g, "/");
            vidEl.src = `/media/${encodeURI(cleanVid)}?t=${Date.now()}`;
          }

          // Show overlay and download button
          const overlayBtn = document.getElementById(`btnPlayOverlay_${sceneIdx}`);
          if (overlayBtn) overlayBtn.style.display = "flex";

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

    const cleanVid = (scene.video_path || "").replace(/\\/g, "/");
    const videoUrl = `/media/${encodeURI(cleanVid)}?t=${Date.now()}`;
    if (this.modalSceneVideoTitle) {
      this.modalSceneVideoTitle.textContent = `🎬 Scene ${scene.scene_number || sceneIdx + 1}: ${scene.title || 'Animation Clip'}`;
    }
    if (this.modalSceneVideoMeta) {
      const motionName = (scene.camera_motion || "zoom_in").replace("_", " ").toUpperCase();
      const dur = scene.duration ? `${scene.duration.toFixed(1)}s` : "Dynamic";
      this.modalSceneVideoMeta.textContent = `Motion: ${motionName} • Duration: ${dur} • Voiceover: ${this.currentProject.enable_voiceover !== false ? 'ON' : 'OFF'} • Burnt Captions: ${this.currentProject.enable_subtitles !== false ? 'ON' : 'OFF'}`;
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
            console.warn("Puter browser AI notice:", pErr);
            this.showToast(`Puter generation notice: ${pErr.message || pErr}`, true);
          }
        } else {
          this.showToast("Puter.js not available in browser. Generating with Google Gemini Imagen 3...", false);
          this.setImageMode("gemini");
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
        const modeLabel = (curProvider === "gemini_cookie" || curProvider === "gemini") ? "Google Imagen 3" : (curProvider === "neural_love" ? "Neural.love AI" : "AI Paint");
        this.showToast(`Scene ${sceneIdx + 1} painted with ${modeLabel}! 🎨✨`);
      }

      const updatedScene = this.currentProject.scenes[sceneIdx];
      const cleanPath = updatedScene?.image_path ? updatedScene.image_path.replace(/\\/g, "/") : "";
      const imgEl = document.getElementById(`sceneImg_${sceneIdx}`);
      const placeholderEl = document.getElementById(`scenePlaceholder_${sceneIdx}`);
      const statusPill = document.getElementById(`sceneStatusPill_${sceneIdx}`);
      if (cleanPath) {
        if (imgEl) {
          imgEl.src = `/media/${encodeURI(cleanPath)}?t=${Date.now()}`;
          imgEl.style.display = "block";
        }
        if (placeholderEl) {
          placeholderEl.style.display = "none";
        }
        if (statusPill) {
          statusPill.className = "scene-status-pill ready";
          statusPill.textContent = "✓ Ready";
        }
      } else {
        if (imgEl) imgEl.style.display = "none";
        if (placeholderEl) placeholderEl.style.display = "flex";
        if (statusPill) {
          statusPill.className = "scene-status-pill error";
          statusPill.textContent = "⚠️ No Image";
        }
      }
      this.updateQuickJumpPill(sceneIdx, Boolean(cleanPath), Boolean(updatedScene?.video_path));
      this.saveActiveProjectState();
    } catch (e) {
      console.error(e);
      this.showToast(e.message || "Failed to regenerate image", true);
    } finally {
      buttonEl.disabled = false;
      buttonEl.textContent = "🎨 Paint";
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
      const cleanPath = updatedScene?.image_path ? updatedScene.image_path.replace(/\\/g, "/") : "";
      const imgEl = document.getElementById(`sceneImg_${sceneIdx}`);
      const placeholderEl = document.getElementById(`scenePlaceholder_${sceneIdx}`);
      if (cleanPath) {
        if (imgEl) {
          imgEl.src = `/media/${encodeURI(cleanPath)}?t=${Date.now()}`;
          imgEl.style.display = "block";
        }
        if (placeholderEl) {
          placeholderEl.style.display = "none";
        }
      }
      const statusPill = document.getElementById(`sceneStatusPill_${sceneIdx}`);
        if (statusPill) {
          statusPill.className = "scene-status-pill ready";
          statusPill.textContent = "✓ Custom Art";
        }
        this.updateQuickJumpPill(sceneIdx, Boolean(cleanPath), Boolean(updatedScene?.video_path));
        this.showToast(`Custom illustration applied to Scene ${sceneIdx + 1}! 🖼️`);
      } catch (e) {
        console.error(e);
        this.showToast("Upload failed: " + e.message, true);
      }
    }

    async cycleSceneProductPhoto(sceneIdx, btnEl) {
      if (!this.currentProject || !this.currentProject.product_images || !this.currentProject.product_images.length) {
        this.showToast("No uploaded product photos found for this project", true);
        return;
      }
      const prodImages = this.currentProject.product_images;
      const scene = this.currentProject.scenes[sceneIdx];

      // Find current product photo index and get next
      let currentRelPath = (scene?.image_path || "").replace(/\\/g, "/");
      let currentIdx = -1;
      for (let i = 0; i < prodImages.length; i++) {
        const p = prodImages[i].replace(/\\/g, "/");
        if (currentRelPath.endsWith(p) || p.endsWith(currentRelPath)) {
          currentIdx = i;
          break;
        }
      }
      const nextIdx = (currentIdx + 1) % prodImages.length;
      const nextImagePath = prodImages[nextIdx];

      const originalText = btnEl ? btnEl.innerHTML : "";
      if (btnEl) btnEl.innerHTML = "⏳ Applying...";

      try {
        this.showToast(`Applying Product Photo ${nextIdx + 1}/${prodImages.length} to Scene ${sceneIdx + 1}...`);
        const resp = await fetch(`/api/projects/${encodeURIComponent(this.currentProject.id)}/set-scene-product-image`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            scene_idx: sceneIdx,
            image_path: nextImagePath
          })
        });

        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.detail || "Failed to set product photo");
        }

        const resData = await resp.json();
        if (resData.project) {
          this.currentProject = resData.project;
        } else if (resData.image_path) {
          scene.image_path = resData.image_path;
          scene.is_product_photo = true;
        }
        this.saveActiveProjectState();
        this.renderStoryboardView();
        this.showToast(`Product Photo ${nextIdx + 1}/${prodImages.length} applied to Scene ${sceneIdx + 1}! 🛍️`);
      } catch (e) {
        console.error(e);
        this.showToast("Failed to apply product photo: " + e.message, true);
      } finally {
        if (btnEl) btnEl.innerHTML = originalText;
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
        const btnDownload = document.getElementById(`btnDownloadClip_${sceneIdx}`);
        if (btnDownload) btnDownload.style.display = "";

        this.updateQuickJumpPill(sceneIdx, true, true);
        this.showToast(`🎉 Scene ${sceneIdx + 1} acting video synced with speech & subtitles!`);
      } catch (e) {
        console.error(e);
        this.showToast("Upload failed: " + e.message, true);
      }
    }

  async generateVeoSceneVideo(sceneIdx, buttonEl) {
    if (!this.currentProject) return;

    await this.saveStoryboardEdits(false);

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
      const btnDownload = document.getElementById(`btnDownloadClip_${sceneIdx}`);
      if (btnDownload) btnDownload.style.display = "";

      this.updateQuickJumpPill(sceneIdx, true, true);
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
      const visualEl = document.getElementById(`visual_prompt_${idx}`);
      const actingEl = document.getElementById(`acting_prompt_${idx}`);
      const legacyPromptEl = document.getElementById(`prompt_${idx}`);
      const motionEl = document.getElementById(`motion_${idx}`);

      if (narEl) scene.narration = narEl.value;
      if (visualEl) {
        scene.visual_prompt = visualEl.value;
      }
      if (actingEl) {
        scene.acting_prompt = actingEl.value;
      } else if (legacyPromptEl) {
        scene.acting_prompt = legacyPromptEl.value;
      }
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
      const cleanProjVid = this.currentProject.video_path.replace(/\\/g, "/");
      this.cinemaVideoPlayer.src = `/media/${encodeURI(cleanProjVid)}?t=${Date.now()}`;
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
        const cleanVid = sc.video_path ? sc.video_path.replace(/\\/g, "/") : "";
        const cleanImg = sc.image_path ? sc.image_path.replace(/\\/g, "/") : "";
        const vidSrc = hasVid ? `/media/${encodeURI(cleanVid)}?t=${Date.now()}` : "";
        const imgSrc = cleanImg ? `/media/${encodeURI(cleanImg)}?t=${Date.now()}` : this.getInstantPreviewUrl(sc, idx);

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

  async loadProject(projectOrId, targetStage = 2) {
    const projId = (typeof projectOrId === "string") ? projectOrId : (projectOrId?.id);
    if (!projId) return;
    let p = projectOrId;
    try {
      const resp = await fetch(`/api/projects/${encodeURIComponent(projId)}`);
      if (resp.ok) {
        p = await resp.json();
      } else if (typeof projectOrId === "string") {
        throw new Error("Could not fetch project details");
      }
    } catch (err) {
      if (typeof projectOrId === "string") {
        this.showToast("Error loading project: " + err.message, true);
        return;
      }
    }

    if (!p || !p.id) return;
    this.currentProject = p;
    this.enableVoiceover = p.enable_voiceover !== false;
    this.enableSubtitles = p.enable_subtitles !== false;
    this.enableMultivoice = p.enable_multivoice !== false;
    localStorage.setItem("anistory_cfg_enable_voiceover", this.enableVoiceover ? "true" : "false");
    localStorage.setItem("anistory_cfg_enable_subtitles", this.enableSubtitles ? "true" : "false");
    localStorage.setItem("anistory_cfg_enable_multivoice", this.enableMultivoice ? "true" : "false");
    this.updateVoiceoverUI(this.enableVoiceover);
    this.updateSubtitlesUI(this.enableSubtitles);
    this.updateMultivoiceUI(this.enableMultivoice);
    this.saveActiveProjectState();

    if (this.modalProjects) {
      this.modalProjects.classList.remove("active");
    }

    if (targetStage === 4 || (p.status === "completed" && targetStage === 4)) {
      this.showCinemaPremiere();
    } else {
      this.renderStoryboardView();
      this.switchStage(2);
    }

    this.showToast(`Loaded film: "${p.title || p.id}" 🎬✨`);
  }

  async loadProjectsIntoContainer(containerEl) {
    if (!containerEl) return;
    containerEl.innerHTML = "<p style='color:var(--text-muted); padding:20px 0;'>Loading projects... ⏳</p>";

    try {
      const resp = await fetch("/api/projects");
      if (!resp.ok) throw new Error("Failed to load project list");
      const list = await resp.json();
      this.renderProjectsCards(list, containerEl);
    } catch (e) {
      console.error(e);
      containerEl.innerHTML = `<p style='color:#ef4444; padding:20px 0;'>Error loading projects: ${e.message}</p>`;
    }
  }

  renderProjectsCards(list, containerEl) {
    if (!containerEl) return;
    containerEl.innerHTML = "";

    if (!list || list.length === 0) {
      containerEl.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 40px 20px; color: var(--text-muted);">
          <div style="font-size: 42px; margin-bottom: 8px;">🎬</div>
          <p style="font-size: 14px; margin-bottom: 4px;">No existing projects found.</p>
          <span style="font-size: 12px; color: var(--text-dim);">Start a new film from an idea or import a project.json!</span>
        </div>
      `;
      return;
    }

    list.forEach(p => {
      const item = document.createElement("div");
      item.className = "project-item-card";

      const createdTime = p.created_at ? (p.created_at > 1e11 ? p.created_at : p.created_at * 1000) : Date.now();
      const dateStr = new Date(createdTime).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
      const scenesCount = p.scenes ? p.scenes.length : 0;
      const isCompleted = p.status === "completed" || Boolean(p.video_path);

      // Find first available scene image as thumbnail
      let thumbSrc = "";
      if (p.scenes && p.scenes.length > 0) {
        for (const sc of p.scenes) {
          if (sc.image_path) {
            const cleanPath = sc.image_path.replace(/\\/g, "/");
            thumbSrc = `/media/${encodeURI(cleanPath)}`;
            break;
          }
        }
      }

      let statusBadgeClass = "draft";
      let statusBadgeText = "Draft";
      if (p.status === "completed") {
        statusBadgeClass = "completed";
        statusBadgeText = "✓ Film Ready";
      } else if (p.status === "rendering") {
        statusBadgeClass = "in-progress";
        statusBadgeText = "⚡ Rendering";
      } else if (scenesCount > 0) {
        statusBadgeClass = "in-progress";
        statusBadgeText = "🎬 Storyboard";
      }

      item.innerHTML = `
        <div class="project-card-thumb-wrap" title="Click to open Director's Storyboard">
          ${thumbSrc
            ? `<img src="${thumbSrc}" class="project-card-thumb" alt="${p.title || 'Scene preview'}" loading="lazy">`
            : `<div style="font-size: 38px; color: rgba(255,255,255,0.25);">🎬</div>`
          }
          <span class="project-card-status-badge ${statusBadgeClass}">${statusBadgeText}</span>
          <span class="project-card-scenes-badge">${scenesCount} scenes</span>
        </div>
        <div class="project-card-info" title="Click to open Director's Storyboard">
          <div class="project-card-title">${p.title || p.idea || "Untitled Film"}</div>
          <div class="project-card-meta">
            <span>📅 ${dateStr}</span>
            <span>🎨 ${p.art_style || 'Style'}</span>
          </div>
        </div>
        <div class="project-card-actions">
          <button type="button" class="glass-btn secondary-btn btn-load-storyboard" title="Open Director's Storyboard to edit script & scenes">
            🎬 Storyboard
          </button>
          ${isCompleted ? `
          <button type="button" class="glass-btn secondary-btn btn-watch-film" style="color: #6ee7b7; border-color: rgba(16,185,129,0.4);" title="Watch film premiere">
            🍿 Watch
          </button>` : ''}
          <button type="button" class="btn-delete-project" title="Delete project">
            🗑️
          </button>
        </div>
      `;

      // Clicking thumbnail or info opens Storyboard
      item.querySelector(".project-card-thumb-wrap").addEventListener("click", () => this.loadProject(p, 2));
      item.querySelector(".project-card-info").addEventListener("click", () => this.loadProject(p, 2));

      // Action buttons
      const btnStoryboard = item.querySelector(".btn-load-storyboard");
      if (btnStoryboard) {
        btnStoryboard.addEventListener("click", (e) => {
          e.stopPropagation();
          this.loadProject(p, 2);
        });
      }

      const btnWatch = item.querySelector(".btn-watch-film");
      if (btnWatch) {
        btnWatch.addEventListener("click", (e) => {
          e.stopPropagation();
          this.loadProject(p, 4);
        });
      }

      const btnDelete = item.querySelector(".btn-delete-project");
      if (btnDelete) {
        btnDelete.addEventListener("click", async (e) => {
          e.stopPropagation();
          const pTitle = p.title || p.id;
          if (!confirm(`Are you sure you want to permanently delete project "${pTitle}"?`)) return;

          try {
            const dResp = await fetch(`/api/projects/${encodeURIComponent(p.id)}`, { method: "DELETE" });
            if (dResp.ok) {
              this.showToast(`Deleted project: "${pTitle}"`);
              if (this.currentProject && this.currentProject.id === p.id) {
                this.clearActiveProjectState();
                this.switchStage(1);
              }
              this.refreshAllProjectLists();
            } else {
              this.showToast("Failed to delete project", true);
            }
          } catch (delErr) {
            console.error(delErr);
            this.showToast("Delete error: " + delErr.message, true);
          }
        });
      }

      containerEl.appendChild(item);
    });
  }

  async refreshAllProjectLists() {
    try {
      const resp = await fetch("/api/projects");
      if (!resp.ok) return;
      const list = await resp.json();
      if (this.stage1ProjectsList) this.renderProjectsCards(list, this.stage1ProjectsList);
      if (this.savedProjectsList) this.renderProjectsCards(list, this.savedProjectsList);
    } catch (e) {
      console.warn("Error refreshing project lists:", e);
    }
  }

  async importProjectJsonFile(file) {
    if (!file) return;
    if (!file.name.endsWith(".json")) {
      this.showToast("Please select a valid .json project file.", true);
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
      this.showToast("Importing project.json... ⏳");
      const resp = await fetch("/api/projects/import-json", {
        method: "POST",
        body: formData
      });

      if (!resp.ok) {
        let errDetail = "Import failed";
        try {
          const ej = await resp.json();
          errDetail = ej.detail || errDetail;
        } catch {}
        throw new Error(errDetail);
      }

      const imported = await resp.json();
      this.showToast(`🎉 Project "${imported.title || imported.id}" imported successfully!`);
      this.loadProject(imported, 2);
    } catch (err) {
      console.error(err);
      this.showToast("Import error: " + err.message, true);
    }
  }

  async openProjectsModal() {
    if (!this.modalProjects) return;
    this.modalProjects.classList.add("active");
    if (this.savedProjectsList) {
      this.loadProjectsIntoContainer(this.savedProjectsList);
    }
  }
}

// Instantiate on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  window.aniStoryApp = new AniStoryApp();
});
