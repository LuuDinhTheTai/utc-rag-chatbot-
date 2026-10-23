'use client';
import {FormEvent,useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import {useAuth} from './AuthProvider';
import {api} from '../lib/api';
import Icon from './Icon';

type Conversation={id:string;title:string;preview:string;updated_at:string;message_count:number};
type Result={items:Conversation[];total:number};

export default function ConversationHistorySidebar({currentId,open,onClose}:{currentId:string;open:boolean;onClose:()=>void}){
  const {user,token,loading:authLoading}=useAuth();
  const [query,setQuery]=useState(''),[search,setSearch]=useState(''),[page,setPage]=useState(1);
  const [activeId,setActiveId]=useState('');
  const [items,setItems]=useState<Conversation[]>([]),[total,setTotal]=useState(0),[loading,setLoading]=useState(false),[error,setError]=useState(''),[revision,setRevision]=useState(0);
  const closeButton=useRef<HTMLButtonElement>(null);
  useEffect(()=>{
    if(!user?.id){setItems([]);setTotal(0);return;}
    let active=true;
    const params=new URLSearchParams({q:search,page:String(page),page_size:'12'});
    api<Result>(`/conversations?${params}`).then(data=>{
      if(!active)return;
      setItems(data.items);setTotal(data.total);setError('');
      if(data.total&&page>Math.ceil(data.total/12))setPage(Math.ceil(data.total/12));
    }).catch(e=>{if(active)setError(e instanceof Error?e.message:'Không thể tải lịch sử hội thoại.');})
      .finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[user?.id,token,search,page,revision]);
  useEffect(()=>{
    const refresh=()=>{setActiveId(sessionStorage.getItem('utc-active-conversation')||'');setRevision(value=>value+1);};
    setActiveId(sessionStorage.getItem('utc-active-conversation')||'');
    window.addEventListener('utc:conversations-changed',refresh);
    window.addEventListener('utc:new-chat',refresh);
    return()=>{window.removeEventListener('utc:conversations-changed',refresh);window.removeEventListener('utc:new-chat',refresh);};
  },[]);
  useEffect(()=>{if(user?.id)setLoading(true);},[user?.id,token,search,page,revision]);
  useEffect(()=>{
    if(!open)return;
    closeButton.current?.focus();
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')onClose();};
    window.addEventListener('keydown',escape);
    return()=>window.removeEventListener('keydown',escape);
  },[open,onClose]);
  function submit(event:FormEvent){event.preventDefault();setPage(1);setSearch(query.trim());}
  const count=Math.max(1,Math.ceil(total/12));
  return <>
    {open&&<button className="history-backdrop" type="button" aria-label="Đóng lịch sử hội thoại" onClick={onClose}/>}
    <aside id="chat-history-sidebar" className={`chat-history-sidebar${open?' history-open':''}`} aria-label="Lịch sử hội thoại">
      <div className="history-sidebar-heading"><div><span className="eyebrow">HỎI ĐÁP TUYỂN SINH</span><h2>Lịch sử hội thoại</h2></div><button ref={closeButton} type="button" className="history-close" onClick={onClose} aria-label="Đóng lịch sử hội thoại">×</button></div>
      {authLoading?<p role="status" className="history-sidebar-state">Đang kiểm tra tài khoản…</p>:!user?.id?<div className="history-sidebar-state"><p>Đăng nhập để lưu và tìm lại các cuộc trò chuyện của bạn.</p><Link href="/account" onClick={onClose}>Đăng nhập →</Link></div>:<>
        <form className="history-sidebar-search" onSubmit={submit}><label htmlFor="history-sidebar-query">Tìm hội thoại</label><div><input id="history-sidebar-query" type="search" maxLength={200} value={query} onChange={event=>setQuery(event.target.value)} placeholder="Tên, câu hỏi, câu trả lời…"/><button type="submit" aria-label="Tìm hội thoại"><Icon name="search"/></button></div></form>
        {search&&<button type="button" className="history-clear" onClick={()=>{setQuery('');setSearch('');setPage(1);}}>Xóa bộ lọc</button>}
        {error&&<p className="history-sidebar-error" role="alert">{error}</p>}
        <div className="history-sidebar-scroll">{loading?<p className="history-sidebar-state" role="status">Đang tải hội thoại…</p>:items.length?<ul className="history-sidebar-list">{items.map(item=><li key={item.id}><Link href={`/?conversation=${encodeURIComponent(item.id)}`} onClick={onClose} className={item.id===(currentId||activeId)?'history-current':undefined} aria-current={item.id===(currentId||activeId)?'page':undefined}><strong>{item.title}</strong><span>{item.preview||'Hội thoại chưa có tin nhắn.'}</span><small>{new Intl.DateTimeFormat('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',day:'2-digit',month:'2-digit',year:'numeric'}).format(new Date(item.updated_at))} · {item.message_count} tin nhắn</small></Link></li>)}</ul>:<p className="history-sidebar-state">{search?'Không tìm thấy hội thoại phù hợp.':'Chưa có hội thoại nào. Hãy bắt đầu đặt câu hỏi.'}</p>}</div>
        {total>12&&<nav className="history-sidebar-pages" aria-label="Phân trang lịch sử"><button type="button" disabled={loading||page<=1} onClick={()=>setPage(value=>value-1)}>← Trước</button><span>{page}/{count}</span><button type="button" disabled={loading||page>=count} onClick={()=>setPage(value=>value+1)}>Sau →</button></nav>}
        <Link className="history-sidebar-all" href="/conversations" onClick={onClose}>Quản lý hội thoại và câu trả lời đã lưu →</Link>
      </>}
    </aside>
  </>;
}
