/**
 * app-extensions.js — Multi-destination, Transport, Restaurants, Razorpay
 * Loaded AFTER app.js. Provides helper functions called by the overridden
 * handleSearch and renderAll in app.js.
 */

// ── Close booking modal on backdrop ──────────────────────────────────────────
(function() {
  const bm = document.getElementById("booking-modal");
  if (bm) bm.addEventListener("click", e => { if (e.target === bm) closeBookingModal(); });
})();

// ── Multi-destination — Add/Remove Stop ──────────────────────────────────────
let extraStops = 0;
const MAX_STOPS = 2;

window.addDestinationStop = function() {
  if (extraStops >= MAX_STOPS) { showToast("Maximum 3 destinations supported."); return; }
  extraStops++;
  const idx  = extraStops;
  const wrap = document.getElementById("extra-destinations");
  if (!wrap) return;
  const div = document.createElement("div");
  div.className = "form-group extra-stop-group";
  div.id = "stop-group-" + idx;
  div.innerHTML =
    '<label class="form-label">\uD83D\uDCCD Stop ' + (idx + 1) + '</label>' +
    '<div class="city-field">' +
      '<span class="city-icon">\uD83D\uDCCD</span>' +
      '<input class="city-input extra-stop-input" id="stop-input-' + idx + '" type="text"' +
        ' placeholder="Additional city\u2026" autocomplete="off" maxlength="80"/>' +
      '<button class="city-clear" onclick="removeStop(' + idx + ')" aria-label="Remove stop">\u00D7</button>' +
    '</div>';
  wrap.appendChild(div);
  if (extraStops >= MAX_STOPS) {
    const btn = document.getElementById("add-stop-btn");
    if (btn) { btn.disabled = true; btn.style.opacity = "0.4"; }
  }
};

window.removeStop = function(idx) {
  const el = document.getElementById("stop-group-" + idx);
  if (el) el.remove();
  extraStops = Math.max(0, extraStops - 1);
  const btn = document.getElementById("add-stop-btn");
  if (btn) { btn.disabled = false; btn.style.opacity = ""; }
};

// Exposed globally so app.js handleSearch can call them
window.getDestinations = function() {
  const primary = (document.getElementById("city-input") || {}).value;
  if (!primary || !primary.trim()) return [];
  const result = [primary.trim()];
  document.querySelectorAll(".extra-stop-input").forEach(function(inp) {
    var v = inp.value.trim();
    if (v) result.push(v);
  });
  return result;
};

window.getSource = function() {
  var el = document.getElementById("source-input");
  return el ? el.value.trim() : "";
};

// ── Override handleSearch AFTER app.js loads ──────────────────────────────────
// Since function declarations can't be monkey-patched after the fact in strict
// mode, we convert it to a global async function that calls itself:
// We reassign the global handleSearch via prototype trick at parse time.
// The simplest safe pattern: reassign on DOMContentLoaded or immediately after
// the script (since this loads after app.js).

(function() {
  var _originalHandleSearch = window.handleSearch;

  window.handleSearch = async function() {
    if (typeof isLoggedIn === "function" && !isLoggedIn()) {
      if (typeof openAuthModal === "function") openAuthModal("login");
      if (typeof showToast    === "function") showToast("Please log in to get travel recommendations.");
      return;
    }

    var destinations = window.getDestinations();
    var source       = window.getSource();

    if (destinations.length === 0) {
      var inp = document.getElementById("city-input");
      if (inp) { inp.focus(); inp.style.outline = "2px solid rgba(239,68,68,.6)"; }
      setTimeout(function() { var el = document.getElementById("city-input"); if (el) el.style.outline = ""; }, 1800);
      return;
    }

    if (typeof setLoading  === "function") setLoading(true);
    if (typeof hideError   === "function") hideError();

    try {
      var isMulti  = !!(source || destinations.length > 1);
      var endpoint = isMulti ? "/api/plan-trip" : "/api/recommend";

      if (typeof setStep === "function") setStep("Fetching live weather data\u2026", 15, "weather");
      await (typeof sleep === "function" ? sleep(400) : new Promise(function(r){ setTimeout(r, 400); }));
      if (typeof setStep === "function") setStep("Building your travel plan\u2026", 50, "plan");

      var body = isMulti
        ? {
            source:            source,
            destinations:      destinations,
            budget:            typeof selectedBudget    !== "undefined" ? selectedBudget    : "mid-range",
            interests:         typeof selectedInterests !== "undefined" ? [...selectedInterests] : [],
            number_of_days:    typeof numberOfDays      !== "undefined" ? numberOfDays      : 3,
            number_of_persons: typeof numberOfPersons   !== "undefined" ? numberOfPersons   : 1,
          }
        : {
            city:              destinations[0],
            budget:            typeof selectedBudget    !== "undefined" ? selectedBudget    : "mid-range",
            interests:         typeof selectedInterests !== "undefined" ? [...selectedInterests] : [],
            number_of_days:    typeof numberOfDays      !== "undefined" ? numberOfDays      : 3,
            number_of_persons: typeof numberOfPersons   !== "undefined" ? numberOfPersons   : 1,
          };

      var headers = typeof authHeaders === "function" ? authHeaders() : { "Content-Type": "application/json" };
      var res     = await fetch(endpoint, { method: "POST", headers: headers, body: JSON.stringify(body) });

      if (typeof setStep === "function") setStep("Searching top hotels\u2026", 80, "hotels");
      var data = await res.json();
      if (typeof setStep === "function") { setStep("Done!", 100, "done"); }
      await (typeof sleep === "function" ? sleep(300) : new Promise(function(r){ setTimeout(r, 300); }));

      if (res.status === 401) {
        if (typeof clearAuthState === "function") clearAuthState();
        if (typeof updateNavAuth  === "function") updateNavAuth();
        if (typeof openAuthModal  === "function") openAuthModal("login");
        if (typeof showToast      === "function") showToast("Your session expired. Please log in again.");
        return;
      }

      if (!res.ok) {
        if (typeof showError === "function") showError(data.error || "Something went wrong.");
        return;
      }

      if (typeof savePreferences === "function") savePreferences(destinations[0], body.budget, body.interests);
      renderAll(data, isMulti);

    } catch (err) {
      console.error("handleSearch (extensions) error:", err);
      if (typeof showError === "function") showError("Could not connect to the server. Please try again.");
    } finally {
      if (typeof setLoading === "function") setLoading(false);
    }
  };
})();

// ── renderAll override ────────────────────────────────────────────────────────
(function() {
  window.renderAll = function(data, isMulti) {
    var empty   = document.getElementById("results-empty");
    var content = document.getElementById("results-content");
    if (empty)   empty.classList.add("hidden");
    if (content) { content.classList.remove("hidden"); content.scrollIntoView({ behavior: "smooth", block: "start" }); }

    var topbar = document.getElementById("results-topbar");
    var lbl    = document.getElementById("results-city-label");
    if (topbar && lbl) {
      var city = data.city || (data.destinations && data.destinations[0]) || "";
      var bMap = { "budget":"Budget","mid-range":"Mid-Range","medium":"Mid-Range","high":"Luxury","luxury":"Luxury" };
      lbl.innerHTML = "\uD83D\uDCCD <strong>" + cap(city) + "</strong> <span class=\"topbar-budget\">" + (bMap[data.budget] || cap(data.budget)) + "</span>";
      topbar.classList.remove("hidden");
    }

    if (typeof renderWeather  === "function") renderWeather(data.weather);
    if (typeof renderWRec     === "function") renderWRec(data.weather_rec);
    if (typeof renderTips     === "function") renderTips(data.tips);

    var nd = typeof numberOfDays    !== "undefined" ? numberOfDays    : (data.number_of_days    || 3);
    var np = typeof numberOfPersons !== "undefined" ? numberOfPersons : (data.number_of_persons || 1);
    if (typeof renderCost     === "function") renderCost(data.cost_estimate, data.group_info, data.group_activities, nd, np);
    if (typeof renderPlan     === "function") renderPlan(data.travel_plan);
    if (typeof renderItinerary=== "function") renderItinerary(data.itinerary);

    var city   = data.city || (data.destinations && data.destinations[0]) || "";
    var budget = data.budget || (typeof selectedBudget !== "undefined" ? selectedBudget : "mid-range");
    if (typeof renderHotels   === "function") renderHotels(data.hotels, city, budget);

    // Transport (multi only)
    var transportCard = document.getElementById("transport-card");
    if (isMulti && data.transport_legs && data.transport_legs.length > 0) {
      renderTransportLegs(data.transport_legs, data.source, data.destinations);
    } else if (transportCard) {
      transportCard.classList.add("hidden");
    }

    // Restaurants
    var restCard = document.getElementById("restaurants-card");
    if (data.restaurants && data.restaurants.length > 0) {
      renderRestaurants(data.restaurants, city);
    } else if (restCard) {
      restCard.classList.add("hidden");
    }
  };
})();

// ── Transport Legs renderer ───────────────────────────────────────────────────
var TRANSPORT_ICONS = { "Bus": "\uD83D\uDE8C", "Cab": "\uD83D\uDE95", "Bike": "\uD83C\uDFCD\uFE0F", "Flight": "\u2708\uFE0F" };

function renderTransportLegs(legs, source, destinations) {
  var card = document.getElementById("transport-card");
  var wrap = document.getElementById("transport-legs-wrap");
  if (!legs || legs.length === 0) { if (card) card.classList.add("hidden"); return; }
  if (card) card.classList.remove("hidden");

  var stops = [source].concat(destinations || []).filter(Boolean);
  var sub   = document.getElementById("transport-subtitle");
  if (sub) sub.textContent = stops.join(" \u2192 ") + " \u00B7 " + legs.length + " leg" + (legs.length !== 1 ? "s" : "");

  if (!wrap) return;
  wrap.innerHTML = legs.map(function(leg, i) {
    var fromCity = stops[i]     || "Source";
    var toCity   = stops[i + 1] || "Destination";

    if (leg.error) {
      return '<div class="transport-leg-block">' +
        '<div class="transport-leg-header">' + fromCity + ' \u2192 ' + toCity + '</div>' +
        '<p class="transport-error">\u26A0 ' + leg.error + '</p>' +
      '</div>';
    }

    var modes = leg.options || [];
    var distText = leg.distance_text ? '<span class="leg-dist">' + leg.distance_text + '</span>' : "";
    var modesHtml = modes.map(function(m) {
      var icon = TRANSPORT_ICONS[m.mode] || "\uD83D\uDE97";
      var cost = (m.total_cost || 0).toLocaleString();
      return '<div class="transport-mode-card">' +
        '<div class="tm-icon">' + icon + '</div>' +
        '<div class="tm-name">' + m.mode + '</div>' +
        '<div class="tm-cost">\u20B9' + cost + '</div>' +
        '<div class="tm-time">' + (m.duration_text || "") + '</div>' +
        '<div class="tm-note">' + (m.note || "") + '</div>' +
        '<button class="tm-book-btn" onclick="initiateTransportBooking(\'' +
          fromCity.replace(/'/g, "\\'") + '\',\'' + toCity.replace(/'/g, "\\'") + '\',\'' +
          m.mode + '\',' + (m.total_cost || 0) + ')">Book Now</button>' +
      '</div>';
    }).join("");

    return '<div class="transport-leg-block">' +
      '<div class="transport-leg-header">' +
        '<span class="leg-from">' + fromCity + '</span>' +
        '<span class="leg-arrow">\u2192</span>' +
        '<span class="leg-to">' + toCity + '</span>' +
        distText +
      '</div>' +
      '<div class="transport-modes-grid">' + modesHtml + '</div>' +
    '</div>';
  }).join("");
}

// ── Restaurant renderer ───────────────────────────────────────────────────────
function renderRestaurants(restaurants, city) {
  var card = document.getElementById("restaurants-card");
  var grid = document.getElementById("restaurants-grid");
  var sub  = document.getElementById("restaurants-subtitle");
  if (!restaurants || restaurants.length === 0) { if (card) card.classList.add("hidden"); return; }
  if (card) card.classList.remove("hidden");
  if (sub)  sub.textContent = "Top " + restaurants.length + " picks in " + cap(city);
  if (!grid) return;

  grid.innerHTML = restaurants.map(function(r) {
    var personsCount = typeof numberOfPersons !== "undefined" ? numberOfPersons : 1;
    var ratingHtml    = r.rating     ? '<span class="rest-rating">\u2B50 ' + r.rating     + '</span>' : "";
    var priceHtml     = r.price_range? '<span class="rest-price">'  + r.price_range  + '</span>' : "";
    var mealHtml      = r.meal_type  ? '<span class="rest-meal">'   + r.meal_type    + '</span>' : "";
    var specialtyHtml = r.specialty  ? '<div class="rest-specialty">\uD83C\uDF7D\uFE0F ' + r.specialty  + '</div>' : "";
    var descHtml      = r.description? '<p class="rest-desc">'      + r.description  + '</p>'   : "";
    var timingHtml    = r.timing     ? '<div class="rest-timing">\uD83D\uDD50 ' + r.timing + '</div>' : "";
    var nameSafe      = (r.name || "").replace(/'/g, "\\'");
    var citySafe      = cap(city).replace(/'/g, "\\'");

    return '<div class="restaurant-card">' +
      '<div class="rest-header">' +
        '<div class="rest-name">'    + (r.name    || "") + '</div>' +
        '<div class="rest-cuisine">' + (r.cuisine || "") + '</div>' +
      '</div>' +
      '<div class="rest-meta">' + ratingHtml + priceHtml + mealHtml + '</div>' +
      specialtyHtml + descHtml + timingHtml +
      '<button class="tm-book-btn" style="margin-top:10px" onclick="initiateRestaurantBooking(\'' +
        nameSafe + '\',\'' + citySafe + '\',' + personsCount + ')">Reserve Table</button>' +
    '</div>';
  }).join("");
}

// ── Payment Flow — Razorpay with auto-fallback ─────────────────────────────
var RAZORPAY_KEY = "rzp_live_SYpdi21cOjFAfJ";

window.initiateTransportBooking = async function(from, to, mode, totalCost) {
  if (typeof isLoggedIn === "function" && !isLoggedIn()) { openAuthModal("login"); return; }
  await startPayment(totalCost, "transport",
    mode + ": " + from + " \u2192 " + to,
    { from: from, to: to, mode: mode, destination: to });
};

window.initiateRestaurantBooking = async function(name, city, persons) {
  if (typeof isLoggedIn === "function" && !isLoggedIn()) { openAuthModal("login"); return; }
  var amount = (parseInt(persons) || 1) * 800;
  await startPayment(amount, "restaurant",
    "Table at " + name + ", " + city + " for " + persons + " person" + (persons !== 1 ? "s" : ""),
    { name: name, city: city, persons: persons, destination: city });
};

// ── Master payment dispatcher ─────────────────────────────────────────────────
// Tries Razorpay first; if order creation fails (e.g. keys not yet active),
// falls back to the built-in TripSense Pay modal automatically.
async function startPayment(amountInr, bookingType, description, details) {
  if (typeof showToast === "function") showToast("Initialising payment\u2026");

  try {
    var headers = typeof authHeaders === "function" ? authHeaders() : { "Content-Type": "application/json" };
    var res = await fetch("/api/create-payment-order", {
      method: "POST", headers: headers,
      body: JSON.stringify({ amount_inr: amountInr, booking_type: bookingType, description: description }),
    });
    var orderData = await res.json();

    // If Razorpay order created successfully, open Razorpay checkout
    if (res.ok && orderData.razorpay_order_id) {
      if (typeof window.Razorpay === "undefined") {
        console.warn("Razorpay SDK not loaded, falling back to custom modal.");
        showPaymentModal(amountInr, bookingType, description, details);
        return;
      }
      var user = (typeof authState !== "undefined" && authState && authState.user) || {};
      var destination = details.destination || details.city || details.to || details.name || "";

      var rzpOptions = {
        key:         RAZORPAY_KEY,
        amount:      orderData.amount,
        currency:    "INR",
        name:        "TripSense AI",
        description: description,
        order_id:    orderData.razorpay_order_id,
        handler: function(response) {
          verifyRazorpayPayment(
            response.razorpay_order_id,
            response.razorpay_payment_id,
            response.razorpay_signature,
            bookingType, destination, amountInr, details
          );
        },
        prefill: { name: user.username || "", email: user.email || "" },
        theme:   { color: "#166534" },
        modal: {
          ondismiss: function() {
            if (typeof showToast === "function") showToast("Payment cancelled.");
          }
        }
      };

      var rzp = new window.Razorpay(rzpOptions);
      rzp.on("payment.failed", function(resp) {
        if (typeof showToast === "function") showToast("\u26A0 Payment failed: " + (resp.error && resp.error.description || "Please try again."));
      });
      rzp.open();
      return;
    }

    // Razorpay order creation failed — log and fall back
    console.warn("Razorpay order creation failed:", orderData.error || res.status, "— using TripSense Pay modal.");
    showPaymentModal(amountInr, bookingType, description, details);

  } catch (err) {
    console.error("Payment init error:", err);
    // Network/server error — fall back to custom modal
    showPaymentModal(amountInr, bookingType, description, details);
  }
}

// ── Razorpay payment verification (called after Razorpay checkout succeeds) ───
async function verifyRazorpayPayment(orderId, paymentId, signature, bookingType, destination, amountInr, details) {
  if (typeof showToast === "function") showToast("Verifying payment\u2026");
  try {
    var headers = typeof authHeaders === "function" ? authHeaders() : { "Content-Type": "application/json" };
    var res = await fetch("/api/verify-payment", {
      method: "POST", headers: headers,
      body: JSON.stringify({
        razorpay_order_id:   orderId,
        razorpay_payment_id: paymentId,
        razorpay_signature:  signature,
        booking_type:        bookingType,
        destination:         destination,
        amount_inr:          amountInr,
        details:             details,
      }),
    });
    var data = await res.json();
    if (!res.ok) {
      if (typeof showToast === "function") showToast("\u26A0 " + (data.error || "Verification failed"));
      return;
    }
    showBookingConfirmation(data.booking);
  } catch (err) {
    console.error("Razorpay verification error:", err);
    if (typeof showToast === "function") showToast("Verification error. Contact support with your payment ID.");
  }
}


// ── Payment Modal HTML ────────────────────────────────────────────────────────
function ensurePaymentModalExists() {
  if (document.getElementById("ts-pay-modal")) return;
  var el = document.createElement("div");
  el.id = "ts-pay-modal";
  el.className = "ts-pay-overlay hidden";
  el.innerHTML = [
    '<div class="ts-pay-box">',
      '<div class="ts-pay-header">',
        '<div class="ts-pay-brand">\uD83C\uDF0D TripSense Pay</div>',
        '<button class="ts-pay-close" onclick="closePaymentModal()">\u00D7</button>',
      '</div>',
      '<div class="ts-pay-summary">',
        '<div class="ts-pay-desc" id="ts-pay-desc"></div>',
        '<div class="ts-pay-amount" id="ts-pay-amount"></div>',
      '</div>',
      '<div class="ts-pay-form">',
        '<div class="ts-pay-field">',
          '<label>Card Number</label>',
          '<input id="ts-card-num" type="text" placeholder="4242 4242 4242 4242" maxlength="19" autocomplete="cc-number">',
        '</div>',
        '<div class="ts-pay-row">',
          '<div class="ts-pay-field">',
            '<label>Expiry</label>',
            '<input id="ts-card-exp" type="text" placeholder="MM / YY" maxlength="7" autocomplete="cc-exp">',
          '</div>',
          '<div class="ts-pay-field">',
            '<label>CVV</label>',
            '<input id="ts-card-cvv" type="password" placeholder="\u2022\u2022\u2022" maxlength="4" autocomplete="cc-csc">',
          '</div>',
        '</div>',
        '<div class="ts-pay-field">',
          '<label>Name on Card</label>',
          '<input id="ts-card-name" type="text" placeholder="Your full name" autocomplete="cc-name">',
        '</div>',
        '<button class="ts-pay-btn" id="ts-pay-submit-btn" onclick="submitPayment()">\uD83D\uDD12 Pay Now \u2014 <span id="ts-pay-btn-amt"></span></button>',
        '<p class="ts-pay-note">\uD83D\uDD12 Secured \u00B7 256-bit SSL encrypted \u00B7 Powered by TripSense Payments</p>',
      '</div>',
    '</div>'
  ].join("");
  document.body.appendChild(el);
  el.addEventListener("click", function(e) { if (e.target === el) closePaymentModal(); });

  // Card number formatting
  document.getElementById("ts-card-num").addEventListener("input", function() {
    var v = this.value.replace(/\D/g, "").slice(0, 16);
    this.value = v.replace(/(.{4})/g, "$1 ").trim();
  });
  // Expiry formatting
  document.getElementById("ts-card-exp").addEventListener("input", function() {
    var v = this.value.replace(/\D/g, "").slice(0, 4);
    if (v.length >= 3) v = v.slice(0, 2) + " / " + v.slice(2);
    this.value = v;
  });
}

var _pendingPayment = null;

function showPaymentModal(amountInr, bookingType, description, details) {
  ensurePaymentModalExists();
  _pendingPayment = { amountInr: amountInr, bookingType: bookingType, description: description, details: details };

  var desc   = document.getElementById("ts-pay-desc");
  var amt    = document.getElementById("ts-pay-amount");
  var btnAmt = document.getElementById("ts-pay-btn-amt");
  var fmtAmt = "\u20B9" + Math.round(amountInr).toLocaleString("en-IN");

  if (desc)   desc.textContent   = description;
  if (amt)    amt.textContent    = fmtAmt;
  if (btnAmt) btnAmt.textContent = fmtAmt;

  // Clear form
  ["ts-card-num","ts-card-exp","ts-card-cvv","ts-card-name"].forEach(function(id) {
    var el = document.getElementById(id); if (el) el.value = "";
  });

  var modal = document.getElementById("ts-pay-modal");
  modal.classList.remove("hidden");
  setTimeout(function() { modal.classList.add("open"); }, 10);
}

window.closePaymentModal = function() {
  var modal = document.getElementById("ts-pay-modal");
  if (!modal) return;
  modal.classList.remove("open");
  setTimeout(function() { modal.classList.add("hidden"); }, 250);
};

window.submitPayment = async function() {
  if (!_pendingPayment) return;

  // Basic validation
  var num  = (document.getElementById("ts-card-num")  || {}).value || "";
  var exp  = (document.getElementById("ts-card-exp")  || {}).value || "";
  var cvv  = (document.getElementById("ts-card-cvv")  || {}).value || "";
  var name = (document.getElementById("ts-card-name") || {}).value || "";

  var numClean = num.replace(/\s/g, "");
  if (numClean.length < 16) { if (typeof showToast==="function") showToast("\u26A0 Enter a valid 16-digit card number."); return; }
  if (exp.replace(/\D/g,"").length < 4) { if (typeof showToast==="function") showToast("\u26A0 Enter a valid expiry date."); return; }
  if (cvv.length < 3) { if (typeof showToast==="function") showToast("\u26A0 Enter a valid CVV."); return; }
  if (name.trim().length < 2) { if (typeof showToast==="function") showToast("\u26A0 Enter the name on card."); return; }

  var btn = document.getElementById("ts-pay-submit-btn");
  if (btn) { btn.disabled = true; btn.textContent = "\u23F3 Processing\u2026"; }

  try {
    var headers = typeof authHeaders === "function" ? authHeaders() : { "Content-Type": "application/json" };
    var p = _pendingPayment;
    var destination = (p.details && (p.details.destination || p.details.city || p.details.to || p.details.name)) || "";

    var res = await fetch("/api/simulate-payment", {
      method: "POST", headers: headers,
      body: JSON.stringify({
        amount_inr:   p.amountInr,
        booking_type: p.bookingType,
        description:  p.description,
        destination:  destination,
        details:      p.details
      })
    });
    var data = await res.json();

    if (!res.ok) {
      if (typeof showToast==="function") showToast("\u26A0 " + (data.error || "Payment failed. Try again."));
      if (btn) { btn.disabled = false; btn.innerHTML = "\uD83D\uDD12 Pay Now \u2014 <span id=\"ts-pay-btn-amt\">" + "\u20B9" + Math.round(p.amountInr).toLocaleString("en-IN") + "</span>"; }
      return;
    }

    closePaymentModal();
    _pendingPayment = null;
    showBookingConfirmation(data.booking);

  } catch (err) {
    console.error("Payment error:", err);
    if (typeof showToast==="function") showToast("Connection error. Please try again.");
    if (btn) { btn.disabled = false; btn.innerHTML = "\uD83D\uDD12 Pay Now \u2014 <span id=\"ts-pay-btn-amt\">" + "\u20B9" + Math.round(_pendingPayment.amountInr).toLocaleString("en-IN") + "</span>"; }
  }
};

// ── Booking Confirmation Modal ────────────────────────────────────────────────
function showBookingConfirmation(booking) {
  var refEl = document.getElementById("booking-ref");
  var detEl = document.getElementById("booking-modal-details");
  if (refEl) refEl.textContent = booking.reference || booking.id || "\u2014";
  if (detEl) detEl.innerHTML =
    '<div class="booking-detail-row"><span>Type</span><strong>' + cap(booking.booking_type || "") + '</strong></div>' +
    '<div class="booking-detail-row"><span>Destination</span><strong>' + (booking.destination || "\u2014") + '</strong></div>' +
    '<div class="booking-detail-row"><span>Amount</span><strong>\u20B9' + (booking.amount_inr || 0).toLocaleString() + '</strong></div>' +
    '<div class="booking-detail-row"><span>Payment ID</span><strong>' + (booking.payment_id || "\u2014") + '</strong></div>';
  var modal = document.getElementById("booking-modal");
  if (modal) { modal.classList.remove("open"); setTimeout(function() { modal.classList.add("hidden"); }, 250); }
};

// ── AI TRAVEL CHATBOT LOGIC ───────────────────────────────────────────────────
(function() {
  var history = []; // Stores {role, content}

  window.toggleChat = function() {
    var chatWindow = document.getElementById("ts-chat-window");
    var chatBtn    = document.getElementById("ts-chat-btn");
    var chatInput  = document.getElementById("ts-chat-input");
    if (!chatWindow) return;

    var isOpen = chatWindow.classList.contains("open");
    if (isOpen) {
      chatWindow.classList.remove("open");
      if (chatBtn) {
        var icon = chatBtn.querySelector("span");
        if (icon) icon.textContent = "💬";
      }
    } else {
      chatWindow.classList.add("open");
      if (chatBtn) {
        var icon = chatBtn.querySelector("span");
        if (icon) icon.textContent = "×";
      }
      if (chatInput) setTimeout(function() { chatInput.focus(); }, 100);
    }
  };

  window.sendChatMessage = async function() {
    var chatInput = document.getElementById("ts-chat-input");
    var chatBody  = document.getElementById("ts-chat-body");
    var chatSend  = document.getElementById("ts-chat-send");
    if (!chatInput || !chatBody || !chatSend || chatSend.disabled) return;

    var text = chatInput.value.trim();
    if (!text) return;

    // Add user message to UI
    appendMessage("user", text);
    chatInput.value = "";
    
    // Disable input while thinking
    chatInput.disabled = true;
    chatSend.disabled = true;

    // Add "Typing..." indicator
    var typing = document.createElement("div");
    typing.className = "ts-chat-typing";
    typing.id = "ts-chat-typing-indicator";
    typing.textContent = "AI is thinking...";
    chatBody.appendChild(typing);
    chatBody.scrollTop = chatBody.scrollHeight;

    try {
      var res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: history })
      });
      var data = await res.json();
      
      var indicator = document.getElementById("ts-chat-typing-indicator");
      if (indicator) indicator.remove();

      if (res.ok && data.reply) {
        appendMessage("assistant", data.reply);
        history.push({ role: "user", content: text });
        history.push({ role: "assistant", content: data.reply });
        if (history.length > 20) history = history.slice(-20);
      } else {
        appendMessage("assistant", "Sorry, I'm having trouble thinking right now. Check your connection!");
      }
    } catch (err) {
      var indicator = document.getElementById("ts-chat-typing-indicator");
      if (indicator) indicator.remove();
      appendMessage("assistant", "Connection error. Please try again later.");
    } finally {
      chatInput.disabled = false;
      chatSend.disabled = false;
      chatInput.focus();
    }
  };

  function appendMessage(role, content) {
    var chatBody = document.getElementById("ts-chat-body");
    if (!chatBody) return;
    var msg = document.createElement("div");
    msg.className = "ts-chat-msg " + (role === "assistant" ? "bot" : "user");
    msg.textContent = content;
    chatBody.appendChild(msg);
    chatBody.scrollTop = chatBody.scrollHeight;
  }

  // Initialisation when document is ready
  function initChat() {
    var btn = document.getElementById("ts-chat-btn");
    if (btn) btn.addEventListener("click", toggleChat);

    var input = document.getElementById("ts-chat-input");
    if (input) {
      input.addEventListener("keypress", function(e) {
        if (e.key === "Enter") sendChatMessage();
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initChat);
  } else {
    initChat();
  }
})();

window.closeBookingModal = function() {
  var modal = document.getElementById("booking-modal");
  if (!modal) return;
  modal.classList.remove("open");
  setTimeout(function() { modal.classList.add("hidden"); }, 220);
};

// Re-bind Esc key for booking modal
document.addEventListener("keydown", function(e) {
  if (e.key === "Escape") {
    if (typeof closeBookingModal === "function") closeBookingModal();
  }
});

// ── Hotel Booking — opens Booking.com ───────────────────────────────────────
window.initiateHotelBooking = function(hotelName, city, days, pricePerNightInr, hotelUrl) {
  // If we have the hotel's direct Booking.com URL, open it directly
  if (hotelUrl && hotelUrl !== "#" && hotelUrl.length > 5) {
    window.open(hotelUrl, "_blank", "noopener,noreferrer");
    return;
  }
  // Otherwise search Booking.com for the hotel + city
  var query = encodeURIComponent((hotelName ? hotelName + " " : "") + city);
  var bookingUrl = "https://www.booking.com/searchresults.html?ss=" + query + "&lang=en-gb";
  window.open(bookingUrl, "_blank", "noopener,noreferrer");
};

// ── Override renderHotels — INR prices + Book Hotel button ────────────────────
(function() {
  var USD_TO_INR = 85;

  window.renderHotels = function(hotelData, city, budget) {
    var card     = document.getElementById("hotels-card");
    var grid     = document.getElementById("hotels-grid");
    var msg      = document.getElementById("hotels-message");
    var subtitle = document.getElementById("hotels-subtitle");
    if (!card)  return;
    card.classList.remove("hidden");

    if (hotelData && hotelData.error) {
      if (grid) grid.innerHTML = "";
      if (msg)  { msg.textContent = "\u26A0 " + hotelData.error; msg.classList.remove("hidden"); }
      if (subtitle) subtitle.textContent = "";
      return;
    }

    var hotels = (hotelData && hotelData.hotels) || [];
    var fs     = (hotelData && hotelData.filter_summary) || null;

    if (hotels.length === 0) {
      if (grid) grid.innerHTML = "<p style=\"color:#94a3b8;font-size:.88rem;\">No hotels found for " + city + ".</p>";
      return;
    }

    if (msg) msg.classList.add("hidden");

    if (subtitle) {
      if (fs) {
        var pMin  = Math.round((fs.price_min || 0) * USD_TO_INR).toLocaleString("en-IN");
        var pMax  = fs.price_max ? Math.round(fs.price_max * USD_TO_INR).toLocaleString("en-IN") : null;
        var range = pMax ? "\u20B9" + pMin + "\u2013\u20B9" + pMax + "/night" : "\u20B9" + pMin + "+/night";
        var sort  = { price_asc:"Cheapest first", rating_desc:"Top-rated first", relevance:"Best match" }[fs.sort] || "";
        subtitle.textContent = "Top " + hotels.length + " \u00B7 " + (fs.tier || "") + " \u00B7 " + range + (sort ? " \u00B7 " + sort : "");
      } else {
        subtitle.textContent = hotels.length + " properties \u00B7 " + (budget || "");
      }
    }

    if (!grid) return;

    var hotelDays = (typeof numberOfDays !== "undefined" ? numberOfDays : 3);

    grid.innerHTML = hotels.map(function(h) {
      var rawPrice = h.price || 0;
      var priceInr = rawPrice > 0 ? (rawPrice < 500 ? Math.round(rawPrice * USD_TO_INR) : Math.round(rawPrice)) : 0;
      var priceStr = priceInr > 0 ? "\u20B9" + priceInr.toLocaleString("en-IN") + "/night" : "Price on request";
      var stars    = h.stars ? "\u2605".repeat(Math.min(h.stars, 5)) : "";
      var rating   = (h.rating && h.rating !== "N/A") ? h.rating : null;
      var photo    = h.photo
        ? '<img class="hotel-photo" src="' + h.photo + '" alt="" loading="lazy" onerror="this.style.display=\'none\'">'
        : '<div class="hotel-photo-ph">\uD83C\uDFE8</div>';
      var score    = h.relevance_score || 0;
      var scorePct = Math.round(score * 100);
      var showScore= fs && fs.sort === "relevance" && score > 0;
      var rwMap    = { 9:"Exceptional", 8:"Excellent", 7:"Very Good", 6:"Good" };
      var rwWord   = rating ? (rwMap[Math.floor(parseFloat(rating))] || "Good") : "";
      var hotelUrl = h.url || "";
      var safeId   = "hotel-" + Math.random().toString(36).slice(2, 8);
      var safeName = (h.name || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;");

      return '<div class="hotel-card">' +
        photo +
        '<div class="hotel-info">' +
          '<div class="hotel-name">' + safeName + '</div>' +
          (stars ? '<div class="hotel-stars">' + stars + '</div>' : "") +
          '<div class="hotel-meta-row">' +
            '<span class="hotel-price">' + priceStr + '</span>' +
            (rating ? '<span class="hotel-rating-btn">' + rating + '</span>' +
              '<span class="hotel-review-lbl">' + rwWord + '</span>' : "") +
          '</div>' +
          (showScore ? '<div class="hotel-score-row">' +
            '<span class="hotel-score-lbl">Match</span>' +
            '<div class="hotel-score-bar"><div class="hotel-score-fill" style="width:' + scorePct + '%"></div></div>' +
            '<span class="hotel-score-pct">' + scorePct + '%</span>' +
          '</div>' : "") +
          (h.address ? '<div class="hotel-addr">\uD83D\uDCCD ' + h.address + '</div>' : "") +
          '<div class="hotel-actions">' +
            '<button class="tm-book-btn hotel-book-btn" ' +
              'data-hotel-name="' + safeName + '" ' +
              'data-hotel-city="' + city + '" ' +
              'data-hotel-days="' + hotelDays + '" ' +
              'data-hotel-price="' + priceInr + '" ' +
              'data-hotel-url="' + (hotelUrl || "") + '"' +
            '>\uD83C\uDFE8 Book on Booking.com</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    }).join("");

    // Attach click handlers via event delegation
    grid.querySelectorAll(".hotel-book-btn").forEach(function(btn) {
      btn.addEventListener("click", function(e) {
        e.stopPropagation();
        window.initiateHotelBooking(
          this.dataset.hotelName  || "",
          this.dataset.hotelCity  || city,
          parseInt(this.dataset.hotelDays)  || 3,
          parseInt(this.dataset.hotelPrice) || 0,
          this.dataset.hotelUrl  || ""
        );
      });
    });
  };
})();

// ── Override renderCost — show in INR ─────────────────────────────────────────
(function() {
  var USD_TO_INR = 85;

  window.renderCost = function(cost, groupInfo, groupActivities, numDays, numPersons) {
    var card = document.getElementById("cost-card");
    if (!cost) { if (card) card.classList.add("hidden"); return; }
    if (card) card.classList.remove("hidden");

    function toInr(usd) { return Math.round((usd || 0) * USD_TO_INR); }
    function fmt(inr)   { return "\u20B9" + inr.toLocaleString("en-IN"); }

    var sub = document.getElementById("cost-subtitle");
    if (sub) sub.textContent = numDays + " day" + (numDays !== 1 ? "s" : "") + " \u00B7 " + numPersons + " person" + (numPersons !== 1 ? "s" : "");

    var totalEl = document.getElementById("cost-total");
    if (totalEl) totalEl.textContent = fmt(toInr(cost.total_cost));

    var bd   = cost.breakdown || {};
    var cats = [
      { key:"accommodation", label:"\uD83C\uDFE8 Accommodation", color:"var(--green)" },
      { key:"food",          label:"\uD83C\uDF5C Food & Dining",  color:"#f59e0b" },
      { key:"activities",    label:"\uD83C\uDFAF Activities",     color:"#6366f1" },
      { key:"transport",     label:"\uD83D\uDE8C Transport",      color:"#06b6d4" },
    ];
    var grandTotal = Object.values(bd).reduce(function(s, v) { return s + v; }, 0) || 1;

    var bdEl = document.getElementById("cost-breakdown");
    if (bdEl) {
      bdEl.innerHTML = cats.map(function(c) {
        var val    = bd[c.key] || 0;
        var valInr = toInr(val);
        var pct    = Math.round((val / grandTotal) * 100);
        return '<div class="cost-item">' +
          '<div class="cost-item-row">' +
            '<span class="cost-item-lbl">' + c.label + '</span>' +
            '<span class="cost-item-val">' + fmt(valInr) + '</span>' +
          '</div>' +
          '<div class="cost-bar-bg">' +
            '<div class="cost-bar-fill" style="width:' + pct + '%;background:' + c.color + '"></div>' +
          '</div>' +
        '</div>';
      }).join("");

      if (cost.group_discount_pct > 0) {
        var discNote = document.createElement("p");
        discNote.className = "cost-discount-note";
        discNote.textContent = "\u2705 " + cost.group_discount_pct + "% group discount applied";
        bdEl.appendChild(discNote);
      }

      var ppNote = document.createElement("p");
      ppNote.className = "cost-pp-note";
      ppNote.textContent = "\u2248 " + fmt(toInr(cost.per_person_total)) + " per person \u00B7 Estimated in \u20B9INR";
      bdEl.appendChild(ppNote);
    }

    var banner = document.getElementById("group-banner");
    if (banner && groupInfo) {
      banner.innerHTML = '<span class="group-emoji">' + groupInfo.emoji + '</span>' +
        '<span class="group-label">' + groupInfo.label + '</span>' +
        '<span class="group-desc">' + groupInfo.description + '</span>';
    }

    if (groupActivities && groupActivities.length > 0) {
      var wrap = document.getElementById("group-acts-wrap");
      var list = document.getElementById("group-acts-list");
      if (list) list.innerHTML = groupActivities.map(function(a) { return "<li>" + a + "</li>"; }).join("");
      if (wrap) wrap.classList.remove("hidden");
    }
  };
})();
