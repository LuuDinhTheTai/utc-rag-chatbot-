'use client';
import Link from 'next/link';
import {FormEvent,useCallback,useEffect,useRef,useState} from 'react';
import UtcLogo from './UtcLogo';
import Icon from './Icon';
import {api,Message} from '../lib/api';
import {useAuth} from './AuthProvider';
import ConversationHistorySidebar from './ConversationHistorySidebar';

type Info={id:string;title:string;created_at:string;updated_at:string};
type History={conversation:Info;items:Message[];next_before:string|null;next_after:string|null};
const prompts=['Trường có những phương thức xét tuyển nào?','Điều kiện xét tuyển ngành Công nghệ thông tin?','Học phí dự kiến là bao nhiêu?','Hồ sơ đăng ký xét tuyển gồm những gì?'];
const errorText=(e:unknown)=>e instanceof Error?e.message:'Không thể kết nối máy chủ.';
export default function ChatWorkspace({conversation='',message=''}:{conversation?:string;message?:string}){
  const {token,loading}=useAuth();
  const [historyOpen,setHistoryOpen]=useState(false);
  const closeHistory=useCallback(()=>setHistoryOpen(false),[]);
  if(loading)return <main className="chat-main"><div className="loading" role="status">Đang kiểm tra phiên đăng nhập…</div></main>;
  return <div className="chat-layout"><ChatSession key={`${token||'guest'}:${conversation}:${message}`} initialConversation={conversation} initialMessage={message} historyOpen={historyOpen} onOpenHistory={()=>setHistoryOpen(true)}/><ConversationHistorySidebar currentId={conversation} open={historyOpen} onClose={closeHistory}/></div>;
}
function ChatSession({initialConversation,initialMessage,historyOpen,onOpenHistory}:{initialConversation:string;initialMessage:string;historyOpen:boolean;onOpenHistory:()=>void}){
  const auth=useAuth();const signedIn=Boolean(auth.user?.id);
  const [messages,setMessages]=useState<Message[]>([]),[question,setQuestion]=useState(''),[busy,setBusy]=useState(false),[loadingHistory,setLoadingHistory]=useState(true);
  const [error,setError]=useState(''),[notice,setNotice]=useState(''),[title,setTitle]=useState('Cuộc trò chuyện mới'),[historyUnavailable,setHistoryUnavailable]=useState(false);
  const [ratings,setRatings]=useState<Record<string,number>>({}),[bookmarks,setBookmarks]=useState<Record<string,boolean>>({}),[bookmarkBusy,setBookmarkBusy]=useState('');
  const [before,setBefore]=useState<string|null>(null),[after,setAfter]=useState<string|null>(null);
  const active=useRef({token:'',id:''}),alive=useRef(true),busyRef=useRef(false);
  const viewport=useRef<HTMLElement>(null),end=useRef<HTMLDivElement>(null),input=useRef<HTMLTextAreaElement>(null);
  const scroll=useRef<{mode:'bottom'|'target'|'prepend'|'keep';height:number;top:number}>({mode:initialMessage?'target':'bottom',height:0,top:0});
  function headers():Record<string,string>{return active.current.id?{'X-Conversation-Id':active.current.id}:{'X-Session-Token':active.current.token};}
  function applyHistory(data:History){setMessages(data.items);setTitle(data.conversation.title);setBefore(data.next_before);setAfter(data.next_after);setBookmarks(Object.fromEntries(data.items.map(m=>[m.id,Boolean(m.bookmarked)])));setRatings(Object.fromEntries(data.items.filter(m=>m.rating).map(m=>[m.id,m.rating!])));}
  useEffect(()=>{
    alive.current=true;
    const selected=signedIn?(initialConversation||sessionStorage.getItem('utc-active-conversation')||''):'';
    if(initialConversation&&!signedIn){setError('Đăng nhập để mở cuộc trò chuyện đã lưu.');setHistoryUnavailable(true);setLoadingHistory(false);}
    else if(selected){
      active.current.id=selected;
      api<History>(`/conversations/${encodeURIComponent(selected)}/messages${initialMessage?'?around='+encodeURIComponent(initialMessage):''}`)
        .then(data=>{if(alive.current){sessionStorage.setItem('utc-active-conversation',selected);applyHistory(data);}})
        .catch(e=>{if(alive.current){setError(errorText(e));setHistoryUnavailable(true);active.current.id='';sessionStorage.removeItem('utc-active-conversation');}})
        .finally(()=>{if(alive.current)setLoadingHistory(false);});
    }else if(!signedIn){
      const saved=localStorage.getItem('utc-session')||'';active.current.token=saved;
      if(saved)api<Message[]>('/messages',{headers:{'X-Session-Token':saved}}).then(rows=>{if(alive.current&&active.current.token===saved)setMessages(rows);}).catch(e=>{if(alive.current){setError(errorText(e));active.current.token='';localStorage.removeItem('utc-session');}}).finally(()=>{if(alive.current)setLoadingHistory(false);});
      else setLoadingHistory(false);
    }else setLoadingHistory(false);
    const reset=(event:Event)=>{
      if(busyRef.current&&event.type==='utc:new-chat'){event.preventDefault();return;}
      active.current={token:'',id:''};localStorage.removeItem('utc-session');sessionStorage.removeItem('utc-active-conversation');
      setQuestion('');setMessages([]);setTitle('Cuộc trò chuyện mới');setBefore(null);setAfter(null);setLoadingHistory(false);setHistoryUnavailable(false);setError('');setNotice('');setRatings({});setBookmarks({});scroll.current.mode='bottom';
    };
    window.addEventListener('utc:new-chat',reset);window.addEventListener('utc:account-changed',reset);
    return()=>{alive.current=false;window.removeEventListener('utc:new-chat',reset);window.removeEventListener('utc:account-changed',reset);};
  },[]);
  useEffect(()=>{window.dispatchEvent(new CustomEvent('utc:chat-busy',{detail:busy}));return()=>{window.dispatchEvent(new CustomEvent('utc:chat-busy',{detail:false}));};},[busy]);
  useEffect(()=>{
    if(!viewport.current)return;
    const position=scroll.current;
    if(position.mode==='prepend')viewport.current.scrollTop=position.top+viewport.current.scrollHeight-position.height;
    else if(position.mode==='keep')viewport.current.scrollTop=position.top;
    else if(position.mode==='target'&&initialMessage){const target=document.getElementById('message-'+initialMessage);if(target){target.scrollIntoView({block:'center',behavior:'instant'});target.focus({preventScroll:true});}}
    else if(!messages.length&&!busy)viewport.current.scrollTo({top:0,behavior:'instant'});
    else end.current?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  },[messages,busy,loadingHistory]);
  async function loadHistory(direction:'before'|'after'|'latest'){
    if(loadingHistory||busy)return;setLoadingHistory(true);setError('');
    const cursor=direction==='before'?before:after;
    scroll.current={mode:direction==='latest'?'bottom':direction==='before'?'prepend':'keep',top:viewport.current?.scrollTop||0,height:viewport.current?.scrollHeight||0};
    try{
      const data=await api<History>(`/conversations/${active.current.id}/messages${direction==='latest'?'':`?${direction}=${cursor}`}`);
      if(!alive.current)return;
      if(direction==='latest')applyHistory(data);
      else{setMessages(old=>{const combined=direction==='before'?[...data.items,...old]:[...old,...data.items];return combined.filter((m,i,all)=>all.findIndex(other=>other.id===m.id)===i);});setBookmarks(old=>({...old,...Object.fromEntries(data.items.map(m=>[m.id,Boolean(m.bookmarked)]))}));setRatings(old=>({...old,...Object.fromEntries(data.items.filter(m=>m.rating).map(m=>[m.id,m.rating!]))}));if(direction==='before')setBefore(data.next_before);else setAfter(data.next_after);}
    }catch(e){if(alive.current)setError(errorText(e));}finally{if(alive.current)setLoadingHistory(false);}
  }
  async function send(event:FormEvent){
    event.preventDefault();if(busyRef.current||loadingHistory||historyUnavailable||after||question.trim().length<2)return;
    const text=question.trim();busyRef.current=true;setBusy(true);setError('');setNotice('');scroll.current.mode='bottom';
    try{
      const wasNew=!active.current.id&&!active.current.token;
      if(wasNew){const session=await api<{id:string;token:string}>('/sessions',{method:'POST'});if(!alive.current)return;
        if(signedIn){active.current.id=session.id;sessionStorage.setItem('utc-active-conversation',session.id);}else{active.current.token=session.token;localStorage.setItem('utc-session',session.token);}}
      const identity=active.current.id||active.current.token;
      const reply=await api<Message>('/chat',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({question:text})});
      if(!alive.current||(active.current.id||active.current.token)!==identity)return;
      setMessages(old=>[...old,{id:crypto.randomUUID(),role:'user',content:text},reply]);setQuestion('');
      if(wasNew)setTitle(text.replace(/\s+/g,' ').slice(0,80));
      window.dispatchEvent(new Event('utc:conversations-changed'));
    }catch(e){if(alive.current)setError(errorText(e));}finally{busyRef.current=false;if(alive.current)setBusy(false);}
  }
  async function rate(id:string,rating:number){try{await api('/feedback',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({message_id:id,rating})});if(alive.current)setRatings(old=>({...old,[id]:rating}));}catch(e){if(alive.current)setError(errorText(e));}}
  async function bookmark(id:string){
    setBookmarkBusy(id);setError('');try{const result=await api<{bookmarked:boolean}>('/conversations/bookmarks/'+id,{method:bookmarks[id]?'DELETE':'POST'});if(alive.current){setBookmarks(old=>({...old,[id]:result.bookmarked}));setNotice(result.bookmarked?'Đã lưu câu trả lời. Xem lại trong Lịch sử hội thoại → Câu trả lời đã lưu.':'Đã bỏ lưu câu trả lời.');}}catch(e){if(alive.current)setError(errorText(e));}finally{if(alive.current)setBookmarkBusy('');}
  }
  return <main className="chat-main">
    <header className="topbar chat-history-header"><span className="topbar-title">{signedIn?title:'Trợ lý tuyển sinh'} <span className="tag">UTC</span><small>{signedIn?'Hội thoại được lưu riêng vào tài khoản.':'Thông tin rõ ràng. Lựa chọn tự tin.'}</small></span><button type="button" className="chat-history-toggle" onClick={onOpenHistory} aria-expanded={historyOpen} aria-controls="chat-history-sidebar" aria-label="Mở lịch sử hội thoại"><Icon name="history"/><span aria-hidden="true">Lịch sử</span></button></header>
    <section className="conversation" ref={viewport} aria-live="polite">
      {before&&<button className="history-page-control" disabled={loadingHistory||busy} onClick={()=>loadHistory('before')}>Xem tin nhắn trước đó</button>}
      {loadingHistory&&<div className="loading" role="status">Đang tải hội thoại…</div>}
      {!messages.length&&!loadingHistory&&!historyUnavailable&&<div className="welcome"><div className="welcome-heading"><div className="welcome-icon"><UtcLogo welcome/></div><div className="eyebrow">TRƯỜNG ĐẠI HỌC GIAO THÔNG VẬN TẢI</div></div><h1>Hiểu đúng thông tin.<br/><em>Vững bước vào UTC.</em></h1><p>Từ chọn ngành đến chuẩn bị hồ sơ, trợ lý UTC giúp bạn tìm câu trả lời — kèm nguồn để đối chiếu.</p><div className="welcome-caption"><span>BẠN MUỐN TÌM HIỂU ĐIỀU GÌ?</span><span>Chọn một chủ đề để bắt đầu</span></div><div className="suggestions">{prompts.map((p,i)=><button key={p} onClick={()=>{setQuestion(p);input.current?.focus();}}><span className="suggestion-icon"><Icon name={(['book','chat','chart','file'] as const)[i]}/></span><strong>{['Phương thức xét tuyển','Ngành học phù hợp','Học phí & chi phí','Hồ sơ đăng ký'][i]}</strong><span className="suggestion-question">{p}</span><span className="suggestion-arrow"><Icon name="arrow"/></span></button>)}</div><div className="trust-note"><Icon name="shield"/><span>{signedIn?'Đặt tên và tìm lại hội thoại trong Lịch sử hội thoại.':'Đăng nhập để lưu nhiều cuộc trò chuyện và tìm lại câu trả lời.'}</span></div></div>}
      {messages.map(m=><article id={'message-'+m.id} tabIndex={m.id===initialMessage?-1:undefined} key={m.id} className={`message ${m.role}${m.id===initialMessage?' message-target':''}`}><div className="message-label">{m.role==='user'?'BẠN':'✦ TRỢ LÝ UTC'}</div><div className="message-text">{m.content}</div>{!!m.sources?.length&&<div className="sources"><div className="eyebrow">NGUỒN THAM KHẢO</div>{m.sources.map((s,i)=><details key={s.id||i}><summary>[{s.citation}] {s.title} · {s.admission_year}</summary><p>{s.content}</p><a href={s.source_url} target="_blank" rel="noreferrer">Mở nguồn chính thức ↗</a></details>)}</div>}{m.role==='assistant'&&<div className="feedback"><span>Câu trả lời có hữu ích?</span><button aria-pressed={ratings[m.id]===1} onClick={()=>rate(m.id,1)}>Có</button><button aria-pressed={ratings[m.id]===-1} onClick={()=>rate(m.id,-1)}>Chưa hữu ích</button>{ratings[m.id]&&<small>Đã ghi nhận</small>}{signedIn?<button className="bookmark-answer" disabled={Boolean(bookmarkBusy)} aria-pressed={Boolean(bookmarks[m.id])} onClick={()=>bookmark(m.id)}><Icon name="bookmark"/>{bookmarks[m.id]?'Đã lưu câu trả lời':'Lưu câu trả lời'}</button>:<Link href="/account">Đăng nhập để lưu câu trả lời</Link>}</div>}</article>)}
      {after&&<div className="history-more"><button className="history-page-control" disabled={loadingHistory||busy} onClick={()=>loadHistory('after')}>Xem tin nhắn mới hơn</button><button className="history-page-control" disabled={loadingHistory||busy} onClick={()=>loadHistory('latest')}>Về tin nhắn mới nhất</button></div>}
      {busy&&<div className="loading">✦ Đang tìm nguồn và soạn câu trả lời…</div>}<div ref={end}/>
    </section>
    <div className="composer-wrap">{error&&<div className="error" role="alert">{error}{historyUnavailable&&<p><Link href={signedIn?'/conversations':'/account'}>{signedIn?'Mở lịch sử hội thoại':'Đăng nhập'} →</Link></p>}</div>}{notice&&<div className="notice" role="status">{notice}</div>}<form className="composer" onSubmit={send}><textarea ref={input} disabled={historyUnavailable||Boolean(after)} aria-label="Câu hỏi tuyển sinh" placeholder={after?'Về tin nhắn mới nhất để tiếp tục hội thoại.':'Bạn muốn tìm hiểu điều gì về tuyển sinh UTC?'} maxLength={2000} value={question} onChange={e=>setQuestion(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();e.currentTarget.form?.requestSubmit();}}}/><button disabled={busy||loadingHistory||historyUnavailable||Boolean(after)||question.trim().length<2} type="submit" aria-label="Gửi câu hỏi"><Icon name="arrow"/></button></form><p className="disclaimer">Thông tin mang tính tham khảo. Luôn đối chiếu thông báo chính thức trước khi đăng ký.</p></div>
  </main>;
}
