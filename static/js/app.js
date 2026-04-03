/**
 * app.js — TripSense Frontend Logic
 * White + Green design · JWT Authentication  
 */

// ── Auth State ───────────────────────────────────────────
/** @type {{ token: string, user: object } | null} */
let authState = null;

function loadAuthState() {
  try {
    const token = localStorage.getItem("ts_token");
    const user  = JSON.parse(localStorage.getItem("ts_user") || "null");
    if (token && user) authState = { token, user };
  } catch { authState = null; }
}

function saveAuthState(token, user) {
  authState = { token, user };
  localStorage.setItem("ts_token", token);
  localStorage.setItem("ts_user", JSON.stringify(user));
}

function clearAuthState() {
  authState = null;
  localStorage.removeItem("ts_token");
  localStorage.removeItem("ts_user");
}

function isLoggedIn() { return !!authState?.token; }

// ── Auth Header ───────────────────────────────────────────
function authHeaders() {
  const h = { "Content-Type": "application/json" };
  if (authState?.token) h["Authorization"] = `Bearer ${authState.token}`;
  return h;
}

// ─────────────────────────────────────────────────────────
// AUTH MODAL
// ─────────────────────────────────────────────────────────
function openAuthModal(tab = "login") {
  const modal = document.getElementById("auth-modal");
  modal.classList.remove("hidden");
  switchAuthTab(tab);
  setTimeout(() => modal.classList.add("open"), 10);
}

function closeAuthModal() {
  const modal = document.getElementById("auth-modal");
  modal.classList.remove("open");
  setTimeout(() => modal.classList.add("hidden"), 220);
  clearAuthErrors();
}

function switchAuthTab(tab) {
  document.querySelectorAll(".auth-tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".auth-form").forEach(f => f.classList.add("hidden"));
  document.getElementById(`tab-${tab}`)?.classList.add("active");
  document.getElementById(`form-${tab}`)?.classList.remove("hidden");
  clearAuthErrors();
}

function clearAuthErrors() {
  document.querySelectorAll(".auth-error").forEach(e => { e.textContent = ""; e.classList.add("hidden"); });
  document.querySelectorAll(".field-err").forEach(e => e.classList.remove("field-error"));
}

function setAuthError(formId, msg, field) {
  const errEl = document.getElementById(`${formId}-error`);
  if (errEl) { errEl.textContent = msg; errEl.classList.remove("hidden"); }
  if (field) {
    const inp = document.getElementById(`${formId}-${field}`);
    if (inp) inp.classList.add("field-error");
  }
}

// ── Register ─────────────────────────────────────────────
async function handleRegister(e) {
  e.preventDefault();
  clearAuthErrors();
  const username = document.getElementById("reg-username").value.trim();
  const email    = document.getElementById("reg-email").value.trim();
  const password = document.getElementById("reg-password").value;
  const confirm  = document.getElementById("reg-confirm").value;

  if (password !== confirm) {
    setAuthError("reg", "Passwords do not match.", "confirm");
    return;
  }

  setAuthLoading("reg", true);
  try {
    const res  = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, email, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      setAuthError("reg", data.error || "Registration failed.", data.field);
      return;
    }
    saveAuthState(data.token, data.user);
    closeAuthModal();
    updateNavAuth();
    showToast(`Welcome, ${data.user.username}! Your account is ready. 🎉`);
    // If on planner, proceed; else go to planner
    if (document.getElementById("planner-page").classList.contains("hidden")) {
      goPlanner();
    }
  } catch {
    setAuthError("reg", "Network error. Please try again.");
  } finally {
    setAuthLoading("reg", false);
  }
}

// ── Login ─────────────────────────────────────────────────
async function handleLogin(e) {
  e.preventDefault();
  clearAuthErrors();
  const email    = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;

  setAuthLoading("login", true);
  try {
    const res  = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      setAuthError("login", data.error || "Login failed.");
      return;
    }
    saveAuthState(data.token, data.user);
    closeAuthModal();
    updateNavAuth();
    showToast(`Welcome back, ${data.user.username}! ✈️`);
    // Restore stored preferences into form
    if (data.user.preferences) applyPreferences(data.user.preferences);
    if (document.getElementById("planner-page").classList.contains("hidden")) {
      goPlanner();
    }
  } catch {
    setAuthError("login", "Network error. Please try again.");
  } finally {
    setAuthLoading("login", false);
  }
}

// ── Logout ────────────────────────────────────────────────
async function handleLogout() {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
  clearAuthState();
  updateNavAuth();
  showToast("Logged out successfully.");
  goLanding();
}

// ── Save preferences after search ────────────────────────
async function savePreferences(city, budget, interests) {
  if (!isLoggedIn()) return;
  try {
    await fetch("/api/auth/preferences", {
      method:  "PUT",
      headers: authHeaders(),
      body: JSON.stringify({ default_city: city, budget, interests }),
    });
  } catch { /* silent */ }
}

function applyPreferences(prefs) {
  if (prefs.default_city) {
    const inp = document.getElementById("city-input");
    if (inp && !inp.value) {
      inp.value = prefs.default_city;
      inp.dispatchEvent(new Event("input"));
    }
  }
  if (prefs.budget) {
    const pill = document.querySelector(`.budget-pill[data-value="${prefs.budget}"]`);
    if (pill) selectBudget(pill);
  }
  if (Array.isArray(prefs.interests)) {
    prefs.interests.forEach(v => {
      const chip = document.querySelector(`.interest-chip[data-value="${v}"]`);
      if (chip && !chip.classList.contains("active")) chip.click();
    });
  }
}

function setAuthLoading(form, on) {
  const btn = document.getElementById(`${form}-btn`);
  if (!btn) return;
  btn.disabled = on;
  btn.textContent = on ? "Please wait…" : (form === "login" ? "Log In" : "Create Account");
}

// ── Update nav based on auth state ────────────────────────
function updateNavAuth() {
  const guestEl  = document.getElementById("nav-guest");
  const userEl   = document.getElementById("nav-user");
  const nameEl   = document.getElementById("nav-username");

  if (isLoggedIn()) {
    guestEl?.classList.add("hidden");
    userEl?.classList.remove("hidden");
    if (nameEl) nameEl.textContent = authState.user.username;
  } else {
    guestEl?.classList.remove("hidden");
    userEl?.classList.add("hidden");
  }
}

// ── Toast ─────────────────────────────────────────────────
function showToast(msg, duration = 3200) {
  let toast = document.getElementById("toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast";
    toast.className = "toast";
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), duration);
}

// ─────────────────────────────────────────────────────────
// PAGE SWITCHING
// ─────────────────────────────────────────────────────────
function goLanding(e) {
  if (e && e.preventDefault) e.preventDefault();
  document.getElementById("landing-page").classList.remove("hidden");
  document.getElementById("planner-page").classList.add("hidden");
  document.getElementById("auth-modal")?.classList.add("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function goPlanner(city) {
  document.getElementById("landing-page").classList.add("hidden");
  document.getElementById("planner-page").classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "instant" });
  if (city && typeof city === "string" && city.trim()) {
    const inp = document.getElementById("city-input");
    inp.value = city.trim();
    inp.dispatchEvent(new Event("input"));
  }
  // Apply saved preferences when opening planner
  if (isLoggedIn() && authState.user.preferences) {
    applyPreferences(authState.user.preferences);
  }
}

// ── State ────────────────────────────────────────────────────────────────────────
let selectedBudget    = "mid-range";
let selectedInterests = new Set();
let numberOfDays      = 3;
let numberOfPersons   = 1;

// ── Counter controls ────────────────────────────────────────────────────────────
const COUNTER_LIMITS = { days: [1, 10], persons: [1, 50] };

function adjustCounter(type, delta) {
  const [min, max] = COUNTER_LIMITS[type];
  if (type === 'days') {
    numberOfDays = Math.min(max, Math.max(min, numberOfDays + delta));
    document.getElementById('days-val').textContent = numberOfDays;
    document.getElementById('days-dec').disabled = numberOfDays <= min;
    document.getElementById('days-inc').disabled = numberOfDays >= max;
  } else {
    numberOfPersons = Math.min(max, Math.max(min, numberOfPersons + delta));
    document.getElementById('persons-val').textContent = numberOfPersons;
    document.getElementById('persons-dec').disabled = numberOfPersons <= min;
    document.getElementById('persons-inc').disabled = numberOfPersons >= max;
    // Update group label hint dynamically
    const hint = document.getElementById('persons-hint');
    if (hint) {
      const g = numberOfPersons === 1 ? '🧓 Solo' :
                numberOfPersons === 2 ? '💑 Couple' :
                numberOfPersons <= 4  ? '👫 Small Group' : '👥 Large Group';
      hint.textContent = g;
    }
  }
}

// ── City input ───────────────────────────────────────────
const cityInp = document.getElementById("city-input");
const cityClr = document.getElementById("city-clear");

cityInp.addEventListener("input", () => {
  cityClr.classList.toggle("hidden", !cityInp.value);
});
cityInp.addEventListener("keydown", e => {
  if (e.key === "Enter") handleSearch();
});

function clearCity() {
  cityInp.value = "";
  cityInp.focus();
  cityClr.classList.add("hidden");
}

// ── Budget ───────────────────────────────────────────────
function selectBudget(btn) {
  document.querySelectorAll(".budget-pill").forEach(p => p.classList.remove("active"));
  btn.classList.add("active");
  selectedBudget = btn.dataset.value;
}

// ── Interest chips ────────────────────────────────────────
document.querySelectorAll(".interest-chip").forEach(chip => {
  chip.addEventListener("click", () => {
    const v = chip.dataset.value;
    if (selectedInterests.has(v)) {
      selectedInterests.delete(v);
      chip.classList.remove("active");
      chip.setAttribute("aria-pressed", "false");
    } else {
      selectedInterests.add(v);
      chip.classList.add("active");
      chip.setAttribute("aria-pressed", "true");
    }
  });
});

// ─────────────────────────────────────────────────────────
// SEARCH
// ─────────────────────────────────────────────────────────
async function handleSearch() {
  // Must be logged in to use recommendations
  if (!isLoggedIn()) {
    openAuthModal("login");
    showToast("Please log in to get travel recommendations.");
    return;
  }

  const city = cityInp.value.trim();
  if (!city) {
    cityInp.focus();
    cityInp.style.outline = "2px solid rgba(239,68,68,.6)";
    setTimeout(() => { cityInp.style.outline = ""; }, 1800);
    return;
  }

  setLoading(true);
  hideError();

  try {
    setStep("Fetching live weather data…", 15, "weather");
    await sleep(400);
    setStep("Building your travel plan…", 50, "plan");

    const res = await fetch("/api/recommend", {
      method:  "POST",
      headers: authHeaders(),
      body: JSON.stringify({
        city,
        budget: selectedBudget,
        interests: [...selectedInterests],
        number_of_days:    numberOfDays,
        number_of_persons: numberOfPersons,
      }),
    });

    setStep("Searching top hotels…", 80, "hotels");
    const data = await res.json();
    setStep("Done!", 100, "done");
    await sleep(300);

    if (res.status === 401) {
      clearAuthState();
      updateNavAuth();
      openAuthModal("login");
      showToast("Your session expired. Please log in again.");
      return;
    }

    if (!res.ok) { showError(data.error || "Something went wrong."); return; }

    // Save preferences in background
    savePreferences(city, selectedBudget, [...selectedInterests]);

    renderAll(data);
  } catch (err) {
    showError("Network error — please check your connection.");
    console.error(err);
  } finally {
    setLoading(false);
  }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function setStep(text, pct, step) {
  const el  = document.getElementById("loading-step");
  const bar = document.getElementById("loading-bar");
  if (el)  el.textContent = text;
  if (bar) bar.style.width = pct + "%";
  ["weather","plan","hotels"].forEach(s => {
    const node = document.getElementById("lstep-" + s);
    if (!node) return;
    node.classList.remove("active","done");
    const order = ["weather","plan","hotels"];
    const si = order.indexOf(s), ai = order.indexOf(step);
    if (step === "done" || si < ai) node.classList.add("done");
    else if (si === ai) node.classList.add("active");
  });
}

function setLoading(on) {
  const overlay = document.getElementById("loading-overlay");
  const empty   = document.getElementById("results-empty");
  const content = document.getElementById("results-content");
  const btnText = document.getElementById("btn-text");
  const btnLoad = document.getElementById("btn-loader");
  const btn     = document.getElementById("search-btn");

  if (on) {
    overlay.classList.remove("hidden");
    empty.classList.add("hidden");
    content.classList.add("hidden");
    btnText.classList.add("hidden");
    btnLoad.classList.remove("hidden");
    btn.disabled = true;
  } else {
    overlay.classList.add("hidden");
    btnText.classList.remove("hidden");
    btnLoad.classList.add("hidden");
    btn.disabled = false;
  }
}

function showError(msg) {
  const box = document.getElementById("error-banner");
  document.getElementById("error-message").textContent = msg;
  box.classList.remove("hidden");
}
function hideError() {
  document.getElementById("error-banner").classList.add("hidden");
}

function clearResults() {
  document.getElementById("results-content").classList.add("hidden");
  document.getElementById("results-empty").classList.remove("hidden");
  document.getElementById("results-topbar").classList.add("hidden");
}

// ─────────────────────────────────────────────────────────
// RENDER ALL
// ─────────────────────────────────────────────────────────
function renderAll(data) {
  const empty   = document.getElementById("results-empty");
  const content = document.getElementById("results-content");
  empty.classList.add("hidden");
  content.classList.remove("hidden");
  content.scrollIntoView({ behavior: "smooth", block: "start" });

  const topbar = document.getElementById("results-topbar");
  const lbl    = document.getElementById("results-city-label");
  if (topbar && lbl) {
    const bMap = { budget:"Budget","mid-range":"Mid-Range",medium:"Mid-Range",high:"Luxury",luxury:"Luxury" };
    lbl.innerHTML = `📍 <strong>${cap(data.city)}</strong>
      <span class="topbar-budget">${bMap[data.budget] || cap(data.budget)}</span>`;
    topbar.classList.remove("hidden");
  }

  renderWeather(data.weather);
  renderWRec(data.weather_rec);
  renderTips(data.tips);
  renderCost(data.cost_estimate, data.group_info, data.group_activities, data.number_of_days, data.number_of_persons);
  renderPlan(data.travel_plan);
  renderItinerary(data.itinerary);
  renderHotels(data.hotels, data.city, data.budget);
}

function cap(s) {
  if (!s) return "";
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ── Weather ──────────────────────────────────────────────
function renderWeather(w) {
  const card = document.getElementById("weather-card");
  if (!w || w.error) {
    if (w?.error) card.querySelector(".weather-body").innerHTML =
      `<p style="color:#94a3b8;font-size:.88rem;">⚠ ${w.error}</p>`;
    return;
  }
  document.getElementById("weather-location").textContent = `${w.city}, ${w.country}`;
  document.getElementById("weather-temp").textContent     = `${w.temperature}°C`;
  document.getElementById("weather-desc").textContent     = w.description;
  document.getElementById("feels-like").textContent       = `${w.feels_like}°C`;
  document.getElementById("humidity").textContent         = `${w.humidity}%`;
  document.getElementById("wind-speed").textContent       = `${w.wind_speed} m/s`;
  const icon = document.getElementById("weather-icon");
  icon.src = `https://openweathermap.org/img/wn/${w.icon}@2x.png`;
  icon.alt = w.description;
}

// ── Weather Recommendation ───────────────────────────────
function renderWRec(rec) {
  const card = document.getElementById("wrec-card");
  if (!rec || !rec.headline) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");
  document.getElementById("wrec-icon").textContent     = rec.icon || "🌤";
  document.getElementById("wrec-mood").textContent     = `Current: ${rec.mood || ""}`;
  document.getElementById("wrec-headline").textContent = rec.headline;
  document.getElementById("wrec-blurb").textContent    = rec.blurb || "";
  document.getElementById("wrec-activities").innerHTML =
    (rec.activities || []).map(a => `<span class="wrec-chip">${a}</span>`).join("");
}

// ── Tips ─────────────────────────────────────────────────
function renderTips(tips) {
  const card = document.getElementById("tips-card");
  if (!tips || !Object.keys(tips).length) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");
  renderList("weather-tips",  tips.weather_tips  || []);
  renderList("interest-tips", tips.interest_tips || []);
  const budgetBox  = document.getElementById("budget-tip");
  const budgetWrap = document.getElementById("budget-tip-wrap");
  if (tips.budget_tip) {
    budgetBox.textContent = tips.budget_tip;
    budgetWrap.classList.remove("hidden");
  } else {
    budgetWrap.classList.add("hidden");
  }
}
function renderList(id, items) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = items.map(t => `<li>${t}</li>`).join("");
}

// ── Travel Plan ──────────────────────────────────────────
function renderPlan(plan) {
  const card = document.getElementById("plan-card");
  if (!plan || !plan.destination_plan) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");

  document.getElementById("plan-subtitle").textContent =
    plan.weather_mood ? `Weather: ${plan.weather_mood.replace(/_/g," ")}` : "";
  document.getElementById("plan-summary").textContent = plan.destination_plan;

  document.getElementById("plan-activities").innerHTML =
    (plan.activities || []).map(a => `
      <div class="plan-act">
        <div class="plan-act-top">
          <span class="plan-act-name">${a.indoor ? "🏠" : "🌿"} ${a.name}</span>
          <span class="${a.indoor ? "badge-in" : "badge-out"}">${a.indoor ? "Indoor" : "Outdoor"}</span>
        </div>
        <p class="plan-act-desc">${a.description}</p>
        <p class="plan-act-reason">✦ ${a.reason}</p>
      </div>`).join("");

  const h     = plan.hotel_recommendation;
  const hPick = document.getElementById("plan-hotel-pick");
  const hBox  = document.getElementById("plan-hotel-box");
  if (h) {
    hPick.classList.remove("hidden");
    const stars  = h.stars ? "★".repeat(Math.min(h.stars,5)) : "";
    const price  = h.price > 0 ? `$${h.price}/night` : "Price N/A";
    const rating = h.rating && h.rating !== "N/A" ? `⭐ ${h.rating}` : "";
    hBox.innerHTML = `
      <a class="plan-hotel-link" href="${h.url || "#"}" target="_blank" rel="noopener">
        <div class="plan-hotel-info">
          <div class="plan-hotel-name">${h.name}</div>
          ${stars ? `<div class="plan-hotel-stars">${stars}</div>` : ""}
          <div class="plan-hotel-meta">
            <span class="plan-hotel-price">${price}</span>
            ${rating ? `<span class="hotel-rating-pill">${rating}</span>` : ""}
            ${h.budget_tag ? `<span class="hotel-tag-pill">${h.budget_tag}</span>` : ""}
          </div>
          <div class="plan-hotel-reason">✦ ${h.reason || ""}</div>
        </div>
      </a>`;
  } else { hPick.classList.add("hidden"); }

  document.getElementById("plan-tips").innerHTML =
    (plan.tips || []).map(t => `<li>${t}</li>`).join("");

  document.getElementById("plan-reasoning").textContent = plan.plan_reasoning || "";
}

function toggleReasoning() {
  const box = document.getElementById("plan-reasoning");
  const btn = document.getElementById("reasoning-toggle");
  const hidden = box.classList.toggle("hidden");
  btn.textContent = hidden ? "Show how this plan was built" : "Hide plan reasoning";
}

// ── Itinerary (timeline) ─────────────────────────────────
const TIMES = { Morning: "09:00", Afternoon: "14:00", Evening: "19:00" };
const ICONS = { Morning: "🌅",    Afternoon: "☀️",    Evening:  "🌙"   };

function inferCategory(label, name, desc) {
  const t = (name + " " + (desc || "")).toLowerCase();
  if (/food|eat|dine|lunch|dinner|restau|café|market|street food|taste/.test(t)) return "Food";
  if (/beach|swim|snorkel|surf|water|dive/.test(t)) return "Beach";
  if (/temple|museum|monument|heritage|culture|gallery|palace/.test(t)) return "Attraction";
  if (/hike|trek|mountain|adventure|climb|zip|kayak/.test(t)) return "Adventure";
  if (/spa|yoga|wellness|meditat|relax/.test(t)) return "Wellness";
  if (/shop|market|bazar|mall/.test(t)) return "Shopping";
  return label;
}

function catClass(cat) {
  const m = {
    "Morning":"cat-morning","Afternoon":"cat-afternoon","Evening":"cat-evening",
    "Food":"cat-food","Beach":"cat-beach","Attraction":"cat-culture",
    "Adventure":"cat-adventure","Nature":"cat-nature","Wellness":"cat-morning",
    "Shopping":"cat-afternoon","Culture":"cat-culture"
  };
  return m[cat] || "cat-morning";
}

function renderItinerary(itin) {
  const card = document.getElementById("itinerary-card");
  if (!itin || !itin.days || itin.days.length === 0) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");

  const isMistral = itin.source === "mistral";
  document.getElementById("itinerary-subtitle").innerHTML =
    `<span class="itin-source-badge ${isMistral ? "badge-ai" : "badge-fallback"}">
      ${isMistral ? "✨ AI-Generated" : "⚙ Smart Plan"}
    </span> ${itin.summary || ""}`;

  document.getElementById("itinerary-days").innerHTML = itin.days.map(day => {
    const slots = [
      { label:"Morning",   data: day.morning   },
      { label:"Afternoon", data: day.afternoon  },
      { label:"Evening",   data: day.evening    },
    ].filter(s => s.data);

    return `
      <div class="day-block">
        <div class="day-heading">Day ${day.day_number}</div>
        <div class="day-sub">${day.theme || ""}</div>
        <div class="timeline">
          ${slots.map(s => {
            const cat = inferCategory(s.label, s.data.name, s.data.description);
            return `
              <div class="tl-item">
                <div class="tl-dot"></div>
                <div class="tl-icon">${ICONS[s.label] || "📍"}</div>
                <div class="tl-body">
                  <div class="tl-top">
                    <span class="tl-time">${TIMES[s.label]}</span>
                    <span class="tl-cat ${catClass(cat)}">${cat}</span>
                  </div>
                  <div class="tl-name">${s.data.name}</div>
                  <div class="tl-desc">${s.data.description || ""}</div>
                </div>
              </div>`;
          }).join("")}
        </div>
      </div>`;
  }).join("");

  const tips     = itin.tips || [];
  const tipsWrap = document.getElementById("itinerary-tips");
  if (tipsWrap) {
    if (tips.length > 0) {
      tipsWrap.innerHTML =
        `<div class="itin-tips-lbl">💡 Travel Tips</div>
         <ul class="itin-tips-list">${tips.map(t => `<li>${t}</li>`).join("")}</ul>`;
      tipsWrap.classList.remove("hidden");
    } else { tipsWrap.classList.add("hidden"); }
  }
}

// ── Hotels ───────────────────────────────────────────────
function renderHotels(hotelData, city, budget) {
  const card     = document.getElementById("hotels-card");
  const grid     = document.getElementById("hotels-grid");
  const msg      = document.getElementById("hotels-message");
  const subtitle = document.getElementById("hotels-subtitle");
  card.classList.remove("hidden");

  if (hotelData?.error) {
    grid.innerHTML = "";
    msg.textContent = "⚠ " + hotelData.error;
    msg.classList.remove("hidden");
    subtitle.textContent = "";
    return;
  }

  const hotels = hotelData?.hotels || [];
  const fs     = hotelData?.filter_summary || null;

  if (hotels.length === 0) {
    grid.innerHTML = `<p style="color:#94a3b8;font-size:.88rem;">No hotels found for ${city}.</p>`;
    return;
  }

  msg.classList.add("hidden");
  if (fs) {
    const range = fs.price_max ? `$${fs.price_min}–$${fs.price_max}/night` : `$${fs.price_min}+/night`;
    const sort  = { price_asc:"Cheapest first",rating_desc:"Top-rated first",relevance:"Best match" }[fs.sort] || "";
    subtitle.textContent = `Top ${hotels.length} · ${fs.tier} · ${range}${sort ? " · " + sort : ""}`;
  } else {
    subtitle.textContent = `${hotels.length} properties · ${cap(budget)}`;
  }

  grid.innerHTML = hotels.map((h, i) => {
    const stars      = h.stars ? "★".repeat(Math.min(h.stars,5)) : "";
    const price      = h.price > 0 ? `$${h.price}` : "N/A";
    const rating     = h.rating && h.rating !== "N/A" ? h.rating : null;
    const photo      = h.photo
      ? `<img class="hotel-photo" src="${h.photo}" alt="${h.name}" loading="lazy"
            onerror="this.outerHTML='<div class=hotel-photo-ph>🏨</div>'"/>`
      : `<div class="hotel-photo-ph">🏨</div>`;
    const score      = h.relevance_score || 0;
    const scorePct   = Math.round(score * 100);
    const showScore  = fs?.sort === "relevance" && score > 0;
    const rwMap      = { 9:"Exceptional",8:"Excellent",7:"Very Good",6:"Good" };
    const rwWord     = rating ? (rwMap[Math.floor(parseFloat(rating))] || "Good") : "";

    return `
      <a class="hotel-card" href="${h.url || "#"}" target="_blank" rel="noopener">
        ${photo}
        <div class="hotel-info">
          <div class="hotel-name">${h.name}</div>
          ${stars ? `<div class="hotel-stars">${stars}</div>` : ""}
          <div class="hotel-meta-row">
            <span class="hotel-price">${price}</span>
            ${rating ? `<span class="hotel-rating-btn">${rating}</span>
              <span class="hotel-review-lbl">${rwWord}</span>` : ""}
          </div>
          ${showScore ? `<div class="hotel-score-row">
            <span class="hotel-score-lbl">Match</span>
            <div class="hotel-score-bar"><div class="hotel-score-fill" style="width:${scorePct}%"></div></div>
            <span class="hotel-score-pct">${scorePct}%</span>
          </div>` : ""}
          ${h.address ? `<div class="hotel-addr">📍 ${h.address}</div>` : ""}
        </div>
      </a>`;
  }).join("");
}

// ── Cost & Group ──────────────────────────────────────────
function renderCost(cost, groupInfo, groupActivities, numDays, numPersons) {
  const card = document.getElementById("cost-card");
  if (!cost) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");

  // Subtitle
  const sub = document.getElementById("cost-subtitle");
  if (sub) sub.textContent = `${numDays} day${numDays !== 1 ? "s" : ""} · ${numPersons} person${numPersons !== 1 ? "s" : ""}`;

  // Total
  document.getElementById("cost-total").textContent = `$${cost.total_cost.toLocaleString()}`;

  // Breakdown bars
  const bd   = cost.breakdown || {};
  const cats = [
    { key:"accommodation", label:"🏨 Accommodation", color:"var(--green)" },
    { key:"food",          label:"🍜 Food & Dining",  color:"#f59e0b" },
    { key:"activities",    label:"🎯 Activities",     color:"#6366f1" },
    { key:"transport",     label:"🚌 Transport",      color:"#06b6d4" },
  ];
  const grandTotal = Object.values(bd).reduce((s, v) => s + v, 0) || 1;

  document.getElementById("cost-breakdown").innerHTML = cats.map(c => {
    const val = bd[c.key] || 0;
    const pct = Math.round((val / grandTotal) * 100);
    return `
      <div class="cost-item">
        <div class="cost-item-row">
          <span class="cost-item-lbl">${c.label}</span>
          <span class="cost-item-val">$${val.toLocaleString()}</span>
        </div>
        <div class="cost-bar-bg">
          <div class="cost-bar-fill" style="width:${pct}%;background:${c.color}"></div>
        </div>
      </div>`;
  }).join("");

  // Discount note
  if (cost.group_discount_pct > 0) {
    const note = document.createElement("p");
    note.className = "cost-discount-note";
    note.textContent = `✅ ${cost.group_discount_pct}% group discount applied`;
    document.getElementById("cost-breakdown").appendChild(note);
  }

  // Per-person note
  const ppNote = document.createElement("p");
  ppNote.className = "cost-pp-note";
  ppNote.textContent = `≈ $${cost.per_person_total.toLocaleString()} per person · ${cost.note}`;
  document.getElementById("cost-breakdown").appendChild(ppNote);

  // Group banner
  if (groupInfo) {
    document.getElementById("group-banner").innerHTML = `
      <span class="group-emoji">${groupInfo.emoji}</span>
      <span class="group-label">${groupInfo.label}</span>
      <span class="group-desc">${groupInfo.description}</span>`;
  }

  // Group activity suggestions
  if (groupActivities && groupActivities.length > 0) {
    const wrap = document.getElementById("group-acts-wrap");
    document.getElementById("group-acts-list").innerHTML =
      groupActivities.map(a => `<li>${a}</li>`).join("");
    wrap.classList.remove("hidden");
  }
}

// ─────────────────────────────────────────────────────────
// INITIALISE
// ─────────────────────────────────────────────────────────
loadAuthState();
updateNavAuth();

// Close auth modal on backdrop click
document.getElementById("auth-modal")?.addEventListener("click", e => {
  if (e.target === e.currentTarget) closeAuthModal();
});

// Keyboard shortcut: Esc to close modal
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeAuthModal();
});
