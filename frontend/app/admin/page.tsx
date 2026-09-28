'use client';
import Link from 'next/link';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { createClient, SupabaseClient } from '@supabase/supabase-js';
import { api, Message } from '../../lib/api';

type Doc = {id: string; title: string; status: string; admission_year: number; campus: string; chunk_count: number; error?: string; storage_path?: string; original_filename?: string};
type Review = {unanswered: Message[]; feedback: {id: string; rating: number; comment: string; messages: {content: string}}[]};
let authClient: SupabaseClient | undefined;
function auth() {
  const url=process.env.NEXT_PUBLIC_SUPABASE_URL, key=process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) throw new Error('Cần cấu hình Supabase trong frontend/.env.local.');
  return authClient ||= createClient(url,key);
}
export default function AdminPage(){
  const documentForm = useRef<HTMLFormElement>(null);
  const [token,setToken]=useState(''), [email,setEmail]=useState(''), [password,setPassword]=useState('');
  const [error,setError]=useState(''), [notice,setNotice]=useState(''), [busy,setBusy]=useState(false);
  const [docs,setDocs]=useState<Doc[]>([]), [review,setReview]=useState<Review>();
  const [url,setUrl]=useState(''), [title,setTitle]=useState(''), [year,setYear]=useState(2026), [campus,setCampus]=useState('hanoi');
  const [file,setFile]=useState<File>(), [text,setText]=useState('');
  useEffect(()=>{
    try {
      const client=auth(); client.auth.getSession().then(({data})=>setToken(data.session?.access_token||''));
      const {data}=client.auth.onAuthStateChange((_event,session)=>setToken(session?.access_token||''));
      return ()=>data.subscription.unsubscribe();
    }catch(e){setError((e as Error).message);}
  },[]);
  async function refresh(access=token){
    const headers={Authorization:`Bearer ${access}`};
    const [documents, reviews]=await Promise.all([api<Doc[]>('/admin/documents',{headers}),api<Review>('/admin/review',{headers})]);
    setDocs(documents);setReview(reviews);
  }
  useEffect(()=>{if(!token)return; refresh().catch(e=>setError(e.message));const timer=setInterval(()=>refresh().catch(()=>{}),10000);return()=>clearInterval(timer);},[token]); // eslint-disable-line react-hooks/exhaustive-deps
  async function run(action:()=>Promise<void>){setBusy(true);setError('');setNotice('');try{await action();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  function login(e:FormEvent){e.preventDefault();run(async()=>{const {error}=await auth().auth.signInWithPassword({email,password});if(error)throw error;setPassword('');});}
  function preview(e:FormEvent){e.preventDefault();run(async()=>{const form=new FormData();if(file)form.append('file',file);else form.append('url',url);const result=await api<{text:string;chunks:number}>('/admin/documents/preview',{method:'POST',headers:{Authorization:`Bearer ${token}`},body:form});setText(result.text);setNotice(`Đã trích xuất văn bản, dự kiến ${result.chunks} đoạn. Kiểm tra nội dung trước khi lập chỉ mục.`);});}
  async function save(){
    if (!documentForm.current?.reportValidity()) return;
    await run(async()=>{
      if (title.trim().length < 3) throw new Error('Tiêu đề cần ít nhất 3 ký tự, không tính khoảng trắng ở hai đầu.');
      if (text.trim().length < 30 || text.trim().length > 2_000_000) throw new Error('Nội dung cần từ 30 đến 2.000.000 ký tự.');
const metadata=JSON.stringify({title:title.trim(),source_url:url.trim(),admission_year:year,campus,text:text.trim()});
      if(file){
        const form=new FormData();form.append('metadata',metadata);form.append('file',file);
        await api('/admin/documents/upload',{method:'POST',headers:{Authorization:`Bearer ${token}`},body:form});
      }else{
        await api('/admin/documents',{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:metadata});
      }setText('');setTitle('');setNotice('Đã gửi tài liệu để lập chỉ mục. Danh sách tự cập nhật mỗi 10 giây.');await refresh();});}
  function download(doc:Doc){run(async()=>{
    const result=await api<{url:string}>(`/admin/documents/${doc.id}/download`,{headers:{Authorization:`Bearer ${token}`}});
    const link=document.createElement('a');link.href=result.url;link.rel='noreferrer';link.click();
  });}
  function action(doc:Doc,kind:string){run(async()=>{await api(`/admin/documents/${doc.id}${kind==='retry'?'/retry':''}`,{method:kind==='delete'?'DELETE':kind==='retry'?'POST':'PATCH',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},...(kind==='toggle'?{body:JSON.stringify({status:doc.status==='ready'?'inactive':'ready'})}:{})});await refresh();});}
  return <main className="admin-page"><header className="admin-header"><Link href="/" className="brand"><span className="logo">UTC</span><span>Quản trị tri thức<small>TRỢ LÝ TUYỂN SINH</small></span></Link><Link href="/">← Về chatbot</Link>{token&&<button onClick={()=>run(async()=>{await auth().auth.signOut();setToken('');setDocs([]);setReview(undefined);})}>Đăng xuất</button>}</header>
    {error&&<div className="error" role="alert">{error}</div>}{notice&&<div className="notice" role="status">{notice}</div>}
    {!token?<form className="panel login" onSubmit={login}><div className="eyebrow">KHÔNG GIAN QUẢN TRỊ</div><h1>Đăng nhập</h1><p>Sử dụng tài khoản quản trị được cấp trên Supabase.</p><label>Email<input type="email" required autoComplete="username" value={email} onChange={e=>setEmail(e.target.value)}/></label><label>Mật khẩu<input type="password" required autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)}/></label><button className="primary" disabled={busy}>Đăng nhập</button></form>:<>
      <div className="admin-intro"><div className="eyebrow">KHO TRI THỨC TUYỂN SINH</div><h1>Quản lý nguồn thông tin</h1><p>Cập nhật tài liệu chính thức để câu trả lời luôn có căn cứ.</p></div>
      <div className="stats"><div><strong>{docs.length}</strong>Tài liệu (tối đa 200)</div><div><strong>{docs.filter(d=>d.status==='ready').length}</strong>Sẵn sàng tra cứu</div><div><strong>{review?.unanswered.length||0}</strong>Chưa đủ nguồn (100 gần nhất)</div></div>
      <section className="panel"><h2>Thêm tài liệu</h2><form ref={documentForm} onSubmit={preview}><div className="form-grid"><label>Tiêu đề<input required minLength={3} maxLength={300} value={title} onChange={e=>setTitle(e.target.value)}/></label><label>URL nguồn chính thức<input type="url" required maxLength={2000} placeholder="https://tuyensinh.utc.edu.vn/…" value={url} onChange={e=>{setUrl(e.target.value);setText('');}}/></label><label>Năm tuyển sinh<input type="number" min={2000} max={2100} step={1} required value={year} onChange={e=>setYear(Number(e.target.value))}/></label><label>Cơ sở<select value={campus} onChange={e=>setCampus(e.target.value)}><option value="hanoi">Hà Nội</option><option value="hcm">TP. Hồ Chí Minh</option></select></label></div><label className="upload">Tệp PDF, TXT hoặc Markdown (tối đa 10 MB)<input type="file" accept=".pdf,.txt,.md" onChange={e=>{setFile(e.target.files?.[0]);setText('');}}/><small>Để trống tệp để lấy nội dung từ URL. Tệp gốc được lưu riêng tư trên Supabase Storage khi xác nhận. Tệp tải lên vẫn cần URL nguồn để trích dẫn.</small></label><button disabled={busy} type="submit">{busy?'Đang xử lý…':'Trích xuất & xem trước'}</button></form>{text&&<div className="preview"><label>Nội dung đã trích xuất<textarea value={text} onChange={e=>setText(e.target.value)} rows={12}/></label><button className="primary" disabled={busy || text.length<30} onClick={save}>Xác nhận & lập chỉ mục</button></div>}</section>
      <section className="panel"><h2>Tài liệu trong hệ thống</h2>{!docs.length&&<p className="muted">Chưa có tài liệu. Thêm nguồn đầu tiên để bắt đầu hỏi đáp.</p>}{docs.map(d=><div className="document-row" key={d.id}><div><strong>{d.title}</strong><p>{d.admission_year} · {d.campus==='hanoi'?'Hà Nội':'TP. HCM'} · {d.chunk_count} đoạn</p>{d.error&&<p className="error">{d.error}</p>}</div><span className={`status ${d.status}`}>{d.status}</span><div className="row-actions">{d.storage_path&&d.status!=='deleting'&&<button disabled={busy} onClick={()=>download(d)}>Tải tệp gốc</button>}{['ready','inactive'].includes(d.status)&&<button disabled={busy} onClick={()=>action(d,'toggle')}>{d.status==='ready'?'Vô hiệu hóa':'Kích hoạt'}</button>}{d.status==='failed'&&<button disabled={busy} onClick={()=>action(d,'retry')}>Thử lại</button>}<button disabled={busy||d.status==='processing'} onClick={()=>{if(window.confirm(`Xóa tài liệu “${d.title}” và các đoạn đã lập chỉ mục?`))action(d,'delete');}}>Xóa</button></div></div>)}</section>
      <section className="panel"><h2>Phản hồi gần đây</h2>{!review?.feedback.length&&<p className="muted">Chưa có phản hồi.</p>}{review?.feedback.map(f=><div className="review-row" key={f.id}><strong>{f.rating===1?'Hữu ích':'Cần cải thiện'}</strong><p>{f.messages?.content}</p>{f.comment&&<p>{f.comment}</p>}</div>)}<h2>Câu trả lời chưa đủ nguồn</h2>{review?.unanswered.map(m=><div className="review-row" key={m.id}><strong>{m.question || "Câu hỏi chưa được ghi nhận"}</strong><p>{m.content}</p><small>Phiên được ghi nhận trong cơ sở dữ liệu để kiểm tra.</small></div>)}</section>
    </>}
  </main>;
}
