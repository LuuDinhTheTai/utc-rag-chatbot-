export const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${path}`, {...init, signal: AbortSignal.timeout(120000)});
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const labels: Record<string, string> = {admission_code: 'Mã xét tuyển', major_code: 'Mã ngành', name: 'Tên ngành', program_name: 'Tên chương trình', quota: 'Chỉ tiêu', methods: 'Phương thức', subject_groups: 'Tổ hợp môn', title: 'Tiêu đề', source_url: 'URL nguồn', admission_year: 'Năm tuyển sinh', campus: 'Cơ sở', text: 'Nội dung', category: 'Loại tài liệu'};
    const detail = body?.detail;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map((item: {loc?: (string | number)[]; msg?: string; type?: string; ctx?: Record<string, number>}) => {
          const field = String(item.loc?.at(-1) || '');
          let reason = item.msg || 'Giá trị không hợp lệ';
          if (item.type === 'string_too_short') reason = `Cần ít nhất ${item.ctx?.min_length} ký tự.`;
          if (item.type === 'string_too_long') reason = `Tối đa ${item.ctx?.max_length} ký tự.`;
          if (item.type === 'missing') reason = 'Không được bỏ trống.';
          if (item.type === 'greater_than_equal') reason = `Phải từ ${item.ctx?.ge} trở lên.`;
          if (item.type === 'less_than_equal') reason = `Không được vượt quá ${item.ctx?.le}.`;
          if (item.type === 'int_type' || item.type === 'int_parsing' || item.type === 'int_from_float') reason = 'Phải là số nguyên.';
          return `${labels[field] || field || 'Dữ liệu'}: ${reason}`;
        }).join(' ') : '';
    throw new Error(message || `Yêu cầu thất bại (${response.status}).`);
  }
  return body as T;
}
export type Source = {id: string; citation: number; title: string; source_url: string; content: string; admission_year: number; campus: string};
export type Message = {id: string; role: 'user' | 'assistant'; content: string; question?: string; sources?: Source[]; supported?: boolean; latency_ms?: number};
