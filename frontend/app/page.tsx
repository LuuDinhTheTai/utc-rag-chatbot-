'use client';
import Link from 'next/link';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { api, Message } from '../lib/api';

const prompts = ['Trường có những phương thức xét tuyển nào?', 'Điều kiện xét tuyển ngành Công nghệ thông tin?', 'Học phí dự kiến là bao nhiêu?', 'Hồ sơ đăng ký xét tuyển gồm những gì?'];
export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState('');
  const [year, setYear] = useState(2026);
  const [campus, setCampus] = useState('hanoi');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [ratings, setRatings] = useState<Record<string, number>>({});
  const token = useRef('');
  const busyRef = useRef(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let active = true;
    token.current = localStorage.getItem('utc-session') || '';
    const storedToken = token.current;
    if (storedToken) {
      api<Message[]>('/messages', {headers: {'X-Session-Token': storedToken}})
        .then(rows => { if (active && token.current === storedToken) setMessages(rows); })
        .catch(cause => { if (active && token.current === storedToken) setError(cause.message); });
    }
    const reset = (event: Event) => {
      if (busyRef.current) { event.preventDefault(); return; }
      token.current = '';
      setMessages([]);
      setError('');
      setRatings({});
    };
    window.addEventListener('utc:new-chat', reset);
    return () => { active = false; window.removeEventListener('utc:new-chat', reset); };
  }, []);
  useEffect(() => {
    window.dispatchEvent(new CustomEvent('utc:chat-busy', {detail: busy}));
    return () => { window.dispatchEvent(new CustomEvent('utc:chat-busy', {detail: false})); };
  }, [busy]);
  useEffect(() => { end.current?.scrollIntoView({behavior: 'smooth'}); }, [messages, busy]);
  async function send(event: FormEvent) {
    event.preventDefault(); if (busy || question.trim().length < 2) return;
    const text = question.trim(); busyRef.current = true; setBusy(true); setError('');
    try {
      if (!token.current) {
        const session = await api<{token: string}>('/sessions', {method: 'POST'});
        token.current = session.token; localStorage.setItem('utc-session', session.token);
      }
      const reply = await api<Message>('/chat', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Session-Token': token.current}, body: JSON.stringify({question: text, year, campus})});
      setMessages(old => [...old, {id: crypto.randomUUID(), role: 'user', content: text}, reply]); setQuestion('');
    } catch (e) { setError(e instanceof Error ? e.message : 'Không thể kết nối máy chủ.'); }
    finally { busyRef.current = false; setBusy(false); }
  }
  async function rate(id: string, rating: number) {
    try {
      await api('/feedback', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Session-Token': token.current}, body: JSON.stringify({message_id: id, rating})});
      setRatings(old => ({...old, [id]: rating}));
    } catch(e) {setError(e instanceof Error ? e.message : 'Không gửi được phản hồi.');}
  }
  return <main className="chat-main">
      <header className="topbar"><span>Hỏi đáp cùng UTC <span className="tag">AI ASSISTANT</span></span><div className="topbar-links"><Link href="/majors">Ngành học</Link><Link href="/freshmen">Tân sinh viên ↗</Link></div></header>
      <div className="filters"><span>Thông tin áp dụng</span><label>Năm <input aria-label="Năm tuyển sinh" type="number" min="2000" max="2100" value={year} onChange={e => setYear(Number(e.target.value))}/></label><label>Cơ sở <select value={campus} onChange={e => setCampus(e.target.value)}><option value="hanoi">Hà Nội</option><option value="hcm">TP. Hồ Chí Minh</option></select></label></div>
      <section className="conversation" aria-live="polite">
        {!messages.length && <div className="welcome"><div className="welcome-icon">✦</div><div className="eyebrow">CHÀO BẠN, MÌNH LÀ TRỢ LÝ UTC</div><h1>Hành trình đại học,<br/><em>bắt đầu từ một câu hỏi.</em></h1><p>Cùng tìm hiểu ngành học, phương thức xét tuyển và những điều bạn cần chuẩn bị. Thông tin rõ ràng, kèm nguồn để bạn kiểm chứng.</p><div className="suggestions">{prompts.map((p,i) => <button key={p} onClick={() => setQuestion(p)}><span>0{i+1} ↗</span>{p}</button>)}</div></div>}
        {messages.map(m => <article key={m.id} className={`message ${m.role}`}><div className="message-label">{m.role === 'user' ? 'BẠN' : '✦ TRỢ LÝ UTC'}</div><div className="message-text">{m.content}</div>{!!m.sources?.length && <div className="sources"><div className="eyebrow">NGUỒN THAM KHẢO</div>{m.sources.map(s => <details key={s.id}><summary>[{s.citation}] {s.title} · {s.admission_year}</summary><p>{s.content}</p><a href={s.source_url} target="_blank" rel="noreferrer">Mở nguồn chính thức ↗</a></details>)}</div>}{m.role === 'assistant' && <div className="feedback"><span>Câu trả lời có hữu ích?</span><button aria-pressed={ratings[m.id]===1} onClick={() => rate(m.id,1)}>Có</button><button aria-pressed={ratings[m.id]===-1} onClick={() => rate(m.id,-1)}>Chưa hữu ích</button>{ratings[m.id] && <small>Đã ghi nhận</small>}</div>}</article>)}
        {busy && <div className="loading">✦ Đang tìm nguồn và soạn câu trả lời…</div>}<div ref={end}/>
      </section>
      <div className="composer-wrap">{error && <div className="error" role="alert">{error}</div>}<form className="composer" onSubmit={send}><textarea aria-label="Câu hỏi tuyển sinh" placeholder="Bạn muốn tìm hiểu điều gì về tuyển sinh UTC?" maxLength={2000} value={question} onChange={e => setQuestion(e.target.value)} onKeyDown={e => {if(e.key==='Enter' && !e.shiftKey && !e.nativeEvent.isComposing){e.preventDefault();e.currentTarget.form?.requestSubmit();}}}/><button disabled={busy || question.trim().length < 2} type="submit" aria-label="Gửi câu hỏi">↑</button></form><p className="disclaimer">Thông tin mang tính tham khảo. Luôn đối chiếu thông báo chính thức trước khi đăng ký.</p></div>
  </main>;
}
