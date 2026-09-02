(() => {
  const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[character]));

  const inlineMarkdown = (value) => value
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");

  function renderMarkdown(markdown) {
    return escapeHtml(markdown).split("\n").map((line) => {
      if (line.startsWith("### ")) return `<h4>${inlineMarkdown(line.slice(4))}</h4>`;
      if (line.startsWith("## ")) return `<h3>${inlineMarkdown(line.slice(3))}</h3>`;
      if (line.startsWith("# ")) return `<h2>${inlineMarkdown(line.slice(2))}</h2>`;
      if (line.startsWith("- ")) return `<div class="md-list">• ${inlineMarkdown(line.slice(2))}</div>`;
      if (!line.trim()) return "<div class=\"md-gap\"></div>";
      return `<div>${inlineMarkdown(line)}</div>`;
    }).join("");
  }

  function eventFromBlock(block) {
    const event = (block.match(/^event: (.+)$/m) || [])[1];
    const data = (block.match(/^data: (.+)$/m) || [])[1];
    if (!event || !data) return null;
    try { return { event, data: JSON.parse(data) }; } catch { return null; }
  }

  window.ask = async function streamAsk() {
    const question = document.getElementById("question").value.trim();
    if (!question) return;
    const button = document.getElementById("askButton");
    const output = document.getElementById("answer");
    const useRag = document.querySelector('input[name="mode"]:checked').value === "rag";
    button.dataset.old = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="load"></span>Thinking';
    output.className = "answer";
    output.innerHTML = '<div class="engine">Connecting to Ollama stream</div><span class="load"></span>Waiting for the first token…';
    let markdown = "";
    let engine = "Ollama/qwen2.5-coder:7b";

    try {
      const response = await fetch("/api/ask/stream", {
        method: "POST",
        headers: { "content-type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ question, use_rag: useRag }),
      });
      if (!response.ok || !response.body) throw new Error(`Streaming request failed (${response.status})`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finished = false;
      while (!finished) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop();
        for (const block of blocks) {
          const message = eventFromBlock(block);
          if (!message) continue;
          if (message.event === "context") {
            engine = message.data.engine || engine;
            if (message.data.retrieved_evidence?.length && window.evidence) window.evidence(message.data.retrieved_evidence);
            output.innerHTML = `<div class="engine">${escapeHtml(engine)} · streaming Markdown response</div>`;
          }
          if (message.event === "token") {
            markdown += message.data.text;
            output.innerHTML = `<div class="engine">${escapeHtml(engine)} · streaming Markdown response</div><div class="md-answer">${renderMarkdown(markdown)}</div><span class="cursor">▋</span>`;
          }
          if (message.event === "error") {
            output.innerHTML += `<div class="safety">Model detail: ${escapeHtml(message.data.detail)}</div>`;
            finished = true;
          }
          if (message.event === "done") {
            engine = message.data.engine || engine;
            output.innerHTML = `<div class="engine">${escapeHtml(engine)} · Markdown response complete</div><div class="md-answer">${renderMarkdown(markdown)}</div>`;
            finished = true;
          }
        }
      }
      if (!markdown && !output.querySelector(".safety")) output.innerHTML += "<div class=\"safety\">The model stream ended without text.</div>";
    } catch (error) {
      output.innerHTML = `<div class="engine">Stream unavailable</div><div class="safety">${escapeHtml(error.message)}</div>`;
    } finally {
      button.disabled = false;
      button.innerHTML = button.dataset.old || "Analyze →";
      if (window.loadAudit) window.loadAudit();
    }
  };
})();
