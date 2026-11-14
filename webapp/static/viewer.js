const picker = document.querySelector("[data-sky-picker]");
const archiveForm = document.querySelector("[data-archive-form]");
const sigmaInput = document.querySelector("[data-sigma-threshold]");
const sigmaValue = document.querySelector("[data-sigma-value]");
const statusLoaderUrl = "/static/vendor/ui/loading-green.gif?v=2";

function showLoadingStatus(element, message) {
  const image = document.createElement("img");
  image.src = statusLoaderUrl;
  image.alt = "";
  image.className = "status-loader-gif";
  const text = document.createElement("span");
  text.textContent = message;
  element.replaceChildren(image, text);
  element.classList.add("loading");
}

if (sigmaInput && sigmaValue) {
  sigmaInput.addEventListener("input", () => { sigmaValue.textContent = `${Number(sigmaInput.value).toFixed(1)}σ`; });
}

if (picker) {
  const viewport = picker.querySelector("[data-sky-viewport]");
  const aladinElement = picker.querySelector("[data-aladin-map]");
  const layer = picker.querySelector("[data-sky-layer]");
  const image = picker.querySelector("[data-sky-image]");
  const marker = picker.querySelector("[data-selection-box]");
  const channelSelect = picker.querySelector("[data-sky-channel]");
  const loadingOverlay = picker.querySelector("[data-map-loading]");
  const help = picker.querySelector("[data-map-help]");
  const raInput = document.querySelector("[data-ra-input]");
  const decInput = document.querySelector("[data-dec-input]");
  let scale = 1;
  let offsetX = 0;
  let offsetY = 0;
  let dragging = false;
  let moved = false;
  let lastX = 0;
  let lastY = 0;
  let atlasMode = false;
  let aladin = null;
  let hipsLayer = null;

  function selectCoordinates(ra, dec, label) {
    raInput.value = ra.toFixed(6);
    decInput.value = dec.toFixed(6);
    raInput.dispatchEvent(new Event("change"));
    decInput.dispatchEvent(new Event("change"));
    help.textContent = label;
  }

  function useAtlasFallback() {
    atlasMode = true;
    aladinElement.hidden = true;
    layer.hidden = false;
    loadingOverlay.hidden = true;
    help.textContent = "WebGL2 unavailable · using selectable HEALPix tile atlas";
  }

  function showCubeChannel(channel) {
    if (!hipsLayer) return false;
    const depth = 102;
    const c = 299792458.0;
    const fLo = c / 5.009e-6;
    const fHi = c / 7.43e-7;
    const frame = Number(channel) - 1;
    hipsLayer.setFrequency({value: fLo + (frame + 0.5) / depth * (fHi - fLo), unit: "Hz"});
    return true;
  }

  for (let channel = 2; channel <= 102; channel += 1) {
    const option = document.createElement("option");
    const detector = Math.ceil(channel / 17);
    const detectorChannel = ((channel - 1) % 17) + 1;
    option.value = String(channel);
    option.textContent = `Channel ${channel} · D${detector}/${detectorChannel}`;
    channelSelect.append(option);
  }
  channelSelect.addEventListener("change", () => {
    const channel = channelSelect.value;
    help.textContent = `Loading spectral channel ${channel}…`;
    if (!showCubeChannel(channel)) {
      image.src = channelSelect.dataset.channelUrl.replace("{channel}", channel);
    } else {
      help.textContent = `Continuous Aitoff map · channel ${channel}/102`;
    }
  });
  image.addEventListener("load", () => {
    help.textContent = `Channel ${channelSelect.value}/102 loaded · click a sky tile`;
  });
  image.addEventListener("error", () => {
    help.textContent = `Channel ${channelSelect.value} could not load · choose another channel`;
  });

  function render() {
    layer.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
  }

  function zoomBy(factor, x = viewport.clientWidth / 2, y = viewport.clientHeight / 2) {
    const next = Math.max(1, Math.min(10, scale * factor));
    const ratio = next / scale;
    offsetX = x - (x - offsetX) * ratio;
    offsetY = y - (y - offsetY) * ratio;
    scale = next;
    render();
  }

  viewport.addEventListener("wheel", (event) => {
    if (!atlasMode) return;
    event.preventDefault();
    const rect = viewport.getBoundingClientRect();
    zoomBy(event.deltaY < 0 ? 1.2 : 1 / 1.2, event.clientX - rect.left, event.clientY - rect.top);
  }, {passive: false});
  viewport.addEventListener("pointerdown", (event) => {
    if (!atlasMode) return;
    dragging = true; moved = false; lastX = event.clientX; lastY = event.clientY;
    viewport.setPointerCapture(event.pointerId);
  });
  viewport.addEventListener("pointermove", (event) => {
    if (!atlasMode) return;
    if (!dragging) return;
    const dx = event.clientX - lastX;
    const dy = event.clientY - lastY;
    if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
    offsetX += dx; offsetY += dy; lastX = event.clientX; lastY = event.clientY;
    render();
  });
  viewport.addEventListener("pointerup", async (event) => {
    if (!atlasMode) return;
    dragging = false;
    if (moved || !image.naturalWidth) return;
    const rect = viewport.getBoundingClientRect();
    const displayX = (event.clientX - rect.left - offsetX) / scale;
    const displayY = (event.clientY - rect.top - offsetY) / scale;
    const x = displayX * image.naturalWidth / layer.clientWidth;
    const y = displayY * image.naturalHeight / layer.clientHeight;
    if (x < 0 || y < 0 || x >= image.naturalWidth || y >= image.naturalHeight) return;
    marker.style.left = `${displayX}px`;
    marker.style.top = `${displayY}px`;
    marker.classList.add("visible");
    help.textContent = "Reading the HEALPix tile…";
    const params = new URLSearchParams({x, y, width: image.naturalWidth, height: image.naturalHeight});
    try {
      const response = await fetch(`${picker.dataset.tileUrl}?${params}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Tile lookup failed.");
      selectCoordinates(data.ra, data.dec, `Tile ${data.tile} · RA ${data.ra.toFixed(3)}° · Dec ${data.dec.toFixed(3)}°`);
    } catch (error) {
      marker.classList.remove("visible");
      help.textContent = error.message;
    }
  });

  picker.querySelector("[data-zoom-in]").addEventListener("click", () => atlasMode ? zoomBy(1.25) : aladin?.increaseZoom?.());
  picker.querySelector("[data-zoom-out]").addEventListener("click", () => atlasMode ? zoomBy(1 / 1.25) : aladin?.decreaseZoom?.());
  picker.querySelector("[data-reset-view]").addEventListener("click", () => {
    if (atlasMode) {
      scale = 1; offsetX = 0; offsetY = 0; marker.classList.remove("visible"); render();
    } else {
      aladin?.gotoRaDec?.(180, 0);
      aladin?.setFoV?.(360);
    }
  });

  async function startContinuousMap() {
    if (!window.A) {
      window.addEventListener("aladin-ready", startContinuousMap, {once: true});
      window.setTimeout(() => { if (!window.A) useAtlasFallback(); }, 15000);
      return;
    }
    try {
      await window.A.init;
      aladin = window.A.aladin("#spherex-all-sky", {
        fov: 360,
        projection: "AIT",
        cooFrame: "equatorial",
        showCooGrid: true,
        showReticle: true,
        showSimbadPointerControl: false,
      });
      hipsLayer = window.A.imageHiPS(picker.dataset.hipsUrl, {
        successCallback: () => {
          showCubeChannel(channelSelect.value);
          loadingOverlay.hidden = true;
          help.textContent = `Continuous Aitoff map · channel ${channelSelect.value}/102`;
        },
      });
      aladin.setBaseImageLayer(hipsLayer);
      aladin.setProjection?.("AIT");
      aladin.setFoV?.(360);
      aladin.gotoRaDec?.(180, 0);
      aladin.on("click", (position) => {
        if (!position || !Number.isFinite(position.ra) || !Number.isFinite(position.dec)) return;
        selectCoordinates(position.ra, position.dec, `RA ${position.ra.toFixed(3)}° · Dec ${position.dec.toFixed(3)}°`);
      });
    } catch (error) {
      useAtlasFallback();
    }
  }
  startContinuousMap();
}

if (archiveForm) {
  const raInput = archiveForm.querySelector("[data-ra-input]");
  const decInput = archiveForm.querySelector("[data-dec-input]");
  const bandInput = archiveForm.querySelector("[data-band-input]");
  const periodInput = archiveForm.querySelector("[data-period-input]");
  const fromDateInput = archiveForm.querySelector("[data-from-date]");
  const toDateInput = archiveForm.querySelector("[data-to-date]");
  const startSelect = archiveForm.querySelector("[data-start-date]");
  const endSelect = archiveForm.querySelector("[data-end-date]");
  const searchButton = archiveForm.querySelector("[data-search-observations]");
  const generateButton = archiveForm.querySelector("[data-generate]");
  const status = archiveForm.querySelector("[data-archive-status]");
  const generateStatus = archiveForm.querySelector("[data-generate-status]");

  function formatLocalDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function formatGreekDate(value) {
    const [year, month, day] = String(value).slice(0, 10).split("-");
    return year && month && day ? `${day}/${month}/${year}` : value;
  }

  function applyQuickPeriod() {
    const custom = periodInput.value === "custom";
    const allData = periodInput.value === "all";
    fromDateInput.readOnly = !custom;
    toDateInput.readOnly = !custom;
    if (allData) {
      fromDateInput.value = "";
      toDateInput.value = "";
    } else if (!custom) {
      const toDate = new Date();
      const fromDate = new Date(toDate);
      fromDate.setDate(fromDate.getDate() - Number(periodInput.value));
      fromDateInput.value = formatLocalDate(fromDate);
      toDateInput.value = formatLocalDate(toDate);
    }
    generateButton.disabled = true;
    generateStatus.textContent = "";
    generateStatus.classList.remove("loading");
    status.textContent = allData
      ? "All current DR1 + QR3 dates will be searched."
      : "Period changed — search the archive again.";
  }

  function fillSelect(select, observations, selectedIndex) {
    select.replaceChildren();
    observations.forEach((observation, index) => {
      const option = document.createElement("option");
      option.value = observation.id;
      option.textContent = `${formatGreekDate(observation.date)} · ${observation.collection} · pipeline ${observation.version}`;
      option.selected = index === selectedIndex;
      select.append(option);
    });
    select.disabled = false;
  }

  async function searchArchive() {
    searchButton.disabled = true;
    generateButton.disabled = true;
    generateStatus.textContent = "";
    generateStatus.classList.remove("loading");
    showLoadingStatus(status, "Searching the current NASA/IPAC archive…");
    const params = new URLSearchParams({
      ra: raInput.value,
      dec: decInput.value,
      band: bandInput.value,
      from_date: fromDateInput.value,
      to_date: toDateInput.value,
    });
    try {
      const response = await fetch(`${archiveForm.dataset.observationsUrl}?${params}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Archive search failed.");
      if (!data.count) throw new Error("No observations cover this position in the selected band.");
      const rangeStart = 0;
      fillSelect(startSelect, data.observations, rangeStart);
      fillSelect(endSelect, data.observations, data.observations.length - 1);
      const first = formatGreekDate(data.observations[rangeStart].date);
      const last = formatGreekDate(data.observations.at(-1).date);
      let sourceNote = "";
      if (data.source === "local catalog fallback") {
        sourceNote = " Local catalog fallback is active because the live IRSA proxy is unavailable.";
      } else if (data.source === "local demo files") {
        sourceNote = " Offline demo active: using the two downloaded D5 FITS files at RA 133.805°, Dec −8.770°.";
      }
      status.textContent = `${data.count} current observations found${data.cache_hit ? " (cached search)" : ""}, from ${first} to ${last}. All are available in the From/To selectors${data.truncated ? " (first 5,000 shown)" : ""}.${sourceNote}`;
      generateButton.disabled = false;
    } catch (error) {
      status.textContent = error.message;
      startSelect.disabled = true;
      endSelect.disabled = true;
    } finally {
      searchButton.disabled = false;
      status.classList.remove("loading");
    }
  }

  searchButton.addEventListener("click", searchArchive);
  periodInput.addEventListener("change", applyQuickPeriod);
  fromDateInput.addEventListener("change", () => { generateButton.disabled = true; });
  toDateInput.addEventListener("change", () => { generateButton.disabled = true; });
  archiveForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const originalLabel = generateButton.textContent;
    generateButton.disabled = true;
    generateButton.textContent = "Downloading available frames…";
    showLoadingStatus(generateStatus, "Generating the time-lapse… downloading and analysing available frames.");
    try {
      const response = await fetch(archiveForm.action, {
        method: "POST",
        body: new FormData(archiveForm),
        headers: {"X-Requested-With": "fetch"},
      });
      const html = await response.text();
      const page = new DOMParser().parseFromString(html, "text/html");
      const incomingMount = page.querySelector("[data-result-mount]");
      const currentMount = document.querySelector("[data-result-mount]");
      const returnedError = page.querySelector(".error");
      if (!response.ok || !incomingMount || !incomingMount.querySelector("[data-viewer]")) {
        throw new Error(returnedError?.textContent?.trim() || "The time-lapse could not be generated.");
      }
      currentMount.innerHTML = incomingMount.innerHTML;
      const newViewer = currentMount.querySelector("[data-viewer]");
      initializeViewer(newViewer);
      generateStatus.textContent = "Time-lapse ready. The results are displayed below.";
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      newViewer.scrollIntoView({behavior: reducedMotion ? "auto" : "smooth", block: "start"});
    } catch (error) {
      generateStatus.textContent = error.message;
    } finally {
      generateButton.textContent = originalLabel;
      generateButton.disabled = startSelect.disabled || endSelect.disabled;
      generateStatus.classList.remove("loading");
    }
  });
  bandInput.addEventListener("change", () => { generateButton.disabled = true; status.textContent = "Band changed — search again."; });
  raInput.addEventListener("change", () => { generateButton.disabled = true; });
  decInput.addEventListener("change", () => { generateButton.disabled = true; });
  applyQuickPeriod();
}

function initializeViewer(viewer) {
  if (!viewer) return;
  const frames = [...viewer.querySelectorAll(".frame")];
  const points = [...viewer.querySelectorAll(".timeline-point")];
  const dateLabel = viewer.querySelector("#current-date");
  const playButton = viewer.querySelector('[data-action="play"]');
  const pauseButton = viewer.querySelector('[data-action="pause"]');
  let current = 0;
  let timer = null;

  function show(index) {
    current = (index + frames.length) % frames.length;
    frames.forEach((frame, i) => {
      const active = i === current;
      frame.classList.toggle("active", active);
      frame.setAttribute("aria-hidden", String(!active));
    });
    points.forEach((point, i) => {
      const active = i === current;
      point.classList.toggle("active", active);
      if (active) point.setAttribute("aria-current", "date");
      else point.removeAttribute("aria-current");
    });
    dateLabel.textContent = frames[current].dataset.date;
  }

  function pause() {
    window.clearInterval(timer);
    timer = null;
    playButton.setAttribute("aria-pressed", "false");
    pauseButton.setAttribute("aria-pressed", "true");
  }

  function play() {
    if (!timer) timer = window.setInterval(() => show(current + 1), 1200);
    playButton.setAttribute("aria-pressed", "true");
    pauseButton.setAttribute("aria-pressed", "false");
  }

  viewer.querySelector('[data-action="previous"]').addEventListener("click", () => show(current - 1));
  viewer.querySelector('[data-action="next"]').addEventListener("click", () => show(current + 1));
  playButton.addEventListener("click", play);
  pauseButton.addEventListener("click", pause);
  points.forEach((point) => point.addEventListener("click", () => { pause(); show(Number(point.dataset.index)); }));
  pause();
  show(0);
}

initializeViewer(document.querySelector("[data-viewer]"));
