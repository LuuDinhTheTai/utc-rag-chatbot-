'use client';

import {FormEvent, useEffect, useRef, useState} from 'react';
import {api} from '../lib/api';

export const reasonLabels:Record<string,string> = {
  needs_ocr:'Cần đọc nội dung ảnh', ocr_review_required:'Cần đối chiếu kết quả OCR',
  ocr_failed:'Chưa đọc được ảnh', attachment_unreadable:'Chưa đọc được tệp',
  unsupported_attachment:'Tệp chưa hỗ trợ', ambiguous_year:'Chưa rõ năm áp dụng',
  ambiguous_campus:'Chưa rõ cơ sở', insufficient_text:'Chưa đủ nội dung',
  invalid_title:'Tiêu đề không hợp lệ', attachment_limit:'Quá nhiều tệp đính kèm',
  outside_admissions:'Ngoài nội dung tuyển sinh', personal_or_unrelated_data:'Nội dung cá nhân hoặc không phù hợp',
};
const labels:Record<string,string>={staged:'Chờ duyệt',review:'Cần kiểm tra',approving:'Đang thêm vào RAG',published:'Đã thêm vào RAG',unchanged:'Đã có trong RAG',rejected:'Đã bỏ qua'};
type Duplicate={id:string;title:string;reason:string;status:string};
type Candidate={id:string;url:string;title:string;year:number|null;campus:string|null;status:string;preview:string;reasons:string[];error:string|null;duplicate?:Duplicate|null};
type Detail=Candidate&{text:string;original_text:string;assets:{url:string;kind:string;error?:string}[]};
type Listing={items:Candidate[];total:number;page:number;page_size:number};

export default function UtcCrawlerReview({token,onComplete}:{token:string;onComplete:()=>Promise<void>}){
  const [state,setState]=useState('pending'),[page,setPage]=useState(1);
  const [listing,setListing]=useState<Listing>();
  const [selected,setSelected]=useState<Detail>();
  const [title,setTitle]=useState(''),[text,setText]=useState(''),[year,setYear]=useState(''),[campus,setCampus]=useState('');
  const [confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[opening,setOpening]=useState(false);
  const [error,setError]=useState(''),[loadError,setLoadError]=useState(''),[notice,setNotice]=useState('');
  const [duplicateCheck,setDuplicateCheck]=useState<{key:string;duplicate:Duplicate|null;error?:string}>();
  const draftKey=JSON.stringify([selected?.id,text.trim(),Number(year),campus]);
  const validDraft=text.trim().length>=30&&text.trim().length<=2_000_000&&Number.isInteger(Number(year))&&Number(year)>=2000&&Number(year)<=2100&&['hanoi','hcm'].includes(campus);
  const completion=useRef(onComplete);completion.current=onComplete;
  const requestId=useRef(0);
  const editorHeading=useRef<HTMLHeadingElement>(null);
  useEffect(()=>{
    if(selected&&!opening){
      editorHeading.current?.focus({preventScroll:true});
      if(window.matchMedia('(max-width:800px)').matches)editorHeading.current?.scrollIntoView({behavior:'smooth',block:'start'});
    }
  },[selected?.id,opening]);
  const headers={Authorization:`Bearer ${token}`};
  useEffect(()=>{
    if(!selected||['approving','published','unchanged'].includes(selected.status)||!validDraft)return;
    let active=true;
    const timer=setTimeout(async()=>{
      try{
        // Check content only: rechecking a crawler URL may contain a valid update.
        const result=await api<{duplicate:Duplicate|null}>('/admin/documents/check-duplicate',{
          method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},
          body:JSON.stringify({text:text.trim(),admission_year:Number(year),campus}),
        });
        if(active)setDuplicateCheck({key:draftKey,duplicate:result.duplicate});
      }catch(e){if(active)setDuplicateCheck({key:draftKey,duplicate:null,error:(e as Error).message});}
    },400);
    return()=>{active=false;clearTimeout(timer);};
  },[selected?.id,selected?.status,text,year,campus,token,validDraft,draftKey]);
  async function load(){
    const result=await api<Listing>(`/admin/crawler/utc/items?state=${state}&page=${page}`,{headers});
    setListing(result);
  }
  useEffect(()=>{
    let cancelled=false;let timer:ReturnType<typeof setTimeout>;
    async function poll(){
      try{
        const result=await api<Listing>(`/admin/crawler/utc/items?state=${state}&page=${page}`,{headers:{Authorization:`Bearer ${token}`}});
        if(!cancelled){setListing(result);setLoadError('');}
      }catch(e){if(!cancelled)setLoadError((e as Error).message);}
      finally{if(!cancelled)timer=setTimeout(poll,4000);}
    }
    setListing(undefined);poll();
    return()=>{cancelled=true;clearTimeout(timer);};
  },[token,state,page]);
  useEffect(()=>{
    if(!selected||selected.status!=='approving')return;
    let cancelled=false;let timer:ReturnType<typeof setTimeout>;
    const id=selected.id;
    async function poll(){
      try{
        const item=await api<Detail>(`/admin/crawler/utc/items/${id}`,{headers:{Authorization:`Bearer ${token}`}});
        if(cancelled)return;
        setSelected(item);
        if(item.status!=='approving'){
          if(['published','unchanged'].includes(item.status)){
            setNotice(item.status==='unchanged'?'Nội dung đã có trong RAG, đã bỏ qua bản trùng.':'Đã duyệt và thêm nội dung vào tài liệu RAG.');
            completion.current().catch(()=>{});
          }
          return;
        }
      }catch(e){if(!cancelled)setError((e as Error).message);}
      if(!cancelled)timer=setTimeout(poll,4000);
    }
    timer=setTimeout(poll,1000);
    return()=>{cancelled=true;clearTimeout(timer);};
  },[selected?.id,selected?.status,token]); // eslint-disable-line react-hooks/exhaustive-deps
  async function open(id:string){
    const request=++requestId.current;setOpening(true);setError('');setNotice('');
    try{
      const item=await api<Detail>(`/admin/crawler/utc/items/${id}`,{headers});
      if(request!==requestId.current)return;
      setSelected(item);setTitle(item.title);setText(item.text);setYear(item.year?.toString()||'');setCampus(item.campus||'');setConfirmed(false);
    }catch(e){if(request===requestId.current)setError((e as Error).message);}
    finally{if(request===requestId.current)setOpening(false);}
  }
  async function approve(e:FormEvent){
    e.preventDefault();if(!selected||busy||!validDraft||duplicateCheck?.key!==draftKey||duplicateCheck.error)return;
    setBusy(true);setError('');setNotice('');
    try{
      const result=await api<{status:string;duplicate?:Duplicate}>(`/admin/crawler/utc/items/${selected.id}/approve`,{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({title,text,year:Number(year),campus,confirmed:confirmed||duplicateCheck.duplicate?.status==='ready'})});
      setSelected({...selected,status:result.status,error:null,duplicate:result.duplicate});
      if(result.status==='unchanged')setNotice('Đã bỏ qua bản trùng và liên kết với tài liệu có sẵn. Không thêm tài liệu hoặc tạo embedding mới.');
      await load();
    }catch(e){setError((e as Error).message);}
    finally{setBusy(false);}
  }
  async function reject(){
    if(!selected||busy)return;setBusy(true);setError('');
    try{
      await api(`/admin/crawler/utc/items/${selected.id}/reject`,{method:'POST',headers});
      setSelected({...selected,status:'rejected'});setNotice('Đã bỏ qua bài này. Bạn vẫn có thể xem lại trong mục Đã bỏ qua.');await load();
    }catch(e){setError((e as Error).message);}
    finally{setBusy(false);}
  }
  const readOnly=!!selected&&['approving','published','unchanged'].includes(selected.status);
  const checked=duplicateCheck?.key===draftKey;
  const duplicate=readOnly?selected?.duplicate:checked?duplicateCheck?.duplicate:undefined;
  const duplicateReady=duplicate?.status==='ready';
  return <div className="crawler-review">
    <aside className="crawler-review-list" aria-labelledby="crawler-list-title">
    <h3 id="crawler-list-title">Danh sách bài đã thu thập</h3>
    <label>Hiển thị <select value={state} onChange={e=>{setState(e.target.value);setPage(1);}}>
      <option value="pending">Chờ duyệt</option><option value="published">Đã thêm vào RAG</option><option value="rejected">Đã bỏ qua</option><option value="all">Tất cả</option>
    </select></label>
    {loadError&&<p className="error" role="alert">{loadError}</p>}
    {!listing?<p role="status">Đang tải danh sách…</p>:<>
      <p>{listing.total} bài · Chỉ hiển thị phiên bản được thu thập gần nhất của mỗi bài.</p>
      {!listing.items.length&&<p className="muted">Chưa có bài trong mục này. Bấm “Lấy dữ liệu UTC ngay” để thu thập bài mới.</p>}
      <div className="crawler-candidates">{listing.items.map(item=><button
        className={`crawler-candidate${selected?.id===item.id?' is-selected':''}`} key={item.id}
        type="button" aria-pressed={selected?.id===item.id} aria-controls="crawler-detail"
        disabled={busy||opening} onClick={()=>open(item.id)}>
        <strong>{item.title}</strong><span>{labels[item.status]||item.status} · {item.year||'Chưa rõ năm'} · {item.campus==='hanoi'?'Hà Nội':item.campus==='hcm'?'TP. HCM':'Chưa rõ cơ sở'}</span>
        {item.preview&&<span className="muted crawler-candidate-preview">{item.preview}…</span>}
        {item.duplicate&&<small>{item.duplicate.reason==='near_content'?'Nội dung gần trùng với':'Nội dung trùng với'} “{item.duplicate.title}”.</small>}
        {!!item.reasons.length&&<small>{item.reasons.map(r=>reasonLabels[r]||r).join(' · ')}</small>}
        {item.error&&<span className="error">{item.error}</span>}
      </button>)}</div>
      {(page>1||listing.total>listing.page_size)&&<div className="row-actions">
        <button type="button" disabled={page===1} onClick={()=>setPage(page-1)}>Trang trước</button><span>Trang {page}</span>
        <button type="button" disabled={page*listing.page_size>=listing.total} onClick={()=>setPage(page+1)}>Trang sau</button>
      </div>}
    </>}
    </aside>
    <section className="crawler-review-detail" id="crawler-detail" aria-labelledby="crawler-detail-title" aria-busy={opening}>
    <h3 id="crawler-detail-title" ref={editorHeading} tabIndex={-1}>Xem & duyệt tài liệu</h3>
    {error&&<p className="error" role="alert">{error}</p>}{notice&&<p className="notice" role="status">{notice}</p>}
    {opening?<p role="status">Đang tải nội dung tài liệu…</p>:selected?<form className="crawler-editor" onSubmit={approve}>
      <h4>{selected.title}</h4>
      <a href={selected.url} target="_blank" rel="noreferrer">Mở bài gốc trên UTC ↗</a>
      {selected.reasons.includes('ocr_failed')&&<p className="error" role="alert">Không đọc được chữ trong ảnh bằng OCR. Sau khi kiểm tra cấu hình OCR_MODEL và hạn mức Gemini, bật “Đọc cả ảnh và PDF scan (OCR)” cùng “Kiểm tra lại bài đã có” rồi chạy lấy dữ liệu lại. Mở lại bài để xem nội dung mới.</p>}
      {selected.reasons.includes('needs_ocr')&&<p className="notice">Bài có nội dung trong ảnh. Bật “Đọc cả ảnh và PDF scan (OCR)” cùng “Kiểm tra lại bài đã có” rồi chạy lấy dữ liệu lại để trích xuất văn bản.</p>}
      {selected.assets.filter(a=>a.error).map(asset=><p className="error" role="alert" key={asset.url}>{asset.error}</p>)}
      {duplicate&&<p className="notice">{duplicate.reason==='near_content'?'Nội dung gần trùng với':'Nội dung trùng với'} “{duplicate.title}” trong RAG. {selected.status==='unchanged'?'Đã bỏ qua bản trùng; không tạo thêm embedding.':duplicateReady?'Bấm “Bỏ qua bản trùng” để đóng bài trong hàng chờ, không thêm tài liệu mới.':'Tài liệu hiện có đang ẩn, xử lý hoặc có lỗi. Kiểm tra tài liệu đó trước khi duyệt lại.'}</p>}
      {!!selected.assets.length&&<details><summary>Ảnh và tệp đính kèm ({selected.assets.length})</summary>
        {selected.assets.filter(a=>/^https?:\/\//i.test(a.url)).map((asset,i)=><p key={asset.url}><a href={asset.url} target="_blank" rel="noreferrer">{asset.kind==='image'?'Ảnh':'Tệp'} {i+1} ↗</a></p>)}
      </details>}
      <div className="form-grid">
        <label>Tiêu đề<input required minLength={3} maxLength={300} value={title} disabled={busy||readOnly} onChange={e=>setTitle(e.target.value)}/></label>
        <label>Năm áp dụng<input required type="number" min={2000} max={2100} step={1} value={year} disabled={busy||readOnly} onChange={e=>setYear(e.target.value)}/></label>
        <label>Cơ sở<select required value={campus} disabled={busy||readOnly} onChange={e=>setCampus(e.target.value)}><option value="">Chọn cơ sở</option><option value="hanoi">Hà Nội</option><option value="hcm">TP. Hồ Chí Minh</option></select></label>
      </div>
      <label>Nội dung sẽ đưa vào RAG<textarea required minLength={30} maxLength={2000000} rows={14} value={text} disabled={busy||readOnly} onChange={e=>setText(e.target.value)} placeholder="Kiểm tra hoặc bổ sung văn bản từ bài gốc, ảnh và tệp đính kèm."/></label>
      <details><summary>Văn bản trích xuất ban đầu</summary><pre className="crawler-original">{selected.original_text||'Chưa trích xuất được văn bản. Xem ảnh/tệp gốc để bổ sung nội dung.'}</pre></details>
      {selected.error&&<p className="error" role="alert">{selected.error}</p>}
      {!readOnly&&validDraft&&!checked&&<p role="status">Đang kiểm tra nội dung trùng trong RAG…</p>}
      {!readOnly&&checked&&duplicateCheck?.error&&<p className="error" role="alert">Không kiểm tra được trùng: {duplicateCheck.error}. Chọn lại tài liệu để thử lại.</p>}
      {!readOnly&&!duplicateReady&&<label className="crawler-checkbox"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>Tôi đã đối chiếu nội dung, số liệu, năm và cơ sở với nguồn UTC.</label>}
      <div className="row-actions">
        {!readOnly&&<><button type="submit" className="primary" disabled={busy||!validDraft||!checked||Boolean(duplicateCheck?.error)||Boolean(duplicate&&!duplicateReady)||(!duplicateReady&&!confirmed)}>{duplicateReady?'Bỏ qua bản trùng':'Duyệt & thêm vào tài liệu RAG'}</button><button type="button" disabled={busy} onClick={reject}>Bỏ qua bài này</button></>}
        <button type="button" disabled={busy} onClick={()=>setSelected(undefined)}>Bỏ chọn tài liệu</button>
      </div>
      {readOnly&&<p role="status">{labels[selected.status]}</p>}
    </form>:<div className="crawler-selection-hint"><strong>Chọn một tài liệu ở danh sách bên phải</strong><p>Nội dung sẽ mở tại đây để bạn kiểm tra, chỉnh sửa và duyệt vào RAG.</p></div>}
    </section>
  </div>;
}
