/* Shared script for the protected pages: guard, user name, logout */
(() => {
  let user = null;
  try { user = JSON.parse(localStorage.getItem("ahlia_user")); } catch {}
  if (!user) { location.replace("login.html?next=" + encodeURIComponent(location.pathname.split("/").pop())); return; }

  document.querySelectorAll("[data-user-name]").forEach((el) => (el.textContent = user.name));

  document.getElementById("logout")?.addEventListener("click", () => {
    if (window.AhliaStore) AhliaStore.logout();
    else { localStorage.removeItem("ahlia_user"); location.href = "index.html"; }
  });
})();
