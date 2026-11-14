'use client';

import {useEffect, useRef, useState} from 'react';
import {api, ApiError} from '../lib/api';
import UtcCrawlerReview, {reasonLabels} from './UtcCrawlerReview';

type Item = {url:string; title:string; status:string; reasons:string[]};
type Job = {
  id:string; status:'running'|'stopped'|'completed'|'completed_with_errors'|'failed';
  created_at:string; config:{year:number; ocr:boolean; recheck_existing?:boolean; stop_requested?:boolean}; error:string|null;
  report:{requests:number; items:Item[]; errors:{url?:string; error:string}[]}|null;
};
const statusLabels:Record<string,string> = {
  published:'Đã thêm vào chatbot', unchanged:'Đã có, không thay đổi', review:'Cần kiểm tra',
  outside_selected_year:'Ngoài năm đã chọn', staged:'Đã thu thập, chờ duyệt',
  existing_inactive_or_failed:'Tài liệu đang ẩn hoặc có lỗi',
  skipped_existing:'Đã có — bỏ qua tải lại', rejected:'Đã bỏ qua trước đó', approving:'Đang lập chỉ mục',
};

export default function UtcCrawler({token,onComplete}:{token:string;onComplete:()=>Promise<void>}) {
  const [job,setJob]=useState<Job|null>(null);
  const [year,setYear]=useState(2026), [ocr,setOcr]=useState(false);
  const [recheckExisting,setRecheckExisting]=useState(false);
  const [loading,setLoading]=useState(true), [starting,setStarting]=useState(false);
  const [stopping,setStopping]=useState(false);
  const [error,setError]=useState('');
  const completion=useRef(onComplete);
  completion.current=onComplete;

  useEffect(()=>{
    let cancelled=false;
    let previous:Job|null=null;
    let timer:ReturnType<typeof setTimeout>;
    async function poll(){
      try {
        const latest=await api<Job|null>('/admin/crawler/utc',{headers:{Authorization:`Bearer ${token}`}});
        if(cancelled)return;
        setJob(latest);setError('');
        if(previous?.id===latest?.id&&previous?.status==='running'&&latest?.status!=='running'){
          completion.current().catch(()=>{});
        }
        previous=latest;
      } catch(e){if(!cancelled)setError((e as Error).message);}
      finally {
        if(!cancelled){setLoading(false);timer=setTimeout(poll,4000);}
      }
    }
    setLoading(true);setJob(null);
    poll();
    return()=>{cancelled=true;clearTimeout(timer);};
  },[token]);

  async function start(){
    if(starting||job?.status==='running')return;
    setStarting(true);setError('');
    try {
      const next=await api<Job>('/admin/crawler/utc',{
        method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},
        body:JSON.stringify({year,ocr,recheck_existing:recheckExisting}),
      });
      setJob(next);
    } catch(e){
      setError((e as Error).message);
      if(e instanceof ApiError&&e.status===409){
        try{setJob(await api<Job|null>('/admin/crawler/utc',{headers:{Authorization:`Bearer ${token}`}}));}catch{/* Next poll retries. */}
      }
    } finally {setStarting(false);}
  }
  async function stop(){
    if(!job||job.status!=='running'||job.config.stop_requested||stopping)return;
    setStopping(true);setError('');
    try {
      setJob(await api<Job>(`/admin/crawler/utc/${job.id}/stop`,{
        method:'POST',headers:{Authorization:`Bearer ${token}`},
      }));
    } catch(e){setError((e as Error).message);}
    finally {setStopping(false);}
  }
  const running=job?.status==='running';
  const stopRequested=running&&job.config.stop_requested;
  const items=job?.report?.items||[];
  const disabled=loading||starting||running;
  return <section className="panel utc-crawler" aria-labelledby="utc-crawler-title">
    <h2 id="utc-crawler-title">Lấy dữ liệu tuyển sinh từ UTC</h2>
    <p>Tự lấy bài từ cổng tuyển sinh chính thức vào danh sách chờ duyệt. Bạn xem, chỉnh sửa và duyệt nội dung trước khi thêm vào tài liệu RAG. Mỗi lượt kiểm tra tối đa 10 bài.</p>
    <div className="crawler-controls">
      <label>Năm tuyển sinh<select value={year} disabled={disabled} onChange={e=>setYear(Number(e.target.value))}>
        {Array.from({length:5},(_,i)=>new Date().getFullYear()+1-i).map(y=><option key={y} value={y}>{y}</option>)}
      </select></label>
      <label className="crawler-checkbox"><input type="checkbox" checked={ocr} disabled={disabled} onChange={e=>setOcr(e.target.checked)}/>Đọc cả ảnh và PDF scan (OCR)</label>
      <label className="crawler-checkbox"><input type="checkbox" checked={recheckExisting} disabled={disabled} onChange={e=>setRecheckExisting(e.target.checked)}/>Kiểm tra lại bài đã có</label>
      <button className="primary" type="button" disabled={disabled} onClick={start}>
        {loading?'Đang kiểm tra…':starting?'Đang bắt đầu…':running?'Đang lấy dữ liệu…':'Lấy dữ liệu UTC ngay'}
      </button>
      {running&&<button type="button" disabled={stopping||stopRequested} onClick={stop}>
        {stopping?'Đang gửi yêu cầu…':stopRequested?'Đang chờ dừng…':'Dừng crawl'}
      </button>}
    </div>
    {stopRequested&&<p role="status">Đã yêu cầu dừng. Bài đang crawl sẽ được xử lý và lưu xong, bao gồm ảnh/PDF đính kèm; sau đó hệ thống không lấy bài tiếp theo.</p>}
    <p className="muted">Mặc định bỏ qua các URL đã thu thập hoặc đã có trong tài liệu RAG. Bật “Kiểm tra lại bài đã có” nếu muốn tìm bản cập nhật hoặc đọc lại bằng OCR. Mỗi lần tải cách nhau ít nhất 10 giây theo quy định UTC; OCR và bước thêm vào RAG sử dụng hạn mức Gemini.</p>
    {error&&<p className="error" role="alert">{error}</p>}
    {job&&<>
      <div className="crawler-summary" role="status" aria-live="polite">
        <strong>{stopRequested?'Đang hoàn tất bài hiện tại để dừng':running?'Đang lấy dữ liệu':job.status==='stopped'?'Đã dừng — các bài đã thu thập được giữ lại':job.status==='completed'?'Đã hoàn tất':job.status==='completed_with_errors'?'Đã kết thúc, có lỗi cần kiểm tra':'Lượt lấy dữ liệu bị gián đoạn'}</strong>
        <span>Năm {job.config.year} · {job.report?.requests||0} lần tải · {items.filter(i=>i.status!=='skipped_existing').length} bài đã xử lý · {items.filter(i=>i.status==='skipped_existing').length} bài đã có được bỏ qua</span>
        <span>{items.filter(i=>['staged','review'].includes(i.status)).length} bài đã lưu để bạn xem và duyệt</span>
        <small>Bắt đầu: {new Date(job.created_at).toLocaleString('vi-VN')}</small>
      </div>
      {job.error&&<p className="error" role="alert">{job.error}</p>}
      {!!job.report?.errors.length&&<details><summary>Lỗi trong lượt lấy dữ liệu ({job.report.errors.length})</summary>
        {job.report.errors.map((e,i)=><p key={i}>{e.url&&<a href={e.url} target="_blank" rel="noreferrer">Xem trang nguồn</a>} · {e.error}</p>)}
      </details>}
      {!!items.length&&<details><summary>Xem kết quả từng bài ({items.length})</summary>
        {items.map((item,i)=><div className="review-row" key={`${item.url}-${i}`}>
          <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a>
          <p>{statusLabels[item.status]||item.status}</p>
          {!!item.reasons.length&&<small>{item.reasons.map(r=>reasonLabels[r]||r).join(' · ')}</small>}
        </div>)}
      </details>}
    </>}
    <UtcCrawlerReview token={token} onComplete={onComplete}/>
  </section>;
}
