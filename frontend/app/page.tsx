'use client';
import UtcLogo from '../components/UtcLogo';
import Icon from '../components/Icon';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { api, Message } from '../lib/api';

const prompts = ['Trường có những phương thức xét tuyển nào?', 'Điều kiện xét tuyển ngành Công nghệ thông tin?', 'Học phí dự kiến là bao nhiêu?', 'Hồ sơ đăng ký xét tuyển gồm những gì?'];
export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [error, setError] = useState('');
  const [ratings, setRatings] = useState<Record<string, number>>({});
  const token = useRef('');
  const busyRef = useRef(false);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    let active = true;
    token.current = localStorage.getItem('utc-session') || '';
    const storedToken = token.current;
    if (storedToken) {
      api<Message[]>('/messages', {headers: {'X-Session-Token': storedToken}})
        .then(rows => { if (active && token.current === storedToken) {
          setMessages(rows);
        } })
        .catch(cause => { if (active && token.current === storedToken) setError(cause.message); })
        .finally(() => { if (active) setLoadingHistory(false); });
    } else setLoadingHistory(false);
    const reset = (event: Event) => {
      if (busyRef.current && event.type === 'utc:new-chat') { event.preventDefault(); return; }
      token.current = '';
      localStorage.removeItem('utc-session');
      setQuestion('');
      setLoadingHistory(false);
      setMessages([]);
      setError('');
      setRatings({});
    };
    window.addEventListener('utc:new-chat', reset);
    window.addEventListener('utc:account-changed', reset);
    return () => { active = false; window.removeEventListener('utc:new-chat', reset); window.removeEventListener('utc:account-changed', reset); };
  }, []);
  useEffect(() => {
    window.dispatchEvent(new CustomEvent('utc:chat-busy', {detail: busy}));
    return () => { window.dispatchEvent(new CustomEvent('utc:chat-busy', {detail: false})); };
  }, [busy]);
  useEffect(() => {
    if (!messages.length && !busy) {
      end.current?.parentElement?.scrollTo({top: 0, behavior: 'instant'});
    } else {
      end.current?.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    }
  }, [messages, busy]);
  async function send(event: FormEvent) {
    event.preventDefault(); if (busyRef.current || loadingHistory || question.trim().length < 2) return;
    const text = question.trim(); busyRef.current = true; setBusy(true); setError('');
    try {
      if (!token.current) {
        const session = await api<{token: string}>('/sessions', {method: 'POST'});
        token.current = session.token; localStorage.setItem('utc-session', session.token);
      }
      const sentToken = token.current;
      const reply = await api<Message>('/chat', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Session-Token': sentToken}, body: JSON.stringify({question: text})});
      if (token.current !== sentToken) return;
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
      <header className="topbar"><span className="topbar-title">Trợ lý tuyển sinh <span className="tag">UTC</span><small>Thông tin rõ ràng. Lựa chọn tự tin.</small></span></header>
      <section className="conversation" aria-live="polite">
        {!messages.length && <div className="welcome">
          <div className="welcome-heading"><div className="welcome-icon"><UtcLogo welcome/></div><div className="eyebrow">TRƯỜNG ĐẠI HỌC GIAO THÔNG VẬN TẢI</div></div>
          <h1>Hiểu đúng thông tin.<br/><em>Vững bước vào UTC.</em></h1>
          <p>Từ chọn ngành đến chuẩn bị hồ sơ, trợ lý UTC giúp bạn tìm câu trả lời — kèm nguồn để đối chiếu.</p>
          <div className="welcome-caption"><span>BẠN MUỐN TÌM HIỂU ĐIỀU GÌ?</span><span>Chọn một chủ đề để bắt đầu</span></div>
          <div className="suggestions">{prompts.map((p,i) => <button key={p} onClick={() => {setQuestion(p); input.current?.focus();}}><span className="suggestion-icon"><Icon name={(['book','chat','chart','file'] as const)[i]}/></span><strong>{['Phương thức xét tuyển','Ngành học phù hợp','Học phí & chi phí','Hồ sơ đăng ký'][i]}</strong><span className="suggestion-question">{p}</span><span className="suggestion-arrow"><Icon name="arrow"/></span></button>)}</div>
          <div className="trust-note"><Icon name="shield"/><span>Câu trả lời có nguồn tham khảo · Hỗ trợ cả hai cơ sở</span></div>
        </div>}
        {messages.map(m => <article key={m.id} className={`message ${m.role}`}><div className="message-label">{m.role === 'user' ? 'BẠN' : '✦ TRỢ LÝ UTC'}</div><div className="message-text">{m.content}</div>{!!m.sources?.length && <div className="sources"><div className="eyebrow">NGUỒN THAM KHẢO</div>{m.sources.map(s => <details key={s.id}><summary>[{s.citation}] {s.title} · {s.admission_year}</summary><p>{s.content}</p><a href={s.source_url} target="_blank" rel="noreferrer">Mở nguồn chính thức ↗</a></details>)}</div>}{m.role === 'assistant' && <div className="feedback"><span>Câu trả lời có hữu ích?</span><button aria-pressed={ratings[m.id]===1} onClick={() => rate(m.id,1)}>Có</button><button aria-pressed={ratings[m.id]===-1} onClick={() => rate(m.id,-1)}>Chưa hữu ích</button>{ratings[m.id] && <small>Đã ghi nhận</small>}</div>}</article>)}
        {busy && <div className="loading">✦ Đang tìm nguồn và soạn câu trả lời…</div>}<div ref={end}/>
      </section>
      <div className="composer-wrap">{error && <div className="error" role="alert">{error}</div>}<form className="composer" onSubmit={send}><textarea ref={input} aria-label="Câu hỏi tuyển sinh" placeholder="Bạn muốn tìm hiểu điều gì về tuyển sinh UTC?" maxLength={2000} value={question} onChange={e => setQuestion(e.target.value)} onKeyDown={e => {if(e.key==='Enter' && !e.shiftKey && !e.nativeEvent.isComposing){e.preventDefault();e.currentTarget.form?.requestSubmit();}}}/><button disabled={busy || loadingHistory || question.trim().length < 2} type="submit" aria-label="Gửi câu hỏi"><Icon name="arrow"/></button></form><p className="disclaimer">Thông tin mang tính tham khảo. Luôn đối chiếu thông báo chính thức trước khi đăng ký.</p></div>
  </main>;
}
