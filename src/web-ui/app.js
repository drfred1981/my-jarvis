(() => {
    const messagesEl = document.getElementById("messages");
    const inputEl = document.getElementById("input");
    const formEl = document.getElementById("input-form");
    const statusEl = document.getElementById("status");
    const sendBtn = document.getElementById("send-btn");

    const sessionId = crypto.randomUUID();
    let ws = null;
    let reconnectTimer = null;

    // Simple markdown rendering (bold, italic, code, code blocks, links)
    function renderMarkdown(text) {
        return text
            // Code blocks (``` ... ```)
            .replace(/```(\w*)\n([\s\S]*?)```/g,
                '<pre><code class="lang-$1">$2</code></pre>')
            // Inline code
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            // Bold
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            // Italic
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            // Links
            .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
            // Line breaks
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

    function connect() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        const url = `${proto}//${location.host}/ws/${sessionId}`;

        ws = new WebSocket(url);

        ws.onopen = () => {
            setStatus("Connecté", "connected");
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
        };

        ws.onmessage = (event) => {
            setLoading(false);
            addMessage(event.data, "jarvis");
        };

        ws.onclose = () => {
            setStatus("Déconnecté", "error");
            setLoading(false);
            reconnectTimer = setTimeout(connect, 3000);
        };

        ws.onerror = () => {
            setStatus("Erreur", "error");
            ws.close();
        };
    }

    async function sendViaRest(message) {
        try {
            const resp = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message, session_id: sessionId }),
            });
            const data = await resp.json();
            addMessage(data.response, "jarvis");
        } catch (err) {
            addMessage(`Erreur: ${err.message}`, "jarvis");
        } finally {
            setLoading(false);
        }
    }

    function send(message) {
        if (!message.trim()) return;
        addMessage(message, "user");
        setLoading(true);

        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(message);
        } else {
            sendViaRest(message);
        }
    }

    formEl.addEventListener("submit", (e) => {
        e.preventDefault();
        const msg = inputEl.value;
        inputEl.value = "";
        inputEl.style.height = "auto";
        send(msg);
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

    connect();
})();
