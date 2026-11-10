'use client';

import {FormEvent, useEffect, useRef, useState} from 'react';
import {api} from '../lib/api';

type Duplicate = {id: string; title: string; status: string; reason?: 'content' | 'near_content' | 'source_url'; similarity?: number};
type ExistingSource = Duplicate & {admission_year: number; campus: string};
type Check = {key: string; duplicate: Duplicate | null; existing_sources?: ExistingSource[]; error?: string};

export default function ManualDocumentUpload({token, onComplete}: {token: string; onComplete: () => Promise<void>}) {
  const formRef = useRef<HTMLFormElement>(null);
  const [mode, setMode] = useState<'web' | 'file'>('web');
  const [title, setTitle] = useState('');
  const [url, setUrl] = useState('');
  const [year, setYear] = useState(2026);
  const [campus, setCampus] = useState('hanoi');
  const [file, setFile] = useState<File>();
  const [ocr, setOcr] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [text, setText] = useState('');
  const [previewed, setPreviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [check, setCheck] = useState<Check>();
  const contentValid = text.trim().length >= 30 && text.trim().length <= 2_000_000;
  const scopeValid = Number.isInteger(year) && year >= 2000 && year <= 2100;
  const checkKey = JSON.stringify([text.trim(), year, campus, url.trim()]);
  const checked = check?.key === checkKey;

  useEffect(() => {
    if (!previewed || !contentValid || !scopeValid) return;
    let active = true;
    const timer = setTimeout(async () => {
      try {
        const result = await api<{duplicate: Duplicate | null; existing_sources: ExistingSource[]}>('/admin/documents/check-duplicate', {
          method: 'POST', headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
          body: JSON.stringify({text: text.trim(), admission_year: year, campus, source_url: url.trim()}),
        });
        if (active) setCheck({key: checkKey, duplicate: result.duplicate, existing_sources: result.existing_sources});
      } catch (e) {
        if (active) setCheck({key: checkKey, duplicate: null, error: (e as Error).message});
      }
    }, 400);
    return () => {active = false; clearTimeout(timer);};
  }, [text, year, campus, url, token, previewed, contentValid, scopeValid, checkKey]);

  function resetPreview() {
    setText(''); setPreviewed(false); setCheck(undefined); setError(''); setNotice(''); setWarnings([]);
  }

  async function preview(event: FormEvent) {
    event.preventDefault();
    setBusy(true); resetPreview();
    try {
      const form = new FormData();
      if (mode === 'file') {
        if (!file) throw new Error('Vui lòng chọn tệp cần tải lên.');
        if (file.size > 10 * 1024 * 1024) throw new Error('Tệp tối đa 10 MB.');
        form.append('file', file);
      } else form.append('url', url.trim());
      form.append('admission_year', String(year)); form.append('campus', campus);
      form.append('ocr', String(mode === 'web' && ocr));
      const result = await api<{text: string; chunks: number; duplicate: Duplicate | null; existing_sources: ExistingSource[]; ocr_used: boolean; warnings: string[]}>('/admin/documents/preview', {
        method: 'POST', headers: {Authorization: `Bearer ${token}`}, body: form,
        signal: AbortSignal.timeout(mode === 'web' && ocr ? 900000 : 120000),
      });
      setText(result.text); setPreviewed(true);
      setCheck({key: JSON.stringify([result.text.trim(), year, campus, url.trim()]), duplicate: result.duplicate, existing_sources: result.existing_sources});
      setWarnings(result.warnings || []);
      setNotice(`Đã trích xuất văn bản, dự kiến ${result.chunks} đoạn. ${result.ocr_used ? 'Đã dùng OCR: đối chiếu ảnh/PDF gốc, nhất là bảng và số liệu, trước khi lưu.' : 'Kiểm tra nội dung trước khi lưu.'}`);
    } catch (e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }

  async function save() {
    if (!formRef.current?.reportValidity() || !checked || check?.duplicate || check?.error || !contentValid || !scopeValid) return;
    setBusy(true); setError(''); setNotice('');
    try {
      if (title.trim().length < 3) throw new Error('Tiêu đề cần ít nhất 3 ký tự.');
      const metadata = JSON.stringify({title: title.trim(), source_url: url.trim(), admission_year: year, campus, text: text.trim()});
      if (mode === 'file') {
        if (!file) throw new Error('Vui lòng chọn tệp cần tải lên.');
        const form = new FormData(); form.append('metadata', metadata); form.append('file', file);
        await api('/admin/documents/upload', {method: 'POST', headers: {Authorization: `Bearer ${token}`}, body: form});
      } else {
        await api('/admin/documents', {method: 'POST', headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'}, body: metadata});
      }
      resetPreview(); setTitle(''); setUrl(''); setFile(undefined); formRef.current?.reset();
      setNotice('Đã gửi tài liệu để lập chỉ mục. Danh sách tự cập nhật mỗi 10 giây.');
      await onComplete();
    } catch (e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }

  return <section className="panel manual-upload">
    <h2>Thêm tài liệu thủ công</h2>
    <p className="muted">Chọn nguồn tài liệu, xem trước nội dung và kiểm tra trùng trước khi thêm vào kho tri thức.</p>
    {error && <div className="error" role="alert">{error}</div>}
    {notice && <div className="notice" role="status">{notice}</div>}
    <form ref={formRef} onSubmit={preview}>
      <fieldset disabled={busy} className="manual-upload-fields">
        <legend>Nguồn tài liệu</legend>
        <div className="document-source-options">
          <label className={mode === 'web' ? 'is-selected' : ''}>
            <input type="radio" name="document-source" value="web" checked={mode === 'web'} onChange={() => {setMode('web'); setFile(undefined); setUrl(''); resetPreview();}}/>
            <span><strong>Tải từ web</strong><small>Đọc bài viết, ảnh và PDF đính kèm từ đường dẫn UTC.</small></span>
          </label>
          <label className={mode === 'file' ? 'is-selected' : ''}>
            <input type="radio" name="document-source" value="file" checked={mode === 'file'} onChange={() => {setMode('file'); setFile(undefined); setUrl(''); resetPreview();}}/>
            <span><strong>Tải file lên</strong><small>Chọn tài liệu PDF, TXT hoặc Markdown từ máy tính.</small></span>
          </label>
        </div>
        <div className="form-grid">
          <label>Tiêu đề<input required minLength={3} maxLength={300} value={title} onChange={e => setTitle(e.target.value)}/></label>
          <label>Năm tuyển sinh<input type="number" min={2000} max={2100} step={1} required value={year || ''} onChange={e => setYear(Number(e.target.value))}/></label>
          <label>Cơ sở<select value={campus} onChange={e => setCampus(e.target.value)}><option value="hanoi">Hà Nội</option><option value="hcm">TP. Hồ Chí Minh</option></select></label>
          <label>{mode === 'web' ? 'URL nguồn chính thức' : 'URL nguồn chính thức (không bắt buộc)'}<input type="url" required={mode === 'web'} maxLength={2000} placeholder="https://tuyensinh.utc.edu.vn/…" value={url} onChange={e => {setUrl(e.target.value); if (mode === 'web') resetPreview();}}/></label>
        </div>
        {mode === 'web' && <div className="manual-ocr-option">
          <label><input type="checkbox" checked={ocr} onChange={e => {setOcr(e.target.checked); resetPreview();}}/>Đọc cả ảnh và PDF scan (OCR)</label>
          <p className="muted">Dùng Gemini đọc ảnh trong bài và PDF scan đính kèm, tương tự crawler. Có thể nhập URL ảnh/PDF trực tiếp. OCR có thể mất vài phút; hãy đối chiếu kết quả trước khi lưu.</p>
        </div>}
        {mode === 'file' && <label className="upload">Chọn tệp (tối đa 10 MB)<input type="file" required accept=".pdf,.txt,.md" onChange={e => {setFile(e.target.files?.[0]); resetPreview();}}/><small>PDF cần có văn bản; tệp TXT và Markdown dùng mã hóa UTF-8. Tệp gốc được lưu khi xác nhận.</small></label>}
        <p className="muted">Kiểm tra cả URL nguồn và nội dung trong cùng năm/cơ sở. URL khác cách viết hoặc có tham số tracking vẫn được đối chiếu.</p>
        <button type="submit">{busy ? mode === 'web' && ocr ? 'Đang đọc web và OCR…' : 'Đang xử lý…' : 'Trích xuất & xem trước'}</button>
      </fieldset>
    </form>
    {previewed && <div className="preview">
      {warnings.length > 0 && <div className="error" role="alert"><strong>Nội dung có thể chưa đầy đủ:</strong><ul>{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
      <label>Nội dung đã trích xuất<textarea disabled={busy} value={text} maxLength={2_000_000} onChange={e => setText(e.target.value)} rows={12}/></label>
      <div role="status" aria-live="polite">
        {!contentValid ? <p className="error">Nội dung cần từ 30 đến 2.000.000 ký tự.</p>
          : !scopeValid ? <p className="error">Chọn năm tuyển sinh hợp lệ để kiểm tra trùng.</p>
          : !checked ? <p className="muted">Đang kiểm tra trùng…</p>
          : check?.error ? <p className="error">Không kiểm tra được trùng: {check.error} Hãy trích xuất lại để thử lại.</p>
          : check?.duplicate ? <p className="error">{check.duplicate.reason === 'source_url' ? 'URL nguồn đã có trong RAG ở tài liệu' : check.duplicate.reason === 'near_content' ? 'Nội dung gần trùng với' : 'Nội dung trùng với'} “{check.duplicate.title}” trong năm {year}, cơ sở {campus === 'hanoi' ? 'Hà Nội' : 'TP. Hồ Chí Minh'}. Tài liệu sẽ không được thêm lại.</p>
          : check?.existing_sources?.length ? <div className="notice">URL nguồn này đã có trong RAG ở phạm vi khác:<ul>{check.existing_sources.map(source => <li key={source.id}>{source.title} · {source.admission_year} · {source.campus === 'hanoi' ? 'Hà Nội' : 'TP. Hồ Chí Minh'}</li>)}</ul>Bạn đang chọn năm {year}, cơ sở {campus === 'hanoi' ? 'Hà Nội' : 'TP. Hồ Chí Minh'}. Kiểm tra lại phạm vi trước khi thêm.</div>
          : <p className="notice">Không phát hiện URL nguồn hoặc nội dung trùng trong năm và cơ sở đã chọn.</p>}
      </div>
      <button className="primary" disabled={busy || !contentValid || !scopeValid || !checked || Boolean(check?.duplicate) || Boolean(check?.error)} onClick={save}>Xác nhận & lập chỉ mục</button>
    </div>}
  </section>;
}
