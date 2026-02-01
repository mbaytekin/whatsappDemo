let currentUserId = 'user_' + Date.now();

const CATEGORY_PROMPT = [
    'Sultangazi Belediyesi Kamu Destek Hattına hoş geldiniz.',
    'Size nasıl yardımcı olalım?',
    '1) İstek ve Şikayet',
    '2) Bilgi/Hizmetler (yakında)',
    '3) E-Belediye (yakında)',
    '',
    'Lütfen 1, 2 veya 3 yazın.'
].join('\n');

const QUICK_REPLIES = [
    { label: 'Çöp/Temizlik', text: 'Mahallemizde çöp alınmadı, konteynerler taşıyor.' },
    { label: 'Yol/Altyapı', text: 'Sokağımızda çukur oluştu, acil onarım gerekiyor.' },
    { label: 'Park/Bahçe', text: 'Parktaki oyun grubu kırık, bakım yapılabilir mi?' },
    { label: 'Zabıta', text: 'Kaldırım işgali var, denetim rica ederim.' },
    { label: 'Sosyal Yardım', text: 'Sosyal yardım başvurusu hakkında bilgi almak istiyorum.' }
];

function addMessage(text, isUser) {
    const messagesContainer = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user' : 'bot'}`;
    
    const messageContent = document.createElement('div');
    messageContent.className = 'message-content';
    
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    bubble.textContent = text;
    
    const time = document.createElement('div');
    time.className = 'message-time';
    time.textContent = new Date().toLocaleTimeString('tr-TR', { 
        hour: '2-digit', 
        minute: '2-digit' 
    });
    
    messageContent.appendChild(bubble);
    messageContent.appendChild(time);
    messageDiv.appendChild(messageContent);
    messagesContainer.appendChild(messageDiv);
    
    // Scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function renderQuickReplies(items = QUICK_REPLIES, autoSend = false) {
    const container = document.getElementById('quickReplies');
    container.innerHTML = '';
    items.forEach((item) => {
        const btn = document.createElement('button');
        btn.className = 'quick-reply';
        btn.type = 'button';
        btn.textContent = item.label;
        btn.onclick = () => quickSend(item.text, autoSend);
        container.appendChild(btn);
    });
}

function renderChoiceReplies(choices) {
    const container = document.getElementById('quickReplies');
    container.innerHTML = '';
    choices.forEach((choice) => {
        const btn = document.createElement('button');
        btn.className = 'quick-reply choice';
        btn.type = 'button';
        btn.textContent = `${choice.number}) ${choice.label}`;
        btn.onclick = () => quickSend(String(choice.number), true);
        container.appendChild(btn);
    });
}

function extractChoices(text) {
    const lines = text.split('\n');
    const choices = [];
    lines.forEach((line) => {
        const trimmed = line.trim();
        const match = trimmed.match(/^(\d+)\)\s*(.+)$/);
        if (match) {
            choices.push({ number: parseInt(match[1], 10), label: match[2] });
        }
    });
    return choices;
}

function quickSend(text, autoSend = false) {
    const input = document.getElementById('messageInput');
    input.value = text;
    input.focus();
    if (autoSend) {
        sendMessage();
    }
}

async function sendMessage() {
    const input = document.getElementById('messageInput');
    const sendButton = document.querySelector('button[onclick="sendMessage()"]');
    const message = input.value.trim();
    
    if (!message) return;
    
    // Disable input and button
    input.disabled = true;
    sendButton.disabled = true;
    
    // Add user message
    addMessage(message, true);
    input.value = '';
    
    // Show loading
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'message bot';
    loadingDiv.id = 'loading';
    const loadingContent = document.createElement('div');
    loadingContent.className = 'message-content';
    const loadingBubble = document.createElement('div');
    loadingBubble.className = 'message-bubble loading';
    loadingBubble.textContent = '⏳ Cevap bekleniyor...';
    loadingContent.appendChild(loadingBubble);
    loadingDiv.appendChild(loadingContent);
    document.getElementById('chatMessages').appendChild(loadingDiv);
    
    // Scroll to bottom
    const messagesContainer = document.getElementById('chatMessages');
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message: message,
                user_id: currentUserId
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Remove loading
        const loadingElement = document.getElementById('loading');
        if (loadingElement) {
            loadingElement.remove();
        }
        
        // Add bot response
        if (data.reply) {
            addMessage(data.reply, false);
            const choices = extractChoices(data.reply);
            if (choices.length) {
                renderChoiceReplies(choices);
            } else {
                renderQuickReplies();
            }
        } else {
            addMessage('❌ Yanıt alınamadı. Lütfen tekrar deneyin.', false);
            renderQuickReplies();
        }
    } catch (error) {
        // Remove loading
        const loadingElement = document.getElementById('loading');
        if (loadingElement) {
            loadingElement.remove();
        }
        
        addMessage('❌ Bir hata oluştu. Lütfen tekrar deneyin.', false);
        console.error('Error:', error);
        renderQuickReplies();
    } finally {
        // Re-enable input and button
        input.disabled = false;
        sendButton.disabled = false;
        input.focus();
    }
}

function handleKeyPress(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

function startNewChat() {
    if (confirm('Yeni bir konuşma başlatmak istediğinize emin misiniz? Mevcut konuşma silinecek.')) {
        currentUserId = 'user_' + Date.now();
        document.getElementById('chatMessages').innerHTML = '';
        addMessage(CATEGORY_PROMPT, false);
        renderChoiceReplies(extractChoices(CATEGORY_PROMPT));
    }
}

// Sayfa yüklendiğinde hoş geldin mesajı
window.onload = function() {
    addMessage(CATEGORY_PROMPT, false);
    renderChoiceReplies(extractChoices(CATEGORY_PROMPT));
    
    // Focus input
    document.getElementById('messageInput').focus();
};
