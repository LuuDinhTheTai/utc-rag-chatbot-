'use client';
import { FormEvent, useEffect, useState } from 'react';
import { api, API } from '../lib/api';

type Guide={id:string;cohort:string;admission_year:number;title:string;is_published?:boolean};
type Item={id:string;code:string;category:'document'|'priority';title:string;applies_to:string;evidence:string;source_page:number;sort_order:number;is_active:boolean};
type ItemDraft=Omit<Item,'id'>;
type Detail={guide:Guide;items:Item[]};
const empty:ItemDraft={code:'',category:'document',title:'',applies_to:'',evidence:'',source_page:1,sort_order:1,is_active:true};

export default function FreshmanGuide({token}:{token?:string}){
  const admin=Boolean(token);
  const [guides,setGuides]=useState<Guide[]>([]),[cohort,setCohort]=useState('K67'),[detail,setDetail]=useState<Detail|null>(null);
  const [loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [draft,setDraft]=useState<ItemDraft|null>(null),[editing,setEditing]=useState<string|null>(null);
  const [guideDraft,setGuideDraft]=useState({cohort:'',title:'',admission_year:2026,is_published:true});
  const [guideFile,setGuideFile]=useState<File>();
  const [showGuideForm,setShowGuideForm]=useState(false),[editingGuide,setEditingGuide]=useState(false);
  const headers=token?{Authorization:`Bearer ${token}`}:undefined;
  async function loadGuides(){
    const list=await api<Guide[]>(admin?'/admin/freshmen':'/freshmen',{headers});
    setGuides(list);
    if(!list.some(g=>g.cohort===cohort)&&list.length)setCohort(list[0].cohort);
    if(!list.length){setDetail(null);setLoading(false);}
  }
  useEffect(()=>{loadGuides().catch(e=>{setError(e.message);setLoading(false);});},[token]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(()=>{
    if(!cohort)return;
    let active=true;setLoading(true);
    api<Detail>(`${admin?'/admin':''}/freshmen/${encodeURIComponent(cohort)}`,{headers})
      .then(data=>{if(active)setDetail(data);}).catch(e=>{if(active){setDetail(null);setError(e.message);}})
      .finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[cohort,token]); // eslint-disable-line react-hooks/exhaustive-deps
  async function refresh(){
    await loadGuides();
    if(cohort){
      const data=await api<Detail>(`/admin/freshmen/${encodeURIComponent(cohort)}`,{headers});
      setDetail(data);
    }
  }
  async function run(action:()=>Promise<void>){
    setBusy(true);setError('');setNotice('');
    try{await action();}catch(e){setError(e instanceof Error?e.message:'Không thể xử lý yêu cầu.');}finally{setBusy(false);}
  }
  async function openPdf(page?:number){
    if(!admin){window.open(`${API}/freshmen/${encodeURIComponent(cohort)}/pdf${page?`#page=${page}`:''}`,'_blank','noopener');return;}
    const tab=window.open('','_blank');
    try{
      const response=await fetch(`${API}/admin/freshmen/${encodeURIComponent(cohort)}/pdf`,{headers});
      if(!response.ok)throw new Error('Không thể mở PDF gốc.');
      const url=URL.createObjectURL(await response.blob());
      if(tab){tab.location.href=`${url}${page?`#page=${page}`:''}`;setTimeout(()=>URL.revokeObjectURL(url),60000);}
      else URL.revokeObjectURL(url);
    }catch(e){if(tab)tab.close();setError(e instanceof Error?e.message:'Không thể mở PDF gốc.');}
  }
  function edit(item?:Item){
    setEditing(item?.id||null);
    setDraft(item?{code:item.code,category:item.category,title:item.title,applies_to:item.applies_to,
      evidence:item.evidence,source_page:item.source_page,sort_order:item.sort_order,is_active:item.is_active}:{...empty,sort_order:(detail?.items.length||0)+1});
  }
  function save(e:FormEvent){
    e.preventDefault();if(!draft)return;
    run(async()=>{
      await api(`/admin/freshmen/${encodeURIComponent(cohort)}/items${editing?'/'+editing:''}`,{
        method:editing?'PATCH':'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify(draft)
      });
      setDraft(null);setEditing(null);setNotice('Đã lưu mục hướng dẫn.');await refresh();
    });
  }
  function remove(item:Item){
    if(!window.confirm(`Xóa mục “${item.title}”?`))return;
    run(async()=>{
      await api(`/admin/freshmen/${encodeURIComponent(cohort)}/items/${item.id}`,{method:'DELETE',headers});
      if(editing===item.id){setDraft(null);setEditing(null);}
      setNotice('Đã xóa mục hướng dẫn.');await refresh();
    });
  }
  function createGuide(e:FormEvent){
    e.preventDefault();if(!guideFile)return;
    run(async()=>{
      const form=new FormData();
      form.append('cohort',guideDraft.cohort.trim().toUpperCase());
      form.append('title',guideDraft.title.trim());
      form.append('admission_year',String(guideDraft.admission_year));
      form.append('file',guideFile);
      const row=await api<Guide>('/admin/freshmen',{method:'POST',headers,body:form});
      setShowGuideForm(false);setGuideFile(undefined);setCohort(row.cohort);setNotice('Đã tạo hướng dẫn và lưu PDF gốc.');await loadGuides();
    });
  }
  function updateGuide(e:FormEvent){
    e.preventDefault();if(!detail)return;
    run(async()=>{
      await api(`/admin/freshmen/${encodeURIComponent(cohort)}`,{method:'PATCH',headers:{...headers,'Content-Type':'application/json'},
        body:JSON.stringify({title:guideDraft.title,admission_year:guideDraft.admission_year,is_published:guideDraft.is_published})});
      setShowGuideForm(false);setNotice('Đã cập nhật hướng dẫn.');await refresh();
    });
  }
  function deleteGuide(){
    if(!window.confirm(`Xóa toàn bộ hướng dẫn ${cohort}, các mục và PDF gốc?`))return;
    run(async()=>{
      await api(`/admin/freshmen/${encodeURIComponent(cohort)}`,{method:'DELETE',headers});
      setDraft(null);setDetail(null);setCohort('');setShowGuideForm(false);
      const list=await api<Guide[]>('/admin/freshmen',{headers});setGuides(list);
      if(list.length)setCohort(list[0].cohort);
      setNotice('Đã xóa hướng dẫn.');
    });
  }
  const documents=detail?.items.filter(i=>i.category==='document')||[];
  const priorities=detail?.items.filter(i=>i.category==='priority')||[];
  return <section className="freshmen-page">
    <div className="major-heading"><div><div className="eyebrow">{admin?'QUẢN TRỊ TÂN SINH VIÊN':'HƯỚNG DẪN NHẬP HỌC'}</div><h1>Hồ sơ tân sinh viên</h1><p className="muted">Chuẩn bị theo khóa, năm tốt nghiệp và đối tượng xét tuyển của bạn.</p></div>
      {admin&&<button className="primary" onClick={()=>{setShowGuideForm(true);setEditingGuide(false);setGuideFile(undefined);setGuideDraft({cohort:'',title:'',admission_year:2026,is_published:true});}}>＋ Thêm khóa</button>}</div>
    {error&&<div className="error" role="alert">{error}</div>}{notice&&<div className="notice" role="status">{notice}</div>}
    <div className="freshmen-toolbar"><label>Khóa<select value={cohort} onChange={e=>{setCohort(e.target.value);setDraft(null);setShowGuideForm(false);}}>{guides.map(g=><option key={g.id} value={g.cohort}>{g.cohort} · {g.admission_year}</option>)}</select></label>
      {detail&&<button type="button" className="freshmen-pdf-link" onClick={()=>openPdf()}>Mở PDF gốc ↗</button>}
      {admin&&detail&&<><button onClick={()=>{setGuideDraft({...detail.guide,is_published:detail.guide.is_published??true});setEditingGuide(true);setShowGuideForm(true);}}>Sửa hướng dẫn</button><button disabled={busy} onClick={deleteGuide}>Xóa khóa</button><button className="primary" onClick={()=>edit()}>＋ Thêm mục</button></>}</div>
    {admin&&showGuideForm&&<form className="panel" onSubmit={editingGuide?updateGuide:createGuide}><h2>{editingGuide?'Sửa hướng dẫn':'Tạo hướng dẫn mới'}</h2><div className="form-grid">
      {!editingGuide&&<label>Mã khóa<input required placeholder="K68" pattern="K[0-9]{1,4}" value={guideDraft.cohort} onChange={e=>setGuideDraft(d=>({...d,cohort:e.target.value.toUpperCase()}))}/></label>}
      <label>Tiêu đề<input required minLength={5} maxLength={300} value={guideDraft.title} onChange={e=>setGuideDraft(d=>({...d,title:e.target.value}))}/></label>
      <label>Năm tuyển sinh<input type="number" required min={2000} max={2100} value={guideDraft.admission_year} onChange={e=>setGuideDraft(d=>({...d,admission_year:Number(e.target.value)}))}/></label>
      {!editingGuide&&<label>PDF gốc<input type="file" required accept=".pdf,application/pdf" onChange={e=>setGuideFile(e.target.files?.[0])}/></label>}</div>
      {editingGuide&&<label className="freshmen-check"><input type="checkbox" checked={guideDraft.is_published} onChange={e=>setGuideDraft(d=>({...d,is_published:e.target.checked}))}/> Công bố cho user</label>}
      <div className="row-actions"><button className="primary" disabled={busy}>Lưu hướng dẫn</button><button type="button" onClick={()=>setShowGuideForm(false)}>Hủy</button></div></form>}
    {admin&&draft&&<form className="panel" onSubmit={save}><h2>{editing?'Sửa mục hướng dẫn':'Thêm mục hướng dẫn'}</h2><div className="form-grid">
      <label>Nhóm<select value={draft.category} onChange={e=>setDraft(d=>d?{...d,category:e.target.value as ItemDraft['category']}:d)}><option value="document">Hồ sơ</option><option value="priority">Minh chứng ưu tiên</option></select></label>
      <label>Mã mục<input required maxLength={20} value={draft.code} onChange={e=>setDraft(d=>d?{...d,code:e.target.value}:d)}/></label>
      <label>Tiêu đề<input required minLength={2} maxLength={500} value={draft.title} onChange={e=>setDraft(d=>d?{...d,title:e.target.value}:d)}/></label>
      <label>Trang PDF<input type="number" required min={1} max={100} value={draft.source_page} onChange={e=>setDraft(d=>d?{...d,source_page:Number(e.target.value)}:d)}/></label>
      <label>Thứ tự<input type="number" required min={0} max={10000} value={draft.sort_order} onChange={e=>setDraft(d=>d?{...d,sort_order:Number(e.target.value)}:d)}/></label>
    </div><label className="freshmen-wide-label">Áp dụng cho<textarea rows={3} maxLength={2000} value={draft.applies_to} onChange={e=>setDraft(d=>d?{...d,applies_to:e.target.value}:d)}/></label>
      <label className="freshmen-wide-label">Giấy tờ / minh chứng cần chuẩn bị<textarea rows={4} maxLength={5000} value={draft.evidence} onChange={e=>setDraft(d=>d?{...d,evidence:e.target.value}:d)}/></label>
      <label className="freshmen-check"><input type="checkbox" checked={draft.is_active} onChange={e=>setDraft(d=>d?{...d,is_active:e.target.checked}:d)}/> Hiển thị cho user</label>
      <div className="row-actions"><button className="primary" disabled={busy}>Lưu mục</button><button type="button" onClick={()=>setDraft(null)}>Hủy</button></div></form>}
    {loading&&<p className="muted">Đang tải hướng dẫn…</p>}
    {!loading&&!detail&&<div className="panel muted">Chưa có hướng dẫn nào để hiển thị.</div>}
    {detail&&<><div className="freshmen-source"><strong>{detail.guide.title}</strong><span>Khóa {detail.guide.cohort} · năm {detail.guide.admission_year}</span>{admin&&!detail.guide.is_published&&<span className="status">Chưa công bố</span>}</div>
      <FreshmanSection title="Hồ sơ sinh viên" items={documents} admin={admin} busy={busy} edit={edit} remove={remove} openPdf={openPdf}/>
      <FreshmanSection title="Minh chứng ưu tiên đối tượng" items={priorities} admin={admin} busy={busy} edit={edit} remove={remove} openPdf={openPdf}/>
      <p className="disclaimer">Chỉ chuẩn bị giấy tờ thuộc trường hợp của bạn. Đối chiếu bản PDF gốc và thông báo mới nhất của trường trước khi nộp hồ sơ.</p></>}
  </section>;
}
function FreshmanSection({title,items,admin,busy,edit,remove,openPdf}:{title:string;items:Item[];admin:boolean;busy:boolean;edit:(item:Item)=>void;remove:(item:Item)=>void;openPdf:(page?:number)=>void}){
  return <section className="freshmen-section"><h2>{title} <small>{items.length} mục</small></h2>
    <div className="freshmen-table-scroll" role="region" aria-label={title} tabIndex={0}><table className="freshmen-table"><thead><tr>
      <th scope="col">Mục</th><th scope="col">Nội dung</th><th scope="col">Áp dụng cho</th><th scope="col">Giấy tờ / minh chứng</th><th scope="col">Nguồn</th>{admin&&<th scope="col">Thao tác</th>}
    </tr></thead><tbody>{items.map(item=><tr key={item.id}>
      <td className="freshmen-code">{item.code}</td><td><strong>{item.title}</strong>{admin&&!item.is_active&&<span className="status"> Đã ẩn</span>}</td>
      <td>{item.applies_to||'Theo nội dung hướng dẫn'}</td><td>{item.evidence||'Xem PDF gốc'}</td>
      <td><button type="button" className="freshmen-page-link" onClick={()=>openPdf(item.source_page)}>Trang {item.source_page} ↗</button></td>
      {admin&&<td className="freshmen-actions"><button disabled={busy} onClick={()=>edit(item)}>Sửa</button><button disabled={busy} onClick={()=>remove(item)}>Xóa</button></td>}
    </tr>)}</tbody></table>{!items.length&&<p className="muted freshmen-empty">Chưa có mục nào.</p>}</div>
  </section>;
}
