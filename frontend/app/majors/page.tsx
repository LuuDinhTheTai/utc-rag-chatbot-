import Link from 'next/link';
import MajorCatalogue from '../../components/MajorCatalogue';
export default function MajorsPage(){
  return <main className="admin-page"><header className="admin-header"><Link href="/" className="brand"><span className="logo">UTC</span><span>Ngành học<small>ĐẠI HỌC GIAO THÔNG VẬN TẢI</small></span></Link><Link href="/">← Hỏi đáp tuyển sinh</Link><Link href="/admin">Quản trị</Link></header><MajorCatalogue/></main>;
}
