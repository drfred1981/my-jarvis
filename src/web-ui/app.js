(() => {
    const messagesEl = document.getElementById("messages");
    const inputEl = document.getElementById("input");
    const formEl = document.getElementById("input-form");
    const statusEl = document.getElementById("status");
    const sendBtn = document.getElementById("send-btn");

    const sessionId = crypto.randomUUID();
    let ws = null;
    let reconnectTimer = null;
    let pingInterval = null;

    // Escape HTML to prevent DOM corruption from Claude responses
    function escapeHtml(text) {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // Simple markdown rendering (bold, italic, code, code blocks, links)
    function renderMarkdown(text) {
        text = escapeHtml(text);
        return text
            .replace(/```(\w*)\n([\s\S]*?)```/g,
                '<pre><code class="lang-$1">$2</code></pre>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
            .replace(/\n/g, '<br>');
    }

    function addMessage(text, sender) {
        const div = document.createElement("div");
        div.className = `message ${sender}`;

        const senderLabel = document.createElement("div");
        senderLabel.className = "sender";
        senderLabel.textContent = sender === "user" ? "Vous" : "Jarvis";

        const content = document.createElement("div");
        content.className = "content";
        if (sender === "jarvis") {
            content.innerHTML = renderMarkdown(text);
        } else {
            content.textContent = text;
        }

        div.appendChild(senderLabel);
        div.appendChild(content);
        messagesEl.appendChild(div);
        messagesEl.parentElement.scrollTop = messagesEl.parentElement.scrollHeight;
    }

    function showTyping() {
        let el = document.getElementById("typing");
        if (!el) {
            el = document.createElement("div");
            el.id = "typing";
            el.className = "typing-indicator";
            el.textContent = "Jarvis réfléchit...";
            messagesEl.appendChild(el);
        }
        el.style.display = "block";
        messagesEl.parentElement.scrollTop = messagesEl.parentElement.scrollHeight;
    }

    function hideTyping() {
        const el = document.getElementById("typing");
        if (el) el.style.display = "none";
    }

    function setStatus(text, state) {
        statusEl.textContent = text;
        statusEl.className = `status ${state}`;
    }

    function setLoading(loading) {
        sendBtn.disabled = loading;
        inputEl.disabled = loading;
        sendBtn.textContent = loading ? "..." : "Envoyer";
        if (loading) showTyping(); else hideTyping();
    }

    // --- WebSocket (push notifications only, optional) ---

    function connectWs() {
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        if (pingInterval) {
            clearInterval(pingInterval);
            pingInterval = null;
        }

        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        const url = `${proto}//${location.host}/ws/${sessionId}`;

        try {
            ws = new WebSocket(url);

            ws.onopen = () => {
                setStatus("Connecté", "connected");
                // Keepalive ping every 10s to prevent ingress timeout
                pingInterval = setInterval(() => {
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send("ping");
                    }
                }, 10000);
            };

            ws.onmessage = (event) => {
                // Push notifications from monitoring
                if (event.data && event.data !== "pong") {
                    addMessage(event.data, "jarvis");
                }
            };

            ws.onclose = () => {
                if (pingInterval) {
                    clearInterval(pingInterval);
                    pingInterval = null;
                }
                // Silently reconnect - no status change, no page impact
                reconnectTimer = setTimeout(connectWs, 5000);
            };

            ws.onerror = () => {
                // Let onclose handle reconnection
            };
        } catch (e) {
            // WebSocket not available - REST still works fine
            setStatus("Connecté (REST)", "connected");
        }
    }

    // --- REST API (primary method for sending messages) ---

    async function sendMessage(message) {
        if (!message.trim()) return;
        addMessage(message, "user");
        setLoading(true);

        try {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 5 * 60 * 1000);

            const resp = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message, session_id: sessionId }),
                signal: controller.signal,
            });
            clearTimeout(timeout);

            if (!resp.ok) {
                const text = await resp.text().catch(() => "");
                throw new Error(`HTTP ${resp.status}${text ? ": " + text.slice(0, 200) : ""}`);
            }

            const data = await resp.json();
            addMessage(data.response, "jarvis");
        } catch (err) {
            const msg = err.name === "AbortError"
                ? "Timeout: pas de réponse après 5 minutes."
                : `Erreur: ${err.message}`;
            addMessage(msg, "jarvis");
        } finally {
            setLoading(false);
        }
    }

    // --- Event handlers ---

    formEl.addEventListener("submit", (e) => {
        e.preventDefault();
        const msg = inputEl.value;
        inputEl.value = "";
        inputEl.style.height = "auto";
        sendMessage(msg);
    });

    inputEl.addEventListener("input", () => {
        inputEl.style.height = "auto";
        inputEl.style.height = Math.min(inputEl.scrollHeight, 150) + "px";
    });

    // Enter to send, Shift+Enter for newline
    inputEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            formEl.dispatchEvent(new Event("submit"));
        }
    });

    setStatus("Connecté", "connected");
    connectWs();
})();
