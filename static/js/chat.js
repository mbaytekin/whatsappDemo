let currentUserId = 'user_' + Date.now();
let mediaRecorder = null;
let recordingChunks = [];
let recordingTimer = null;
let recordingInterval = null;
const MAX_RECORD_SECONDS = 90;

const WELCOME_MESSAGE = [
    'Selam komşum, ben Osman. Sultangazi Belediyesi\'nden yazıyorum. Sizlere yardımcı olmak için buradayım.',
    '',
    'Şu başlıklarda yardımcı olabilirim:',
    '',
    '1) Talep Oluşturma',
    '2) Eğitim ve Kurs Başvuru',
    '3) Yardımlar',
    '4) Millet Kütüphaneleri Randevu Alma',
    '5) Nöbetçi Eczaneler',
    '',
    'İsteğinizi veya şikayetinizi doğrudan yazabilirsiniz.'
].join('\n');

const QUICK_REPLIES = [
    { label: 'Çöp/Temizlik', text: 'Mahallemizde çöp alınmadı, konteynerler taşıyor.' },
    { label: 'Yol/Altyapı', text: 'Sokağımızda çukur oluştu, acil onarım gerekiyor.' },
    { label: 'Park/Bahçe', text: 'Parktaki oyun grubu kırık, bakım yapılabilir mi?' },
    { label: 'Zabıta', text: 'Kaldırım işgali var, denetim rica ederim.' },
    { label: 'Sosyal Yardım', text: 'Sosyal yardım başvurusu hakkında bilgi almak istiyorum.' }
];

async function initSession() {
    try {
        await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message: '',
                user_id: currentUserId
            })
        });
    } catch (error) {
        console.error('Init error:', error);
    }
}

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

function createLoadingBubble(text = '⏳ Cevap bekleniyor...') {
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'message bot';
    loadingDiv.id = 'loading';
    const loadingContent = document.createElement('div');
    loadingContent.className = 'message-content';
    const loadingBubble = document.createElement('div');
    loadingBubble.className = 'message-bubble loading';
    loadingBubble.textContent = text;
    loadingContent.appendChild(loadingBubble);
    loadingDiv.appendChild(loadingContent);
    document.getElementById('chatMessages').appendChild(loadingDiv);

    const messagesContainer = document.getElementById('chatMessages');
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function removeLoadingBubble() {
    const loadingElement = document.getElementById('loading');
    if (loadingElement) {
        loadingElement.remove();
    }
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
    createLoadingBubble();

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
        removeLoadingBubble();

        // Add bot response
        if (data.reply !== undefined && data.reply !== null) {
            if (data.reply) {
                addMessage(data.reply, false);
                const choices = extractChoices(data.reply);
                if (choices.length) {
                    renderChoiceReplies(choices);
                } else {
                    renderQuickReplies();
                }
            } else {
                // empty reply means no response is intended
                renderQuickReplies();
            }
        } else {
            addMessage('❌ Yanıt alınamadı. Lütfen tekrar deneyin.', false);
            renderQuickReplies();
        }
    } catch (error) {
        // Remove loading
        removeLoadingBubble();

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
        addMessage(WELCOME_MESSAGE, false);
        const choices = extractChoices(WELCOME_MESSAGE);
        if (choices.length) {
            renderChoiceReplies(choices);
        } else {
            renderQuickReplies();
        }
        initSession();
    }
}

function pickSupportedMimeType() {
    const candidates = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/mp4',
        'audio/mpeg'
    ];
    for (const type of candidates) {
        if (MediaRecorder.isTypeSupported(type)) {
            return type;
        }
    }
    return '';
}

async function toggleRecording() {
    const button = document.getElementById('recordButton');
    const timer = document.getElementById('recordTimer');
    if (typeof MediaRecorder === 'undefined') {
        addMessage('🎙️ Tarayıcı ses kaydını desteklemiyor.', false);
        return;
    }
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
        button.classList.remove('recording');
        button.textContent = '🎙️';
        if (recordingInterval) {
            clearInterval(recordingInterval);
            recordingInterval = null;
        }
        timer.textContent = '00:00';
        return;
    }

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mimeType = pickSupportedMimeType();
        mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
        recordingChunks = [];

        mediaRecorder.ondataavailable = (event) => {
            if (event.data && event.data.size > 0) {
                recordingChunks.push(event.data);
            }
        };

        mediaRecorder.onstop = async () => {
            clearTimeout(recordingTimer);
            if (recordingInterval) {
                clearInterval(recordingInterval);
                recordingInterval = null;
            }
            timer.textContent = '00:00';
            const blob = new Blob(recordingChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
            stream.getTracks().forEach(track => track.stop());
            await sendAudio(blob);
        };

        mediaRecorder.start();
        button.classList.add('recording');
        button.textContent = '⏹️';
        const startedAt = Date.now();
        timer.textContent = '00:00';
        recordingInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - startedAt) / 1000);
            const minutes = String(Math.floor(elapsed / 60)).padStart(2, '0');
            const seconds = String(elapsed % 60).padStart(2, '0');
            timer.textContent = `${minutes}:${seconds}`;
        }, 500);
        recordingTimer = setTimeout(() => {
            if (mediaRecorder && mediaRecorder.state === 'recording') {
                mediaRecorder.stop();
            }
        }, MAX_RECORD_SECONDS * 1000);
    } catch (error) {
        console.error('Mic error:', error);
        addMessage('🎙️ Mikrofon izni verilemedi.', false);
    }
}

async function sendAudio(blob) {
    const sendButton = document.querySelector('button[onclick="sendMessage()"]');
    const input = document.getElementById('messageInput');
    const recordButton = document.getElementById('recordButton');
    input.disabled = true;
    sendButton.disabled = true;
    recordButton.disabled = true;

    createLoadingBubble('⏳ Ses kaydı çözümleniyor...');

    try {
        const formData = new FormData();
        const extension = (blob.type.split('/')[1] || 'webm').split(';')[0];
        formData.append('file', blob, `recording.${extension}`);
        formData.append('user_id', currentUserId);

        const response = await fetch('/api/transcribe', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();
        removeLoadingBubble();

        if (!response.ok || data.error) {
            addMessage(data.error || '❌ Ses çözümlenemedi.', false);
            renderQuickReplies();
            return;
        }

        if (data.transcript) {
            addMessage(data.transcript, true);
        }

        if (data.reply) {
            addMessage(data.reply, false);
            const choices = extractChoices(data.reply);
            if (choices.length) {
                renderChoiceReplies(choices);
            } else {
                renderQuickReplies();
            }
        }
    } catch (error) {
        removeLoadingBubble();
        addMessage('❌ Ses kaydı gönderilemedi.', false);
        console.error('Error:', error);
        renderQuickReplies();
    } finally {
        input.disabled = false;
        sendButton.disabled = false;
        recordButton.disabled = false;
        input.focus();
    }
}

// Sayfa yüklendiğinde hoş geldin mesajı
window.onload = function () {
    addMessage(WELCOME_MESSAGE, false);
    const choices = extractChoices(WELCOME_MESSAGE);
    if (choices.length) {
        renderChoiceReplies(choices);
    } else {
        renderQuickReplies();
    }
    initSession();
    // Focus input
    document.getElementById('messageInput').focus();
};
