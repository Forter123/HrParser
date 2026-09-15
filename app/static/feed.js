(function () {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws/feed`);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "status_changed") {
      const select = document.querySelector(
        `.status-select[data-candidate-id="${msg.payload.candidate_id}"]`
      );
      if (select) {
        select.value = msg.payload.status;
        select.dataset.value = msg.payload.status;
        select.classList.remove("pulse");
        void select.offsetWidth;
        select.classList.add("pulse");
      }
    } else if (msg.type === "comment_added") {
      const list = document.querySelector(
        `.comments-list[data-candidate-id="${msg.payload.candidate_id}"]`
      );
      if (list) {
        const div = document.createElement("div");
        div.className = "comment enter";
        const time = new Date(msg.payload.created_at).toLocaleString();
        div.innerHTML = `<span class="author">${msg.payload.author}</span><span class="time">${time}</span><div>${msg.payload.text}</div>`;
        list.appendChild(div);
      }
    } else if (msg.type === "candidate_deleted") {
      const card = document.querySelector(
        `.card[data-candidate-id="${msg.payload.candidate_id}"]`
      );
      if (card) {
        card.classList.add("leave");
        card.addEventListener("animationend", () => card.remove(), { once: true });
      }
    } else if (msg.type === "candidate_new" || msg.type === "candidate_updated") {
      fetch(`/candidates/${msg.payload.candidate_id}/card`)
        .then((r) => (r.ok ? r.text() : null))
        .then((html) => {
          if (!html) return;
          const existing = document.querySelector(
            `.card[data-candidate-id="${msg.payload.candidate_id}"]`
          );
          const wrapper = document.createElement("div");
          wrapper.innerHTML = html;
          const newCard = wrapper.firstElementChild;
          if (existing) {
            newCard.classList.add("flash");
            existing.replaceWith(newCard);
          } else {
            newCard.classList.add("enter");
            document.getElementById("feed-list").prepend(newCard);
          }
        });
    }
  };
})();
