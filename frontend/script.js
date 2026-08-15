const API_BASE_URL = 'https://price-worthiness.onrender.com'; // Update this after deploying backend

document.addEventListener('DOMContentLoaded', () => {
    const apiKeyInput = document.getElementById('api-key');
    const saveKeyBtn = document.getElementById('save-key-btn');
    const keyStatus = document.getElementById('key-status');
    const clearCacheBtn = document.getElementById('clear-cache-btn');
    const cacheStatus = document.getElementById('cache-status');
    
    const chatMessages = document.getElementById('chat-messages');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');

    let threadId = 'user_' + Math.random().toString(36).substring(2, 9);

    // Auto-resize textarea
    userInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        if (this.value === '') {
            this.style.height = 'auto';
        }
    });

    // Save API Key
    saveKeyBtn.addEventListener('click', async () => {
        const key = apiKeyInput.value.trim();
        if (!key) return;

        saveKeyBtn.disabled = true;
        saveKeyBtn.textContent = 'Saving...';
        
        try {
            const res = await fetch(`${API_BASE_URL}/update-api-key`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: key })
            });
            const data = await res.json();
            
            if (res.ok) {
                keyStatus.textContent = 'Key updated successfully!';
                keyStatus.className = 'status-msg';
                // Optional: Store in localStorage for convenience during dev
                localStorage.setItem('groq_api_key', key);
            } else {
                throw new Error(data.detail || 'Failed to update key');
            }
        } catch (err) {
            keyStatus.textContent = err.message;
            keyStatus.className = 'status-msg error';
        } finally {
            saveKeyBtn.disabled = false;
            saveKeyBtn.textContent = 'Save Key';
            setTimeout(() => { keyStatus.textContent = ''; }, 3000);
        }
    });

    // Restore key if saved
    const savedKey = localStorage.getItem('groq_api_key');
    if (savedKey) {
        apiKeyInput.value = savedKey;
        // Optionally auto-apply on load
        fetch(`${API_BASE_URL}/update-api-key`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: savedKey })
        }).catch(e => console.error(e));
    }

    // Clear Cache
    clearCacheBtn.addEventListener('click', async () => {
        try {
            await fetch(`${API_BASE_URL}/clear-cache`, { method: 'POST' });
            cacheStatus.textContent = 'Cache cleared!';
            cacheStatus.className = 'status-msg';
        } catch (err) {
            cacheStatus.textContent = 'Error clearing cache';
            cacheStatus.className = 'status-msg error';
        } finally {
            setTimeout(() => { cacheStatus.textContent = ''; }, 3000);
        }
    });

    // Send Message
    async function sendMessage() {
        const text = userInput.value.trim();
        if (!text) return;

        // Add user message to UI
        addMessageToUI(text, 'user-message');
        userInput.value = '';
        userInput.style.height = 'auto';
        sendBtn.disabled = true;
        
        // Add loading indicator
        const loadingId = addLoadingIndicator();

        try {
            const res = await fetch(`${API_BASE_URL}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text, thread_id: threadId })
            });
            
            const data = await res.json();
            removeLoadingIndicator(loadingId);
            
            if (res.ok) {
                addMessageToUI(data.response, 'ai-message', true);
            } else {
                addMessageToUI(`**Error**: ${data.detail || 'Something went wrong.'}`, 'ai-message', true);
            }
        } catch (err) {
            removeLoadingIndicator(loadingId);
            addMessageToUI(`**Error**: Could not connect to server.`, 'ai-message', true);
        } finally {
            sendBtn.disabled = false;
        }
    }

    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    function addMessageToUI(text, type, parseMarkdown = false) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${type}`;
        
        const avatar = document.createElement('div');
        avatar.className = 'avatar';
        avatar.textContent = type === 'user-message' ? '👤' : '🤖';
        
        const content = document.createElement('div');
        content.className = 'content';
        if (parseMarkdown) {
            content.innerHTML = marked.parse(text);
        } else {
            content.textContent = text;
        }
        
        msgDiv.appendChild(avatar);
        msgDiv.appendChild(content);
        chatMessages.appendChild(msgDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function addLoadingIndicator() {
        const id = 'loading-' + Date.now();
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message ai-message';
        msgDiv.id = id;
        
        const avatar = document.createElement('div');
        avatar.className = 'avatar';
        avatar.textContent = '🤖';
        
        const content = document.createElement('div');
        content.className = 'typing-indicator';
        content.innerHTML = '<div class="dot"></div><div class="dot"></div><div class="dot"></div>';
        
        msgDiv.appendChild(avatar);
        msgDiv.appendChild(content);
        chatMessages.appendChild(msgDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return id;
    }

    function removeLoadingIndicator(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }
});
