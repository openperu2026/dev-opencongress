document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.getElementById("edit-mode-toggle");
  const bar = document.getElementById("edit-toggle-bar");

  if (toggle) {
    toggle.addEventListener("change", () => {
      const on = toggle.checked;
      // Re-query on every toggle rather than caching a NodeList at load
      // time -- rows added later via "+ Add another" wouldn't be in a
      // snapshot taken before they existed.
      document.querySelectorAll(".edit-gated").forEach((el) => {
        el.disabled = !on;
      });
      if (bar) bar.classList.toggle("edit-mode-on", on);
      document.body.classList.toggle("edit-mode-on", on);
    });
  }

  const addRowsContainer = document.getElementById("add-rows");
  const addRowTemplate = document.getElementById("add-row-template");
  const addRowBtn = document.getElementById("add-row-btn");

  if (addRowBtn && addRowsContainer && addRowTemplate) {
    addRowBtn.addEventListener("click", () => {
      // Only reachable while Edit Mode is on (the button itself is
      // edit-gated), so the cloned row's controls start enabled --
      // the template intentionally has no `disabled` attribute.
      addRowsContainer.appendChild(addRowTemplate.content.cloneNode(true));
    });

    addRowsContainer.addEventListener("click", (event) => {
      if (!event.target.classList.contains("remove-row-btn")) return;
      const rows = addRowsContainer.querySelectorAll(".add-row");
      // Always leave at least one row so the form has something to submit.
      if (rows.length > 1) {
        event.target.closest(".add-row").remove();
      }
    });
  }

  const nav = document.getElementById("prev-next");
  if (nav) {
    const ids = (nav.dataset.ids || "").split(",").filter(Boolean);
    const pos = parseInt(nav.dataset.pos, 10);
    if (ids.length && !Number.isNaN(pos)) {
      const idsParam = encodeURIComponent(ids.join(","));
      const parts = [];
      if (pos > 0) {
        parts.push(
          `<a href="/review/${ids[pos - 1]}?ids=${idsParam}&pos=${pos - 1}">&laquo; Prev</a>`
        );
      }
      if (pos < ids.length - 1) {
        parts.push(
          `<a href="/review/${ids[pos + 1]}?ids=${idsParam}&pos=${pos + 1}">Next &raquo;</a>`
        );
      }
      nav.innerHTML = parts.join(" ");
    }
  }
});
