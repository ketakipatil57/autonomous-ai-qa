/**
 * ShopEasy Sample Application JavaScript
 * Controls products, cart, checkout, login, and planted bugs logic.
 */

// Available catalog products (Section 5: 3 products with name, price, and "Add to cart")
const PRODUCTS = [
  { id: "p1", name: "Wireless Headphones", price: 99.00, desc: "Premium noise-canceling headphones." },
  { id: "p2", name: "Mechanical Keyboard", price: 149.00, desc: "RGB backlit mechanical keyboard." },
  { id: "p3", name: "Ergonomic Mouse", price: 49.00, desc: "High-precision ergonomic wireless mouse." }
];

// Determine if planted bugs are enabled
function areBugsEnabled() {
  const urlParams = new URLSearchParams(window.location.search);
  const q = urlParams.get("bugs");
  if (q === "on") {
    sessionStorage.setItem("sample_bugs", "on");
    return true;
  }
  if (q === "off") {
    sessionStorage.setItem("sample_bugs", "off");
    return false;
  }

  const stored = sessionStorage.getItem("sample_bugs");
  if (stored === "on") return true;
  if (stored === "off") return false;

  if (typeof window.SERVER_SAMPLE_BUGS !== "undefined") {
    return window.SERVER_SAMPLE_BUGS === "on";
  }

  return true; // Default fallback: on
}

// Set up bugs toggle UI in footer
function initBugToggleUI() {
  const statusEl = document.getElementById("bug-status-indicator");
  if (statusEl) {
    const isEnabled = areBugsEnabled();
    statusEl.textContent = isEnabled ? "ON" : "OFF";
    statusEl.className = "bug-status-tag " + (isEnabled ? "on" : "off");
  }

  const toggleBtn = document.getElementById("toggle-bugs-btn");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", (e) => {
      e.preventDefault();
      const current = areBugsEnabled();
      const next = current ? "off" : "on";
      sessionStorage.setItem("sample_bugs", next);
      const url = new URL(window.location.href);
      url.searchParams.set("bugs", next);
      window.location.href = url.toString();
    });
  }
}

// Cart Storage Helpers
function getCart() {
  try {
    const raw = localStorage.getItem("sample_app_cart");
    return raw ? JSON.parse(raw) : [];
  } catch (err) {
    return [];
  }
}

function saveCart(cart) {
  localStorage.setItem("sample_app_cart", JSON.stringify(cart));
}

function clearCart() {
  localStorage.removeItem("sample_app_cart");
}

function addToCart(productId) {
  const product = PRODUCTS.find(p => p.id === productId);
  if (!product) return;

  const cart = getCart();
  const existing = cart.find(item => item.id === productId);

  if (existing) {
    existing.quantity += 1;
  } else {
    cart.push({
      id: product.id,
      name: product.name,
      price: product.price,
      quantity: 1
    });
  }

  saveCart(cart);
  updateCartBadge();
  updateCartSummary();
}

// BUG-05 Implementation
// Cart count badge does not update after adding a second item
function updateCartBadge() {
  const badge = document.getElementById("cart-badge");
  if (!badge) return;

  const cart = getCart();
  const totalItemsCount = cart.reduce((sum, item) => sum + item.quantity, 0);
  const distinctItemCount = cart.length;

  if (areBugsEnabled()) {
    // BUG-05: Cart count badge does not update after adding a second distinct item
    if (distinctItemCount >= 2) {
      badge.textContent = "1";
      return;
    }
  }

  badge.textContent = String(totalItemsCount);
}

// Index Page: Update cart count and subtotal
function updateCartSummary() {
  const countEl = document.getElementById("cart-count");
  const subtotalEl = document.getElementById("cart-subtotal");
  const cart = getCart();

  const totalItemsCount = cart.reduce((sum, item) => sum + item.quantity, 0);
  const subtotal = cart.reduce((sum, item) => sum + (item.price * item.quantity), 0);

  if (countEl) countEl.textContent = String(totalItemsCount);
  if (subtotalEl) subtotalEl.textContent = "$" + subtotal.toFixed(2);
}

// Index Page: Render products
function renderProducts() {
  const container = document.getElementById("products-container");
  if (!container) return;

  container.innerHTML = "";
  PRODUCTS.forEach(p => {
    const card = document.createElement("div");
    card.className = "product-card";
    card.innerHTML = `
      <div>
        <h3 class="product-title">${p.name}</h3>
        <p class="product-desc">${p.desc}</p>
      </div>
      <div>
        <div class="product-price">$${p.price.toFixed(2)}</div>
        <button class="btn add-to-cart-btn" data-product-id="${p.id}" id="add-${p.id}">Add to Cart</button>
      </div>
    `;
    container.appendChild(card);
  });

  // Attach button listeners
  container.querySelectorAll(".add-to-cart-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const pid = btn.getAttribute("data-product-id");
      addToCart(pid);
    });
  });

  updateCartSummary();
}

// BUG-02 Calculation Implementation
// Checkout total is wrong when quantity is 2 or more
function calculateCheckoutTotal(cart) {
  if (areBugsEnabled()) {
    // BUG-02: Total ignores quantity when quantity >= 2 (calculates each product's base price once)
    const hasMultiple = cart.some(item => item.quantity >= 2);
    if (hasMultiple) {
      return cart.reduce((sum, item) => sum + item.price, 0);
    }
  }
  return cart.reduce((sum, item) => sum + (item.price * item.quantity), 0);
}

// Checkout Page: Render cart items and total
function renderCheckout() {
  const tbody = document.getElementById("checkout-items");
  const totalEl = document.getElementById("checkout-total");
  if (!tbody || !totalEl) return;

  const cart = getCart();
  tbody.innerHTML = "";

  if (cart.length === 0) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="4" style="text-align: center; color: var(--text-muted); padding: 2rem;">No items in cart</td>`;
    tbody.appendChild(row);
    totalEl.textContent = "$0.00";
    return;
  }

  cart.forEach(item => {
    const row = document.createElement("tr");
    const itemTotal = item.price * item.quantity;
    row.innerHTML = `
      <td><strong>${item.name}</strong></td>
      <td>$${item.price.toFixed(2)}</td>
      <td>${item.quantity}</td>
      <td>$${itemTotal.toFixed(2)}</td>
    `;
    tbody.appendChild(row);
  });

  const grandTotal = calculateCheckoutTotal(cart);
  totalEl.textContent = "$" + grandTotal.toFixed(2);
}

// Checkout Page: BUG-03 Place order handler
function handleCheckoutOrder() {
  const messageEl = document.getElementById("order-message");
  if (!messageEl) return;

  const cart = getCart();

  if (cart.length === 0) {
    if (areBugsEnabled()) {
      // BUG-03: Allows placing an order with an empty cart
      messageEl.textContent = "Order placed";
      messageEl.className = "message success show";
      return;
    } else {
      // Correct validation: placing order with empty cart shows error
      messageEl.textContent = "Your cart is empty";
      messageEl.className = "message error show";
      return;
    }
  }

  // Non-empty cart: order successfully placed
  clearCart();
  renderCheckout();
  updateCartBadge();
  messageEl.textContent = "Order placed";
  messageEl.className = "message success show";
}

// Login Page: BUG-01 and BUG-04 handler
function handleLoginSubmit(event) {
  event.preventDefault();
  const emailInput = document.getElementById("email");
  const passwordInput = document.getElementById("password");
  const messageEl = document.getElementById("login-message");

  const email = emailInput ? emailInput.value.trim() : "";
  const password = passwordInput ? passwordInput.value : "";

  // Reset message
  messageEl.className = "message";
  messageEl.textContent = "";

  // Validation: Empty email or password
  if (!email || !password) {
    if (areBugsEnabled()) {
      // BUG-04: Empty email on login does not show the required message
      messageEl.className = "message";
      messageEl.textContent = "";
      return;
    } else {
      // Correct validation behaviour
      messageEl.textContent = "Email and password are required";
      messageEl.className = "message error show";
      return;
    }
  }

  // Credentials verification
  const validEmail = "test@demo.com";
  const validPassword = "Test@123";

  if (email === validEmail) {
    if (password === validPassword) {
      // Correct credentials
      sessionStorage.setItem("user", email);
      messageEl.textContent = "Login successful! Redirecting...";
      messageEl.className = "message success show";
      setTimeout(() => {
        window.location.href = "/index.html";
      }, 400);
      return;
    } else {
      // Wrong password
      if (areBugsEnabled()) {
        // BUG-01: Login accepts a wrong password for the valid email
        sessionStorage.setItem("user", email);
        messageEl.textContent = "Login successful! Redirecting...";
        messageEl.className = "message success show";
        setTimeout(() => {
          window.location.href = "/index.html";
        }, 400);
        return;
      } else {
        // Correct behavior: show "Invalid email or password" and stay on login page
        messageEl.textContent = "Invalid email or password";
        messageEl.className = "message error show";
        return;
      }
    }
  } else {
    // Unrecognized email
    messageEl.textContent = "Invalid email or password";
    messageEl.className = "message error show";
  }
}

// User session display
function initUserSession() {
  const user = sessionStorage.getItem("user");
  const loginLink = document.getElementById("nav-login-link");
  if (loginLink && user) {
    loginLink.textContent = "Logout (" + user.split("@")[0] + ")";
    loginLink.href = "#";
    loginLink.addEventListener("click", (e) => {
      e.preventDefault();
      sessionStorage.removeItem("user");
      window.location.reload();
    });
  }
}

// Initialization on DOMContentLoaded
document.addEventListener("DOMContentLoaded", () => {
  initBugToggleUI();
  updateCartBadge();
  initUserSession();

  // Page-specific initialization
  if (document.getElementById("products-container")) {
    renderProducts();
  }

  if (document.getElementById("checkout-items")) {
    renderCheckout();
    const placeOrderBtn = document.getElementById("place-order-btn");
    if (placeOrderBtn) {
      placeOrderBtn.addEventListener("click", handleCheckoutOrder);
    }
  }

  const loginForm = document.getElementById("login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", handleLoginSubmit);
  }
});
