function escHtml(s){return (s||'').replace(/[&<>"']/g,m=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]));}

async function postJSON(url, body){
  const res = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!res.ok) throw new Error('HTTP '+res.status);
  return res.json();
}

async function getJSON(url){
  const res = await fetch(url);
  if(!res.ok) throw new Error('HTTP '+res.status);
  return res.json();
}

function sse(url, onEvent){
  const ev = new EventSource(url);
  ev.onmessage = e=>{ try{ onEvent(JSON.parse(e.data)); }catch{} };
  return ev;
}

async function initFeedbackUser(){
  const email = document.getElementById('fbEmail');
  const text  = document.getElementById('fbText');
  const rating= document.getElementById('fbRating');
  const cat   = document.getElementById('fbCategory');
  const send  = document.getElementById('fbSend');
  const attachBtn = document.getElementById('fbAttach');
  const fileInput = document.getElementById('fbFile');
  const out   = document.getElementById('fbMessages');
  let threadId = null;

  attachBtn?.addEventListener('click',()=>fileInput.click());

  async function sendMsg(){
    let attachText = '';
    if(fileInput.files && fileInput.files.length){
      if(!threadId) threadId = crypto.randomUUID();
      const fd = new FormData();
      fd.append('thread_id', threadId);
      Array.from(fileInput.files).forEach(f=>fd.append('files', f));
      const res = await fetch('/api/feedback/upload',{method:'POST',body:fd});
      if(res.ok){
        const j = await res.json();
        attachText = '\n' + j.files.map(f=>`[lampiran] ${f.name}: ${f.path}`).join('\n');
      }
      fileInput.value = '';
    }
    const payload = {
      email: email.value.trim(),
      message: (text.value.trim() + attachText).trim(),
      rating: rating.value?parseInt(rating.value):null,
      category: cat.value||null,
      thread_id: threadId
    };
    if(!payload.email || !payload.message){ alert('Email dan pesan wajib'); return; }
    const r = await postJSON('/api/feedback/messages', payload);
    threadId = r.thread_id;
    out.textContent = (out.textContent==='Belum ada pesan.'?'':out.textContent+'\n') + `[Anda] ${new Date().toLocaleString()} — ${payload.message}`;
    text.value = '';
  }
  send?.addEventListener('click', sendMsg);

  setInterval(async ()=>{
    if(!threadId) return;
    const msgs = await getJSON('/api/feedback/messages?thread_id='+encodeURIComponent(threadId));
    out.textContent = msgs.map(m=>`[${m.sender}] ${m.created_at} — ${m.message}`).join('\n');
  }, 5000);
}

async function initFeedbackAdmin(){
  const list = document.getElementById('fbThreadList');
  const msgs = document.getElementById('fbAdminMessages');
  const search = document.getElementById('fbSearch');
  const resolveBtn = document.getElementById('fbResolve');
  const exportBtn = document.getElementById('fbExport');
  const sendBtn = document.getElementById('fbAdminSend');
  const input = document.getElementById('fbAdminText');
  const header = document.getElementById('fbHeader');

  let currentThread = null;
  let es = null;

  async function loadThreads(q){
    const data = await getJSON('/api/feedback/threads'+(q?'?q='+encodeURIComponent(q):''));
    list.innerHTML = '';
    data.forEach(t=>{
      const el = document.createElement('div');
      el.className = 'nav-item';
      el.textContent = `${t.email} ${t.resolved?'(resolved)':''}`;
      el.onclick = ()=>openThread(t.id, t.email);
      list.appendChild(el);
    });
  }

  async function openThread(id, email){
    currentThread = id;
    header.textContent = email+' — '+id;
    const data = await getJSON('/api/feedback/messages?thread_id='+encodeURIComponent(id));
    msgs.textContent = data.map(m=>`[${m.sender}] ${m.created_at} — ${m.message}`).join('\n');
    if(es) es.close();
    es = sse('/api/feedback/stream?thread_id='+encodeURIComponent(id), ev=>{
      if(ev.type==='message'){
        msgs.textContent += `\n[${ev.sender}] ${new Date().toISOString()} — ${ev.message}`;
      }
    });
  }

  resolveBtn?.addEventListener('click', async ()=>{
    if(!currentThread) return;
    await fetch('/api/feedback/threads/'+currentThread+'/resolve?resolved=true', {method:'PATCH'});
    loadThreads(search.value.trim());
  });
  exportBtn?.addEventListener('click', ()=>{ window.location='/api/feedback/export.csv'; });
  sendBtn?.addEventListener('click', async ()=>{
    if(!currentThread) return;
    const txt = input.value.trim();
    if(!txt) return;
    const r = await postJSON('/api/feedback/messages', {thread_id: currentThread, email: 'admin@local', message: txt});
    msgs.textContent += `\n[admin] ${new Date().toISOString()} — ${txt}`;
    input.value = '';
  });
  search?.addEventListener('input', ()=>loadThreads(search.value.trim()));

  loadThreads('');
}

document.addEventListener('DOMContentLoaded', ()=>{
  if(document.getElementById('fbSend')) initFeedbackUser();
  if(document.getElementById('fbThreadList')) initFeedbackAdmin();
});
